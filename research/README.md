# Research notes

Notes the engine ingests as "papers" (`python3 -m p2a ingest research/`). Each note targets one data
category so its ideas fit the current Power Pool theme (single data category: analyst, model or news).

Sources: the 42 WorldQuant BRAIN research write-ups and "Getting started" guides linked to the theme's 127
datasets (read through the logged-in support site on 2026-10-16), plus the original papers they cite and
classic published studies on the same effects. The notes are summaries in our own words with full citations;
every field id was verified against the live BRAIN catalog for USA/D1/TOP3000.

Findings from verification worth remembering:

- 38 of 50 fields recommended in the write-ups exist in USA/D1/TOP3000; the other 11 are other regions or renamed.
- Several write-up recipes pair model/news fields with `returns` or `close` (price-volume category): not allowed
  while the theme requires a single data category.
- One write-up calls `mdl109_iv` implied volatility; BRAIN describes it as a Vortex technical indicator.
- BRAIN spells `anl34_stockdivforecasts_expectedamount` in lower case (the write-up capitalises it).
- `model30` contains SYMBOL-type date fields (`period_end_*`) that are not numeric.

When a new theme starts, write or ingest notes for its categories in the same way.
