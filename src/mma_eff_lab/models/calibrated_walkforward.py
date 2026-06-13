from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.models.benchmark import (
    BenchmarkSpec,
    _benchmark_specs,
    _fit_model,
    make_walk_forward_folds,
)
from mma_eff_lab.models.calibration import (
    _fit_calibrators,
    _isotonic_predict,
    _probability_metrics,
    expected_calibration_error,
)
from mma_eff_lab.models.dataset import TARGET_COLUMN, build_model_dataset

_CALIBRATED_SPEC = BenchmarkSpec(
    name="calibrated_ufc_catboost_v1",
    model_type="catboost",
    feature_columns=_benchmark_specs()[1].feature_columns,
)


def evaluate_calibrated_walkforward(
    settings: Settings | None = None,
    output_dir: Path | None = None,
    folds: int = 8,
    initial_train_fraction: float = 0.5,
    bins: int = 10,
    validation_fraction: float = 0.15,
) -> dict[str, Any]:
    settings = settings or get_settings()
    dataset = build_model_dataset(settings)
    spec = _CALIBRATED_SPEC

    walk_forward_folds = make_walk_forward_folds(
        dataset.frame, folds, initial_train_fraction
    )

    fold_results = []
    all_raw_truth: list[int] = []
    all_raw_probabilities: list[float] = []
    all_calibrated_truth: list[int] = []
    all_calibrated_probabilities: list[float] = []

    for fold_index, fold in enumerate(walk_forward_folds, start=1):
        fold_train = dataset.frame[
            dataset.frame["event_date"].isin(fold.train_dates)
        ].reset_index(drop=True)
        fold_test = dataset.frame[
            dataset.frame["event_date"].isin(fold.test_dates)
        ].reset_index(drop=True)

        n_validation = max(1, int(len(fold_train) * validation_fraction))
        fold_validation = fold_train.iloc[-n_validation:]
        fold_train_inner = fold_train.iloc[:-n_validation]

        model = _fit_model(spec, fold_train_inner, fold_validation)
        raw_probabilities = _predict_probabilities(model, fold_test, spec.feature_columns)

        validation_probabilities = _predict_probabilities(
            model, fold_validation, spec.feature_columns
        )
        calibrators = _fit_calibrators(
            validation_probabilities,
            fold_validation[TARGET_COLUMN].astype(int),
        )
        calibrated_probabilities = _isotonic_predict(
            calibrators.isotonic, raw_probabilities
        )

        raw_metrics = _probability_metrics(
            fold_test[TARGET_COLUMN].astype(int), raw_probabilities
        )
        raw_metrics["expected_calibration_error"] = expected_calibration_error(
            fold_test[TARGET_COLUMN].astype(int), raw_probabilities, bins=bins
        )

        calibrated_metrics = _probability_metrics(
            fold_test[TARGET_COLUMN].astype(int), calibrated_probabilities
        )
        calibrated_metrics["expected_calibration_error"] = expected_calibration_error(
            fold_test[TARGET_COLUMN].astype(int), calibrated_probabilities, bins=bins
        )

        source_metrics: dict[str, dict[str, Any]] = {}
        for source, group in fold_test.groupby("source", dropna=False):
            source_raw = _predict_probabilities(model, group, spec.feature_columns)
            source_calibrated = _isotonic_predict(calibrators.isotonic, source_raw)
            source_metrics[str(source)] = {
                "raw": {
                    **_probability_metrics(
                        group[TARGET_COLUMN].astype(int), source_raw
                    ),
                    "expected_calibration_error": expected_calibration_error(
                        group[TARGET_COLUMN].astype(int), source_raw, bins=bins
                    ),
                },
                "calibrated": {
                    **_probability_metrics(
                        group[TARGET_COLUMN].astype(int), source_calibrated
                    ),
                    "expected_calibration_error": expected_calibration_error(
                        group[TARGET_COLUMN].astype(int), source_calibrated, bins=bins
                    ),
                },
            }

        fold_results.append(
            {
                "fold": fold_index,
                "train_end_date": str(max(fold.train_dates)),
                "validation_end_date": str(fold_train.iloc[-n_validation]["event_date"]),
                "test_start_date": str(min(fold.test_dates)),
                "test_end_date": str(max(fold.test_dates)),
                "train_rows": len(fold_train_inner),
                "validation_rows": len(fold_validation),
                "test_rows": len(fold_test),
                "raw": raw_metrics,
                "calibrated": calibrated_metrics,
                "source_metrics": source_metrics,
            }
        )

        all_raw_truth.extend(fold_test[TARGET_COLUMN].astype(int).tolist())
        all_raw_probabilities.extend(raw_probabilities.tolist())
        all_calibrated_truth.extend(fold_test[TARGET_COLUMN].astype(int).tolist())
        all_calibrated_probabilities.extend(calibrated_probabilities.tolist())

    overall_raw = _probability_metrics(
        pd.Series(all_raw_truth), pd.Series(all_raw_probabilities)
    )
    overall_raw["expected_calibration_error"] = expected_calibration_error(
        pd.Series(all_raw_truth), pd.Series(all_raw_probabilities), bins=bins
    )

    overall_calibrated = _probability_metrics(
        pd.Series(all_calibrated_truth), pd.Series(all_calibrated_probabilities)
    )
    overall_calibrated["expected_calibration_error"] = expected_calibration_error(
        pd.Series(all_calibrated_truth),
        pd.Series(all_calibrated_probabilities),
        bins=bins,
    )

    result = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "spec": spec.name,
        "model_type": spec.model_type,
        "n_folds": folds,
        "initial_train_fraction": initial_train_fraction,
        "validation_fraction": validation_fraction,
        "bins": bins,
        "dataset": dataset.metadata,
        "overall_raw": overall_raw,
        "overall_calibrated": overall_calibrated,
        "fold_details": fold_results,
    }

    path = (output_dir or settings.data_dir / "models" / "calibrated_walkforward")
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / "calibrated_walkforward_report.json"
    report_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return {"output_path": str(report_path), **result}


def _predict_probabilities(
    model: Any, frame: pd.DataFrame, features: list[str]
) -> pd.Series:
    matrix = frame[features].apply(pd.to_numeric, errors="coerce")
    return pd.Series(model.predict_proba(matrix)[:, 1], index=frame.index)