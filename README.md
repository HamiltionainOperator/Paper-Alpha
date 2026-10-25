# paper2alpha

Turns research papers into **WorldQuant BRAIN alphas** - production (regular) alphas and Power Pool alphas - using
**free OpenRouter models**, without letting the models hallucinate operators, fields, or syntax.

```
papers (PDF / arXiv / URL / text)
   │  ingest + chunk + BM25 index
   ▼
hypotheses  ── 1 LLM call per paper, mapped onto BRAIN's live data categories
   │
   ▼
grounded prompt ── live operator catalog + real field shortlist + theme rules + your past results
   │  free model (picked by learned score)
   ▼
static validator ── every operator / keyword / field / type / limit checked against the live catalog
   │  errors with exact hints  ──►  targeted LLM repair (same conversation)
   ▼
BRAIN simulation ── batched multi-simulations, quota guard, polling
   ▼
Power Pool evaluation ── Sharpe, turnover, sub-universe, theme match, PP correlation
   ▼
idea lifecycle ── per signal family: winner / promising / used / dropped, from the evidence
   │  only "promising" families get one targeted refinement round
   ▼
refinement ── fixes for specific failed checks, then one batched LLM call (expression changes only)
   ▼
submission queue ── best alpha per winning family, ordered by quality, de-duplicated by daily PnL correlation
   ▼
report with Power Pool descriptions (Idea / Rationale for data / Rationale for operators)
```

## Why it doesn't hallucinate

Nothing about the platform is hard-coded. `p2a sync` pulls it from the BRAIN API:

| What | Source |
|---|---|
| Operators, their parameters, keywords, infix forms | `GET /operators` (definitions parsed, e.g. `ts_backfill(x,lookback = d, k=1)`) |
| Operator documentation and official examples | `GET /operators/{name}` |
| Valid settings (regions, universes, neutralizations, decay range...) | `OPTIONS /simulations` |
| Data categories, datasets, fields (type, coverage, dataset, category) | `/data-categories`, `/data-sets`, `/data-fields` |
| Which datasets an active Power Pool theme covers | the `themes` tags the API puts on datasets |
| Platform guidance | BRAIN Learn pages (`/tutorials`, `/tutorial-pages/{id}`) |

Then every candidate goes through a real Fast Expression parser and type checker
(`p2a/fastexpr/`) before any simulation is spent:

- unknown operators → rejected with the closest real ones (`ts_max` → `ts_mean, ts_arg_max, ...`)
- unknown or invented fields → rejected with near matches
- VECTOR fields used without a `vec_*` operator, `vec_*` applied to MATRIX fields → rejected
- group arguments that aren't GROUP fields → rejected
- wrong arity, unknown keyword arguments, non-integer windows, COMBO-only operators → rejected
- Power Pool limits: operators counted **exactly like BRAIN's `operatorCount`** (verified 45/45 on real
  alphas), `ts_backfill`/`group_backfill` excluded, max 3 non-grouping fields, theme categories,
  single-category rule

The exact error messages go back to the model, which repairs the candidates in the same conversation.
In live tests with free models, 12/12 candidates were valid on the first pass and all
deliberately broken candidates were fixed in one repair call.

## How it "trains"

Free OpenRouter models can't be fine-tuned, so the engine learns from its own experience and feeds it back:

- **Knowledge base**: papers and BRAIN docs are chunked and indexed; each prompt gets the most relevant paper excerpts and docs.
- **Hallucination memory**: every validator catch and simulator rejection is counted, and the most frequent
  ones are listed in future prompts ("`ts_max` is NOT an available operator (invented 3x before)").
- **Exemplars**: your best simulated alphas (closest dataset/category first) become few-shot examples.
- **Outcome stats**: per-dataset median Sharpe/turnover and most frequent failing checks go into the prompt.
- **Bandits**: hypotheses and free models are chosen by Thompson sampling on past results; models that return
  broken JSON or invalid alphas get used less.

## When to keep an idea and when to drop it

Changing the settings of one alpha over and over does not create new alphas: neutralization, decay and
cosmetic wrappers (rank, zscore, winsorize) of the same data fields trade almost the same positions, so the
copies are correlated (Power Pool alphas must be < 0.5 correlated with each other) and a weak signal stays weak.
The engine therefore budgets **idea families** (one family = one set of data fields), not expressions, and
decides from the simulation evidence (`p2a/engine/lifecycle.py`, thresholds in `config.yaml` → `lifecycle`):

