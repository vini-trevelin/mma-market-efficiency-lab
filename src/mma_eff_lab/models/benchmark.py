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
    "delta_time_decayed_elo",
    "delta_elo_expected_win_prob",
    "delta_elo_uncertainty",
    "delta_glicko_like_rd",
    "delta_avg_opponent_pre_fight_elo",
    "delta_recent_3_opponent_pre_fight_elo",
    "delta_best_win_opponent_pre_fight_elo",
    "delta_worst_loss_opponent_pre_fight_elo",
    "delta_recent_3_win_rate",
    "delta_recent_5_win_rate",
]
NORMALIZED_STAT_FEATURE_COLUMNS = [
    "delta_sig_str_landed_per_min",
    "delta_sig_str_absorbed_per_min",
    "delta_td_landed_per_15min",
    "delta_td_attempted_per_15min",
    "delta_sub_attempts_per_15min",
    "delta_ctrl_sec_per_min",
]
BASELINE_FEATURE_COLUMNS = [
    feature
    for feature in FEATURE_COLUMNS
    if feature not in {*RATING_FEATURE_COLUMNS, *NORMALIZED_STAT_FEATURE_COLUMNS}
]

FEATURE_GROUPS: dict[str, list[str]] = {
    "record": [
        feature
        for feature in FEATURE_COLUMNS
        if any(
            feature.endswith(suffix)
            for suffix in (
                "prior_fights",
                "prior_wins",
                "prior_losses",
                "prior_draws",
                "prior_nc",
            )
        )
    ],
    "activity_bio": [
        feature
        for feature in FEATURE_COLUMNS
        if any(
            feature.endswith(suffix)
            for suffix in (
                "days_since_last_fight",
                "age_years",
                "height_in",
                "reach_in",
            )
        )
    ],
    "win_method": [
        feature
        for feature in FEATURE_COLUMNS
        if any(
            feature.endswith(suffix)
            for suffix in (
                "wins_by_ko_tko",
                "wins_by_sub",
                "wins_by_dec",
            )
        )
    ],
    "historical_averages": [
        feature
        for feature in FEATURE_COLUMNS
        if any(
            feature.endswith(suffix)
            for suffix in (
                "avg_fight_time_sec",
                "avg_sig_str_landed",
                "avg_sig_str_absorbed",
                "avg_td_landed",
                "avg_td_attempted",
                "avg_sub_attempts",
                "avg_ctrl_sec",
            )
        )
    ],
    "ufcstats_rates": NORMALIZED_STAT_FEATURE_COLUMNS,
    "rating": RATING_FEATURE_COLUMNS,
}

ABLATION_SPECS: list[dict[str, Any]] = [
    {"name": "all_features", "features": FEATURE_COLUMNS},
    {
        "name": "no_rating",
        "features": BASELINE_FEATURE_COLUMNS + NORMALIZED_STAT_FEATURE_COLUMNS,
    },
    {
        "name": "no_ufcstats_rates",
        "features": BASELINE_FEATURE_COLUMNS + RATING_FEATURE_COLUMNS,
    },
    {"name": "rating_only", "features": RATING_FEATURE_COLUMNS},
    {
        "name": "record_and_activity",
        "features": FEATURE_GROUPS["record"] + FEATURE_GROUPS["activity_bio"],
    },
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


def benchmark_ablation(
    settings: Settings | None = None,
    output_path: Path | None = None,
    folds: int = 8,
    initial_train_fraction: float = 0.5,
) -> dict[str, Any]:
    settings = settings or get_settings()
    dataset = build_model_dataset(settings)

    covered = set()
    for group_name, group_features in FEATURE_GROUPS.items():
        for f in group_features:
            assert f in FEATURE_COLUMNS, (
                f"Feature {f} in group {group_name} not in FEATURE_COLUMNS"
            )
            covered.add(f)
    assert covered == set(FEATURE_COLUMNS), (
        f"Feature groups cover {len(covered)} features "
        f"but FEATURE_COLUMNS has {len(FEATURE_COLUMNS)}"
    )
    assert len(covered) == len(FEATURE_COLUMNS), "Feature groups have duplicate entries"

    results = []
    for spec in ABLATION_SPECS:
        ablation_benchmark = BenchmarkSpec(
            name=spec["name"],
            model_type="xgboost",
            feature_columns=spec["features"],
        )
        result = _run_benchmark(
            ablation_benchmark, dataset.frame, folds, initial_train_fraction
        )
        result["feature_count"] = len(spec["features"])
        results.append(result)

    baseline_all = next(r for r in results if r["name"] == "all_features")
    baseline_wf = baseline_all["walk_forward"]["summary"]

    summary_rows = []
    for result in results:
        wf = result["walk_forward"]["summary"]
        delta_log_loss = None
        delta_brier = None
        if wf.get("log_loss") is not None and baseline_wf.get("log_loss") is not None:
            delta_log_loss = round(wf["log_loss"] - baseline_wf["log_loss"], 6)
        if wf.get("brier_score") is not None and baseline_wf.get("brier_score") is not None:
            delta_brier = round(wf["brier_score"] - baseline_wf["brier_score"], 6)
        summary_rows.append({
            "name": result["name"],
            "feature_count": result["feature_count"],
            "walk_forward_log_loss": wf.get("log_loss"),
            "walk_forward_brier_score": wf.get("brier_score"),
            "walk_forward_auc": wf.get("auc"),
            "walk_forward_accuracy": wf.get("accuracy"),
            "delta_log_loss_vs_all": delta_log_loss,
            "delta_brier_vs_all": delta_brier,
        })

    summary_rows.sort(key=lambda r: (r["walk_forward_log_loss"] or 999))

    report = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "dataset": dataset.metadata,
        "ablation_summary": summary_rows,
        "ablation_details": results,
        "feature_groups": {k: v for k, v in FEATURE_GROUPS.items()},
    }

    path = output_path or settings.data_dir / "models" / "ablation_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    md_path = path.with_suffix(".md")
    md_lines = [
        "# Feature Ablation Report",
        "",
        f"Generated: {report['created_at_utc']}",
        "",
        "| Spec | Features | WF Log Loss | WF Brier | WF AUC | Δ Log Loss | Δ Brier |",
        "|------|----------|-------------|-----------|--------|------------|---------|",
    ]
    for row in summary_rows:
        ll = (
            f"{row['walk_forward_log_loss']:.4f}"
            if row["walk_forward_log_loss"] is not None
            else "N/A"
        )
        brier = (
            f"{row['walk_forward_brier_score']:.4f}"
            if row["walk_forward_brier_score"] is not None
            else "N/A"
        )
        auc = (
            f"{row['walk_forward_auc']:.4f}"
            if row["walk_forward_auc"] is not None
            else "N/A"
        )
        dll = (
            f"{row['delta_log_loss_vs_all']:+.4f}"
            if row["delta_log_loss_vs_all"] is not None
            else "N/A"
        )
        db = (
            f"{row['delta_brier_vs_all']:+.4f}"
            if row["delta_brier_vs_all"] is not None
            else "N/A"
        )
        md_lines.append(
            f"| {row['name']} | {row['feature_count']} | {ll} | {brier} | {auc} | {dll} | {db} |"
        )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return {"output_path": str(path), "markdown_path": str(md_path), **report}
