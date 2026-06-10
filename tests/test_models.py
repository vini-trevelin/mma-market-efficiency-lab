from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from mma_eff_lab.config import get_settings
from mma_eff_lab.features.pit import NUMERIC_FEATURES, build_pit_features
from mma_eff_lab.models.dataset import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    build_model_dataset,
    build_model_dataset_from_matchups,
)
from mma_eff_lab.models.predict import predict_fight_probability
from mma_eff_lab.models.train import temporal_split
from mma_eff_lab.warehouse.build import build_warehouse
from tests.test_warehouse_and_pit import _write_cached_fixture_tree, _write_cached_sherdog_tree


class _ConstantModel:
    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        assert list(frame.columns) == FEATURE_COLUMNS
        return np.array([[0.35, 0.65]])


def test_model_dataset_orients_labels_and_removes_red_blue_leakage(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    build_pit_features(settings)

    dataset = build_model_dataset(settings)

    assert dataset.metadata["excluded_draw_nc"] == 0
    assert dataset.metadata["training_rows"] == len(dataset.frame)
    assert TARGET_COLUMN in dataset.frame
    assert all(not column.startswith(("red_", "blue_")) for column in dataset.frame.columns)
    assert dataset.frame["fighter_a_id"].le(dataset.frame["fighter_b_id"]).all()
    assert set(FEATURE_COLUMNS).issubset(dataset.frame.columns)

    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        source_rows = conn.execute(
            """
            select m.fight_id, m.red_fighter_id, m.blue_fighter_id, red_part.winner_flag
            from pit_matchup_features m
            join fight_participants red_part
              on red_part.fight_id = m.fight_id
             and red_part.fighter_id = m.red_fighter_id
            """
        ).fetchall()
    red_winner_by_fight = {fight_id: bool(red_won) for fight_id, red_id, _, red_won in source_rows}
    red_is_a_by_fight = {
        fight_id: red_id <= blue_id for fight_id, red_id, blue_id, _ in source_rows
    }
    for row in dataset.frame.to_dict("records"):
        expected = (
            red_winner_by_fight[row["fight_id"]]
            if red_is_a_by_fight[row["fight_id"]]
            else not red_winner_by_fight[row["fight_id"]]
        )
        assert row[TARGET_COLUMN] == expected


def test_model_dataset_excludes_draws_no_contests_and_invalid_labels() -> None:
    row = {
        "fight_id": "f1",
        "event_id": "e1",
        "event_date": "2020-01-01",
        "red_fighter_id": "b",
        "blue_fighter_id": "a",
        "red_source": "ufcstats",
        "blue_source": "ufcstats",
        "red_promotion": "UFC",
        "blue_promotion": "UFC",
        "red_full_name": "B",
        "blue_full_name": "A",
        "red_winner_flag": True,
        "blue_winner_flag": False,
        "red_outcome": "W",
        "blue_outcome": "L",
    }
    for feature in FEATURE_COLUMNS:
        row[feature] = 1.0
    draw = {**row, "fight_id": "f2", "red_outcome": "D", "blue_outcome": "D"}
    invalid = {**row, "fight_id": "f3", "red_winner_flag": False, "blue_winner_flag": False}

    dataset = build_model_dataset_from_matchups(pd.DataFrame([row, draw, invalid]))

    assert len(dataset.frame) == 1
    assert dataset.metadata["excluded_draw_nc"] == 1
    assert dataset.metadata["excluded_invalid_label"] == 1
    assert dataset.frame.iloc[0]["fighter_a_id"] == "a"
    assert not bool(dataset.frame.iloc[0][TARGET_COLUMN])
    for feature in FEATURE_COLUMNS:
        assert dataset.frame.iloc[0][feature] == -1.0


def test_temporal_split_is_ordered() -> None:
    frame = pd.DataFrame(
        {
            "fight_id": [f"f{i}" for i in range(10)],
            "event_id": [f"e{i}" for i in range(10)],
            "event_date": pd.date_range("2020-01-01", periods=10, freq="D").date,
            "source": ["ufcstats"] * 10,
            TARGET_COLUMN: [i % 2 == 0 for i in range(10)],
            **{feature: [float(i) for i in range(10)] for feature in FEATURE_COLUMNS},
        }
    )

    split = temporal_split(frame, train_fraction=0.6, validation_fraction=0.2)

    assert len(split.train) == 6
    assert len(split.validation) == 2
    assert len(split.test) == 2
    assert split.train["event_date"].max() <= split.validation["event_date"].min()
    assert split.validation["event_date"].max() <= split.test["event_date"].min()


def test_temporal_split_does_not_split_same_event_date() -> None:
    event_dates = pd.to_datetime(
        ["2020-01-01", "2020-01-01", "2020-02-01", "2020-02-01", "2020-03-01", "2020-03-01"]
    ).date
    frame = pd.DataFrame(
        {
            "fight_id": [f"f{i}" for i in range(6)],
            "event_id": [f"e{i}" for i in range(6)],
            "event_date": event_dates,
            "source": ["ufcstats"] * 6,
            TARGET_COLUMN: [i % 2 == 0 for i in range(6)],
            **{feature: [float(i) for i in range(6)] for feature in FEATURE_COLUMNS},
        }
    )

    split = temporal_split(frame, train_fraction=0.34, validation_fraction=0.33)

    partitions = [split.train, split.validation, split.test]
    for date_value in set(event_dates):
        containing = [
            partition for partition in partitions if date_value in set(partition["event_date"])
        ]
        assert len(containing) == 1


def test_prediction_probability_contract() -> None:
    features = {f"delta_{feature}": 1.0 for feature in NUMERIC_FEATURES}

    prediction = predict_fight_probability(_ConstantModel(), features, model_version="test")

    assert prediction.model_version == "test"
    assert prediction.fighter_a_win_probability == 0.65
    assert prediction.fighter_b_win_probability == 0.35
    assert prediction.fighter_a_win_probability + prediction.fighter_b_win_probability == 1.0
    assert prediction.feature_coverage["present_count"] == len(FEATURE_COLUMNS)
