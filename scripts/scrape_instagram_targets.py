#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ufc_elo.util import identity_key, read_csv, write_csv, write_json


PROFILE_BLOCKLIST = {
    "about",
    "accounts",
    "api",
    "developer",
    "explore",
    "legal",
    "oauth",
    "p",
    "reel",
    "reels",
    "stories",
    "tv",
}
FAN_TERMS = (
    "fan page",
    "fanpage",
    "not impersonating",
    "parody",
    "news",
    "updates",
    "daily",
    "team ",
    "supporters",
)


@dataclass
class Candidate:
    handle: str
    url: str
    context: str
    order: int
    score: float = 0.0
    profile: dict[str, Any] | None = None
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover Instagram handles for current top-ranked fighters and champions.")
    parser.add_argument("--docs-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--overrides", type=Path, default=ROOT / "overrides" / "instagram_handles.csv")
    parser.add_argument("--report", type=Path, default=ROOT / "data" / "processed" / "instagram_discovery_report.json")
    parser.add_argument("--limit", type=int, default=0, help="Only process this many missing fighters; 0 means all.")
    parser.add_argument("--sleep", type=float, default=0.45, help="Delay between network requests.")
    parser.add_argument("--apply", action="store_true", help="Write discovered handles into overrides/instagram_handles.csv.")
    parser.add_argument("--refresh-existing", action="store_true", help="Refresh target handles even when an override already exists.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = load_targets(args.docs_dir)
    existing = load_existing(args.overrides)
    missing = targets if args.refresh_existing else [target for target in targets if identity_key(target["fighter_name"]) not in existing]
    if args.limit:
        missing = missing[: args.limit]

    discoveries: list[dict[str, Any]] = []
    rows_to_add: list[dict[str, str]] = []

    for index, target in enumerate(missing, 1):
        name = target["fighter_name"]
        print(f"[{index}/{len(missing)}] {name}", file=sys.stderr)
        try:
            candidates = discover_candidates(name, sleep=args.sleep)
        except Exception as exc:  # noqa: BLE001 - one provider failure should not stop the batch.
            discoveries.append(
                {
                    "fighter_name": name,
                    "reasons": target["reasons"],
                    "selected_handle": "",
                    "selected_url": "",
                    "score": 0,
                    "verified": False,
                    "followers": None,
                    "full_name": "",
                    "error": str(exc),
                    "candidates": [],
                }
            )
            continue
        selected = select_candidate(name, candidates)
        row = {
            "fighter_name": name,
            "reasons": target["reasons"],
            "selected_handle": selected.handle if selected else "",
            "selected_url": selected.url if selected else "",
            "score": round(selected.score, 1) if selected else 0,
            "verified": bool((selected.profile or {}).get("is_verified")) if selected else False,
            "followers": (selected.profile or {}).get("edge_followed_by", {}).get("count") if selected else None,
            "full_name": (selected.profile or {}).get("full_name") if selected else "",
            "candidates": [
                {
                    "handle": candidate.handle,
                    "url": candidate.url,
                    "score": round(candidate.score, 1),
                    "full_name": (candidate.profile or {}).get("full_name", ""),
                    "verified": bool((candidate.profile or {}).get("is_verified")) if candidate.profile else False,
                    "followers": (candidate.profile or {}).get("edge_followed_by", {}).get("count") if candidate.profile else None,
                    "error": candidate.error,
                }
                for candidate in candidates[:5]
            ],
        }
        discoveries.append(row)
        if selected:
            rows_to_add.append(
                {
                    "fighter_name": name,
                    "instagram_handle": selected.handle,
                    "verified_by": "public-search",
                    "notes": f"auto target: {target['reasons']}; score {selected.score:.1f}",
                }
            )
        time.sleep(args.sleep)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        args.report,
        {
            "target_count": len(targets),
            "existing_count": len(existing),
            "processed_missing": len(missing),
            "discovered_count": len(rows_to_add),
            "applied": bool(args.apply),
            "discoveries": discoveries,
        },
    )

    if args.apply and rows_to_add:
        apply_rows(args.overrides, rows_to_add)

    print(json.dumps({"targets": len(targets), "missing_processed": len(missing), "discovered": len(rows_to_add), "applied": args.apply}, indent=2))
    return 0


def load_targets(docs_dir: Path) -> list[dict[str, str]]:
    rankings = json.loads((docs_dir / "assets" / "rankings.json").read_text(encoding="utf-8"))
    home = json.loads((docs_dir / "assets" / "home.json").read_text(encoding="utf-8"))
    reasons: dict[str, set[str]] = {}
    display_names: dict[str, str] = {}

    for system, rows in rankings.get("rankings", {}).items():
        if system.endswith(":overall"):
            continue
        gender, _, division = system.partition(":")
        for row in rows[:10]:
            name = row["name"]
            key = identity_key(name)
            display_names[key] = name
            reasons.setdefault(key, set()).add(f"top10 {gender} {division} #{row.get('rank')}")

    for champion in home.get("champions", []):
        name = champion.get("fighter_name")
        if not name:
            continue
        key = identity_key(name)
        display_names[key] = name
        reasons.setdefault(key, set()).add(f"champion {champion.get('gender')} {champion.get('weight_class')}")

    return [
        {"fighter_name": display_names[key], "reasons": "; ".join(sorted(values))}
        for key, values in sorted(reasons.items(), key=lambda item: display_names[item[0]])
    ]


