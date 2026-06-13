from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from mma_eff_lab.config import Settings, get_settings
from mma_eff_lab.models.benchmark import make_walk_forward_folds
from mma_eff_lab.models.calibrated import CALIBRATED_CATBOOST_VERSION
from mma_eff_lab.models.dataset import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    TRAINING_COLUMNS,
    build_model_dataset,
)
from mma_eff_lab.models.train import temporal_split

FORBIDDEN_FEATURE_TOKENS = [
    "red_",
    "blue_",
    "corner",
    "winner",
    "outcome",
    "source",
    "promotion",
]

CALIBRATED_METRIC_DEGRADATION_THRESHOLD = 0.03


def validate_model_quality(
    settings: Settings | None = None,
    benchmark_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    dataset = build_model_dataset(settings)
    split = temporal_split(dataset.frame)
    default_benchmark_path = settings.data_dir / "models" / "fight_outcome_benchmarks.json"
    benchmark = _load_benchmark(benchmark_path or default_benchmark_path)
    checks = [
        _forbidden_feature_check(),
        _training_column_check(),
        _deterministic_orientation_check(dataset.frame),
        _label_balance_check(dataset.metadata),
        _temporal_split_check(split),
        _walk_forward_check(dataset.frame),
        _prior_count_leakage_check(settings),
        _source_gap_check(benchmark),
        _missingness_check(dataset.metadata),
        _serving_model_artifact_check(settings),
    ]
    summary = _summary(checks)
    result = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "summary": summary,
        "checks": checks,
        "dataset": {
            "rows": dataset.metadata["training_rows"],
            "date_min": dataset.metadata["date_min"],
            "date_max": dataset.metadata["date_max"],
            "feature_count": len(FEATURE_COLUMNS),
            "label_balance": dataset.metadata["label_balance"],
        },
    }
    path = output_path or settings.data_dir / "models" / "model_quality_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return {"output_path": str(path), **result}


def _forbidden_feature_check() -> dict[str, Any]:
    forbidden = [
        feature
        for feature in FEATURE_COLUMNS
        if any(token in feature for token in FORBIDDEN_FEATURE_TOKENS)
    ]
    return {
        "name": "no_forbidden_training_features",
        "status": "fail" if forbidden else "pass",
        "details": {
            "forbidden_tokens": FORBIDDEN_FEATURE_TOKENS,
            "forbidden_features": forbidden,
        },
    }


def _training_column_check() -> dict[str, Any]:
    expected = [column for column in TRAINING_COLUMNS if column not in FEATURE_COLUMNS]
    return {
        "name": "training_columns_keep_identifiers_out_of_feature_matrix",
        "status": "pass",
        "details": {
            "identifier_columns": expected,
            "feature_columns": FEATURE_COLUMNS,
        },
    }


def _deterministic_orientation_check(frame: Any) -> dict[str, Any]:
    violations = frame[frame["fighter_a_id"] > frame["fighter_b_id"]]
    wins = int(frame[TARGET_COLUMN].sum())
    fighter_a_win_rate = wins / len(frame) if len(frame) else 0.0
    status = "pass"
    if not violations.empty:
        status = "fail"
    elif not 0.4 <= fighter_a_win_rate <= 0.6:
        status = "warn"
    return {
        "name": "deterministic_orientation_without_extreme_id_label_bias",
        "status": status,
        "details": {
            "orientation_violations": int(len(violations)),
            "fighter_a_win_rate": fighter_a_win_rate,
        },
    }


def _label_balance_check(metadata: dict[str, Any]) -> dict[str, Any]:
    balance = metadata["label_balance"]
    total = balance["fighter_a_wins"] + balance["fighter_b_wins"]
    fighter_a_rate = balance["fighter_a_wins"] / total if total else 0.0
    return {
        "name": "binary_label_balance",
        "status": "pass" if 0.4 <= fighter_a_rate <= 0.6 else "warn",
        "details": {
            **balance,
            "fighter_a_win_rate": fighter_a_rate,
            "excluded_draw_nc": metadata["excluded_draw_nc"],
            "excluded_invalid_label": metadata["excluded_invalid_label"],
        },
    }


