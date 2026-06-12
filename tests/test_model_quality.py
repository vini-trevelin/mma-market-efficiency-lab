from __future__ import annotations

import pandas as pd

from mma_eff_lab.models.dataset import FEATURE_COLUMNS, TARGET_COLUMN
from mma_eff_lab.models.quality import (
    _deterministic_orientation_check,
    _forbidden_feature_check,
    _label_balance_check,
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
