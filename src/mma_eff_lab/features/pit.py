from __future__ import annotations

from datetime import date
from math import sqrt
from typing import Any

import duckdb
import pandas as pd

from mma_eff_lab.config import Settings, ensure_data_dirs, get_settings

NUMERIC_FEATURES = [
    "prior_fights",
    "prior_wins",
    "prior_losses",
    "prior_draws",
    "prior_nc",
    "days_since_last_fight",
    "age_years",
    "height_in",
    "reach_in",
    "wins_by_ko_tko",
    "wins_by_sub",
    "wins_by_dec",
    "avg_fight_time_sec",
    "avg_sig_str_landed",
    "avg_sig_str_absorbed",
    "avg_td_landed",
    "avg_td_attempted",
    "avg_sub_attempts",
    "avg_ctrl_sec",
    "sig_str_landed_per_min",
    "sig_str_absorbed_per_min",
    "td_landed_per_15min",
    "td_attempted_per_15min",
    "sub_attempts_per_15min",
    "ctrl_sec_per_min",
    "pre_fight_elo",
    "time_decayed_elo",
    "elo_expected_win_prob",
    "elo_uncertainty",
    "glicko_like_rd",
    "avg_opponent_pre_fight_elo",
    "recent_3_opponent_pre_fight_elo",
    "best_win_opponent_pre_fight_elo",
    "worst_loss_opponent_pre_fight_elo",
    "recent_3_win_rate",
    "recent_5_win_rate",
]

INITIAL_ELO = 1500.0
ELO_K_FACTOR = 32.0
ELO_DECAY_HALF_LIFE_DAYS = 730.0
INITIAL_RATING_DEVIATION = 350.0
MIN_RATING_DEVIATION = 70.0


