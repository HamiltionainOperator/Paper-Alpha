# Deep research round 15: new papers for USA, EUR and GLB (25 Oct 2026)

Question: which well-regarded papers document stock return predictability that holds in the U.S., Europe or globally,
can be written with BRAIN data, and has not been measured on this account yet (rounds 1-14, `research/FINDINGS.md`)?

The result is `research/deep_research_round15.json`: 45 probes (USA 14, EUR 17, GLB 14) in 16 themes, in the format
`p2a try --file` reads. **Nothing in it has been simulated.** The paper facts below were checked with web searches on
25 Oct 2026; points not re-checked are marked *from memory*. The expressions passed the engine's static analyzer
offline. They also ran end to end through `p2a try` on a synthetic catalog, where every role found its intended field
and none of the decoys.

## How to run

```bash
python3 -m p2a sync --no-docs                                   # plus once per scope:
python3 -m p2a sync --region EUR --universe TOP2500 --no-docs
python3 -m p2a sync --region GLB --universe MINVOL1M --no-docs
python3 -m p2a try --file research/deep_research_round15.json --route regular --no-sim   # dry run: fills, validation
python3 -m p2a try --file research/deep_research_round15.json --route regular             # simulate all 45
python3 -m p2a try --file research/deep_research_round15.json --route regular --region EUR  # or one region
```

- Each probe names its own region, universe and delay. `{name}` slots are filled from that scope's live catalog using
  the probe's `roles` specs: exact ids first, then description patterns. A probe whose role finds nothing there is
  skipped and reported.
- Read the dry run before simulating. 26 probes depend on roles, and their descriptions have not been seen live outside
  the USA fields this account has used.

## How the papers were chosen

- **Quality.** Top journals (Journal of Finance, JFE, RFS, JFQA, The Accounting Review), award winners, or papers whose
  result was replicated outside their own sample.
- **Regional evidence.** Published anomalies have not decayed outside the U.S. Jacobs and Müller (2020, JFE) built
  241 anomalies in 39 countries; only the U.S. shows a robust post-publication decline. One replication finds that 61%
  of U.S. anomalies replicate in Europe (single test), and Europe keeps the most survivors after a multiple-testing
  adjustment (27%). Jensen, Kelly and Pedersen (2023, JF) find their 153 factors hold out of sample in 93 countries.
- **Realistic expectations.** Chen, Lopez-Lira and Zimmermann find that about half of a predictor's in-sample return
  survives after the original sample, for peer-reviewed and data-mined predictors alike. Expect probes near half the
  papers' strength. Composites (`p2a combine`) are how this account turns such parts into submittable alphas.
- **Fit with this account.** The probes use information that is not the stock's own price where possible (round 7). They
  avoid ideas already measured here: option smirk and IV innovations, lending, call tone, recommendation and
  target-price revisions, insider buying and the vendor forecasts.

## The ideas

