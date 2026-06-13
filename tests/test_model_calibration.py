from __future__ import annotations

import pandas as pd

from mma_eff_lab.models.calibration import _calibration_curve, _fit_calibrators


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
