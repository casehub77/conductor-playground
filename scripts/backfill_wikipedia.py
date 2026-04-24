#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ufc_elo.settings import repo_paths
from ufc_elo.util import read_csv, read_json, write_csv, write_json
from ufc_elo.wikipedia import (
    WIKIPEDIA_MANUAL_FIELDS,
    discover_event_titles,
    discover_titles_from_allpages_prefix,
    discover_titles_from_search,
    fetch_event_payload,
    fetch_page_payload,
    parse_event_payload,
    parse_fighter_page_payload,
    parse_year_page_payload,
    resolve_fighter_page_title,
)
from ufc_elo.ingestion import fetch_primary_rows, load_primary_local, rows_to_fights
from ufc_elo.overrides import load_overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historical non-UFC fights from Wikipedia into manual event rows.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "wikipedia_backfill.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "manual_events" / "wikipedia_backfill.csv")
    parser.add_argument("--report", type=Path, default=ROOT / "data" / "processed" / "wikipedia_backfill_report.json")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "raw" / "wikipedia")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on event pages to parse.")
    parser.add_argument("--source", action="append", default=[], help="Limit to specific source name(s), repeatable.")
    parser.add_argument("--no-event-sources", action="store_true", help="Skip promotion/event discovery and only run fighter-page backfill.")
    parser.add_argument("--append", action="store_true", help="Append and dedupe against an existing output CSV.")
    parser.add_argument("--fighter-pages", action="store_true", help="Also backfill from fighter Wikipedia pages for fighters already in the UFC source dataset.")
    parser.add_argument("--fighter-limit", type=int, default=0, help="Optional cap on fighter pages to parse.")
    parser.add_argument("--fighter-name", action="append", default=[], help="Target specific fighter page(s), repeatable.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached MediaWiki responses.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_paths(ROOT)
    config = read_json(args.config, {})
    sources = [] if args.no_event_sources else config.get("sources", [])
    paths = repo_paths(ROOT)
    overrides = load_overrides(paths.overrides)
    if args.source:
        selected = set(args.source)
        sources = [source for source in sources if source.get("name") in selected]
    rows: list[dict[str, str]] = []
    report_sources: list[dict[str, object]] = []
    total_events = 0

    for source in sources:
        discovery_mode = source.get("discovery", "page_links")
        if discovery_mode == "search":
            titles = discover_titles_from_search(
                source["query"],
                source.get("title_patterns", []),
                source.get("exclude_patterns", []),
                cache_dir=args.cache_dir / "lists",
                refresh=args.refresh,
                limit=int(source.get("search_limit", 50)),
            )
        elif discovery_mode == "allpages_prefix":
            titles = discover_titles_from_allpages_prefix(
                source["prefix"],
                source.get("title_patterns", []),
                source.get("exclude_patterns", []),
                cache_dir=args.cache_dir / "lists",
                refresh=args.refresh,
                limit=int(source.get("prefix_limit", 500)),
            )
        else:
            titles = discover_event_titles(
                source["list_page"],
                source.get("title_patterns", []),
                source.get("exclude_patterns", []),
                cache_dir=args.cache_dir / "lists",
                refresh=args.refresh,
            )
        if args.limit:
            remaining = args.limit - total_events
            if remaining <= 0:
                break
            titles = titles[:remaining]

        source_report = {
            "name": source["name"],
            "discovery": discovery_mode,
            "source_ref": source.get("list_page") or source.get("query") or source.get("prefix", ""),
            "discovered_titles": len(titles),
            "parsed_titles": 0,
            "rows": 0,
            "errors": [],
        }
        for title in titles:
            try:
                payload = fetch_event_payload(title, cache_dir=args.cache_dir / "pages", refresh=args.refresh)
                if source.get("parse_mode") == "year_page":
                    event_rows = parse_year_page_payload(payload, title)
                else:
                    event_rows = parse_event_payload(payload, title)
            except Exception as exc:
                source_report["errors"].append(f"{title}: {exc}")
                continue
            rows.extend(event_rows)
            total_events += 1
            source_report["parsed_titles"] += 1
            source_report["rows"] += len(event_rows)
        report_sources.append(source_report)

    if args.fighter_pages:
        fighter_names = args.fighter_name or load_ufc_fighter_names(paths, overrides)
        if args.fighter_limit:
            fighter_names = fighter_names[:args.fighter_limit]
        fighter_report: dict[str, object] = {
            "name": "fighter_pages",
            "discovery": "fighter_pages",
            "source_ref": "ufc-primary-fighter-list",
            "discovered_titles": 0,
            "parsed_titles": 0,
            "rows": 0,
            "errors": [],
        }
        for fighter_name in fighter_names:
            try:
                title = resolve_fighter_page_title(
                    fighter_name,
                    cache_dir=args.cache_dir / "fighter-search",
                    refresh=args.refresh,
                )
                if not title:
                    continue
                fighter_report["discovered_titles"] = int(fighter_report["discovered_titles"]) + 1
                payload = fetch_page_payload(title, cache_dir=args.cache_dir / "fighter-pages", refresh=args.refresh)
                fighter_rows = parse_fighter_page_payload(payload, title, fighter_name)
            except Exception as exc:
                fighter_report["errors"].append(f"{fighter_name}: {exc}")
                continue
            rows.extend(fighter_rows)
            fighter_report["parsed_titles"] = int(fighter_report["parsed_titles"]) + 1
            fighter_report["rows"] = int(fighter_report["rows"]) + len(fighter_rows)
        report_sources.append(fighter_report)

    existing_rows: list[dict[str, str]] = []
    if args.append and args.output.exists():
        existing_rows = read_csv(args.output)
        rows = merge_rows(existing_rows, rows)
    else:
        rows = merge_rows([], rows)

    write_csv(args.output, rows, WIKIPEDIA_MANUAL_FIELDS)
    write_json(
        args.report,
        {
            "sources": report_sources,
            "rows": len(rows),
            "events": total_events,
            "output": str(args.output),
            "append": args.append,
            "existing_rows": len(existing_rows),
        },
    )
    print(f"Wrote {len(rows)} rows from {total_events} event pages to {args.output}")
    return 0


def merge_rows(existing_rows: list[dict[str, str]], new_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged = list(existing_rows)
    seen = {row_key(row) for row in existing_rows}
    for row in new_rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def row_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple((row.get(field) or "").strip() for field in WIKIPEDIA_MANUAL_FIELDS)


def load_ufc_fighter_names(paths, overrides) -> list[str]:
    raw_candidates = [paths.raw / "stats_processed_all_bouts.csv", paths.raw / "stats_raw.csv"]
    source_path = next((path for path in raw_candidates if path.exists()), None)
    if source_path is not None:
        primary_rows, _ = load_primary_local(source_path)
    else:
        primary_rows, _ = fetch_primary_rows(paths.raw)
    fights = rows_to_fights(primary_rows, "ufc-primary", overrides)
    names = sorted({fight.red_name for fight in fights} | {fight.blue_name for fight in fights})
    return names


if __name__ == "__main__":
    raise SystemExit(main())
