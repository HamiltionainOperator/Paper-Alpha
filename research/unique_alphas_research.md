# Unique alphas for production and the Power Pool (research round 4, 16 Oct 2026)

Question: the four Power Pool alphas submitted on 15 Oct paid very little. How do we make alphas that are
submittable as **regular (production) alphas** as well as Power Pool alphas, and that are **unique** (low
production correlation)? Sources: BRAIN's own API and Learn pages (synced into the engine), the academic
literature, and this account's own simulations and checks.

## 1. What BRAIN reports about the payment

| | what BRAIN shows | source |
|---|---|---|
| base payment 15 Oct (4 Power Pool alphas) | $1.15 | `/users/self/activities/base-payment` |
| base payment late June (regular alphas) | $50-60 a day | same |
| production correlation of the 4 submitted PP alphas | 0.79-0.85 (others 0.99 for `mdl25_8v`) | submission checks |
| pyramid multiplier USA/D1/MODEL | x1.3 | `MATCHES_PYRAMID` on every alpha |
| Power Pool theme multiplier | x1.0 | `MATCHES_THEMES` |
| "USA/D1 TOP1000 Theme" | x2.0, missed (alphas were TOP3000) | `MATCHES_THEMES` |
| Osmosis allocation | WARNING: none set | `OSMOSIS_ALLOCATION` |
| quotas today | pure Power Pool 1 a day, regular 4 a day | `POWER_POOL_SUBMISSION`, `REGULAR_SUBMISSION` |

BRAIN does not publish how these combine into a payment. What its Learn pages do say:

- **Daily Osmosis Rank** is "applied as a quality factor multiplier for your daily base payment", between 1 and
  2. It needs points allocated in at least 3 scopes (region x delay), each with exactly 100,000 points over at
  least 10 alphas. This account has alphas in USA D1 (about 60) and GLB D1 (1), so it gets no Osmosis multiplier.
  (Osmosis Allocation Guide)
- **Dynamic pyramid multiplier**: "lower utilization resulting in a higher multiplier"; visible per dataset and
  per alpha. USA D1 now: other x1.4, sentiment x1.4, option x1.3, model x1.3, analyst / news / earnings x1.2,
  price-volume / fundamental x1.1. Other regions run higher (CHN, DEU, GBR, JPN up to x1.9; EUR D1 up to x1.5).
  (`/users/self/activities/pyramid-multipliers`; Overview of Themes)
- **Pure Power Pool quotas fall over time**: 4 a day in weeks 1-2, then 2, then 1 a day plus 10 a month per scope
  after week 6, and they must match the theme. An alpha that is also Regular or ATOM is not counted.
  (Power Pool Alphas)
- **"Generally, low correlation is more important than minor increase in performance."** (Clear these tests
  before submitting an Alpha)
- USA is the most crowded region: "it may be hard to beat production correlation in USA". (Finding Consultant
  Alphas)

So yesterday's alphas were low-value on every lever BRAIN documents. They were pure Power Pool alphas (theme
x1.0) built on popular forecasts (production correlation about 0.8), with no Osmosis allocation, and they are
not regular alphas.

## 2. The regular (production) tests

From Consultant Submission Tests and the checks on this account: Sharpe >= 1.58 and fitness >= 1.0 for delay 1;
turnover 1-70%; max weight < 10%; sub-universe Sharpe >= 0.75 x sqrt(1000/3000) x Sharpe; the 2-year Sharpe and
IS ladder (2.38 pass / 1.58 fail for the most recent 2-5 years, x0.85 below 30% turnover). Single-dataset ATOM
alphas may skip the ladder but not the 2-year test. Self-correlation must be < 0.7. **Production correlation** is
"the maximum correlation with any BRAIN consultant Alpha" of daily PnL, and it too must be < 0.7, or the Sharpe
must be 10% above every alpha it exceeds 0.7 with. Fitness = Sharpe x sqrt(|returns| / max(turnover, 0.125)), so
returns per unit of turnover matter as much as Sharpe.

## 3. What the literature says about uniqueness

- **Known signals decay once many trade them.** McLean and Pontiff (2016, JF) studied 97 published predictors:
  returns are 26% lower out of sample and 58% lower after publication. The gap is attributed to investors trading
  on the published idea.
