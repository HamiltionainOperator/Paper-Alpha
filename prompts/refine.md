# Task
These alphas were simulated on BRAIN. They are close to the submission criteria but fail some checks. Propose {{k}} improved variants for EACH alpha.

## Submission criteria
{{criteria}}

## What these alphas are for
{{route}}

## Simulation scope
{{scope}}

## Hard constraints (variants that break these are discarded)
{{constraints}}

## Settings you choose per variant
{{settings_choices}}

## Alphas to improve
{{alphas}}

## How to fix typical failures
Each alpha comes with the engine's verdict and the kinds of change allowed. Settings-only variants of the same expression are NOT allowed here: they trade the same positions, so they are correlated copies, not new alphas. Every variant must change the expression itself.
- Sharpe too low: sharpen the signal (better normalisation, smoothing a noisy forecast over its own horizon, conditioning on when the effect is strongest, or combining with a complementary field from the SAME dataset/category), or invert it if the economic logic supports the opposite sign.
- HIGH_TURNOVER: smooth over time (ts_mean, ts_decay_linear) or gate trades with trade_when.
- LOW_TURNOVER: shorten windows, or use changes (ts_delta) instead of levels.
- LOW_SUB_UNIVERSE_SHARPE: the effect must also hold in the most liquid stocks. Remove size tilts; a noisy daily signal often becomes more robust when smoothed over a few days; combining two related fields of the same dataset diversifies the noise.
- CONCENTRATED_WEIGHT: normalise cross-sectionally (rank/zscore), winsorize, backfill sparse fields.
- LOW_FITNESS (fitness = Sharpe * sqrt(|returns| / max(turnover, 0.125))): cut turnover without losing the signal (smooth over the signal's own horizon, trade only on meaningful changes with trade_when) or raise returns per trade (act where the signal is strongest).
- PROD_CORRELATION (too much like alphas already in production): keep the economic idea but express it with less-used data or a different angle - a change or surprise instead of a level, a shorter-lived version of the information, or a second, economically linked signal from a different data source that the crowded alphas do not use. Never add noise.
- LOW_2Y_SHARPE: the effect has weakened recently; only a better construction helps (do not shorten windows to fit the last two years).
Change one or two things per variant and explain the change in `idea`.

## Construction playbook: which operators these fields need (BRAIN docs, research and this engine's measurements)
{{playbook}}

## Alpha shapes that research supports for these kinds of data
A variant may move the idea into a different shape ({x}, {y} are fields from the table; windows follow the field's update speed). Set `shape` to the shape id you used.
{{shapes}}

## OPERATOR REFERENCE (the only operators that exist on this account)
{{operators}}

## DATA FIELDS (the only fields you may use)
field_id | type | dataset | coverage | description
{{fields}}

Grouping fields (type GROUP; only as group arguments): {{grouping_fields}}

## Mistakes caught by the validator in earlier runs - do not repeat them
{{lessons}}

## Output - JSON only
{"candidates": [{"parent_id": 0, "expression": "...", "shape": "...", "neutralization": "...", "decay": 4, "truncation": 0.08, "idea": "...", "rationale_data": "...", "rationale_operators": "..."}]}
