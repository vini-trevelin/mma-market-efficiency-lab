from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb

from mma_eff_lab.config import get_settings
from mma_eff_lab.features.pit import build_pit_features
from mma_eff_lab.warehouse.build import build_warehouse
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


def _write_cached_fixture_tree(root: Path) -> None:
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
    (raw / "fighters" / f"{RED_ID}.html").write_text(fighter_html("Red Fighter"), encoding="utf-8")
    (raw / "fighters" / f"{BLUE_ID}.html").write_text(
        fighter_html("Blue Fighter").replace("5' 11\"", "5' 9\""), encoding="utf-8"
    )


def _write_cached_sherdog_tree(root: Path) -> None:
    raw = root / "data" / "raw" / "sherdog"
    (raw / "events").mkdir(parents=True)
    (raw / "fighters").mkdir(parents=True)
    event_html = sherdog_event_html(
        event_id=SHERDOG_EVENT_ID,
        red_id=SHERDOG_RED_ID,
        blue_id=SHERDOG_BLUE_ID,
    ).replace("Apr 11, 2014", "Jan 01, 2019")
    (raw / "events" / f"{SHERDOG_EVENT_ID}.html").write_text(event_html, encoding="utf-8")
    (raw / "fighters" / f"{SHERDOG_RED_ID}.html").write_text(
        sherdog_fighter_html("Red Fighter"), encoding="utf-8"
    )
    (raw / "fighters" / f"{SHERDOG_BLUE_ID}.html").write_text(
        sherdog_fighter_html("Blue Fighter"), encoding="utf-8"
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
