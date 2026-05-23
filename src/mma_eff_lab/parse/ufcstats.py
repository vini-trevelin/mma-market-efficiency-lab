from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

BASE_URL = "http://ufcstats.com"
EVENTS_INDEX_URL = f"{BASE_URL}/statistics/events/completed?page=all"


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    event_id: str
    name: str
    event_date: date
    location: str | None
    url: str


@dataclass(frozen=True)
class Fight:
    fight_id: str
    event_id: str
    winner_id: str | None
    method: str
    round: int
    time: str
    time_format: str | None
    referee: str | None
    url: str


@dataclass(frozen=True)
class FightParticipant:
    fight_id: str
    event_id: str
    fighter_id: str
    opponent_id: str
    corner: str
    full_name: str
    winner_flag: bool
    outcome: str | None


@dataclass(frozen=True)
class Fighter:
    fighter_id: str
    full_name: str
    height_in: int | None
    weight_lbs: int | None
    reach_in: int | None
    stance: str | None
    dob: date | None
    url: str


@dataclass(frozen=True)
class FighterFightStats:
    fight_id: str
    event_id: str
    fighter_id: str
    opponent_id: str
    corner: str
    kd: int | None
    sig_str_landed: int | None
    sig_str_attempted: int | None
    total_str_landed: int | None
    total_str_attempted: int | None
    td_landed: int | None
    td_attempted: int | None
    sub_att: int | None
    rev: int | None
    ctrl_sec: int | None


@dataclass(frozen=True)
class EventParseResult:
    event: Event
    fights: list[Fight]
    participants: list[FightParticipant]


@dataclass(frozen=True)
class FightParseResult:
    fight_id: str
    participants: list[FightParticipant]
    stats: list[FighterFightStats]


def to_rows(items: list[object]) -> list[dict[str, object]]:
    return [asdict(item) for item in items]


def clean_text(node: Tag | BeautifulSoup | str | None) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        text = node
    else:
        text = " ".join(node.stripped_strings)
    return re.sub(r"\s+", " ", text).strip()


def extract_id(url: str, entity: str) -> str:
    match = re.search(rf"{entity}-details/([A-Za-z0-9]+)", url)
    if not match:
        raise ParseError(f"Could not extract {entity} id from {url}")
    return match.group(1)


def absolute_url(url: str) -> str:
    return urljoin(BASE_URL, url).replace("https://www.ufcstats.com", BASE_URL).replace(
        "https://ufcstats.com", BASE_URL
    )


def parse_ufcstats_date(value: str) -> date:
    value = clean_text(value).replace(",", ", ")
    value = re.sub(r"\s+", " ", value)
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"Could not parse UFCStats date: {value}")


def parse_height(value: str) -> int | None:
    value = clean_text(value)
    if not value or value == "--":
        return None
    match = re.search(r"(\d+)'\s*(\d+)", value)
    if not match:
        return None
    return int(match.group(1)) * 12 + int(match.group(2))


def parse_int(value: str) -> int | None:
    value = clean_text(value)
    if not value or value == "--":
        return None
    match = re.search(r"-?\d+", value.replace(",", ""))
    return int(match.group(0)) if match else None


