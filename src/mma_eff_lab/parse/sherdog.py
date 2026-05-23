from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.sherdog.com"
SOURCE = "sherdog"
NON_MMA_TOKENS = ("kickboxing", "muay thai", "submission grappling", "grappling")


class SherdogParseError(ValueError):
    pass


@dataclass(frozen=True)
class SherdogEvent:
    source: str
    source_event_id: str
    name: str
    event_date: date
    location: str | None
    promotion: str
    url: str


@dataclass(frozen=True)
class SherdogFight:
    source: str
    source_fight_id: str
    source_event_id: str
    promotion: str
    weight_class: str | None
    winner_source_fighter_id: str | None
    method: str
    round: int
    time: str
    referee: str | None
    url: str


@dataclass(frozen=True)
class SherdogFightParticipant:
    source: str
    source_fight_id: str
    source_event_id: str
    source_fighter_id: str
    opponent_source_fighter_id: str
    promotion: str
    corner: str
    full_name: str
    winner_flag: bool
    outcome: str | None


@dataclass(frozen=True)
class SherdogFighter:
    source: str
    source_fighter_id: str
    full_name: str
    height_in: int | None
    weight_lbs: int | None
    reach_in: int | None
    stance: str | None
    dob: date | None
    url: str


@dataclass(frozen=True)
class ParseQuarantine:
    source: str
    entity_type: str
    source_entity_id: str
    promotion: str | None
    reason: str
    url: str


@dataclass(frozen=True)
class SherdogOrgResult:
    events: list[SherdogEvent]
    older_url: str | None


@dataclass(frozen=True)
class SherdogEventResult:
    event: SherdogEvent
    fights: list[SherdogFight]
    participants: list[SherdogFightParticipant]
    fighters: list[SherdogFighter]
    quarantine: list[ParseQuarantine]


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


def absolute_url(url: str) -> str:
    return urljoin(BASE_URL, url)


def extract_event_id(url: str) -> str:
    match = re.search(r"/events/[^/#?]+-(\d+)", url)
    if not match:
        raise SherdogParseError(f"Could not extract Sherdog event id from {url}")
    return match.group(1)


def extract_fighter_id(url: str) -> str:
    match = re.search(r"/fighter/(?:[^/#?]+-)?(\d+)", url)
    if not match:
        raise SherdogParseError(f"Could not extract Sherdog fighter id from {url}")
    return match.group(1)


def parse_sherdog_date(value: str) -> date:
    value = clean_text(value).replace(",", "")
    value = re.sub(r"\s+", " ", value)
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SherdogParseError(f"Could not parse Sherdog date: {value}")


def parse_height(value: str) -> int | None:
    match = re.search(r"(\d+)'\s*(\d+)", clean_text(value))
    if not match:
        return None
    return int(match.group(1)) * 12 + int(match.group(2))


def parse_int(value: str) -> int | None:
    match = re.search(r"-?\d+", clean_text(value).replace(",", ""))
    return int(match.group(0)) if match else None


def parse_org_page(
    html: str, promotion: str, organization_id: str, url: str
) -> SherdogOrgResult:
    soup = BeautifulSoup(html, "html.parser")
    events: list[SherdogEvent] = []
    seen: set[str] = set()
    for table in soup.select("table.new_table.event"):
        for row in table.select("tr"):
            if row.get("class") and "table_head" in row.get("class", []):
                continue
            cells = row.select("td")
            link = row.select_one("a[href*='/events/']")
            if len(cells) < 3 or link is None:
                continue
            event_url = absolute_url(link.get("href", ""))
            source_event_id = extract_event_id(event_url)
            if source_event_id in seen:
                continue
            events.append(
                SherdogEvent(
                    source=SOURCE,
                    source_event_id=source_event_id,
                    name=clean_text(link),
                    event_date=parse_sherdog_date(clean_text(cells[0])),
                    location=clean_text(cells[2]) or None,
                    promotion=promotion,
                    url=event_url,
                )
            )
            seen.add(source_event_id)
    older_url = None
    older = soup.find("a", string=re.compile(r"Older Events", re.I))
    if isinstance(older, Tag) and older.get("href"):
        older_url = absolute_url(older["href"])
    if not events and not older_url:
        raise SherdogParseError(f"Missing organization events for {organization_id}: {url}")
    return SherdogOrgResult(events=events, older_url=older_url)


