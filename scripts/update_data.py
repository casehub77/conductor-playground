#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ufc_elo.elo import compute_ratings
from ufc_elo.identity import (
    collect_fight_names,
    detect_same_name_collisions,
    fetch_fighter_details,
    load_fighter_details_local,
    suggest_aliases,
    write_suggested_aliases,
)
from ufc_elo.ingestion import (
    ManualRowError,
    ScraperSchemaError,
    detect_source_conflicts,
    fetch_primary_rows,
    fetch_ufc_official_recent_rows,
    fetch_ufcstats_recent_rows,
    filter_fights,
    load_manual_rows,
    load_primary_local,
    merge_new_fights,
    rows_to_fights,
    save_ingestion_report,
    source_health,
    write_source_manifest,
)
from ufc_elo.overrides import load_overrides
from ufc_elo.settings import load_settings, repo_paths
from ufc_elo.site import build_site_payload, clean_generated_site
from ufc_elo.util import identity_key, write_json
from ufc_elo.validation import validate_fights


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh UFC Elo ratings and static site assets.")
    parser.add_argument("--mode", choices=["mvp", "full"], default="mvp", help="mvp uses configured since date; full rebuild uses all loaded history.")
    parser.add_argument("--since", default=None, help="Override the MVP since date, for example 2020-01-01.")
    parser.add_argument("--source-file", type=Path, help="Use a local UFC-DataLab-compatible CSV instead of fetching primary data.")
    parser.add_argument("--allow-fallback", action="store_true", help="Try UFCStats fallback if primary data appears stale.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and compute without publishing docs/ output.")
    parser.add_argument("--no-manual", action="store_true", help="Skip data/manual_events CSV/JSON overlays.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = repo_paths(ROOT)
    settings = load_settings(paths)
    elo_config: dict[str, Any] = settings["elo"]
    site_config: dict[str, Any] = settings["site"]
    overrides = load_overrides(paths.overrides)

    if args.source_file:
        primary_rows, primary_report = load_primary_local(args.source_file)
    else:
        primary_rows, primary_report = fetch_primary_rows(paths.raw)

    primary_fights = rows_to_fights(primary_rows, primary_report["source"], overrides)
    stale_after_days = int(elo_config.get("source_stale_after_days", 21))
    drift_tolerance = float(elo_config.get("row_count_drift_tolerance", 0.25))
    manifest_path = paths.raw / "primary_manifest.json"
    health = source_health(primary_fights, stale_after_days, manifest_path, drift_tolerance)
    all_fights = list(primary_fights)
    official_report: dict[str, Any] = {"used": False, "rows": 0, "errors": []}
    fallback_report: dict[str, Any] = {"used": False, "rows": 0, "errors": []}
    official_fights_for_conflicts: list = []
    fallback_fights: list = []
    fallback_fights_for_conflicts: list = []

    if health.get("stale") and args.allow_fallback:
        try:
            official_rows = fetch_ufc_official_recent_rows(days_back=max(stale_after_days + 7, 30))
            official_fights = rows_to_fights(official_rows, "ufc:official", overrides)
            safe_official_fights = [
                fight
                for fight in official_fights
                if fight.outcome in {"red_win", "blue_win", "draw", "no_contest"} and fight.weight_class != "Unknown"
            ]
            official_fights_for_conflicts = safe_official_fights
            new_fights, official_duplicates = merge_new_fights(all_fights, safe_official_fights)
            all_fights.extend(new_fights)
            official_report = {
                "used": True,
                "rows": len(official_rows),
                "parsed_fights": len(official_fights),
                "discarded_unparseable": len(official_fights) - len(safe_official_fights),
                "duplicates": official_duplicates,
                "new_fights": len(new_fights),
                "errors": [],
            }
        except ScraperSchemaError as exc:
            official_report["errors"] = [str(exc)]
        try:
            fallback_rows = fetch_ufcstats_recent_rows(days_back=max(stale_after_days + 7, 30))
            fallback_fights = rows_to_fights(fallback_rows, "ufcstats:fallback", overrides)
            safe_fallback_fights = [
                fight
                for fight in fallback_fights
                if fight.outcome in {"red_win", "blue_win", "draw", "no_contest"} and fight.weight_class != "Unknown"
            ]
            fallback_fights_for_conflicts = safe_fallback_fights
            new_fights, fallback_duplicates = merge_new_fights(all_fights, safe_fallback_fights)
            all_fights.extend(new_fights)
            fallback_report = {
                "used": True,
                "rows": len(fallback_rows),
                "parsed_fights": len(fallback_fights),
                "discarded_unparseable": len(fallback_fights) - len(safe_fallback_fights),
                "duplicates": fallback_duplicates,
                "new_fights": len(new_fights),
                "errors": [],
            }
        except ScraperSchemaError as exc:
            print(f"Scraper schema error: {exc}", file=sys.stderr)
            return 3

    if args.no_manual:
        manual_rows = []
    else:
        try:
            manual_rows = load_manual_rows(paths.manual_events)
        except ManualRowError as exc:
            print(f"Manual event file error: {exc}", file=sys.stderr)
            return 4
    manual_fights = rows_to_fights(manual_rows, "manual", overrides)
    new_manual_fights, manual_duplicates = merge_new_fights(all_fights, manual_fights)
    all_fights.extend(new_manual_fights)

    conflicts = detect_source_conflicts([
        (primary_report["source"], primary_fights),
        ("ufc:official", official_fights_for_conflicts),
        ("ufcstats:fallback", fallback_fights_for_conflicts),
        ("manual", manual_fights),
    ])
    if conflicts:
        write_json(paths.processed / "source_conflicts.json", {"conflicts": conflicts})
        print(f"Source conflicts detected ({len(conflicts)}). See data/processed/source_conflicts.json.", file=sys.stderr)
        return 5

    since = None if args.mode == "full" else args.since or elo_config.get("mvp_since_date", "2020-01-01")
    fights = filter_fights(all_fights, since)
    min_fights = int(elo_config.get("validation", {}).get("min_fights_full" if args.mode == "full" else "min_fights_mvp", 1))
    validation = validate_fights(fights, min_fights=min_fights)
    report_prefix = "dry_run_" if args.dry_run else ""

    fighter_details_local = paths.raw / "raw_fighter_details.csv"
    if fighter_details_local.exists():
        details_rows, details_report = load_fighter_details_local(fighter_details_local)
    else:
        details_rows, details_report = fetch_fighter_details(paths.raw)
    fight_names = collect_fight_names(fights)
    collisions = detect_same_name_collisions(details_rows, fight_names)
    existing_alias_keys = {identity_key(key) for key in overrides.aliases.keys()}
    suggestions = suggest_aliases(fight_names, existing_alias_keys)
    write_suggested_aliases(paths.processed / f"{report_prefix}suggested_aliases.csv", suggestions)
    validation["same_name_collisions"] = collisions
    validation["suggested_alias_count"] = len(suggestions)
    if collisions:
        validation["warnings"] = validation.get("warnings", []) + [
            f"{len(collisions)} fighter name(s) share a display name but have distinct DOBs in UFC-DataLab: resolve via fighter_aliases.csv."
        ]

    ingestion_report = {
        "mode": args.mode,
        "since": since,
        "dry_run": args.dry_run,
        "primary": primary_report,
        "primary_health": health,
        "official_fallback": official_report,
        "fallback": fallback_report,
        "manual": {
            "rows": len(manual_rows),
            "fights": len(manual_fights),
            "duplicates": manual_duplicates,
            "new_fights": len(new_manual_fights),
        },
        "fighter_details": details_report,
        "validation": validation,
    }

    paths.processed.mkdir(parents=True, exist_ok=True)
    save_ingestion_report(paths.processed / f"{report_prefix}ingestion_report.json", ingestion_report)
    write_json(paths.processed / f"{report_prefix}validation_report.json", validation)

    if not validation["ok"]:
        print(json.dumps(ingestion_report, indent=2))
        return 2

    output = compute_ratings(fights, elo_config, overrides)
    output["run"] = {
        "mode": args.mode,
        "since": since,
        "primary_source": primary_report["source"],
        "official_fallback_used": official_report["used"],
        "fallback_used": fallback_report["used"],
        "manual_fights": len(manual_fights),
    }
    write_json(paths.processed / f"{report_prefix}ratings.json", output)

    if not args.dry_run:
        clean_generated_site(paths.docs)
        build_site_payload(output, paths.docs, site_config)
        write_source_manifest(manifest_path, primary_fights)

    print(json.dumps({**ingestion_report, "published": not args.dry_run}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
