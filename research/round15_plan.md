# Round 15 plan: the next alphas (24 Oct 2026)

**Status: prepared, not simulated.** The session that wrote this plan could not reach BRAIN: the cloud environment's
network policy denied `api.worldquantbrain.com` and `openrouter.ai`, and it had no BRAIN credentials. Nothing here is a
measurement. This note is the run order for the next session that has access. It follows the "next experiments" of
`research/deep_research_round14.md` and the lessons of rounds 7-14 (`research/FINDINGS.md`).

## Why this order

- **Osmosis needs 3 scopes with 10+ alphas each** (round 13). USA D1 has enough. On 20 Oct EUR D1 had 4 alphas and GLB
  D1 had 1. Run `p2a osmosis --refresh` for today's counts. So EUR and GLB alphas count for more than more USA ones.
- **Combinations of independent non-price sources are how this account's production alphas are made** (#499, #516,
  #605, #692 in USA; #742, #771, #819 in EUR). The combiner needs the parts already simulated, and those live in the
  local store, which a fresh checkout does not have. Step 0 rebuilds it from the BRAIN account.
- **EUR composites failed BRAIN's 2-year test** (round 13: #837-#840, 1.46-1.55 overall, about 1.24 over the last two
  years). The combiner now estimates a combination's last-two-years Sharpe from its parts' PnL and proposes only those
  that clear the bar (`combine.recent_days`, `combine.recent_sharpe_margin`).
- **New regions get new mechanisms, not USA ports.** Round 14 verified that quality and value are strongest in emerging
  markets. Its sourced but unverified leads: momentum and analyst revisions fail in Japan and most of Asia, and in China
  value is earnings-to-price outside the smallest 30%. ASI and JPN analyst and event signals scored only 0.16-0.51 on
  this account. The round-15 mechanisms (`research/mechanisms.yaml`) run only in the regions their research covers.

## 0. Access, then rebuild the engine's memory

Environment settings (cloud environment menu, then Edit):
- Network access: allow `api.worldquantbrain.com`. Add `openrouter.ai` only for the LLM steps (`generate`, LLM
  refinement); restore, mechanisms, combine, decrowd, uniqueness and check do not use it.
- Environment variables: `BRAIN_EMAIL`, `BRAIN_PASSWORD` (and `OPENROUTER_API_KEY` for the LLM steps). A new session
  picks them up. With biometric sign-in, `p2a login` prints a link to open on the phone.

```bash
python3 -m p2a doctor                                  # keys, login, catalog
python3 -m p2a sync --no-docs                          # operators, settings, USA datasets (minutes)
python3 -m p2a restore                                 # every alpha on the account -> local store (idempotent)
python3 -m p2a osmosis --refresh                       # alphas per scope, what each scope still needs
```

`restore` reads up to `restore.max_alphas` (5000) of the newest alphas. Each becomes a simulated row in its own
region, universe and delay. Fields are analysed against the live catalog, one lookup per new field. BRAIN's settings,
results and checks are kept. Daily PnL is fetched later, when a step needs it. The engine's crowded reference factors go
back to the cache the uniqueness screen reads, so they are not simulated again. Alphas submitted earlier and since
decommissioned count as used. SuperAlphas and Region Agnostic alphas are skipped.

## 1. EUR TOP2500: country revision score plus parts that held up in 2022-23

```bash
python3 -m p2a sync --region EUR --universe TOP2500 --no-docs
python3 -m p2a references --region EUR --universe TOP2500 --top 80     # exposures; simulates only missing factors
python3 -m p2a inventory --region EUR --universe TOP2500               # available parts, last-2y Sharpe of each
python3 -m p2a combine --region EUR --universe TOP2500 --n 8           # proposals: est. Sharpe, sub-universe, last 2y
python3 -m p2a combine --region EUR --universe TOP2500 --n 8 --simulate
```

