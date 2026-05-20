from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pandas as pd

from mma_eff_lab.config import Settings, ensure_data_dirs, get_settings
from mma_eff_lab.parse.sherdog import parse_all_cached as parse_all_cached_sherdog
from mma_eff_lab.parse.ufcstats import parse_all_cached

TABLES = [
    "events",
    "fights",
    "fight_participants",
    "fighters",
    "fighter_fight_stats",
]
SOURCE_TABLES = [
    "source_events",
    "source_fights",
    "source_fight_participants",
    "source_fighters",
    "parse_quarantine",
]

EMPTY_COLUMNS = {
    "events": ["event_id", "name", "event_date", "location", "url"],
    "fights": [
        "fight_id",
        "event_id",
        "winner_id",
        "method",
        "round",
        "time",
        "time_format",
        "referee",
        "url",
    ],
    "fight_participants": [
        "fight_id",
        "event_id",
        "fighter_id",
        "opponent_id",
        "corner",
        "full_name",
        "winner_flag",
        "outcome",
    ],
    "fighters": [
        "fighter_id",
        "full_name",
        "height_in",
        "weight_lbs",
        "reach_in",
        "stance",
        "dob",
        "url",
    ],
    "fighter_fight_stats": [
        "fight_id",
        "event_id",
        "fighter_id",
        "opponent_id",
        "corner",
        "kd",
        "sig_str_landed",
        "sig_str_attempted",
        "total_str_landed",
        "total_str_attempted",
        "td_landed",
        "td_attempted",
        "sub_att",
        "rev",
        "ctrl_sec",
    ],
    "source_events": [
        "source",
        "source_event_id",
        "name",
        "event_date",
        "location",
        "promotion",
        "url",
    ],
    "source_fights": [
        "source",
        "source_fight_id",
        "source_event_id",
        "promotion",
        "weight_class",
        "winner_source_fighter_id",
        "method",
        "round",
        "time",
        "time_format",
        "referee",
        "url",
    ],
    "source_fight_participants": [
        "source",
        "source_fight_id",
        "source_event_id",
        "source_fighter_id",
        "opponent_source_fighter_id",
        "promotion",
        "corner",
        "full_name",
        "winner_flag",
        "outcome",
    ],
    "source_fighters": [
        "source",
        "source_fighter_id",
        "full_name",
        "height_in",
        "weight_lbs",
        "reach_in",
        "stance",
        "dob",
        "url",
    ],
    "parse_quarantine": ["source", "entity_type", "source_entity_id", "promotion", "reason", "url"],
}


