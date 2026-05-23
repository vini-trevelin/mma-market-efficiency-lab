from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mma_eff_lab.config import ensure_data_dirs, get_settings
from mma_eff_lab.warehouse.build import (
    EMPTY_TABLE_SCHEMAS,
    MANUAL_OVERRIDE_TABLE,
    table_counts,
)

settings = get_settings()
ensure_data_dirs(settings)

app = FastAPI(title="MMA Market Efficiency Lab")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

ALLOWED_TABLES = {
    "events",
    "fights",
    "fight_participants",
    "fighters",
    "fighter_fight_stats",
    "source_events",
    "source_fights",
    "source_fight_participants",
    "source_fighters",
    MANUAL_OVERRIDE_TABLE,
    "fighter_identity_links",
    "parse_quarantine",
    "pit_fighter_features",
    "pit_matchup_features",
    "warehouse_quality",
    "audit_summary",
    "audit_checks",
    "audit_coverage",
    "audit_missingness",
    "audit_identity",
    "audit_pit",
    "analysis_event_audit",
    "analysis_fight_audit",
    "analysis_fighter_audit",
    "analysis_identity_review",
    "analysis_pit_audit",
}
AUDIT_TABLES = {
    "summary": "audit_summary",
    "checks": "audit_checks",
    "coverage": "audit_coverage",
    "identity": "audit_identity",
    "quarantine": "parse_quarantine",
}
ALLOWED_COMMANDS = {
    "download-ufcstats": ["download-ufcstats"],
    "download-sherdog": ["download-sherdog"],
    "parse-ufcstats": ["parse-ufcstats"],
    "parse-sherdog": ["parse-sherdog"],
    "build-warehouse": ["build-warehouse"],
    "build-features": ["build-features"],
    "make-reports": ["make-reports"],
    "validate-warehouse": ["validate-warehouse"],
    "apply-identity-overrides": ["apply-identity-overrides"],
    "full-pipeline": ["full-pipeline"],
    "full-pipeline-sherdog-major": ["full-pipeline-sherdog-major"],
    "repair-sherdog-major": ["repair-sherdog-major"],
}
_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}


class IdentityDecisionRequest(BaseModel):
    source: Literal["sherdog"] = "sherdog"
    source_fighter_id: str
    target_source: Literal["ufcstats"] = "ufcstats"
    target_source_fighter_id: str | None = None
    decision: Literal["approved", "rejected", "accepted_unresolved"]
    note: str | None = None
    apply: bool = True


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "warehouse_exists": settings.warehouse_path.exists(),
        "warehouse_path": str(settings.warehouse_path),
        "table_counts": table_counts(settings.warehouse_path),
    }


@app.get("/tables/{name}")
def table(
    name: str,
    limit: int = 100,
    offset: int = 0,
    source: str | None = None,
    promotion: str | None = None,
    event_id: str | None = None,
    fight_id: str | None = None,
    fighter_id: str | None = None,
    source_fight_id: str | None = None,
    source_fighter_id: str | None = None,
    status: str | None = None,
    link_method: str | None = None,
    review_status: str | None = None,
    decision_status: str | None = None,
    has_candidate: str | None = None,
    has_anomaly: str | None = None,
) -> dict[str, Any]:
    if name not in ALLOWED_TABLES:
        raise HTTPException(status_code=404, detail="Table not allowed")
    return _table_response(
        name,
        limit,
        offset,
        {
            "source": source,
            "promotion": promotion,
            "event_id": event_id,
            "fight_id": fight_id,
            "fighter_id": fighter_id,
            "source_fight_id": source_fight_id,
            "source_fighter_id": source_fighter_id,
            "status": status,
            "link_method": link_method,
            "review_status": review_status,
            "decision_status": decision_status,
            "has_candidate": has_candidate,
            "has_anomaly": has_anomaly,
        },
    )


