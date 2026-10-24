# New alpha ideas from research papers, on data few BRAIN alphas use (research round 6, 17 Oct 2026)

## Why new ideas instead of better combinations

Round 5 built integrated composites of the best existing signals: option-implied spreads, analyst revisions, chart-CNN
forecasts, residual reversal and earnings surprises. Two of them reached Sharpe 2.80-2.84 with fitness 1.74-1.93. BRAIN's
check still failed them on production correlation, at 0.82-0.83, with about 60,000 production alphas above 0.5
correlation. Production already holds combinations of the popular signals, so recombining them cannot make a unique
alpha. Uniqueness has to come from a new economic mechanism measured with data few alphas use.

The method:
1. Survey the least-used USA D1 datasets (catalog alpha counts of 0-40 per field).
2. Read what each field measures.
3. Match it to a published mechanism with documented return predictability.
4. Write the mechanism in BRAIN operators as a template whose inputs are roles filled from the live catalog
   (`research/mechanisms.yaml`).

## The ideas

| idea | paper(s) | what the paper found | BRAIN data (alphas on BRAIN) | expression |
|---|---|---|---|---|
| Board centrality | Larcker, So and Wang (2013) JAE | most- minus least-central boards earn 4.68% a year; higher future ROA growth that analysts miss | `board_network` (37): director-network eigenvector / betweenness centrality | `rank(network_eigenvector_centrality_metric)` |
| Quadrophobia | Malenko, Grundfest and Shen (2023) JFQA | firms that avoid a 4 in EPS's tenth-of-a-cent digit are rounding up; this predicts restatements, SEC enforcement and class actions | `model259` (13): 3-year QUAD score | `rank(mdl259_qad_score)` (sign learned) |
| Organization capital | Eisfeldt and Papanikolaou (2013) JF | high organization capital relative to industry peers earns about 4.6% a year | `model313` (34): organizational capital intensity | `rank(mdl313_ico)` |
| Intangible intensity | Peters and Taylor (2017) JFE; Eisfeldt, Kim and Papanikolaou (2022) RFS | book value misses intangibles; an intangible-value premium | `model313`: intangible asset intensity | `rank(mdl313_us_iai)` |
| Innovation focus | Cohen, Diether and Malloy (2013) RFS; Hirshleifer, Hsu and Li (2013) JFE | markets misvalue innovation ability and efficiency | `model127` (83): relevance of recent patents to the firm's technological footprint | `rank(vec_avg(mdl127_relevance_hist_3_recent_1_neut))` |
| Patent quality | Hirshleifer, Hsu and Li (2013); Kogan, Papanikolaou, Seru and Stoffman (2017) QJE | innovative efficiency predicts returns | `model127`: patent innovation composite | `rank(vec_avg(mdl127_pia2))` |
| Lazy prices | Cohen, Malloy and Nguyen (2020) JF | firms that change their 10-K/10-Q substantially underperform, up to 188 bp a month, with no announcement reaction | `filing_sentiment` (42): words per filing section | `-rank(abs(ts_delta(ts_backfill(vec_avg(total_word_quantity_2),252),252)) / ts_mean(...,252))` |
| Filing negativity | Loughran and McDonald (2011) JF | share of finance-negative words in 10-Ks predicts returns | `filing_sentiment`: negative-term counts / words | `-rank(negative terms / words)` |
| Passive-flow reversal | Ben-David, Franzoni and Moussawi (2018) JF | ETF arbitrage transmits non-fundamental demand; impact decays in days | `model237` (364; these fields 0-6): passive-ETF holding growth | `-rank(vec_avg(mdl237_znorm_etf_us_p_lev_g2w))` |
| Active vs passive ETF demand | same; Easley, Michayluk, O'Hara and Putnins (2021) | active ETFs trade on information, passive flows are noise | `model237`: active minus passive growth | `rank(active - passive)` |
| Salience | Cosemans and Frehen (2021) JFE | salient-upside stocks are overvalued and earn low returns | `behavioral_signals` (69): salience theory value | `-rank(vec_avg(salience_weighted_return_score))` |
| Return ordering | Mohrschladt (2021) JBF; Cakici and Zaremba (2021) | high chronological return ordering means lower returns, 0.91% a month across 49 countries | `behavioral_signals`: CRO | `-rank(vec_avg(chronological_return_sequence_correlation))` |
| Lottery extremes | Bali, Cakici and Whitelaw (2011) JFE | extreme recent daily returns mean overpricing | `behavioral_signals`: return extremeness | `-rank(vec_avg(extreme_daily_return_indicator))` |
| Frog in the pan | Da, Gurun and Warachka (2014) RFS | continuous (smooth) information is underreacted to more than jumps | `behavioral_signals`: price-path shape | `rank(vec_avg(visual_price_path_shape_score))` |
| Abnormal short volume | Diether, Lee and Werner (2009) RFS; Boehmer, Jones and Zhang (2008) JF | rising daily short-sale share predicts negative returns over the next days | `us_short_sale` (224): short / total shares | `-rank(5d - 63d mean short share)` |
| Forum opinion | Chen, De, Hu and Hwang (2014) RFS | social-media opinions predict returns and earnings surprises | `equity_forum_data` (6): buy and sell opinion | `rank(buy - sell)` |
| Equity-bond gap | Kapadia and Pu (2012) JFE | equity and credit pricing gaps are common, often anomalous, and close | `pv173` (88): equity return minus the bond-implied equity return | `-rank(vec_avg(pv173_zscoreseqbddivrgbdrtn120d))` |
| Earnings-volatility premium | Bali and Hovakimian (2009) MS; Gao, Xing and Zhang (2018) JFQA | implied minus realized volatility predicts returns; investors overpay for event insurance | `earnings_risk` (5): implied earnings vol minus realized | `-rank(ts_backfill(...,63))` |
| Dividend-forecast revision | Michaely, Thaler and Womack (1995) JF; Brav, Graham, Harvey and Michaely (2005) JFE | dividend changes signal earnings confidence; prices drift after them | `analyst34` (156; this field 3): dividend forecast | `rank(ts_zscore(vec_avg(predicted_dividend_per_share),252))` |
| Insider direction | Cohen, Malloy and Pomorski (2012) JF; Lakonishok and Lee (2001) RFS | opportunistic insider trades earn 82 bp a month; routine ones are uninformative | `insider_agg_matrix` (122): directional insider indicator | `rank(ts_backfill(directional_indicator_2,63))` |

