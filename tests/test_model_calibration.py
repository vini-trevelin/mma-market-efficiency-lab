from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from mma_eff_lab.models.calibrated import (
    load_isotonic_calibrator_payload,
    serialize_isotonic_calibrator,
)
from mma_eff_lab.models.calibration import (
    _calibration_curve,
    _fit_calibrators,
    expected_calibration_error,
)


def test_calibration_curve_preserves_probability_and_observed_rate() -> None:
    target = pd.Series([0, 0, 1, 1])
    probabilities = pd.Series([0.1, 0.2, 0.8, 0.9])

    curve = _calibration_curve(target, probabilities, bins=2)

    assert len(curve) == 2
    assert curve[0]["rows"] == 2
    assert curve[0]["observed_win_rate"] == 0.0
    assert curve[1]["rows"] == 2
    assert curve[1]["observed_win_rate"] == 1.0


def test_calibrators_return_valid_probability_models() -> None:
    target = pd.Series([0, 0, 0, 1, 1, 1])
    probabilities = pd.Series([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])

    calibrators = _fit_calibrators(probabilities, target)

    assert calibrators.platt.predict_proba([[0.5]]).shape == (1, 2)
    assert 0.0 <= float(calibrators.isotonic.predict([0.5])[0]) <= 1.0


def test_ece_perfect_calibration() -> None:
    target = pd.Series([0.0, 0.0, 1.0, 1.0])
    probabilities = pd.Series([0.0, 0.0, 1.0, 1.0])

    ece = expected_calibration_error(target, probabilities, bins=2)

    assert ece == 0.0


def test_ece_miscalibrated() -> None:
    np.random.seed(42)
    n = 200
    target = pd.Series(np.random.binomial(1, 0.3, n))
    probabilities = pd.Series(np.clip(target + np.random.normal(0.4, 0.1, n), 0.01, 0.99))

    ece = expected_calibration_error(target, probabilities, bins=10)

    assert ece > 0.05


def test_isotonic_json_serialization_roundtrip() -> None:
    target = pd.Series([0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
    probabilities = pd.Series([0.05, 0.15, 0.25, 0.35, 0.55, 0.65, 0.75, 0.85, 0.90, 0.95])
    calibrators = _fit_calibrators(probabilities, target)

    payload = serialize_isotonic_calibrator(calibrators.isotonic)
    assert payload["kind"] == "isotonic"
    assert len(payload["x_thresholds"]) > 0
    assert len(payload["y_thresholds"]) == len(payload["x_thresholds"])

    loaded = load_isotonic_calibrator_payload(payload)
    test_probs = pd.Series([0.1, 0.3, 0.5, 0.7, 0.9])
    original_preds = calibrators.isotonic.predict(test_probs)
    loaded_preds = loaded.predict(test_probs)
    np.testing.assert_allclose(original_preds, loaded_preds, atol=1e-10)


def test_json_calibrator_file_roundtrip(tmp_path: Path) -> None:
    target = pd.Series([0, 0, 0, 1, 1, 1])
    probabilities = pd.Series([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    calibrators = _fit_calibrators(probabilities, target)

    payload = serialize_isotonic_calibrator(calibrators.isotonic)
    json_path = tmp_path / "isotonic_calibrator.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    loaded_payload = json.loads(json_path.read_text(encoding="utf-8"))
    loaded = load_isotonic_calibrator_payload(loaded_payload)
    test_probs = pd.Series([0.2, 0.5, 0.8])
    original_preds = calibrators.isotonic.predict(test_probs)
    loaded_preds = loaded.predict(test_probs)
    np.testing.assert_allclose(original_preds, loaded_preds, atol=1e-10)


def test_no_pickle_import_in_normal_path() -> None:
    import ast

    from mma_eff_lab.models import calibrated as calibrated_module

    source = Path(calibrated_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_pickle = False
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pickle":
                    top_level_pickle = True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "pickle":
                top_level_pickle = True
    assert not top_level_pickle, "pickle should not be imported at module level in calibrated.py"


def test_quality_check_prefers_json_calibrator(tmp_path) -> None:
    from dataclasses import replace

    from mma_eff_lab.config import get_settings
    from mma_eff_lab.models.dataset import FEATURE_COLUMNS
    from mma_eff_lab.models.quality import _serving_model_artifact_check

    model_dir = tmp_path / "data" / "models" / "calibrated_ufc_catboost_v1"
    model_dir.mkdir(parents=True)
    (model_dir / "model.cbm").write_bytes(b"fake")
    (model_dir / "isotonic_calibrator.json").write_text("{}", encoding="utf-8")
    (model_dir / "metadata.json").write_text(
        json.dumps({"feature_columns": FEATURE_COLUMNS}), encoding="utf-8"
    )
    (model_dir / "metrics.json").write_text(
        json.dumps({
            "ufcstats_test_raw": {"log_loss": 0.65, "brier_score": 0.23, "rows": 100},
            "ufcstats_test_isotonic": {
                "log_loss": 0.64,
                "brier_score": 0.22,
                "rows": 100,
            },
        }),
        encoding="utf-8",
    )

    settings = replace(get_settings(tmp_path), data_dir=tmp_path / "data")
    check = _serving_model_artifact_check(settings)
    assert check["details"]["calibrator_format"] == "json"