def parse_event_detail(
    html: str,
    source_event_id: str | None = None,
    promotion_hint: str | None = None,
    url: str | None = None,
) -> SherdogEventResult:
    soup = BeautifulSoup(html, "html.parser")
    event_url = url or _canonical_page_url(soup) or ""
    resolved_event_id = source_event_id or extract_event_id(event_url)
    detail = soup.select_one(".event_detail") or soup
    title_node = detail.select_one("h1, h2")
    name = clean_text(title_node)
    promotion_node = detail.select_one("a[href*='/organizations/']")
    promotion = clean_text(promotion_node) or promotion_hint or ""
    detail_text = clean_text(detail)
    date_match = re.search(r"\b([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})\b", detail_text)
    if not name or not promotion or not date_match:
        raise SherdogParseError(f"Missing required event fields for {resolved_event_id}")
    event_date = parse_sherdog_date(date_match.group(1))
    location = _extract_location(detail, date_match.group(1))
    event = SherdogEvent(
        source=SOURCE,
        source_event_id=resolved_event_id,
        name=name,
        event_date=event_date,
        location=location,
        promotion=promotion,
        url=event_url or f"{BASE_URL}/events/{resolved_event_id}",
    )
    fights: list[SherdogFight] = []
    participants: list[SherdogFightParticipant] = []
    fighters: dict[str, SherdogFighter] = {}
    quarantine: list[ParseQuarantine] = []
    fight_rows = _parse_result_table(soup, event)
    if not fight_rows:
        main_event = _parse_main_event(soup, event)
        if main_event is not None:
            fight_rows = [main_event]
    fights_by_id: dict[str, SherdogFight] = {}
    participants_by_fight: dict[str, dict[tuple[str, str, str, str], SherdogFightParticipant]] = {}

    for parsed in fight_rows:
        if parsed is None:
            continue
        fight, row_participants, row_fighters = parsed
        fights_by_id.setdefault(fight.source_fight_id, fight)
        participant_rows = participants_by_fight.setdefault(fight.source_fight_id, {})
        for participant in row_participants:
            participant_rows.setdefault(_participant_key(participant), participant)
        for fighter in row_fighters:
            fighters[fighter.source_fighter_id] = fighter
    for fight_id, fight in fights_by_id.items():
        row_participants = list(participants_by_fight.get(fight_id, {}).values())
        if not _valid_participant_shape(row_participants):
            quarantine.append(
                ParseQuarantine(
                    source=SOURCE,
                    entity_type="fight",
                    source_entity_id=fight.source_fight_id,
                    promotion=event.promotion,
                    reason="invalid_participant_shape",
                    url=fight.url,
                )
            )
            continue
        if _must_quarantine_one(fight, row_participants):
            quarantine.append(
                ParseQuarantine(
                    source=SOURCE,
                    entity_type="fight",
                    source_entity_id=fight.source_fight_id,
                    promotion=event.promotion,
                    reason="ambiguous_or_non_mma_one_bout",
                    url=fight.url,
                )
            )
            continue
        fights.append(fight)
        participants.extend(row_participants)
    return SherdogEventResult(
        event=event,
        fights=fights,
        participants=participants,
        fighters=list(fighters.values()),
        quarantine=quarantine,
    )


def parse_fighter_detail(html: str, url: str) -> SherdogFighter:
    soup = BeautifulSoup(html, "html.parser")
    source_fighter_id = extract_fighter_id(url)
    title = clean_text(soup.title.string if soup.title else "")
    full_name = re.sub(r"\s+MMA Stats.*$", "", title).strip()
    if not full_name:
        name_node = soup.select_one(".fighter-line1 .fn, h1")
        full_name = clean_text(name_node)
    if not full_name:
        raise SherdogParseError(f"Missing fighter name for {source_fighter_id}")
    data = clean_text(soup.select_one(".fighter-data"))
    return SherdogFighter(
        source=SOURCE,
        source_fighter_id=source_fighter_id,
        full_name=full_name,
        height_in=parse_height(_between(data, "HEIGHT", "WEIGHT")),
        weight_lbs=parse_int(_between(data, "WEIGHT", "ASSOCIATION")),
        reach_in=None,
        stance=_optional_between(data, "STYLE", "Wins"),
        dob=_parse_optional_dob(data),
        url=absolute_url(url),
    )


