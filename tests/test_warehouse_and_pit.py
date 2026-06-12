from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb

from mma_eff_lab.config import get_settings
from mma_eff_lab.features.pit import build_pit_features
from mma_eff_lab.warehouse.build import MANUAL_OVERRIDE_TABLE, build_warehouse
from tests.test_sherdog_parser import (
    SHERDOG_BLUE_ID,
    SHERDOG_EVENT_ID,
    SHERDOG_RED_ID,
    sherdog_event_html,
    sherdog_fighter_html,
)
from tests.test_ufcstats_parser import (
    BLUE_ID,
    EVENT_ID_1,
    FIGHT_ID_1,
    RED_ID,
    event_detail_html,
    fight_detail_html,
    fighter_html,
)

EVENT_ID_2 = "cccccccccccccccc"
EVENT_ID_3 = "eeeeeeeeeeeeeeee"
FIGHT_ID_2 = "dddddddddddddddd"
FIGHT_ID_3 = "ffffffffffffffff"
UFC_ALT_ID_1 = "3333333333333333"
UFC_ALT_ID_2 = "4444444444444444"
SHERDOG_ALT_ID = "77777"


def _write_cached_fixture_tree(
    root: Path,
    red_name: str = "Red Fighter",
    red_title_name: str | None = None,
) -> None:
    raw = root / "data" / "raw" / "ufcstats"
    (raw / "events").mkdir(parents=True)
    (raw / "fights").mkdir(parents=True)
    (raw / "fighters").mkdir(parents=True)
    (raw / "events" / f"{EVENT_ID_1}.html").write_text(event_detail_html(), encoding="utf-8")
    same_day = event_detail_html(EVENT_ID_2, FIGHT_ID_2).replace("UFC Test 1", "UFC Test 2")
    same_day = same_day.replace(FIGHT_ID_1, FIGHT_ID_2)
    (raw / "events" / f"{EVENT_ID_2}.html").write_text(same_day, encoding="utf-8")
    later = event_detail_html(EVENT_ID_3, FIGHT_ID_3).replace(
        "January 01, 2020", "February 01, 2020"
    )
    later = later.replace("UFC Test 1", "UFC Test 3").replace(FIGHT_ID_1, FIGHT_ID_3)
    (raw / "events" / f"{EVENT_ID_3}.html").write_text(later, encoding="utf-8")
    for fight_id in [FIGHT_ID_1, FIGHT_ID_2, FIGHT_ID_3]:
        (raw / "fights" / f"{fight_id}.html").write_text(fight_detail_html(), encoding="utf-8")
    (raw / "fighters" / f"{RED_ID}.html").write_text(
        fighter_html(red_name, title_name=red_title_name), encoding="utf-8"
    )
    (raw / "fighters" / f"{BLUE_ID}.html").write_text(
        fighter_html("Blue Fighter").replace("5' 11\"", "5' 9\""), encoding="utf-8"
    )


def _write_cached_sherdog_tree(
    root: Path,
    duplicate_match_row: bool = False,
    red_name: str = "Red Fighter",
) -> None:
    raw = root / "data" / "raw" / "sherdog"
    (raw / "events").mkdir(parents=True)
    (raw / "fighters").mkdir(parents=True)
    event_html = sherdog_event_html(
        event_id=SHERDOG_EVENT_ID,
        red_id=SHERDOG_RED_ID,
        blue_id=SHERDOG_BLUE_ID,
        include_result_table=duplicate_match_row,
        duplicate_match_row=duplicate_match_row,
    ).replace("Apr 11, 2014", "Jan 01, 2019")
    (raw / "events" / f"{SHERDOG_EVENT_ID}.html").write_text(event_html, encoding="utf-8")
    (raw / "fighters" / f"{SHERDOG_RED_ID}.html").write_text(
        sherdog_fighter_html(red_name), encoding="utf-8"
    )
    (raw / "fighters" / f"{SHERDOG_BLUE_ID}.html").write_text(
        sherdog_fighter_html("Blue Fighter"), encoding="utf-8"
    )


def _write_extra_ufc_fighter(
    root: Path, fighter_id: str, name: str, dob: str = "Jan 1, 1990"
) -> None:
    raw = root / "data" / "raw" / "ufcstats" / "fighters"
    raw.mkdir(parents=True, exist_ok=True)
    raw.joinpath(f"{fighter_id}.html").write_text(
        fighter_html(name, title_name=name).replace("January 01, 1990", dob),
        encoding="utf-8",
    )


