Alpha Shapes: How Research Ideas Become Fast Expressions

Prepared 2026-10-16. A "shape" is the structure of an alpha independent of the field it is applied to: which
time-series and cross-sectional operators turn a raw field into positions. Round 2 showed that one shape,
rank(field) on vendor return forecasts, works well (three submissions, six more eligible). This note collects
the other shapes that research supports, says which kinds of data each one suits, and how to write it with the
operators this account actually has (checked against the live operator list on 2026-10-16). The machine-readable
version is research/shapes.yaml; the engine loads it, validates every template against the live catalog, and
learns which shape works on which kind of data.

Sources read for this note
- Kakushadze (2016), "101 Formulaic Alphas", Wilmott (arXiv 1601.00991): 101 production alphas from WorldQuant.
  Average holding period 0.6-6.4 days, average pairwise correlation only 15.9%, returns scale with volatility
  (about R ~ V^0.76) and do not depend significantly on turnover.
- Chen and Zimmermann (2022), "Open Source Cross-Sectional Asset Pricing", Critical Finance Review: the signal
  documentation of 300+ published predictors with their construction, sign and holding period.
- Jensen, Kelly and Pedersen (2023), "Is There a Replication Crisis in Finance?", Journal of Finance: most
  published factors replicate (about 82% after multiple-testing adjustment) and cluster into 13 themes.
- Gu, Kelly and Xiu (2020), "Empirical Asset Pricing via Machine Learning", Review of Financial Studies.
- Ke, Kelly and Xiu (2019), "Predicting Returns with Text Data", NBER w26186.
- BRAIN Learn pages synced into the knowledge base: Build Alphas using research papers, Intermediate packs
  (conditional operators, improving alphas), Alpha examples (beginner, bronze, silver), Vector data fields,
  How to pass the sub-universe test, High turnover alphas, PnL realization horizon, Understanding data,
  Vector_neut, Double neutralization, Group data fields, Single dataset alphas, and the dataset guides for
  Model17, Earnings4, Option6 and Sentiment1.

1. What the evidence says about building alphas in general

- Simple beats elaborate. Most of the 101 production alphas combine two or three building blocks; BRAIN's
  high-turnover guide warns that chains of operators without an economic story are the usual sign of
  overfitting, and that a good alpha "still looks reasonable when simplified".
- Diversity is the product. The 101 alphas are only 16% correlated on average. A pool needs many different
  information sources and shapes, not variants of one; the Power Pool rule (< 0.5 correlation between your own
  Power Pool alphas) enforces exactly that.
- Turnover is not a source of return. Returns scale with volatility, not turnover (Kakushadze 2016). Turnover
  should follow from how fast the information decays, never be targeted directly (BRAIN high-turnover guide).
- Match the operator windows to the data's update speed. BRAIN's Model17 guide: weekly analyst data needs
  windows of 20+ days and a 5-10 day ts_backfill; ts_delta(x, 1) on such data measures noise. The Option6 guide:
  interpolated implied-volatility series are already smooth, so ask "where is today relative to the last 60
  days" (ts_zscore, ts_av_diff over a quarter) rather than "what changed in 5 days".
- Changes beat levels at short horizons; levels can work at long horizons (BRAIN high-turnover guide: deltas,
  surprises and revision-like constructs suit short horizons).
- Event fields are step functions. On a field that only changes at an event (an earnings release, a revision),
  ts_delta catches the event itself, which is often the point (Earnings4 guide); days_from_last_change(x) tells
  how fresh the information is.
- Most published ideas need adapting: BRAIN's research-paper guide notes that almost none work exactly as
  printed, and sometimes the opposite sign works. Probe once, invert strong negatives once.
- The sub-universe test requires Sharpe in TOP1000 >= 0.75 * sqrt(1000/3000) * Sharpe (about 0.43x). Signals
  that live in illiquid names fail it; BRAIN suggests decaying the liquid and illiquid parts separately rather
  than multiplying by size.

2. The shapes

Notation: x, y are fields of the same data category (vector fields are aggregated first, usually vec_avg);
d is a window chosen from the field's speed (fast = changes most days; medium = weekly; slow = monthly or
quarterly); size is a company-size field of the same category, used only for robustness.

A. Level shapes (one field)
- level: rank(x). For fields that already are forecasts or scores (vendor return predictions, composite
  ranks). Gu, Kelly and Xiu (2020) show machine-learning combinations of many characteristics forecast the
  cross-section; BRAIN notes model datasets are often "already treated". This is the shape that produced the
  round-2 winners. Keep it as the first probe for every forecast or score field.
- level, inverted: the engine flips a strong negative probe once (multi_source_model's quantile-5 probability
  turned out to be the top quantile; the first probe came out at Sharpe -1.91).

