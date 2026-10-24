You are a quantitative researcher reading a finance paper to find tradeable equity signals that can become WorldQuant BRAIN alphas: daily, cross-sectional, long/short stock selection computed from per-stock data.

The platform's data comes in these categories (id: name - subcategories):
{{categories}}

# Paper: {{title}}
---
{{text}}
---

Extract up to {{max}} distinct, testable hypotheses from this paper. For each one give:
- title: short name
- mechanism: why it should predict future stock returns (the economic story the paper tells)
- signal_construction: how to compute it in words - inputs, transformation, look-back horizon, and which stocks are bought vs sold
- data_concepts: the quantities needed (e.g. "consensus EPS revisions over 30 days", "news sentiment per story")
- candidate_categories: category ids from the list above that could supply those quantities (ids only, from the list)
- horizon: short (days to weeks), medium (1-6 months) or long (6+ months)
- expected_turnover: low, medium or high
- keywords: 5-10 search terms for finding matching data fields (e.g. "revision", "surprise", "dispersion")
- evidence: where in the paper the result is shown and how strong it is

Only include hypotheses computable from daily per-stock data. If the paper relies on data the platform may lack, map it to the closest category and say so in data_concepts. Prefer ideas the paper actually tests over ones it only mentions.

Answer with JSON only:
{"paper_summary": "...", "hypotheses": [{"title": "...", "mechanism": "...", "signal_construction": "...", "data_concepts": ["..."], "candidate_categories": ["..."], "horizon": "...", "expected_turnover": "...", "keywords": ["..."], "evidence": "..."}]}