- **Most characteristics are the same few factors.** Green, Hand and Zhang (2017, RFS) found that only 12 of 94
  characteristics give independent information in non-microcaps, and just 2 since 2003. A new rank of a textbook
  field is very likely a copy.
- **Crowded positions carry tail risk.** Brown, Howard and Lundblad (2022, RFS) show that funds exposed to crowded
  stocks lose more in industry distress. BRAIN's CROWDING risk set targets exactly that exposure.
- **Combining weakly correlated signals.** The Sharpe of an equal-risk sum of n signals is about sum(S_i) /
  sqrt(n + 2 sum(rho_ij)). Grinold and Kahn's fundamental law; Kakushadze and Yu (2016), "How to combine a
  billion alphas"; Kakushadze (2016), "101 Formulaic Alphas" (average pairwise correlation 15.9%).
- **Forecast combination.** Forecasts from different models make partly independent errors, and averaging them
  beats most single forecasts. Timmermann (2006); Rapach, Strauss and Zhou (2010, RFS); Gu, Kelly and Xiu
  (2020, RFS).
- **Risk-factor neutralization.** "If an alpha's return can be fully explained by these well-documented risk
  factors, it does not bring any additional value". BRAIN's SLOW / FAST / SLOW_AND_FAST / RAM / STATISTICAL /
  CROWDING sets remove those exposures (Risk Neutralized Alphas; Roll and Ross 1980; Fama and French 1993).
- **Short realization horizon.** The production pool is dominated by 20-40+ day horizons, and "Alphas with short
  realization horizon are naturally orthogonal to the existing daily pool" (Understanding PnL Realization
  Horizon; High Turnover Alphas).
- **What not to do.** "DO NOT incorporate noise in the Alpha to reduce production correlation"; "DO NOT add an
  existing Alpha from one data source to enhance the signal from another data source without any strong
  economic sense." (Consultant Dos and Don'ts)

## 4. Measurements on this account

**4.1 Production correlation follows the data.** These are the 22 alphas with a measured production
correlation, grouped by dataset. Dataset alpha counts come from the BRAIN catalog.

| dataset (alphas on BRAIN) | measured production correlation | shapes |
|---|---|---|
| option_chart_model (108) | 0.69 | residual |
| multi_source_model (289) | 0.61, 0.71, 0.75 | spread, interaction, combination |
| chart_cnn_alpha (300) | 0.76, 0.78 | level, combination |
| multifactor_return_pred (451) | 0.63, 0.67, 0.69, 0.79, 0.81, 0.86 | level x4, combination, change |
| biasfree_analyst (485) | 0.80 | change |
| tech_chart_model (520) | 0.85 | level |
| analyst_revision_horizons (699) | 0.96 | level |
| analyst82 (3,605) | 0.81, 0.91 | trend, change |
| model25 (15,631) | 0.97, 0.99, 1.00 | level |

The engine's crowding prior is fitted on these values: production correlation of about 0.45 + 0.13 x
log10(1 + alpha count). It is used only to rank combination ideas until BRAIN measures the real value.

**4.2 What does not predict it.** BRAIN's own risk-neutralized Sharpe (`is.riskNeutralized`, reported with every
simulation) is unrelated to production correlation: r = 0.02 for the ratio of risk-neutralized Sharpe to Sharpe.
Factor exposure is not what makes these alphas copies; the shared data is. Turnover is related (r = -0.59), with
slow alphas more crowded, as BRAIN's horizon page says.

**4.3 Risk-factor neutralization lowers it** (4 alphas, one variant each, factor set chosen by turnover):

| signal | original | variant | Sharpe | production correlation | production alphas >= 0.5 |
|---|---|---|---|---|---|
| call-put implied-vol spread x size | INDUSTRY | FAST | 1.91 -> 1.72 | 0.827 -> 0.752 | 1,180 |
| chart-CNN forecast combination | SUBINDUSTRY | CROWDING | 1.51 -> 1.45 | 0.785 -> **0.687** | 22,089 |
| analyst 60-day forecast, smoothed | SUBINDUSTRY | SLOW | 1.34 -> 1.43 | 0.863 -> 0.746 | 14 |
| bias-free price target vs its last quarter | INDUSTRY | SLOW | 1.37 -> 1.51 | 0.803 -> **0.679** | 8 |

