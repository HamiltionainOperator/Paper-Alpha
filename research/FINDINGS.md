# Research findings - 2026-10-16

## Round 15: prepared, not simulated (24 Oct 2026)

- The session could not reach BRAIN (the cloud environment's network policy denied `api.worldquantbrain.com`), so this
  round has no measurements. The run order for the next session is `research/round15_plan.md`.
- Engine: `p2a restore` rebuilds the local store from the account's alphas, so a fresh checkout keeps the history.
  The combiner estimates each combination's last-two-years Sharpe and proposes only those that clear BRAIN's 2-year
  test. Five new mechanisms only run in the regions their research covers (CHN, IND, ASI, JPN): value, value without
  shell stocks, abnormal turnover, profitability, and country x industry value plus quality.
- Deep research (25 Oct): `research/deep_research_round15.md` reviews well-regarded papers with U.S., European or global
  evidence. `research/deep_research_round15.json` holds 45 unsimulated probes (USA 14, EUR 17, GLB 14) from them:
  - net issuance, return seasonality, overnight-daytime tug of war, high-volume premium;
  - vol-of-vol, target price against industry peers, long-term growth optimism, analyst bias, bold revisions;
  - cash and gross profitability, asset growth, fresh-information timing, residual momentum, news-day drift;
  - carbon and short disclosure (speculative).
  `p2a try` now reads entries that name their own region and fills `{role}` slots from each region's catalog.

## Round 13: signal inventory and EUR source scan (20 Oct 2026)

- **Signal inventory** (`p2a inventory`). It lists every simulated part of a scope with its verdict: used, crowded,
  illiquid, weak or available. Before the scan, EUR TOP2500 had 1 available part of 16 (leverage presentation tone,
  #535, 0.98). Everything else was weak or already inside #742 / #771 / #777.
- **Securities lending (model239) is the new EUR channel.** Each part's correlation with the account's EUR alphas is
  at most 0.28.
  - Δutilization: rank Sharpe -1.01 (#788), so rising utilization predicts low returns.
  - Ticket growth: -1.10 (#798); trades 0.68 like low volatility, crowded.
  - Squeeze-risk score `mdl239_shortlasso30d`: +1.01 when ranked (#789), so crowded shorts outperform.
  - Utilization level: 1.15 when negated (#808, the Boehmer et al. 2022 measure). It trades 0.71 like low volatility,
    crowded.
  - Days to cover as utilization vs turnover ranks: 0.91 (#809). Fee volatility, after Engelberg-Reed-Ringgenberg:
    0.14 (#810).
- **The lending composite with factor residuals reached 1.50** (#807): Δutilization, tickets, squeeze score and
  leverage tone, regressed on low volatility and within-industry momentum. Fitness 0.90, sub-universe 1.17 vs 0.78,
  ladder 3.3.
- **Fourth EUR alpha #819 (LL59V2P1): BRAIN's check says regular eligible.**
  - Parts, seven sources: Δutilization (negated), squeeze score, leverage presentation tone, event-embedding and
    120-day ML predictions, numeric share of the Q&A, Loughran-McDonald Q&A tone (#816, 1.14 alone) and abnormal
    search attention (Da-Engelberg-Gao, #794 negated). The composite is regressed on low volatility and size.
  - Results: Sharpe 1.82, fitness 1.03, sub-universe 1.53 vs 0.95, ladder 2.18 vs 2.02, investability-constrained
    Sharpe 1.79.
  - Correlation: production 0.522 (6 production alphas above 0.5), self 0.14. Weak years: 2016 (0.24) and 2018
    (-0.10).
  - The path there:
    - #811, five parts: 1.57.
    - #818, seven parts: 1.73. It passed every computed test but was 0.693 with production (1810 production alphas
      above 0.5).
    - The parts alone were only 0.55-0.63. Combining them cancels their own noise and leaves the shared low-volatility
      (+0.35) and large-size (-0.29) tilt, as in round 9.
    - Regressing the tilt out (#819) raised the Sharpe and cut production correlation to 0.52. `SLOW` neutralization
      instead fell to 1.29 (#820).
  - The part estimator overshot again: 2.05 estimated vs 1.57 actual for the five parts.
- **Other new EUR sources:**
  - Tone change of the other executives: 0.92 (#817). It trades 0.40 like #771 and 0.51 like momentum.
  - Analyst-feature ML forecast: 0.71 (#815; momentum 0.64).
  - Seasonality forecast: 0.61 (#814).
  - Fundamental ML forecasts: 0.23 and -0.31 (#812, #813).
- **Osmosis** (Learn guide, 18 Sep 2026; account read on 20 Oct).
  - Rules: at least 3 scopes, each with exactly 100,000 points over at least 10 alphas.
  - Account: 0 points allocated. USA D1 has 62 alphas, EUR D1 has 4 (with #819), GLB D1 has 1.
  - `p2a osmosis` plans the points.
    - USA: 52 alphas kept after excluding near-duplicates (0.73-0.91).
    - In-sample after-cost Sharpe: 3.92 with the plan, 2.95 with equal points (assumed cost 2 bps per dollar traded).
    - Margin decides who survives that cost: #692 (11.3 bps) keeps 1.72; #499 (3.8 bps) and the early Power Pool
      alphas (2-3 bps) fall to 0.2-1.2.
  - Third-scope options:
    - USA D0 regular needs Sharpe 2.69 and fitness 1.5.
    - In GBR, lending, call topic tone and key-driver fields have no coverage.
  - Region Agnostic alphas (API type `REGION_AGNOSTIC`, region `ALL`, universe LARGE/MEDIUM/SMALL):
    - One submission adds every passing child, each in its own scope.
    - Probe leM8Oe6O (events plus recommendation change): EUR 2.15 (2-year ladder 1.43 < 1.58), USA 1.55 (sub-universe
      fails), ASI 0.51, no GLB child (`other553` missing in GLB).
  - Power Pool theme Oct 14-27: single category among analyst, model and news. #729 (events) and #808 (utilization
    level) are eligible; fundamental45 and key-driver alphas fail `PURE_POWER_POOL_THEME`.
- **Third scope: GLB** (20 Oct). 136 datasets, almost none tried before.
  - Ten paper probes on TOPDIV3000, double-neutralized by country and industry: only abnormal search interest
    reached 1.09 (#827).
  - Each GLB source works in one geography only:
    - Search interest: AMER 1.11, EMEA -0.52.
    - Call topic sentiment: EMEA 0.93.
    - Insider net buying: APAC 0.76.
    - Trade ideas: APAC 0.79.
  - Composites of these estimate at most 1.34 (AMER 1.08 / EMEA 0.80 / APAC 0.43). The GLB `pnl` record set has
    `amer-pnl`, `emea-pnl` and `apac-pnl` columns, read by the scratch script `glb_est.py`.
  - EUR small-cap signals vanish in GLB's large-cap EMEA slice: trade ideas score 1.66 in EUR but -0.22 in GLB EMEA.
- **Transfers of the account's USA price-volume alphas** (BRAIN recommends transferring alphas to TOPDIV3000).
  - Volume-confirmed reversal travels: GLB TOPDIV3000 1.80; Region Agnostic GLB MINVOL1M 2.54, EUR 1.98.
  - All copies are crowded. Production correlation is 0.78 for GLB, 0.85 for EUR and 0.92 for USA, with thousands of
    production alphas above 0.5. Fundamental USA alphas need translation because GLB uses other field names.
- **Region Agnostic GLB children skip the AMER/EMEA/APAC test.** BRAIN's parent check counted a GLB child with EMEA 0.84
  as submittable (`MIN_SUBMITTABLE_CHILDREN` 1 of 2).
- **More EUR sources.**
  - Strong: trade-ideas net exposure 1.66 (#835, sub-universe ratio 0.33) and call topic sentiment 1.26 (#831).
  - Moderate: Q&A tone 0.91 (#832).
  - Weak: Wikipedia attention, Q&A-presentation gap, retail net buying.
  - Their composites (#837-#840) reach 1.46-1.55 but fail the 2-year ladder (about 1.24). Days to cover and other
    executives' tone faded in 2022-23.
- **SuperAlphas** (20 Oct). The account has 144 submissions; 77 USA alphas are decommissioned and 67 are ACTIVE.
  - Only ACTIVE alphas of the SuperAlpha's region and delay can be selected (at least 10), so USA D1 (62) is the only
    pool.
  - API: POST /simulations with `type` SUPER, `selection`, `combo` and settings `selectionHandling`,
    `selectionLimit` and `componentActivation`. The scratch script `super_probe.py` runs one.
  - `ts_ir` is not accessible at Gold. The trailing-Sharpe combo
    `max(ts_mean(stats.returns, 250) / ts_std_dev(stats.returns, 250), 0)` works.
  - Results with that combo (IS component activation):

    | Selection | Sharpe | Fitness | Turnover | Returns | Drawdown |
    |---|---|---|---|---|---|
    | All 62 | 2.81 | 2.83 | 21% | 21.6% | 7.5% |
    | Non-price information (16) | 3.34 | 2.62 | 20% | 12.3% | 3.3% |
    | Fundamental6 (20) | 2.90 | 3.08 | 17% | 19.2% | 5.2% |
    | Price-volume only (26) | 2.40 | 3.24 | 20% | 37.2% | 10.5% |

    Equal weight and the correlation penalty scored 2.53-2.54.
  - Daily-PnL correlation: information-fundamental 0.61, information-price-volume 0.33, fundamental-price-volume
    0.29. All-62 is 0.92 with price-volume.
  - **Every SUBINDUSTRY SuperAlpha failed production correlation**: information 0.81, fundamental 0.83,
    price-volume 0.84. Self-correlation passed (0.70-0.77, by the Sharpe-higher rule).
  - **STATISTICAL neutralization on the SuperAlpha fixed it.**
    - The user submitted d5KOapn2: information family, STATISTICAL, decay 3. Sharpe 3.86, fitness 2.36,
      production correlation 0.62, self-correlation 0.46.
    - With the same settings:
      - fundamental 9qEVGq2q: Sharpe 3.33, fitness 2.55, sub-universe 1.84 vs 1.44, 0.40 with d5KOapn2;
      - price-volume 2rjOGrp8: Sharpe 2.68, fitness 3.10, 0.20 with d5KOapn2.
    - Other neutralizations on the information family (decay 4):
      - RAM: 3.00, passes the computed tests;
      - SLOW_AND_FAST: 3.13, fails sub-universe;
      - STATISTICAL: 3.76, fails sub-universe by 0.03 at decay 4.
  - Submission also needs selection and combo descriptions of at least 100 characters each
    (`SELECTION_DESCRIPTION_LENGTH`, `COMBO_DESCRIPTION_LENGTH`). They are set with
    PATCH /alphas/{id} {"selection": {"description"}, "combo": {"description"}}.
- **Failed EUR sources** (|Sharpe| < 0.45):
  - options;
  - lending: loan age, activity change, term vs overnight contracts;
  - partner network: return gap (0.82, but 0.98 like 21-day reversal) and partner momentum;
  - Merton distance-to-default change and default probability;
  - calls: casting, buy-side share, analyst participation;
  - news hype.

## Rounds 11-12: one paper per alpha, any region; China mechanics (19-20 Oct 2026)

- **New USA type.** #692 (LL5Rxkr2) shares no part with the earlier IV / call-tone / lending composites:
  - Parts: call linguistics (complexity, numbers, blame terms, passive voice; `other553`), website-visit growth,
    key-driver call events, event scores (weight 0.3), bias-free price targets, board centrality, intangibles.
  - Results: Sharpe 2.09, fitness 1.32, production correlation 0.62, self correlation 0.24. All computed tests pass.
  - First try (#691) missed the IS ladder by 0.02 and sub-universe by 0.01. Adding two liquid parts that held up in
    2022-23 fixed both.
- **Regional single-paper probes were mostly weak** (|Sharpe| < 0.5, about 45 probes in CHN, DEU, GBR, AMR, JPN, ASI).
  - Japan: Lazy Prices, customer ratings and accruals.
  - DEU and GBR: retail trades, director dealings and network momentum.
  - AMR: takeover likelihood, best ideas and breadth.
- **China mechanics, measured.**
  - **Costs are inside the simulation.** A signal and its negation do not mirror each other: the pair loses about
    9-15% a year in total, roughly a 3-4% fixed drag per alpha plus about 10% x turnover.
  - **Long-only robust component.** Every robust-universe component had 24-28% volatility and a Sharpe of 0.16-0.58,
    even momentum (full Sharpe -0.86) and a top-15%-cap alpha. So the test needs a long book with Sharpe
    >= 0.4 x the full Sharpe.
  - **Order flow.** Order-flow signals by trade size were reversal in disguise. Their gross edge was about 10%, but
    only about 2% survived costs.
  - **Style neutralization.** `SLOW_AND_FAST` lifted earnings surprise from 1.47 to 2.52 (#706, production
    correlation 0.55, 10 production alphas above 0.5). Raw SUE traded 0.72 / -0.64 / -0.62 like momentum, size and
    value. #706 still fails the robust test (0.54 vs 1.01).
- **EUR result.** #742 (0mj715a2) passed BRAIN's check as a regular alpha.
  - Parts: Boudoukh event scores, Womack recommendation change (`oth553_recvalue` vs `oth553_prerecvalue`) and call
    key-driver sentiment. INDUSTRY neutralization, then `decrowd` regressed out the momentum and low-volatility tilts.
  - Results: Sharpe 2.58, fitness 1.64, ladder 2.43, production correlation 0.55 (3 production alphas above 0.5). No
    EUR self correlation.
  - Before de-crowding (#740): Sharpe 2.51, production correlation 0.665.
- **EUR lessons.**
  - Price-target revisions trade 0.76 like momentum.
  - Analyst EPS and revenue surprises fell to Sharpe -1.7 and -1.0 in 2022 and sank the ladder (#738, #739).
  - Parts measured under `SLOW_AND_FAST` lost their edge inside an INDUSTRY composite: the estimate overshot by 0.7.
- **Second EUR alpha.** #771 (E5VGNoGJ, submitted) passed every computed test:
  - Parts: target-price and EPS revisions plus insider net purchases, regressed on within-industry momentum, low
    volatility and value; management's answer tone against its own past year; the CEO's tone change.
  - Results: Sharpe 2.32, production correlation 0.657, self correlation 0.31.
  - `REVERSION_AND_MOMENTUM` neutralization: Sharpe 3.07, production correlation 0.516 (#773). Revisions are earnings
    momentum and co-move with the momentum factor even when positions are orthogonal to it.
  - Sized by `0.5 + rank(cap)` it passes everything (#777, 2.68), but it is 0.79 with #771, a near-duplicate.
  - About 12 other distinct EUR mechanisms each scored below 1.3: call-tone breadth and consensus, obfuscation gap
    (Bushee et al.), So (2013) forecast gap, dispersion, dividend signals, auction order flow, news tone, CEO pay, ESG
    momentum, web attention.
- **BRAIN operator limit.** BRAIN limits regular alphas to 64 operators and counts `ts_backfill`. The validator now
  counts the same way (#771: 59 = BRAIN's `operatorCount`).
- **GLB.** Nothing submittable yet. Best part: revenue surprise vs consensus, 1.09 under `SLOW_AND_FAST`, but returns
  of 1.5% cap its fitness. News48 recommendation, event and earnings tone, and target-price signals were 0.27-0.48
  and failed sub-region tests. Composites of the unique GLB parts estimate about 1.1.
- **Engine.**
  - References are now simulated per alpha region; references a region cannot run are recorded once.
  - `scope(region)` picks a universe that exists in that region.
  - `decrowd` and the `uniqueness` pre-screen now use the alpha's own region. Before, a EUR variant was built and
    simulated in USA (#741).

## Round 9: third production alpha #605; recalibrated combiner (19 Oct 2026)

- **Submitted.** #605: Sharpe 2.37, fitness 1.06, production correlation 0.667, self correlation 0.667 with #499.
- **Probes.** About 85, mostly failures. New liquid parts: cash-flow presentation tone, own-history tone, rising
  lending fee, inverted squeeze risk.
- **Estimator.** The combiner now adds the parts' PnL as simulated (error 0.05 Sharpe, against 0.12 before).
- **Crowded factors.** Composites that trade 0.45 or more like a reference factor are skipped: mild tilts in several
  parts added up to production correlation 0.77.
- **No fourth alpha yet.** Remaining blocks: sub-universe, crowded tilts and weak clean parts. TOP1000 halves the
  Sharpe.

## Round 8: after #499 and #516 were submitted (18 Oct 2026)

Details: `research/deep_research_round7.md`, section "Round 8".

- **Submitted.** Two unique production alphas from this research: #499 (2.58, production correlation 0.659) and #516
  (2.29, 0.694).
- **New channel.** Leverage presentation tone (1.24). Most other new channels failed.
- **Most unique part.** IV innovations: production correlation 0.509, a single production alpha above 0.5.
- **Lowering production correlation.**
  - STATISTICAL neutralization cut it to 0.563 but broke the sub-universe test.
  - Regressing out the value tilt cut it below 0.6 for 0.1 Sharpe. This is now `p2a decrowd`.
- **Combinations.** Parts that drive a submitted alpha stay out.
- **UNITS warnings.** These are informational, per BRAIN.

## Round 7: unique alphas from non-price information (17 Oct 2026)

Full note: `research/deep_research_round7.md`.

- **Submittable.** #493 (d5KlxOVj) has Sharpe 2.63, fitness 1.20 and production correlation 0.630, and passed BRAIN's
  check. It combines five channels of private information: the option smirk, implied-volatility innovations, lending
  tightness, and management's profitability and leverage answer tone. #494 is its more robust sibling.
- **Uniqueness needs non-price information.** Ideas on rarely used data whose values are past returns were 0.90-0.93
  with production. A Sharpe-3.0 composite holding one residual-reversal part was 0.83.
- **Engine.** New pieces: the crowded reference-factor screen (`p2a references`), a residual-test remedy using
  regression_proj, the construction playbook in the prompts, and five research mechanisms. The combiner now:
  - estimates each combination's sub-universe test from its parts and gives illiquid parts half weight;
  - keeps parts that trade like a crowded factor out of regular combinations;
  - keeps flat days in its estimates.
- **What failed.** Most published mechanisms on BRAIN's vendor fields: employee reviews, workforce flows, insider
  ratios, sales revisions, fund holdings, breadth, option volume ratios, news sentiment aggregates and earnings-date
  timing (|Sharpe| below 0.5).

## Round 4: production (regular) alphas and uniqueness

**Question.** The 15 Oct Power Pool alphas paid $1.15 in total. How do we make alphas that are submittable as
regular (production) alphas, every consultant test passed and production correlation below 0.7, and that are
unique? Full write-up with sources: `research/unique_alphas_research.md`.

**What BRAIN reports.**
- Pyramid multiplier USA/D1/MODEL x1.3.
- The Power Pool theme pays x1.0; a "USA/D1 TOP1000" theme pays x2.0 (missed, because our alphas run on TOP3000).
- No Osmosis allocation (needs 3 scopes x 10 alphas), so no 1-2x daily multiplier.
- Quotas: pure Power Pool 1 a day, regular 4 a day.
- The submitted alphas were 0.79-0.85 correlated with production.

**Measured this round.**
1. Production correlation follows the data: 0.61-0.75 on datasets with about 100-300 alphas, 0.97-1.00 on
   model25 (15,631 alphas). BRAIN's risk-neutralized Sharpe does not predict it (r = 0.02); turnover does
   (r = -0.59, slow alphas are more crowded).
2. Risk-factor neutralization (FAST, CROWDING, SLOW) cut production correlation by 0.08-0.12 at about the same
   Sharpe, and 2 of 4 alphas went below 0.7. It costs returns (fitness) and often the liquid sub-universe.
3. TOP1000 kept only 0.46-0.74 of each signal's TOP3000 Sharpe, so the x2.0 theme is out of reach for these
   signals.
4. Combinations of existing parts (8 simulated): the estimate from daily PnL was accurate for slow parts and
   optimistic for fast ones. Returns rise about sqrt(n / (1 + (n-1) rho)) because BRAIN rescales positions.
   Combining popular forecasts only weakly dilutes production correlation (0.69-0.85).
5. BRAIN's `/alphas/{id}/correlations/prod|self` endpoints answer in seconds. The full check only reports
   correlations once they exist, which is why checks sat at PENDING for 10+ minutes.

**Result.** The first regular-eligible alpha: **#299 `d5Ke6EpE`**, `rank(option_quantile5_20d_pred) +
rank(long_term_120d_regression_prediction - short_term_20d_regression_prediction) +
rank(ts_zscore(short_term_return_pred_r20_q1, 63))`. Sharpe 2.40, fitness 1.24, turnover 28%, production
correlation 0.688, self-correlation 0.45, IS ladder 2.07 vs 2.02, sub-universe 1.43 vs 1.04. Every year
2018-2023 is positive. BRAIN's check PASSes every test.

**Later the same day.**
- A second, recalibrated combination batch produced #340 (Sharpe 2.19, fitness 1.06) and #338 (1.86 / 1.07). Both
  pass every regular test so far; production correlation is still being computed (BRAIN rations correlation
  requests per hour).
- #339 reached Sharpe 2.60, but its production correlation is 0.737.
- The engine's own regular cycle (`p2a run --route regular`) added #364 (1.90 / 1.03).
- Power Pool: the CROWDING-neutralized chart-CNN pair #287 `2rjPWNrJ` is eligible, with production correlation
  0.687 against 0.79-0.85 for the 15 Oct submissions, and a 2-year Sharpe of 2.27.
- Exploration of the least-used data (USA sentiment, EUR) found no standalone signal, and EUR ports of USA field
  names do not exist.

**Engine changes.**
- The regular route (`--route regular`) gives every alpha a regular verdict and has its own lifecycle bar (1.58)
  with a one-time "decorrelate" remedy.
- `p2a uniqueness` uses the fast correlation endpoints, and the check calls them first.
- `p2a combine` builds combinations of mechanism-linked parts, with Sharpe, returns, turnover, fitness and
  production-correlation estimates calibrated on this round.
- Pyramid-weighted exploration across all categories.
- Two submission queues; `p2a pyramids` lists the multipliers.

## Round 3: shapes beyond rank(field)

**Question.** Round 2's winners were almost all one shape, `rank(vendor_forecast)`. Which other structures
work, on which kinds of data? Research and templates: `research/alpha_shapes_research.md` and
`research/shapes.yaml` (16 shapes, 4 robustness wrappers, each with sources, validated against the live
operators).

**Experiment.** 34 shape probes on BRAIN across forecasts, option-implied data, analyst estimates, news and
stock-loan data (`research/shape-probes-2026-10-16.json`), then the engine's own explore and shape steps.

**Best result: a combination turned a near-miss into the strongest alpha of the project.** The option-implied
20-day forecast (Sharpe 1.91 alone, failing the sub-universe test) plus the 5-day "hedge" forecast built to be
uncorrelated with the main signals (0.80 alone): `rank(option_quantile5_20d_pred) +
rank(short_horizon_hedge3_quantile1_5d_pred)`, Sharpe **2.27**, fitness **1.22**, turnover 31%, every year
2018-2023 positive, recent 2-year Sharpe 1.83, sub-universe 1.12 vs 0.98, Power Pool correlation 0.25 -
it passes the regular Sharpe and fitness bars too (`rKdQXaA3`). The LLM proposed it in a refinement round
from the shape list in its prompt. The interaction of the same pair reached 2.08 but trades like it (0.97).

**What else worked** (all confirmed by BRAIN's check, eligible):

| Shape | Data (category) | Sharpe | BRAIN id |
|---|---|---|---|
| combination of two forecasts (5-day event + 120-day) | multifactor_return_pred (model) | 1.66 | `JjPRqLZW` |
| history-relative (vs own last quarter) | bias-free analyst price target (analyst) | 1.37 | `rKdQYQMa` |
| history-relative | analyst82 predicted profitability change (analyst) | 1.35 | `RRA0MZEo` |
| time-series residual (call IV on put IV) | option_chart_model (model) | 1.30 | `pwvQmQZ3` |
| combination of two chart CNNs | chart_cnn_alpha (model) | 1.51 | `d5KepwLg` (trades like `78oOM6av`) |
| trend (slope over a quarter) | analyst82 profitability (analyst) | 1.13 | `YPxX6Xow` (trades like `RRA0MZEo`) |
| change (21-day) | 60-day seasonal forecast (model) | 1.10 | `bl87X3pM` (weak recent 2y) |

**What did not:** orthogonalising forecasts against the submitted 20-day forecast (-0.3: the shared part is
the edge); news-day sentiment updates on three story-sentiment vectors (-0.4 to 0.1); tone x novelty (0.11,
124% turnover); EPS fresh-update, surprise-hold and dispersion on analyst estimates (0.28-0.40); stock-loan
changes (-0.25). News coverage came out with the opposite sign to Fang and Peress (2009).

**Shape diversity is not information diversity.** Most combinations, interactions and transforms of the
vendor forecasts traded like an existing winner (daily PnL correlation 0.6-0.99) and were dropped by the
screen; new information came from different data (analyst targets and profitability, option residuals) or
from pairing a signal with one built to be uncorrelated.

**Takeaways now in the engine's priors:** analyst estimates need history-relative or trend shapes (plain levels
never cleared 0.5); forecasts gain from combinations across horizons; option spreads work as levels and
time-series residuals; one field can carry several uncorrelated alphas through different shapes (the call-put
spread as a size-weighted level and as a time-series residual are below 0.5 correlated, both eligible).

## Round 2: why there were zero submittable alphas, and what changed

**Why.** The first round spent ~30 of ~120 simulations on settings and wrapper variants of two signals
(`rank(mdl25_8v)` and the corporate event scores). Variants of the same fields trade the same positions: once
`npA00Roq` (`rank(mdl25_8v)`) was submitted, every sibling failed `POWER_POOL_CORRELATION` (0.81 > 0.5), and the
event scores could never pass the sub-universe test (0.21-0.25 vs a ~0.7 limit). Settings cannot fix either.

**What changed in the engine** (`p2a/engine/lifecycle.py`, `explorer.py`; rules in `config.yaml`):
- Ideas are budgeted as *families* (the set of data fields). Weak, illiquid, crowded, already-submitted and
  plateaued families are dropped from the evidence; a family with a submittable alpha is closed ("winner").
- Settings change only to fix one specific failed check, once; LLM refinement must change the expression.
- Daily PnL of every candidate is compared with your submitted alphas before spending a BRAIN check; this caught
  a 1.64 and a 1.30 Sharpe alpha that traded like `leMx5kZ8` (0.84) and another submitted alpha (0.72).
- New probes come from the theme's high-value, low-crowding datasets (BRAIN's `valueScore` / `alphaCount`).
- Sub-universe near-misses get one size-weighted variant `(rank(x) - 0.5) * rank(size)` using a size field
  from the same data category (found by description), which keeps single-category themes matched.

**Results (87 simulations, about 45 families, one probe each unless promising; 5 free-LLM requests).**

| Family (dataset) | Best Sharpe | Outcome |
|---|---|---|
| `predicted_return_quantile_1` (tech_chart_model) | 2.01 | submitted by you (`MP0welWz`); recent 2y Sharpe 0.91 |
| `short_term_return_pred_r20_q1` (multifactor_return_pred) | 1.81 | submitted by you (`leMx5kZ8`); every year positive |
| `-williams_percent_range_10d` (tech_chart_model) | 1.28 | submitted by you (`kqJRWk76`) |
| call minus put ATM implied volatility, size-weighted (option_chart_model) | 1.91 | sub-universe fixed by size weighting (`58jRYxjN`) |
| `ts_mean(analyst_60d_regression_pred, 21)` (multifactor_return_pred) | 1.34 | eligible (`78oOM6av`), fitness 1.02 |
| `historic_earnings_surprise_score` (ai_equity_alpha) | 1.26 | eligible (`Vkdn5wz5`) |
| `event_embedding_5d_regression_prediction` (multifactor_return_pred) | 1.16 | eligible (`zqra2QzE`), weak recent 2y |
| `long_term_120d_regression_prediction` (multifactor_return_pred) | 1.44 | eligible (`O0JeV67Y`); Power Pool correlation 0.48, close to the limit |
| put-call parity deviation x call implied volatility (option_chart_model) | 1.13 | eligible (`j2eLxRRE`); turnover 65% |
| `img30d_return_quintile` (chart_cnn_alpha) | 1.20 | eligible, but trades like `78oOM6av` (0.52): not queued |
| `option_quantile5_20d_pred` (multi_source_model) | 1.91 | inverted after a -1.91 probe; sub-universe 0.81 vs 0.83, size weighting did not fix it |
| `img30d_return_bisection_prob1_zackbatch` (chart_cnn_alpha) | 1.43 | sub-universe near-miss even size-weighted |
| `money_flow_index_10d_2` (tech_chart_model) | 1.02 | used: PnL correlation 0.85 with `kqJRWk76` |
| `mid_term_seasonal_adjusted_return_forecast_60d` | 1.64 | used: correlation 0.84 with `leMx5kZ8` |
| analyst 60/120-day forecasts (two datasets) | 1.05-1.12 | one family in practice: correlations 0.95-0.98 |
| revisions, dispersion, ESG-like scores, residual momentum, loan fees, implied skew | < 0.6 | dropped after one probe each |

**Learned about the platform and the data.**
- Regular delay-1 submission now needs Sharpe 1.58 (`LOW_SHARPE` limit) and fitness 1.0; Power Pool needs 1.0.
- For a Power Pool-qualifying alpha BRAIN shows the exempt checks as WARNING, so any FAIL blocks submission;
  `POWER_POOL_CORRELATION` can be a WARNING with a value above its limit, which also disqualifies.
- The sub-universe limit is about 0.43 x the alpha's own Sharpe.
- These model datasets start in 2018, so the in-sample period is 2018-2023.
- In `multi_source_model`, a high `option_quantile5_*` probability predicts *higher* returns (the sign of the
  first probe was wrong; the lifecycle inverts strong negatives once).
- Smoothing short-horizon option and chart signals destroys them (1.68 -> 1.03, 1.34 -> 1.17): their
  information is used up within days.

## Round 1

Scope: USA / TOP3000 / delay 1, Power Pool theme "D1 Power Pool Oct`26 2" (analyst, model or news; single
data category). 23 hypotheses were extracted from the research notes in this folder; 11 were tested on BRAIN
(about 120 simulations including refinement variants).

### Platform rules verified by experiment

1. **Grouping fields count for theme matching.** `group_rank(mdl25_8v, industry)` did not match the theme, while
   `rank(mdl25_8v)` with INDUSTRY neutralization in the settings did. `industry`, `sector`, `subindustry` and
   `market` come from the price-volume dataset and break a single-category theme. They still do not count toward
   the 3-field limit or the pyramid count. The engine now enforces this (`power_pool.theme_counts_grouping_fields`).
2. **The theme match needs the description.** The same alpha failed MATCHES_THEMES without a description and
   passed with one (checks POWER_POOL_DESCRIPTION_LENGTH / _FORMAT). The engine now sets its generated description
   before running the read-only submission check (`power_pool.describe_before_check`).
3. **The Power Pool classification tag is not assigned before submission.** Before submitting, MATCHES_THEMES PASS
   plus passing Power Pool checks is the evidence that an alpha qualifies.
4. Signals that are constant within an industry vanish under INDUSTRY/SUBINDUSTRY neutralization (Sharpe 0.00,
   turnover 0.00 observed). The validator now tracks group-constant signals and moves the neutralization up.
5. NONE neutralization on rank()-style signals produced long-only books (3,056 long / 0 short, 77% drawdown).
   The engine now replaces NONE with MARKET.

### Results by idea

| Idea (notes section) | Data | Best Sharpe | Verdict |
|---|---|---|---|
| Earnings quality / accruals (model 3) | `mdl25_8v` (model25) | **1.11** | **Power Pool eligible** (3 settings variants; crowded signal, prod correlation 0.97) |
| Corporate event scores (found by the engine) | `corporate_structure_event_score`, `earnings_financial_event_score` (event_stock_model) | 1.71 | Real but illiquid: fails sub-universe; TOP1000 Sharpe only ~0.4 |
| Net equity issuance (model 4) | `net_equity_issuance_indicator` (model23) | 0.75 | Near miss |
| Change in earnings-quality rank (model 3) | `mdl25_6v`, `star_eq_region_rank` | 0.68 | Near miss |
| News tone momentum (news 1) | news97 / news73 sentiment | 0.61 | Only as a long-only artifact; balanced versions are weak |
| Predicted earnings surprise (model 1) | model30 `star_new_eps_surprise_prediction_*` | 0.55 | Weak in the tested forms (all used industry group ops; retest without) |
| Revision breadth (analyst 2) | analyst15 up/down estimate counts | 0.40 | Weak |
| Earnings news drift (news 3) | `rp_css_earnings`, `rp_nip_earnings`, `nws18_bee` | 0.35 | Weak |
| Earnings surprise drift (analyst 4) | analyst7 `act_q_*_surprisemean` | 0.17 | Weak, ~1% turnover |
| Low risk: beta / idiosyncratic volatility (model 6) | model51 | 0.09 | No signal in this setup |
| Industry M&A drift (news 4) | news23 acquirer scores by industry | 5.3 (artifact) | Rejected: 715 long vs 3 short, 50% weight in one stock |

### What to try next (round 1)

- Untested hypotheses: news 2, 5, 6, 7, 8; analyst 1, 3, 5, 6, 7, 8; model 2, 5, 7, 8 (`p2a hypotheses` lists them).
- Predicted surprise and revision ideas again, without grouping fields in the expression.
- Corporate event scores: look for a liquid-stock version (the effect lives outside TOP1000).
- Other regions with delay 1 (the theme does not restrict region), e.g. EUR or GLB, after `p2a sync --region ...`.
