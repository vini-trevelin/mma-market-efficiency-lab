from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.models.dataset import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    build_model_dataset,
    feature_matrix,
    target_vector,
)

MODEL_VERSION = "xgboost_fight_outcome_v1"


@dataclass(frozen=True)
class TemporalSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    cutoffs: dict[str, str]


def train_xgboost_model(
    settings: Settings | None = None,
    output_dir: Path | None = None,
    train_fraction: float = 0.7,
    validation_fraction: float = 0.15,
    n_estimators: int = 200,
    max_depth: int = 3,
    learning_rate: float = 0.05,
) -> dict[str, Any]:
    settings = settings or get_settings()
    dataset = build_model_dataset(settings)
    split = temporal_split(dataset.frame, train_fraction, validation_fraction)
    _validate_split(split)
    xgb_classifier = _xgb_classifier()

    model = xgb_classifier(
        objective="binary:logistic",
        eval_metric="logloss",
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        random_state=42,
        missing=float("nan"),
    )
    model.fit(
        feature_matrix(split.train),
        target_vector(split.train),
        eval_set=[(feature_matrix(split.validation), target_vector(split.validation))],
        verbose=False,
    )

    output = output_dir or settings.data_dir / "models" / MODEL_VERSION
    output.mkdir(parents=True, exist_ok=True)
    model_path = output / "model.json"
    metadata_path = output / "metadata.json"
    metrics_path = output / "metrics.json"
    model.save_model(model_path)

    metrics = {
        "validation": evaluate_frame(model, split.validation),
        "test": evaluate_frame(model, split.test),
        "test_by_source": evaluate_by_source(model, split.test),
    }
    metadata = {
        "model_version": MODEL_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "objective": "binary:logistic",
        "probability_contract": "fighter_b_win_probability = 1 - fighter_a_win_probability",
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "dataset": dataset.metadata,
        "split": {
            **split.cutoffs,
            "train_rows": len(split.train),
            "validation_rows": len(split.validation),
            "test_rows": len(split.test),
        },
        "hyperparameters": {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "subsample": 0.85,
            "colsample_bytree": 0.85,
            "reg_lambda": 1.0,
            "random_state": 42,
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    metrics_path.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    return {
        "model_path": str(model_path),
        "metadata_path": str(metadata_path),
        "metrics_path": str(metrics_path),
        "metrics": metrics,
    }


def temporal_split(
    frame: pd.DataFrame, train_fraction: float = 0.7, validation_fraction: float = 0.15
) -> TemporalSplit:
    if frame.empty:
        raise ValueError("Cannot split empty model dataset")
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("Split fractions must be between 0 and 1")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("Train + validation fractions must leave a test split")
    ordered = frame.sort_values(["event_date", "event_id", "fight_id"]).reset_index(drop=True)
    dates = sorted(ordered["event_date"].drop_duplicates())
    if len(dates) < 3:
        raise ValueError("Temporal split requires at least three distinct event dates")
    train_date_end = max(1, int(len(dates) * train_fraction))
    validation_date_end = max(
        train_date_end + 1,
        int(len(dates) * (train_fraction + validation_fraction)),
    )
    if validation_date_end >= len(dates):
        validation_date_end = len(dates) - 1
    train_dates = set(dates[:train_date_end])
    validation_dates = set(dates[train_date_end:validation_date_end])
    test_dates = set(dates[validation_date_end:])
    train = ordered[ordered["event_date"].isin(train_dates)].reset_index(drop=True)
    validation = ordered[ordered["event_date"].isin(validation_dates)].reset_index(drop=True)
    test = ordered[ordered["event_date"].isin(test_dates)].reset_index(drop=True)
    split = TemporalSplit(
        train=train,
        validation=validation,
        test=test,
        cutoffs={
            "train_end_date": str(train["event_date"].max()) if not train.empty else "",
            "validation_end_date": str(validation["event_date"].max())
            if not validation.empty
            else "",
            "test_start_date": str(test["event_date"].min()) if not test.empty else "",
        },
    )
    _validate_split(split)
    return split


def evaluate_frame(model: Any, frame: pd.DataFrame) -> dict[str, float | int | None]:
    if frame.empty:
        return {"rows": 0, "log_loss": None, "brier_score": None, "auc": None, "accuracy": None}
    y_true = target_vector(frame)
    probabilities = model.predict_proba(feature_matrix(frame))[:, 1]
    predictions = probabilities >= 0.5
    auc = roc_auc_score(y_true, probabilities) if y_true.nunique() == 2 else None
    return {
        "rows": int(len(frame)),
        "log_loss": float(log_loss(y_true, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y_true, probabilities)),
        "auc": float(auc) if auc is not None else None,
        "accuracy": float(accuracy_score(y_true, predictions)),
    }


def evaluate_by_source(model: Any, frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {
        str(source): evaluate_frame(model, group)
        for source, group in frame.groupby("source", dropna=False)
    }


def _validate_split(split: TemporalSplit) -> None:
    if split.train.empty or split.validation.empty or split.test.empty:
        raise ValueError("Temporal split produced an empty train, validation, or test partition")
    if split.train["event_date"].max() >= split.validation["event_date"].min():
        raise ValueError("Temporal split overlap: train ends after validation starts")
    if split.validation["event_date"].max() >= split.test["event_date"].min():
        raise ValueError("Temporal split overlap: validation ends after test starts")


def _xgb_classifier() -> Any:
    try:
        from xgboost import XGBClassifier
    except Exception as exc:  # pragma: no cover - environment-specific native dependency
        raise RuntimeError(
            "XGBoost could not be imported. On macOS, install OpenMP first with "
            "`brew install libomp`, then rerun the command."
        ) from exc
    return XGBClassifier
