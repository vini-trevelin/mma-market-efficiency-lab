from __future__ import annotations

from mma_eff_lab.models.benchmark import ABLATION_SPECS, FEATURE_COLUMNS, FEATURE_GROUPS


def test_feature_groups_cover_all_features() -> None:
    covered = set()
    for group_features in FEATURE_GROUPS.values():
        covered.update(group_features)
    assert covered == set(FEATURE_COLUMNS), (
        f"Groups cover {len(covered)} features, FEATURE_COLUMNS has {len(FEATURE_COLUMNS)}"
    )


def test_feature_groups_have_no_duplicates() -> None:
    all_features: list[str] = []
    for group_features in FEATURE_GROUPS.values():
        all_features.extend(group_features)
    assert len(all_features) == len(set(all_features)), "Feature groups contain duplicates"


def test_ablation_spec_names_are_unique() -> None:
    names = [spec["name"] for spec in ABLATION_SPECS]
    assert len(names) == len(set(names))


def test_ablation_specs_reference_valid_features() -> None:
    feature_set = set(FEATURE_COLUMNS)
    for spec in ABLATION_SPECS:
        for feature in spec["features"]:
            assert feature in feature_set, f"Spec {spec['name']} has invalid feature {feature}"


def test_ablation_includes_all_features_spec() -> None:
    all_spec = next(spec for spec in ABLATION_SPECS if spec["name"] == "all_features")
    assert all_spec["features"] == FEATURE_COLUMNS