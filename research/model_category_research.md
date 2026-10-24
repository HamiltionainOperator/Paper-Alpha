Model-Category Alpha Research Notes (USA, delay 1, TOP3000)

Prepared 2026-10-16 for the Power Pool theme "D1 Power Pool Oct`26 2" (delay=1, data category analyst, model
or news, single category). Every idea below uses ONLY model-category fields (plus grouping fields). Field ids,
types and coverage were verified against the live BRAIN catalog for USA/D1/TOP3000; "uses" = number of BRAIN
alphas already using the field.

Datasets: model30 (EPS Estimate Model / StarMine SmartEstimate, 48 fields), model26 (Analyst Revisions, 839 fields),
model12 (Stock Selection Model, 5 fields), model51 (Systematic Risk Metrics, 16 fields), model23 (Scorings Data, 157
fields), model31 (Earnings Quality Model, 235 fields), model25 (Earnings Quality, 430 fields), model16 (Fundamental
Scores, 24 fields), model10 (Research Indicators).

Category playbook (summarised from WorldQuant's "Getting started with Model Datasets" and "Creating D0 Alphas with
Model Data")
- Model fields are mostly scores and percentile ranks produced by vendor models. Apply rank, zscore, ts_rank,
  ts_zscore or ts_delta; the trend of a score over a long window is often informative.
- Compare within groups through the neutralization setting (INDUSTRY, SUBINDUSTRY, SECTOR); it usually helps,
  especially for credit and quality scores whose levels differ by industry.
- Verified on BRAIN (2026-10-16): while the theme requires a single data category, do NOT reference grouping fields (industry, sector, subindustry, market) in the expression - the platform counts them as price-volume data. Use the neutralization setting (INDUSTRY, SECTOR, ...) for within-industry comparisons instead.
- Percentage-surprise fields compare companies of different sizes better than raw estimate levels.
- WorldQuant's guide also suggests correlating model fields with returns or close prices; under this month's
  single-category rule that mixes in the price-volume category, so use model fields on their own.
- Correction found while verifying: one WorldQuant write-up describes mdl109_iv as implied volatility, but BRAIN
  describes it as a Vortex technical indicator. Trust the field descriptions in the catalog.

1. Predicted earnings surprise (accuracy-weighted vs simple consensus)
Source: the StarMine SmartEstimate methodology behind model30 (estimates weighted by each analyst's historical
accuracy and recency; also described in the analyst10 dataset); WorldQuant's write-up of Kottimukkalur (2018),
"Earnings Uncertainty and Attention", maps estimated EPS to this dataset.
Finding: when the accuracy-weighted estimate differs from the plain consensus, actual results tend to surprise in
that direction, and prices react to the surprise.
Build: rank the predicted percentage surprise, possibly within industry and smoothed over 5-21 days. Fields (model30,
MATRIX, about 93-95% coverage): star_new_eps_surprise_prediction_fy1 (587 uses), star_new_eps_surprise_prediction_12m
(546 uses), star_new_eps_surprise_prediction_fq1, mdl30_psprise_pct_f12m_eps. Avoid the period_end_* fields: they
are SYMBOL-type dates, not numbers.

2. Analyst revision momentum model and bold forecasts
Sources: Chan, Jegadeesh and Lakonishok (1996), "Momentum Strategies", Journal of Finance; Clement and Tse (2005),
"Financial Analyst Characteristics and Herding Behavior in Forecasting", Journal of Finance (bold forecasts that
move away from consensus are more accurate than herding forecasts).
Finding: stocks with improving analyst revisions outperform; bold revisions carry more information.
Build: model26 fields: mdl26_v14_sma_arm_global_rank (MATRIX, 100%, 134 uses), mdl26_v14_sma_arm_country_rank
(MATRIX, 100%, 237 uses), star_arm_global_rank (MATRIX, 99%, but crowded with 999 uses), mdl26_arm_score_change_7
(7-day score change), count_positive_bold_estimates_fy1 and count_negative_bold_estimates_fy1 (counts of bold up and
down estimates). Examples: change in the ARM rank over 21 days; imbalance of positive versus negative bold
estimates.

3. Earnings quality and accruals
Sources: Sloan (1996), "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future
Earnings?", The Accounting Review; Liceran-Gutierrez and Cano-Rodriguez (2017), on measuring earnings quality with
partial least squares (WorldQuant write-up mapping to model31 and model25).
Finding: firms whose earnings rely heavily on accruals rather than cash flows underperform; higher earnings quality
predicts better returns.
Build: rank earnings-quality scores within industry, or track their change over about 63 days. Fields:
star_v14_eq_accruals_rank (model31, MATRIX, 94%, 242 uses), star_eq_region_rank (model31, MATRIX, 93%),
mdl25_8v (model25, MATRIX, 93%: earnings quality by accruals), mdl25_6v (model25: earnings quality region rank),
mdl25_9v (model25: one-day difference of the accruals score). Expect low turnover.

4. Net equity issuance
Sources: Loughran and Ritter (1995), "The New Issues Puzzle", Journal of Finance; Pontiff and Woodgate (2008), "Share
Issuance and Cross-sectional Returns", Journal of Finance; Dong, Hirshleifer and Teoh (2012), "Overvalued Equity and
Financing Decisions", SSRN 1874726 (WorldQuant write-up).
Finding: firms that issue equity (often when overvalued) underperform, and firms that buy back shares outperform.
Build: short high issuance. Fields (model23): mdl23_bk_net_equity_financ (MATRIX, 71%: higher = more equity
issuance), recent_equity_issuance_score (MATRIX, 71%, 0 uses), net_equity_issuance_indicator (MATRIX, 100%, 2 uses).
The last two are almost untouched on BRAIN, which helps diversity. Low turnover; sector neutralization.

5. Short-term reversal and the overnight versus daytime tug of war
Sources: Akbas, Boehmer, Jiang and Koch (2021), "Overnight Returns, Daytime Reversals, and Future Stock Returns",
SSRN 3324880 (WorldQuant write-up mapping to mdl12_reversal_component); Jegadeesh (1990), "Evidence of Predictable
Behavior of Security Returns", Journal of Finance.
Finding: stocks with an intense daily tug of war (positive overnight returns reversed during the day) earn higher
future returns; short-term losers tend to rebound.
Build: model12 component scores (MATRIX, 100%, percentile 1-100): mdl12_reversal_component (700 uses),
mdl12_liquidity_shock_component (432 uses), mdl12_factor_momentum_component (562 uses),
mdl12_seasonality_component (765 uses), mdl12_1mt (combined score). Test each alone with rank or ts_rank, then
pairs such as reversal plus liquidity shock. Short horizon, so smooth to control turnover.

6. Low-risk anomalies: beta, idiosyncratic and downside risk
Sources: Frazzini and Pedersen (2014), "Betting Against Beta", Journal of Financial Economics; Ang, Hodrick, Xing
and Zhang (2006), "The Cross-Section of Volatility and Expected Returns", Journal of Finance; Atilgan, Bali,
Demirtas and Gunaydin, "Downside Beta and Equity Returns around the World" (WorldQuant write-up); Zaremba (2018),
"Small-Minus-Big Predicts Betting-Against-Beta", SSRN 3227047 (WorldQuant write-up).
Finding: low-beta and low-idiosyncratic-volatility stocks earn better risk-adjusted returns than high-risk stocks.
Build: model51 (MATRIX, 94-98%): beta_last_60_days_spy, beta_last_360_days_spy, unsystematic_risk_last_30_days,
unsystematic_risk_last_90_days, systematic_risk_last_90_days, correlation_last_360_days_spy. The 360-day
idiosyncratic risk field is heavily crowded (16,637 uses); prefer shorter windows or changes in risk, e.g. the
21-day change of unsystematic_risk_last_30_days. Low-risk tilts lean toward large companies, so rank within sector
to protect the sub-universe test.

7. Multi-style composite scores and their acceleration
Source: the model16 Fundamental Scores dataset (value, growth, profitability, momentum and quality scores combined
into a style "surface", plus its acceleration); WorldQuant's news-momentum write-up maps fscore_momentum to news
momentum.
Finding: improving composite fundamentals and strengthening analyst revisions point to future outperformance.
Build: model16 (MATRIX, 100% coverage for the *_derivative fields): analyst_revision_rank_derivative (1,658 uses),
earnings_certainty_rank_derivative, multi_factor_acceleration_score_derivative (499 uses),
growth_potential_rank_derivative (509 uses), relative_valuation_rank_derivative (441 uses). The fscore_* fields cover
only about 30-38% of stocks, so backfill them or prefer the *_derivative versions. Rank within industry.

8. Institutional ownership as an amplifier of mispricing
Sources: Konstantinidi (2022), "Firm Life Cycle, Expectation Errors and Future Stock Returns", SSRN 3332513
(WorldQuant write-up); Cao, Titman, Zhan and Zhang (2021), SSRN 3353623.
Finding: mispricing-based returns are concentrated in stocks with low institutional ownership, where arbitrage is
weaker.
Build: mdl10_inst_ownership (model10, MATRIX, 92%) as a conditioning variable for another model signal from this
note, e.g. a quality or predicted-surprise score weighted more heavily where institutional ownership is low. Both
inputs come from the model category, so the single-category rule holds. Ownership is related to size, so check the
sub-universe test.