Corrections from checking the papers:
- Gebhardt, Hvidkjaer and Swaminathan (2005) show that stocks lead bonds, not the reverse. So no "bond momentum to
  stock" alpha was built; the equity-bond gap idea follows Kapadia and Pu instead.
- The Seeking Alpha study's sample ends in 2012.

## What also came out of the BRAIN research this round

- **Fast D1** (BRAIN Learn "Fast D1"): about 1,000 `_fast_d1` fields carry information released between yesterday's
  close and today's open (news, earnings calls, filings, pre-market). They use delay-1 settings and the same submission
  bars and production-correlation pool. Most have 0-5 alphas. The delta `field_fast_d1 - field` is BRAIN's own suggestion
  for lower production correlation.
  - Overnight news tone alone did not predict close-to-close returns (Sharpe -0.53 to 0, turnover 100-160%).
- **Risk-model residual returns** (`pv20`: Barra and GEMTR specific returns, 27 alphas): residual reversal reached
  Sharpe 1.66. It trades 0.83 like your submitted Williams-%R reversal, so it is crowded in your own book.
- **NaN-safe composites**: `add(rank(a) - 0.5, rank(b) - 0.5, ..., filter=true)` keeps stocks that miss one part. Plain
  rank sums had dropped 15-20% of the universe and about 0.4 Sharpe.
