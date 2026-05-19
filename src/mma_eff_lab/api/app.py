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
    "pit_fighter_features",
    "pit_matchup_features",
    "warehouse_quality",
}
ALLOWED_COMMANDS = {
    "download-ufcstats": ["download-ufcstats"],
    "parse-ufcstats": ["parse-ufcstats"],
    "build-warehouse": ["build-warehouse"],
    "build-features": ["build-features"],
    "make-reports": ["make-reports"],
    "full-pipeline": ["full-pipeline"],
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
def table(name: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    if name not in ALLOWED_TABLES:
        raise HTTPException(status_code=404, detail="Table not allowed")
    if not settings.warehouse_path.exists():
        raise HTTPException(status_code=404, detail="Warehouse not found")
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        if not _table_exists(conn, name):
            raise HTTPException(status_code=404, detail="Table not found")
        total = conn.execute(f"select count(*) from {name}").fetchone()[0]
        rows = conn.execute(f"select * from {name} limit ? offset ?", [limit, offset]).fetchdf()
    return {"name": name, "total": total, "limit": limit, "offset": offset, "rows": _records(rows)}


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


def _records(frame: Any) -> list[dict[str, Any]]:
    frame = frame.where(frame.notna(), None)
    return frame.to_dict("records")