| theme | papers (venue) | regional evidence | probes |
|---|---|---|---|
| Net issuance (FIN) | Pontiff-Woodgate 2008 JF; McLean-Pontiff-Watanabe 2009 JFE; Daniel-Titman 2006 JF; Daniel-Hirshleifer-Sun 2020 RFS; Manconi-Peyer-Vermaelen 2019 JFQA | 41 countries; buybacks in 31 countries | composite issuance 1y and 5y in USA, EUR, GLB |
| Return seasonality | Heston-Sadka 2008 JFE, 2010 JFQA; Keloharju-Linnainmaa-Nyberg 2016 JF | 14 developed markets incl. 12 European | USA, EUR, GLB |
| Overnight-daytime tug of war | Akbas-Boehmer-Jiang-Koch 2022 JFE; Lou-Polk-Skouras 2019 JFE | U.S. | USA, EUR, GLB (ports) |
| High-volume return premium | Kaniel-Ozoguz-Starks 2012 JFE; Gervais-Kaniel-Mingelgrin 2001 JF | 41 countries | EUR, GLB (USA failed in round 8) |
| Volatility of volatility | Baltussen-van Bekkum-van der Grient 2018 JFQA | U.S. and Europe, about 8%/yr | USA x2, EUR |
| Target price relative to industry | Da-Schaumburg 2011 JFM; Dechow-You 2020 TAR | U.S. | USA x2, EUR, GLB |
| Long-term growth over-optimism | Bordalo-Gennaioli-La Porta-Shleifer 2019 JF | U.S. | USA, EUR, GLB |
| Analyst forecast bias | van Binsbergen-Han-Lopez-Lira 2023 RFS | U.S. | USA |
| Bold revisions | Gleason-Lee 2003 TAR; Clement-Tse 2005 JF | U.S. | USA, EUR |
| Cash-based and gross profitability | Ball-Gerakos-Linnainmaa-Nikolaev 2016 JFE; Novy-Marx 2013 JFE; Asness-Frazzini-Pedersen 2019 RAS | international (Huber-Hanauer; QMJ in 24 countries) | USA, EUR x2, GLB x2 |
| Asset growth | Cooper-Gulen-Schill 2008 JF; Watanabe-Xu-Yao-Yu 2013 JFE | international, larger in developed markets | EUR, GLB |
| Fresh information ("anomaly time") | Bowles-Reed-Ringgenberg-Thornock 2024 JF; Engelberg-McLean-Pontiff 2018 JF | U.S. | cash profitability held only while fresh: USA, EUR, GLB |
| Residual momentum | Blitz-Huij-Martens 2011 JEF; Blitz-Hanauer-Vidojevic 2020 IREF | developed and emerging, incl. Japan | EUR, GLB |
| News-day drift | Jiang-Li-Wang 2021 JFE; Chen-Kelly-Xiu (LLM news, 16 markets, working paper) | U.S.; news text in 16 markets | USA, EUR, GLB |
| Carbon-transition premium | Bolton-Kacperczyk 2023 JF, 2021 JFE | 77 countries (contested) | EUR level, GLB growth |
| Short-sale disclosure | Jank-Roling-Smajlbegovic 2021 JFE | Germany / EU rule | EUR |

### Net issuance: the strongest international evidence

- McLean, Pontiff and Watanabe (2009) studied 41 non-U.S. countries. Issuance predicts returns more significantly than
  size or momentum, about as strongly as book-to-market, for small and large firms. Outside the U.S. it is driven by low
  returns after issuance. It is stronger where issuing and repurchasing are easier.
- Buyback announcements in 31 non-U.S. countries earn positive short- and long-run excess returns that are not takeover
  compensation (Manconi, Peyer and Vermaelen 2019, JFQA best paper).
- Daniel, Hirshleifer and Sun (2020) make issuance (FIN) one of two behavioral factors that explain a broad set of
  anomalies.
- **BRAIN form.** `log(cap / ts_delay(cap, k)) - ts_sum(log(1 + returns), k)` is Daniel-Titman's composite issuance:
  growth in market value that returns do not explain. It needs only price-volume fields, so it validates in every
  region. EUR and GLB rank within country, which removes currency effects in `cap`.

### Seasonality: same calendar month, earlier years

- Heston and Sadka (2010) covered Canada, Japan and 12 European countries. A stock that beat its market in a calendar
  month keeps doing so in that month for up to five years. Global seasonal strategies beat non-seasonal ones by over 1%
  a month and are weakly correlated across countries.
- Keloharju et al. (2016) report about 13% a year from same-calendar-month selection in the U.S.
- **BRAIN form.** `ts_sum(ts_delay(returns, 231 + 252k), 21)` is the return over the coming month k+1 years ago. The
  probe averages five years with `add(..., filter=true)`, so young stocks keep a signal.

### Overnight versus daytime returns

- Akbas et al. (2022) measure the tug of war between overnight noise traders and daytime arbitrageurs: the frequency of
  days with a positive overnight return followed by a negative daytime return, against its 12-month average. More
  intense months predict higher returns, because daytime arbitrageurs over-correct.
- Lou et al. (2019) show that momentum profits accrue overnight and other anomalies intraday, most strongly in large,
  high-price stocks.
- **BRAIN form.** `open` against the previous `close`, and `close` against `open`. The probes use `if_else(..., 1, 0)`
  flags rather than boolean arithmetic.

### Visibility: the high-volume return premium

- Kaniel, Ozoguz and Starks (2012) find that stocks with unusually high weekly volume earn more over the next month in
  41 developed and emerging countries. Risk and liquidity do not explain it. It is larger where visibility changes more
  (investor recognition).
- The U.S. version failed on this account in round 8, so only EUR and GLB get probes.

### Options: volatility of volatility

- Baltussen, van Bekkum and van der Grient (2018): stocks with volatile implied volatility underperform by about 8% a
  year in the U.S. and Europe, distinct from at least 20 known predictors.
