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
        conn.execute("create table events(event_id varchar, name varchar)")
        conn.execute("insert into events values ('e1', 'UFC Test')")
    api_module.settings = settings
    client = TestClient(api_module.app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["table_counts"]["events"] == 1
    table = client.get("/tables/events?limit=10")
    assert table.status_code == 200
    assert table.json()["rows"][0]["event_id"] == "e1"


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