def parse_cached_ufcstats(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    parsed = parse_all_cached(settings.raw_dir)
    parsed_dir = settings.warehouse_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, rows in parsed.items():
        counts[name] = len(rows)
        pd.DataFrame(rows).to_parquet(parsed_dir / f"{name}.parquet", index=False)
    (parsed_dir / "summary.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    return counts


def parse_cached_sherdog(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    parsed = parse_all_cached_sherdog(settings.raw_dir)
    parsed_dir = settings.warehouse_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, rows in parsed.items():
        frame = pd.DataFrame(rows, columns=EMPTY_COLUMNS[name])
        counts[name] = len(frame)
        frame.to_parquet(parsed_dir / f"{name}.parquet", index=False)
    (parsed_dir / "sherdog_summary.json").write_text(
        json.dumps(counts, indent=2), encoding="utf-8"
    )
    return counts


def build_warehouse(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    parsed_dir = settings.warehouse_dir / "parsed"
    if not parsed_dir.exists():
        parse_cached_ufcstats(settings)
        parse_cached_sherdog(settings)
    settings.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    frames = _build_canonical_frames(parsed_dir)
    counts: dict[str, int] = {}
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        for table, frame in frames.items():
            _write_table(conn, table, frame)
            counts[table] = len(frame)
        _add_quality_views(conn)
    return counts


def table_counts(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {}
    counts: dict[str, int] = {}
    with duckdb.connect(str(db_path), read_only=True) as conn:
        names = conn.execute(
            "select table_name from information_schema.tables where table_schema='main'"
        ).fetchall()
        for (name,) in names:
            counts[name] = conn.execute(f"select count(*) from {name}").fetchone()[0]
    return counts


def _write_table(conn: duckdb.DuckDBPyConnection, name: str, frame: pd.DataFrame) -> None:
    conn.execute(f"drop table if exists {name}")
    conn.register("frame", frame)
    if frame.empty:
        conn.execute(f"create table {name} as select * from frame where false")
        conn.unregister("frame")
        return
    conn.execute(f"create table {name} as select * from frame")
    conn.unregister("frame")


def _add_quality_views(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        create or replace view warehouse_quality as
        select 'events' as table_name, count(*) as row_count from events
        union all select 'fights', count(*) from fights
        union all select 'fight_participants', count(*) from fight_participants
        union all select 'fighters', count(*) from fighters
        union all select 'fighter_fight_stats', count(*) from fighter_fight_stats
        union all select 'source_events', count(*) from source_events
        union all select 'source_fights', count(*) from source_fights
        union all select 'source_fight_participants', count(*) from source_fight_participants
        union all select 'source_fighters', count(*) from source_fighters
        union all select 'fighter_identity_links', count(*) from fighter_identity_links
        union all select 'parse_quarantine', count(*) from parse_quarantine
        """
    )


def _build_canonical_frames(parsed_dir: Path) -> dict[str, pd.DataFrame]:
    ufc = {table: _read_table(parsed_dir, table) for table in TABLES}
    sherdog = {table: _read_table(parsed_dir, table) for table in SOURCE_TABLES}
    ufc_source = _ufc_source_frames(ufc)
    source_events = _dedupe(
        pd.concat([ufc_source["source_events"], sherdog["source_events"]], ignore_index=True),
        ["source", "source_event_id"],
    )
    source_fights = _dedupe(
        pd.concat([ufc_source["source_fights"], sherdog["source_fights"]], ignore_index=True),
        ["source", "source_fight_id"],
    )
    source_participants = _dedupe(
        pd.concat(
            [ufc_source["source_fight_participants"], sherdog["source_fight_participants"]],
            ignore_index=True,
        ),
        ["source", "source_fight_id", "source_fighter_id"],
    )
    source_fighters = _dedupe(
        pd.concat([ufc_source["source_fighters"], sherdog["source_fighters"]], ignore_index=True),
        ["source", "source_fighter_id"],
    )
    identity_links = _identity_links(source_fighters)
    canonical_fighters = _canonical_fighters(source_fighters, identity_links)
    return {
        "source_events": source_events,
        "source_fights": source_fights,
        "source_fight_participants": source_participants,
        "source_fighters": source_fighters,
        "fighter_identity_links": identity_links,
        "parse_quarantine": sherdog["parse_quarantine"],
        "events": _canonical_events(source_events),
        "fights": _canonical_fights(source_fights, identity_links),
        "fight_participants": _canonical_participants(source_participants, identity_links),
        "fighters": canonical_fighters,
        "fighter_fight_stats": _canonical_stats(ufc["fighter_fight_stats"]),
    }


def _read_table(parsed_dir: Path, table: str) -> pd.DataFrame:
    path = parsed_dir / f"{table}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=EMPTY_COLUMNS[table])
    frame = pd.read_parquet(path)
    for column in EMPTY_COLUMNS[table]:
        if column not in frame:
            frame[column] = None
    return frame[EMPTY_COLUMNS[table]]


def _ufc_source_frames(ufc: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    events = ufc["events"].copy()
    events = events.rename(columns={"event_id": "source_event_id"})
    events["source"] = "ufcstats"
    events["promotion"] = "UFC"
    events = events[EMPTY_COLUMNS["source_events"]]

    fights = ufc["fights"].copy()
    fights = fights.rename(
        columns={
            "fight_id": "source_fight_id",
            "event_id": "source_event_id",
            "winner_id": "winner_source_fighter_id",
        }
    )
    fights["source"] = "ufcstats"
    fights["promotion"] = "UFC"
    fights["weight_class"] = None
    fights = fights[EMPTY_COLUMNS["source_fights"]]

    participants = ufc["fight_participants"].copy()
    participants = participants.rename(
        columns={
            "fight_id": "source_fight_id",
            "event_id": "source_event_id",
            "fighter_id": "source_fighter_id",
            "opponent_id": "opponent_source_fighter_id",
        }
    )
    participants["source"] = "ufcstats"
    participants["promotion"] = "UFC"
    participants = participants[EMPTY_COLUMNS["source_fight_participants"]]

    fighters = ufc["fighters"].copy()
    fighters = fighters.rename(columns={"fighter_id": "source_fighter_id"})
    fighters["source"] = "ufcstats"
    fighters = fighters[EMPTY_COLUMNS["source_fighters"]]
    return {
        "source_events": events,
        "source_fights": fights,
        "source_fight_participants": participants,
        "source_fighters": fighters,
    }


def _canonical_events(source_events: pd.DataFrame) -> pd.DataFrame:
    frame = source_events.copy()
    frame["event_id"] = frame.apply(
        lambda row: _canonical_id(row["source"], row["source_event_id"]), axis=1
    )
    return frame[
        [
            "event_id",
            "source",
            "source_event_id",
            "promotion",
            "name",
            "event_date",
            "location",
            "url",
        ]
    ]


def _canonical_fights(source_fights: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    frame = source_fights.copy()
    frame["fight_id"] = frame.apply(
        lambda row: _canonical_id(row["source"], row["source_fight_id"]), axis=1
    )
    frame["event_id"] = frame.apply(
        lambda row: _canonical_id(row["source"], row["source_event_id"]), axis=1
    )
    link_map = _identity_map(links)
    frame["winner_id"] = frame.apply(
        lambda row: link_map.get((row["source"], row["winner_source_fighter_id"]))
        if pd.notna(row["winner_source_fighter_id"])
        else None,
        axis=1,
    )
    return frame[
        [
            "fight_id",
            "event_id",
            "source",
            "source_fight_id",
            "source_event_id",
            "promotion",
            "weight_class",
            "winner_id",
            "method",
            "round",
            "time",
            "time_format",
            "referee",
            "url",
        ]
    ]


def _canonical_participants(participants: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    frame = participants.copy()
    link_map = _identity_map(links)
    frame["fight_id"] = frame.apply(
        lambda row: _canonical_id(row["source"], row["source_fight_id"]), axis=1
    )
    frame["event_id"] = frame.apply(
        lambda row: _canonical_id(row["source"], row["source_event_id"]), axis=1
    )
    frame["fighter_id"] = frame.apply(
        lambda row: link_map[(row["source"], row["source_fighter_id"])], axis=1
    )
    frame["opponent_id"] = frame.apply(
        lambda row: link_map[(row["source"], row["opponent_source_fighter_id"])], axis=1
    )
    return frame[
        [
            "fight_id",
            "event_id",
            "source",
            "source_fight_id",
            "source_event_id",
            "promotion",
            "source_fighter_id",
            "fighter_id",
            "opponent_id",
            "corner",
            "full_name",
            "winner_flag",
            "outcome",
        ]
    ]


def _canonical_stats(stats: pd.DataFrame) -> pd.DataFrame:
    frame = stats.copy()
    frame["source"] = "ufcstats"
    frame["source_fight_id"] = frame["fight_id"]
    frame["source_event_id"] = frame["event_id"]
    frame["source_fighter_id"] = frame["fighter_id"]
    frame["fight_id"] = frame["fight_id"].map(lambda value: _canonical_id("ufcstats", value))
    frame["event_id"] = frame["event_id"].map(lambda value: _canonical_id("ufcstats", value))
    frame["fighter_id"] = frame["fighter_id"].map(lambda value: _canonical_id("ufcstats", value))
    frame["opponent_id"] = frame["opponent_id"].map(lambda value: _canonical_id("ufcstats", value))
    columns = [
        "fight_id",
        "event_id",
        "source",
        "source_fight_id",
        "source_event_id",
        "source_fighter_id",
        "fighter_id",
        "opponent_id",
        "corner",
        "kd",
        "sig_str_landed",
        "sig_str_attempted",
        "total_str_landed",
        "total_str_attempted",
        "td_landed",
        "td_attempted",
        "sub_att",
        "rev",
        "ctrl_sec",
    ]
    return frame[columns]


def _identity_links(source_fighters: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    ufc = source_fighters[source_fighters["source"] == "ufcstats"].copy()
    ufc["identity_key"] = ufc.apply(_identity_key, axis=1)
    unique_ufc = {
        key: group.iloc[0]["source_fighter_id"]
        for key, group in ufc.dropna(subset=["identity_key"]).groupby("identity_key")
        if len(group) == 1
    }
    for row in source_fighters.to_dict("records"):
        source = row["source"]
        source_fighter_id = row["source_fighter_id"]
        canonical_fighter_id = _canonical_id(source, source_fighter_id)
        link_method = "source_self"
        confidence = 1.0
        key = _identity_key(row)
        if source == "sherdog" and key and key in unique_ufc:
            canonical_fighter_id = _canonical_id("ufcstats", unique_ufc[key])
            link_method = "exact_name_dob"
        rows.append(
            {
                "source": source,
                "source_fighter_id": source_fighter_id,
                "canonical_fighter_id": canonical_fighter_id,
                "full_name": row["full_name"],
                "dob": row.get("dob"),
                "link_method": link_method,
                "confidence": confidence,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "source",
            "source_fighter_id",
            "canonical_fighter_id",
            "full_name",
            "dob",
            "link_method",
            "confidence",
        ],
    )


def _canonical_fighters(source_fighters: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    if source_fighters.empty:
        return pd.DataFrame(
            columns=[
                "fighter_id",
                "source",
                "source_fighter_id",
                "full_name",
                "height_in",
                "weight_lbs",
                "reach_in",
                "stance",
                "dob",
                "url",
            ]
        )
    frame = source_fighters.merge(
        links[["source", "source_fighter_id", "canonical_fighter_id"]],
        on=["source", "source_fighter_id"],
        how="left",
    )
    frame["_priority"] = frame["source"].map({"ufcstats": 0, "sherdog": 1}).fillna(9)
    rows = []
    for canonical_id, group in frame.sort_values("_priority").groupby("canonical_fighter_id"):
        first = group.iloc[0].to_dict()
        output = {
            "fighter_id": canonical_id,
            "source": first["source"],
            "source_fighter_id": first["source_fighter_id"],
            "full_name": _first_non_null(group, "full_name"),
            "height_in": _first_non_null(group, "height_in"),
            "weight_lbs": _first_non_null(group, "weight_lbs"),
            "reach_in": _first_non_null(group, "reach_in"),
            "stance": _first_non_null(group, "stance"),
            "dob": _first_non_null(group, "dob"),
            "url": _first_non_null(group, "url"),
        }
        rows.append(output)
    return pd.DataFrame(rows)


def _identity_map(links: pd.DataFrame) -> dict[tuple[str, str], str]:
    return {
        (row["source"], row["source_fighter_id"]): row["canonical_fighter_id"]
        for row in links.to_dict("records")
    }


def _identity_key(row: pd.Series | dict[str, object]) -> str | None:
    dob = row.get("dob")
    if dob is None or pd.isna(dob):
        return None
    name = _normalize_name(str(row.get("full_name") or ""))
    if not name:
        return None
    return f"{name}|{dob}"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _canonical_id(source: object, source_id: object) -> str:
    return f"{source}:{source_id}"


def _dedupe(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.drop_duplicates(keys, keep="first").reset_index(drop=True)


def _first_non_null(frame: pd.DataFrame, column: str) -> object:
    values = frame[column].dropna()
    if values.empty:
        return None
    return values.iloc[0]
