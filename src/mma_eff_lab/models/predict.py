from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from mma_eff_lab.models.dataset import FEATURE_COLUMNS, feature_matrix
from mma_eff_lab.models.train import MODEL_VERSION


@dataclass(frozen=True)
class FightPrediction:
    fighter_a_win_probability: float
    fighter_b_win_probability: float
    model_version: str
    feature_coverage: dict[str, Any]


def load_xgboost_model(model_path: Path) -> Any:
    try:
        from xgboost import XGBClassifier
    except Exception as exc:  # pragma: no cover - environment-specific native dependency
        raise RuntimeError(
            "XGBoost could not be imported. On macOS, install OpenMP first with "
            "`brew install libomp`, then rerun the command."
        ) from exc
    model = XGBClassifier()
    model.load_model(model_path)
    return model


def load_model_metadata(metadata_path: Path) -> dict[str, Any]:
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def predict_fight_probability(
    model: Any,
    delta_features: dict[str, float | None],
    model_version: str = MODEL_VERSION,
) -> FightPrediction:
    row = {feature: delta_features.get(feature) for feature in FEATURE_COLUMNS}
    frame = pd.DataFrame([row], columns=FEATURE_COLUMNS)
    probability = float(model.predict_proba(feature_matrix(frame))[:, 1][0])
    probability = min(max(probability, 0.0), 1.0)
    return FightPrediction(
        fighter_a_win_probability=probability,
        fighter_b_win_probability=1.0 - probability,
        model_version=model_version,
        feature_coverage={
            "feature_count": len(FEATURE_COLUMNS),
            "present_count": int(frame.notna().sum(axis=1).iloc[0]),
            "missing_features": [feature for feature in FEATURE_COLUMNS if pd.isna(row[feature])],
        },
    )
