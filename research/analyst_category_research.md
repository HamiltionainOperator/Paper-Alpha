Analyst-Category Alpha Research Notes (USA, delay 1, TOP3000)

Prepared 2026-10-16 for the Power Pool theme "D1 Power Pool Oct`26 2" (delay=1, data category analyst, model
or news, single category). Every idea below uses ONLY analyst-category fields (plus grouping fields), so none may be
combined with price, returns or fundamental fields. Field ids, types and coverage were verified against the live
BRAIN catalog for USA/D1/TOP3000; "uses" = number of BRAIN alphas already using the field.

Datasets: analyst4 (Analyst Estimate Data for Equity, 1324 fields), analyst7 (Broker Estimates, 1317 fields),
analyst11 (ESG scores, 445 fields), analyst14 (Estimations of Key Fundamentals, 868 fields), analyst34 (Dividend
forecasts model, 6 fields), analyst44 (Integrated Broker Estimates, 797 fields), analyst46 (Analyst Investment
Insight Data, 6 fields).

Category playbook (summarised from WorldQuant's "Getting started with Analyst Datasets" and "Creating D0 Alphas with
Analyst Data")
- Analyst fields are opinions about future fundamentals. Changes over time (ts_delta, ts_zscore) capture revisions;
  comparing short- and long-horizon estimates, or estimates with actuals, gives momentum or reversal signals.
- Many fields are VECTOR type (one value per analyst). vec_avg gives the consensus, vec_count the number of analysts
  (low counts are noisy), and vec_stddev or vec_range the disagreement (low spread = strong consensus).
- Per-share values jump at stock splits. Use relative changes (divide by the absolute lagged value) or ranks and
  z-scores instead of raw differences.
- Compare within industries through the neutralization setting; sector or industry neutralization usually helps.
- Verified on BRAIN (2026-10-16): while the theme requires a single data category, do NOT reference grouping fields (industry, sector, subindustry, market) in the expression - the platform counts them as price-volume data. Use the neutralization setting (INDUSTRY, SECTOR, ...) for within-industry comparisons instead. Some fields cover only part of the universe; carry values forward with ts_backfill.

1. Earnings forecast revision momentum
Sources: Chan, Jegadeesh and Lakonishok (1996), "Momentum Strategies", Journal of Finance; Givoly and Lakonishok
(1979), "The Information Content of Financial Analysts' Forecasts of Earnings", Journal of Accounting and Economics.
Finding: stocks whose consensus earnings forecasts were revised up keep outperforming over the next one to six
months; prices absorb revisions slowly.
Build: relative change of the consensus EPS estimate over about 21-63 days, or its time-series z-score. Fields:
earnings_per_share_average (analyst4, MATRIX, 100%, 497 uses) and anl4_qfv4_eps_mean (analyst4, MATRIX, 100%, 233
uses) are far less crowded than est_eps (17,322 uses), which carries the same information.

2. Revision breadth: how many analysts raise versus lower
Source: same revision literature; breadth is a standard practitioner refinement of revision signals.
Finding: a revision backed by many analysts moving in the same direction is more reliable than the average change.
Build: (number of upward estimates - number of downward estimates) / number of estimates, averaged over about 21 days.
Fields (analyst4, VECTOR, about 70%): anl4_adxqfv110_pu (number of upper estimations), anl4_adxqfv110_down (number
of lower estimations), anl4_adxqfv110_numest (number of estimates). That is exactly three fields, so the expression
must stay compact to respect the eight-operator limit.

3. Analyst disagreement predicts lower returns
Source: Diether, Malloy and Scherbina (2002), "Differences of Opinion and the Cross Section of Stock Returns",
Journal of Finance.
Finding: stocks with high dispersion in analysts' forecasts earn lower future returns, consistent with prices
reflecting the optimists when pessimists cannot easily sell short.
Build: forecast standard deviation divided by the absolute mean forecast, then short high dispersion. Fields:
earnings_per_share_standard_deviation (analyst4, MATRIX, 72%, 946 uses) or anl4_afv4_dts_spe (analyst4, MATRIX,
69%) with earnings_per_share_average. Add a small constant to the denominator to avoid dividing by near-zero
means. Expect low turnover.

4. Earnings surprise drift, and which earnings signal drifts most
Sources: Bernard and Thomas (1989), "Post-Earnings-Announcement Drift", Journal of Accounting Research; Chiu and
Haight (2019), "Investor Learning, Earnings Signals, and Stock Returns", SSRN 3348325 (WorldQuant write-up).
Finding: prices keep moving in the direction of the latest earnings surprise for weeks. Investor learning has eroded
the predictability of bottom-line earnings signals more than that of less noisy measures such as operating profit.
Build: standardised surprise = mean surprise / standard deviation of surprise, held through the quarter. Fields
(analyst7, MATRIX, 50% so backfill about 63 days): act_q_opr_surprisemean (operating profit surprise),
act_q_eps_surprisemean (EPS surprise, 573 uses), act_q_gps_surprisemean (GAAP EPS surprise),
act_q_eps_surprisestd (dispersion of the surprise). Test operating-profit surprise against GAAP EPS surprise.

5. ESG improvements and long-horizon investors
Sources: Starks, Venkat and Zhu (2017), "Corporate ESG Profiles and Investor Horizons", SSRN 3049943 (WorldQuant
write-up); Cao, Titman, Zhan and Zhang (2021), "ESG Preference, Institutional Trading, and Stock Return Patterns",
SSRN 3353623 (WorldQuant write-up).
Finding: long-horizon institutions tilt toward firms with better and improving ESG profiles, and the rise of ESG
investing changed how mispricing signals behave in stocks these investors hold.
Build: change in the ESG score over 63-252 days, compared within industry because ESG levels differ by industry.
Fields (analyst11, MATRIX, about 84%): anl11_gse (overall ESG score, 119 uses), anl11_g (governance score),
sustainability_industry_rank (rank within industry, 1 use), sustainability_sector_percentile (0 uses). ESG moves
slowly: if turnover drops below 1%, use a shorter change window or less decay.

6. Sell-side trade-idea sentiment, weighted by track record
Source: the analyst46 dataset (aggregated sell-side investment ideas with components for idea age and for the
historical accuracy of the contributing analysts).
Finding: idea sentiment from analysts with good track records, and fresh ideas, should carry more information.
Build: anl46_sentiment (composite idea sentiment), anl46_performancepercentile (historical performance percentile,
1-100), anl46_indicator (1-10 cross-sectional score), anl46_alphadecay (idea staleness) - analyst46, MATRIX, about
62-71% coverage, all rarely used (29-95 uses). Example: sentiment weighted by the rank of the performance
percentile, backfilled.

7. Dividend forecast changes
Sources: Michaely, Thaler and Womack (1995), "Price Reactions to Dividend Initiations and Omissions: Overreaction or
Drift?", Journal of Finance; Healy and O'Sullivan (2019), "Dividend capture returns: anomaly or risk premium?",
SSRN 3337964 (WorldQuant write-up).
Finding: prices drift after dividend increases and initiations, and expected dividends carry information that
markets incorporate slowly.
Build: compare the forecast dividend with the forecast implied by historical payout growth, or track changes in the
forecast. Fields (analyst34, VECTOR, 96%; note BRAIN spells them in lower case):
anl34_stockdivforecasts_expectedamount, anl34_stockdivforecasts_expectedamount_histgrowth. Aggregate with vec_avg
first. Many stocks pay no dividend, so treat missing values carefully.

8. Gap between GAAP and adjusted earnings estimates (exploratory)
Source: Ribeiro, Shan and Taylor (2018), "Non-GAAP Earnings and the Earnings Quality Trade-off", SSRN 3277318
(WorldQuant write-up).
Finding: adjusted (non-GAAP) earnings are more persistent and value-relevant but less conservative; large gaps
between adjusted and GAAP figures can flag aggressive exclusions.
Build: analyst44 vectors anl44_gaap_best_eps, anl44_gaap_best_eps_gaap and anl44_r_best_eps_gaap (VECTOR, about
92%). Their descriptions on BRAIN are terse, so read them before relying on a particular interpretation; aggregate
with vec_avg before comparing.
