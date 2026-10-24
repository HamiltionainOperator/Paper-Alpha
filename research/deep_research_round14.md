# Deep research round 14: alphas and SuperAlphas by region and universe (22 Oct 2026)

Question: which signal constructions, universes and combination methods give unique, high-Sharpe BRAIN alphas and
SuperAlphas in each region?

**About the evidence.** The deep-research workflow ran twice.

- Both runs fetched 23 primary sources and extracted 109 claims.
- Most claim-check agents and the synthesis step failed on the account's usage limit. Only **2 claims were verified**
  (3-0 and 2-0 votes); none were refuted.
- Everything marked *lead* below comes from a primary source but was not independently checked.
- Where our own BRAIN simulations tested the same idea, the result is noted. Those numbers are measured, not cited.

## Verified (adversarially checked)

1. **Regions agree only moderately on which factors pay** (Jensen, Kelly and Pedersen 2023 JF, "Is There a
   Replication Crisis in Finance?").
   - U.S. factor alphas have a 62% rank correlation with developed ex-U.S. alphas and 43% with emerging markets.
   - Size is much stronger in emerging markets.
   - Short-term reversal is about 0.4%/month in the U.S. against about 0.1 elsewhere. Accruals and debt issuance are
     also much weaker outside the U.S.
   - Quality and value are strongest in emerging markets; low risk is strongest in developed ex-U.S.
2. **Published factors decay but do not vanish** (same paper).
   - The U.S. average CAPM alpha falls 47% after publication, from 0.49 to 0.26%/month.
   - In-sample alpha still predicts out-of-sample alpha, but the relation is concave: the highest in-sample alphas are
     the most mined or arbitraged.

## Leads by region (sourced, not verified), with our BRAIN evidence

| Region | Lead | Our BRAIN measurements |
|---|---|---|
| USA | Anomaly returns decline after publication only in the U.S. (Jacobs and Müller 2020 JFE: 241 anomalies in 39 markets). Equity loan fees are the strongest U.S. predictor, driven by the high-fee short tail (Muravyev, Pearson and Pollet, Management Science 2025). Opportunistic, not routine, insider trades predict (Cohen, Malloy and Pomorski 2012 JF). | Consistent with U.S. arbitrage: analyst revisions 0.09 (round 11); insider_feats ratio probes 0.45 or lower (#898-#901, 22 Oct), even with zero-user fields. What still works in USA is options skew and call-tone composites (#499, #605, #692). |
| EUR | Analyst-revision and price momentum strategies earn about 1%/month in France, Germany and the UK (SMU study of 11 markets). Value plus momentum hedge each other (correlation about -0.5) and the mix roughly doubles value's Sharpe in Europe (Asness, "Momentum in Japan"). | Revisions, recommendations, events, insider buying and call tone all work (#742, #771, #819, #862). Country-normalized revision score 1.19 with ≤ 0.10 correlation to the account's EUR alphas (#890). 2022-23 is weak for most text parts, so watch the IS ladder. |
| GLB | Regions disagree (verified 1). | Information signals work only in **MINVOL1M** (broad), not in TOPDIV3000 (large caps). Each source is strong in one geography, so build balanced composites. #886: earnings-quality change and level, seasonally abnormal insider buying, capital-investment score, abnormal revision breadth, country revision score. Sharpe 2.19, every geography ≥ 1.31, production correlation 0.475 with no production alpha above 0.5. |
| ASI / JPN | Analyst revisions and price momentum fail in Japan, Korea, Malaysia, Singapore and Taiwan (SMU). There is no momentum in Japan, while value is strongest there: Sharpe 0.71 vs 0.14 in the U.S. (Fama-French 2012 JFE; Asness). | ASI and JPN analyst and event signals scored 0.16-0.51 (rounds 11 and 14). For ASI, use value or quality (strong in Japan, verified 1) to pass the `LOW_ASI_JPN_SHARPE` test. |
| CHN | Value is earnings-to-price, not book-to-market. Exclude the smallest 30% of stocks, which are priced as reverse-merger shells. There is no momentum, but strong one-month reversal. Abnormal turnover (last month vs last year) is a sentiment factor at 1.14%/month (Liu, Stambaugh and Yuan 2019 JFE). | Costs are inside the CHN simulation, and reversal/flow signals lose about 10% × turnover. Low-turnover EP value restricted to rank(cap) > 0.3 is untested. Fields: `net_income_total_5` (fundamental23), `relative_earnings_yield_factor` (mfm_model_output). |
| IND | Size, quality and value are strongest in emerging markets (verified 1). | Untested. India is a Gold scope (one more Osmosis option). 141 datasets are known locally. |

## Universe

- *Lead* (Jensen-Kelly-Pedersen; Hou, Xue and Zhang 2020 RFS):
  - Most anomalies replicate in mega and large caps. Microcaps inflate equal-weighted results; reversal and size live
    in micro and nano caps.
  - Value and momentum spreads shrink with size, except value in Japan.
- *Ours*:
  - Volume-confirmed reversal is GLB MINVOL1M 2.54 vs TOPDIV3000 1.80.
  - Information signals need breadth: GLB trade ideas are 1.58 in MINVOL1M vs 0.46 in TOPDIV3000.
  - BRAIN's sub-universe test punishes signals that live in illiquid names. Fix with a `rank(cap)` position weight.
    For #862, the unweighted EUR version failed (1.17 vs 1.33) and the weighted one passed (1.03 vs 1.00). The bar
    scales with the alpha's Sharpe.

## Combining alphas (SuperAlphas, composites)

- *Lead* (Jensen-Kelly-Pedersen; Asness):
  - In a tangency portfolio, a theme's weight depends on how it hedges the others, not on its standalone alpha.
  - Full mean-variance weights lose about 30% of their Sharpe out of sample (0.80 to 0.56), so shrink.
- *Ours*:
  - Splitting the USA pool into dataset families gives SuperAlphas only 0.20-0.61 correlated with each other.
  - The trailing-Sharpe combo beats equal weight (2.81 vs 2.54).
  - The correlation-penalty combo added nothing (2.53).
  - **STATISTICAL neutralization of the SuperAlpha** removed the factor crowding: production correlation 0.81 → 0.62
    (d5KOapn2, submitted).
  - The Osmosis planner shrinks covariance and Sharpe toward the mean for the same reason.

## Uniqueness

- Composites become crowded when their parts share a factor tilt, even if each part is unique (#818: parts 0.55-0.63,
  composite 0.693).
- Residualize on low volatility, size and within-industry momentum (#819: production correlation 0.52), or use
  STATISTICAL neutralization (SuperAlphas).
- Zero-user fields do not guarantee signal (USA insider_feats). Non-U.S. regions keep more of a published anomaly
  (lead: Jacobs-Müller), but production correlation is about what consultants trade, so measure it every time.

## Next experiments

1. IND probes for EP value, quality and size, plus the robust-universe test (a fourth Osmosis scope).
2. CHN: EP value on the top 70% by cap, plus low abnormal turnover (Liu-Stambaugh-Yuan PMO). Keep turnover low
   because costs are simulated.
3. ASI: a value and quality composite with country neutralization, aimed at the JPN sub-test.
4. EUR: the country revision score as the base, plus parts that held up in 2022-23, to pass the ladder.
5. SuperAlphas for EUR and GLB once each scope has at least 10 active alphas.
