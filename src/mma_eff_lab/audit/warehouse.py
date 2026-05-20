from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import duckdb
import pandas as pd

from mma_eff_lab.config import Settings, get_settings

AUDIT_TABLES = {
    "audit_summary",
    "audit_checks",
    "audit_coverage",
    "audit_missingness",
    "audit_identity",
    "audit_pit",
}


@dataclass(frozen=True)
class Check:
    status: str
    table_name: str
    check_name: str
    metric_value: float
    threshold: str
    details: str


def validate_warehouse(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    if not settings.warehouse_path.exists():
        raise FileNotFoundError(f"Warehouse not found: {settings.warehouse_path}")
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        summary = _summary(conn)
        coverage = _coverage(conn)
        missingness = _missingness(conn)
        identity = _identity(conn)
        pit = _pit(conn)
        checks = _checks(conn, missingness=missingness, pit=pit)
        _write_audit_table(conn, "audit_summary", summary, _summary_schema())
        _write_audit_table(conn, "audit_checks", checks, _checks_schema())
        _write_audit_table(conn, "audit_coverage", coverage, _coverage_schema())
        _write_audit_table(conn, "audit_missingness", missingness, _missingness_schema())
        _write_audit_table(conn, "audit_identity", identity, _identity_schema())
        _write_audit_table(conn, "audit_pit", pit, _pit_schema())
    return {
        "audit_summary": len(summary),
        "audit_checks": len(checks),
        "audit_coverage": len(coverage),
        "audit_missingness": len(missingness),
        "audit_identity": len(identity),
        "audit_pit": len(pit),
    }


def _summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    now = datetime.now(UTC).isoformat()
    rows = [
        {"section": "run", "metric_name": "validated_at_utc", "metric_value": now, "details": ""},
        {
            "section": "warehouse",
            "metric_name": "warehouse_tables",
            "metric_value": str(_table_count(conn)),
            "details": "main schema table count",
        },
    ]
    for table in [
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
    ]:
        rows.append(
            {
                "section": "row_counts",
                "metric_name": table,
                "metric_value": str(_count(conn, table)),
                "details": "",
            }
        )
    if _table_exists(conn, "events"):
        for row in conn.execute(
            """
            select
              source,
              count(*) as events,
              min(event_date) as first_date,
              max(event_date) as last_date
            from events
            group by source
            order by source
            """
        ).fetchdf().to_dict("records"):
            rows.append(
                {
                    "section": "source_coverage",
                    "metric_name": f"{row['source']}_events",
                    "metric_value": str(row["events"]),
                    "details": f"{row['first_date']} to {row['last_date']}",
                }
            )
    return pd.DataFrame(rows, columns=list(_summary_schema()))


def _coverage(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if not _all_tables_exist(conn, ["events", "fights", "fight_participants"]):
        return pd.DataFrame(columns=list(_coverage_schema()))
    return conn.execute(
        """
        with event_base as (
          select
            e.source,
            e.promotion,
            year(e.event_date) as event_year,
            count(distinct e.event_id) as events,
            count(distinct f.fight_id) as fights,
            count(distinct p.fighter_id) as fighters,
            min(e.event_date) as first_event_date,
            max(e.event_date) as last_event_date
          from events e
          left join fights f using (event_id)
          left join fight_participants p using (fight_id)
          group by e.source, e.promotion, year(e.event_date)
        )
        select
          source,
          promotion,
          event_year,
          events,
          fights,
          fighters,
          first_event_date,
          last_event_date,
          case
            when events = 0 then null
            else round(fights::double / events, 3)
          end as fights_per_event
        from event_base
        order by source, promotion, event_year desc
        """
    ).fetchdf()


def _missingness(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for spec in [
        ("events", ["event_id", "source", "source_event_id", "promotion", "name", "event_date"]),
        (
            "fights",
            ["fight_id", "event_id", "source", "source_fight_id", "method", "round", "time"],
        ),
        (
            "fight_participants",
            ["fight_id", "fighter_id", "opponent_id", "source_fighter_id", "full_name"],
        ),
        ("fighters", ["fighter_id", "full_name", "dob", "height_in", "reach_in", "stance"]),
        ("source_fighters", ["source_fighter_id", "full_name", "dob", "height_in", "weight_lbs"]),
    ]:
        table, columns = spec
        if not _table_exists(conn, table):
            continue
        table_columns = _columns(conn, table)
        group_columns = [column for column in ["source", "promotion"] if column in table_columns]
        for column in columns:
            if column not in table_columns:
                continue
            rows.extend(_missingness_rows(conn, table, column, group_columns))
    return pd.DataFrame(rows, columns=list(_missingness_schema()))


def _identity(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    if not _table_exists(conn, "fighter_identity_links"):
        return pd.DataFrame(columns=list(_identity_schema()))
    return conn.execute(
        """
        select
          source,
          link_method,
          count(*) as fighters,
          sum(case when dob is not null then 1 else 0 end) as with_dob,
          sum(case when dob is null then 1 else 0 end) as missing_dob,
          min(full_name) as sample_name
        from fighter_identity_links
        group by source, link_method
        order by source, link_method
        """
    ).fetchdf()


def _pit(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if _all_tables_exist(conn, ["fight_participants", "pit_fighter_features"]):
        participant_count = _count(conn, "fight_participants")
        pit_count = _count(conn, "pit_fighter_features")
        rows.append(
            {
                "check_name": "pit_rows_match_participants",
                "status": "pass" if participant_count == pit_count else "fail",
                "metric_value": abs(participant_count - pit_count),
                "threshold": "0",
                "details": f"participants={participant_count} pit_rows={pit_count}",
            }
        )
        mismatches = conn.execute(
            """
            select count(*) from (
              select
                pit.fight_id,
                pit.fighter_id,
                pit.prior_fights,
                sum(
                  case
                    when hist_event.event_date < pit.event_date then 1
                    else 0
                  end
                ) as expected_prior_fights
              from pit_fighter_features pit
              left join fight_participants hist
                on hist.fighter_id = pit.fighter_id
              left join events hist_event
                on hist_event.event_id = hist.event_id
              group by pit.fight_id, pit.fighter_id, pit.prior_fights
              having pit.prior_fights != sum(
                case
                  when hist_event.event_date < pit.event_date then 1
                  else 0
                end
              )
            )
            """
        ).fetchone()[0]
        rows.append(
            {
                "check_name": "pit_prior_fights_no_leakage",
                "status": "pass" if mismatches == 0 else "fail",
                "metric_value": mismatches,
                "threshold": "0",
                "details": (
                    "prior_fights must equal historical fights with event_date "
                    "< current event_date"
                ),
            }
        )
    return pd.DataFrame(rows, columns=list(_pit_schema()))


def _checks(
    conn: duckdb.DuckDBPyConnection, missingness: pd.DataFrame, pit: pd.DataFrame
) -> pd.DataFrame:
    checks: list[Check] = []
    checks.extend(_duplicate_checks(conn))
    checks.extend(_orphan_checks(conn))
    checks.extend(_required_missingness_checks(missingness))
    checks.extend(_identity_checks(conn))
    checks.extend(_quarantine_checks(conn))
    checks.extend(
        Check(
            status=row["status"],
            table_name="pit_fighter_features",
            check_name=row["check_name"],
            metric_value=float(row["metric_value"]),
            threshold=row["threshold"],
            details=row["details"],
        )
        for row in pit.to_dict("records")
    )
    return pd.DataFrame([check.__dict__ for check in checks], columns=list(_checks_schema()))


def _duplicate_checks(conn: duckdb.DuckDBPyConnection) -> list[Check]:
    specs = [
        ("events", ["event_id"]),
        ("source_events", ["source", "source_event_id"]),
        ("fights", ["fight_id"]),
        ("source_fights", ["source", "source_fight_id"]),
        ("fight_participants", ["fight_id", "fighter_id"]),
        ("source_fight_participants", ["source", "source_fight_id", "source_fighter_id"]),
        ("fighters", ["fighter_id"]),
        ("fighter_identity_links", ["source", "source_fighter_id"]),
    ]
    checks = []
    for table, keys in specs:
        if not _table_exists(conn, table):
            continue
        duplicates = _duplicate_count(conn, table, keys)
        checks.append(
            Check(
                status="pass" if duplicates == 0 else "fail",
                table_name=table,
                check_name=f"unique_{'_'.join(keys)}",
                metric_value=float(duplicates),
                threshold="0",
                details=f"duplicate key groups for {', '.join(keys)}",
            )
        )
    return checks


def _orphan_checks(conn: duckdb.DuckDBPyConnection) -> list[Check]:
    specs = [
        (
            "fights",
            "fight_event_fk",
            """
            select count(*) from fights f
            left join events e on e.event_id = f.event_id
            where e.event_id is null
            """,
        ),
        (
            "fight_participants",
            "participant_fight_fk",
            """
            select count(*) from fight_participants p
            left join fights f on f.fight_id = p.fight_id
            where f.fight_id is null
            """,
        ),
        (
            "fight_participants",
            "participant_fighter_fk",
            """
            select count(*) from fight_participants p
            left join fighters f on f.fighter_id = p.fighter_id
            where f.fighter_id is null
            """,
        ),
    ]
    checks = []
    for table, name, sql in specs:
        if not _table_exists(conn, table):
            continue
        orphans = conn.execute(sql).fetchone()[0]
        checks.append(
            Check(
                status="pass" if orphans == 0 else "fail",
                table_name=table,
                check_name=name,
                metric_value=float(orphans),
                threshold="0",
                details="orphan rows",
            )
        )
    return checks


def _required_missingness_checks(missingness: pd.DataFrame) -> list[Check]:
    required = {
        ("events", "event_id"),
        ("events", "source"),
        ("events", "source_event_id"),
        ("events", "promotion"),
        ("events", "name"),
        ("events", "event_date"),
        ("fights", "fight_id"),
        ("fights", "event_id"),
        ("fights", "method"),
        ("fights", "round"),
        ("fights", "time"),
        ("fight_participants", "fighter_id"),
        ("fight_participants", "opponent_id"),
        ("fight_participants", "full_name"),
        ("fighters", "fighter_id"),
        ("fighters", "full_name"),
    }
    checks = []
    for row in missingness.to_dict("records"):
        key = (row["table_name"], row["column_name"])
        if key in required:
            missing = int(row["missing_rows"])
            checks.append(
                Check(
                    status="pass" if missing == 0 else "fail",
                    table_name=row["table_name"],
                    check_name=f"required_{row['column_name']}_not_null",
                    metric_value=float(missing),
                    threshold="0",
                    details=f"source={row['source']} promotion={row['promotion']}",
                )
            )
    return checks


def _identity_checks(conn: duckdb.DuckDBPyConnection) -> list[Check]:
    if not _table_exists(conn, "fighter_identity_links"):
        return []
    unresolved = conn.execute(
        """
        select count(*) from fighter_identity_links
        where source = 'sherdog' and link_method = 'source_self'
        """
    ).fetchone()[0]
    return [
        Check(
            status="warn" if unresolved else "pass",
            table_name="fighter_identity_links",
            check_name="unresolved_sherdog_identities",
            metric_value=float(unresolved),
            threshold="0 preferred",
            details="Sherdog fighters not linked to UFCStats by exact normalized name + DOB",
        )
    ]


def _quarantine_checks(conn: duckdb.DuckDBPyConnection) -> list[Check]:
    if not _table_exists(conn, "parse_quarantine"):
        return []
    quarantine_count = _count(conn, "parse_quarantine")
    return [
        Check(
            status="warn" if quarantine_count else "pass",
            table_name="parse_quarantine",
            check_name="quarantined_rows",
            metric_value=float(quarantine_count),
            threshold="0 preferred",
            details="Rows excluded from canonical analytical tables",
        )
    ]


def _missingness_rows(
    conn: duckdb.DuckDBPyConnection, table: str, column: str, group_columns: list[str]
) -> list[dict[str, Any]]:
    if group_columns:
        select_groups = ", ".join(group_columns)
        group_by = f"group by {select_groups}"
        order_by = f"order by {select_groups}"
    else:
        select_groups = "'all' as source, 'all' as promotion"
        group_by = ""
        order_by = ""
    if group_columns == ["source"]:
        select_groups = "source, 'all' as promotion"
    sql = f"""
    select
      '{table}' as table_name,
      '{column}' as column_name,
      {select_groups},
      count(*) as total_rows,
      sum(case when {column} is null then 1 else 0 end) as missing_rows,
      case when count(*) = 0 then 0
           else round(100.0 * sum(case when {column} is null then 1 else 0 end) / count(*), 3)
      end as missing_pct
    from {table}
    {group_by}
    {order_by}
    """
    rows = conn.execute(sql).fetchdf().to_dict("records")
    for row in rows:
        row["status"] = _missingness_status(row["column_name"], row["missing_pct"])
    return rows


def _missingness_status(column: str, missing_pct: float) -> str:
    if missing_pct == 0:
        return "pass"
    if column in {"event_id", "fight_id", "fighter_id", "source", "name", "full_name"}:
        return "fail"
    return "warn"


def _duplicate_count(conn: duckdb.DuckDBPyConnection, table: str, keys: list[str]) -> int:
    key_sql = ", ".join(keys)
    return conn.execute(
        f"""
        select count(*) from (
          select {key_sql}, count(*) as row_count
          from {table}
          group by {key_sql}
          having count(*) > 1
        )
        """
    ).fetchone()[0]


def _write_audit_table(
    conn: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame, schema: dict[str, str]
) -> None:
    conn.execute(f"drop table if exists {table}")
    column_sql = ", ".join(f"{name} {sql_type}" for name, sql_type in schema.items())
    conn.execute(f"create table {table} ({column_sql})")
    if frame.empty:
        return
    conn.register("audit_frame", frame[list(schema)])
    conn.execute(f"insert into {table} select * from audit_frame")
    conn.unregister("audit_frame")


def _count(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def _table_count(conn: duckdb.DuckDBPyConnection) -> int:
    return conn.execute(
        "select count(*) from information_schema.tables where table_schema = 'main'"
    ).fetchone()[0]


def _table_exists(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(
        conn.execute(
            "select 1 from information_schema.tables where table_schema='main' and table_name=?",
            [table],
        ).fetchone()
    )


def _all_tables_exist(conn: duckdb.DuckDBPyConnection, tables: list[str]) -> bool:
    return all(_table_exists(conn, table) for table in tables)


def _columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"pragma table_info('{table}')").fetchall()}


def _summary_schema() -> dict[str, str]:
    return {
        "section": "varchar",
        "metric_name": "varchar",
        "metric_value": "varchar",
        "details": "varchar",
    }


def _checks_schema() -> dict[str, str]:
    return {
        "status": "varchar",
        "table_name": "varchar",
        "check_name": "varchar",
        "metric_value": "double",
        "threshold": "varchar",
        "details": "varchar",
    }


def _coverage_schema() -> dict[str, str]:
    return {
        "source": "varchar",
        "promotion": "varchar",
        "event_year": "integer",
        "events": "bigint",
        "fights": "bigint",
        "fighters": "bigint",
        "first_event_date": "date",
        "last_event_date": "date",
        "fights_per_event": "double",
    }


def _missingness_schema() -> dict[str, str]:
    return {
        "table_name": "varchar",
        "column_name": "varchar",
        "source": "varchar",
        "promotion": "varchar",
        "total_rows": "bigint",
        "missing_rows": "bigint",
        "missing_pct": "double",
        "status": "varchar",
    }


def _identity_schema() -> dict[str, str]:
    return {
        "source": "varchar",
        "link_method": "varchar",
        "fighters": "bigint",
        "with_dob": "bigint",
        "missing_dob": "bigint",
        "sample_name": "varchar",
    }


def _pit_schema() -> dict[str, str]:
    return {
        "check_name": "varchar",
        "status": "varchar",
        "metric_value": "double",
        "threshold": "varchar",
        "details": "varchar",
    }