def parse_all_cached(raw_dir: Path) -> dict[str, list[dict[str, object]]]:
    sherdog_dir = raw_dir / "sherdog"
    events: dict[str, SherdogEvent] = {}
    fights: dict[str, SherdogFight] = {}
    participants: dict[tuple[str, str, str, str], SherdogFightParticipant] = {}
    fighters: dict[str, SherdogFighter] = {}
    quarantine: list[ParseQuarantine] = []
    for path in sorted((sherdog_dir / "events").glob("*.html")):
        result = parse_event_detail(path.read_text(encoding="utf-8"), source_event_id=path.stem)
        if result.event.event_date > date.today():
            continue
        events[result.event.source_event_id] = result.event
        for fight in result.fights:
            fights[fight.source_fight_id] = fight
        for participant in result.participants:
            participants.setdefault(_participant_key(participant), participant)
        for fighter in result.fighters:
            fighters[fighter.source_fighter_id] = fighter
        quarantine.extend(result.quarantine)
    for path in sorted((sherdog_dir / "fighters").glob("*.html")):
        fighter = parse_fighter_detail(
            path.read_text(encoding="utf-8"), url=f"{BASE_URL}/fighter/{path.stem}"
        )
        existing = fighters.get(fighter.source_fighter_id)
        if existing is None or fighter.dob is not None:
            fighters[fighter.source_fighter_id] = fighter
    return {
        "source_events": to_rows(list(events.values())),
        "source_fights": to_rows(list(fights.values())),
        "source_fight_participants": to_rows(list(participants.values())),
        "source_fighters": to_rows(list(fighters.values())),
        "parse_quarantine": to_rows(quarantine),
    }


def _parse_main_event(
    soup: BeautifulSoup, event: SherdogEvent
) -> tuple[SherdogFight, list[SherdogFightParticipant], list[SherdogFighter]] | None:
    card = soup.select_one(".fight_card")
    resume = soup.select_one("table.fight_card_resume")
    if card is None or resume is None:
        return None
    fighters = [_fighter_from_link(link) for link in card.select("h3 a[href*='/fighter/']")[:2]]
    if len(fighters) < 2 or fighters[0] is None or fighters[1] is None:
        return None
    cells = {
        clean_text(cell.select_one("em")).lower(): clean_text(cell)
        for cell in resume.select("td")
    }
    match_number = _last_token(cells.get("match", "")) or "main"
    method = _strip_label(cells.get("method", ""), "Method")
    round_value = _strip_label(cells.get("round", ""), "Round")
    time_value = _strip_label(cells.get("time", ""), "Time")
    referee = _strip_label(cells.get("referee", ""), "Referee") or None
    if not method or not round_value or not time_value:
        return None
    statuses = [clean_text(node).lower() for node in card.select(".final_result")[:2]]
    return _fight_bundle(
        event=event,
        match_number=match_number,
        left=fighters[0],
        right=fighters[1],
        left_outcome=_normalize_outcome(statuses[0] if statuses else ""),
        right_outcome=_normalize_outcome(statuses[1] if len(statuses) > 1 else ""),
        weight_class=clean_text(card.select_one(".weight_class")) or None,
        method=method,
        referee=referee,
        round_value=round_value,
        time_value=time_value,
    )


def _parse_result_table(
    soup: BeautifulSoup, event: SherdogEvent
) -> list[tuple[SherdogFight, list[SherdogFightParticipant], list[SherdogFighter]] | None]:
    parsed = []
    table = soup.select_one("table.new_table.result")
    if table is None:
        return parsed
    for row in table.select("tr"):
        if row.get("class") and "table_head" in row.get("class", []):
            continue
        cells = row.select("td")
        if len(cells) < 7:
            continue
        left = _fighter_from_link(cells[1].select_one("a[href*='/fighter/']"))
        right = _fighter_from_link(cells[3].select_one("a[href*='/fighter/']"))
        if left is None or right is None:
            continue
        method_node = cells[4].select_one("b")
        referee_node = cells[4].select_one(".sub_line")
        parsed.append(
            _fight_bundle(
                event=event,
                match_number=clean_text(cells[0]),
                left=left,
                right=right,
                left_outcome=_normalize_outcome(clean_text(cells[1].select_one(".final_result"))),
                right_outcome=_normalize_outcome(clean_text(cells[3].select_one(".final_result"))),
                weight_class=clean_text(cells[2].select_one(".weight_class") or cells[2]) or None,
                method=clean_text(method_node) or clean_text(cells[4]),
                referee=clean_text(referee_node) or None,
                round_value=clean_text(cells[5]),
                time_value=clean_text(cells[6]),
            )
        )
    return parsed


