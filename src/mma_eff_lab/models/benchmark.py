from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.models.dataset import FEATURE_COLUMNS, TARGET_COLUMN, build_model_dataset
from mma_eff_lab.models.train import temporal_split

RATING_FEATURE_COLUMNS = [
    "delta_pre_fight_elo",
    "delta_elo_expected_win_prob",
    "delta_elo_uncertainty",
    "delta_recent_3_win_rate",
    "delta_recent_5_win_rate",
]
BASELINE_FEATURE_COLUMNS = [
    feature for feature in FEATURE_COLUMNS if feature not in RATING_FEATURE_COLUMNS
]


@dataclass(frozen=True)
class BenchmarkSpec:
    name: str
    model_type: str
    feature_columns: list[str]


@dataclass(frozen=True)
class WalkForwardFold:
    train_dates: list[Any]
    test_dates: list[Any]


def benchmark_fight_models(
    settings: Settings | None = None,
    output_path: Path | None = None,
    folds: int = 8,
    initial_train_fraction: float = 0.5,
) -> dict[str, Any]:
    settings = settings or get_settings()
    dataset = build_model_dataset(settings)
    results = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "dataset": dataset.metadata,
        "walk_forward": {
            "folds": folds,
            "initial_train_fraction": initial_train_fraction,
        },
        "benchmarks": [
            _run_benchmark(spec, dataset.frame, folds, initial_train_fraction)
            for spec in _benchmark_specs()
        ],
    }
    path = output_path or settings.data_dir / "models" / "fight_outcome_benchmarks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return {"output_path": str(path), **results}


def _benchmark_specs() -> list[BenchmarkSpec]:
    return [
        BenchmarkSpec(
            name="baseline_xgboost",
            model_type="xgboost",
            feature_columns=BASELINE_FEATURE_COLUMNS,
        ),
        BenchmarkSpec(
            name="xgboost_rating_features",
            model_type="xgboost",
            feature_columns=FEATURE_COLUMNS,
        ),
        BenchmarkSpec(
            name="catboost_rating_features",
            model_type="catboost",
            feature_columns=FEATURE_COLUMNS,
        ),
    ]


def _run_benchmark(
    spec: BenchmarkSpec,
    frame: pd.DataFrame,
    folds: int,
    initial_train_fraction: float,
) -> dict[str, Any]:
    split = temporal_split(frame)
    model = _fit_model(spec, split.train, split.validation)
    validation = _evaluate_model(model, split.validation, spec.feature_columns)
    test = _evaluate_model(model, split.test, spec.feature_columns)
    test_by_source = {
        str(source): _evaluate_model(model, group, spec.feature_columns)
        for source, group in split.test.groupby("source", dropna=False)
    }
    return {
        "name": spec.name,
        "model_type": spec.model_type,
        "feature_count": len(spec.feature_columns),
        "feature_columns": spec.feature_columns,
        "temporal_split": {
            "cutoffs": split.cutoffs,
            "validation": validation,
            "test": test,
            "test_by_source": test_by_source,
        },
        "walk_forward": _walk_forward_benchmark(spec, frame, folds, initial_train_fraction),
    }


def _walk_forward_benchmark(
    spec: BenchmarkSpec,
    frame: pd.DataFrame,
    folds: int,
    initial_train_fraction: float,
) -> dict[str, Any]:
    rows = []
    all_truth: list[int] = []
    all_probabilities: list[float] = []
    for fold_index, fold in enumerate(
        make_walk_forward_folds(frame, folds, initial_train_fraction),
        start=1,
    ):
        train = frame[frame["event_date"].isin(fold.train_dates)].reset_index(drop=True)
        test = frame[frame["event_date"].isin(fold.test_dates)].reset_index(drop=True)
        model = _fit_model(spec, train)
        probabilities = _predict_probabilities(model, test, spec.feature_columns)
        truth = _target_vector(test)
        all_truth.extend(truth.tolist())
        all_probabilities.extend(probabilities.tolist())
        rows.append(
            {
                "fold": fold_index,
                "train_end_date": str(max(fold.train_dates)),
                "test_start_date": str(min(fold.test_dates)),
                "test_end_date": str(max(fold.test_dates)),
                **_metrics(truth, probabilities),
            }
        )

    return {
        "summary": _metrics(pd.Series(all_truth), pd.Series(all_probabilities)),
        "folds": rows,
    }