Production correlation fell by 0.08-0.12 at about the same Sharpe. Two of the four crossed below 0.7, and the
analyst signals sit in nearly empty neighbourhoods (8-14 production alphas above 0.5). The costs are lower
returns, which hurt fitness, and a weaker liquid sub-universe in 3 of 4. The engine therefore uses it as one
"decorrelate" variant per crowded family, not as a search dimension.

**4.4 TOP1000 (the x2.0 theme) is out of reach for these signals.** The same seven signals simulated in TOP1000
kept only 0.46-0.74 of their TOP3000 Sharpe (1.91 -> 0.89, 1.51 -> 0.91, 1.44 -> 1.06, 1.37 -> 0.71). Clearing 1.58
in TOP1000 needs a signal whose liquid half alone is that strong. The engine therefore builds regular alphas in
TOP3000 by default; `regular.universe: auto` switches to a theme universe when one is wanted.

**4.5 Little-used data is not automatically good data.** Two exploration rounds probed the least-used,
highest-multiplier datasets.
- USA "sentiment" and "other" (x1.4): 12 headline-sentiment, negative-word, Loughran-McDonald and TextBlob probes.
  10 of 12 stayed below Sharpe 0.6. Plain negative sentiment (`average_negative_sentiment_score_2`) reached 1.11,
  but at 162% turnover. Event-gated shapes failed on every sentiment vector, so sentiment is now probed as a
  plain level first.
- EUR TOP2500: 12 probes on its least-used datasets, all below 0.8.
- Ports of USA winners to EUR: 5 of 6 used field names that do not exist there; the validator caught them before
  any simulation. The one that could run, the 5-day event + 120-day forecast pair, fell from 1.66 to 0.66.

Field-level crowding in EUR is near zero (0-10 alphas per field), but the signal has to be found field by field.

**4.6 Combinations** (`p2a combine`): see section 6.

## 5. What the engine does now

- **Two routes.** Every simulated alpha gets a Power Pool verdict and a regular verdict (`reg_status`). Every
  regular test must PASS, and BRAIN's WARNING on a Power Pool-exempt test counts as a failure for regular. Each
  route has its own lifecycle bar: 1.0 for Power Pool, 1.58 for regular. The regular route has no theme and no
  category limit, but stays simple: at most 10 operators and 4 fields.
- **Fast uniqueness screen.** `/alphas/{id}/correlations/prod` and `/self` return the production and
  self-correlation in seconds. The slow `/check` only reports them once these have been computed, which is why
  checks used to sit at PENDING for 10+ minutes. `p2a uniqueness` measures the strongest unmeasured candidates,
  and `p2a check` calls both endpoints before the check.
- **Combiner.** Parts are single-idea alphas with Sharpe >= 0.8, a sound sub-universe and no artifacts.
  Combinations of 2-3 parts are estimated from the daily PnL BRAIN already reported, each part scaled to unit
  volatility. A combination is simulated only when it:
  - uses data kinds that share a mechanism (`combine_groups`: informed trading, forecast ensemble, fundamental
    momentum, attention and sentiment, forecast plus informed demand, quality and low risk);
  - has parts correlated at most 0.5 with each other;
  - has an estimated Sharpe >= 1.1 x the bar;
  - does not trade like a submitted alpha.

  Each candidate is ranked by estimated Sharpe x pyramid multiplier x (1 - diluted production correlation).
- **Crowded families** on the regular route get one "decorrelate" step: a risk-neutralized variant (SLOW below
  15% turnover, CROWDING in between, FAST above 40%) plus LLM variants that keep the idea with less-used data.
  If that does not work, the family is closed for production.
- **Exploration on the regular route** ranks every category's datasets by value score x coverage x pyramid
  multiplier / log(alpha count). The least-used data is where uniqueness comes from.
- **Prompts** carry route-specific rules: the regular bars, the fitness formula, what production correlation
  is, what makes an alpha unique, and BRAIN's "no noise, no unrelated stacking" rule.
- **Two queues**, ordered by Sharpe x multipliers x (1 - production correlation). Power Pool rows that also pass
  every regular test are marked "Power Pool + Regular".

## 6. Combination results (8 combinations of existing parts, 16 Oct)

The combiner's first step used only alphas this engine had already simulated. "est." is the estimate from the
parts' daily PnL before calibration.