- **Statistical industry groups** (`sta1_top3000c50`, `sta2_top3000_*`) for double neutralization, and
  `ts_target_tvr_decay` for turnover targeting, are on the account. They are kept as enhancers for new signals that
  work.

## Results (USA, TOP3000, delay 1; simulated 17 Oct 2026)

| # | idea | Sharpe | fitness | turnover | returns | note |
|---|---|---|---|---|---|---|
| 427 | equity-bond continuation | 1.18 | 0.50 | 40% | 7.3% | production correlation 0.895: the equity-return leg trades like momentum |
| 419 | equity-bond gap | -1.22 | -0.37 | 85% | -8.0% | inverted it works; production correlation 0.723 (only 74 production alphas above 0.5) |
| 430 | earnings-call answer tone | 1.04 | 0.45 | 4% | 2.3% | **production correlation 0.654** (104 production alphas above 0.5); self 0.18 |
| 423 | ETF ownership breadth | -0.88 | -0.31 | 29% | -3.5% | inverted |
| 412 | passive-flow reversal | 0.87 | 0.41 | 30% | 6.7% | production correlation 0.925: flow growth embeds the stock's own return |
| 415 | return ordering (CRO) | -0.86 | -0.31 | 34% | -4.5% | sign as the paper predicts |
| 414 | salience | -0.81 | -0.37 | 18% | -3.7% | sign as the paper predicts |
| 417 | abnormal short volume | 0.81 | 0.24 | 25% | 2.2% | |
| 407 | intangible intensity | 0.74 | 0.18 | 10% | 0.7% | traded on 237 of 2493 days (see below) |
| 416 | lottery extremes (MAX) | -0.73 | -0.32 | 18% | -3.5% | sign as the paper predicts |
| 409 | patent quality | 0.71 | 0.38 | 10% | 3.6% | lives in illiquid stocks |
| 404 | board centrality | 0.63 | 0.14 | 10% | 0.6% | traded on 237 of 2493 days |
| 410 | lazy prices | 0.63 | 0.19 | 13% | 1.2% | illiquid |
| 431 | scripted-vs-unscripted tone gap | -0.62 | -0.26 | 4% | -2.2% | |
| 424 | fund ownership breadth | -0.51 | -0.25 | 8% | -3.0% | |
| 413 | active vs passive ETF demand | 0.50 | 0.12 | 32% | 2.0% | |
| 405, 406, 408, 411, 418, 420-422, 425, 426, 432, 433 | quadrophobia, organization capital, innovation focus, filing negativity, forum opinion, earnings-volatility premium, dividend revision, insider direction, lazy-prices notes/items, revision breadth, consensus revision | -0.23 to 0.36 | | | | no usable signal |

What the results teach:
- **Uniqueness needs information that is not the stock's own price.** Two ideas on rarely used datasets came out
  crowded (0.895 and 0.925 with production) because their values are mostly past returns: the bond-implied gap's
  equity leg and ETF flow growth. The one pure non-price signal, management's tone when answering analysts, came out
  at 0.654. Screen every new idea for a hidden price component before simulating it.
- **Sparse fields need an explicit form.** Board-network and intangible-capital fields used bare held positions on
  only 237 of 2493 days (BRAIN's dateCoverage said 0.95). On those days the Sharpe was 2.1-2.45; carried forward with
  `ts_backfill(x, 252)` they fell to 0.16-0.33 (#434-#437, turnover below 1%). The information is an update-day
  reaction, not a premium to hold, so neither form is an alpha by itself. The combiner now ignores parts that trade on
  fewer than half the days, and its estimate keeps flat days (it had dropped them, which inflated sparse parts).
- **Single paper ideas are weak alone** (best |Sharpe| 1.22) and slow ones fail fitness on returns (answer tone: Sharpe
  1.04 but returns 2.3%). They are parts of composites, and only with other parts that carry no price information.
- Round 7 (`research/deep_research_round7.md`) takes these lessons into a per-dataset search across 13 families of
  uncrowded data.
