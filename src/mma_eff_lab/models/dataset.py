from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.features.pit import NUMERIC_FEATURES

TARGET_COLUMN = "fighter_a_won"
FEATURE_COLUMNS = [f"delta_{feature}" for feature in NUMERIC_FEATURES]
IDENTIFIER_COLUMNS = [
    "fight_id",
    "event_id",
    "event_date",
    "source",
    "promotion",
    "fighter_a_id",
    "fighter_b_id",
    "fighter_a_name",
    "fighter_b_name",
]
TRAINING_COLUMNS = [*IDENTIFIER_COLUMNS, TARGET_COLUMN, *FEATURE_COLUMNS]


@dataclass(frozen=True)
class ModelDataset:
    frame: pd.DataFrame
    metadata: dict[str, Any]


def build_model_dataset(settings: Settings | None = None) -> ModelDataset:
    settings = settings or get_settings()
    if not settings.warehouse_path.exists():
        raise FileNotFoundError(f"Warehouse not found: {settings.warehouse_path}")
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        source = conn.execute(_dataset_query()).fetchdf()
    return build_model_dataset_from_matchups(source)


def write_model_dataset(
    output_path: Path | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    dataset = build_model_dataset(settings)
    path = output_path or settings.warehouse_dir / "model_fight_outcomes.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset.frame.to_parquet(path, index=False)
    return {**dataset.metadata, "output_path": str(path)}


def build_model_dataset_from_matchups(source: pd.DataFrame) -> ModelDataset:
    rows: list[dict[str, Any]] = []
    excluded_draw_nc = 0
    excluded_invalid_label = 0
    for row in source.to_dict("records"):
        red_outcome = row.get("red_outcome")
        blue_outcome = row.get("blue_outcome")
        if red_outcome in {"D", "NC"} or blue_outcome in {"D", "NC"}:
            excluded_draw_nc += 1
            continue
        red_won = _as_bool(row.get("red_winner_flag"))
        blue_won = _as_bool(row.get("blue_winner_flag"))
        if red_won == blue_won:
            excluded_invalid_label += 1
            continue

        red_id = str(row["red_fighter_id"])
        blue_id = str(row["blue_fighter_id"])
        red_is_a = red_id <= blue_id
        output = {
            "fight_id": row["fight_id"],
            "event_id": row["event_id"],
            "event_date": row["event_date"],
            "source": row.get("red_source") or row.get("blue_source"),
            "promotion": row.get("red_promotion") or row.get("blue_promotion"),
            "fighter_a_id": red_id if red_is_a else blue_id,
            "fighter_b_id": blue_id if red_is_a else red_id,
            "fighter_a_name": row.get("red_full_name") if red_is_a else row.get("blue_full_name"),
            "fighter_b_name": row.get("blue_full_name") if red_is_a else row.get("red_full_name"),
            TARGET_COLUMN: red_won if red_is_a else blue_won,
        }
        sign = 1 if red_is_a else -1
        for feature in FEATURE_COLUMNS:
            output[feature] = _signed_value(row.get(feature), sign)
        rows.append(output)

    frame = pd.DataFrame(rows, columns=TRAINING_COLUMNS)
    if not frame.empty:
        frame["event_date"] = pd.to_datetime(frame["event_date"]).dt.date
        frame[TARGET_COLUMN] = frame[TARGET_COLUMN].astype(bool)
        frame = frame.sort_values(["event_date", "event_id", "fight_id"]).reset_index(drop=True)

    metadata = {
        "input_rows": int(len(source)),
        "training_rows": int(len(frame)),
        "excluded_draw_nc": int(excluded_draw_nc),
        "excluded_invalid_label": int(excluded_invalid_label),
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "orientation": "fighter_a_id is lexicographically first; deltas are fighter_a - fighter_b",
        "label_balance": _label_balance(frame),
        "missingness": _missingness(frame),
        "date_min": _date_extreme(frame, "min"),
        "date_max": _date_extreme(frame, "max"),
    }
    return ModelDataset(frame=frame, metadata=metadata)


def feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")


def target_vector(frame: pd.DataFrame) -> pd.Series:
    return frame[TARGET_COLUMN].astype(int)


def _dataset_query() -> str:
    features = ",\n              ".join(f"m.{feature}" for feature in FEATURE_COLUMNS)
    return f"""
            select
              m.fight_id,
              m.event_id,
              m.event_date,
              m.red_fighter_id,
              m.blue_fighter_id,
              m.red_source,
              m.blue_source,
              m.red_promotion,
              m.blue_promotion,
              m.red_full_name,
              m.blue_full_name,
              red_part.winner_flag as red_winner_flag,
              blue_part.winner_flag as blue_winner_flag,
              red_part.outcome as red_outcome,
              blue_part.outcome as blue_outcome,
              {features}
            from pit_matchup_features m
            join fight_participants red_part
              on red_part.fight_id = m.fight_id
             and red_part.event_id = m.event_id
             and red_part.fighter_id = m.red_fighter_id
            join fight_participants blue_part
              on blue_part.fight_id = m.fight_id
             and blue_part.event_id = m.event_id
             and blue_part.fighter_id = m.blue_fighter_id
            """


def _as_bool(value: Any) -> bool:
    if pd.isna(value):
        return False
    return bool(value)


def _signed_value(value: Any, sign: int) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value) * sign


def _label_balance(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {"fighter_a_wins": 0, "fighter_b_wins": 0}
    wins = int(frame[TARGET_COLUMN].sum())
    return {"fighter_a_wins": wins, "fighter_b_wins": int(len(frame) - wins)}


def _missingness(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {feature: 0.0 for feature in FEATURE_COLUMNS}
    return {
        feature: round(float(frame[feature].isna().mean()), 6)
        for feature in FEATURE_COLUMNS
    }


def _date_extreme(frame: pd.DataFrame, op: str) -> str | None:
    if frame.empty:
        return None
    value = getattr(frame["event_date"], op)()
    return str(value)
