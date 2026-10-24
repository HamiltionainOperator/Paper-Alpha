# Round 7: unique alphas from non-price information (17 Oct 2026, USA TOP3000 delay 1)

## The problem

The engine's alphas were mainstream. Composites of popular vendor forecasts reached Sharpe 2.8 but were 0.82 correlated
with production. Round 6's paper ideas on rarely used data were weak alone (best |Sharpe| 1.22), and two of them turned
out crowded anyway (0.90 and 0.93 with production). This round asks why, fixes the engine's construction mistakes, and
builds unique alphas from mechanisms that research documents and few BRAIN alphas use.

Method: 141 lightly used datasets were synced (field lists with per-field alpha counts). Each family was matched to papers
with documented return predictability and written in BRAIN operators chosen for the data's structure. Then:
1. Every expression was validated against the live catalog.
2. Each was simulated once in its paper's form.
3. Each was screened against crowded reference factors, and the best were measured with BRAIN's correlation endpoints.

## Three construction mistakes, measured

**1. Sparse fields traded bare.** Board-network and intangible-capital fields used as `rank(field)` held positions on
only 237 of 2,493 days. BRAIN's dateCoverage said 0.95; the values exist only on update days. The result was Sharpe
0.6-0.7 and a CONCENTRATED_WEIGHT fail. Carried forward with `ts_backfill(x, 252)` they fell to 0.16-0.33 (#434-#437):
the information was an update-day reaction, not a premium to hold. Earnings-call tone shows the opposite case:
- held for 63 days (`ts_backfill`): Sharpe 1.04;
- traded only in the 21 days after each call (event form): 0.61.

A sparse field needs an explicit choice of form, tested once.

**2. "Unique data" that is the stock's own price.** The equity-minus-bond-implied return (pv173, 58 alphas) and ETF
holding growth (model237) are rarely used fields. Yet they were 0.895 and 0.925 correlated with production, because
their values are mostly past returns.
- A local screen against nine crowded reference factors catches this: both trade 0.74-0.75 like short-term reversal.
  The factors are 1/5/21-day reversal, 12-1 momentum, size, low volatility, volume-price, value and EPS revision.
- The proper residual, `s - regression_proj(s, rank(returns))`, had Sharpe -0.26 to 0.21 (#442-#444). The idea *was*
  reversal.
- `vector_neut(s, -rank(returns))` looked like the right operator but is not. It projects without an intercept, so
  against a rank (all values of one sign) it removes a constant. The "neutralized" versions traded *more* like reversal
  (0.80-0.82, #438-#440).

**3. The combiner's estimate dropped flat days.** It averaged only days on which some part traded, which inflated
sparse parts to their active-day Sharpe (an estimated 2.65 pair from two parts of 0.7). It also rejected different
mechanisms that read the same field: the smirk and implied-volatility innovations both read ATM call volatility.

## What the papers' mechanisms did on BRAIN's data

| family | paper | field (alphas on BRAIN) | Sharpe | note |
|---|---|---|---|---|
| option smirk | Xing, Zhang and Zhao (2010) JFQA | opt3 OTM put IV - ATM call IV (33/117) | **1.80** | 0.07 with the crowded ATM call-put spread; turnover 56% |
| lending tightness | Engelberg, Reed and Ringgenberg (2018); D'Avolio (2002) | change in loan utilization (140) | **1.43** | sign opposite to Cohen, Diether and Malloy (2007); reference exposure 0.27 |
| call answer tone, leverage | Price et al. (2012); Matsumoto et al. (2011) | mean_polarity_leverage_answer (7) | **1.10** | 0.09-0.34 with the other tones |
| call answer tone, asset utilization | same | (10) | 1.08 | 0.67 with profitability tone |
| analysts' leverage questions | Chen, Nagar and Schoenfeld (2018) RAST | mean_polarity_leverage_question (7) | 1.07 | illiquid |
| call answer tone, profitability | same | (14) | 1.04 | production correlation **0.654** |
| lending-fee volatility | Engelberg, Reed and Ringgenberg (2018) JF | loan_rate_volatility (93) | 0.99 | 0.76 like low volatility: a factor in disguise |
| IV innovations | An, Ang, Bali and Cakici (2014) JF | change in ATM call minus put IV (117/51) | 0.95 | works in liquid stocks (sub-universe ratio 0.69) |
| tone against own history | Davis, Ge, Matsumoto and Zhang (2015) | z-score of answer tone | 0.94 | |
| analysts' questions, 5 topics | Chen, Nagar and Schoenfeld (2018) | (0-7 each) | 0.90 | |
| cash-flow / valuation answer tone | Price et al. (2012) | (6 / 7) | 0.88 / 0.79 | one factor with profitability tone |
| call skew (lottery) | Conrad, Dittmar and Ghysels (2013) JF | OTM - ATM call IV | 0.60 | |
| numbers in answers | Dzielinski, Wagner and Zeckhauser (2017) | (4) | 0.50 | |
| short answers / non-answers | Gow, Larcker and Zakolyukina (2021) JAR | q/a word ratio (0) | -0.47 | |
| lendable supply growth | Prado, Saffi and Sturgess (2016) RFS | available shares (112) | -0.84 | agrees with lending tightness |
| no signal (\|Sharpe\| < 0.5) | Green et al. (2019); Huang, Li and Markov (2020); Belo, Lin and Bazdresch (2014); Cohen, Malloy and Pomorski (2012); Jegadeesh and Livnat (2006); McNichols and O'Brien (1997); Diether, Malloy and Scherbina (2002); Johnson and So (2012); Pan and Poteshman (2006); Bali and Hovakimian (2009); Cohen, Polk and Silli (2010); Chen, Hong and Stein (2002); So (2016); Cohen and Frazzini (2008); Heston and Sinha (2017); Drechsler and Drechsler (2014); Ham et al. (2017); Bushee, Gow and Taylor (2018) | employee reviews, workforce flows, insider ratios, sales revisions / coverage / dispersion / surprise, option volume ratios, implied vs realized volatility, fund best ideas, breadth, earnings-date timing, network momentum, aggregated news sentiment, fee changes, CFO pronouns, CEO obfuscation | -0.47 to 0.45 | |

Most published mechanisms do not survive on these vendor fields in 2014-2023. The ones that do share a trait: they
measure **private information while it is being revealed**, through the option market, the lending market or managers'
unscripted words.

## The composite

The surviving channels are nearly independent: daily PnL correlations run from -0.11 to 0.34, mostly about 0.1.
Joined NaN-safe as one score per stock:

```
add(rank(-(ts_backfill(opt3_volputotmb, 5) - ts_backfill(opt3_volcallatm, 5))) - 0.5,
    rank(ts_backfill(mean_polarity_profitability_answer, 63)) - 0.5,
    rank(ts_backfill(mean_polarity_leverage_answer, 63)) - 0.5,
    rank(ts_delta(ts_backfill(vec_avg(loan_utilization_ratio), 21), 21)) - 0.5, filter=true)
```

**#486 (3qjnAo86)** results, SUBINDUSTRY, decay 4:

| measure | value | bar |
|---|---|---|
| Sharpe | **2.58** | 1.58 |
| fitness | **1.34** | 1.0 |
| turnover | 24% | 1-70% |
| IS ladder | 2.77 | 2.02 |
| production correlation | **0.655** (151 production alphas above 0.5) | below 0.7 |
| self correlation | 0.396 | below 0.7 |
| largest reference-factor exposure | 0.32 | |
| sub-universe Sharpe | **1.01, fails** | 1.12 |

The sub-universe test fails because lending tightness and leverage tone live in illiquid stocks: their TOP1000 Sharpe is
0.24-0.35 of their full Sharpe, against the 0.433 required. Fixes that add liquid-stock signal (IV innovations) are in the
next section.

## Sub-universe fixes, and the submittable alpha

Implied-volatility innovations (An, Ang, Bali and Cakici 2014) work in liquid stocks: sub-universe ratio 0.69, and
-0.07 to 0.08 correlated with every other channel. Three constructions targeted the one failing test:

| # | construction | Sharpe | fitness | turnover | sub-universe | result |
|---|---|---|---|---|---|---|
| **493** (d5KlxOVj) | five channels, equal weights | **2.63** | **1.20** | 32% | 1.14 vs 1.14 | **passes every test** |
| 494 (d5KlxOVv) | five channels, lending and leverage tone at half weight | 2.48 | 1.04 | 38% | 1.21 vs 1.07 | passes every test |
| 495 | #493 with BRAIN's liquidity-split decay | 2.49 | 1.34 | 22% | 1.02 vs 1.08 | fails |

**#493 passed BRAIN's submission check.** Every regular test passed:

| test | value | limit |
|---|---|---|
| Sharpe | 2.63 | 1.58 |
| fitness | 1.20 | 1.0 |
| sub-universe Sharpe | 1.14 | 1.14 |
| IS ladder | 2.77 | 2.37 |
| self correlation | 0.386 | 0.7 |
| production correlation | **0.630** (71 production alphas above 0.5) | 0.7 |

Data diversity and the regular-submission quota (0 of 4) also passed. It matches the OTHER (x1.4), OPTION (x1.3) and
SHORTINTEREST (x1.1) pyramids. The cluster test is only a warning. #494 is the more robust sibling (sub-universe
margin 13%, production correlation 0.641); both are one family, so submit one.

```
add(rank(-(ts_backfill(opt3_volputotmb, 5) - ts_backfill(opt3_volcallatm, 5))) - 0.5,
    rank(ts_backfill(mean_polarity_profitability_answer, 63)) - 0.5,
    rank(ts_backfill(mean_polarity_leverage_answer, 63)) - 0.5,
    rank(ts_delta(ts_backfill(vec_avg(loan_utilization_ratio), 21), 21)) - 0.5,
    rank(ts_delta(ts_backfill(opt3_volcallatm, 5), 21) - ts_delta(ts_backfill(opt3_volputatm, 5), 21)) - 0.5,
    filter=true)                                   # USA TOP3000 D1, SUBINDUSTRY, decay 4, truncation 0.08
```

The sub-universe ratio of a combination is predictable from its parts. It is sum(w x part sub-universe Sharpe) /
sum(w x part Sharpe):

| alpha | estimated ratio | measured |
|---|---|---|
| #486 | 0.39 | 0.39 |
| #493 | 0.435 | 0.433 |
| #494 | 0.47 | 0.49 |

The combiner now uses this estimate.

## Sharpe 3 is reachable, but not with a crowded part

With the combiner fixed, the engine itself proposed two six-part composites that also held residual reversal (a
pv20 risk-model signal). They reached **Sharpe 3.00 and 3.04** (fitness 1.66 and 1.70; estimates 2.96 and 2.97) and
passed the sub-universe test with margin. Their production correlation was **0.826 and 0.830**, with 31,551 and 35,573
production alphas above 0.5. One crowded part is not diluted away: production holds thousands of alphas that mix
reversal with other signals.

The parts that cause this are visible beforehand. They correlate |0.69-0.80| with a reference factor:
- residual reversal: 0.80 with five-day reversal;
- salience: -0.69 with 21-day reversal;
- tone gap: -0.80 with low volatility.

The parts of #493 are 0.17-0.52. The combiner now keeps parts at |0.6| or above out of regular-route combinations,
and assumes almost no dilution of production correlation (prod_dilution 0.05).

## What the engine does now

- **`p2a references`** and the run cycle's exposure step (`p2a/engine/references.py`, `uniqueness.references`).
  - Nine crowded factors are simulated once; every new alpha's PnL is correlated with them.
  - At 0.6 or above, the uniqueness step does not spend an hourly correlation request on the alpha.
  - The combiner's production prior rises with the exposure.
- **Residual test** (lifecycle remedy `orthogonalize`, `refiner.residual_code`). An idea that trades like a reference
  factor gets one `s - regression_proj(s, factor)` variant. If the residual has no signal, the family is dropped with
  the reason.
- **Construction playbook** (`research/operator_playbook.yaml`, `p2a/engine/playbook.py`). Rules are chosen by field
  type, category and update frequency and placed in the generate and refine prompts:
  - sparse persistent vs event form, and vector reduction;
  - consensus snapshot revisions and disagreement ratios;
  - residuals with intercept, NaN-safe composites, trade_when and hump;
  - the sub-universe liquidity split;
  - plus the uniqueness and fitness techniques with this account's measurements.
- **Mechanisms** (`research/mechanisms.yaml`): iv_smirk, iv_innovation, lending_tightness, leverage_answer_tone and
  leverage_question_tone. Their roles resolve to the right live fields from descriptions alone. A combine group,
  `informed_channels` in `research/shapes.yaml`, lets the combiner join them.
- **Combiner fixes**:
  - flat days are kept in estimates;
  - parts that trade on fewer than half the days are skipped;
  - different mechanisms may share a field;
  - illiquid parts join at half weight, and each combination's sub-universe test is estimated from its parts;
  - the search grows toward combinations that can pass that test;
  - parts that trade like a crowded factor stay out of regular combinations;
  - composites already simulated by hand count as tried.

## Next

- #493 or #494 is a production submission for today; the choice is yours. Neither is Power Pool eligible (18-20
  operators, 6 fields).
- Each channel would keep this result from being a one-off if it got a second, independent measure. Liquid-stock
  signals help most, because the sub-universe test is the binding constraint. Candidates:
  - more option-surface information from expected_move and option_horizon_decomp, with no alphas;
  - analysts' Q&A tone by topic, which is partly independent.
- Run `p2a references` after each batch. It costs no correlation requests, and it caught every crowded idea this
  round.

## Round 8 (18 Oct 2026): after #499 and #516 were submitted

Two alphas from this research are now in production:

| alpha | Sharpe | fitness | production correlation | self correlation |
|---|---|---|---|---|
| #499 (N1e5bMgX) | 2.58 | 1.12 | 0.659 | |
| #516 (WjLW22OZ) | 2.29 | 1.14 | 0.694 | 0.506 with #499 |

#499 is six channels, built by the engine. #516 is leverage tone (presentation and answers), IV innovations, falling
lendable supply, rising utilization, customers' OTM option flow and profitability answer tone. Every new alpha must now
stay below 0.7 with both.

**New channels.** For the "unique" column: production correlation, the PnL correlation with #499, and the reference
exposure, where measured.

| signal | paper | Sharpe | sub ratio | unique |
|---|---|---|---|---|
| leverage presentation tone | Davis, Piger and Sedor (2012) | **1.24** | 0.64 | prod 0.715 (7,911 above 0.5): a quality-like common factor |
| falling lendable supply | Engelberg, Reed and Ringgenberg (2018) | 0.84 | 0.27 | 0.15 with rising utilization: a separate channel |
| customers' OTM option flow | Pan and Poteshman (2006) | 0.58 | 0.21 | -0.16 with #499 |
| borrow-demand score change | (lending channel) | 0.93 | 0.04 | illiquid |
| OTM call-put open-interest growth | Fodor, Krieger and Doran (2011) | 0.95 | 0.52 | investability-constrained Sharpe 0.08 |
| closing-auction dislocation reversal | Bogousslavsky and Muravyev (2023) | 0.93 | -0.30 | lives only in illiquid stocks |
| Alexandria call sentiment | | 0.72 | 0.53 | 0.67 with other answer tones |

**Measured production correlation of the parts** (BRAIN endpoints):

| part | production correlation | production alphas above 0.5 |
|---|---|---|
| IV innovations | **0.509** | 1 |
| leverage answer tone | 0.650 | 9 |
| profitability answer tone | 0.654 | 104 |
| leverage presentation tone | 0.715 | 7,911 |
| utilization change | 0.755 | 53 |

The changes of the option surface are the most unique information found.

**Failed (|Sharpe| below 0.6)**, papers in brackets:
- option order flow by trader class (Pan and Poteshman; Hu 2014): firm and broker-dealer flow even reversed;
- takeover likelihood (Cremers, Nair and John 2009);
- abnormal search (Da, Engelberg and Gao 2011): 106% turnover;
- TipRanks retail flow (Boehmer et al. 2021);
- IV term-structure level and change (Vasquez 2017);
- 8-K NLP scores (Lerman and Livnat 2010);
- aggressive and book-sweeping order imbalance (Chordia and Subrahmanyam 2004; Cao, Hansch and Wang 2009);
- volume surprise (Gervais, Kaniel and Mingelgrin 2001);
- laughter on calls (Call, Flam, Lee and Sharp 2023): -0.48 at delay 1, the paper's call-window effect does not drift;
- other vendors' Q&A tone;
- the smirk's and OTM spread's changes: the spread change failed BRAIN's investability test.

In EUR, call tones reach 1.0-1.16 alone, but their composite only 1.17: without option and lending data the
independent channels are missing.

**Lowering production correlation of a composite** (#518, 0.694, value tilt 0.31, momentum -0.24):

| construction | Sharpe | fitness | production correlation | sub-universe |
|---|---|---|---|---|
| SUBINDUSTRY (#518) | 2.29 | 1.14 | 0.694 | passes |
| CROWDING (#519) | 1.44 | 0.79 | | |
| STATISTICAL (#520) | 2.37 | 1.05 | **0.563** (3 above 0.5) | fails (0.77 vs 1.03) |
| value regressed out (#525) | 2.19 | 1.05 | **0.5-0.6** apart from #516 | passes |
| value and momentum regressed out (#526) | 2.07 | 0.97 | | passes |

These became `p2a decrowd` (regression on the factors an alpha tilts toward). The uniqueness step uses it on eligible
alphas above `regular.prod_corr_target` (0.65). #520 and #525 cannot be submitted: they are variants of the
submitted #516 (self correlation 0.70 and 0.95).

**Engine changes this round:**
- Parts that drive a submitted alpha stay out of combinations (`combine.part_max_submitted_corr`: the smirk is 0.75
  like #499).
- UNITS warnings are informational, as BRAIN says they do not prevent submission. Templates use unitless ratios
  (supply / supply 21 days ago instead of log(shares)).
- `p2a validate --route regular` checks against the production limits.
- `regular.max_fields` is 12. BRAIN sets no field limit for regular alphas, and factor residuals need two or three
  fields.
- Every reference-factor exposure is stored per alpha (`ref_exposures`).
- New mechanisms: leverage_presentation_tone, lendable_supply_decline, customer_otm_option_flow.

**Next.** A third production alpha needs new channels that are both liquid and unique. The option surface is the most
promising: its changes were the most unique information found (IV innovations, 1 production alpha above 0.5).
Candidates:
- option_horizon_decomp's 500 untouched fields: breakeven prices and moneyness by horizon;
- expected_move's implied moves.

## Round 9 (19 Oct 2026): the third production alpha, and why a fourth is hard

**Submitted today.** #605 (6XAzWNYO), built from the channels below. It is unique against other users' alphas (only
six production alphas in the 0.6-0.7 band apart from #499), but close to #499: it shares four of #499's channels.

```
add(0.5 * (rank(ts_delta(ts_backfill(vec_avg(loan_utilization_ratio), 21), 21)) - 0.5),
    0.5 * (rank(ts_backfill(mean_polarity_leverage_answer, 63)) - 0.5),
    rank(ts_delta(ts_backfill(opt3_volcallatm, 5), 21) - ts_delta(ts_backfill(opt3_volputatm, 5), 21)) - 0.5,
    rank(ts_zscore(ts_backfill(mean_polarity_profitability_answer, 63), 252)) - 0.5,
    0.5 * (rank(ts_backfill(mean_polarity_leverage_question, 63)) - 0.5),
    0.5 * (rank(-(ts_mean(short / total volume, 5) - ts_mean(short / total volume, 63))) - 0.5),
    rank(ts_delta(ts_backfill(vec_avg(rsk59_last_rate), 21), 21)) - 0.5, filter=true)     # SUBINDUSTRY, decay 4
```

| measure | value |
|---|---|
| Sharpe | 2.37 |
| fitness | 1.06 |
| production correlation | 0.667 (the maximum is the user's own #499) |
| self correlation | 0.667 with #499, 0.50 with #516 |

**About 85 probes today.**

Failed (|Sharpe| below 0.7):
- option-implied borrow fee from forward prices (Muravyev, Pearson and Pollet 2025): the vendor forward is not the
  parity forward;
- IV rank, 90-day IV innovations and put/call ratios;
- management guidance surprise, width and revisions (Kasznik and Lev 1995; Baginski et al. 1993);
- management quality;
- KPI-forecast surprise;
- the sustainable-profitability library (Bradshaw et al. 2006; Akbas et al. 2017; Ball et al. 2016; Penman and Zhang
  2002; Hirshleifer et al. 2004);
- lending fee dispersion, loan growth, loan duration and transaction growth;
- order-flow trade counts by class;
- most speaker-level call sentiment.

New parts (TOP1000 Sharpe = the sub-universe value):

| part | Sharpe | TOP1000 Sharpe | note |
|---|---|---|---|
| cash-flow presentation tone | 1.04 | 0.83 | |
| own-history profitability tone | 0.94 | 0.74 | |
| rising spot lending fee | 0.90 | 0.54 | |
| S3 utilization change / availability decline | 0.89-0.91 | 0.3 | 0.5-0.6 with utilization |
| long-dated skew (inverted) | 0.77-0.86 | 0.3 | |
| inverted squeeze risk (crowded shorts underperform) | 0.80 | 0.59 | |
| CEO Q&A positive tone | 0.82 | 0.43 | |

**What blocked a fourth alpha:**

| attempt | Sharpe | fitness | blocked by |
|---|---|---|---|
| clean parts only (F, F2) | 1.54-1.68 | 0.73-0.91 | weak parts; the best clean set estimates 1.77 even at self 0.70 |
| strong parts back in at reduced weight (H1, H2) | 2.06-2.19 | 1.08-1.18 | **production correlation 0.77**: the composites traded 0.50-0.53 like a crowded factor although no part did alone |
| H3 | 2.40 | 1.11 | sub-universe (0.98 vs 1.04) |
| #605 de-tilted (size and volume-price regressed out) | 2.39 | 1.03 | sub-universe (0.95 vs 1.03); self with #499 fell 0.667 -> 0.617 |
| TOP1000 composites of the liquid parts | 1.07-1.31 | 0.52-0.58 | Sharpe: the liquid stocks keep about half |

**The combiner's estimate, recalibrated** on 11 composites:
- Adding the parts' PnL as simulated (a rank sum gives equal positions, so each part counts with its own volatility)
  erred by 0.05 Sharpe on average.
- Scaling each part to unit volatility erred by 0.12, and by 0.41 on F2.
- The turnover haircut made both worse.

**Engine changes:**
- `combine.estimate_scaling: position`, with the turnover haircut set to 0. The sub-universe estimate is weighted by
  PnL volatility (error 0.017 on 9 composites).
- Combinations whose PnL trades 0.45 or more like a reference factor are skipped (`combine.max_ref_corr`).
- Combinations must stay below `combine.max_submitted_corr` (0.6) with every submitted alpha.
- `regular.max_operators` is 60 and `max_fields` 14. BRAIN sets no limits; decrowd's variant needed 43 operators.
- New mechanisms: short_crowding, call_tone_surprise, iv_rank_fear.

**Next.** All three production alphas draw on the same families: option surface, lending, call tone. A fourth that is
truly unique needs a new family of private information, with parts of Sharpe 1+ that work in liquid stocks. The
candidates with documented mechanisms still untested on BRAIN are:
- delay-0 versions of the option channels (fresher information; a separate D0 category);
- other regions with option and lending coverage.