| Evidence | Decision |
|---|---|
| Best Sharpe below 50% of the Power Pool floor after the first probe | **drop**: settings cannot add signal |
| Sharpe at or below -60% of the floor | invert once, then judge the inverted signal |
| Sub-universe Sharpe below half its limit | **drop**: the effect lives in illiquid stocks |
| Correlation >= 0.9 with production alphas | **drop**: crowded, adds nothing |
| Same fields as a submitted alpha, or daily PnL correlation with one above the limit | **used**: never refined again |
| A submittable (eligible) alpha exists | **winner**: stop spending on the family |
| Two refinements that did not beat the parent by 0.05 Sharpe, or 5 simulations in total | **drop**: plateau / budget |
| Otherwise, Sharpe >= 75% of the floor | **promising**: one targeted round |

Settings change only to fix a specific failed check (high turnover → more decay, concentration → lower
truncation, a liquid-universe test only when the liquid names alone already clear the floor), at most once per
expression. Everything else must change the expression. New simulations go to unexplored families first.
`p2a families` shows every family with its state and the reason; `p2a queue` lists what to submit next.

## Alpha shapes: more than one way to turn a field into an alpha

`rank(field)` works well on vendor forecasts, but most data needs a different structure. The shape library
(`research/shapes.yaml`, research and sources in `research/alpha_shapes_research.md`) holds 16 research-backed
templates (level, change, history-relative, trend, fresh-update and surprise-hold event gating, news-day
update, intensity, dispersion, spread, standardized spread, time-series residual, orthogonal, combination,
interaction, co-movement) and 4 robustness wrappers (liquidity-split decay, size weight, size-bucket neutral,
hump). The engine:

- validates every template against the live operator list and disables shapes whose operators are missing;
- recognises the kind of each field (forecast, analyst estimate, surprise, implied volatility, sentiment, news
  count, flow, risk, quality/value) from its catalog description, and its speed from the level probe's turnover,
  which sets the windows (5 / 21 / 63 days);
- probes a never-tried field with the first shape of its kind (`first_shape`), then gives fields that showed
  signal their next shapes (`p2a shapes`), pairing two-field shapes with a counterpart of the same dataset, an
  unrelated signal, or the submitted alpha the field trades like;
- treats each shape class on a field as its own idea family (still screened by daily-PnL correlation);
- puts the shapes that suit the prompt's fields, with what they produced so far, into every generation and
  refinement prompt, and orders shapes by Thompson sampling on those results (`p2a shapes --stats`).

## Two routes: production (regular) alphas and Power Pool alphas

BRAIN takes two kinds of alpha, and they pay differently (`research/unique_alphas_research.md`):

| | Power Pool (`--route power_pool`) | production / regular (`--route regular`) |
|---|---|---|
| data | the active theme (now: one of analyst, model, news) | any category |
| bars | Sharpe >= 1.0, <= 8 operators, <= 3 fields, PP correlation < 0.5 | Sharpe >= 1.58, fitness >= 1.0, 2-year Sharpe, sub-universe, self- and **production correlation < 0.7** |
| quota (your account now) | 1 pure Power Pool alpha a day | 4 a day |

An alpha that is Power Pool eligible *and* passes every regular test is "Power Pool + Regular" and does not use
the pure Power Pool quota; the Power Pool queue marks these. Base payments carry multipliers BRAIN reports with
every simulation (pyramid = region x delay x category, higher where few alphas exist; themes such as a universe
theme); `p2a pyramids` lists them. What makes an alpha unique, measured on this account:

- **Production correlation follows the data, not the shape.** Popular vendor forecasts are 0.7-0.99 correlated
  with alphas already in production; the more alphas a dataset has, the higher.
- **Combinations dilute it.** The combiner (`p2a combine`) joins 2-3 economically linked signals from different
  data sources (groups in `research/shapes.yaml` `combine_groups`), estimated from the daily PnL BRAIN already
  reported: Sharpe adds up when parts are weakly correlated, and the correlation with any production alpha is
  divided by the volatility of the sum. Only combinations whose estimate clears 1.1x the bar are simulated. On the
  regular route the estimate over the parts' last two years must clear the bar too (BRAIN's 2-year test, which sank
  EUR composites whose parts faded in 2022-23).
- **Risk-factor neutralization** (SLOW, FAST, SLOW_AND_FAST, CROWDING, ...) lowered production correlation by
  0.08-0.12 at a similar Sharpe; it is the one settings change the regular route uses ("decorrelate"), once per
  family, chosen by turnover.
