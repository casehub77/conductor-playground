# Elo Assumptions

Defaults live in `config/elo.json`.

## Rating Systems

- Initial rating: `1500`
- Overall Elo: separate `men:overall` and `women:overall`
- Divisional Elo: separate by gender and UFC weight class
- MVP date filter: `2020-01-01`

## Fight Outcomes

- Win: winner scores `1.0`, loser scores `0.0`
- Draw: both fighters score `0.5`
- No contest/unknown: rating does not move
- Overturned bouts: handled through `overrides/result_overrides.csv`
- Excluded/cancelled/bad records: handled through `overrides/excluded_bouts.csv`

## K Factors

- Overall K-factor: `32`
- Divisional K-factor: `36`
- Maximum single-fight delta: `60`

Divisional Elo moves slightly more because divisional rankings are the main user-facing rating.

## Multipliers

- UFC title fight multiplier: `1.1`
- Finish multiplier: `1.08`
- Decision multiplier: `1.0`

These are intentionally conservative. The project should not overfit method details before historical validation.

## Inactivity Decay

Current display ratings decay after `545` inactive days by `25` points per inactive year, with a floor at `1500` for above-average ratings. Fight history keeps actual post-fight values.

## Full History Requirement

Elo is path dependent. A 2020-only build initializes every 2020 fighter at `1500`, which is false for veterans. Production launch must run a full rebuild from earliest available UFC history.

