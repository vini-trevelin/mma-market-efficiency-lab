from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from mma_eff_lab.api import app as api_module
from mma_eff_lab.audit.warehouse import validate_warehouse
from mma_eff_lab.config import get_settings
from mma_eff_lab.features.pit import build_pit_features
from mma_eff_lab.warehouse.build import build_warehouse
from tests.test_sherdog_parser import SHERDOG_RED_ID
from tests.test_warehouse_and_pit import _write_cached_fixture_tree, _write_cached_sherdog_tree


def test_api_health_and_table_reads(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    settings.warehouse_dir.mkdir(parents=True)
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        conn.execute(
            "create table events(event_id varchar, name varchar, source varchar, promotion varchar)"
        )
        conn.execute(
            """
            create table analysis_fight_audit(
              fight_id varchar,
              event_id varchar,
              source varchar,
              promotion varchar,
              has_anomaly boolean
            )
            """
        )
        conn.execute(
            """
            create table analysis_identity_review(
              source varchar,
              source_fighter_id varchar,
              canonical_fighter_id varchar,
              full_name varchar,
              dob varchar,
              link_method varchar,
              confidence double,
              exact_name_key varchar,
              cleaned_name_key varchar,
              match_reason varchar,
              review_status varchar,
              candidate_count bigint,
              has_candidate boolean,
              candidate_source_fighter_ids varchar,
              candidate_canonical_fighter_ids varchar,
              candidate_full_names varchar
            )
            """
        )
        conn.execute("insert into events values ('e1', 'UFC Test', 'ufcstats', 'UFC')")
        conn.execute("insert into events values ('e2', 'Bellator Test', 'sherdog', 'Bellator MMA')")
        conn.execute(
            "insert into analysis_fight_audit values ('f1', 'e1', 'ufcstats', 'UFC', false)"
        )
        conn.execute(
            "insert into analysis_fight_audit values ('f2', 'e2', 'sherdog', 'Bellator MMA', true)"
        )
        conn.execute(
            """
            insert into analysis_identity_review values
            (
              'sherdog', 's1', 'ufcstats:u1', 'Nick Name', '1990-01-01',
              'cleaned_name_dob', 0.95, 'nick name', 'name', 'cleaned full name + exact dob',
              'linked_cleaned', 1, true, 'u1', 'ufcstats:u1', 'Name'
            ),
            (
              'sherdog', 's2', 'sherdog:s2', 'Shared Name', '1990-01-01',
              'source_self', 1.0, 'shared name', 'shared name', 'source_self',
              'candidate_review', 2, true, 'u2, u3', 'ufcstats:u2, ufcstats:u3',
              'Shared Name | Shared Name'
            )
            """
        )
    api_module.settings = settings
    client = TestClient(api_module.app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["table_counts"]["events"] == 2
    table = client.get("/tables/events?limit=10")
    assert table.status_code == 200
    assert table.json()["rows"][0]["event_id"] == "e1"
    filtered = client.get("/tables/events?source=sherdog&promotion=Bellator")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["rows"][0]["event_id"] == "e2"
    anomalies = client.get("/tables/analysis_fight_audit?source=sherdog&has_anomaly=true")
    assert anomalies.status_code == 200
    assert anomalies.json()["total"] == 1
    assert anomalies.json()["rows"][0]["fight_id"] == "f2"
    identity = client.get(
        "/tables/analysis_identity_review?review_status=candidate_review&has_candidate=true"
    )
    assert identity.status_code == 200
    assert identity.json()["total"] == 1
    assert identity.json()["rows"][0]["source_fighter_id"] == "s2"


def test_api_rejects_unknown_command_and_running_lock(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    settings.logs_dir.mkdir(parents=True)
    api_module.settings = settings
    client = TestClient(api_module.app)
    assert client.post("/commands/rm-rf").status_code == 404
    api_module._lock.acquire()
    try:
        assert client.post("/commands/make-reports").status_code == 409
    finally:
        api_module._lock.release()
    assert "download-sherdog" in api_module.ALLOWED_COMMANDS
    assert "validate-warehouse" in api_module.ALLOWED_COMMANDS
    assert "repair-sherdog-major" in api_module.ALLOWED_COMMANDS


def test_api_audit_endpoints_empty_and_filtered_reads(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    settings.warehouse_dir.mkdir(parents=True)
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        conn.execute(
            """
            create table audit_checks(
              status varchar,
              table_name varchar,
              check_name varchar,
              metric_value double,
              threshold varchar,
              details varchar
            )
            """
        )
        conn.execute(
            """
            insert into audit_checks
            values ('fail', 'events', 'unique_event_id', 1, '0', 'duplicate')
            """
        )
    api_module.settings = settings
    client = TestClient(api_module.app)
    missing = client.get("/audit/summary")
    assert missing.status_code == 200
    assert missing.json()["exists"] is False
    checks = client.get("/audit/checks?status=fail&table_name=events")
    assert checks.status_code == 200
    assert checks.json()["total"] == 1
    assert checks.json()["rows"][0]["check_name"] == "unique_event_id"
    assert client.get("/audit/checks?status=pass").json()["total"] == 0


def test_identity_decision_endpoints_and_candidates(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    build_pit_features(settings)
    validate_warehouse(settings)
    api_module.settings = settings
    api_module._runs.clear()

    def fake_start(name: str) -> dict[str, str]:
        assert name == "apply-identity-overrides"
        return {"run_id": "run-1", "status": "running"}

    original_start = api_module._start_background_command
    api_module._start_background_command = fake_start  # type: ignore[assignment]
    try:
        client = TestClient(api_module.app)

        review = client.get("/identity/review?source=sherdog&review_status=linked_exact")
        assert review.status_code == 200
        assert review.json()["total"] >= 1

        candidates = client.get(f"/identity/candidates?source_fighter_id={SHERDOG_RED_ID}")
        assert candidates.status_code == 200
        payload = candidates.json()
        assert payload["suggestions"][0]["target_source_fighter_id"] == "1111111111111111"

        decision = client.post(
            "/identity/decisions",
            json={
                "source_fighter_id": SHERDOG_RED_ID,
                "target_source_fighter_id": "1111111111111111",
                "decision": "rejected",
                "note": "manual reject",
                "apply": True,
            },
        )
        assert decision.status_code == 200
        assert decision.json()["apply_status"] == "started"
        assert decision.json()["run_id"] == "run-1"

        candidates_after = client.get(f"/identity/candidates?source_fighter_id={SHERDOG_RED_ID}")
        assert candidates_after.status_code == 200
        assert candidates_after.json()["suggestions"] == []
        assert (
            candidates_after.json()["rejected_pairs"][0]["target_source_fighter_id"]
            == "1111111111111111"
        )

        cleared = client.request(
            "DELETE",
            "/identity/decisions",
            params={
                "source_fighter_id": SHERDOG_RED_ID,
                "target_source_fighter_id": "1111111111111111",
                "apply": "false",
            },
        )
        assert cleared.status_code == 200
        assert cleared.json()["apply_status"] == "skipped"

        accepted = client.post(
            "/identity/decisions",
            json={
                "source_fighter_id": SHERDOG_RED_ID,
                "decision": "accepted_unresolved",
                "note": "no candidates",
                "apply": False,
            },
        )
        assert accepted.status_code == 200
        with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
            decision = conn.execute(
                """
                select decision
                from fighter_identity_manual_overrides
                where source_fighter_id = ? and target_source_fighter_id is null
                """,
                [SHERDOG_RED_ID],
            ).fetchone()[0]
        assert decision == "accepted_unresolved"

        cleared_unresolved = client.request(
            "DELETE",
            "/identity/decisions",
            params={
                "source_fighter_id": SHERDOG_RED_ID,
                "apply": "false",
            },
        )
        assert cleared_unresolved.status_code == 200
        with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
            remaining = conn.execute(
                """
                select count(*)
                from fighter_identity_manual_overrides
                where source_fighter_id = ? and target_source_fighter_id is null
                """,
                [SHERDOG_RED_ID],
            ).fetchone()[0]
        assert remaining == 0
    finally:
        api_module._start_background_command = original_start  # type: ignore[assignment]


def test_identity_candidates_works_with_existing_read_only_connection(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    build_pit_features(settings)
    validate_warehouse(settings)
    api_module.settings = settings
    client = TestClient(api_module.app)

    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        assert conn.execute("select count(*) from analysis_identity_review").fetchone()[0] > 0
        response = client.get(f"/identity/candidates?source_fighter_id={SHERDOG_RED_ID}")

    assert response.status_code == 200
    assert response.json()["source_fighter"]["source_fighter_id"] == SHERDOG_RED_ID