- **The fast correlation endpoints** (`p2a uniqueness`) measure production and self-correlation in seconds, so
  crowded candidates are dropped before the slow submission check.
- **Unusual data is not enough: the information must not be the stock's own price** (round 7,
  `research/deep_research_round7.md`). Two ideas on rarely used datasets were 0.90-0.93 with production because
  their values were mostly past returns. `p2a references` correlates every alpha's PnL with nine crowded factors
  (1-, 5- and 21-day reversal, momentum, size, low volatility, volume-price, value, EPS revisions). Every alpha above 0.7 with one of
  them was crowded in production. The lifecycle gives such an idea one residual test,
  `s - regression_proj(s, factor)`, and drops it if nothing is left.
- **What worked: channels of private information.** The option smirk, implied-volatility innovations, lending-market
  tightness and managers' unscripted answers on earnings calls each have Sharpe 0.95-1.80 and are nearly independent.
  Their composite (#493) has Sharpe 2.63, fitness 1.20 and production correlation 0.630 (only 71 production alphas
  above 0.5). It passed BRAIN's submission check. The combiner estimates a combination's sub-universe test from its
  parts, so parts that work only in illiquid stocks join at half weight.
- **Construction playbook** (`research/operator_playbook.yaml`): which operators a field's structure needs (sparse
  fields held or traded as events, vectors reduced, snapshot revisions, residuals with an intercept, NaN-safe sums).
  It goes into every generate and refine prompt.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in BRAIN_EMAIL / BRAIN_PASSWORD (and OPENROUTER_API_KEY if not already set)
python3 -m p2a doctor       # checks keys, login, free models, catalog, theme
python3 -m p2a sync         # one-time catalog + docs sync (a few minutes; cached)
python3 -m p2a restore      # fresh checkout or cloud session: rebuild the local memory from your BRAIN alphas
```

If your BRAIN account uses biometric sign-in, `p2a login` prints a link to open in your browser.
The session cookie is cached in `.p2a/session.json` (permissions 600).

The local store (`.p2a/`) stays on the machine that made it. In a fresh checkout or a cloud session, `p2a restore`
rebuilds it from the account's own alphas: every idea already tried, with BRAIN's settings, results and checks (daily
PnL is fetched when a step needs it). The lifecycle then skips decided ideas, and the combiner and the inventory have
their parts without new simulations. Running it again only adds alphas created since.

## Use

```bash
python3 -m p2a ingest papers/                 # PDFs, .txt/.md, URLs, or arXiv ids like 2401.01234
python3 -m p2a hypotheses                     # what was extracted
python3 -m p2a run --cycles 2 --n-hyp 3       # generate -> simulate -> refine -> check -> report
python3 -m p2a report                         # markdown report in .p2a/reports/
```

Step by step instead:

```bash
python3 -m p2a generate --hypothesis 4 --simulate
python3 -m p2a refine --simulate              # variants of near-misses
python3 -m p2a check --top 5                  # BRAIN's read-only submission check (PP correlation, theme)
python3 -m p2a describe 17 --apply            # put the Power Pool description on the BRAIN alpha
python3 -m p2a try "rank(some_field)" --neutralization INDUSTRY   # your own idea, same validator + simulator
python3 -m p2a try --file research/probes-2026-10-16.json         # a batch of researched probes
python3 -m p2a try --file research/deep_research_round15.json --route regular --no-sim  # entries name their own region;
                                                                  # {role} slots are filled from each region's catalog
