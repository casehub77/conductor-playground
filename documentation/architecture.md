# Architecture

## Simple Public Hosting

The site is static and lives in `docs/`, so GitHub Pages can host it free. The generated frontend reads JSON assets from `docs/assets/` and needs no API server.

## Pipeline

`scripts/update_data.py` performs one refresh:

1. Fetch UFC-DataLab CSV from raw GitHub URLs or read a local `--source-file`.
2. Normalize fight rows into a full-history-capable internal model.
3. Apply aliases, result overrides, exclusions, and manual event files.
4. Check source freshness.
5. Optionally attempt recent UFCStats fallback when primary data is stale.
6. Validate fight count, duplicate IDs, outcomes, and weight-class parsing.
7. Compute overall and divisional Elo systems.
8. Write reports and generated static JSON/HTML.

## Data Model

Each fight has:

- deterministic `fight_id`
- event date/name/location
- red/blue fighter names
- outcome
- method
- bout type
- gender
- weight class
- title-bout flag
- source

Elo systems are keyed as:

- `men:overall`
- `women:overall`
- `men:Lightweight`
- `women:Strawweight`
- and equivalent UFC divisions

## Maintenance Strategy

The project avoids hosted databases, server runtimes, background workers, and paid APIs. Everything important is versioned as files, so failures are visible in GitHub Actions logs and data diffs.

Bad data should be fixed by editing override CSVs, not by patching generated JSON.

