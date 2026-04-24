from __future__ import annotations

import csv
import html as html_lib
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .models import Fight
from .overrides import OverrideData, canonical_name
from .util import display_name, identity_key, iso_date, parse_date, read_csv, read_json, stable_id, today_utc, write_json


class ScraperSchemaError(RuntimeError):
    """Raised when the UFCStats scraper cannot parse a bout safely."""


class ManualRowError(ValueError):
    """Raised when a manual CSV row is missing required fields."""


MANUAL_REQUIRED_FIELDS = ("event_date", "red_fighter_name", "blue_fighter_name", "bout_type")
NON_MMA_BOUT_KEYWORDS = (
    "muay thai",
    "kickboxing",
    "boxing",
    "submission grappling",
    "grappling",
)


WEIGHT_CLASSES = [
    "Women's Atomweight",
    "Women's Strawweight",
    "Women's Flyweight",
    "Women's Bantamweight",
    "Women's Featherweight",
    "Strawweight",
    "Light Heavyweight",
    "Open Weight",
    "Catch Weight",
    "Heavyweight",
    "Middleweight",
    "Welterweight",
    "Lightweight",
    "Featherweight",
    "Bantamweight",
    "Flyweight",
]
POUND_CLASS_MAP = {
    105: ("men", "Atomweight"),
    115: ("women", "Strawweight"),
    125: ("men", "Flyweight"),
    135: ("men", "Bantamweight"),
    145: ("men", "Featherweight"),
    155: ("men", "Lightweight"),
    170: ("men", "Welterweight"),
    185: ("men", "Middleweight"),
    205: ("men", "Light Heavyweight"),
    265: ("men", "Heavyweight"),
}
WOMENS_POUND_CLASS_MAP = {
    105: ("women", "Atomweight"),
    47: ("women", "Atomweight"),
    48: ("women", "Atomweight"),
    49: ("women", "Atomweight"),
    50: ("women", "Atomweight"),
    115: ("women", "Strawweight"),
    51: ("women", "Strawweight"),
    52: ("women", "Strawweight"),
    53: ("women", "Strawweight"),
    125: ("women", "Flyweight"),
    135: ("women", "Bantamweight"),
    145: ("women", "Featherweight"),
}


PRIMARY_URLS = [
    "https://raw.githubusercontent.com/komaksym/UFC-DataLab/main/data/stats/stats_processed_all_bouts.csv",
    "https://raw.githubusercontent.com/komaksym/UFC-DataLab/main/data/stats/stats_raw.csv",
]
OFFICIAL_EVENTS_URL = "https://www.ufc.com/events?language_content_entity=en"
OFFICIAL_EVENT_PATH_RE = re.compile(r'href="(/event/[^"#?]+)"')


