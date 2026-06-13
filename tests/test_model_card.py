from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from mma_eff_lab.config import get_settings
from mma_eff_lab.models.dataset import FEATURE_COLUMNS
from mma_eff_lab.warehouse.build import build_warehouse
from tests.test_warehouse_and_pit import _write_cached_fixture_tree, _write_cached_sherdog_tree


def test_write_model_card_schema_keys(tmp_path: Path) -> None:
    from mma_eff_lab.models.model_card import write_model_card

    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)

    model_dir = settings.data_dir / "models" / "calibrated_ufc_catboost_v1"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.cbm").write_bytes(b"fake")
    (model_dir / "isotonic_calibrator.pkl").write_bytes(b"fake")
    (model_dir / "metadata.json").write_text(
        json.dumps({
            "model_version": "calibrated_ufc_catboost_v1",
            "feature_columns": FEATURE_COLUMNS,
            "split": {
                "train_end_date": "2025-01-01",
                "validation_end_date": "2025-06-01",
                "test_start_date": "2025-06-02",
                "train_rows": 10000,
                "validation_rows": 2000,
                "test_rows": 3000,
            },
        }),
        encoding="utf-8",
    )
    (model_dir / "metrics.json").write_text(
        json.dumps({
            "ufcstats_test_raw": {"log_loss": 0.65, "brier_score": 0.23},
            "ufcstats_test_isotonic": {"log_loss": 0.64, "brier_score": 0.22},
        }),
        encoding="utf-8",
    )

    from mma_eff_lab.features.pit import build_pit_features
    build_pit_features(settings)

    result = write_model_card(output_dir=tmp_path / "cards", settings=settings)

    assert "card_path" in result
    assert "registry_path" in result

    card = json.loads(Path(result["card_path"]).read_text(encoding="utf-8"))
    required_keys = {
        "model_version", "created_at_utc", "code_commit",
        "dataset_date_min", "dataset_date_max", "training_rows",
        "excluded_rows", "feature_count", "feature_set_name",
        "source_coverage_caveats", "probability_contract",
        "train_window", "validation_window", "test_window",
        "metrics_summary", "intended_use", "not_intended_use",
    }
    assert required_keys.issubset(set(card.keys()))
    assert card["model_version"] == "calibrated_ufc_catboost_v1"
    assert isinstance(card["intended_use"], list)
    assert isinstance(card["not_intended_use"], list)
    assert len(card["intended_use"]) > 0
    assert len(card["not_intended_use"]) > 0


def test_code_commit_follows_format(tmp_path: Path) -> None:
    from mma_eff_lab.models.model_card import _get_code_commit

    commit = _get_code_commit()
    assert commit == "unknown" or len(commit) >= 7


def test_registry_appends_entries(tmp_path: Path) -> None:
    from mma_eff_lab.models.model_card import _write_registry

    card_data = {
        "model_version": "test_v1",
        "created_at_utc": "2026-01-01",
        "code_commit": "abc1234",
        "feature_count": 36,
        "training_rows": 10000,
        "dataset_date_min": "2020-01-01",
        "dataset_date_max": "2025-12-31",
    }

    registry_path = _write_registry(tmp_path, card_data)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert len(registry) == 1
    assert registry[0]["model_version"] == "test_v1"

    card_data_v2 = {**card_data, "model_version": "test_v2"}
    _write_registry(tmp_path, card_data_v2)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert len(registry) == 2

    card_data_updated = {**card_data, "code_commit": "def5678"}
    _write_registry(tmp_path, card_data_updated)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    test_v1_entries = [e for e in registry if e["model_version"] == "test_v1"]
    assert len(test_v1_entries) == 1
    assert test_v1_entries[0]["code_commit"] == "def5678"