@app.get("/identity/review")
def identity_review(
    source: str | None = "sherdog",
    review_status: str | None = None,
    has_candidate: str | None = None,
    decision_status: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    return _table_response(
        "analysis_identity_review",
        limit,
        offset,
        {
            "source": source,
            "review_status": review_status,
            "has_candidate": has_candidate,
            "decision_status": decision_status,
        },
    )


@app.get("/identity/candidates")
def identity_candidates(source_fighter_id: str, q: str | None = None) -> dict[str, Any]:
    if not settings.warehouse_path.exists():
        raise HTTPException(status_code=404, detail="Warehouse not found")
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        if not _table_exists(conn, "analysis_identity_review"):
            raise HTTPException(status_code=404, detail="Run validate-warehouse first")
        source_row = conn.execute(
            """
            select *
            from analysis_identity_review
            where source = 'sherdog' and source_fighter_id = ?
            """,
            [source_fighter_id],
        ).fetchdf()
        if source_row.empty:
            raise HTTPException(status_code=404, detail="Sherdog fighter not found")
        source_detail = conn.execute(
            """
            select
              sf.*,
              ir.canonical_fighter_id,
              ir.review_status,
              ir.link_method,
              ir.match_reason,
              ir.manual_note,
              ir.rejected_pair_count,
              af.fight_count,
              af.ufc_fight_count,
              af.sherdog_fight_count,
              af.first_fight_date,
              af.last_fight_date
            from source_fighters sf
            join analysis_identity_review ir
              on ir.source = sf.source
             and ir.source_fighter_id = sf.source_fighter_id
            left join analysis_fighter_audit af
              on af.fighter_id = ir.canonical_fighter_id
            where sf.source = 'sherdog' and sf.source_fighter_id = ?
            """,
            [source_fighter_id],
        ).fetchdf()
        suggestions = conn.execute(
            """
            with source_row as (
              select *
              from analysis_identity_review
              where source = 'sherdog' and source_fighter_id = ?
            )
            select
              u.source_fighter_id as target_source_fighter_id,
              u.canonical_fighter_id as target_canonical_fighter_id,
              sf.full_name,
              sf.dob,
              sf.url,
              case
                when u.exact_name_key = s.exact_name_key and sf.dob = s.dob then 'exact_name_dob'
                when u.cleaned_name_key = s.cleaned_name_key
                  and sf.dob = s.dob then 'cleaned_name_dob'
                else 'search'
              end as candidate_reason,
              mo.decision as manual_decision,
              mo.note as manual_note,
              af.fight_count,
              af.ufc_fight_count,
              af.sherdog_fight_count,
              af.first_fight_date,
              af.last_fight_date
            from source_row s
            join fighter_identity_links u
              on u.source = 'ufcstats'
            join source_fighters sf
              on sf.source = 'ufcstats'
             and sf.source_fighter_id = u.source_fighter_id
             and s.dob is not null
             and sf.dob = s.dob
             and (
               u.exact_name_key = s.exact_name_key
               or u.cleaned_name_key = s.cleaned_name_key
             )
            left join fighter_identity_manual_overrides mo
              on mo.source = 'sherdog'
             and mo.source_fighter_id = s.source_fighter_id
             and mo.target_source = 'ufcstats'
             and mo.target_source_fighter_id = u.source_fighter_id
            left join analysis_fighter_audit af
              on af.fighter_id = u.canonical_fighter_id
            where coalesce(mo.decision, '') != 'rejected'
            order by candidate_reason, sf.full_name
            """,
            [source_fighter_id],
        ).fetchdf()
        search_results = pd.DataFrame()
        normalized_query = _normalize_name(q or "")
        if q:
            search_results = conn.execute(
                """
                with source_row as (
                  select *
                  from analysis_identity_review
                  where source = 'sherdog' and source_fighter_id = ?
                )
                select
                  u.source_fighter_id as target_source_fighter_id,
                  u.canonical_fighter_id as target_canonical_fighter_id,
                  sf.full_name,
                  sf.dob,
                  sf.url,
                  'manual_search' as candidate_reason,
                  mo.decision as manual_decision,
                  mo.note as manual_note,
                  af.fight_count,
                  af.ufc_fight_count,
                  af.sherdog_fight_count,
                  af.first_fight_date,
                  af.last_fight_date
                from source_row s
                join fighter_identity_links u
                  on u.source = 'ufcstats'
                join source_fighters sf
                  on sf.source = 'ufcstats'
                 and sf.source_fighter_id = u.source_fighter_id
                left join fighter_identity_manual_overrides mo
                  on mo.source = 'sherdog'
                 and mo.source_fighter_id = s.source_fighter_id
                 and mo.target_source = 'ufcstats'
                 and mo.target_source_fighter_id = u.source_fighter_id
                left join analysis_fighter_audit af
                  on af.fighter_id = u.canonical_fighter_id
                where coalesce(mo.decision, '') != 'rejected'
                  and (
                    sf.full_name ilike ?
                    or u.cleaned_name_key ilike ?
                  )
                order by sf.full_name
                limit 25
                """,
                [source_fighter_id, f"%{q}%", f"%{normalized_query}%"],
            ).fetchdf()
        rejected_pairs = conn.execute(
            """
            select
              mo.target_source_fighter_id,
              'ufcstats:' || mo.target_source_fighter_id as target_canonical_fighter_id,
              sf.full_name,
              sf.dob,
              sf.url,
              mo.note,
              mo.updated_at_utc
            from fighter_identity_manual_overrides mo
            left join source_fighters sf
              on sf.source = mo.target_source
             and sf.source_fighter_id = mo.target_source_fighter_id
            where mo.source = 'sherdog'
              and mo.source_fighter_id = ?
              and mo.decision = 'rejected'
            order by sf.full_name, mo.target_source_fighter_id
            """,
            [source_fighter_id],
        ).fetchdf()
    return {
        "source_fighter": _records(source_detail)[0],
        "review_row": _records(source_row)[0],
        "suggestions": _records(suggestions),
        "search_results": _records(search_results),
        "rejected_pairs": _records(rejected_pairs),
    }


@app.post("/identity/decisions")
def save_identity_decision(payload: IdentityDecisionRequest) -> dict[str, Any]:
    if not settings.warehouse_path.exists():
        raise HTTPException(status_code=404, detail="Warehouse not found")
    settings.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        _ensure_manual_override_table(conn)
        _validate_identity_source(conn, payload.source, payload.source_fighter_id)
        if payload.decision in {"approved", "rejected"}:
            if not payload.target_source_fighter_id:
                raise HTTPException(
                    status_code=400,
                    detail="target_source_fighter_id is required for approved/rejected decisions",
                )
            _validate_identity_target(
                conn,
                payload.target_source,
                payload.target_source_fighter_id,
            )
        elif payload.target_source_fighter_id:
            raise HTTPException(
                status_code=400,
                detail="accepted_unresolved does not accept a UFC target",
            )
        if payload.decision == "approved":
            conflict = conn.execute(
                f"""
                select target_source_fighter_id
                from {MANUAL_OVERRIDE_TABLE}
                where source = ?
                  and source_fighter_id = ?
                  and decision = 'approved'
                  and target_source_fighter_id != ?
                """,
                [payload.source, payload.source_fighter_id, payload.target_source_fighter_id],
            ).fetchone()
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Clear the existing approved override before approving a "
                        "different UFC target"
                    ),
                )
        elif payload.decision == "accepted_unresolved":
            conflict = conn.execute(
                f"""
                select decision
                from {MANUAL_OVERRIDE_TABLE}
                where source = ?
                  and source_fighter_id = ?
                  and decision = 'approved'
                """,
                [payload.source, payload.source_fighter_id],
            ).fetchone()
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail="Clear the existing approved override before accepting unresolved state",
                )
        existing = conn.execute(
            f"""
            select created_at_utc
            from {MANUAL_OVERRIDE_TABLE}
            where source = ?
              and source_fighter_id = ?
              and target_source = ?
              and (
                (? is null and target_source_fighter_id is null)
                or cast(target_source_fighter_id as varchar) = cast(? as varchar)
              )
            """,
            [
                payload.source,
                payload.source_fighter_id,
                payload.target_source,
                payload.target_source_fighter_id,
                payload.target_source_fighter_id,
            ],
        ).fetchone()
        created_at = existing[0] if existing else now
        conn.execute(
            f"""
            delete from {MANUAL_OVERRIDE_TABLE}
            where source = ?
              and source_fighter_id = ?
              and target_source = ?
              and (
                (? is null and target_source_fighter_id is null)
                or cast(target_source_fighter_id as varchar) = cast(? as varchar)
              )
            """,
            [
                payload.source,
                payload.source_fighter_id,
                payload.target_source,
                payload.target_source_fighter_id,
                payload.target_source_fighter_id,
            ],
        )
        conn.execute(
            f"""
            insert into {MANUAL_OVERRIDE_TABLE} (
              source,
              source_fighter_id,
              target_source,
              target_source_fighter_id,
              decision,
              note,
              created_at_utc,
              updated_at_utc
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                payload.source,
                payload.source_fighter_id,
                payload.target_source,
                payload.target_source_fighter_id,
                payload.decision,
                payload.note,
                created_at,
                now,
            ],
        )
        return _decision_response(
            payload.source,
            payload.source_fighter_id,
            payload.target_source,
            payload.target_source_fighter_id,
            payload.decision,
            payload.note,
            payload.apply,
        )


@app.delete("/identity/decisions")
def delete_identity_decision(
    source: str = "sherdog",
    source_fighter_id: str = "",
    target_source: str = "ufcstats",
    target_source_fighter_id: str | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    if not source_fighter_id:
        raise HTTPException(
            status_code=400,
            detail="source_fighter_id is required",
        )
    if not settings.warehouse_path.exists():
        raise HTTPException(status_code=404, detail="Warehouse not found")
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        _ensure_manual_override_table(conn)
        deleted = conn.execute(
            f"""
            delete from {MANUAL_OVERRIDE_TABLE}
            where source = ?
              and source_fighter_id = ?
              and target_source = ?
              and (
                (? is null and target_source_fighter_id is null)
                or cast(target_source_fighter_id as varchar) = cast(? as varchar)
              )
            returning source
            """,
            [
                source,
                source_fighter_id,
                target_source,
                target_source_fighter_id,
                target_source_fighter_id,
            ],
        ).fetchone()
    if not deleted:
        raise HTTPException(status_code=404, detail="Manual decision not found")
    return _decision_response(
        source,
        source_fighter_id,
        target_source,
        target_source_fighter_id,
        "cleared",
        None,
        apply,
    )


@app.get("/audit/summary")
def audit_summary() -> dict[str, Any]:
    return _table_response("audit_summary", 500, 0, {}, allow_missing=True)


@app.get("/audit/checks")
def audit_checks(
    status: str | None = None, table_name: str | None = None, limit: int = 500, offset: int = 0
) -> dict[str, Any]:
    return _table_response(
        "audit_checks",
        limit,
        offset,
        {"status": status, "table_name": table_name},
        allow_missing=True,
    )


@app.get("/audit/coverage")
def audit_coverage(
    source: str | None = None, promotion: str | None = None, limit: int = 500, offset: int = 0
) -> dict[str, Any]:
    return _table_response(
        "audit_coverage",
        limit,
        offset,
        {"source": source, "promotion": promotion},
        allow_missing=True,
    )


@app.get("/audit/identity")
def audit_identity(
    source: str | None = None, link_method: str | None = None, limit: int = 500, offset: int = 0
) -> dict[str, Any]:
    return _table_response(
        "audit_identity",
        limit,
        offset,
        {"source": source, "link_method": link_method},
        allow_missing=True,
    )


@app.get("/audit/quarantine")
def audit_quarantine(
    reason: str | None = None, promotion: str | None = None, limit: int = 500, offset: int = 0
) -> dict[str, Any]:
    return _table_response(
        "parse_quarantine",
        limit,
        offset,
        {"reason": reason, "promotion": promotion},
        allow_missing=True,
    )


def _table_response(
    name: str,
    limit: int,
    offset: int,
    filters: dict[str, str | None],
    allow_missing: bool = False,
) -> dict[str, Any]:
    if not settings.warehouse_path.exists():
        raise HTTPException(status_code=404, detail="Warehouse not found")
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        if not _table_exists(conn, name):
            if allow_missing:
                return {
                    "name": name,
                    "exists": False,
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "rows": [],
                }
            raise HTTPException(status_code=404, detail="Table not found")
        where_sql, params = _table_filters(conn, name, filters)
        total = conn.execute(f"select count(*) from {name}{where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"select * from {name}{where_sql} limit ? offset ?", [*params, limit, offset]
        ).fetchdf()
    return {
        "name": name,
        "exists": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": _records(rows),
    }


@app.post("/commands/{name}")
def start_command(name: str) -> dict[str, str]:
    if name not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=404, detail="Command not allowed")
    return _start_background_command(name)


def _start_background_command(name: str) -> dict[str, str]:
    if not _lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Another command is running")
    run_id = uuid.uuid4().hex
    log_path = settings.logs_dir / f"{run_id}-{name}.log"
    _runs[run_id] = {
        "run_id": run_id,
        "name": name,
        "status": "running",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "finished_at_utc": None,
        "returncode": None,
        "log_path": str(log_path),
    }
    thread = threading.Thread(target=_run_command, args=(run_id, name, log_path), daemon=True)
    thread.start()
    return {"run_id": run_id, "status": "running"}


@app.get("/commands/{run_id}")
def command_status(run_id: str) -> dict[str, Any]:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    log = Path(run["log_path"])
    data = dict(run)
    data["log"] = log.read_text(encoding="utf-8") if log.exists() else ""
    return data


def _run_command(run_id: str, name: str, log_path: Path) -> None:
    command = [sys.executable, "-m", "mma_eff_lab", *ALLOWED_COMMANDS[name]]
    try:
        with log_path.open("w", encoding="utf-8") as handle:
            process = subprocess.run(
                command,
                cwd=settings.repo_root,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        _runs[run_id]["returncode"] = process.returncode
        _runs[run_id]["status"] = "succeeded" if process.returncode == 0 else "failed"
    finally:
        _runs[run_id]["finished_at_utc"] = datetime.now(UTC).isoformat()
        _lock.release()


def _table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(
        conn.execute(
            "select 1 from information_schema.tables where table_schema='main' and table_name=?",
            [name],
        ).fetchone()
    )


def _table_filters(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    filters: dict[str, str | None],
) -> tuple[str, list[str]]:
    table_info = {
        row[1]: str(row[2]).upper()
        for row in conn.execute(f"pragma table_info('{name}')").fetchall()
    }
    columns = set(table_info)
    clauses = []
    params: list[Any] = []
    for column, value in filters.items():
        if not value or column not in columns:
            continue
        if column in {"promotion", "reason", "details"}:
            clauses.append(f"{column} ilike ?")
            params.append(f"%{value}%")
        elif table_info[column] == "BOOLEAN" and value.lower() in {"true", "false"}:
            clauses.append(f"{column} = ?")
            params.append(value.lower() == "true")
        else:
            clauses.append(f"{column} = ?")
            params.append(value)
    return (f" where {' and '.join(clauses)}" if clauses else "", params)


def _ensure_manual_override_table(conn: duckdb.DuckDBPyConnection) -> None:
    if _table_exists(conn, MANUAL_OVERRIDE_TABLE):
        return
    schema = EMPTY_TABLE_SCHEMAS[MANUAL_OVERRIDE_TABLE]
    column_sql = ", ".join(f"{column} {sql_type}" for column, sql_type in schema.items())
    conn.execute(f"create table {MANUAL_OVERRIDE_TABLE} ({column_sql})")

def _validate_identity_source(
    conn: duckdb.DuckDBPyConnection,
    source: str,
    source_fighter_id: str,
) -> None:
    source_exists = conn.execute(
        """
        select 1 from source_fighters
        where source = ? and source_fighter_id = ?
        """,
        [source, source_fighter_id],
    ).fetchone()
    if not source_exists:
        raise HTTPException(status_code=404, detail="Sherdog fighter not found")


def _validate_identity_target(
    conn: duckdb.DuckDBPyConnection,
    target_source: str,
    target_source_fighter_id: str,
) -> None:
    target_exists = conn.execute(
        """
        select 1 from source_fighters
        where source = ? and source_fighter_id = ?
        """,
        [target_source, target_source_fighter_id],
    ).fetchone()
    if not target_exists:
        raise HTTPException(status_code=404, detail="UFCStats fighter not found")


def _decision_response(
    source: str,
    source_fighter_id: str,
    target_source: str,
    target_source_fighter_id: str | None,
    decision: str,
    note: str | None,
    apply: bool,
) -> dict[str, Any]:
    response = {
        "source": source,
        "source_fighter_id": source_fighter_id,
        "target_source": target_source,
        "target_source_fighter_id": target_source_fighter_id,
        "decision": decision,
        "note": note,
        "apply_status": "skipped",
        "run_id": None,
    }
    if not apply:
        return response
    try:
        started = _start_background_command("apply-identity-overrides")
    except HTTPException as exc:
        if exc.status_code == 409:
            response["apply_status"] = "blocked"
            return response
        raise
    response["apply_status"] = "started"
    response["run_id"] = started["run_id"]
    return response


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _records(frame: Any) -> list[dict[str, Any]]:
    if hasattr(frame, "select_dtypes"):
        datetime_columns = frame.select_dtypes(include=["datetime"]).columns
        for column in datetime_columns:
            frame[column] = frame[column].dt.strftime("%Y-%m-%d")
    frame = frame.astype(object).where(pd.notna(frame), None)
    return frame.to_dict("records")