B. Change shapes (one field)
- change: rank(ts_delta(x, d)). Revisions and updates: analyst EPS revisions (Hawkins, Chamberlin and Daniel
  1984; Chan, Jegadeesh and Lakonishok 1996 "REV6"), recommendation changes (Jegadeesh, Kim, Krische and Lee
  2004), changes in call and put implied volatility (An, Ang, Bali and Cakici 2014: rising call IV predicts
  higher returns, rising put IV lower returns). Medium and slow fields; d = 21 or 63.
- history-relative: rank(ts_zscore(x, d)) or ts_rank(x, d). Where today's value sits in the field's own
  history; BRAIN's examples ts_rank(operating_income, 252) and the Option6 advice. Removes stable
  cross-sectional level differences, so it is often weakly correlated with the level shape.
- trend: rank(ts_regression(x, ts_step(1), d, rettype=2)). The slope of the field over time (BRAIN's
  "Investing for the Future" example); fundamental and estimate momentum (Novy-Marx 2015).

C. Event shapes (one field)
- fresh update: trade_when(days_from_last_change(x) <= k, rank(ts_delta(x, d)), -1). Trade only when the
  field has just changed and hold until the next change; BRAIN's research-paper guide builds an earnings-beat
  alpha this way. Suits sparse step fields (estimates, surprises, recommendations). Holding between events also
  cuts turnover.
- surprise hold: trade_when(days_from_last_change(x) == 0, rank(x), -1). Post-event drift: prices keep moving
  in the direction of an earnings surprise for weeks (Bernard and Thomas 1989; Foster, Olsen and Shevlin 1984);
  streaks of surprises are informative too (Loh and Warachka 2012).
- news-day update: trade_when(vec_count(v) > 0, rank(vec_avg(v)), -1). Update a story-level sentiment signal
  only on days with news and hold it otherwise. Tetlock (2007) and Tetlock, Saar-Tsechansky and Macskassy (2008)
  find news tone predicts returns and earnings; Ke, Kelly and Xiu (2019) find text-based signals are absorbed
  within days, so the update must be fast but the hold short.

D. Vector-specific shapes (one vector field)
- intensity: rank(ts_mean(vec_count(v), d)). Media attention: low-coverage stocks earn more (Fang and Peress
  2009); attention changes how fast prices absorb news. Raw counts have very high turnover (BRAIN vector
  guide), so they need averaging. Sign is set by the probe.
- dispersion: -rank(vec_stddev(v)). Disagreement among analysts or stories; high dispersion predicts lower
  returns (Diether, Malloy and Scherbina 2002).

E. Two-field shapes (same category, ideally same dataset)
- spread: rank(x - y). Paired measures whose gap is the signal: call minus put implied volatility
  (Bali and Hovakimian 2009; Cremers and Weinbaum 2010), put-minus-call smile slope (Yan 2011; Xing, Zhang and
  Zhao 2010), long- versus short-horizon forecasts (Da and Warachka 2011), with- versus ex-earnings volatility
  (BRAIN Earnings4 guide).
- standardized spread: rank(ts_zscore(x, d) - ts_zscore(y, d)). For fields that are mechanically linked, where
  the raw gap mostly reflects construction (BRAIN Option6 guide).
- time-series residual: rank(ts_regression(x, y, d, rettype=0)). The part of x that y does not explain over
  time; BRAIN prefers this to ts_corr between related fields.
- orthogonal: vector_neut(rank(x), rank(y)). x with its cross-sectional exposure to y removed (BRAIN vector_neut
  guide: reduces unwanted factor exposure and correlation). Use y = the field of a crowded or already-submitted
  signal to make a new alpha that does not trade like it. This is the main tool against the "trades like
  submitted" verdict.
- combination: rank(x) + rank(y). Two weakly correlated signals from one dataset: by the fundamental law of
  active management (Grinold and Kahn) the information ratio grows with independent breadth; combining
  predictors beats single ones (Lewellen 2015; Kakushadze and Yu 2017 on combining alphas). Only worth it when
  the two parts are themselves less than about 0.5 correlated.
- interaction: rank(x) * rank(y). A fast catalyst weighted by a slow conditioning variable (BRAIN high-turnover
  guide); anomalies are stronger in some states (Stambaugh, Yu and Yuan 2012). After neutralization this tilts
  the book toward stocks high on both.