def make_walk_forward_folds(
    frame: pd.DataFrame,
    folds: int = 8,
    initial_train_fraction: float = 0.5,
) -> list[WalkForwardFold]:
    if folds < 1:
        raise ValueError("Walk-forward folds must be positive")
    if not 0 < initial_train_fraction < 1:
        raise ValueError("Initial train fraction must be between 0 and 1")
    dates = sorted(frame["event_date"].drop_duplicates())
    if len(dates) < 3:
        raise ValueError("Walk-forward benchmark requires at least three distinct event dates")
    start = max(1, int(len(dates) * initial_train_fraction))
    if start >= len(dates):
        start = len(dates) - 1
    block_size = max(1, math.ceil((len(dates) - start) / folds))
    output = []
    for test_start in range(start, len(dates), block_size):
        test_end = min(len(dates), test_start + block_size)
        output.append(WalkForwardFold(dates[:test_start], dates[test_start:test_end]))
    return output


def _fit_model(
    spec: BenchmarkSpec,
    train: pd.DataFrame,
    validation: pd.DataFrame | None = None,
) -> Any:
    if spec.model_type == "xgboost":
        model = _xgboost_model()
        eval_set = None
        if validation is not None:
            eval_set = [
                (
                    _feature_matrix(validation, spec.feature_columns),
                    _target_vector(validation),
                )
            ]
        model.fit(
            _feature_matrix(train, spec.feature_columns),
            _target_vector(train),
            eval_set=eval_set,
            verbose=False,
        )
        return model
    if spec.model_type == "catboost":
        model = _catboost_model()
        eval_set = None
        if validation is not None:
            eval_set = (
                _feature_matrix(validation, spec.feature_columns),
                _target_vector(validation),
            )
        model.fit(
            _feature_matrix(train, spec.feature_columns),
            _target_vector(train),
            eval_set=eval_set,
            verbose=False,
        )
        return model
    raise ValueError(f"Unsupported benchmark model type: {spec.model_type}")


def _xgboost_model() -> Any:
    try:
        from xgboost import XGBClassifier
    except Exception as exc:  # pragma: no cover - environment-specific native dependency
        raise RuntimeError(
            "XGBoost could not be imported. On macOS, install OpenMP first with "
            "`brew install libomp`, then rerun the command."
        ) from exc
    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        random_state=42,
        missing=float("nan"),
    )


def _catboost_model() -> Any:
    try:
        from catboost import CatBoostClassifier
    except Exception as exc:  # pragma: no cover - optional native dependency
        raise RuntimeError("CatBoost could not be imported. Run `uv sync` and retry.") from exc
    return CatBoostClassifier(
        iterations=200,
        depth=3,
        learning_rate=0.05,
        loss_function="Logloss",
        eval_metric="Logloss",
        random_seed=42,
        allow_writing_files=False,
        verbose=False,
    )


def _evaluate_model(model: Any, frame: pd.DataFrame, features: list[str]) -> dict[str, Any]:
    probabilities = _predict_probabilities(model, frame, features)
    return _metrics(_target_vector(frame), probabilities)


def _predict_probabilities(model: Any, frame: pd.DataFrame, features: list[str]) -> pd.Series:
    probabilities = model.predict_proba(_feature_matrix(frame, features))[:, 1]
    return pd.Series(probabilities, index=frame.index)


def _metrics(truth: pd.Series, probabilities: pd.Series) -> dict[str, float | int | None]:
    if truth.empty:
        return {"rows": 0, "accuracy": None, "log_loss": None, "brier_score": None, "auc": None}
    predictions = probabilities >= 0.5
    auc = roc_auc_score(truth, probabilities) if truth.nunique() == 2 else None
    return {
        "rows": int(len(truth)),
        "accuracy": float(accuracy_score(truth, predictions)),
        "log_loss": float(log_loss(truth, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(truth, probabilities)),
        "auc": float(auc) if auc is not None else None,
    }


def _feature_matrix(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    return frame[features].apply(pd.to_numeric, errors="coerce")


def _target_vector(frame: pd.DataFrame) -> pd.Series:
    return frame[TARGET_COLUMN].astype(int)
