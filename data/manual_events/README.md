# Manual Event Import

Drop emergency result files here when UFC-DataLab and UFCStats are behind.

For historical non-UFC backfills, use:

```bash
python3 scripts/backfill_wikipedia.py
```

That script writes `data/manual_events/wikipedia_backfill.csv`, which `scripts/update_data.py` will ingest automatically.

To backfill in smaller batches and reuse the local cache:

```bash
python3 scripts/backfill_wikipedia.py --source bellator --source dream --source one
python3 scripts/backfill_wikipedia.py --source cage_warriors --source ksw --source rizin_years
```

Supported formats:

- `.csv` with UFC-DataLab-like columns
- `.json` as either a list of fight objects or an object with a `fights` array

Minimum useful fields:

```csv
red_fighter_name,blue_fighter_name,event_date,red_fighter_result,blue_fighter_result,fight_outcome,method,bout_type,event_name,event_location
Example Red,Example Blue,2026-01-01,W,L,red_win,Decision - Unanimous,Lightweight Bout,UFC Example,Las Vegas, Nevada, USA
```

Use ISO dates (`YYYY-MM-DD`) or UFC-DataLab dates (`DD/MM/YYYY`).

Rows without a result are rejected. Include either:

- `fight_outcome` as `red_win`, `blue_win`, `draw`, or `no_contest`
- or both `red_fighter_result` and `blue_fighter_result`