def _write_extra_sherdog_fighter(
    root: Path, fighter_id: str, name: str, dob: str = "Jan 1, 1990"
) -> None:
    raw = root / "data" / "raw" / "sherdog" / "fighters"
    raw.mkdir(parents=True, exist_ok=True)
    raw.joinpath(f"{fighter_id}.html").write_text(
        sherdog_fighter_html(name, dob=dob),
        encoding="utf-8",
    )


def _write_manual_override(
    warehouse_path: Path,
    source_fighter_id: str,
    target_source_fighter_id: str,
    decision: str,
    note: str | None = None,
) -> None:
    target_value = target_source_fighter_id or None
    with duckdb.connect(str(warehouse_path)) as conn:
        conn.execute(
            f"""
            create table if not exists {MANUAL_OVERRIDE_TABLE}(
              source varchar,
              source_fighter_id varchar,
              target_source varchar,
              target_source_fighter_id varchar,
              decision varchar,
              note varchar,
              created_at_utc varchar,
              updated_at_utc varchar
            )
            """
        )
        conn.execute(
            f"""
            insert into {MANUAL_OVERRIDE_TABLE}
            values (
              'sherdog',
              ?,
              'ufcstats',
              ?,
              ?,
              ?,
              '2026-01-01T00:00:00+00:00',
              '2026-01-01T00:00:00+00:00'
            )
            """,
            [source_fighter_id, target_value, decision, note],
        )