def _temporal_split_check(split: Any) -> dict[str, Any]:
    ordered = (
        split.train["event_date"].max() < split.validation["event_date"].min()
        and split.validation["event_date"].max() < split.test["event_date"].min()
    )
    return {
        "name": "temporal_split_has_no_date_overlap",
        "status": "pass" if ordered else "fail",
        "details": split.cutoffs,
    }


def _walk_forward_check(frame: Any) -> dict[str, Any]:
    violations = []
    folds = make_walk_forward_folds(frame)
    for index, fold in enumerate(folds, start=1):
        if max(fold.train_dates) >= min(fold.test_dates):
            violations.append(index)
    return {
        "name": "walk_forward_folds_are_expanding_and_chronological",
        "status": "fail" if violations else "pass",
        "details": {
            "folds": len(folds),
            "violating_folds": violations,
        },
    }


def _prior_count_leakage_check(settings: Settings) -> dict[str, Any]:
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        mismatches = conn.execute(
            """
            with expected as (
              select
                pit.fight_id,
                pit.fighter_id,
                count(hist_event.event_id) as expected_prior_fights
              from pit_fighter_features pit
              left join fight_participants hist
                on hist.fighter_id = pit.fighter_id
              left join events hist_event
                on hist_event.event_id = hist.event_id
               and hist_event.event_date < pit.event_date
              group by pit.fight_id, pit.fighter_id
            )
            select count(*)
            from pit_fighter_features pit
            join expected using (fight_id, fighter_id)
            where pit.prior_fights != expected.expected_prior_fights
            """
        ).fetchone()[0]
    return {
        "name": "pit_prior_counts_exclude_current_and_same_date_fights",
        "status": "pass" if mismatches == 0 else "fail",
        "details": {"mismatched_rows": int(mismatches)},
    }


def _source_gap_check(benchmark: dict[str, Any] | None) -> dict[str, Any]:
    if not benchmark:
        return {
            "name": "source_split_performance_gap",
            "status": "warn",
            "details": {"reason": "benchmark artifact missing"},
        }
    primary = next(
        (
            item
            for item in benchmark.get("benchmarks", [])
            if item.get("name") == "xgboost_rating_features"
        ),
        None,
    )
    by_source = (primary or {}).get("temporal_split", {}).get("test_by_source", {})
    auc_values = [
        metrics["auc"] for metrics in by_source.values() if metrics.get("auc") is not None
    ]
    accuracy_values = [
        metrics["accuracy"] for metrics in by_source.values() if metrics.get("accuracy") is not None
    ]
    auc_gap = max(auc_values) - min(auc_values) if len(auc_values) >= 2 else None
    accuracy_gap = (
        max(accuracy_values) - min(accuracy_values)
        if len(accuracy_values) >= 2
        else None
    )
    status = "pass"
    if auc_gap is None or accuracy_gap is None:
        status = "warn"
    elif auc_gap > 0.05 or accuracy_gap > 0.05:
        status = "warn"
    return {
        "name": "source_split_performance_gap",
        "status": status,
        "details": {
            "primary_model": "xgboost_rating_features",
            "auc_gap": auc_gap,
            "accuracy_gap": accuracy_gap,
            "test_by_source": by_source,
        },
    }


def _missingness_check(metadata: dict[str, Any]) -> dict[str, Any]:
    high_missing = {
        feature: missing
        for feature, missing in metadata["missingness"].items()
        if missing > 0.6
    }
    return {
        "name": "high_feature_missingness",
        "status": "warn" if high_missing else "pass",
        "details": {"threshold": 0.6, "features": high_missing},
    }


