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
    parse_event_payload,
    parse_year_page_payload,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historical non-UFC fights from Wikipedia into manual event rows.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "wikipedia_backfill.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "manual_events" / "wikipedia_backfill.csv")
    parser.add_argument("--report", type=Path, default=ROOT / "data" / "processed" / "wikipedia_backfill_report.json")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "raw" / "wikipedia")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on event pages to parse.")
    parser.add_argument("--source", action="append", default=[], help="Limit to specific source name(s), repeatable.")
    parser.add_argument("--append", action="store_true", help="Append and dedupe against an existing output CSV.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached MediaWiki responses.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_paths(ROOT)
    config = read_json(args.config, {})
    sources = config.get("sources", [])
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

    existing_rows: list[dict[str, str]] = []
    if args.append and args.output.exists():
        existing_rows = read_csv(args.output)
        rows = merge_rows(existing_rows, rows)

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


if __name__ == "__main__":
    raise SystemExit(main())
