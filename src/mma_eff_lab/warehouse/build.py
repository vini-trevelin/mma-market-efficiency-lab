from __future__ import annotations

import json
import re
from datetime import UTC, datetime
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
MANUAL_OVERRIDE_TABLE = "fighter_identity_manual_overrides"

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
    MANUAL_OVERRIDE_TABLE: [
        "source",
        "source_fighter_id",
        "target_source",
        "target_source_fighter_id",
        "decision",
        "note",
        "created_at_utc",
        "updated_at_utc",
    ],
}

EMPTY_TABLE_SCHEMAS = {
    "parse_quarantine": {
        "source": "varchar",
        "entity_type": "varchar",
        "source_entity_id": "varchar",
        "promotion": "varchar",
        "reason": "varchar",
        "url": "varchar",
    },
    MANUAL_OVERRIDE_TABLE: {
        "source": "varchar",
        "source_fighter_id": "varchar",
        "target_source": "varchar",
        "target_source_fighter_id": "varchar",
        "decision": "varchar",
        "note": "varchar",
        "created_at_utc": "varchar",
        "updated_at_utc": "varchar",
    },
}

EMPTY_FRAME_DTYPES = {
    "parse_quarantine": {
        "source": "string",
        "entity_type": "string",
        "source_entity_id": "string",
        "promotion": "string",
        "reason": "string",
        "url": "string",
    },
    MANUAL_OVERRIDE_TABLE: {
        "source": "string",
        "source_fighter_id": "string",
        "target_source": "string",
        "target_source_fighter_id": "string",
        "decision": "string",
        "note": "string",
        "created_at_utc": "string",
        "updated_at_utc": "string",
    },
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
        frame = _typed_frame(rows, name)
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
    manual_overrides = _read_manual_overrides(settings)
    frames = _build_canonical_frames(parsed_dir, manual_overrides)
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
    if frame.empty and name in EMPTY_TABLE_SCHEMAS:
        schema = EMPTY_TABLE_SCHEMAS[name]
        column_sql = ", ".join(f"{column} {sql_type}" for column, sql_type in schema.items())
        conn.execute(f"create table {name} ({column_sql})")
        return
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
        union all
        select 'fighter_identity_manual_overrides', count(*)
        from fighter_identity_manual_overrides
        union all select 'parse_quarantine', count(*) from parse_quarantine
        """
    )


def _build_canonical_frames(
    parsed_dir: Path, manual_overrides: pd.DataFrame
) -> dict[str, pd.DataFrame]:
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
        ["source", "source_fight_id", "source_fighter_id", "corner"],
    )
    source_fighters = _dedupe(
        pd.concat([ufc_source["source_fighters"], sherdog["source_fighters"]], ignore_index=True),
        ["source", "source_fighter_id"],
    )
    identity_links = _identity_links(source_fighters, manual_overrides)
    canonical_fighters = _canonical_fighters(source_fighters, identity_links)
    return {
        "source_events": source_events,
        "source_fights": source_fights,
        "source_fight_participants": source_participants,
        "source_fighters": source_fighters,
        MANUAL_OVERRIDE_TABLE: manual_overrides,
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
        return _typed_frame([], table)
    frame = pd.read_parquet(path)
    for column in EMPTY_COLUMNS[table]:
        if column not in frame:
            frame[column] = None
    frame = frame[EMPTY_COLUMNS[table]]
    if frame.empty and table in EMPTY_FRAME_DTYPES:
        return _typed_frame([], table)
    return frame


def _read_manual_overrides(settings: Settings) -> pd.DataFrame:
    if not settings.warehouse_path.exists():
        return _typed_frame([], MANUAL_OVERRIDE_TABLE)
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        exists = conn.execute(
            """
            select 1
            from information_schema.tables
            where table_schema = 'main' and table_name = ?
            """,
            [MANUAL_OVERRIDE_TABLE],
        ).fetchone()
        if not exists:
            return _typed_frame([], MANUAL_OVERRIDE_TABLE)
        frame = conn.execute(f"select * from {MANUAL_OVERRIDE_TABLE}").fetchdf()
    for column in EMPTY_COLUMNS[MANUAL_OVERRIDE_TABLE]:
        if column not in frame:
            frame[column] = None
    frame = frame[EMPTY_COLUMNS[MANUAL_OVERRIDE_TABLE]]
    if frame.empty:
        return _typed_frame([], MANUAL_OVERRIDE_TABLE)
    return frame


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


def _identity_links(
    source_fighters: pd.DataFrame, manual_overrides: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    manual_overrides = _normalize_manual_overrides(manual_overrides)
    ufc = source_fighters[source_fighters["source"] == "ufcstats"].copy()
    ufc_ids = set(ufc["source_fighter_id"].astype(str))
    ufc["exact_name_key"] = ufc.apply(_exact_name_key, axis=1)
    ufc["cleaned_name_key"] = ufc.apply(_cleaned_name_key, axis=1)
    ufc["exact_identity_key"] = ufc.apply(_identity_key, axis=1)
    ufc["cleaned_identity_key"] = ufc.apply(
        lambda row: _identity_key(row, cleaned=True), axis=1
    )
    unique_exact_ufc = {
        key: group.iloc[0]["source_fighter_id"]
        for key, group in ufc.dropna(subset=["exact_identity_key"]).groupby("exact_identity_key")
        if len(group) == 1
    }
    unique_cleaned_ufc = {
        key: group.iloc[0]["source_fighter_id"]
        for key, group in ufc.dropna(subset=["cleaned_identity_key"]).groupby(
            "cleaned_identity_key"
        )
        if len(group) == 1
    }
    approved = manual_overrides[manual_overrides["decision"] == "approved"].copy()
    accepted_unresolved = manual_overrides[
        manual_overrides["decision"] == "accepted_unresolved"
    ].copy()
    approved_targets = approved.groupby("source_fighter_id")["target_source_fighter_id"].nunique()
    conflicting = approved_targets[approved_targets > 1]
    if not conflicting.empty:
        conflict_ids = ", ".join(sorted(conflicting.index.astype(str).tolist()))
        raise ValueError(
            f"Conflicting approved manual overrides for source_fighter_id: {conflict_ids}"
        )
    primary_decisions = manual_overrides[
        manual_overrides["decision"].isin({"approved", "accepted_unresolved"})
    ].groupby("source_fighter_id")["decision"].count()
    conflicting_primary = primary_decisions[primary_decisions > 1]
    if not conflicting_primary.empty:
        conflict_ids = ", ".join(sorted(conflicting_primary.index.astype(str).tolist()))
        raise ValueError(
            "Conflicting primary manual identity decisions for source_fighter_id: "
            + conflict_ids
        )
    missing_targets = sorted(
        set(approved["target_source_fighter_id"].astype(str)) - ufc_ids
    )
    if missing_targets:
        raise ValueError(
            "Approved manual override targets not found in UFCStats source_fighters: "
            + ", ".join(missing_targets)
        )
    approved_map = {
        str(row["source_fighter_id"]): {
            "target_source_fighter_id": str(row["target_source_fighter_id"]),
            "note": row.get("note"),
        }
        for row in approved.to_dict("records")
    }
    accepted_unresolved_map = {
        str(row["source_fighter_id"]): row.get("note")
        for row in accepted_unresolved.to_dict("records")
    }
    rejected_pairs = {
        (str(row["source_fighter_id"]), str(row["target_source_fighter_id"]))
        for row in manual_overrides[manual_overrides["decision"] == "rejected"].to_dict("records")
        if row.get("target_source_fighter_id") not in (None, "")
    }
    for row in source_fighters.to_dict("records"):
        source = str(row["source"])
        source_fighter_id = str(row["source_fighter_id"])
        canonical_fighter_id = _canonical_id(source, source_fighter_id)
        link_method = "source_self"
        confidence = 1.0
        exact_name_key = _exact_name_key(row)
        cleaned_name_key = _cleaned_name_key(row)
        exact_identity_key = _identity_key(row)
        cleaned_identity_key = _identity_key(row, cleaned=True)
        match_reason = "source_self"
        override_note = None
        approved_override = approved_map.get(source_fighter_id)
        if source == "sherdog" and approved_override:
            target_id = approved_override["target_source_fighter_id"]
            canonical_fighter_id = _canonical_id("ufcstats", target_id)
            link_method = "manual_override"
            confidence = 1.0
            match_reason = "manual override approval"
            override_note = approved_override["note"]
        elif source == "sherdog" and source_fighter_id in accepted_unresolved_map:
            link_method = "manual_unresolved"
            confidence = 1.0
            match_reason = "manual unresolved acceptance"
            override_note = accepted_unresolved_map[source_fighter_id]
        elif source == "sherdog" and exact_identity_key and exact_identity_key in unique_exact_ufc:
            target_id = str(unique_exact_ufc[exact_identity_key])
            if (source_fighter_id, target_id) not in rejected_pairs:
                canonical_fighter_id = _canonical_id("ufcstats", target_id)
                link_method = "exact_name_dob"
                confidence = 1.0
                match_reason = "exact normalized full name + exact dob"
        elif (
            source == "sherdog"
            and cleaned_identity_key
            and cleaned_identity_key in unique_cleaned_ufc
        ):
            target_id = str(unique_cleaned_ufc[cleaned_identity_key])
            if (source_fighter_id, target_id) not in rejected_pairs:
                canonical_fighter_id = _canonical_id("ufcstats", target_id)
                link_method = "cleaned_name_dob"
                confidence = 0.95
                match_reason = "cleaned full name + exact dob"
        rows.append(
            {
                "source": source,
                "source_fighter_id": source_fighter_id,
                "canonical_fighter_id": canonical_fighter_id,
                "full_name": row["full_name"],
                "dob": row.get("dob"),
                "link_method": link_method,
                "confidence": confidence,
                "exact_name_key": exact_name_key,
                "cleaned_name_key": cleaned_name_key,
                "match_reason": match_reason,
                "override_note": override_note,
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
            "exact_name_key",
            "cleaned_name_key",
            "match_reason",
            "override_note",
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


def _identity_key(row: pd.Series | dict[str, object], cleaned: bool = False) -> str | None:
    dob = row.get("dob")
    if dob is None or pd.isna(dob):
        return None
    name = _cleaned_name_key(row) if cleaned else _exact_name_key(row)
    if not name:
        return None
    return f"{name}|{dob}"


def _exact_name_key(row: pd.Series | dict[str, object]) -> str:
    return _normalize_name(str(row.get("full_name") or ""))


def _cleaned_name_key(row: pd.Series | dict[str, object]) -> str:
    value = str(row.get("full_name") or "")
    value = _strip_record_suffix(value)
    value = _strip_quoted_nickname(value)
    return _normalize_name(value)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _strip_quoted_nickname(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'"[^"]+"', "", str(value))).strip()


def _strip_record_suffix(value: str) -> str:
    stripped = re.sub(r"\s+Record:\s+.+$", "", str(value), flags=re.I)
    return re.sub(r"\s+", " ", stripped).strip()


def _canonical_id(source: object, source_id: object) -> str:
    return f"{source}:{source_id}"


def _dedupe(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.drop_duplicates(keys, keep="first").reset_index(drop=True)


def _typed_frame(rows: list[dict[str, object]], table: str) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=EMPTY_COLUMNS[table])
    for column, dtype in EMPTY_FRAME_DTYPES.get(table, {}).items():
        frame[column] = pd.Series(frame[column], dtype=dtype)
    return frame


def _first_non_null(frame: pd.DataFrame, column: str) -> object:
    values = frame[column].dropna()
    if values.empty:
        return None
    return values.iloc[0]


def _normalize_manual_overrides(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _typed_frame([], MANUAL_OVERRIDE_TABLE)
    normalized = frame.copy()
    for column in EMPTY_COLUMNS[MANUAL_OVERRIDE_TABLE]:
        if column not in normalized:
            normalized[column] = None
    normalized = normalized[EMPTY_COLUMNS[MANUAL_OVERRIDE_TABLE]]
    normalized["source"] = normalized["source"].fillna("sherdog")
    normalized["target_source"] = normalized["target_source"].fillna("ufcstats")
    normalized["decision"] = normalized["decision"].fillna("").astype(str).str.lower()
    normalized["source_fighter_id"] = normalized["source_fighter_id"].astype(str)
    normalized["target_source_fighter_id"] = normalized["target_source_fighter_id"].where(
        normalized["target_source_fighter_id"].notna(),
        None,
    )
    normalized["created_at_utc"] = normalized["created_at_utc"].fillna(
        datetime.now(UTC).isoformat()
    )
    normalized["updated_at_utc"] = normalized["updated_at_utc"].fillna(
        datetime.now(UTC).isoformat()
    )
    normalized = normalized[
        normalized["source"].eq("sherdog")
        & normalized["target_source"].eq("ufcstats")
        & normalized["decision"].isin({"approved", "rejected", "accepted_unresolved"})
    ]
    normalized = normalized[
        (
            normalized["decision"].isin({"approved", "rejected"})
            & normalized["target_source_fighter_id"].notna()
        )
        | (
            normalized["decision"].eq("accepted_unresolved")
            & normalized["target_source_fighter_id"].isna()
        )
    ]
    if normalized.empty:
        return _typed_frame([], MANUAL_OVERRIDE_TABLE)
    return _dedupe(
        normalized,
        ["source", "source_fighter_id", "target_source", "target_source_fighter_id"],
    )