- co-movement: -ts_corr(x, y, d). Two related series moving in lockstep can mean the information is already
  priced (BRAIN's price-target versus cash-flow example); a staple pattern of the 101 alphas, which correlate
  ranks of price and volume. Exploratory for non-price data.

F. Robustness wrappers (applied to a base shape, never a new idea on their own)
- liquidity-split decay: ts_decay_linear(s, d1) * rank(size) + ts_decay_linear(s, d2) * (1 - rank(size)), d1 <
  d2. BRAIN's own suggestion for sub-universe failures.
- size weight: (rank(s) - 0.5) * rank(size). Fixed one of three sub-universe near-misses in round 2 (Sharpe
  1.68 -> 1.91 and passing); BRAIN cautions that size multipliers shift weight toward large names, so it is a
  one-shot remedy.
- size-bucket neutral: group_neutralize(s, densify(bucket(rank(size), range="0.1,1,0.1"))). Size-decile
  neutral positions built from a same-category size field, so single-category themes stay matched (industry
  and sector fields count as price-volume data).
- hump: hump(s, hump=0.01). Limits small daily changes; for fast signals whose turnover is too high.
- confidence gate: trade_when(ts_mean(c, 60) > 0.5, s, -1) where c is a model-confidence field of the same
  dataset (BRAIN Option6 guide).

3. Which shapes suit which data (starting priors; the engine updates them from results)

| Data kind | First probe | Next shapes |
|---|---|---|
| Vendor return forecasts, composite scores | level | orthogonal (vs submitted), combination, spread of horizons, liquidity-split decay |
| Analyst estimates, revisions, recommendations | change (d 21-63) | history-relative, fresh update, trend, dispersion (vector) |
| Earnings surprises, event step fields | surprise hold | fresh update, level |
| News sentiment (vector) | news-day update | level of a smoothed average, interaction with intensity |
| News counts / attention | intensity | interaction with sentiment |
| Option-implied volatility, skew | spread | standardized spread, change, history-relative, time-series residual |
| Short interest, lending, ownership flows | level | change, history-relative |
| Risk (beta, volatility) | level (low-risk sign) | change |
| Quality and valuation scores | level | history-relative, trend |

4. Lessons from rounds 1 and 2 that shape the priors
- Level of a vendor forecast: 7 of 15 forecast fields cleared Sharpe 1.0 on the first probe.
- Smoothing short-horizon option and chart signals destroyed them (1.68 -> 1.03, 1.34 -> 1.17): no level_smooth
  for fields whose own horizon is a few days.
- Slow textbook shapes on crowded analyst fields (quarterly revisions, dispersion, ESG) stayed below 0.6.
- Two analyst-based forecasts from different datasets were 0.95-0.98 correlated: different field ids are not
  different ideas; the daily-PnL screen decides.

5. What the BRAIN experiments showed (2026-10-16, USA TOP3000 delay 1, 34 shape probes)

| Shape | Data | Result | Verdict |
|---|---|---|---|
| combination | option-implied 20-day forecast + 5-day "hedge" forecast | Sharpe 2.27, fitness 1.22 (singles 1.91 failing, 0.80), eligible, passes regular bars | best alpha so far: a sub-universe near-miss rescued by an uncorrelated partner |
| combination | 5-day event forecast + 120-day forecast | Sharpe 1.66 (singles 1.16, 1.44), eligible | works: breadth across horizons |
| combination | two chart-image CNN models | 1.51 (singles 1.34, 1.20) | works, but trades like another winner |
| size-bucket neutral | call minus put implied volatility | 1.66 | works (as does size weighting, 1.91) |
| history-relative | bias-free analyst price target | 1.37, eligible | works: first analyst-category winner |
| history-relative | analyst82 predicted profitability change | 1.35 (level 0.65), eligible | works, but crowded (prod corr 0.91) |
| time-series residual | call IV on put IV | 1.30 | works |
| trend | analyst82 predicted profitability change | 1.13 | works, very low turnover (5%) |
| spread | 120-day minus 20-day forecast | 1.17 | works but trades like the 120-day forecast (0.90) |
| change | 60-day seasonal forecast, 21-day change | 1.10 | works |
| liquidity-split decay | option-implied 20-day forecast | 1.60 | better than plain (1.91 but failing), still a sub-universe near-miss |
| interaction | option forecast x analyst forecast | 1.21 | trades like an existing winner |
| orthogonal | 60-day and 50-day forecasts vs the submitted 20-day forecast | -0.31, -0.32 | fails: their edge is the shared part |
| news-day update | three story-sentiment vectors | -0.40 to 0.10 | fails at delay 1 in TOP3000 |
| interaction | news tone x novelty | 0.11, turnover 124% | fails |
| intensity | news coverage | -0.65 | opposite sign to Fang and Peress: more coverage, higher returns |
| fresh update / surprise hold / dispersion | analyst EPS consensus, broker surprise, broker dispersion | 0.29-0.40 | fail |
| change / history-relative | stock-loan utilisation | -0.25, -0.21 | fail |

Updated priors (these now drive the engine through its shape statistics):
- Analyst estimates: history-relative and trend are the shapes that work; levels, event gating and dispersion
  did not on these fields.
- Vendor forecasts: level first, then combinations across horizons or model families; orthogonalising against
  a correlated submitted forecast removes the signal instead of the overlap.
- Option-implied spreads: level and time-series residual work; standardized spreads and changes did not.
- News: none of the research shapes worked on the delay-1 TOP3000 story-sentiment fields tested here; news
  ideas need a different universe, delay or data (left for later).