def test_warehouse_builds_core_tables(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    counts = build_warehouse(settings)
    assert counts["events"] == 3
    assert counts["fights"] == 3
    assert counts["fight_participants"] == 6
    assert counts["source_events"] == 3
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        assert conn.execute("select count(distinct fight_id) from fights").fetchone()[0] == 3
        assert conn.execute("select distinct source from events").fetchall() == [("ufcstats",)]


def test_pit_features_exclude_current_and_same_date_fights(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    counts = build_pit_features(settings)
    assert counts["pit_fighter_features"] == 6
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        rows = conn.execute(
            """
            select fight_id, fighter_id, prior_fights, prior_wins
            from pit_fighter_features
            where fighter_id = ?
            order by event_date, fight_id
            """,
            [f"ufcstats:{RED_ID}"],
        ).fetchall()
    assert rows[0][2] == 0
    assert rows[1][2] == 0
    assert rows[2][2] == 2
    assert rows[2][3] == 2


def test_sherdog_history_supplements_linked_ufc_pit_features(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    counts = build_warehouse(settings)
    assert counts["source_events"] == 4
    assert counts["events"] == 4
    build_pit_features(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        link_method = conn.execute(
            """
            select link_method from fighter_identity_links
            where source = 'sherdog' and source_fighter_id = ?
            """,
            [SHERDOG_RED_ID],
        ).fetchone()[0]
        prior = conn.execute(
            """
            select prior_fights, prior_wins
            from pit_fighter_features
            where source = 'ufcstats'
              and event_date = date '2020-01-01'
              and fighter_id = ?
            order by fight_id
            limit 1
            """,
            [f"ufcstats:{RED_ID}"],
        ).fetchone()
    assert link_method == "exact_name_dob"
    assert prior == (1, 1)


def test_invalid_sherdog_fight_shape_is_quarantined_and_excluded(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path, duplicate_match_row=True)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    counts = build_warehouse(settings)
    assert counts["parse_quarantine"] == 1
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        sherdog_fights = conn.execute(
            "select count(*) from fights where source = 'sherdog'"
        ).fetchone()[0]
        quarantine_reason = conn.execute(
            "select reason from parse_quarantine limit 1"
        ).fetchone()[0]
    assert sherdog_fights == 0
    assert quarantine_reason == "invalid_participant_shape"


def test_cleaned_name_dob_links_nickname_variants(tmp_path: Path) -> None:
    _write_cached_fixture_tree(
        tmp_path,
        red_name="Red Fighter",
        red_title_name="Red Fighter Record: 8-1-0",
    )
    _write_cached_sherdog_tree(tmp_path, red_name='Red "Crusher" Fighter')
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        row = conn.execute(
            """
            select link_method, canonical_fighter_id
            from fighter_identity_links
            where source = 'sherdog' and source_fighter_id = ?
            """,
            [SHERDOG_RED_ID],
        ).fetchone()
    assert row == ("cleaned_name_dob", f"ufcstats:{RED_ID}")


def test_ambiguous_cleaned_name_dob_stays_unresolved(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    _write_extra_ufc_fighter(tmp_path, UFC_ALT_ID_1, "Shared Name", dob="January 01, 1990")
    _write_extra_ufc_fighter(tmp_path, UFC_ALT_ID_2, "Shared Name", dob="January 01, 1990")
    _write_extra_sherdog_fighter(tmp_path, SHERDOG_ALT_ID, "Shared Name", dob="Jan 1, 1990")
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        row = conn.execute(
            """
            select link_method, canonical_fighter_id
            from fighter_identity_links
            where source = 'sherdog' and source_fighter_id = ?
            """,
            [SHERDOG_ALT_ID],
        ).fetchone()
    assert row == ("source_self", f"sherdog:{SHERDOG_ALT_ID}")


def test_name_only_match_without_dob_does_not_auto_link(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    _write_extra_sherdog_fighter(tmp_path, SHERDOG_ALT_ID, "Red Fighter", dob="Unknown")
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        row = conn.execute(
            """
            select link_method, canonical_fighter_id
            from fighter_identity_links
            where source = 'sherdog' and source_fighter_id = ?
            """,
            [SHERDOG_ALT_ID],
        ).fetchone()
    assert row == ("source_self", f"sherdog:{SHERDOG_ALT_ID}")


def test_manual_override_approval_beats_unresolved_identity(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    _write_extra_sherdog_fighter(tmp_path, SHERDOG_ALT_ID, "Red Fighter", dob="Unknown")
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    _write_manual_override(
        settings.warehouse_path,
        SHERDOG_ALT_ID,
        RED_ID,
        "approved",
        "manual link",
    )
    build_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        row = conn.execute(
            """
            select link_method, canonical_fighter_id, override_note
            from fighter_identity_links
            where source = 'sherdog' and source_fighter_id = ?
            """,
            [SHERDOG_ALT_ID],
        ).fetchone()
    assert row == ("manual_override", f"ufcstats:{RED_ID}", "manual link")


def test_manual_rejection_blocks_deterministic_identity_link(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    _write_manual_override(
        settings.warehouse_path,
        SHERDOG_RED_ID,
        RED_ID,
        "rejected",
        "not same fighter",
    )
    build_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        row = conn.execute(
            """
            select link_method, canonical_fighter_id
            from fighter_identity_links
            where source = 'sherdog' and source_fighter_id = ?
            """,
            [SHERDOG_RED_ID],
        ).fetchone()
    assert row == ("source_self", f"sherdog:{SHERDOG_RED_ID}")


def test_conflicting_manual_approvals_fail_build(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    _write_extra_sherdog_fighter(tmp_path, SHERDOG_ALT_ID, "Shared Name", dob="Jan 1, 1990")
    _write_extra_ufc_fighter(tmp_path, UFC_ALT_ID_1, "Shared Name", dob="January 01, 1990")
    _write_extra_ufc_fighter(tmp_path, UFC_ALT_ID_2, "Shared Name", dob="January 01, 1990")
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    _write_manual_override(settings.warehouse_path, SHERDOG_ALT_ID, UFC_ALT_ID_1, "approved")
    _write_manual_override(settings.warehouse_path, SHERDOG_ALT_ID, UFC_ALT_ID_2, "approved")
    try:
        build_warehouse(settings)
    except ValueError as error:
        assert "Conflicting approved manual overrides" in str(error)
    else:
        raise AssertionError("Expected conflicting manual overrides to fail build_warehouse")


def test_accepted_unresolved_persists_manual_no_candidate_state(tmp_path: Path) -> None:
    _write_cached_fixture_tree(tmp_path)
    _write_cached_sherdog_tree(tmp_path)
    _write_extra_sherdog_fighter(tmp_path, SHERDOG_ALT_ID, "Red Fighter", dob="Unknown")
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    build_warehouse(settings)
    _write_manual_override(
        settings.warehouse_path,
        SHERDOG_ALT_ID,
        "",
        "accepted_unresolved",
        "no candidates found",
    )
    build_warehouse(settings)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        row = conn.execute(
            """
            select link_method, canonical_fighter_id, override_note
            from fighter_identity_links
            where source = 'sherdog' and source_fighter_id = ?
            """,
            [SHERDOG_ALT_ID],
        ).fetchone()
        target_type = conn.execute(
            """
            select column_type
            from (describe fighter_identity_manual_overrides)
            where column_name = 'target_source_fighter_id'
            """
        ).fetchone()[0]
    assert row == ("manual_unresolved", f"sherdog:{SHERDOG_ALT_ID}", "no candidates found")
    assert target_type == "VARCHAR"
