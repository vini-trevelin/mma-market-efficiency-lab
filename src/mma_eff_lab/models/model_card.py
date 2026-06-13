from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.models.calibrated import CALIBRATED_CATBOOST_VERSION
from mma_eff_lab.models.dataset import FEATURE_COLUMNS, build_model_dataset


@dataclass
class ModelCard:
    model_version: str
    created_at_utc: str
    code_commit: str
    dataset_date_min: str | None
    dataset_date_max: str | None
    training_rows: int
    excluded_rows: int
    feature_count: int
    feature_set_name: str
    source_coverage_caveats: list[str]
    probability_contract: str
    train_window: dict[str, str] | None
    validation_window: dict[str, str] | None
    test_window: dict[str, str] | None
    metrics_summary: dict[str, Any]
    intended_use: list[str]
    not_intended_use: list[str]


def _get_code_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def write_model_card(
    model_version: str = CALIBRATED_CATBOOST_VERSION,
    output_dir: Path | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    model_dir = settings.data_dir / "models" / model_version
    metadata_path = model_dir / "metadata.json"
    metrics_path = model_dir / "metrics.json"

    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Model metadata not found at {metadata_path}. "
            f"Train the model first with train-calibrated-ufc-catboost."
        )

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metrics = {}
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    dataset = build_model_dataset(settings)
    code_commit = _get_code_commit()

    split_info = metadata.get("split", {})
    train_window = {
        "end_date": split_info.get("train_end_date"),
        "rows": split_info.get("train_rows"),
    } if split_info.get("train_end_date") else None
    validation_window = {
        "end_date": split_info.get("validation_end_date"),
        "rows": split_info.get("validation_rows"),
    } if split_info.get("validation_end_date") else None
    test_window = {
        "start_date": split_info.get("test_start_date"),
        "rows": split_info.get("test_rows"),
    } if split_info.get("test_start_date") else None

    source_caveats: list[str] = []
    ufcstats_coverage = _source_coverage(dataset, "ufcstats")
    sherdog_coverage = _source_coverage(dataset, "sherdog")
    if ufcstats_coverage is not None and sherdog_coverage is not None:
        if sherdog_coverage < ufcstats_coverage * 0.7:
            source_caveats.append(
                f"Sherdog coverage ({sherdog_coverage:.1%}) is substantially lower "
                f"than UFCStats coverage ({ufcstats_coverage:.1%})"
            )

    missingness = dataset.metadata.get("missingness", {})
    high_missing_features = [
        f for f, m in missingness.items() if m > 0.5
    ]
    if high_missing_features:
        source_caveats.append(
            f"High missingness features (>50%): {', '.join(high_missing_features)}"
        )

    walkforward_metrics = _load_walkforward_metrics(settings)

    card = ModelCard(
        model_version=model_version,
        created_at_utc=datetime.now(UTC).isoformat(),
        code_commit=code_commit,
        dataset_date_min=dataset.metadata.get("date_min"),
        dataset_date_max=dataset.metadata.get("date_max"),
        training_rows=dataset.metadata.get("training_rows", 0),
        excluded_rows=(
            dataset.metadata.get("excluded_draw_nc", 0)
            + dataset.metadata.get("excluded_invalid_label", 0)
        ),
        feature_count=len(FEATURE_COLUMNS),
        feature_set_name="expanded_rating_features",
        source_coverage_caveats=source_caveats,
        probability_contract="fighter_b_win_probability = 1 - fighter_a_win_probability",
        train_window=train_window,
        validation_window=validation_window,
        test_window=test_window,
        metrics_summary={
            "single_split": _flatten_metrics(metrics),
            "calibrated_walkforward": walkforward_metrics,
        },
        intended_use=[
            "Historical fight win-probability research",
            "Prospective fight probability estimation for analysis",
        ],
        not_intended_use=[
            "Betting automation or gambling decisions",
            "Medical or athlete safety decisions",
            "Claims of certainty about fight outcomes",
        ],
    )

    output = output_dir or settings.data_dir / "models" / "model_cards"
    output.mkdir(parents=True, exist_ok=True)

    card_path = output / f"{model_version}.json"
    card_data = asdict(card)
    card_path.write_text(json.dumps(card_data, indent=2, default=str), encoding="utf-8")

    registry_path = _write_registry(output, card_data)
    return {"card_path": str(card_path), "registry_path": str(registry_path)}


def _flatten_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                result[f"{key}_{sub_key}"] = sub_value
        else:
            result[key] = value
    return result


def _load_walkforward_metrics(settings: Settings) -> dict[str, Any] | None:
    wf_path = (
        settings.data_dir
        / "models"
        / "calibrated_walkforward"
        / "calibrated_walkforward_report.json"
    )
    if not wf_path.exists():
        return None
    wf_data = json.loads(wf_path.read_text(encoding="utf-8"))
    return {
        "overall_raw": wf_data.get("overall_raw"),
        "overall_calibrated": wf_data.get("overall_calibrated"),
        "n_folds": wf_data.get("n_folds"),
    }


def _source_coverage(dataset: Any, source: str) -> float | None:
    frame = dataset.frame
    source_frame = frame[frame["source"] == source]
    if frame.empty:
        return None
    total = len(frame)
    source_count = len(source_frame)
    return source_count / total if total > 0 else None


def _write_registry(output_dir: Path, card_data: dict[str, Any]) -> Path:
    registry_path = output_dir / "experiments.json"
    existing: list[dict[str, Any]] = []
    if registry_path.exists():
        try:
            existing = json.loads(registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            existing = []
    existing = [e for e in existing if e.get("model_version") != card_data["model_version"]]
    existing.append({
        "model_version": card_data["model_version"],
        "created_at_utc": card_data["created_at_utc"],
        "code_commit": card_data["code_commit"],
        "feature_count": card_data["feature_count"],
        "training_rows": card_data["training_rows"],
        "dataset_date_min": card_data["dataset_date_min"],
        "dataset_date_max": card_data["dataset_date_max"],
        "card_path": f"{card_data['model_version']}.json",
    })
    registry_path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
    return registry_path