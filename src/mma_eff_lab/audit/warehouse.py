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
        _refresh_analysis_views(conn)
        summary = _summary(conn, settings)
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


def _summary(conn: duckdb.DuckDBPyConnection, settings: Settings) -> pd.DataFrame:
    now = datetime.now(UTC).isoformat()
    rows = [
        {"section": "run", "metric_name": "validated_at_utc", "metric_value": now, "details": ""},
        {
            "section": "warehouse",
            "metric_name": "warehouse_tables",
            "metric_value": str(_table_count(conn)),
            "details": "main schema table count",
        },
        {
            "section": "warehouse",
            "metric_name": "warehouse_file_bytes",
            "metric_value": str(settings.warehouse_path.stat().st_size),
            "details": str(settings.warehouse_path),
        },
    ]
    rows.extend(_raw_size_summary(settings))
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
        "fighter_identity_manual_overrides",
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
        for row in conn.execute(
            """
            select
              source,
              promotion,
              count(*) as events
            from events
            group by source, promotion
            order by source, promotion
            """
        ).fetchdf().to_dict("records"):
            rows.append(
                {
                    "section": "source_promotion",
                    "metric_name": f"{row['source']}::{row['promotion']}",
                    "metric_value": str(row["events"]),
                    "details": "event count",
                }
            )
    if _table_exists(conn, "fighter_identity_links"):
        for row in conn.execute(
            """
            select
              source,
              link_method,
              count(*) as fighters
            from fighter_identity_links
            group by source, link_method
            order by source, link_method
            """
        ).fetchdf().to_dict("records"):
            rows.append(
                {
                    "section": "identity_links",
                    "metric_name": f"{row['source']}::{row['link_method']}",
                    "metric_value": str(row["fighters"]),
                    "details": "fighters by link method",
                }
            )
    if _table_exists(conn, "fighter_identity_manual_overrides"):
        for row in conn.execute(
            """
            select
              decision,
              count(*) as rows
            from fighter_identity_manual_overrides
            group by decision
            order by decision
            """
        ).fetchdf().to_dict("records"):
            rows.append(
                {
                    "section": "manual_overrides",
                    "metric_name": str(row["decision"]),
                    "metric_value": str(row["rows"]),
                    "details": "manual identity overrides by decision",
                }
            )
    if _table_exists(conn, "analysis_identity_review"):
        for row in conn.execute(
            """
            select
              review_status,
              count(*) as fighters
            from analysis_identity_review
            group by review_status
            order by review_status
            """
        ).fetchdf().to_dict("records"):
            rows.append(
                {
                    "section": "identity_review",
                    "metric_name": row["review_status"],
                    "metric_value": str(row["fighters"]),
                    "details": "sherdog fighters by review status",
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
          min(full_name) as sample_name,
          sum(case when override_note is not null and override_note != '' then 1 else 0 end)
            as with_override_note
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
        same_date_mismatches = conn.execute(
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
                ) as expected_prior_fights,
                sum(
                  case
                    when hist_event.event_date = pit.event_date
                     and hist.fight_id != pit.fight_id then 1
                    else 0
                  end
                ) as same_day_history
              from pit_fighter_features pit
              left join fight_participants hist
                on hist.fighter_id = pit.fighter_id
              left join events hist_event
                on hist_event.event_id = hist.event_id
              group by pit.fight_id, pit.fighter_id, pit.prior_fights, pit.event_date
              having same_day_history > 0
                 and pit.prior_fights != expected_prior_fights
            )
            """
        ).fetchone()[0]
        rows.append(
            {
                "check_name": "pit_same_day_history_excluded",
                "status": "pass" if same_date_mismatches == 0 else "fail",
                "metric_value": same_date_mismatches,
                "threshold": "0",
                "details": "same-date fight history must not be counted in prior_fights",
            }
        )
    if _table_exists(conn, "pit_matchup_features"):
        duplicates = _duplicate_count(conn, "pit_matchup_features", ["fight_id"])
        rows.append(
            {
                "check_name": "pit_matchup_unique_fight_id",
                "status": "pass" if duplicates == 0 else "fail",
                "metric_value": duplicates,
                "threshold": "0",
                "details": "one matchup feature row per fight_id",
            }
        )
    return pd.DataFrame(rows, columns=list(_pit_schema()))


def _checks(
    conn: duckdb.DuckDBPyConnection, missingness: pd.DataFrame, pit: pd.DataFrame
) -> pd.DataFrame:
    checks: list[Check] = []
    checks.extend(_duplicate_checks(conn))
    checks.extend(_orphan_checks(conn))
    checks.extend(_participant_shape_checks(conn))
    checks.extend(_schema_checks(conn))
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
        (
            "fighter_identity_manual_overrides",
            ["source", "source_fighter_id", "target_source", "target_source_fighter_id"],
        ),
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


def _participant_shape_checks(conn: duckdb.DuckDBPyConnection) -> list[Check]:
    checks: list[Check] = []
    if _table_exists(conn, "fight_participants"):
        bad_shapes = conn.execute(
            """
            select count(*) from (
              select
                fight_id,
                count(*) as participant_count,
                sum(case when corner = 'red' then 1 else 0 end) as red_count,
                sum(case when corner = 'blue' then 1 else 0 end) as blue_count
              from fight_participants
              group by fight_id
              having participant_count != 2 or red_count != 1 or blue_count != 1
            )
            """
        ).fetchone()[0]
        checks.append(
            Check(
                status="pass" if bad_shapes == 0 else "fail",
                table_name="fight_participants",
                check_name="fight_corner_shape",
                metric_value=float(bad_shapes),
                threshold="0",
                details="fights must have exactly one red and one blue participant",
            )
        )
    if _table_exists(conn, "pit_matchup_features"):
        duplicates = _duplicate_count(conn, "pit_matchup_features", ["fight_id"])
        checks.append(
            Check(
                status="pass" if duplicates == 0 else "fail",
                table_name="pit_matchup_features",
                check_name="unique_fight_id",
                metric_value=float(duplicates),
                threshold="0",
                details="one matchup row per fight_id",
            )
        )
    return checks


def _schema_checks(conn: duckdb.DuckDBPyConnection) -> list[Check]:
    checks: list[Check] = []
    specs = {
        "parse_quarantine": {
            "source": "VARCHAR",
            "entity_type": "VARCHAR",
            "source_entity_id": "VARCHAR",
            "promotion": "VARCHAR",
            "reason": "VARCHAR",
            "url": "VARCHAR",
        },
        "fighter_identity_manual_overrides": {
            "source": "VARCHAR",
            "source_fighter_id": "VARCHAR",
            "target_source": "VARCHAR",
            "target_source_fighter_id": "VARCHAR",
            "decision": "VARCHAR",
            "note": "VARCHAR",
            "created_at_utc": "VARCHAR",
            "updated_at_utc": "VARCHAR",
        }
    }
    for table, schema in specs.items():
        if not _table_exists(conn, table):
            continue
        columns = {
            row[1]: str(row[2]).upper()
            for row in conn.execute(f"pragma table_info('{table}')").fetchall()
        }
        mismatches = sum(
            1 for column, expected in schema.items() if columns.get(column) != expected
        )
        checks.append(
            Check(
                status="pass" if mismatches == 0 else "fail",
                table_name=table,
                check_name="schema_types_match",
                metric_value=float(mismatches),
                threshold="0",
                details="declared schema types must match expected text-safe layout",
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
    if _table_exists(conn, "analysis_identity_review"):
        unresolved = conn.execute(
            """
            select count(*)
            from analysis_identity_review
            where review_status = 'unresolved'
            """
        ).fetchone()[0]
    else:
        unresolved = conn.execute(
            """
            select count(*) from fighter_identity_links
            where source = 'sherdog' and link_method = 'source_self'
            """
        ).fetchone()[0]
    checks = [
        Check(
            status="warn" if unresolved else "pass",
            table_name="fighter_identity_links",
            check_name="unresolved_sherdog_identities",
            metric_value=float(unresolved),
            threshold="0 preferred",
            details=(
                "Sherdog fighters not linked to UFCStats after manual overrides "
                "and deterministic DOB-gated rules"
            ),
        )
    ]
    if _table_exists(conn, "fighter_identity_manual_overrides"):
        conflicts = conn.execute(
            """
            select count(*) from (
              select source_fighter_id
              from fighter_identity_manual_overrides
              where decision = 'approved'
              group by source_fighter_id
              having count(*) > 1
            )
            """
        ).fetchone()[0]
        checks.append(
            Check(
                status="pass" if conflicts == 0 else "fail",
                table_name="fighter_identity_manual_overrides",
                check_name="single_approved_target_per_source_fighter",
                metric_value=float(conflicts),
                threshold="0",
                details="a Sherdog fighter may have at most one approved manual UFC target",
            )
        )
    return checks


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


def _raw_size_summary(settings: Settings) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source in ["ufcstats", "sherdog"]:
        root = settings.raw_dir / source
        files = [path for path in root.rglob("*") if path.is_file()]
        rows.append(
            {
                "section": "raw_cache",
                "metric_name": f"{source}_files",
                "metric_value": str(len(files)),
                "details": str(root),
            }
        )
        rows.append(
            {
                "section": "raw_cache",
                "metric_name": f"{source}_bytes",
                "metric_value": str(sum(path.stat().st_size for path in files)),
                "details": str(root),
            }
        )
    return rows


def _refresh_analysis_views(conn: duckdb.DuckDBPyConnection) -> None:
    if not _table_exists(conn, "fighter_identity_manual_overrides"):
        conn.execute(
            """
            create table fighter_identity_manual_overrides(
              source varchar,
              source_fighter_id varchar,
              target_source varchar,
              target_source_fighter_id varchar,
              decision varchar,
              note varchar,
              created_at_utc varchar,
              updated_at_utc varchar
            )
            """
        )
    conn.execute("drop view if exists analysis_event_audit")
    conn.execute("drop view if exists analysis_fight_audit")
    conn.execute("drop view if exists analysis_fighter_audit")
    conn.execute("drop view if exists analysis_identity_review")
    conn.execute("drop view if exists analysis_pit_audit")
    conn.execute(
        """
        create view analysis_fight_audit as
        with participant_counts as (
          select
            fight_id,
            count(*) as participant_count,
            sum(case when corner = 'red' then 1 else 0 end) as red_count,
            sum(case when corner = 'blue' then 1 else 0 end) as blue_count,
            min(case when corner = 'red' then fighter_id end) as red_fighter_id,
            min(case when corner = 'blue' then fighter_id end) as blue_fighter_id
          from fight_participants
          group by fight_id
        ),
        stats_counts as (
          select fight_id, count(*) as stats_row_count
          from fighter_fight_stats
          group by fight_id
        ),
        pit_counts as (
          select fight_id, count(*) as pit_row_count
          from pit_fighter_features
          group by fight_id
        ),
        matchup_counts as (
          select fight_id, count(*) as matchup_row_count
          from pit_matchup_features
          group by fight_id
        )
        select
          f.fight_id,
          f.event_id,
          e.event_date,
          e.name as event_name,
          f.source,
          f.source_fight_id,
          f.source_event_id,
          f.promotion,
          f.weight_class,
          f.method,
          f.round,
          f.time,
          f.referee,
          pc.red_fighter_id,
          pc.blue_fighter_id,
          coalesce(pc.participant_count, 0) as participant_count,
          coalesce(pc.red_count, 0) as red_count,
          coalesce(pc.blue_count, 0) as blue_count,
          coalesce(stats_counts.stats_row_count, 0) as stats_row_count,
          coalesce(pit_counts.pit_row_count, 0) as pit_row_count,
          coalesce(matchup_counts.matchup_row_count, 0) as matchup_row_count,
          (
            coalesce(pc.participant_count, 0) != 2
            or coalesce(pc.red_count, 0) != 1
            or coalesce(pc.blue_count, 0) != 1
            or coalesce(pit_counts.pit_row_count, 0) != coalesce(pc.participant_count, 0)
            or coalesce(matchup_counts.matchup_row_count, 0) != case
              when coalesce(pc.participant_count, 0) = 2
               and coalesce(pc.red_count, 0) = 1
               and coalesce(pc.blue_count, 0) = 1 then 1
              else 0
            end
          ) as has_anomaly,
          trim(both ';' from
            (
              case
                when coalesce(pc.participant_count, 0) != 2 then 'participant_count;'
                else ''
              end
            ) ||
            (case when coalesce(pc.red_count, 0) != 1 then 'red_count;' else '' end) ||
            (case when coalesce(pc.blue_count, 0) != 1 then 'blue_count;' else '' end) ||
            (
              case
                when coalesce(pit_counts.pit_row_count, 0) != coalesce(pc.participant_count, 0)
                  then 'pit_rows;'
                else ''
              end
            ) ||
            (case when coalesce(matchup_counts.matchup_row_count, 0) != case
              when coalesce(pc.participant_count, 0) = 2
               and coalesce(pc.red_count, 0) = 1
               and coalesce(pc.blue_count, 0) = 1 then 1
              else 0
            end then 'matchup_rows;' else '' end)
          ) as anomaly_flags
        from fights f
        join events e using (event_id)
        left join participant_counts pc using (fight_id)
        left join stats_counts using (fight_id)
        left join pit_counts using (fight_id)
        left join matchup_counts using (fight_id)
        """
    )
    conn.execute(
        """
        create view analysis_event_audit as
        select
          e.event_id,
          e.source,
          e.source_event_id,
          e.promotion,
          e.name,
          e.event_date,
          e.location,
          count(distinct f.fight_id) as fight_count,
          count(distinct p.fighter_id) as fighter_count,
          count(distinct case when fa.has_anomaly then f.fight_id end) as anomalous_fight_count,
          max(case when fa.has_anomaly then 1 else 0 end) = 1 as has_anomaly
        from events e
        left join fights f using (event_id)
        left join fight_participants p using (fight_id)
        left join analysis_fight_audit fa on fa.fight_id = f.fight_id
        group by
          e.event_id,
          e.source,
          e.source_event_id,
          e.promotion,
          e.name,
          e.event_date,
          e.location
        """
    )
    conn.execute(
        """
        create view analysis_fighter_audit as
        with history as (
          select
            p.fighter_id,
            count(*) as fight_count,
            sum(case when p.source = 'ufcstats' then 1 else 0 end) as ufc_fight_count,
            sum(case when p.source = 'sherdog' then 1 else 0 end) as sherdog_fight_count,
            min(e.event_date) as first_fight_date,
            max(e.event_date) as last_fight_date
          from fight_participants p
          join events e using (event_id)
          group by p.fighter_id
        ),
        stat_history as (
          select fighter_id, count(*) as stat_fight_count
          from fighter_fight_stats
          group by fighter_id
        )
        select
          f.fighter_id,
          f.source,
          f.source_fighter_id,
          f.full_name,
          f.dob,
          f.height_in,
          f.weight_lbs,
          f.reach_in,
          f.stance,
          coalesce(history.fight_count, 0) as fight_count,
          coalesce(history.ufc_fight_count, 0) as ufc_fight_count,
          coalesce(history.sherdog_fight_count, 0) as sherdog_fight_count,
          coalesce(stat_history.stat_fight_count, 0) as stat_fight_count,
          history.first_fight_date,
          history.last_fight_date,
          f.dob is null as missing_dob,
          f.height_in is null as missing_height,
          f.reach_in is null as missing_reach,
          f.stance is null as missing_stance,
          (
            f.dob is null
            or f.height_in is null
            or f.reach_in is null
            or f.stance is null
          ) as has_anomaly
        from fighters f
        left join history using (fighter_id)
        left join stat_history using (fighter_id)
        """
    )
    conn.execute(
        """
        create view analysis_identity_review as
        with manual_overrides as (
          select
            source,
            source_fighter_id,
            target_source,
            target_source_fighter_id,
            decision,
            note,
            created_at_utc,
            updated_at_utc
          from fighter_identity_manual_overrides
        ),
            approved_override as (
          select
            source_fighter_id,
            target_source_fighter_id,
            note,
            created_at_utc,
            updated_at_utc
          from manual_overrides
          where decision = 'approved'
        ),
        accepted_unresolved as (
          select
            source_fighter_id,
            note,
            created_at_utc,
            updated_at_utc
          from manual_overrides
          where decision = 'accepted_unresolved'
        ),
        rejected_override_counts as (
          select
            source_fighter_id,
            count(*) as rejected_pair_count
          from manual_overrides
          where decision = 'rejected'
          group by source_fighter_id
        ),
        sherdog_links as (
          select
            source,
            source_fighter_id,
            canonical_fighter_id,
            full_name,
            dob,
            link_method,
            confidence,
            exact_name_key,
            cleaned_name_key,
            match_reason,
            override_note
          from fighter_identity_links
          where source = 'sherdog'
        ),
        ufc_links as (
          select
            source_fighter_id,
            canonical_fighter_id,
            full_name,
            dob,
            exact_name_key,
            cleaned_name_key
          from fighter_identity_links
          where source = 'ufcstats'
        ),
        candidate_matches as (
          select
            s.source_fighter_id,
            count(*) as candidate_count,
            string_agg(
              u.source_fighter_id,
              ', ' order by u.source_fighter_id
            ) as candidate_source_fighter_ids,
            string_agg(
              u.canonical_fighter_id,
              ', ' order by u.canonical_fighter_id
            ) as candidate_canonical_fighter_ids,
            string_agg(u.full_name, ' | ' order by u.full_name) as candidate_full_names
          from sherdog_links s
          join ufc_links u
            on s.cleaned_name_key = u.cleaned_name_key
           and s.dob = u.dob
          left join manual_overrides mo
            on mo.source = 'sherdog'
           and mo.source_fighter_id = s.source_fighter_id
           and mo.target_source = 'ufcstats'
           and mo.target_source_fighter_id = u.source_fighter_id
          where s.link_method = 'source_self'
            and coalesce(mo.decision, '') != 'rejected'
          group by s.source_fighter_id
        )
        select
          s.source,
          s.source_fighter_id,
          s.canonical_fighter_id,
          s.full_name,
          s.dob,
          s.link_method,
          s.confidence,
          s.exact_name_key,
          s.cleaned_name_key,
          s.match_reason,
          case
            when s.link_method = 'manual_override' then 'linked_manual'
            when s.link_method = 'manual_unresolved' then 'accepted_unresolved'
            when s.link_method = 'exact_name_dob' then 'linked_exact'
            when s.link_method = 'cleaned_name_dob' then 'linked_cleaned'
            when coalesce(c.candidate_count, 0) > 0 then 'candidate_review'
            else 'unresolved'
          end as review_status,
          coalesce(c.candidate_count, 0) as candidate_count,
          coalesce(c.candidate_count, 0) > 0 as has_candidate,
          c.candidate_source_fighter_ids,
          c.candidate_canonical_fighter_ids,
          c.candidate_full_names,
          case
            when a.source_fighter_id is not null then 'approved'
            when au.source_fighter_id is not null then 'accepted_unresolved'
            else 'none'
          end as decision_status,
          a.target_source_fighter_id as approved_target_source_fighter_id,
          case
            when a.target_source_fighter_id is not null
              then 'ufcstats:' || a.target_source_fighter_id
            else null
          end as approved_target_canonical_fighter_id,
          coalesce(a.note, au.note, cast(s.override_note as varchar)) as manual_note,
          coalesce(a.created_at_utc, au.created_at_utc) as manual_created_at_utc,
          coalesce(a.updated_at_utc, au.updated_at_utc) as manual_updated_at_utc,
          coalesce(r.rejected_pair_count, 0) as rejected_pair_count
        from sherdog_links s
        left join candidate_matches c
          on s.source_fighter_id = c.source_fighter_id
        left join approved_override a
          on s.source_fighter_id = a.source_fighter_id
        left join accepted_unresolved au
          on s.source_fighter_id = au.source_fighter_id
        left join rejected_override_counts r
          on s.source_fighter_id = r.source_fighter_id
        """
    )
    conn.execute(
        """
        create view analysis_pit_audit as
        select
          pit.fight_id,
          pit.event_id,
          pit.event_date,
          pit.fighter_id,
          pit.opponent_id,
          pit.source,
          pit.promotion,
          pit.full_name,
          pit.prior_fights,
          sum(
            case
              when hist_event.event_date < pit.event_date then 1
              else 0
            end
          ) as expected_prior_fights,
          sum(
            case
              when hist_event.event_date = pit.event_date
               and hist.fight_id != pit.fight_id then 1
              else 0
            end
          ) as same_day_history_count,
          pit.prior_fights != sum(
            case
              when hist_event.event_date < pit.event_date then 1
              else 0
            end
          ) as has_anomaly
        from pit_fighter_features pit
        left join fight_participants hist
          on hist.fighter_id = pit.fighter_id
        left join events hist_event
          on hist_event.event_id = hist.event_id
        group by
          pit.fight_id,
          pit.event_id,
          pit.event_date,
          pit.fighter_id,
          pit.opponent_id,
          pit.source,
          pit.promotion,
          pit.full_name,
          pit.prior_fights
        """
    )


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
        "with_override_note": "bigint",
    }


def _pit_schema() -> dict[str, str]:
    return {
        "check_name": "varchar",
        "status": "varchar",
        "metric_value": "double",
        "threshold": "varchar",
        "details": "varchar",
    }
