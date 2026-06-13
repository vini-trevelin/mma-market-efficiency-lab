from __future__ import annotations

import pandas as pd

from mma_eff_lab.models.calibrated_walkforward import (
    _predict_probabilities,
    evaluate_calibrated_walkforward,
)
from mma_eff_lab.models.calibration import expected_calibration_error
from mma_eff_lab.models.dataset import FEATURE_COLUMNS, TARGET_COLUMN


def test_ece_with_empty_input() -> None:
    ece = expected_calibration_error(
        pd.Series([], dtype=float),
        pd.Series([], dtype=float),
        bins=10,
    )
    assert ece == 0.0


def test_walkforward_report_shape(tmp_path, monkeypatch) -> None:
    from mma_eff_lab.config import Settings
    from mma_eff_lab.models import calibrated_walkforward

    n = 100
    dates = pd.date_range("2020-01-01", periods=n, freq="D").date
    rows = []
    for i in range(n):
        row = {
            "fight_id": f"f{i}",
            "event_id": f"e{i}",
            "event_date": dates[i],
            "source": "ufcstats" if i % 3 != 0 else "sherdog",
            "promotion": "UFC",
            "fighter_a_id": f"a{i}",
            "fighter_b_id": f"b{i}",
            "fighter_a_name": f"Fighter A {i}",
            "fighter_b_name": f"Fighter B {i}",
            TARGET_COLUMN: i % 2 == 0,
        }
        for feature in FEATURE_COLUMNS:
            row[feature] = float(i % 5)
        rows.append(row)

    frame = pd.DataFrame(rows)

    from mma_eff_lab.models.dataset import ModelDataset

    fake_dataset = ModelDataset(
        frame=frame,
        metadata={
            "input_rows": n,
            "training_rows": n,
            "excluded_draw_nc": 0,
            "excluded_invalid_label": 0,
        },
    )

    monkeypatch.setattr(calibrated_walkforward, "build_model_dataset", lambda s=None: fake_dataset)

    result = evaluate_calibrated_walkforward(
        settings=Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            raw_dir=tmp_path / "data" / "raw",
            warehouse_dir=tmp_path / "data" / "warehouse",
            reports_dir=tmp_path / "data" / "reports",
            logs_dir=tmp_path / "data" / "logs",
            warehouse_path=tmp_path / "data" / "warehouse" / "mma.duckdb",
        ),
        folds=3,
        initial_train_fraction=0.5,
        bins=5,
    )

    assert "overall_raw" in result
    assert "overall_calibrated" in result
    assert "fold_details" in result
    assert len(result["fold_details"]) == 3

    for fold_result in result["fold_details"]:
        assert "raw" in fold_result
        assert "calibrated" in fold_result
        assert "expected_calibration_error" in fold_result["raw"]
        assert "expected_calibration_error" in fold_result["calibrated"]
        assert "source_metrics" in fold_result
        assert "train_rows" in fold_result
        assert "test_rows" in fold_result
        assert "train_end_date" in fold_result
        assert "test_start_date" in fold_result

    overall = result["overall_raw"]
    assert "log_loss" in overall
    assert "brier_score" in overall
    assert "auc" in overall
    assert "accuracy" in overall
    assert "expected_calibration_error" in overall
    assert overall["rows"] > 0

    calibrated = result["overall_calibrated"]
    assert "log_loss" in calibrated
    assert "expected_calibration_error" in calibrated


def test_predict_probabilities_returns_correct_length() -> None:
    class FakeModel:
        def predict_proba(self, x):
            import numpy as np
            probs = np.full((len(x), 2), 0.5)
            probs[:, 1] = 0.6
            probs[:, 0] = 0.4
            return probs

    model = FakeModel()
    frame = pd.DataFrame({col: [1.0, 2.0] for col in FEATURE_COLUMNS[:3]})
    frame = pd.DataFrame({col: [1.0, 2.0] for col in FEATURE_COLUMNS})

    result = _predict_probabilities(model, frame, FEATURE_COLUMNS)

    assert len(result) == 2
    assert all(0 <= p <= 1 for p in result)