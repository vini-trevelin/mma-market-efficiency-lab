from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.models.benchmark import BenchmarkSpec, _catboost_model, _feature_matrix
from mma_eff_lab.models.calibration import (
    _fit_calibrators,
    _isotonic_predict,
    _probabilities,
    _probability_metrics,
)
from mma_eff_lab.models.dataset import FEATURE_COLUMNS, TARGET_COLUMN, build_model_dataset
from mma_eff_lab.models.train import temporal_split

CALIBRATED_CATBOOST_VERSION = "calibrated_ufc_catboost_v1"


@dataclass(frozen=True)
class CalibratedModelBundle:
    model: Any
    calibrator: Any
    metadata: dict[str, Any]


def train_calibrated_ufc_catboost(
    settings: Settings | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    dataset = build_model_dataset(settings)
    split = temporal_split(dataset.frame)
    spec = BenchmarkSpec(
        name=CALIBRATED_CATBOOST_VERSION,
        model_type="catboost",
        feature_columns=FEATURE_COLUMNS,
    )
    calibration_model = _catboost_model()
    calibration_model.fit(
        _feature_matrix(split.train, FEATURE_COLUMNS),
        split.train[TARGET_COLUMN].astype(int),
        eval_set=(
            _feature_matrix(split.validation, FEATURE_COLUMNS),
            split.validation[TARGET_COLUMN].astype(int),
        ),
        verbose=False,
    )
    validation_probabilities = _probabilities(
        calibration_model,
        split.validation,
        spec.feature_columns,
    )
    calibrator = _fit_calibrators(
        validation_probabilities,
        split.validation[TARGET_COLUMN].astype(int),
    ).isotonic

    final_train = pd.concat([split.train, split.validation], ignore_index=True)
    final_model = _catboost_model()
    final_model.fit(
        _feature_matrix(final_train, FEATURE_COLUMNS),
        final_train[TARGET_COLUMN].astype(int),
        verbose=False,
    )

    ufc_test = split.test[split.test["source"] == "ufcstats"].reset_index(drop=True)
    raw_test_probabilities = _probabilities(final_model, ufc_test, FEATURE_COLUMNS)
    calibrated_test_probabilities = _isotonic_predict(calibrator, raw_test_probabilities)
    metrics = {
        "ufcstats_test_raw": _probability_metrics(
            ufc_test[TARGET_COLUMN].astype(int),
            raw_test_probabilities,
        ),
        "ufcstats_test_isotonic": _probability_metrics(
            ufc_test[TARGET_COLUMN].astype(int),
            calibrated_test_probabilities,
        ),
    }

    output = output_dir or settings.data_dir / "models" / CALIBRATED_CATBOOST_VERSION
    output.mkdir(parents=True, exist_ok=True)
    model_path = output / "model.cbm"
    calibrator_path = output / "isotonic_calibrator.pkl"
    metadata_path = output / "metadata.json"
    metrics_path = output / "metrics.json"
    final_model.save_model(model_path)
    with calibrator_path.open("wb") as handle:
        pickle.dump(calibrator, handle)
    metadata = {
        "model_version": CALIBRATED_CATBOOST_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "model_type": "catboost",
        "calibration": "isotonic",
        "calibration_source": "ufcstats",
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "probability_contract": "fighter_b_win_probability = 1 - fighter_a_win_probability",
        "dataset": dataset.metadata,
        "split": {
            **split.cutoffs,
            "train_rows": len(split.train),
            "validation_rows": len(split.validation),
            "test_rows": len(split.test),
            "final_train_rows": len(final_train),
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    metrics_path.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    return {
        "model_path": str(model_path),
        "calibrator_path": str(calibrator_path),
        "metadata_path": str(metadata_path),
        "metrics_path": str(metrics_path),
        "metrics": metrics,
    }


def load_calibrated_catboost(model_dir: Path) -> CalibratedModelBundle:
    try:
        from catboost import CatBoostClassifier
    except Exception as exc:  # pragma: no cover - optional native dependency
        raise RuntimeError("CatBoost could not be imported. Run `uv sync` and retry.") from exc
    model = CatBoostClassifier()
    model.load_model(model_dir / "model.cbm")
    with (model_dir / "isotonic_calibrator.pkl").open("rb") as handle:
        calibrator = pickle.load(handle)
    metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    return CalibratedModelBundle(model=model, calibrator=calibrator, metadata=metadata)
