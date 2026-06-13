from __future__ import annotations

import json

import pandas as pd

from mma_eff_lab.models.dataset import FEATURE_COLUMNS, TARGET_COLUMN
from mma_eff_lab.models.quality import (
    _deterministic_orientation_check,
    _forbidden_feature_check,
    _label_balance_check,
    _serving_model_artifact_check,
)


def test_quality_check_rejects_forbidden_feature_leakage() -> None:
    check = _forbidden_feature_check()

    assert check["status"] == "pass"
    assert check["details"]["forbidden_features"] == []
    assert all(not feature.startswith(("red_", "blue_")) for feature in FEATURE_COLUMNS)


def test_quality_check_reports_orientation_and_label_balance() -> None:
    frame = pd.DataFrame(
        {
            "fighter_a_id": ["a", "b"],
            "fighter_b_id": ["b", "c"],
            TARGET_COLUMN: [True, False],
        }
    )
    metadata = {
        "label_balance": {"fighter_a_wins": 1, "fighter_b_wins": 1},
        "excluded_draw_nc": 0,
        "excluded_invalid_label": 0,
    }

    assert _deterministic_orientation_check(frame)["status"] == "pass"
    assert _label_balance_check(metadata)["status"] == "pass"


def test_serving_artifact_missing_files(tmp_path) -> None:
    from dataclasses import replace

    from mma_eff_lab.config import get_settings

    settings = replace(
        get_settings(tmp_path),
        data_dir=tmp_path / "data",
    )
    check = _serving_model_artifact_check(settings)

    assert check["status"] == "fail"
    assert "model.cbm" in check["details"]["missing_files"]
    assert check["details"]["model_version"] == "calibrated_ufc_catboost_v1"


def test_serving_artifact_bad_metadata_schema(tmp_path) -> None:
    from dataclasses import replace

    from mma_eff_lab.config import get_settings

    model_dir = tmp_path / "data" / "models" / "calibrated_ufc_catboost_v1"
    model_dir.mkdir(parents=True)
    (model_dir / "model.cbm").write_bytes(b"fake")
    (model_dir / "isotonic_calibrator.pkl").write_bytes(b"fake")
    (model_dir / "metadata.json").write_text("not json", encoding="utf-8")
    (model_dir / "metrics.json").write_text("{}", encoding="utf-8")

    settings = replace(get_settings(tmp_path), data_dir=tmp_path / "data")
    check = _serving_model_artifact_check(settings)

    assert check["status"] == "fail"


def test_serving_artifact_feature_mismatch(tmp_path) -> None:
    from dataclasses import replace

    from mma_eff_lab.config import get_settings

    model_dir = tmp_path / "data" / "models" / "calibrated_ufc_catboost_v1"
    model_dir.mkdir(parents=True)
    (model_dir / "model.cbm").write_bytes(b"fake")
    (model_dir / "isotonic_calibrator.pkl").write_bytes(b"fake")
    (model_dir / "metadata.json").write_text(
        json.dumps({"feature_columns": ["wrong_feature"]}), encoding="utf-8"
    )
    (model_dir / "metrics.json").write_text(
        json.dumps(
            {
                "ufcstats_test_raw": {"log_loss": 0.65, "brier_score": 0.23, "rows": 100},
                "ufcstats_test_isotonic": {
                    "log_loss": 0.64,
                    "brier_score": 0.22,
                    "rows": 100,
                },
            }
        ),
        encoding="utf-8",
    )

    settings = replace(get_settings(tmp_path), data_dir=tmp_path / "data")
    check = _serving_model_artifact_check(settings)

    assert check["status"] == "fail"
    assert check["details"]["feature_mismatch"] is True


def test_serving_artifact_calibrated_degradation_warns(tmp_path) -> None:
    from dataclasses import replace

    from mma_eff_lab.config import get_settings

    model_dir = tmp_path / "data" / "models" / "calibrated_ufc_catboost_v1"
    model_dir.mkdir(parents=True)
    (model_dir / "model.cbm").write_bytes(b"fake")
    (model_dir / "isotonic_calibrator.pkl").write_bytes(b"fake")
    (model_dir / "metadata.json").write_text(
        json.dumps({"feature_columns": FEATURE_COLUMNS}), encoding="utf-8"
    )
    (model_dir / "metrics.json").write_text(
        json.dumps(
            {
                "ufcstats_test_raw": {"log_loss": 0.60, "brier_score": 0.22, "rows": 100},
                "ufcstats_test_isotonic": {
                    "log_loss": 0.70,
                    "brier_score": 0.28,
                    "rows": 100,
                },
            }
        ),
        encoding="utf-8",
    )

    settings = replace(get_settings(tmp_path), data_dir=tmp_path / "data")
    check = _serving_model_artifact_check(settings)

    assert check["status"] == "warn"
    assert "calibrated_log_loss_degradation" in check["details"]
