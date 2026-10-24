News-Category Alpha Research Notes (USA, delay 1, TOP3000)

Prepared 2026-10-16 for the Power Pool theme "D1 Power Pool Oct`26 2" (delay=1, data category analyst, model
or news, single category). Every idea below uses ONLY news-category fields (plus grouping fields such as industry),
so none of them may be combined with price/volume fields like close or returns. Field ids, types and coverage were
verified against the live BRAIN catalog for USA/D1/TOP3000. "uses" = number of BRAIN alphas already using a field
(lower means less crowded).

Datasets: news18 (Ravenpack News Data, 121 fields), news7 (Real Time News Feed, 162 fields), news3 (Dow Jones News
Analytics, 19 fields).

Category playbook (summarised from WorldQuant's "Getting started with News Datasets" and the D0 news guides)
- News is noisy: clip extremes (winsorize) and then normalise across stocks (rank, zscore, normalize).
- The price effect of news can last from days to a quarter; averaging over time (ts_mean, ts_decay_linear) keeps
  turnover low, which matters because Power Pool is scored on after-cost performance.
- Story-level fields are VECTOR type (several stories per stock per day). Aggregate them first: vec_avg for the
  average tone, vec_sum for net direction, vec_count for news intensity, vec_max/vec_min for extremes.
- Fields named rp_* have about 50% coverage because they only update on relevant news; carry the last value
  forward with ts_backfill (20-63 days) before ranking.
- Verified on BRAIN (2026-10-16): while the theme requires a single data category, do NOT reference grouping fields (industry, sector, subindustry, market) in the expression - the platform counts them as price-volume data. Use the neutralization setting (INDUSTRY, SECTOR, ...) for within-industry comparisons instead.
- The "event reaction" ideas in the guides use price or volume changes around news; under this month's
  single-category rule that is not allowed, so use the news datasets' own impact and sentiment fields instead.

1. News momentum: persistent news tone
Sources: Wang, Zhang and Zhu (2018), "The Momentum of News", SSRN 3267337; WorldQuant write-ups "Research Paper 01:
The Momentum of News" and "Research Paper: The Momentum of News".
Finding: firms with more positive news over the past month tend to get more positive news next month, because the
underlying fundamentals are persistent. A long good-news / short bad-news quintile strategy earned about 7.45% per
year risk-adjusted, on both news and non-news days, so prices do not fully anticipate future news tone.
Build: average daily news sentiment over 21-63 days and rank it. Fields: mean_composite_sentiment_score (news18,
MATRIX, coverage 100%, 247 uses), mean_event_sentiment_score (news18, MATRIX, 100%, 103 uses),
mean_equity_sentiment_score (news18, MATRIX, 100%, 150 uses), storytone_sentiment_value_v2_1_0 (news7, MATRIX, 92%:
positive minus negative word count of stories), headline_sentiment_value_v2 (news7, MATRIX, 100%).
Horizon: one to three months; turnover should be low. Some industries get systematically more positive coverage,
so compare within industry (group_rank) or use industry/subindustry neutralization.

2. Pessimistic language predicts weaker earnings and returns
Sources: Tetlock (2007), "Giving Content to Investor Sentiment: The Role of Media in the Stock Market", Journal of
Finance; Tetlock, Saar-Tsechansky and Macskassy (2008), "More Than Words: Quantifying Language to Measure Firms'
Fundamentals", Journal of Finance.
Finding: the share of negative words in firm-specific news predicts lower future earnings and lower returns, and
prices take a few days to absorb it. At the market level pessimism also causes temporary price pressure that
partly reverses, so both a drift version (weeks) and a short reversal version (days) are worth testing.
Build: nws7_storytone_news_freq (news7, MATRIX, 87%: negative words divided by all words) - more negative words
means short; average over 5-21 days. Emotion vectors from Dow Jones (news3, VECTOR, 96%): nws3_scores_negnormscr
(negative), nws3_scores_findownnormscr (financial pessimism, 169 uses), nws3_scores_finupnormscr (financial
optimism, 180 uses). An optimism-minus-pessimism spread uses two fields from the same dataset.

3. Earnings news drift when attention is limited
Sources: Bernard and Thomas (1989), "Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?",
Journal of Accounting Research; Hagendorff, Gonzalez and Li (2021), "Let Me Sleep on It: Sleep and Investor
Reactions to Earnings Surprises", SSRN 3803494 (WorldQuant Research Paper 64); Chen, Cohen and Wang (2020), "Famous
Firms, Earnings Clusters, and the Stock Market", SSRN 3685452 (Research Paper 57); Gao, Hu and Zhang (2020),
"Uncertainty Resolution Before Earnings Announcements", SSRN 3595953 (Research Paper 73); Kottimukkalur (2018),
"Earnings Uncertainty and Attention", SSRN 3287470.
Finding: when investors are distracted, prices under-react to earnings news and drift in its direction for weeks;
drift is stronger for firms that attract less attention, and much of the announcement premium of uncertain firms
is earned before the release.
Build: hold the tone of the most recent earnings news for 20-60 days. Fields: rp_css_earnings (news18, MATRIX, 50%:
composite sentiment of earnings news), rp_nip_earnings (news18, MATRIX, 50%: projected market impact of earnings
news), mean_earnings_evaluation_sentiment (news18, MATRIX, 100%, 153 uses), nws18_bee (news18, VECTOR, 100%:
earnings evaluation -1/0/+1), nws18_ber (news18, VECTOR, 100%: earnings release flag). Backfill the sparse rp_*
fields, or use trade_when to update positions only on release days, which also cuts turnover.

4. Industry drift after M&A announcements
Source: Funke, Gebken, Johanning and Michel, "Predictability of Industry Returns After M&A Announcements",
SSRN 887289 (WorldQuant Research Paper 05).
Finding: industries whose merger announcements are received well keep outperforming for months, and industries with
badly received deals keep underperforming; markets under-react to the industry-wide information in mergers.
Build: average M&A sentiment across each industry (group_mean with weight 1 over industry or subindustry), smoothed
over 63-126 days, so every stock in a well-received industry is long. Fields: mean_merger_acquisition_sentiment
(news18, MATRIX, 100%, 362 uses), rp_css_mna and rp_ess_mna (news18, MATRIX, 50%: composite and event sentiment of
M&A news), rp_nip_mna (news18, MATRIX, 50%: projected impact), nws18_bam (news18, VECTOR, 100%: M&A sentiment
-1/0/+1). Important: this is an industry-level signal, so do not use INDUSTRY or SUBINDUSTRY neutralization (it
would cancel the signal); use MARKET or SECTOR. Expect low turnover.

5. Analyst recommendation changes in the news flow
Sources: Womack (1996), "Do Brokerage Analysts' Recommendations Have Investment Value?", Journal of Finance;
Jegadeesh, Kim, Krische and Lee (2004), "Analyzing the Analysts: When Do Recommendations Add Value?", Journal of
Finance; WorldQuant Research Paper 55 maps analyst revisions to nws18_ghc_lna.
Finding: prices keep drifting for weeks to months after recommendation changes, more strongly after downgrades.
Build: nws18_ghc_lna (news18, VECTOR, 90%: change in analyst recommendation) - sum the day's changes (vec_sum), then
sum or average over 21-63 days and rank.

6. Neglected stocks and slow diffusion of bad news
Sources: Fang and Peress (2009), "Media Coverage and the Cross-section of Stock Returns", Journal of Finance; Hong,
Lim and Stein (2000), "Bad News Travels Slowly: Size, Analyst Coverage, and the Profitability of Momentum
Strategies", Journal of Finance.
Finding: stocks with little media coverage earn higher returns than heavily covered ones, and bad news spreads slowly
among low-coverage firms.
Build: news intensity = number of stories per day, e.g. vec_count(nws18_event_relevance) or
vec_count(story_event_record_count) (news18, VECTOR), summed over 63-126 days; long low-coverage stocks. A second
version shorts low-coverage stocks with negative tone (combine intensity with mean_composite_sentiment_score).
Caution: coverage is related to company size, which can fail the sub-universe robustness test; rank within
industry or sector rather than across the market.

7. Novel news continues, stale news reverses
Sources: Tetlock (2011), "All the News That's Fit to Reprint: Do Investors React to Stale Information?", Review of
Financial Studies; WorldQuant's news momentum write-ups.
Finding: investors over-react to repeated (stale) stories, which later reverses, while genuinely new information
leads to persistent moves.
Build: weight sentiment by novelty. Fields: mean_event_novelty_score (news18, MATRIX, 100%, 154 uses),
event_novelty_score_2 and global_event_novelty_score_2 (news18, VECTOR, 100%), together with
mean_composite_sentiment_score. Continuation version: sentiment times novelty, averaged over 10-21 days. Reversal
version: sentiment on low-novelty days with the opposite sign.

8. Fear and uncertainty in news (exploratory)
Source: Shen, Najand, Dong and He (2017), "News and Social Media Emotions in the Commodity Market" (WorldQuant
Research Paper 80): media-based emotion indices (optimism, fear, joy) predicted the next five days' returns of
individual assets.
Build: nws3_scores_fearnormscr (38 uses), nws3_scores_uncertaintynormscr (127 uses),
nws3_scores_certaintynormscr (204 uses) (news3, VECTOR, 96%): vec_avg, then a 5-10 day average, then rank. This is a
short-horizon idea, so expect higher turnover and smooth it; the equity evidence is weaker than for the ideas above.
