from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from mma_eff_lab.config import ensure_data_dirs, get_settings
from mma_eff_lab.warehouse.build import table_counts

settings = get_settings()
ensure_data_dirs(settings)

app = FastAPI(title="MMA Market Efficiency Lab")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
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
    "full-pipeline": ["full-pipeline"],
    "full-pipeline-sherdog-major": ["full-pipeline-sherdog-major"],
}
_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}


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
) -> dict[str, Any]:
    if name not in ALLOWED_TABLES:
        raise HTTPException(status_code=404, detail="Table not allowed")
    return _table_response(name, limit, offset, {"source": source, "promotion": promotion})


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
    columns = {
        row[1]
        for row in conn.execute(f"pragma table_info('{name}')").fetchall()
    }
    clauses = []
    params = []
    for column, value in filters.items():
        if not value or column not in columns:
            continue
        if column in {"promotion", "reason", "details"}:
            clauses.append(f"{column} ilike ?")
            params.append(f"%{value}%")
        else:
            clauses.append(f"{column} = ?")
            params.append(value)
    return (f" where {' and '.join(clauses)}" if clauses else "", params)


def _records(frame: Any) -> list[dict[str, Any]]:
    frame = frame.where(frame.notna(), None)
    return frame.to_dict("records")