- On this account, changes of the option surface were the most unique information found (round 8). The two USA probes
  use the opt3 fields of the submitted composites and the barely used option-horizon dataset. EUR options coverage was
  thin in round 13.

### Analysts' expectations

- **Long-term growth.** Bordalo et al. (2019): stocks with the most optimistic long-term growth forecasts earn less than
  the most pessimistic, because analysts over-extrapolate (diagnostic expectations).
- **Forecast bias.** van Binsbergen, Han and Lopez-Lira (2023): analyst forecasts are biased upward relative to a
  machine-learning benchmark. The bias predicts lower returns and fills the short legs of many anomalies, and the most
  over-forecast firms issue stock. The probe proxies the bias with forecast minus last actual EPS, over price.
- **Target prices.** Da and Schaumburg: target-price-implied returns predict within an industry, which removes analysts'
  industry-wide optimism (*from memory*; only the venue was confirmed this session). A Dechow and You draft finds
  consensus targets implied 22.7% a year against 9.3% realized. Earlier rounds tried target-price z-scores and revision counts,
  not the level against peers. EUR and GLB rank within country x industry cells, so target and price share a currency.
- **Bold revisions.** Gleason and Lee (2003): the market fails to separate high-innovation revisions from herding ones,
  and the drift is corrected around later announcements. The USA ids come from model26 (test fixture).

### Fundamentals: profitability, investment and timing

- **Cash profitability.** Ball et al. (2016): cash-based operating profitability predicts better than accrual-based
  profitability and subsumes the accrual anomaly. Huber and Hanauer (working paper) find the same internationally.
- **Asset growth.** Watanabe et al. (2013): the asset-growth effect holds internationally and is larger in more developed,
  more efficiently priced markets.
- **Fresh information.** Bowles et al. (2024): anomaly returns concentrate in the first month after information release
  and decay soon after. Engelberg et al. (2018): anomaly returns are 50% higher on news days and six times higher on
  earnings days. The "fresh" probes hold cash profitability only while the latest report is at most about six weeks
  old. Compare each with its ungated twin.
- USA gets only cash profitability. Gross profitability and investment are mainstream U.S. production factors.

### Residual momentum, news drift, carbon, short disclosure

- **Residual momentum** works in developed and emerging markets, including Japan where raw momentum fails (Blitz,
  Hanauer and Vidojevic). It is in the momentum family, so check its reference exposure.
- **News-day drift.** Jiang, Li and Wang (2021): prices drift for several days in the direction of the news-day move,
  without reversal, more when investors are distracted. Chen, Kelly and Xiu's LLM news predictions work in 16 markets.
  The probe sums only news-day returns. No-news returns are left out because they reverse, and reversal is crowded.
- **Carbon** (speculative). Bolton and Kacperczyk (2023): across 14,400 firms in 77 countries, returns rise with emission
  levels (more where climate policy is strict, as in Europe) and with emission growth (more in less developed
  economies). Later work disputes part of it (*from memory*), and BRAIN may not carry emissions data.
- **Short disclosure** (speculative). Jank, Roling and Smajlbegovic (2021): short positions bunch just below the EU
  disclosure threshold. The working paper reports -1.0 to -1.4% a month where that constraint binds. This needs
  position data on BRAIN.

## Left out, and why

- **MAX / lottery stocks** (Bali-Cakici-Whitelaw 2011; European evidence in Walkshäusl 2014): `ts_max` does not exist on
  this account (the validator rejects it), and the effect leans on low volatility, a crowded reference factor.
- **Price delay** (Hou-Moskowitz 2005): mostly an illiquidity and size effect.
- **Stambaugh-Yuan MGMT/PERF factors**: a replication thesis found them failing across 88 markets. The composite mispricing score held in developed
  markets (Jacobs 2016). The combiner can rebuild such a composite from the parts above once they are simulated.
- **Earnings announcement premium** (Barber et al. 2013, nine of 20 countries significant): it needs expected
  announcement dates, and earnings-date timing failed here in round 7.
- **52-week high**: momentum in disguise.
- **Agnostic fundamental analysis** (Bartram-Grinblatt 2021, 36 countries): it needs a monthly regression on about 21
  accounting items. BRAIN's `regression_proj` takes one regressor.

## After the run