python3 -m p2a families                       # idea lifecycle: winners, promising, used, dropped (and why)
python3 -m p2a queue                          # submittable alphas in the order to submit them
python3 -m p2a explore --category analyst --simulate   # first-shape probes of untried fields in one category
python3 -m p2a shapes --simulate              # next research shapes for fields that showed signal
python3 -m p2a shapes --stats                 # which shape works on which kind of data
python3 -m p2a validate "group_rank(ts_mean(vec_avg(nws18_ssc), 21), subindustry)"   # add --route regular for production limits
python3 -m p2a stats                          # what the engine has learned
```

Production (regular) alphas:

```bash
python3 -m p2a run --route regular                       # generate, explore, combine, refine, measure, check
python3 -m p2a explore --route regular --n 10 --simulate # probes of the least-used data in every category
python3 -m p2a combine --n 8 --simulate                  # combinations estimated to clear Sharpe 1.58 x 1.1
python3 -m p2a references                               # PnL correlation with crowded reference factors (local)
python3 -m p2a mechanisms --only iv_smirk --simulate     # research mechanisms (research/mechanisms.yaml)
python3 -m p2a mechanisms --list --region CHN            # live fields each role resolves to; region-scoped mechanisms
python3 -m p2a combine --origin mechanism: --simulate    # composites of research mechanisms only
python3 -m p2a uniqueness                                # production / self-correlation via the fast endpoints
python3 -m p2a check --top 5                             # BRAIN's full submission check (both routes)
python3 -m p2a queue                                     # production queue and Power Pool queue
python3 -m p2a pyramids                                  # pyramid multipliers and themes BRAIN reported
python3 -m p2a inventory --region EUR --universe TOP2500 # simulated parts still free to feed a new alpha
python3 -m p2a osmosis --csv osmosis.csv                 # Osmosis points plan per scope (read-only)
```

Other regions: `--region EUR --universe TOP2500` (run `p2a sync` with the same flags first). Mechanisms with
`regions:` in `research/mechanisms.yaml` (value, profitability and sentiment for CHN, IND, ASI and JPN) are proposed
only there. The next round's run order is in `research/round15_plan.md`.

**Osmosis.** BRAIN combines the alphas you give Osmosis points to, per scope (region x delay). It uses the combo's PnL
for a 1-2x multiplier on the daily base payment, for Combined Osmosis Performance in Genius and for the leaderboard.
An allocation counts only with at least 3 scopes, each with exactly 100,000 points over at least 10 alphas (config
`osmosis`). `p2a osmosis` shows which scopes are short of alphas. For each scope that has enough, it applies the
guide's exclusions (weak investability, high turnover, near-duplicates) and proposes points. The points maximize the
in-sample Sharpe of the combined daily PnL after an assumed trading cost. You enter the points on the platform; the
engine does not change them.

**The engine never submits alphas.** Submission quotas show up in BRAIN's check (`REGULAR_SUBMISSION`,
`POWER_POOL_SUBMISSION`); the engine reports a used-up quota as "WAIT", not as a defect. Review the queue and
submit on the platform. After you submit, the engine reads your submitted alphas back and treats their
families as used.

## Monthly theme update

The current themes live in `config.yaml` under `themes:`. Each month, paste the rules from
[Current month Power Pool Themes](https://support.worldquantbrain.com/hc/en-us/articles/38927747787031-Current-month-Power-Pool-Themes)
(the support site needs a login, so the engine can't fetch it itself). Typos such as `fundamnetal`
are fuzzy-matched against the live category list. The engine also detects active Power Pool themes
from the API's dataset tags even without a rule, and `p2a themes` shows how each rule was interpreted.

Current rule (Oct 14-27, 2026): `delay=1 & datacategory in ['analyst', 'model', 'news'] & single datacategory`.

## Power Pool rules used (from the BRAIN docs, Oct 2026; editable in `config.yaml`)

- Sharpe >= 1.0; turnover 1%-70%; sub-universe and robust-universe tests must pass
- <= 8 operators (`ts_backfill`, `group_backfill` free); <= 3 unique data fields (grouping fields free)
- Power Pool correlation < 0.5 against your own Power Pool alphas (or 10% better Sharpe)
- Must match an active theme; description must follow Idea / Rationale for data used / Rationale for operators used (>= 100 chars)
- Fitness, concentrated weight, IS ladder, self/prod correlation are not required

## Budgets

- OpenRouter free tier is about 50 free-model requests/day without credits, reset at 00:00 UTC.
  `llm.daily_request_budget` (default 45) stops the engine before that. One paper ≈ 1 request; one hypothesis ≈ 1-3 requests.
- BRAIN simulations: the engine stops submitting when `X-Ratelimit-Remaining` drops below
  `brain.simulation.stop_when_remaining_below`, and never re-simulates an identical payload.

## Layout

```
p2a/fastexpr/   lexer, Pratt parser, signature parser, catalog-driven analyzer, printer
p2a/brain/      API client (auth, throttling), catalog sync, settings validator, simulator
p2a/llm/        OpenRouter free-model client (discovery, budget, Thompson sampling), JSON extraction
p2a/knowledge/  paper ingestion, BM25 retrieval
p2a/engine/     themes, memory, grounding, hypotheses, generator, evaluator, refiner, pipeline
prompts/        prompt templates (edit freely)
tests/          unit tests, mock BRAIN API, mock OpenRouter
```

Tests: `python3 -m unittest discover -s tests -t .`