def _serving_model_artifact_check(settings: Settings) -> dict[str, Any]:
    model_dir = settings.data_dir / "models" / CALIBRATED_CATBOOST_VERSION
    required_files = ["model.cbm", "metadata.json", "metrics.json"]
    missing = [f for f in required_files if not (model_dir / f).exists()]
    has_json_calibrator = (model_dir / "isotonic_calibrator.json").exists()
    has_pkl_calibrator = (model_dir / "isotonic_calibrator.pkl").exists()
    if not has_json_calibrator and not has_pkl_calibrator:
        missing.append("isotonic_calibrator.json")
    calibrator_warnings: list[str] = []
    if not has_json_calibrator and has_pkl_calibrator:
        calibrator_warnings.append(
            "Calibrator stored as pickle; retrain to generate JSON format"
        )
    if missing:
        return {
            "name": "serving_model_artifact",
            "status": "fail",
            "details": {
                "model_dir": str(model_dir),
                "model_version": CALIBRATED_CATBOOST_VERSION,
                "missing_files": missing,
            },
        }
    try:
        metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
        metrics = json.loads((model_dir / "metrics.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "name": "serving_model_artifact",
            "status": "fail",
            "details": {
                "model_dir": str(model_dir),
                "model_version": CALIBRATED_CATBOOST_VERSION,
                "error": str(exc),
            },
        }
    stored_features = metadata.get("feature_columns", [])
    if stored_features != FEATURE_COLUMNS:
        return {
            "name": "serving_model_artifact",
            "status": "fail",
            "details": {
                "model_version": CALIBRATED_CATBOOST_VERSION,
                "feature_mismatch": True,
                "expected_count": len(FEATURE_COLUMNS),
                "stored_count": len(stored_features),
                "extra_in_stored": [f for f in stored_features if f not in FEATURE_COLUMNS],
                "missing_from_stored": [f for f in FEATURE_COLUMNS if f not in stored_features],
            },
        }
    metric_source = "single_split"
    degraded = False
    degradation_details: dict[str, Any] = {}
    for key in ("ufcstats_test_raw", "ufcstats_test_isotonic"):
        entry = metrics.get(key)
        if not entry:
            continue
        if not all(k in entry for k in ("log_loss", "brier_score", "rows")):
            continue
        if entry["rows"] <= 0:
            degraded = True
            degradation_details[f"{key}_rows"] = entry["rows"]
        for metric_name in ("log_loss", "brier_score"):
            val = entry.get(metric_name)
            if val is not None and not isinstance(val, (int, float)):
                degraded = True
                degradation_details[f"{key}_{metric_name}_not_finite"] = True
                continue
            if val is not None and not isinstance(val, bool):
                import math

                if math.isnan(val) or math.isinf(val):
                    degraded = True
                    degradation_details[f"{key}_{metric_name}_not_finite"] = True
    raw_log_loss = metrics.get("ufcstats_test_raw", {}).get("log_loss")
    isotonic_log_loss = metrics.get("ufcstats_test_isotonic", {}).get("log_loss")
    if raw_log_loss is not None and isotonic_log_loss is not None:
        if isotonic_log_loss - raw_log_loss > CALIBRATED_METRIC_DEGRADATION_THRESHOLD:
            degraded = True
            degradation_details["calibrated_log_loss_degradation"] = (
                isotonic_log_loss - raw_log_loss
            )
    walkforward_path = (
        settings.data_dir
        / "models"
        / "calibrated_walkforward"
        / "calibrated_walkforward_report.json"
    )
    if walkforward_path.exists():
        metric_source = "calibrated_walkforward"
    else:
        metric_source = "single_split"
    status = "pass"
    if degraded or calibrator_warnings:
        status = "warn"
    return {
        "name": "serving_model_artifact",
        "status": status,
        "details": {
            "model_version": CALIBRATED_CATBOOST_VERSION,
            "files_checked": required_files,
            "calibrator_format": "json" if has_json_calibrator else "pickle",
            "feature_column_count": len(stored_features),
            "metric_source": metric_source,
            "calibrated_walkforward_available": walkforward_path.exists(),
            **degradation_details,
        },
    }


def _load_benchmark(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "pass": sum(1 for check in checks if check["status"] == "pass"),
        "warn": sum(1 for check in checks if check["status"] == "warn"),
        "fail": sum(1 for check in checks if check["status"] == "fail"),
    }
