from __future__ import annotations

import pandas as pd

from mma_eff_lab.models.benchmark import (
    BASELINE_FEATURE_COLUMNS,
    RATING_FEATURE_COLUMNS,
    _benchmark_specs,
    make_walk_forward_folds,
)
from mma_eff_lab.models.dataset import FEATURE_COLUMNS, TARGET_COLUMN


def test_benchmark_specs_cover_requested_models() -> None:
    specs = _benchmark_specs()

    assert [spec.name for spec in specs] == [
        "baseline_xgboost",
        "xgboost_rating_features",
        "catboost_rating_features",
    ]
    assert specs[0].model_type == "xgboost"
    assert specs[0].feature_columns == BASELINE_FEATURE_COLUMNS
    assert specs[1].model_type == "xgboost"
    assert specs[1].feature_columns == FEATURE_COLUMNS
    assert specs[2].model_type == "catboost"
    assert specs[2].feature_columns == FEATURE_COLUMNS
    assert not set(RATING_FEATURE_COLUMNS).intersection(BASELINE_FEATURE_COLUMNS)
    assert set(RATING_FEATURE_COLUMNS).issubset(FEATURE_COLUMNS)


def test_walk_forward_folds_are_expanding_and_chronological() -> None:
    frame = pd.DataFrame(
        {
            "event_date": pd.date_range("2020-01-01", periods=10, freq="D").date,
            TARGET_COLUMN: [i % 2 == 0 for i in range(10)],
        }
    )

    folds = make_walk_forward_folds(frame, folds=3, initial_train_fraction=0.5)

    assert len(folds) == 3
    previous_train_size = 0
    for fold in folds:
        assert len(fold.train_dates) > previous_train_size
        assert max(fold.train_dates) < min(fold.test_dates)
        previous_train_size = len(fold.train_dates)
