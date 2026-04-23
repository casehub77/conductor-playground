from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from .models import Fight


def compute_input_hash(fights: list[Fight]) -> str:
    parts = sorted(f"{fight.fight_id}|{fight.outcome}" for fight in fights)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def validate_fights(fights: list[Fight], min_fights: int = 1) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if len(fights) < min_fights:
        errors.append(f"Expected at least {min_fights} fights, loaded {len(fights)}.")

    ids = Counter(fight.fight_id for fight in fights)
    duplicate_ids = [fight_id for fight_id, count in ids.items() if count > 1]
    if duplicate_ids:
        errors.append(f"Duplicate fight ids: {', '.join(duplicate_ids[:10])}")

    unknown_outcomes = sorted({fight.outcome for fight in fights if fight.outcome not in {"red_win", "blue_win", "draw", "no_contest"}})
    if unknown_outcomes:
        warnings.append(f"Unknown outcomes will not move ratings: {', '.join(unknown_outcomes)}")

    unknown_weights = sum(1 for fight in fights if fight.weight_class == "Unknown")
    if unknown_weights:
        warnings.append(f"{unknown_weights} fights have unknown weight class.")

    no_event = sum(1 for fight in fights if not fight.event_name)
    if no_event:
        warnings.append(f"{no_event} fights are missing event names.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "fight_count": len(fights),
        "fighter_count": len({fight.red_name for fight in fights} | {fight.blue_name for fight in fights}),
        "input_hash": compute_input_hash(fights),
    }

