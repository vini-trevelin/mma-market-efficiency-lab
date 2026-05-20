from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb

from mma_eff_lab.audit.warehouse import validate_warehouse
from mma_eff_lab.config import get_settings
from mma_eff_lab.features.pit import build_pit_features
from mma_eff_lab.warehouse.build import build_warehouse
from tests.test_warehouse_and_pit import FIGHT_ID_1, _write_cached_fixture_tree


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
    assert statuses == [("pass",)]
    assert quarantine_types[0][1:3] == ("source", "VARCHAR")


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
