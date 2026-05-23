from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb

from mma_eff_lab.audit.warehouse import validate_warehouse
from mma_eff_lab.config import get_settings
from mma_eff_lab.features.pit import build_pit_features
from mma_eff_lab.warehouse.build import build_warehouse
from tests.test_warehouse_and_pit import (
    FIGHT_ID_1,
    SHERDOG_ALT_ID,
    UFC_ALT_ID_1,
    UFC_ALT_ID_2,
    _write_cached_fixture_tree,
    _write_cached_sherdog_tree,
    _write_extra_sherdog_fighter,
    _write_extra_ufc_fighter,
    _write_manual_override,
)


def test_validate_warehouse_writes_audit_tables_for_clean_fixture(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    build_pit_features(settings)
    counts = validate_warehouse(settings)
    assert counts["audit_checks"] > 0
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        statuses = conn.execute(
            "select distinct status from audit_checks order by status"
        ).fetchall()
        quarantine_types = conn.execute("pragma table_info('parse_quarantine')").fetchall()
        analysis_views = conn.execute(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'main'
              and table_name like 'analysis_%'
            order by table_name
            """
        ).fetchall()
    assert statuses == [("pass",)]
    assert quarantine_types[0][1:3] == ("source", "VARCHAR")
    assert ("analysis_fight_audit",) in analysis_views
    assert ("analysis_identity_review",) in analysis_views


def test_validate_warehouse_flags_duplicate_and_orphan_rows(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    build_pit_features(settings)
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        conn.execute("insert into events select * from events limit 1")
        conn.execute(
            """
            insert into fights
            select
              'bad:fight',
              'missing:event',
              source,
              source_fight_id,
              source_event_id,
              promotion,
              weight_class,
              winner_id,
              method,
              round,
              time,
              time_format,
              referee,
              url
            from fights
            limit 1
            """
        )
    validate_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        failures = conn.execute(
            """
            select check_name
            from audit_checks
            where status = 'fail'
            order by check_name
            """
        ).fetchall()
    assert ("fight_event_fk",) in failures
    assert ("unique_event_id",) in failures


def test_validate_warehouse_flags_pit_leakage_mismatch(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    build_pit_features(settings)
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        conn.execute(
            "update pit_fighter_features set prior_fights = 99 where fight_id = ?",
            [f"ufcstats:{FIGHT_ID_1}"],
        )
    validate_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        status = conn.execute(
            """
            select status
            from audit_pit
            where check_name = 'pit_prior_fights_no_leakage'
            """
        ).fetchone()[0]
    assert status == "fail"


def test_validate_warehouse_flags_matchup_and_schema_issues(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    build_pit_features(settings)
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        conn.execute("insert into pit_matchup_features select * from pit_matchup_features limit 1")
        conn.execute("drop table parse_quarantine")
        conn.execute(
            """
            create table parse_quarantine(
              source integer,
              entity_type integer,
              source_entity_id integer,
              promotion integer,
              reason integer,
              url integer
            )
            """
        )
    validate_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        failures = conn.execute(
            """
            select table_name, check_name
            from audit_checks
            where status = 'fail'
            order by table_name, check_name
            """
        ).fetchall()
    assert ("parse_quarantine", "schema_types_match") in failures
    assert ("pit_matchup_features", "unique_fight_id") in failures


def test_validate_warehouse_exposes_identity_review_statuses(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    _write_extra_ufc_fighter(tmp_path, UFC_ALT_ID_1, "Shared Name", dob="January 01, 1990")
    _write_extra_ufc_fighter(tmp_path, UFC_ALT_ID_2, "Shared Name", dob="January 01, 1990")
    _write_extra_sherdog_fighter(tmp_path, SHERDOG_ALT_ID, "Shared Name", dob="Jan 1, 1990")
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    build_pit_features(settings)
    validate_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        statuses = conn.execute(
            """
            select distinct review_status
            from analysis_identity_review
            order by review_status
            """
        ).fetchall()
    assert ("candidate_review",) in statuses
    assert ("linked_exact",) in statuses


def test_validate_warehouse_exposes_manual_override_review_status(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    _write_manual_override(
        settings.warehouse_path,
        "6166",
        "1111111111111111",
        "approved",
        "manual",
    )
    build_warehouse(settings)
    build_pit_features(settings)
    validate_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        statuses = conn.execute(
            """
            select distinct review_status
            from analysis_identity_review
            order by review_status
            """
        ).fetchall()
        metrics = conn.execute(
            """
            select metric_name, metric_value
            from audit_summary
            where section = 'manual_overrides'
            """
        ).fetchall()
    assert ("linked_manual",) in statuses
    assert ("approved", "1") in metrics


def test_validate_warehouse_excludes_accepted_unresolved_from_warning_count(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    _write_extra_sherdog_fighter(tmp_path, SHERDOG_ALT_ID, "Red Fighter", dob="Unknown")
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    _write_manual_override(
        settings.warehouse_path,
        SHERDOG_ALT_ID,
        "",
        "accepted_unresolved",
        "checked manually",
    )
    build_warehouse(settings)
    build_pit_features(settings)
    validate_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        statuses = conn.execute(
            """
            select distinct review_status
            from analysis_identity_review
            order by review_status
            """
        ).fetchall()
        warning = conn.execute(
            """
            select metric_value
            from audit_checks
            where check_name = 'unresolved_sherdog_identities'
            """
        ).fetchone()[0]
    assert ("accepted_unresolved",) in statuses
    assert warning == 0
