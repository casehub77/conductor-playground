from __future__ import annotations

import csv
import urllib.error
from collections import defaultdict
from pathlib import Path
from typing import Any

from .ingestion import fetch_url
from .models import Fight
from .util import identity_key, write_csv


FIGHTER_DETAILS_URL = "https://raw.githubusercontent.com/komaksym/UFC-DataLab/main/data/external_data/raw_fighter_details.csv"


def fetch_fighter_details(raw_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    try:
        text = fetch_url(FIGHTER_DETAILS_URL)
    except (urllib.error.URLError, TimeoutError) as exc:
        return [], {"source": FIGHTER_DETAILS_URL, "rows": 0, "errors": [str(exc)]}
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "raw_fighter_details.csv").write_text(text, encoding="utf-8")
    lines = text.splitlines()
    delimiter = ";" if lines and lines[0].count(";") > lines[0].count(",") else ","
    rows = list(csv.DictReader(lines, delimiter=delimiter))
    return rows, {"source": FIGHTER_DETAILS_URL, "rows": len(rows), "errors": []}


def load_fighter_details_local(path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not path.exists():
        return [], {"source": str(path), "rows": 0, "errors": ["file missing"]}
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    delimiter = ";" if lines and lines[0].count(";") > lines[0].count(",") else ","
    rows = list(csv.DictReader(lines, delimiter=delimiter))
    return rows, {"source": str(path), "rows": len(rows), "errors": []}


def dob_map(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        name = (row.get("fighter_name") or row.get("name") or "").strip()
        dob = (row.get("DOB") or row.get("dob") or "").strip()
        if not name:
            continue
        key = identity_key(name)
        if dob and dob not in mapping[key]:
            mapping[key].append(dob)
        elif not mapping[key]:
            mapping[key] = []
    return dict(mapping)


def detect_same_name_collisions(details_rows: list[dict[str, str]], fight_names: set[str]) -> list[dict[str, Any]]:
    collisions: dict[str, dict[str, Any]] = {}
    for row in details_rows:
        name = (row.get("fighter_name") or row.get("name") or "").strip()
        dob = (row.get("DOB") or row.get("dob") or "").strip()
        if not name:
            continue
        key = identity_key(name)
        entry = collisions.setdefault(key, {"name": name, "dobs": []})
        if dob and dob not in entry["dobs"]:
            entry["dobs"].append(dob)

    results = []
    for key, entry in collisions.items():
        if len(entry["dobs"]) <= 1:
            continue
        if fight_names and key not in {identity_key(n) for n in fight_names}:
            continue
        results.append(
            {
                "name": entry["name"],
                "distinct_dobs": entry["dobs"],
                "resolution": "Add fighter_aliases.csv rows mapping each spelling variant to a distinct canonical display name (for example, append ' (b. 1985)').",
            }
        )
    return sorted(results, key=lambda row: row["name"])


def edit_distance(left: str, right: str, cap: int = 2) -> int:
    if abs(len(left) - len(right)) > cap:
        return cap + 1
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, ch_left in enumerate(left, 1):
        current = [i] + [0] * len(right)
        row_min = current[0]
        for j, ch_right in enumerate(right, 1):
            cost = 0 if ch_left == ch_right else 1
            current[j] = min(
                current[j - 1] + 1,
                previous[j] + 1,
                previous[j - 1] + cost,
            )
            row_min = min(row_min, current[j])
        if row_min > cap:
            return cap + 1
        previous = current
    return previous[-1]


def suggest_aliases(fight_names: set[str], existing_aliases: set[str], max_distance: int = 2, limit: int = 500) -> list[dict[str, str]]:
    canonical_names = sorted({name for name in fight_names if name})
    keys = [identity_key(name) for name in canonical_names]
    suggestions: list[dict[str, str]] = []
    for i, left in enumerate(canonical_names):
        left_key = keys[i]
        if left_key in existing_aliases:
            continue
        for j in range(i + 1, len(canonical_names)):
            right = canonical_names[j]
            right_key = keys[j]
            if right_key in existing_aliases:
                continue
            distance = edit_distance(left_key, right_key, cap=max_distance)
            if 1 <= distance <= max_distance:
                suggestions.append(
                    {
                        "name_a": left,
                        "name_b": right,
                        "distance": str(distance),
                    }
                )
            if len(suggestions) >= limit:
                return suggestions
    return suggestions


def write_suggested_aliases(path: Path, suggestions: list[dict[str, str]]) -> None:
    write_csv(path, suggestions, fieldnames=["name_a", "name_b", "distance"])


def collect_fight_names(fights: list[Fight]) -> set[str]:
    names: set[str] = set()
    for fight in fights:
        names.add(fight.red_name)
        names.add(fight.blue_name)
    return names
