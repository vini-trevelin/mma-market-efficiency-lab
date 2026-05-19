from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from mma_eff_lab.config import Settings, ensure_data_dirs, get_settings
from mma_eff_lab.parse.ufcstats import parse_all_cached

TABLES = [
    "events",
    "fights",
    "fight_participants",
    "fighters",
    "fighter_fight_stats",
]


def parse_cached_ufcstats(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    parsed = parse_all_cached(settings.raw_dir)
    parsed_dir = settings.warehouse_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, rows in parsed.items():
        counts[name] = len(rows)
        pd.DataFrame(rows).to_parquet(parsed_dir / f"{name}.parquet", index=False)
    (parsed_dir / "summary.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    return counts


def build_warehouse(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    parsed_dir = settings.warehouse_dir / "parsed"
    if not parsed_dir.exists():
        parse_cached_ufcstats(settings)
    settings.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        for table in TABLES:
            path = parsed_dir / f"{table}.parquet"
            frame = pd.read_parquet(path) if path.exists() else pd.DataFrame()
            _write_table(conn, table, frame)
            counts[table] = len(frame)
        _add_quality_views(conn)
    return counts


def table_counts(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {}
    counts: dict[str, int] = {}
    with duckdb.connect(str(db_path), read_only=True) as conn:
        names = conn.execute(
            "select table_name from information_schema.tables where table_schema='main'"
        ).fetchall()
        for (name,) in names:
            counts[name] = conn.execute(f"select count(*) from {name}").fetchone()[0]
    return counts


def _write_table(conn: duckdb.DuckDBPyConnection, name: str, frame: pd.DataFrame) -> None:
    conn.execute(f"drop table if exists {name}")
    if frame.empty:
        conn.execute(f"create table {name} as select * from frame where false")
        return
    conn.register("frame", frame)
    conn.execute(f"create table {name} as select * from frame")
    conn.unregister("frame")


def _add_quality_views(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        create or replace view warehouse_quality as
        select 'events' as table_name, count(*) as row_count from events
        union all select 'fights', count(*) from fights
        union all select 'fight_participants', count(*) from fight_participants
        union all select 'fighters', count(*) from fighters
        union all select 'fighter_fight_stats', count(*) from fighter_fight_stats
        """
    )