Then for each result with Sharpe >= 1.58:
- production correlation above 0.65: `p2a decrowd --ids <id> --simulate` (round 13: #818 0.693 -> #819 0.522);
- `p2a uniqueness --ids <id>` (fast correlation endpoints), then `p2a check --ids <id>`;
- `p2a queue --region EUR --universe TOP2500` lists what is ready, in order.

What to expect from the notes: the country-normalized revision score (#890, 1.19, at most 0.10 with the account's EUR
alphas) is the strongest unused base. Days to cover and other executives' tone faded in 2022-23 and should now be
filtered out by the 2-year estimate. Trade-ideas net exposure (1.66) is illiquid (sub-universe ratio 0.33), so it can
only join at half weight.

## 2. GLB MINVOL1M: balanced composites

```bash
python3 -m p2a sync --region GLB --universe MINVOL1M --no-docs
python3 -m p2a references --region GLB --universe MINVOL1M --top 80
python3 -m p2a inventory --region GLB --universe MINVOL1M
python3 -m p2a combine --region GLB --universe MINVOL1M --n 8 --simulate
```

Information signals work in MINVOL1M, not TOPDIV3000 (round 14). Each GLB source is strong in one geography only
(search interest in AMER, call topic sentiment in EMEA, insider buying and trade ideas in APAC), so a submittable GLB
alpha needs parts from different geographies, like #886 (2.19, every geography >= 1.31). The engine does not yet
estimate the AMER / EMEA / APAC split: read it from the simulation's PnL record set before submitting.

## 3. New scopes: CHN, IND, ASI (and JPN) with the round-15 mechanisms

Mechanisms (each one probe; `research/mechanisms.yaml`, section "round 15"):

| mechanism | regions | idea (source) |
|---|---|---|
| `ep_value` | CHN, IND, ASI, JPN | earnings-to-price value (Basu 1977; Fama-French 2012; Liu-Stambaugh-Yuan 2019) |
| `ep_value_ex_shells` | CHN | the same without the smallest 30% by cap, priced as reverse-merger shells (Liu-Stambaugh-Yuan 2019) |
| `abnormal_turnover` | CHN | low last-month turnover against the past year beats high (the PMO sentiment factor, same paper) |
| `profitability` | CHN, IND, ASI, JPN | return on equity, negative book equity left out (Novy-Marx 2013; Asness-Frazzini-Pedersen 2019) |
| `country_value_quality` | ASI, IND, JPN | book-to-market plus profitability, neutral within country x industry (for the Japan sub-test) |

The roles `net_income` and `book_equity` lead with ids verified in one region (`net_income_total_5` in CHN, `equity` in
USA) and otherwise match descriptions. **Those descriptions were never seen live outside CHN and USA, so check the
fills before simulating:**

```bash
python3 -m p2a sync --region CHN --no-docs             # without --universe the engine picks one the region has
python3 -m p2a mechanisms --list --region CHN          # roles -> live fields: net income must be reported net income,
                                                       # not an estimate, a growth rate or a per-share figure
python3 -m p2a mechanisms --region CHN --simulate      # only the mechanisms whose regions include CHN
python3 -m p2a references --region CHN --top 40
python3 -m p2a combine --region CHN --n 6 --simulate   # value + sentiment (combine group china_value_sentiment)
```

Repeat with `--region IND` and `--region ASI` (and `JPN` if the account has it). China specifics from round 11:
simulated trading costs take about a 3-4% fixed drag per alpha plus about 10% x turnover, so keep turnover low (the
CHN-only mechanisms use decay 8, the others 6). The robust-universe test needs a long book with Sharpe >= 0.4 x the full Sharpe. For ASI,
BRAIN's `LOW_ASI_JPN_SHARPE` test checks the Japanese stocks on their own: that is why `country_value_quality`
neutralizes within country x industry.

## 4. After the simulations

- Submission stays manual. `p2a queue` gives the order and the reasons. Regular quota: 4 a day.
- After submitting, `p2a osmosis --refresh` shows which scopes have reached 10 alphas. With 3 valid scopes the points
  plan (`p2a osmosis --csv osmosis.csv`) becomes an allocation.
- SuperAlphas for EUR and GLB (round 14, next experiment 5) need 10+ ACTIVE alphas in the region first. STATISTICAL
  neutralization cut the USA SuperAlpha's production correlation from 0.81 to 0.62 (d5KOapn2).
- Record measured results in `research/FINDINGS.md` as round 15.

## Rules that still hold (rounds 7-14)

- Unique means non-price information: an idea whose values are mostly past returns is crowded however rare its data.
  The reference screen catches these. Above 0.6 with a crowded factor, the idea gets one residual test.
- One crowded part makes the whole composite crowded. Shared mild tilts add up, so regress them out (`decrowd`) or use
  risk neutralization.
- Sparse fields need an explicit form: held with `ts_backfill` over their update interval, or traded as events.
- A part that drives a submitted alpha stays out of new combinations. The combiner keeps combinations below 0.6 with
  every submitted alpha.
- Sub-universe: weight by `rank(cap)` or add liquid parts. The combiner estimates the composite's ratio from its parts.
