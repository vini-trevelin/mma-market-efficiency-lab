from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from mma_eff_lab.api import app as api_module
from mma_eff_lab.config import get_settings


def test_api_health_and_table_reads(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    settings.warehouse_dir.mkdir(parents=True)
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        conn.execute(
            "create table events(event_id varchar, name varchar, source varchar, promotion varchar)"
        )
        conn.execute("insert into events values ('e1', 'UFC Test', 'ufcstats', 'UFC')")
        conn.execute("insert into events values ('e2', 'Bellator Test', 'sherdog', 'Bellator MMA')")
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
