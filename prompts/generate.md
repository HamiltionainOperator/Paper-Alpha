# Task
Implement the research hypothesis below as {{n}} DIFFERENT candidate alphas for WorldQuant BRAIN.

## Hypothesis (from the paper "{{paper_title}}")
{{hypothesis}}

## Relevant excerpts from the paper
{{paper_excerpts}}

## Simulation scope
{{scope}}

## What these alphas are for
{{route}}

## Hard constraints (candidates that break these are discarded)
{{constraints}}

## Settings you choose per candidate
{{settings_choices}}

## OPERATOR REFERENCE (the only operators that exist on this account)
{{operators}}

## DATA FIELDS (the only fields you may use) - datasets: {{datasets}}
field_id | type | dataset | coverage | description
{{fields}}

Fields the research cites for this hypothesis (verified on BRAIN; prefer these): {{cited_fields}}

Grouping fields (type GROUP; only as group arguments; they do not count toward the field limit): {{grouping_fields}}

## Alpha shapes that research supports for these kinds of data
Templates: {x} and {y} are fields from the table above (vector fields aggregated with vec_avg first), windows follow how often the field changes (about 5 days for daily-changing fields, 21 for weekly, 63 for monthly or quarterly). "seen" is what this engine has measured for that shape on this kind of data.
{{shapes}}

## Construction playbook: which operators these fields need (BRAIN docs, research and this engine's measurements)
{{playbook}}

## Alphas that worked before on BRAIN (for style and scale, do not copy)
{{exemplars}}

## Mistakes caught by the validator in earlier runs - do not repeat them
{{lessons}}

## Platform guidance (official BRAIN documentation)
{{guidance}}

## How to build strong candidates
- Implement the paper's economic mechanism. In `idea`, say which part of the hypothesis the candidate implements.
- Choose fields whose description matches the concept you need. Prefer good coverage. A sparse or event-like field is either carried forward (ts_backfill, for characteristics that predict for months) or traded around its updates (an event form); never leave it bare, and say in `idea` which form you chose and why.
- Normalise cross-sectionally (rank, zscore, or a group operator) so a few extreme stocks do not dominate.
- Control turnover: news and event data are noisy, so smooth them over time or gate trading with trade_when.
- Do not multiply by company size (it tends to fail the sub-universe robustness test).
- Make the {{n}} candidates genuinely different: submitted alphas must be weakly correlated with each other (Power Pool alphas below 0.5, regular alphas below 0.7), so vary the fields (no more than two candidates may use exactly the same set of fields), the construction, the horizon or the conditioning.
- Use at least three different shapes from the list above across your candidates, and set `shape` to the shape id each candidate follows (or "other"). rank(x) is right for fields that already are forecasts or scores; estimates, events and news usually need a change, event or spread shape.
- Respect the operator limit. Count every function call and every infix + - * / < > <= >= == != && ||; a unary minus counts unless it negates a plain number; ts_backfill and group_backfill are free.

## Output - JSON only
{"candidates": [{"expression": "...", "shape": "...", "neutralization": "...", "decay": 4, "truncation": 0.08, "idea": "...", "rationale_data": "...", "rationale_operators": "..."}]}
- expression: the Fast Expression code.
- idea: 1-3 sentences of economic intuition, no code.
- rationale_data: why each field was chosen, naming the fields.
- rationale_operators: one short clause per operator used, e.g. "ts_mean(): smooths daily noise"; never paste the expression.
