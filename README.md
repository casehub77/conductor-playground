# UFC Elo Pit

Public static website and data pipeline for unofficial UFC fighter Elo ratings.

Primary source of truth: [komaksym/UFC-DataLab](https://github.com/komaksym/UFC-DataLab).

## Why This Stack

- **Python 3.11 stdlib pipeline**: no database, no paid services, no fragile app server.
- **Static site in `docs/`**: deploys free on GitHub Pages.
- **GitHub Actions refresh**: scheduled updates, manual full rebuilds, dry-runs, and validation gates.
- **CSV/JSON outputs**: easy to inspect, diff, cache, and replace.

This is intentionally low-maintenance. The website is just HTML/CSS/JS plus generated JSON files.

## Upstream Repo Inspection

UFC-DataLab currently exposes these useful datasets:

- `data/stats/stats_processed_all_bouts.csv`: semicolon-delimited all-bouts table, including decisive fights, draws, and no contests.
- `data/stats/stats_raw.csv`: semicolon-delimited raw UFCStats export with nicknames and bout details.
- `data/merged_stats_n_scorecards/merged_stats_n_scorecards.csv`: comma-delimited merged scorecard dataset.
- `data/external_data/raw_fighter_details.csv`: fighter-level details.

This project prefers `stats_processed_all_bouts.csv` because Elo needs all outcomes, not only decisive fights.

## Quick Start

```bash
python3 scripts/update_data.py --mode mvp --allow-fallback
python3 -m http.server 8000 --directory docs
```

Open `http://localhost:8000`.

Run tests:

```bash
python3 -m unittest discover -s tests
```

Dry-run without publishing generated site files:

```bash
python3 scripts/update_data.py --mode mvp --dry-run --allow-fallback
```

Full historical rebuild before launch:

```bash
python3 scripts/update_data.py --mode full --allow-fallback
```

## MVP vs Production History

The MVP defaults to fights from `2020-01-01` onward for development speed. That is useful for validating the pipeline, Elo math, UI, automation, and override workflow.

Production ratings must be rebuilt from full UFC history before launch:

1. Run `python3 scripts/update_data.py --mode full --allow-fallback`.
2. Review `data/processed/validation_report.json`.
3. Review top rankings and champion history.
4. Commit the generated `docs/` and `data/processed/` outputs.

If older fights are added after a 2020-only build, later ratings change. The canonical production dataset must therefore be a full recomputation from earliest UFC history forward.

## Data Refresh

The workflow `.github/workflows/refresh-ratings.yml` runs:

- Weekly refresh.
- Daily check, which helps catch post-event updates after recent UFC cards.
- Manual `workflow_dispatch` with `mvp`, `full`, `dry_run`, and `allow_fallback` controls.

Publishing is blocked if validation fails. Generated changes are committed only after a successful run.

## Fallback Sources

The ingestion order is:

1. UFC-DataLab raw GitHub CSV.
2. UFCStats recent-event fallback if UFC-DataLab appears stale and `--allow-fallback` is set.
3. Manual CSV/JSON files in `data/manual_events/`.

Manual files are the emergency path when upstream data is stale or UFCStats markup changes.
Manual rows must include either a valid `fight_outcome` (`red_win`, `blue_win`, `draw`, `no_contest`) or both `red_fighter_result` and `blue_fighter_result`.

## Overrides

Admin maintenance files live in `overrides/`:

- `fighter_aliases.csv`: maps source spelling/name mismatches to canonical names.
- `instagram_handles.csv`: verified Instagram handles. This is final authority for displayed links.
- `result_overrides.csv`: overturned/corrected results by `fight_id`.
- `excluded_bouts.csv`: hides bad/cancelled records by `fight_id`.
- `champion_overrides.csv`: manual champion labels by system, for example `men:Lightweight`.

After editing overrides, rerun the pipeline.

## Troubleshooting

The fetcher uses normal HTTPS certificate verification and fails closed. If a local macOS Python install cannot verify `raw.githubusercontent.com`, refresh from an existing local snapshot while you fix certificates:

```bash
python3 scripts/update_data.py --mode mvp --source-file data/raw/stats_processed_all_bouts.csv --allow-fallback
```

GitHub Actions uses the hosted runner certificate store and should not need this workaround.

## Deployment

Recommended free deployment:

1. Push this repo to GitHub.
2. Enable GitHub Pages.
3. Set Pages source to `main` branch, `/docs` folder.
4. Enable GitHub Actions.
5. Run the refresh workflow manually once.

Ad placeholders are marked with `.ad-slot` and are easy to replace later in `docs/assets/app.js` or via a small ad script.

## Main Risks

- **Source staleness**: UFC-DataLab says it updates roughly every three months, so recent cards may lag. The daily workflow plus UFCStats/manual fallback reduces that risk.
- **Fighter identity matching**: source spelling differences can split one fighter into multiple Elo profiles. Keep `overrides/fighter_aliases.csv` small, reviewed, and versioned.
- **Champion labeling**: title history can be affected by interim belts, vacancies, stripped titles, and source lag. Use `overrides/champion_overrides.csv` when public labeling matters.
- **Instagram enrichment**: scraping social profiles is brittle. Use scraped/enriched data only as suggestions, and keep `instagram_handles.csv` as display authority.

## Project Structure

```text
config/                  Elo and site settings
data/manual_events/       emergency CSV/JSON imports
data/processed/           generated reports and ratings
data/raw/                 fetched upstream source snapshots
docs/                     GitHub Pages static site
overrides/                admin correction files
scripts/update_data.py    refresh entry point
src/ufc_elo/              ingestion, Elo, validation, site generator
tests/                    smoke tests
```
