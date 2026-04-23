from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .util import identity_key, read_csv


@dataclass
class OverrideData:
    aliases: dict[str, str]
    instagram: dict[str, str]
    result_overrides: dict[str, dict[str, str]]
    excluded_bouts: set[str]
    champion_overrides: dict[str, str]


def load_overrides(path: Path) -> OverrideData:
    aliases: dict[str, str] = {}
    for row in read_csv(path / "fighter_aliases.csv"):
        alias = row.get("alias", "")
        canonical = row.get("canonical_name", "")
        if alias and canonical:
            aliases[identity_key(alias)] = canonical
            aliases[identity_key(canonical)] = canonical

    instagram: dict[str, str] = {}
    for row in read_csv(path / "instagram_handles.csv"):
        name = row.get("fighter_name", "")
        handle = (row.get("instagram_handle", "") or "").strip().lstrip("@")
        if name and handle:
            instagram[identity_key(name)] = handle

    result_overrides: dict[str, dict[str, str]] = {}
    for row in read_csv(path / "result_overrides.csv"):
        fight_id = row.get("fight_id", "")
        if fight_id:
            result_overrides[fight_id] = row

    excluded_bouts = {
        row.get("fight_id", "")
        for row in read_csv(path / "excluded_bouts.csv")
        if row.get("fight_id")
    }

    champion_overrides: dict[str, str] = {}
    for row in read_csv(path / "champion_overrides.csv"):
        system = row.get("system", "")
        fighter_name = row.get("fighter_name", "")
        status = (row.get("status", "active") or "active").lower()
        if system and fighter_name and status == "active":
            champion_overrides[system] = fighter_name

    return OverrideData(
        aliases=aliases,
        instagram=instagram,
        result_overrides=result_overrides,
        excluded_bouts=excluded_bouts,
        champion_overrides=champion_overrides,
    )


def canonical_name(name: str, overrides: OverrideData) -> str:
    return overrides.aliases.get(identity_key(name), name)