def load_existing(path: Path) -> dict[str, str]:
    return {
        identity_key(row.get("fighter_name", "")): (row.get("instagram_handle", "") or "").strip().lstrip("@")
        for row in read_csv(path)
        if row.get("fighter_name") and row.get("instagram_handle")
    }


def discover_candidates(name: str, sleep: float) -> list[Candidate]:
    query = f'{name} official Instagram site:instagram.com'
    text = fetch_text("https://search.yahoo.com/search?" + urllib.parse.urlencode({"q": query}))
    candidates = extract_instagram_candidates(text)
    if not candidates:
        try:
            text = fetch_text("https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}))
        except Exception:  # noqa: BLE001 - one provider failure should not stop discovery.
            text = ""
        candidates = extract_instagram_candidates(text)
    if "challenge-form" in text:
        candidates = []
    if not candidates:
        return []

    # Profile metadata is useful when Instagram allows it, but search ordering is
    # the fallback because the web endpoint rate-limits batches aggressively.
    for candidate in candidates[:2]:
        candidate.profile, candidate.error = fetch_profile(candidate.handle)
        time.sleep(sleep)
    for candidate in candidates:
        candidate.score = score_candidate(name, candidate)
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.order, candidate.handle))
    return candidates


def extract_instagram_candidates(text: str) -> list[Candidate]:
    decoded = html.unescape(text)
    matches = re.finditer(
        r"uddg=([^\"&]+)|RU=(https?%3a%2f%2f[^\"&]+)|https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)/?",
        decoded,
        re.I,
    )
    seen: set[str] = set()
    candidates: list[Candidate] = []
    for match in matches:
        url = ""
        if match.group(1):
            url = urllib.parse.unquote(match.group(1))
        elif match.group(2):
            url = urllib.parse.unquote(match.group(2))
        elif match.group(3):
            url = match.group(0)
        url = re.split(r"/R[KOU]=|;_|&", url, maxsplit=1)[0]
        parsed = urllib.parse.urlparse(url)
        if "instagram.com" not in parsed.netloc:
            continue
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            continue
        if len(parts) > 1 and parts[1].lower() not in {"reels"}:
            continue
        handle = parts[0].strip().lstrip("@")
        if (
            not handle
            or not re.match(r"^[A-Za-z0-9_.]{1,30}$", handle)
            or handle.lower() in PROFILE_BLOCKLIST
            or handle.lower() in seen
        ):
            continue
        seen.add(handle.lower())
        start = max(0, match.start() - 500)
        end = min(len(decoded), match.end() + 700)
        context = re.sub(r"<[^>]+>", " ", decoded[start:end])
        context = re.sub(r"\s+", " ", html.unescape(context)).strip()
        candidates.append(Candidate(handle=handle, url=f"https://www.instagram.com/{handle}/", context=context, order=len(candidates)))
    return candidates[:8]


def fetch_profile(handle: str) -> tuple[dict[str, Any] | None, str]:
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={urllib.parse.quote(handle)}"
    try:
        text = fetch_text(
            url,
            headers={
                "Accept": "application/json",
                "x-ig-app-id": "936619743392459",
            },
        )
        payload = json.loads(text)
        return payload.get("data", {}).get("user") or {}, ""
    except Exception as exc:  # noqa: BLE001 - discovery should keep going.
        return None, str(exc)


def score_candidate(name: str, candidate: Candidate) -> float:
    tokens = [token for token in re.findall(r"[a-z0-9]+", name.lower()) if len(token) >= 3]
    profile = candidate.profile or {}
    profile_text = " ".join(
        [
            candidate.handle,
            candidate.context,
            str(profile.get("full_name") or ""),
            str(profile.get("biography") or ""),
        ]
    ).lower()
    matched = sum(1 for token in tokens if token in profile_text)
    score = matched * 45 - candidate.order * 22
    if tokens and matched == len(tokens):
        score += 60
    if profile.get("is_verified"):
        score += 80
    followers = int((profile.get("edge_followed_by") or {}).get("count") or 0)
    if followers:
        score += min(70, math.log10(max(10, followers)) * 10)
    if candidate.profile and candidate.handle.lower().replace("_", "").replace(".", "") in "".join(tokens):
        score += 20
    if any(term in profile_text for term in FAN_TERMS):
        score -= 110
    if not candidate.profile:
        score -= 30
    return score


def select_candidate(name: str, candidates: list[Candidate]) -> Candidate | None:
    if not candidates:
        return None
    best = candidates[0]
    token_count = len([token for token in re.findall(r"[a-z0-9]+", name.lower()) if len(token) >= 3])
    minimum = 115 if token_count > 1 else 90
    return best if best.score >= minimum else None


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/605.1.15 Safari/605.1.15",
        **(headers or {}),
    }
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=20, context=ssl._create_unverified_context()) as response:
        return response.read().decode("utf-8", "replace")


def apply_rows(path: Path, rows_to_add: list[dict[str, str]]) -> None:
    existing_rows = read_csv(path)
    by_key = {identity_key(row.get("fighter_name", "")): row for row in existing_rows if row.get("fighter_name")}
    for row in rows_to_add:
        key = identity_key(row["fighter_name"])
        if (by_key.get(key, {}).get("verified_by") or "").lower() == "manual":
            continue
        by_key[key] = row
    rows = sorted(by_key.values(), key=lambda row: row.get("fighter_name", ""))
    write_csv(path, rows, fieldnames=["fighter_name", "instagram_handle", "verified_by", "notes"])


if __name__ == "__main__":
    raise SystemExit(main())
