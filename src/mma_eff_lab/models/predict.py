from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.features.pit import build_future_matchup_features
from mma_eff_lab.models.calibrated import CALIBRATED_CATBOOST_VERSION, load_calibrated_catboost
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


def compute_swapped_probability_gap(
    model: Any,
    delta_features: dict[str, float | None],
    model_version: str = MODEL_VERSION,
) -> float:
    swapped_features = {
        feature: (-value if value is not None else None)
        for feature, value in delta_features.items()
        if feature in FEATURE_COLUMNS
    }
    original = predict_fight_probability(model, delta_features, model_version)
    swapped_prediction = predict_fight_probability(model, swapped_features, model_version)
    gap = abs(
        original.fighter_a_win_probability
        + swapped_prediction.fighter_a_win_probability
        - 1.0
    )
    return float(gap)


def predict_fight(
    fighter_a: str,
    fighter_b: str,
    event_date: date,
    model_version: str = MODEL_VERSION,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    fighter_a_id = resolve_fighter_id(fighter_a, settings)
    fighter_b_id = resolve_fighter_id(fighter_b, settings)
    features = build_future_matchup_features(fighter_a_id, fighter_b_id, event_date, settings)
    prediction = _predict_with_model_version(features, model_version, settings)
    return {
        "event_date": str(event_date),
        "fighter_a_id": fighter_a_id,
        "fighter_b_id": fighter_b_id,
        "fighter_a_name": features["fighter_a_name"],
        "fighter_b_name": features["fighter_b_name"],
        "fighter_a_win_probability": prediction.fighter_a_win_probability,
        "fighter_b_win_probability": prediction.fighter_b_win_probability,
        "model_version": prediction.model_version,
        "feature_coverage": prediction.feature_coverage,
    }


def predict_card(
    input_path: Path,
    output_path: Path | None = None,
    model_version: str = MODEL_VERSION,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    card = pd.read_csv(input_path)
    required = {"fighter_a", "fighter_b", "event_date"}
    missing = required - set(card.columns)
    if missing:
        raise ValueError(f"Card CSV missing required columns: {', '.join(sorted(missing))}")
    predictions = [
        predict_fight(
            str(row["fighter_a"]),
            str(row["fighter_b"]),
            pd.to_datetime(row["event_date"]).date(),
            model_version,
            settings,
        )
        for row in card.to_dict("records")
    ]
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(predictions).to_csv(output_path, index=False)
    return {
        "rows": len(predictions),
        "output_path": str(output_path) if output_path else None,
        "predictions": predictions,
    }


def _predict_with_model_version(
    features: dict[str, Any],
    model_version: str,
    settings: Settings,
) -> FightPrediction:
    if model_version == MODEL_VERSION:
        model_dir = settings.data_dir / "models" / MODEL_VERSION
        model = load_xgboost_model(model_dir / "model.json")
        metadata = load_model_metadata(model_dir / "metadata.json")
        return predict_fight_probability(model, features, metadata["model_version"])
    if model_version == CALIBRATED_CATBOOST_VERSION:
        bundle = load_calibrated_catboost(settings.data_dir / "models" / model_version)
        row = {feature: features.get(feature) for feature in FEATURE_COLUMNS}
        frame = pd.DataFrame([row], columns=FEATURE_COLUMNS)
        raw_probability = float(bundle.model.predict_proba(feature_matrix(frame))[:, 1][0])
        probability = float(bundle.calibrator.predict([raw_probability])[0])
        probability = min(max(probability, 0.0), 1.0)
        return FightPrediction(
            fighter_a_win_probability=probability,
            fighter_b_win_probability=1.0 - probability,
            model_version=bundle.metadata["model_version"],
            feature_coverage={
                "feature_count": len(FEATURE_COLUMNS),
                "present_count": int(frame.notna().sum(axis=1).iloc[0]),
                "missing_features": [
                    feature for feature in FEATURE_COLUMNS if pd.isna(row[feature])
                ],
                "raw_probability": raw_probability,
                "calibration": bundle.metadata.get("calibration"),
            },
        )
    raise ValueError(
        f"Unsupported model_version: {model_version}. "
        f"Expected {MODEL_VERSION} or {CALIBRATED_CATBOOST_VERSION}."
    )


def resolve_fighter_id(value: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        exact_id = conn.execute(
            "select fighter_id from fighters where fighter_id = ?",
            [value],
        ).fetchone()
        if exact_id:
            return str(exact_id[0])
        rows = conn.execute(
            """
            select fighter_id, full_name, source
            from fighters
            where lower(full_name) = lower(?)
            order by case when source = 'ufcstats' then 0 else 1 end, fighter_id
            """,
            [value],
        ).fetchall()
    if not rows:
        raise ValueError(f"Could not resolve fighter: {value}")
    ufc_rows = [row for row in rows if row[2] == "ufcstats"]
    candidates = ufc_rows or rows
    if len(candidates) > 1:
        formatted = ", ".join(f"{row[0]} ({row[1]}, {row[2]})" for row in candidates[:10])
        raise ValueError(f"Ambiguous fighter name: {value}. Candidates: {formatted}")
    return str(candidates[0][0])
