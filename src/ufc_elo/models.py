from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Fight:
    fight_id: str
    event_date: date
    event_name: str
    event_location: str
    red_name: str
    blue_name: str
    red_nickname: str
    blue_nickname: str
    outcome: str
    method: str
    round: str
    time: str
    bout_type: str
    gender: str
    weight_class: str
    is_title: bool
    source: str
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class RatingState:
    rating: float
    peak: float
    last_fight_date: date | None = None
    fights: int = 0