def parse_duration_to_sec(value: str) -> int | None:
    value = clean_text(value)
    if not value or value == "--":
        return None
    match = re.fullmatch(r"(\d+):(\d{2})", value)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def parse_landed_attempted(value: str) -> tuple[int | None, int | None]:
    value = clean_text(value).lower()
    match = re.search(r"(\d+)\s+of\s+(\d+)", value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_events_index(html: str) -> list[Event]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[Event] = []
    seen: set[str] = set()
    for link in soup.select("a[href*='event-details/']"):
        url = absolute_url(link.get("href", ""))
        event_id = extract_id(url, "event")
        if event_id in seen:
            continue
        row = link.find_parent("tr")
        row_text = clean_text(row)
        date_match = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", row_text)
        if not date_match:
            continue
        cells = [clean_text(cell) for cell in row.select("td")] if row else []
        location = cells[-1] if len(cells) >= 3 else None
        events.append(
            Event(
                event_id=event_id,
                name=clean_text(link),
                event_date=parse_ufcstats_date(date_match.group(1)),
                location=location,
                url=url,
            )
        )
        seen.add(event_id)
    return events


def parse_event_detail(
    html: str, event_id: str | None = None, url: str | None = None
) -> EventParseResult:
    soup = BeautifulSoup(html, "html.parser")
    event_url = url or ""
    resolved_event_id = event_id or extract_id(event_url, "event")
    title = clean_text(soup.select_one(".b-content__title") or soup.select_one("h1, h2"))
    title = title.replace("EVENT DETAILS", "").strip()
    info_text = clean_text(soup.select_one(".b-list__box-list") or soup)
    date_match = re.search(r"DATE:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", info_text, re.I)
    if not date_match:
        date_match = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", info_text)
    if not title or not date_match:
        raise ParseError(f"Missing required event fields for {resolved_event_id}")
    location_match = re.search(r"LOCATION:\s*(.+?)(?:ATTENDANCE:|$)", info_text, re.I)
    event = Event(
        event_id=resolved_event_id,
        name=title,
        event_date=parse_ufcstats_date(date_match.group(1)),
        location=clean_text(location_match.group(1)) if location_match else None,
        url=event_url or f"{BASE_URL}/event-details/{resolved_event_id}",
    )
    fights: list[Fight] = []
    participants: list[FightParticipant] = []
    for row in _fight_rows(soup):
        parsed = _parse_event_fight_row(row, resolved_event_id)
        if parsed is None:
            continue
        fight, row_participants = parsed
        fights.append(fight)
        participants.extend(row_participants)
    return EventParseResult(event=event, fights=fights, participants=participants)


def parse_fighter_detail(html: str, url: str) -> Fighter:
    soup = BeautifulSoup(html, "html.parser")
    fighter_id = extract_id(url, "fighter")
    first = clean_text(soup.select_one(".b-content__title-highlight"))
    last = clean_text(soup.select_one(".b-content__title-highlight + .b-content__title-highlight"))
    full_name = clean_text(soup.select_one(".b-content__title") or soup.select_one("h1, h2"))
    full_name = re.sub(r"\s+", " ", full_name.replace("FIGHTER DETAILS", "")).strip()
    full_name = _strip_record_suffix(full_name)
    if first and last:
        full_name = f"{first} {last}"
    if not full_name:
        raise ParseError(f"Missing fighter name for {fighter_id}")
    fields = _parse_label_values(soup)
    return Fighter(
        fighter_id=fighter_id,
        full_name=full_name,
        height_in=parse_height(fields.get("height", "")),
        weight_lbs=parse_int(fields.get("weight", "")),
        reach_in=parse_int(fields.get("reach", "")),
        stance=_none_if_blank(fields.get("stance")),
        dob=_parse_optional_date(fields.get("dob", "")),
        url=url,
    )


def parse_fight_detail(html: str, event_id: str, url: str) -> FightParseResult:
    soup = BeautifulSoup(html, "html.parser")
    fight_id = extract_id(url, "fight")
    links = _unique_links(soup, "fighter")
    if len(links) < 2:
        raise ParseError(f"Missing fighter links for fight {fight_id}")
    fighter_ids = [extract_id(link[0], "fighter") for link in links[:2]]
    names = [link[1] for link in links[:2]]
    statuses = [
        clean_text(node)
        for node in soup.select(".b-fight-details__person-status, [data-status]")
        if clean_text(node) in {"W", "L", "D", "NC"}
    ]
    if len(statuses) < 2:
        statuses = ["", ""]
    participants = [
        FightParticipant(
            fight_id=fight_id,
            event_id=event_id,
            fighter_id=fighter_ids[0],
            opponent_id=fighter_ids[1],
            corner="red",
            full_name=names[0],
            winner_flag=statuses[0] == "W",
            outcome=statuses[0] or None,
        ),
        FightParticipant(
            fight_id=fight_id,
            event_id=event_id,
            fighter_id=fighter_ids[1],
            opponent_id=fighter_ids[0],
            corner="blue",
            full_name=names[1],
            winner_flag=statuses[1] == "W",
            outcome=statuses[1] or None,
        ),
    ]
    stats = _parse_fight_stats_table(soup, fight_id, event_id, fighter_ids)
    return FightParseResult(fight_id=fight_id, participants=participants, stats=stats)


def _fight_rows(soup: BeautifulSoup) -> list[Tag]:
    rows = soup.select("tr[data-link*='fight-details/'], tr.js-fight-details-click")
    if rows:
        return rows
    return [
        row
        for row in soup.select("tr")
        if row.select_one("a[href*='fight-details/']") or row.get("data-fight-id")
    ]


def _parse_event_fight_row(
    row: Tag, event_id: str
) -> tuple[Fight, list[FightParticipant]] | None:
    fight_url = row.get("data-link", "")
    fight_link = row.select_one("a[href*='fight-details/']")
    if not fight_url and fight_link:
        fight_url = fight_link.get("href", "")
    fight_url = absolute_url(fight_url)
    if "fight-details/" not in fight_url:
        return None
    fight_id = extract_id(fight_url, "fight")
    fighter_links = _unique_links(row, "fighter")
    if len(fighter_links) < 2:
        raise ParseError(f"Missing fighter ids for fight {fight_id}")
    fighter_ids = [extract_id(link[0], "fighter") for link in fighter_links[:2]]
    names = [link[1] for link in fighter_links[:2]]
    cells = [clean_text(cell) for cell in row.select("td")]
    row_text = clean_text(row)
    statuses = _parse_outcomes(cells[0] if cells else row_text)
    method = (
        clean_text(cells[7])
        if len(cells) > 9 and clean_text(cells[7]) not in {"", "--"}
        else _extract_after_label(row_text, "METHOD") or _cell_after(cells, names[-1])
    )
    round_value = (
        clean_text(cells[8])
        if len(cells) > 9 and clean_text(cells[8])
        else _extract_after_label(row_text, "ROUND") or _first_regex(row_text, r"\b([1-5])\b")
    )
    time_value = _extract_after_label(row_text, "TIME") or _first_regex(
        row_text, r"\b\d{1,2}:\d{2}\b"
    )
    if len(cells) > 9 and clean_text(cells[9]):
        time_value = clean_text(cells[9])
    if not method or not round_value or not time_value:
        method, round_value, time_value = _fallback_method_round_time(cells)
    if not method or not round_value or not time_value:
        if not statuses:
            return None
        raise ParseError(f"Missing required fight fields for {fight_id}")
    winner_id = None
    if statuses[:2] == ["W", "L"]:
        winner_id = fighter_ids[0]
    elif statuses[:2] == ["L", "W"]:
        winner_id = fighter_ids[1]
    participants = [
        FightParticipant(
            fight_id=fight_id,
            event_id=event_id,
            fighter_id=fighter_ids[0],
            opponent_id=fighter_ids[1],
            corner="red",
            full_name=names[0],
            winner_flag=winner_id == fighter_ids[0],
            outcome=statuses[0] if statuses else None,
        ),
        FightParticipant(
            fight_id=fight_id,
            event_id=event_id,
            fighter_id=fighter_ids[1],
            opponent_id=fighter_ids[0],
            corner="blue",
            full_name=names[1],
            winner_flag=winner_id == fighter_ids[1],
            outcome=statuses[1] if len(statuses) > 1 else None,
        ),
    ]
    fight = Fight(
        fight_id=fight_id,
        event_id=event_id,
        winner_id=winner_id,
        method=method,
        round=int(round_value),
        time=time_value,
        time_format=None,
        referee=None,
        url=fight_url,
    )
    return fight, participants


def _parse_fight_stats_table(
    soup: BeautifulSoup, fight_id: str, event_id: str, fighter_ids: list[str]
) -> list[FighterFightStats]:
    table = soup.select_one("table.b-fight-details__table, table[data-stats='totals'], table")
    if table is None:
        return []
    headers = [clean_text(cell).lower().replace(" ", "_") for cell in table.select("thead th")]
    row = table.select_one("tbody tr")
    if row is None:
        return []
    values_by_header: dict[str, list[str]] = {}
    for index, cell in enumerate(row.select("td")):
        header = headers[index] if index < len(headers) else f"col_{index}"
        values = [clean_text(item) for item in cell.select("p") if clean_text(item)]
        if len(values) < 2:
            split = [part for part in re.split(r"\s{2,}", clean_text(cell)) if part]
            values = split[:2]
        values_by_header[header] = values[:2]

    def val(header: str, side: int) -> str:
        for key, values in values_by_header.items():
            normalized = key.replace(".", "").replace("__", "_")
            if header in normalized and len(values) > side:
                return values[side]
        return ""

    rows: list[FighterFightStats] = []
    for side, corner in enumerate(["red", "blue"]):
        sig_landed, sig_attempted = parse_landed_attempted(val("sig_str", side))
        total_landed, total_attempted = parse_landed_attempted(val("total_str", side))
        td_landed, td_attempted = parse_landed_attempted(val("td", side))
        rows.append(
            FighterFightStats(
                fight_id=fight_id,
                event_id=event_id,
                fighter_id=fighter_ids[side],
                opponent_id=fighter_ids[1 - side],
                corner=corner,
                kd=parse_int(val("kd", side)),
                sig_str_landed=sig_landed,
                sig_str_attempted=sig_attempted,
                total_str_landed=total_landed,
                total_str_attempted=total_attempted,
                td_landed=td_landed,
                td_attempted=td_attempted,
                sub_att=parse_int(val("sub", side)),
                rev=parse_int(val("rev", side)),
                ctrl_sec=parse_duration_to_sec(val("ctrl", side)),
            )
        )
    return rows


def _unique_links(soup: Tag | BeautifulSoup, entity: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for link in soup.select(f"a[href*='{entity}-details/']"):
        url = absolute_url(link.get("href", ""))
        if url in seen:
            continue
        text = clean_text(link)
        if not text:
            continue
        links.append((url, text))
        seen.add(url)
    return links


def _parse_label_values(soup: BeautifulSoup) -> dict[str, str]:
    fields: dict[str, str] = {}
    for item in soup.select("li"):
        title = item.select_one(".b-list__box-item-title")
        if title is None:
            item_text = clean_text(item)
            if ":" not in item_text:
                continue
            raw_key, value = item_text.split(":", 1)
            key = raw_key.strip().lower()
            if key in {"height", "weight", "reach", "stance", "dob"}:
                fields[key] = clean_text(value)
            continue
        key = clean_text(title).rstrip(":").lower()
        if key not in {"height", "weight", "reach", "stance", "dob"}:
            continue
        title.extract()
        fields[key] = clean_text(item)
    return fields


def _none_if_blank(value: str | None) -> str | None:
    value = clean_text(value)
    return None if not value or value == "--" else value


def _strip_record_suffix(value: str) -> str:
    return clean_text(re.sub(r"\s+Record:\s+.+$", "", clean_text(value), flags=re.I))


def _parse_optional_date(value: str) -> date | None:
    value = clean_text(value)
    if not value or value == "--":
        return None
    return parse_ufcstats_date(value)


def _extract_after_label(text: str, label: str) -> str | None:
    match = re.search(rf"{label}:\s*([^:]+?)(?=\s+[A-Z][A-Z ]+:|$)", text, re.I)
    return clean_text(match.group(1)) if match else None


def _first_regex(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match and match.groups() else (match.group(0) if match else None)


def _cell_after(cells: list[str], after_value: str) -> str | None:
    for index, cell in enumerate(cells):
        if after_value in cell and index + 1 < len(cells):
            return cells[index + 1]
    return None


def _fallback_method_round_time(cells: list[str]) -> tuple[str | None, str | None, str | None]:
    method = None
    round_value = None
    time_value = None
    for cell in cells:
        if method is None and any(token in cell.lower() for token in ["dec", "sub", "ko", "tko"]):
            method = cell
        if round_value is None and re.fullmatch(r"[1-5]", cell):
            round_value = cell
        if time_value is None and re.fullmatch(r"\d{1,2}:\d{2}", cell):
            time_value = cell
    return method, round_value, time_value


def _parse_outcomes(value: str) -> list[str]:
    normalized = clean_text(value).lower()
    if not normalized:
        return []
    token_map = {"win": "W", "loss": "L", "draw": "D", "nc": "NC", "w": "W", "l": "L"}
    return [token_map[token] for token in normalized.split() if token in token_map]


def parse_all_cached(raw_dir: Path) -> dict[str, list[dict[str, object]]]:
    ufc_dir = raw_dir / "ufcstats"
    events: list[Event] = []
    fights: list[Fight] = []
    participants: list[FightParticipant] = []
    fighters: list[Fighter] = []
    stats: list[FighterFightStats] = []
    for path in sorted((ufc_dir / "events").glob("*.html")):
        result = parse_event_detail(path.read_text(encoding="utf-8"), event_id=path.stem)
        if result.event.event_date > date.today():
            continue
        events.append(result.event)
        fights.extend(result.fights)
        participants.extend(result.participants)
    fight_event = {fight.fight_id: fight.event_id for fight in fights}
    for path in sorted((ufc_dir / "fights").glob("*.html")):
        event_id = fight_event.get(path.stem)
        if event_id is None:
            continue
        result = parse_fight_detail(
            path.read_text(encoding="utf-8"),
            event_id=event_id,
            url=f"{BASE_URL}/fight-details/{path.stem}",
        )
        stats.extend(result.stats)
        if result.participants:
            participants = [
                item for item in participants if item.fight_id != result.fight_id
            ] + result.participants
    for path in sorted((ufc_dir / "fighters").glob("*.html")):
        fighters.append(
            parse_fighter_detail(
                path.read_text(encoding="utf-8"),
                url=f"{BASE_URL}/fighter-details/{path.stem}",
            )
        )
    return {
        "events": to_rows(events),
        "fights": to_rows(fights),
        "fight_participants": to_rows(participants),
        "fighters": to_rows(fighters),
        "fighter_fight_stats": to_rows(stats),
    }