def _fight_bundle(
    event: SherdogEvent,
    match_number: str,
    left: SherdogFighter,
    right: SherdogFighter,
    left_outcome: str | None,
    right_outcome: str | None,
    weight_class: str | None,
    method: str,
    referee: str | None,
    round_value: str,
    time_value: str,
) -> tuple[SherdogFight, list[SherdogFightParticipant], list[SherdogFighter]] | None:
    if not method or not round_value or not time_value:
        return None
    source_fight_id = f"{event.source_event_id}:{match_number}"
    winner_source_fighter_id = None
    if left_outcome == "W":
        winner_source_fighter_id = left.source_fighter_id
    elif right_outcome == "W":
        winner_source_fighter_id = right.source_fighter_id
    fight = SherdogFight(
        source=SOURCE,
        source_fight_id=source_fight_id,
        source_event_id=event.source_event_id,
        promotion=event.promotion,
        weight_class=weight_class,
        winner_source_fighter_id=winner_source_fighter_id,
        method=method,
        round=int(round_value),
        time=time_value,
        referee=referee,
        url=f"{event.url}#match-{match_number}",
    )
    participants = [
        SherdogFightParticipant(
            source=SOURCE,
            source_fight_id=source_fight_id,
            source_event_id=event.source_event_id,
            source_fighter_id=left.source_fighter_id,
            opponent_source_fighter_id=right.source_fighter_id,
            promotion=event.promotion,
            corner="red",
            full_name=left.full_name,
            winner_flag=winner_source_fighter_id == left.source_fighter_id,
            outcome=left_outcome,
        ),
        SherdogFightParticipant(
            source=SOURCE,
            source_fight_id=source_fight_id,
            source_event_id=event.source_event_id,
            source_fighter_id=right.source_fighter_id,
            opponent_source_fighter_id=left.source_fighter_id,
            promotion=event.promotion,
            corner="blue",
            full_name=right.full_name,
            winner_flag=winner_source_fighter_id == right.source_fighter_id,
            outcome=right_outcome,
        ),
    ]
    return fight, participants, [left, right]


def _fighter_from_link(link: Tag | None) -> SherdogFighter | None:
    if link is None or not link.get("href"):
        return None
    url = absolute_url(link["href"])
    return SherdogFighter(
        source=SOURCE,
        source_fighter_id=extract_fighter_id(url),
        full_name=clean_text(link),
        height_in=None,
        weight_lbs=None,
        reach_in=None,
        stance=None,
        dob=None,
        url=url,
    )


def _extract_location(detail: Tag | BeautifulSoup, date_text: str) -> str | None:
    text = clean_text(detail)
    after_date = text.split(date_text, 1)[-1]
    after_date = re.sub(r"^Image:\s*[^ ]+\s*", "", after_date).strip()
    if not after_date:
        return None
    stop = re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+ \d+-\d+-\d+\b", after_date)
    return clean_text(after_date[: stop.start()] if stop else after_date) or None


def _canonical_page_url(soup: BeautifulSoup) -> str | None:
    for selector in ["link[rel='canonical']", "meta[property='og:url']"]:
        node = soup.select_one(selector)
        if node and node.get("href"):
            return absolute_url(node["href"])
        if node and node.get("content"):
            return absolute_url(node["content"])
    return None


def _must_quarantine_one(
    fight: SherdogFight, participants: list[SherdogFightParticipant]
) -> bool:
    if "one" not in fight.promotion.lower():
        return False
    text = " ".join(
        [
            fight.weight_class or "",
            fight.method,
            *(participant.full_name for participant in participants),
        ]
    ).lower()
    return any(token in text for token in NON_MMA_TOKENS)


def _participant_key(
    participant: SherdogFightParticipant,
) -> tuple[str, str, str, str]:
    return (
        participant.source,
        participant.source_fight_id,
        participant.source_fighter_id,
        participant.corner,
    )


def _valid_participant_shape(participants: list[SherdogFightParticipant]) -> bool:
    if len(participants) != 2:
        return False
    corners = {participant.corner for participant in participants}
    return corners == {"red", "blue"}


def _strip_label(value: str, label: str) -> str:
    return clean_text(re.sub(rf"^{label}\s*", "", clean_text(value), flags=re.I))


def _last_token(value: str) -> str | None:
    tokens = clean_text(value).split()
    return tokens[-1] if tokens else None


def _normalize_outcome(value: str) -> str | None:
    value = clean_text(value).lower()
    return {"win": "W", "loss": "L", "draw": "D", "nc": "NC", "no contest": "NC"}.get(value)


def _between(text: str, left: str, right: str) -> str:
    match = re.search(rf"{left}\s+(.+?)\s+{right}\b", text, re.I)
    return clean_text(match.group(1)) if match else ""


def _optional_between(text: str, left: str, right: str) -> str | None:
    value = _between(text, left, right)
    return value or None


def _parse_optional_dob(text: str) -> date | None:
    match = re.search(r"\b([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})\b", text)
    return parse_sherdog_date(match.group(1)) if match else None