def build_pit_features(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        base = conn.execute(_base_query()).fetchdf()
        base = _add_pre_fight_ratings(base)
        fighter_features = _build_fighter_features(base)
        matchup_features = _build_matchup_features(fighter_features)
        conn.execute("drop table if exists pit_fighter_features")
        conn.register("pit_fighter_features_frame", fighter_features)
        conn.execute(
            "create table pit_fighter_features as select * from pit_fighter_features_frame"
        )
        conn.unregister("pit_fighter_features_frame")
        conn.execute("drop table if exists pit_matchup_features")
        conn.register("pit_matchup_features_frame", matchup_features)
        conn.execute(
            "create table pit_matchup_features as select * from pit_matchup_features_frame"
        )
        conn.unregister("pit_matchup_features_frame")
    return {
        "pit_fighter_features": len(fighter_features),
        "pit_matchup_features": len(matchup_features),
    }


def _base_query() -> str:
    return """
            select
              p.fight_id,
              p.event_id,
              e.event_date,
              p.fighter_id,
              p.opponent_id,
              p.source,
              p.promotion,
              p.corner,
              p.full_name,
              p.winner_flag,
              p.outcome,
              f.method,
              f.round,
              f.time,
              bio.dob,
              bio.height_in,
              bio.reach_in,
              s.sig_str_landed,
              opp.sig_str_landed as sig_str_absorbed,
              s.td_landed,
              s.td_attempted,
              s.sub_att,
              s.ctrl_sec
            from fight_participants p
            join events e using (event_id)
            join fights f using (fight_id, event_id)
            left join fighters bio using (fighter_id)
            left join fighter_fight_stats s
              on s.fight_id = p.fight_id and s.fighter_id = p.fighter_id
            left join fighter_fight_stats opp
              on opp.fight_id = p.fight_id and opp.fighter_id = p.opponent_id
            """


def build_future_matchup_features(
    fighter_a_id: str,
    fighter_b_id: str,
    event_date: date,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        base = conn.execute(_base_query()).fetchdf()
        fighters = conn.execute(
            """
            select fighter_id, full_name, dob, height_in, reach_in
            from fighters
            where fighter_id in (?, ?)
            """,
            [fighter_a_id, fighter_b_id],
        ).fetchdf()
    found = set(fighters["fighter_id"])
    if found != {fighter_a_id, fighter_b_id}:
        missing = sorted({fighter_a_id, fighter_b_id} - found)
        raise ValueError(f"Unknown fighter_id(s): {', '.join(missing)}")

    base = _add_pre_fight_ratings(base)
    ratings, last_fight_dates = _rating_snapshot(base, event_date)
    fighter_a = _future_fighter_features(
        base, fighters, ratings, last_fight_dates, fighter_a_id, fighter_b_id, event_date, "red"
    )
    fighter_b = _future_fighter_features(
        base, fighters, ratings, last_fight_dates, fighter_b_id, fighter_a_id, event_date, "blue"
    )
    output = {
        "fighter_a_id": fighter_a_id,
        "fighter_b_id": fighter_b_id,
        "fighter_a_name": fighter_a["full_name"],
        "fighter_b_name": fighter_b["full_name"],
        "event_date": event_date,
    }
    for feature in NUMERIC_FEATURES:
        output[f"delta_{feature}"] = _delta(fighter_a.get(feature), fighter_b.get(feature))
    return output


def _future_fighter_features(
    base: pd.DataFrame,
    fighters: pd.DataFrame,
    ratings: dict[str, float],
    last_fight_dates: dict[str, date],
    fighter_id: str,
    opponent_id: str,
    event_date: date,
    corner: str,
) -> dict[str, Any]:
    fighter = fighters[fighters["fighter_id"] == fighter_id].iloc[0].to_dict()
    raw_rating = ratings.get(fighter_id, INITIAL_ELO)
    opponent_rating = ratings.get(opponent_id, INITIAL_ELO)
    decayed_rating = _time_decayed_elo(raw_rating, last_fight_dates.get(fighter_id), event_date)
    opponent_decayed_rating = _time_decayed_elo(
        opponent_rating, last_fight_dates.get(opponent_id), event_date
    )
    current = {
        "fight_id": "future",
        "event_id": "future",
        "event_date": event_date,
        "fighter_id": fighter_id,
        "opponent_id": opponent_id,
        "source": "prediction",
        "promotion": "UFC",
        "corner": corner,
        "full_name": fighter["full_name"],
        "dob": _as_date(fighter.get("dob")),
        "height_in": fighter.get("height_in"),
        "reach_in": fighter.get("reach_in"),
        "pre_fight_elo": raw_rating,
        "time_decayed_elo": decayed_rating,
        "elo_expected_win_prob": _elo_expected(decayed_rating, opponent_decayed_rating),
    }
    history = base[
        (base["fighter_id"] == fighter_id)
        & (pd.to_datetime(base["event_date"]).dt.date < event_date)
    ].sort_values(["event_date", "fight_id"])
    return _feature_row(current, history)


def _build_fighter_features(base: pd.DataFrame) -> pd.DataFrame:
    if base.empty:
        return pd.DataFrame()
    base = base.copy()
    base["event_date"] = pd.to_datetime(base["event_date"]).dt.date
    if "dob" in base:
        base["dob"] = pd.to_datetime(base["dob"], errors="coerce").dt.date
    rows: list[dict[str, Any]] = []
    sorted_base = base.sort_values(["event_date", "event_id", "fight_id", "corner"])
    for current in sorted_base.to_dict("records"):
        history = base[
            (base["fighter_id"] == current["fighter_id"])
            & (base["event_date"] < current["event_date"])
        ].sort_values(["event_date", "fight_id"])
        rows.append(_feature_row(current, history))
    return pd.DataFrame(rows)


def _feature_row(current: dict[str, Any], history: pd.DataFrame) -> dict[str, Any]:
    prior_fights = int(len(history))
    current_date = current["event_date"]
    last_date = history["event_date"].max() if prior_fights else None
    output: dict[str, Any] = {
        "fight_id": current["fight_id"],
        "event_id": current["event_id"],
        "event_date": current_date,
        "fighter_id": current["fighter_id"],
        "opponent_id": current["opponent_id"],
        "source": current.get("source"),
        "promotion": current.get("promotion"),
        "corner": current["corner"],
        "full_name": current["full_name"],
        "prior_fights": prior_fights,
        "prior_wins": int(history["winner_flag"].fillna(False).sum()) if prior_fights else 0,
        "prior_losses": int((history["outcome"] == "L").sum()) if prior_fights else 0,
        "prior_draws": int((history["outcome"] == "D").sum()) if prior_fights else 0,
        "prior_nc": int((history["outcome"] == "NC").sum()) if prior_fights else 0,
        "days_since_last_fight": _days_between(last_date, current_date),
        "age_years": _age_years(current.get("dob"), current_date),
        "height_in": current.get("height_in"),
        "reach_in": current.get("reach_in"),
        "wins_by_ko_tko": _method_wins(history, ["KO", "TKO"]),
        "wins_by_sub": _method_wins(history, ["SUB"]),
        "wins_by_dec": _method_wins(history, ["DEC"]),
        "avg_fight_time_sec": _avg_fight_time(history),
        "avg_sig_str_landed": _mean(history, "sig_str_landed"),
        "avg_sig_str_absorbed": _mean(history, "sig_str_absorbed"),
        "avg_td_landed": _mean(history, "td_landed"),
        "avg_td_attempted": _mean(history, "td_attempted"),
        "avg_sub_attempts": _mean(history, "sub_att"),
        "avg_ctrl_sec": _mean(history, "ctrl_sec"),
        "sig_str_landed_per_min": _rate_per_minute(history, "sig_str_landed"),
        "sig_str_absorbed_per_min": _rate_per_minute(history, "sig_str_absorbed"),
        "td_landed_per_15min": _rate_per_15_minutes(history, "td_landed"),
        "td_attempted_per_15min": _rate_per_15_minutes(history, "td_attempted"),
        "sub_attempts_per_15min": _rate_per_15_minutes(history, "sub_att"),
        "ctrl_sec_per_min": _rate_per_minute(history, "ctrl_sec"),
        "pre_fight_elo": current.get("pre_fight_elo", INITIAL_ELO),
        "time_decayed_elo": current.get("time_decayed_elo", INITIAL_ELO),
        "elo_expected_win_prob": current.get("elo_expected_win_prob"),
        "elo_uncertainty": _elo_uncertainty(prior_fights),
        "glicko_like_rd": _glicko_like_rd(prior_fights, _days_between(last_date, current_date)),
        "avg_opponent_pre_fight_elo": _mean(history, "opponent_pre_fight_elo"),
        "recent_3_opponent_pre_fight_elo": _recent_mean(history, "opponent_pre_fight_elo", 3),
        "best_win_opponent_pre_fight_elo": _best_win_opponent_elo(history),
        "worst_loss_opponent_pre_fight_elo": _worst_loss_opponent_elo(history),
        "recent_3_win_rate": _recent_win_rate(history, 3),
        "recent_5_win_rate": _recent_win_rate(history, 5),
    }
    return output


def _build_matchup_features(fighter_features: pd.DataFrame) -> pd.DataFrame:
    if fighter_features.empty:
        return pd.DataFrame()
    red = fighter_features[fighter_features["corner"] == "red"].add_prefix("red_")
    blue = fighter_features[fighter_features["corner"] == "blue"].add_prefix("blue_")
    merged = red.merge(blue, left_on="red_fight_id", right_on="blue_fight_id", how="inner")
    rows: list[dict[str, Any]] = []
    for row in merged.to_dict("records"):
        out = {
            "fight_id": row["red_fight_id"],
            "event_id": row["red_event_id"],
            "event_date": row["red_event_date"],
            "red_fighter_id": row["red_fighter_id"],
            "blue_fighter_id": row["blue_fighter_id"],
            "red_source": row.get("red_source"),
            "blue_source": row.get("blue_source"),
            "red_promotion": row.get("red_promotion"),
            "blue_promotion": row.get("blue_promotion"),
            "red_full_name": row["red_full_name"],
            "blue_full_name": row["blue_full_name"],
        }
        for feature in NUMERIC_FEATURES:
            out[f"red_{feature}"] = row.get(f"red_{feature}")
            out[f"blue_{feature}"] = row.get(f"blue_{feature}")
            out[f"delta_{feature}"] = _delta(row.get(f"red_{feature}"), row.get(f"blue_{feature}"))
        rows.append(out)
    return pd.DataFrame(rows)


def _days_between(left: date | None, right: date) -> int | None:
    if left is None or pd.isna(left):
        return None
    return (right - left).days


def _as_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _age_years(dob: date | None, event_date: date) -> float | None:
    if dob is None or pd.isna(dob):
        return None
    return round((event_date - dob).days / 365.25, 3)


def _method_wins(history: pd.DataFrame, tokens: list[str]) -> int:
    if history.empty:
        return 0
    wins = history[history["winner_flag"].fillna(False)]
    if wins.empty:
        return 0
    methods = wins["method"].fillna("").str.upper()
    return int(methods.apply(lambda value: any(token in value for token in tokens)).sum())


def _avg_fight_time(history: pd.DataFrame) -> float | None:
    if history.empty:
        return None
    seconds = []
    for row in history.to_dict("records"):
        value = _fight_time_seconds(row)
        if value is not None:
            seconds.append(value)
    return sum(seconds) / len(seconds) if seconds else None


def _fight_time_seconds(row: dict[str, Any]) -> int | None:
    round_number = row.get("round")
    time_value = row.get("time")
    if pd.isna(round_number) or not isinstance(time_value, str) or ":" not in time_value:
        return None
    minute, second = [int(part) for part in time_value.split(":", 1)]
    return (int(round_number) - 1) * 300 + minute * 60 + second


def _mean(history: pd.DataFrame, column: str) -> float | None:
    if history.empty or column not in history:
        return None
    series = pd.to_numeric(history[column], errors="coerce").dropna()
    return float(series.mean()) if not series.empty else None


def _recent_mean(history: pd.DataFrame, column: str, window: int) -> float | None:
    if history.empty or column not in history:
        return None
    recent = history.sort_values(["event_date", "fight_id"]).tail(window)
    return _mean(recent, column)


def _rate_per_minute(history: pd.DataFrame, column: str) -> float | None:
    total_seconds = _total_fight_seconds(history)
    if total_seconds is None or total_seconds <= 0:
        return None
    total = pd.to_numeric(history[column], errors="coerce").sum(min_count=1)
    if pd.isna(total):
        return None
    return float(total) / (total_seconds / 60.0)


def _rate_per_15_minutes(history: pd.DataFrame, column: str) -> float | None:
    per_minute = _rate_per_minute(history, column)
    return None if per_minute is None else per_minute * 15.0


def _total_fight_seconds(history: pd.DataFrame) -> float | None:
    if history.empty:
        return None
    seconds = [_fight_time_seconds(row) for row in history.to_dict("records")]
    seconds = [value for value in seconds if value is not None]
    return float(sum(seconds)) if seconds else None


def _add_pre_fight_ratings(base: pd.DataFrame) -> pd.DataFrame:
    if base.empty:
        return base
    output = base.copy()
    output["event_date"] = pd.to_datetime(output["event_date"]).dt.date
    ratings: dict[str, float] = {}
    last_fight_dates: dict[str, date] = {}
    pre_fight_elo: dict[tuple[str, str], float] = {}
    time_decayed_elo: dict[tuple[str, str], float] = {}
    expected_win_prob: dict[tuple[str, str], float] = {}
    opponent_pre_fight_elo: dict[tuple[str, str], float] = {}

    for event_date, date_group in output.sort_values(
        ["event_date", "event_id", "fight_id", "corner"]
    ).groupby("event_date", sort=True):
        del event_date
        updates: list[tuple[str, float]] = []
        for _, fight_group in date_group.groupby("fight_id", sort=True):
            participants = fight_group.to_dict("records")
            if len(participants) != 2:
                continue
            first, second = participants
            first_id = str(first["fighter_id"])
            second_id = str(second["fighter_id"])
            first_rating = ratings.get(first_id, INITIAL_ELO)
            second_rating = ratings.get(second_id, INITIAL_ELO)
            current_date = first["event_date"]
            first_decayed = _time_decayed_elo(
                first_rating, last_fight_dates.get(first_id), current_date
            )
            second_decayed = _time_decayed_elo(
                second_rating, last_fight_dates.get(second_id), current_date
            )
            first_expected = _elo_expected(first_decayed, second_decayed)
            second_expected = 1.0 - first_expected
            pre_fight_elo[(str(first["fight_id"]), first_id)] = first_rating
            pre_fight_elo[(str(second["fight_id"]), second_id)] = second_rating
            time_decayed_elo[(str(first["fight_id"]), first_id)] = first_decayed
            time_decayed_elo[(str(second["fight_id"]), second_id)] = second_decayed
            expected_win_prob[(str(first["fight_id"]), first_id)] = first_expected
            expected_win_prob[(str(second["fight_id"]), second_id)] = second_expected
            opponent_pre_fight_elo[(str(first["fight_id"]), first_id)] = second_decayed
            opponent_pre_fight_elo[(str(second["fight_id"]), second_id)] = first_decayed

            first_outcome = first.get("outcome")
            second_outcome = second.get("outcome")
            last_fight_dates[first_id] = first["event_date"]
            last_fight_dates[second_id] = second["event_date"]
            if first_outcome in {"D", "NC"} or second_outcome in {"D", "NC"}:
                continue
            first_won = _bool_or_none(first.get("winner_flag"))
            second_won = _bool_or_none(second.get("winner_flag"))
            if first_won is None or second_won is None or first_won == second_won:
                continue
            first_score = 1.0 if first_won else 0.0
            second_score = 1.0 - first_score
            updates.append(
                (first_id, first_decayed + ELO_K_FACTOR * (first_score - first_expected))
            )
            updates.append(
                (second_id, second_decayed + ELO_K_FACTOR * (second_score - second_expected))
            )
        for fighter_id, updated_rating in updates:
            ratings[fighter_id] = updated_rating

    keys = list(zip(output["fight_id"].astype(str), output["fighter_id"].astype(str), strict=True))
    output["pre_fight_elo"] = [pre_fight_elo.get(key, INITIAL_ELO) for key in keys]
    output["time_decayed_elo"] = [time_decayed_elo.get(key, INITIAL_ELO) for key in keys]
    output["elo_expected_win_prob"] = [expected_win_prob.get(key) for key in keys]
    output["opponent_pre_fight_elo"] = [opponent_pre_fight_elo.get(key) for key in keys]
    return output


def _rating_snapshot(
    base: pd.DataFrame,
    as_of_date: date,
) -> tuple[dict[str, float], dict[str, date]]:
    ratings: dict[str, float] = {}
    last_fight_dates: dict[str, date] = {}
    historical = base[pd.to_datetime(base["event_date"]).dt.date < as_of_date]
    for event_date, date_group in historical.sort_values(
        ["event_date", "event_id", "fight_id", "corner"]
    ).groupby("event_date", sort=True):
        updates: list[tuple[str, float]] = []
        for _, fight_group in date_group.groupby("fight_id", sort=True):
            participants = fight_group.to_dict("records")
            if len(participants) != 2:
                continue
            first, second = participants
            first_id = str(first["fighter_id"])
            second_id = str(second["fighter_id"])
            first_rating = _time_decayed_elo(
                ratings.get(first_id, INITIAL_ELO), last_fight_dates.get(first_id), event_date
            )
            second_rating = _time_decayed_elo(
                ratings.get(second_id, INITIAL_ELO), last_fight_dates.get(second_id), event_date
            )
            first_expected = _elo_expected(first_rating, second_rating)
            first_outcome = first.get("outcome")
            second_outcome = second.get("outcome")
            last_fight_dates[first_id] = event_date
            last_fight_dates[second_id] = event_date
            if first_outcome in {"D", "NC"} or second_outcome in {"D", "NC"}:
                continue
            first_won = _bool_or_none(first.get("winner_flag"))
            second_won = _bool_or_none(second.get("winner_flag"))
            if first_won is None or second_won is None or first_won == second_won:
                continue
            first_score = 1.0 if first_won else 0.0
            second_score = 1.0 - first_score
            updates.append(
                (first_id, first_rating + ELO_K_FACTOR * (first_score - first_expected))
            )
            updates.append(
                (
                    second_id,
                    second_rating + ELO_K_FACTOR * (second_score - (1.0 - first_expected)),
                )
            )
        for fighter_id, updated_rating in updates:
            ratings[fighter_id] = updated_rating
    return ratings, last_fight_dates


def _time_decayed_elo(
    rating: float,
    last_fight_date: date | None,
    current_date: date,
) -> float:
    if last_fight_date is None or pd.isna(last_fight_date):
        return rating
    days = max(0, (current_date - last_fight_date).days)
    retained = 0.5 ** (days / ELO_DECAY_HALF_LIFE_DAYS)
    return INITIAL_ELO + (rating - INITIAL_ELO) * retained


def _elo_expected(left_rating: float, right_rating: float) -> float:
    return 1.0 / (1.0 + 10 ** ((right_rating - left_rating) / 400.0))


def _bool_or_none(value: Any) -> bool | None:
    if pd.isna(value):
        return None
    return bool(value)


def _elo_uncertainty(prior_fights: int) -> float:
    return 1.0 / sqrt(prior_fights + 1)


def _glicko_like_rd(prior_fights: int, days_since_last_fight: int | None) -> float:
    shrinkage = INITIAL_RATING_DEVIATION / sqrt(prior_fights + 1)
    inactivity = (
        0.0 if days_since_last_fight is None else min(days_since_last_fight / 365.25, 3.0) * 20.0
    )
    return max(MIN_RATING_DEVIATION, min(INITIAL_RATING_DEVIATION, shrinkage + inactivity))


def _recent_win_rate(history: pd.DataFrame, window: int) -> float | None:
    if history.empty:
        return None
    recent = history.sort_values(["event_date", "fight_id"]).tail(window)
    decisions = recent[recent["outcome"].isin(["W", "L"])]
    if decisions.empty:
        return None
    return float(decisions["winner_flag"].fillna(False).mean())


def _best_win_opponent_elo(history: pd.DataFrame) -> float | None:
    if history.empty or "opponent_pre_fight_elo" not in history:
        return None
    wins = history[history["winner_flag"].fillna(False)]
    if wins.empty:
        return None
    values = pd.to_numeric(wins["opponent_pre_fight_elo"], errors="coerce").dropna()
    return float(values.max()) if not values.empty else None


def _worst_loss_opponent_elo(history: pd.DataFrame) -> float | None:
    if history.empty or "opponent_pre_fight_elo" not in history:
        return None
    losses = history[history["outcome"] == "L"]
    if losses.empty:
        return None
    values = pd.to_numeric(losses["opponent_pre_fight_elo"], errors="coerce").dropna()
    return float(values.min()) if not values.empty else None


def _delta(left: object, right: object) -> float | None:
    if left is None or right is None or pd.isna(left) or pd.isna(right):
        return None
    return float(left) - float(right)