1. `p2a references --region <R> --universe <U>`: which probes are a crowded factor in disguise.
2. `p2a combine --region <R> --universe <U> --simulate`. Natural composites:
   - FIN: 1-year plus 5-year issuance;
   - issuance, asset growth and cash profitability (the management-controlled anomalies);
   - vol-of-vol with the option channels.
   The combiner now also requires the last-two-years estimate to clear the bar.
3. `p2a decrowd` for eligible results above 0.65 production correlation; then `p2a uniqueness` and `p2a check`.
4. Record the measurements in `research/FINDINGS.md` as round 15.

## Sources (searched 25 Oct 2026)

- McLean, Pontiff, Watanabe 2009: https://ideas.repec.org/a/eee/jfinec/v94y2009i1p1-17.html
- Manconi, Peyer, Vermaelen 2019: https://jfqa.org/?p=3373
- Daniel, Hirshleifer, Sun 2020: https://ideas.repec.org/a/oup/rfinst/v33y2020i4p1673-1736..html
- Heston, Sadka 2010: https://ideas.repec.org/a/cup/jfinqa/v45y2010i05p1133-1160_00.html
- Keloharju, Linnainmaa, Nyberg 2016 (NBER w20815): https://www.nber.org/papers/w20815.pdf
- Akbas, Boehmer, Jiang, Koch 2022: https://ideas.repec.org/a/eee/jfinec/v145y2022i3p850-875.html
- Lou, Polk, Skouras 2019: https://researchonline.lse.ac.uk/id/eprint/87481
- Kaniel, Ozoguz, Starks 2012: https://ideas.repec.org/a/eee/jfinec/v103y2012i2p255-279.html
- Baltussen, van Bekkum, van der Grient 2018: https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/unknown-unknowns-uncertainty-about-risk-and-stock-returns/6E0E98349D20C1DCF67F3A0452361B80
- Da, Schaumburg (venue): https://www.kellogg.northwestern.edu/academics-research/research/detail/2008/relative-valuation-and-analyst-target-price-forecasts/?p=1
- Bordalo, Gennaioli, La Porta, Shleifer 2019 (NBER w23863): https://www.nber.org/papers/w23863.pdf
- van Binsbergen, Han, Lopez-Lira 2023: https://ideas.repec.org/a/oup/rfinst/v36y2023i6p2361-2396..html
- Gleason, Lee 2003: https://iro.uiowa.edu/esploro/outputs/journalArticle/Analyst-Forecast-Revisions-and-Market-Price/9984380448602771
- Ball, Gerakos, Linnainmaa, Nikolaev 2016: https://faculty.tuck.dartmouth.edu/images/uploads/faculty/joseph-gerakos/Ball,_Gerakos,_Linnainmaa,_et_al._2016.pdf
- Watanabe, Xu, Yao, Yu 2013: https://repository.hku.hk/bitstream/10722/188473/1/content.pdf
- Bowles, Reed, Ringgenberg, Thornock 2024: https://papers.ssrn.com/author=3568822
- Engelberg, McLean, Pontiff 2018: https://ideas.repec.org/a/bla/jfinan/v73y2018i5p1971-2001.html
- Blitz, Hanauer, Vidojevic: https://papers.ssrn.com/author=3570942
- Jiang, Li, Wang 2021: https://ideas.repec.org:443/a/eee/jfinec/v141y2021i2p573-599.html
- Chen, Kelly, Xiu (LLM news): https://nlpecofin.web.ox.ac.uk/node/3041271
- Bolton, Kacperczyk 2023: https://academicnewsletter.sufe.edu.cn/info/359044
- Jank, Roling, Smajlbegovic 2021: https://www.bundesbank.de/en/publications/research/discussion-papers/flying-under-the-radar-the-effects-of-short-sale-disclosure-rules-on-investor-behavior-and-stock-prices-662740
- Jacobs, Müller 2020: https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301618
- International replication (Europe 61%): https://www.sciencedirect.com/science/article/abs/pii/S0261560622001449
- Jensen, Kelly, Pedersen 2023 (NBER w28432): https://nber.org/system/files/working_papers/w28432/w28432.pdf
- Chen, Lopez-Lira, Zimmermann: https://arxiv.org/html/2212.10317v5
- Stambaugh-Yuan factors out of sample (88 markets): https://dalspace.library.dal.ca/handle/10222/80378
- Barber, De George, Lehavy, Trueman 2013: https://lbsresearch.london.edu/id/eprint/391
- Bartram, Grinblatt 2021: https://papers.ssrn.com/abstract=3223539