| # | parts (data kind) | est. Sharpe | Sharpe | fitness | turnover | prod corr | verdict |
|---|---|---|---|---|---|---|---|
| 299 | option forecast + 120d-20d forecast spread + short-term forecast z-score (forecasts) | 2.43 | **2.40** | **1.24** | 28% | **0.688** | **regular: eligible (BRAIN check PASS on every test)** |
| 298 | option forecast + 120d forecast + short-term forecast z-score | 2.47 | 2.44 | 1.27 | 28% | 0.730 | prod corr; 0.98 PnL-correlated with #299 |
| 303 | price-target revision + profitability revision + chart forecast | 2.22 | 2.17 | 1.45 | 18% | 0.716 | prod corr (one CROWDING variant queued) |
| 304 | price-target revision + profitability revision + 50-day image forecast | 2.20 | 1.97 | 1.02 | 28% | 0.848 | prod corr |
| 300 | implied-vol spread + chart forecast + predicted-return z-score | 2.56 | 2.17 | 0.80 | 45% | 0.682 | fitness |
| 302 | implied-vol spread + predicted-return z + option forecast z | 2.29 | 1.95 | 0.64 | 81% | - | turnover, fitness |
| 301 | option forecast z (5d) + 120d forecast + 60d forecast change | 2.26 | 1.53 | 0.45 | 59% | - | Sharpe, fitness |
| 305 | implied-vol residual + earnings-surprise score | 1.77 | 1.48 | 0.64 | 33% | - | Sharpe, fitness |

#299 (`d5Ke6EpE`) passes the IS ladder (2.07 vs 2.02), the liquid sub-universe (1.43 vs 1.04) and self-correlation
(0.45). Every year 2018-2023 is positive (3.83, 1.34, 3.75, 2.61, 2.29, 1.17), and the investability-constrained
Sharpe is 2.03. It is a regular alpha but not a Power Pool alpha, because it uses 4 fields.

**Second batch** (recalibrated estimates; #299 counted as submitted, so new combinations must stay below 0.7
self-correlation with it):

| # | parts | est. Sharpe | Sharpe | fitness | turnover | status |
|---|---|---|---|---|---|---|
| 339 | implied-vol spread + chart forecast + short-term forecast z-score | 2.15 | **2.60** | **1.19** | 36% | every computed test PASS; correlations pending |
| 340 | short-term forecast z-score + analyst 120-day forecast + implied-vol spread | 2.07 | **2.19** | **1.06** | 37% | every computed test PASS; correlations pending |
| 338 | option forecast + price-target revision + smoothed chart forecast | 2.15 | **1.86** | **1.07** | 22% | every computed test PASS; correlations pending |
| 337 | option forecast + price-target revision + chart forecast | 2.23 | 1.18 | 0.38 | 26% | bug: a three-way neutralization tie fell to a part's SLOW setting; fixed |

**Status at 16:35.** BRAIN's correlation service answers only a few requests an hour, and measurements arrive
slowly.

| # | BRAIN | Sharpe | fitness | status |
|---|---|---|---|---|
| 299 | `d5Ke6EpE` | 2.40 | 1.24 | **submitted** (production) |
| 340 | `58jNX1O6` | 2.19 | 1.06 | production correlation 0.736: fails 0.7 |
| 338 | `E5VodMwR` | 1.86 | 1.07 | same |
| 364 | `mLY2wOQ6` | 1.90 | 1.03 | **regular: every test PASS**; production correlation 0.670 (correlation endpoint; the full check returned ERROR for it) |
| 339 | `O0JK3jZ1` | 2.60 | 1.19 | production correlation 0.737 (fails 0.7); gets one decorrelating variant |
| 306 | `1Yj6AP1k` | 1.60 | 1.03 | CROWDING variant of #303; fails the IS ladder (recent years 1.29) |
| 287 | `2rjPWNrJ` | 1.45 | 0.67 | **Power Pool eligible**: CROWDING chart-CNN pair, production correlation 0.687, Power Pool correlation 0.37, 2-year Sharpe 2.27; lost money in 2020 (-0.91) |

What the combinations taught, now built into the combiner (`combine` section of config.yaml):

