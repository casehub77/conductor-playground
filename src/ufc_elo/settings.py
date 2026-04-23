from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import read_json


@dataclass(frozen=True)
class Paths:
    root: Path
    config: Path
    overrides: Path
    manual_events: Path
    processed: Path
    docs: Path
    raw: Path


def repo_paths(root: Path) -> Paths:
    return Paths(
        root=root,
        config=root / "config",
        overrides=root / "overrides",
        manual_events=root / "data" / "manual_events",
        processed=root / "data" / "processed",
        docs=root / "docs",
        raw=root / "data" / "raw",
    )


def load_settings(paths: Paths) -> dict[str, Any]:
    settings = read_json(paths.config / "elo.json", {})
    site = read_json(paths.config / "site.json", {})
    return {"elo": settings, "site": site}

