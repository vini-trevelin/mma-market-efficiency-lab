from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.models.benchmark import BenchmarkSpec, _benchmark_specs, _fit_model
from mma_eff_lab.models.dataset import TARGET_COLUMN, build_model_dataset
from mma_eff_lab.models.train import temporal_split


@dataclass(frozen=True)
class ProbabilityCalibrators:
    platt: LogisticRegression
    isotonic: IsotonicRegression


def evaluate_model_calibration(
    settings: Settings | None = None,
    output_dir: Path | None = None,
    source: str = "ufcstats",
    bins: int = 10,
) -> dict[str, Any]:
    settings = settings or get_settings()
    dataset = build_model_dataset(settings)
    split = temporal_split(dataset.frame)
    output = output_dir or settings.data_dir / "models" / "calibration"
    output.mkdir(parents=True, exist_ok=True)
    reports = [
        _evaluate_spec_calibration(
            spec,
            split.train,
            split.validation,
            split.test,
            source,
            output,
            bins,
        )
        for spec in _benchmark_specs()
        if spec.name != "baseline_xgboost"
    ]
    result = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source": source,
        "bins": bins,
        "split": split.cutoffs,
        "reports": reports,
    }
    path = output / "calibration_report.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return {"output_path": str(path), **result}


def _evaluate_spec_calibration(
    spec: BenchmarkSpec,
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
    source: str,
    output_dir: Path,
    bins: int,
) -> dict[str, Any]:
    model = _fit_model(spec, train)
    validation_probabilities = _probabilities(model, validation, spec.feature_columns)
    calibrators = _fit_calibrators(validation_probabilities, validation[TARGET_COLUMN].astype(int))

    evaluation_frame = test[test["source"] == source].reset_index(drop=True)
    raw_probabilities = _probabilities(model, evaluation_frame, spec.feature_columns)
    probability_sets = {
        "raw": raw_probabilities,
        "platt": _platt_predict(calibrators.platt, raw_probabilities),
        "isotonic": _isotonic_predict(calibrators.isotonic, raw_probabilities),
    }
    metrics = {
        name: _probability_metrics(evaluation_frame[TARGET_COLUMN].astype(int), probabilities)
        for name, probabilities in probability_sets.items()
    }
    curves = {
        name: _calibration_curve(evaluation_frame[TARGET_COLUMN].astype(int), probabilities, bins)
        for name, probabilities in probability_sets.items()
    }
    plot_path = output_dir / f"{spec.name}_{source}_calibration.png"
    _plot_calibration_curves(spec.name, curves, plot_path)
    return {
        "name": spec.name,
        "model_type": spec.model_type,
        "source": source,
        "rows": int(len(evaluation_frame)),
        "metrics": metrics,
        "curves": curves,
        "plot_path": str(plot_path),
    }


def _fit_calibrators(
    probabilities: pd.Series,
    target: pd.Series,
) -> ProbabilityCalibrators:
    platt = LogisticRegression(random_state=42)
    platt.fit(probabilities.to_numpy().reshape(-1, 1), target)
    isotonic = IsotonicRegression(out_of_bounds="clip")
    isotonic.fit(probabilities, target)
    return ProbabilityCalibrators(platt=platt, isotonic=isotonic)


def _probabilities(model: Any, frame: pd.DataFrame, features: list[str]) -> pd.Series:
    matrix = frame[features].apply(pd.to_numeric, errors="coerce")
    return pd.Series(model.predict_proba(matrix)[:, 1], index=frame.index)


def _platt_predict(model: LogisticRegression, probabilities: pd.Series) -> pd.Series:
    return pd.Series(model.predict_proba(probabilities.to_numpy().reshape(-1, 1))[:, 1])


def _isotonic_predict(model: IsotonicRegression, probabilities: pd.Series) -> pd.Series:
    return pd.Series(model.predict(probabilities))


def _probability_metrics(target: pd.Series, probabilities: pd.Series) -> dict[str, float | int]:
    return {
        "rows": int(len(target)),
        "accuracy": float(accuracy_score(target, probabilities >= 0.5)),
        "log_loss": float(log_loss(target, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(target, probabilities)),
        "auc": float(roc_auc_score(target, probabilities)),
    }


def expected_calibration_error(
    target: pd.Series,
    probabilities: pd.Series,
    bins: int = 10,
) -> float:
    if len(target) == 0 or len(probabilities) == 0:
        return 0.0
    frame = pd.DataFrame({"target": target, "probability": probabilities}).reset_index(drop=True)
    frame["bin"] = pd.cut(frame["probability"], bins=bins, labels=False, include_lowest=True)
    total = len(frame)
    if total == 0:
        return 0.0
    ece = 0.0
    for _, group in frame.groupby("bin", dropna=True):
        if group.empty:
            continue
        weight = len(group) / total
        mean_predicted = group["probability"].mean()
        observed_rate = group["target"].mean()
        ece += weight * abs(mean_predicted - observed_rate)
    return float(ece)


def _calibration_curve(
    target: pd.Series,
    probabilities: pd.Series,
    bins: int,
) -> list[dict[str, float | int]]:
    frame = pd.DataFrame({"target": target, "probability": probabilities})
    frame["bin"] = pd.cut(frame["probability"], bins=bins, labels=False, include_lowest=True)
    rows = []
    for _, group in frame.groupby("bin", dropna=True):
        if group.empty:
            continue
        rows.append(
            {
                "rows": int(len(group)),
                "mean_predicted_probability": float(group["probability"].mean()),
                "observed_win_rate": float(group["target"].mean()),
            }
        )
    return rows


def _plot_calibration_curves(
    name: str,
    curves: dict[str, list[dict[str, float | int]]],
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot([0, 1], [0, 1], linestyle="--", color="black", linewidth=1, label="perfect")
    for label, rows in curves.items():
        x = [float(row["mean_predicted_probability"]) for row in rows]
        y = [float(row["observed_win_rate"]) for row in rows]
        ax.plot(x, y, marker="o", label=label)
    ax.set_title(f"{name} calibration")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed win rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