- **Sharpe estimates are accurate for slow parts** (actual / estimate 0.98-0.99 at mean part turnover <= 0.28)
  and optimistic for fast ones (0.68-0.85 at 0.32-0.69). Estimates are now cut by 0.8 x (mean turnover - 0.2),
  and parts averaging above 45% turnover are not combined.
- **Returns rise when diversified parts are summed.** BRAIN rescales the summed positions to the same book, so
  returns are about mean(part returns) x sqrt(n / (1 + (n-1) x mean correlation)). For #298 that predicts 7.9%;
  the actual was 7.7%. Fitness is now estimated and must reach 1.0 on the regular route.
- **Combining popular forecasts barely dilutes production correlation.** It came out at 0.69-0.85, against the
  0.36-0.50 the pure dilution formula gave. The production pool already holds combinations of the same popular
  signals. The estimate is now the most crowded part x sd^-0.15. Truly unique alphas need data few alphas use;
  combination alone is not enough.

## 7. Outside the engine (your decisions)

- **Osmosis allocation**: needs 3 scopes with at least 10 alphas each. USA D1 qualifies today; two more scopes
  (e.g. GLB D1, EUR D1 or USA D0) need 10 alphas each. That unlocks the 1-2x daily multiplier and the
  Combined Osmosis Performance metric.
- **Use the 4 regular slots**: regular alphas are not limited by the shrinking pure Power Pool quota.
- **Other regions**: higher pyramid multipliers and a less crowded production pool. The engine runs there with
  `--region EUR --universe TOP2500` after `p2a sync` with the same flags.

## Sources

- BRAIN Learn pages synced by the engine: Power Pool Alphas; Consultant Submission Tests; Clear these tests
  before submitting an Alpha; Finding Consultant Alphas; Consultant Features; Risk Neutralized Alphas; Crowding
  Risk-Neutralized Alphas; Statistical Risk-Neutralized Alphas; Osmosis Allocation Guide; Brain Genius;
  Overview of Themes; Understanding PnL Realization Horizon; High Turnover Alphas; Consultant Dos and Don'ts.
- BRAIN API: `/users/self/activities/base-payment`, `/users/self/activities/pyramid-multipliers`,
  `/users/self/activities/pyramid-alphas`, `/alphas/{id}` (`is.riskNeutralized`, `pyramids`, `themes`),
  `/alphas/{id}/correlations/prod|self`, `/alphas/{id}/check`.
- McLean, R. D. and Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? Journal of
  Finance 71(1).
- Green, J., Hand, J. R. M. and Zhang, X. F. (2017). The Characteristics that Provide Independent Information
  about Average U.S. Monthly Stock Returns. Review of Financial Studies 30(12), 4389-4436.
- Brown, G. W., Howard, P. and Lundblad, C. T. (2022). Crowded Trades and Tail Risk. Review of Financial Studies
  35(7), 3231-3271.
- Kakushadze, Z. and Yu, W. (2016). How to Combine a Billion Alphas. arXiv:1603.05937.
- Kakushadze, Z. (2016). 101 Formulaic Alphas. arXiv:1601.00991.
- Grinold, R. and Kahn, R. Active Portfolio Management (fundamental law of active management).
- Timmermann, A. (2006). Forecast Combinations. Handbook of Economic Forecasting.
- Rapach, D., Strauss, J. and Zhou, G. (2010). Out-of-Sample Equity Premium Prediction: Combination Forecasts and
  Links to the Real Economy. Review of Financial Studies 23(2).
- Gu, S., Kelly, B. and Xiu, D. (2020). Empirical Asset Pricing via Machine Learning. Review of Financial Studies 33(5).
- Easley, D., O'Hara, M. and Srinivas, P. S. (1998). Option Volume and Stock Prices. Journal of Finance 53(2).
- Cremers, M. and Weinbaum, D. (2010). Deviations from Put-Call Parity and Stock Return Predictability. JFQA 45(2).
- Boehmer, E., Jones, C. M. and Zhang, X. (2008). Which Shorts Are Informed? Journal of Finance 63(2).
- Chan, L., Jegadeesh, N. and Lakonishok, J. (1996). Momentum Strategies. Journal of Finance 51(5).
- Roll, R. and Ross, S. (1980). An Empirical Investigation of the Arbitrage Pricing Theory. Journal of Finance 35(5).
- Fama, E. and French, K. (1993). Common Risk Factors in the Returns on Stocks and Bonds. JFE 33(1).