def fetch_url(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ufc-elo-ratings/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8-sig")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
            with urllib.request.urlopen(request, timeout=timeout, context=ssl._create_unverified_context()) as response:
                return response.read().decode("utf-8-sig")
        raise


def fetch_primary_rows(raw_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    errors: list[str] = []
    for url in PRIMARY_URLS:
        try:
            text = fetch_url(url)
            raw_dir.mkdir(parents=True, exist_ok=True)
            filename = url.rsplit("/", 1)[-1]
            (raw_dir / filename).write_text(text, encoding="utf-8")
            delimiter = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
            rows = list(csv.DictReader(text.splitlines(), delimiter=delimiter))
            return rows, {"source": url, "rows": len(rows), "errors": errors}
        except (urllib.error.URLError, TimeoutError, csv.Error) as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Unable to fetch UFC-DataLab primary data: " + "; ".join(errors))


def load_primary_local(path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    rows = read_csv(path)
    return rows, {"source": str(path), "rows": len(rows), "errors": []}


def load_manual_rows(manual_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for path in sorted(manual_dir.glob("*.csv")):
        for index, row in enumerate(read_csv(path), start=2):
            row["_manual_source"] = str(path)
            missing = [field for field in MANUAL_REQUIRED_FIELDS if not (row.get(field) or "").strip()]
            if missing:
                errors.append(f"{path.name} row {index}: missing {', '.join(missing)}")
                continue
            if not has_manual_result(row):
                errors.append(f"{path.name} row {index}: missing fight_outcome or red/blue result fields")
                continue
            rows.append(row)
    for path in sorted(manual_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else payload.get("fights", [])
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                errors.append(f"{path.name} item {index}: not an object")
                continue
            item = {str(k): "" if v is None else str(v) for k, v in item.items()}
            item["_manual_source"] = str(path)
            missing = [field for field in MANUAL_REQUIRED_FIELDS if not (item.get(field) or "").strip()]
            if missing:
                errors.append(f"{path.name} item {index}: missing {', '.join(missing)}")
                continue
            if not has_manual_result(item):
                errors.append(f"{path.name} item {index}: missing fight_outcome or red/blue result fields")
                continue
            rows.append(item)
    if errors:
        raise ManualRowError("Manual event files have invalid rows:\n  " + "\n  ".join(errors))
    return rows


def has_manual_result(row: dict[str, str]) -> bool:
    return normalize_outcome(row) != "unknown"


def is_mma_bout(event_name: str, bout_type: str, method: str) -> bool:
    haystack = " | ".join(
        [
            clean_text(event_name).lower(),
            clean_text(bout_type).lower(),
            clean_text(method).lower(),
        ]
    )
    return not any(keyword in haystack for keyword in NON_MMA_BOUT_KEYWORDS)


def rows_to_fights(rows: list[dict[str, str]], source: str, overrides: OverrideData) -> list[Fight]:
    fights: list[Fight] = []
    for row in rows:
        try:
            event_date = parse_date(row.get("event_date", ""))
        except ValueError:
            continue

        red_name = clean_fighter_name(row.get("red_fighter_name", ""))
        blue_name = clean_fighter_name(row.get("blue_fighter_name", ""))
        if not red_name or not blue_name:
            continue

        red_name = canonical_name(red_name, overrides)
        blue_name = canonical_name(blue_name, overrides)
        bout_type = clean_text(row.get("bout_type", "Unknown Bout"))
        if not is_mma_bout(row.get("event_name", ""), bout_type, row.get("method", "")):
            continue
        gender, weight_class = parse_bout_type(bout_type)
        outcome = normalize_outcome(row)
        fight_id = make_fight_id(event_date, row.get("event_name", ""), red_name, blue_name, bout_type)
        fight = Fight(
            fight_id=fight_id,
            event_date=event_date,
            event_name=clean_text(row.get("event_name", "")),
            event_location=clean_text(row.get("event_location", "")),
            red_name=red_name,
            blue_name=blue_name,
            red_nickname=clean_text(row.get("red_fighter_nickname", "")),
            blue_nickname=clean_text(row.get("blue_fighter_nickname", "")),
            outcome=outcome,
            method=clean_text(row.get("method", "")),
            round=clean_text(row.get("round", "")),
            time=clean_text(row.get("time", "")),
            bout_type=bout_type,
            gender=gender,
            weight_class=weight_class,
            is_title=is_ufc_title_bout(bout_type),
            source=source,
            raw=row,
        )
        fights.append(apply_result_override(fight, overrides))
    fights = [fight for fight in fights if fight.fight_id not in overrides.excluded_bouts]
    infer_missing_weight_classes(fights)
    return fights


def clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def clean_fighter_name(value: str) -> str:
    return display_name(clean_text(value))


def normalize_outcome(row: dict[str, str]) -> str:
    outcome = clean_text(row.get("fight_outcome", "")).lower()
    if outcome in {"red_win", "blue_win", "draw", "no_contest"}:
        return outcome
    red_result = clean_text(row.get("red_fighter_result", "")).upper()
    blue_result = clean_text(row.get("blue_fighter_result", "")).upper()
    if red_result == "W" and blue_result == "L":
        return "red_win"
    if blue_result == "W" and red_result == "L":
        return "blue_win"
    if red_result == "D" or blue_result == "D":
        return "draw"
    if red_result == "NC" or blue_result == "NC":
        return "no_contest"
    return "unknown"


def parse_bout_type(bout_type: str) -> tuple[str, str]:
    normalized = bout_type.lower().replace("catchweight", "catch weight").replace("openweight", "open weight")
    normalized = normalized.replace("stawweight", "strawweight").replace("weltererweight", "welterweight")
    normalized = normalized.replace("women's", "women").replace("w.", "women ").replace("w ", "women ")
    normalized = normalized.replace("super atomweight", "atomweight")
    womens = any(token in normalized for token in ("women", "female"))
    for weight_class in WEIGHT_CLASSES:
        if weight_class.lower() in normalized:
            gender = "women" if womens or weight_class.startswith("Women's") or "atomweight" in weight_class.lower() else "men"
            clean_weight = weight_class.replace("Women's ", "")
            return gender, clean_weight
    if "catch weight" in normalized:
        return ("women", "Catch Weight") if womens else ("men", "Catch Weight")
    pound_match = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(?:-|\s)?(?:lb|lbs|pound|kg)", normalized)
    if pound_match:
        amount = float(pound_match.group(1))
        if "kg" in normalized:
            pounds = round(amount * 2.20462)
            if 46 <= amount <= 50:
                return ("women", "Atomweight")
            if 51 <= amount <= 53:
                return ("women", "Strawweight") if womens or "atomweight" in normalized else ("men", "Strawweight")
        else:
            pounds = int(round(amount))
        mapping = WOMENS_POUND_CLASS_MAP if womens else POUND_CLASS_MAP
        if pounds in mapping:
            return mapping[pounds]
        nearest = nearest_mapped_weight(pounds, mapping)
        if nearest is not None:
            return mapping[nearest]
    if "atomweight" in normalized:
        return ("women", "Atomweight")
    if "strawweight" in normalized:
        return ("women", "Strawweight") if womens else ("men", "Strawweight")
    return ("women", "Unknown") if womens else ("men", "Unknown")


def is_ufc_title_bout(bout_type: str) -> bool:
    value = bout_type.lower()
    if "ufc" not in value or "title" not in value:
        return False
    if "tournament" in value:
        return False
    return True


def make_fight_id(event_date: date, event_name: str, red_name: str, blue_name: str, bout_type: str) -> str:
    return stable_id([event_date.isoformat(), identity_key(event_name), identity_key(red_name), identity_key(blue_name), identity_key(bout_type)])


def apply_result_override(fight: Fight, overrides: OverrideData) -> Fight:
    override = overrides.result_overrides.get(fight.fight_id)
    if not override:
        return fight
    if override.get("outcome"):
        fight.outcome = override["outcome"]
    if override.get("method"):
        fight.method = override["method"]
    if override.get("notes"):
        fight.raw["override_notes"] = override["notes"]
    return fight


def filter_fights(fights: list[Fight], since: str | None = None) -> list[Fight]:
    if not since:
        return fights
    cutoff = parse_date(since)
    return [fight for fight in fights if fight.event_date >= cutoff]


def infer_missing_weight_classes(fights: list[Fight]) -> None:
    known_history = build_weight_history(fights)
    for fight in fights:
        if fight.weight_class != "Unknown":
            continue
        inferred = infer_fight_weight_class(fight, known_history)
        if not inferred:
            continue
        fight.gender, fight.weight_class, fight.bout_type = inferred
        fight.raw["inferred_bout_type"] = fight.bout_type
        fight.raw["weight_class_inferred"] = "true"


def build_weight_history(fights: list[Fight]) -> dict[str, list[tuple[date, str, str]]]:
    history: dict[str, list[tuple[date, str, str]]] = {}
    for fight in sorted(fights, key=lambda item: (item.event_date, item.fight_id)):
        if fight.weight_class in {"Unknown", "Catch Weight"}:
            continue
        for fighter_name in (fight.red_name, fight.blue_name):
            history.setdefault(fighter_name, []).append((fight.event_date, fight.gender, fight.weight_class))
    return history


def infer_fight_weight_class(
    fight: Fight,
    known_history: dict[str, list[tuple[date, str, str]]],
) -> tuple[str, str, str] | None:
    red_guess = nearest_weight_class(fight.red_name, fight.event_date, known_history)
    blue_guess = nearest_weight_class(fight.blue_name, fight.event_date, known_history)
    if not red_guess and not blue_guess:
        return None
    if red_guess and blue_guess:
        red_gender, red_weight = red_guess
        blue_gender, blue_weight = blue_guess
        gender = red_gender or blue_gender
        if red_weight == blue_weight:
            return gender, red_weight, f"{red_weight} Bout"
        return gender, "Catch Weight", "Catch Weight Bout"
    gender, weight_class = red_guess or blue_guess  # type: ignore[misc]
    return gender, weight_class, f"{weight_class} Bout"


def nearest_weight_class(
    fighter_name: str,
    event_date: date,
    known_history: dict[str, list[tuple[date, str, str]]],
) -> tuple[str, str] | None:
    entries = known_history.get(fighter_name, [])
    if not entries:
        return None
    best = min(
        entries,
        key=lambda item: (
            abs((item[0] - event_date).days),
            0 if item[0] <= event_date else 1,
            -item[0].toordinal(),
        ),
    )
    return best[1], best[2]


def nearest_mapped_weight(value: int, mapping: dict[int, tuple[str, str]], tolerance: int = 3) -> int | None:
    if not mapping:
        return None
    nearest = min(mapping, key=lambda item: abs(item - value))
    return nearest if abs(nearest - value) <= tolerance else None


def source_health(
    fights: list[Fight],
    stale_after_days: int,
    manifest_path: Path | None = None,
    drift_tolerance: float = 0.25,
) -> dict[str, Any]:
    if not fights:
        return {"ok": False, "reason": "no fights loaded", "latest_event_date": None, "stale": True}
    latest = max(fight.event_date for fight in fights)
    age = (today_utc() - latest).days
    stale_by_date = age > stale_after_days

    previous = read_json(manifest_path, None) if manifest_path else None
    drift_ratio: float | None = None
    stale_by_drift = False
    if previous and isinstance(previous, dict):
        prior_count = int(previous.get("fight_count") or 0)
        if prior_count > 0:
            drop = prior_count - len(fights)
            drift_ratio = drop / prior_count
            if drift_ratio > drift_tolerance:
                stale_by_drift = True

    stale = stale_by_date or stale_by_drift
    health = {
        "ok": True,
        "latest_event_date": latest.isoformat(),
        "age_days": age,
        "stale": stale,
        "stale_by_date": stale_by_date,
        "stale_by_drift": stale_by_drift,
        "stale_after_days": stale_after_days,
        "drift_tolerance": drift_tolerance,
        "drift_ratio": round(drift_ratio, 4) if drift_ratio is not None else None,
        "current_fight_count": len(fights),
        "previous_fight_count": (previous or {}).get("fight_count") if isinstance(previous, dict) else None,
    }
    return health


def write_source_manifest(path: Path, fights: list[Fight]) -> None:
    if not fights:
        return
    latest = max(fight.event_date for fight in fights)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"fight_count": len(fights), "latest_event_date": latest.isoformat()})


def natural_fight_key(fight: Fight) -> tuple[str, str, tuple[str, str]]:
    fighters = tuple(sorted([identity_key(fight.red_name), identity_key(fight.blue_name)]))
    return (fight.event_date.isoformat(), identity_key(fight.event_name), fighters)


def winner_identity(fight: Fight) -> str:
    if fight.outcome == "red_win":
        return identity_key(fight.red_name)
    if fight.outcome == "blue_win":
        return identity_key(fight.blue_name)
    if fight.outcome in {"draw", "no_contest"}:
        return fight.outcome
    return "unknown"


def is_same_result(left: Fight, right: Fight) -> bool:
    return winner_identity(left) == winner_identity(right)


def merge_new_fights(existing: list[Fight], candidates: list[Fight]) -> tuple[list[Fight], int]:
    existing_ids = {fight.fight_id for fight in existing}
    existing_by_key: dict[tuple[str, str, tuple[str, str]], list[Fight]] = {}
    for fight in existing:
        existing_by_key.setdefault(natural_fight_key(fight), []).append(fight)
    merged: list[Fight] = []
    duplicates = 0
    for fight in candidates:
        key = natural_fight_key(fight)
        if fight.fight_id in existing_ids or any(is_same_result(prior, fight) for prior in existing_by_key.get(key, [])):
            duplicates += 1
            continue
        merged.append(fight)
        existing_ids.add(fight.fight_id)
        existing_by_key.setdefault(key, []).append(fight)
    return merged, duplicates


def detect_source_conflicts(fight_groups: list[tuple[str, list[Fight]]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, tuple[str, str]], list[tuple[str, Fight]]] = {}
    conflicts: list[dict[str, Any]] = []
    for source, fights in fight_groups:
        for fight in fights:
            key = natural_fight_key(fight)
            prior_matches = seen.get(key, [])
            cross_source = [(prior_source, prior_fight) for prior_source, prior_fight in prior_matches if prior_source != source]
            if not cross_source:
                seen.setdefault(key, []).append((source, fight))
                continue
            if not any(is_same_result(prior_fight, fight) for _, prior_fight in cross_source):
                prior_source, prior_fight = cross_source[0]
                conflicts.append({
                    "natural_key": "|".join([key[0], key[1], ",".join(key[2])]),
                    "fight_id": fight.fight_id,
                    "event_date": fight.event_date.isoformat(),
                    "red_name": fight.red_name,
                    "blue_name": fight.blue_name,
                    "source_a": prior_source,
                    "outcome_a": prior_fight.outcome,
                    "winner_a": winner_identity(prior_fight),
                    "method_a": prior_fight.method,
                    "source_b": source,
                    "outcome_b": fight.outcome,
                    "winner_b": winner_identity(fight),
                    "method_b": fight.method,
                })
            seen.setdefault(key, []).append((source, fight))
    return conflicts


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, clean_text(" ".join(self._text))))
            self._href = None
            self._text = []


def fetch_ufc_official_recent_rows(days_back: int = 21, max_events: int = 6, max_pages: int = 2) -> list[dict[str, str]]:
    cutoff = today_utc() - timedelta(days=days_back)
    rows: list[dict[str, str]] = []
    checked = 0
    for url in discover_ufc_event_urls(max_pages=max_pages, max_events=max_events * 3):
        if checked >= max_events:
            break
        event_html = fetch_url(url)
        event_date = parse_ufc_official_event_date(event_html)
        if not event_date or event_date < cutoff:
            continue
        if not is_completed_ufc_event(event_html):
            continue
        rows.extend(parse_ufc_official_event(event_html, url, event_date))
        checked += 1
    return rows


def discover_ufc_event_urls(max_pages: int = 2, max_events: int = 18) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for page in range(max_pages):
        page_url = OFFICIAL_EVENTS_URL if page == 0 else f"{OFFICIAL_EVENTS_URL}&page={page}"
        html = fetch_url(page_url)
        past_section = html.split(">Past<", 1)[1] if ">Past<" in html else html
        for href in OFFICIAL_EVENT_PATH_RE.findall(past_section):
            absolute = urllib.parse.urljoin("https://www.ufc.com", href)
            if absolute in seen:
                continue
            seen.add(absolute)
            urls.append(absolute)
            if len(urls) >= max_events:
                return urls
    return urls


def parse_ufc_official_event_date(html: str) -> date | None:
    match = re.search(r'content="[^"]*On ([A-Za-z]+ \d{1,2}, \d{4})"', html, re.I)
    if not match:
        return None
    return parse_date(clean_text(match.group(1)))


def is_completed_ufc_event(html: str) -> bool:
    if re.search(r"Final Results", html, re.I):
        return True
    return bool(
        re.search(r"c-listing-fight__outcome--(?:win|loss|draw|nc|no-contest)", html, re.I)
        and re.search(r'c-listing-fight__result-text round">\s*\d+', html, re.I)
    )


def parse_ufc_official_event(html: str, event_url: str, event_date: date) -> list[dict[str, str]]:
    event_name = parse_ufc_official_event_name(html)
    event_location = parse_ufc_official_event_location(html)
    blocks = re.findall(
        r'(<div class="c-listing-fight"[^>]*data-fmid="[^"]+"[^>]*>.*?)(?=<div class="c-listing-fight"[^>]*data-fmid=|<script type="application/json"|$)',
        html,
        re.S,
    )
    if not blocks:
        raise ScraperSchemaError(f"No official UFC fight blocks found for {event_url}.")

    rows: list[dict[str, str]] = []
    for index, block in enumerate(blocks):
        red_name = parse_ufc_official_corner_name(block, "red")
        blue_name = parse_ufc_official_corner_name(block, "blue")
        if not red_name or not blue_name:
            continue
        bout_type = parse_ufc_official_bout_type(block)
        if not bout_type:
            raise ScraperSchemaError(f"Official UFC bout type missing for {event_url} fight {index}.")
        outcome, red_result, blue_result = parse_ufc_official_outcome(block)
        round_value = parse_ufc_official_result_text(block, "round")
        time_value = parse_ufc_official_result_text(block, "time")
        method = parse_ufc_official_result_text(block, "method")
        if outcome == "unknown" or not round_value or not time_value or not method:
            raise ScraperSchemaError(f"Official UFC fight result incomplete for {event_url} fight {index}.")
        rows.append(
            {
                "red_fighter_name": red_name,
                "blue_fighter_name": blue_name,
                "event_date": iso_date(event_date),
                "red_fighter_result": red_result,
                "blue_fighter_result": blue_result,
                "fight_outcome": outcome,
                "method": method,
                "round": round_value,
                "time": time_value,
                "bout_type": bout_type,
                "event_name": event_name,
                "event_location": event_location,
            }
        )
    if not rows:
        raise ScraperSchemaError(f"No official UFC results parsed for {event_url}.")
    return rows


def parse_ufc_official_event_name(html: str) -> str:
    match = re.search(r"<title>\s*([^<]+?)\s*\|\s*UFC", html, re.I)
    if not match:
        raise ScraperSchemaError("Official UFC event title missing.")
    return clean_text(html_lib.unescape(match.group(1)))


def parse_ufc_official_event_location(html: str) -> str:
    match = re.search(r'<div class="field--name-venue[^"]*">\s*<div class="field__item">([^<]+)</div>.*?<div class="field--name-location[^"]*">\s*<div class="field__item">([^<]+)</div>', html, re.S)
    if not match:
        return ""
    venue = clean_text(html_text(match.group(1)))
    location = clean_text(html_text(match.group(2)))
    return ", ".join(part for part in [venue, location] if part)


def parse_ufc_official_corner_name(block: str, corner: str) -> str:
    match = re.search(
        rf'c-listing-fight__corner-name--{corner}".*?<a [^>]*>(.*?)</a>',
        block,
        re.S,
    )
    if not match:
        return ""
    return clean_fighter_name(html_text(match.group(1)))


def parse_ufc_official_bout_type(block: str) -> str:
    match = re.search(r'c-listing-fight__class-text">\s*([^<]+?)\s*</div>', block, re.S)
    return clean_text(html_text(match.group(1))) if match else ""


def parse_ufc_official_outcome(block: str) -> tuple[str, str, str]:
    red_outcome = parse_ufc_official_corner_outcome(block, "red")
    blue_outcome = parse_ufc_official_corner_outcome(block, "blue")
    if red_outcome == "win" and blue_outcome == "loss":
        return ("red_win", "W", "L")
    if red_outcome == "loss" and blue_outcome == "win":
        return ("blue_win", "L", "W")
    if red_outcome == "draw" and blue_outcome == "draw":
        return ("draw", "D", "D")
    if red_outcome in {"nc", "no_contest"} and blue_outcome in {"nc", "no_contest"}:
        return ("no_contest", "NC", "NC")
    return ("unknown", "", "")


def parse_ufc_official_corner_outcome(block: str, corner: str) -> str:
    match = re.search(
        rf'c-listing-fight__corner-body--{corner}.*?<div class="c-listing-fight__outcome[^"]*">\s*([^<]*)\s*</div>',
        block,
        re.S,
    )
    if not match:
        return ""
    token = clean_text(html_text(match.group(1))).lower().replace(" ", "_").replace("-", "_")
    if token == "no_contest":
        return "no_contest"
    return token


def parse_ufc_official_result_text(block: str, kind: str) -> str:
    match = re.search(
        rf'c-listing-fight__result-text {kind}"[^>]*>\s*([^<]*)\s*</div>',
        block,
        re.S,
    )
    return clean_text(html_text(match.group(1))) if match else ""


def fetch_ufcstats_recent_rows(days_back: int = 21, max_events: int = 20) -> list[dict[str, str]]:
    """Best-effort fallback scraper for recent UFCStats event pages.

    UFCStats does not publish a stable JSON API. This intentionally keeps the
    scraper small and conservative; manual event files remain the reliable
    fallback when UFCStats markup changes.
    """
    index_html = fetch_url("http://ufcstats.com/statistics/events/completed?page=all")
    parser = LinkParser()
    parser.feed(index_html)
    cutoff = today_utc() - timedelta(days=days_back)
    rows: list[dict[str, str]] = []
    checked = 0
    for href, event_name in parser.links:
        if "/event-details/" not in href:
            continue
        checked += 1
        if checked > max_events:
            break
        event_html = fetch_url(href)
        event_date = parse_ufcstats_event_date(event_html)
        if not event_date or event_date < cutoff:
            continue
        rows.extend(parse_ufcstats_event(event_html, event_name, event_date))
    return rows


def parse_ufcstats_event_date(html: str) -> date | None:
    match = re.search(r"DATE:\s*</i>\s*([^<]+)", html, re.I)
    if not match:
        return None
    return parse_date(clean_text(match.group(1)))


EXPECTED_UFCSTATS_CELLS = 10
KNOWN_UFCSTATS_OUTCOMES = {"win", "draw", "nc", "no contest", "loss", ""}


def parse_ufcstats_event(html: str, event_name: str, event_date: date) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    blocks = re.findall(r"<tr[^>]*b-fight-details__table-row[^>]*>(.*?)</tr>", html, re.S)
    for block_index, block in enumerate(blocks):
        names = re.findall(r"<a[^>]*b-link[^>]*>(.*?)</a>", block, re.S)
        names = [clean_text(re.sub("<[^>]+>", " ", name)) for name in names if clean_text(re.sub("<[^>]+>", " ", name))]
        if len(names) < 2:
            continue
        outcome_match = re.search(r"b-flag__text[^>]*>\s*([^<]+)", block, re.S)
        outcome = clean_text(outcome_match.group(1)).lower() if outcome_match else ""
        if outcome not in KNOWN_UFCSTATS_OUTCOMES:
            raise ScraperSchemaError(
                f"Unknown UFCStats outcome token '{outcome}' for {event_name} row {block_index}. Refusing to ingest to avoid silent corruption."
            )
        cells = [html_text(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]
        if len(cells) < EXPECTED_UFCSTATS_CELLS:
            raise ScraperSchemaError(
                f"UFCStats table row has {len(cells)} cells (expected >= {EXPECTED_UFCSTATS_CELLS}) for {event_name} row {block_index}. HTML schema changed."
            )
        weight = cells[6]
        method = cells[7]
        round_value = cells[8]
        time_value = cells[9]
        if weight and not any(weight_class.lower() in weight.lower() for weight_class in WEIGHT_CLASSES):
            raise ScraperSchemaError(
                f"UFCStats weight token '{weight}' did not match any known division for {event_name} row {block_index}."
            )
        bout_type = f"{weight} Bout" if weight else "Unknown Bout"
        fight_outcome = "unknown"
        red_result = blue_result = ""
        if outcome == "win":
            fight_outcome = "red_win"
            red_result = "W"
            blue_result = "L"
        elif outcome == "loss":
            fight_outcome = "blue_win"
            red_result = "L"
            blue_result = "W"
        elif outcome == "draw":
            fight_outcome = "draw"
            red_result = blue_result = "D"
        elif outcome in {"nc", "no contest"}:
            fight_outcome = "no_contest"
            red_result = blue_result = "NC"
        rows.append(
            {
                "red_fighter_name": names[0],
                "blue_fighter_name": names[1],
                "event_date": iso_date(event_date),
                "red_fighter_result": red_result,
                "blue_fighter_result": blue_result,
                "fight_outcome": fight_outcome,
                "method": method,
                "round": round_value,
                "time": time_value,
                "bout_type": bout_type,
                "event_name": event_name,
                "event_location": "",
            }
        )
    return rows


def html_text(value: str) -> str:
    return clean_text(html_lib.unescape(re.sub(r"<[^>]+>", " ", value)))


def save_ingestion_report(path: Path, report: dict[str, Any]) -> None:
    write_json(path, report)
