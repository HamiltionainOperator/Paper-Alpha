"""Small Okapi BM25 implementation (no external dependencies)."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("""a an the and or of to in on for by with from at as is are was were be been being this that these
those it its into than then there their they them we our you your he she his her not no but if so such can could
may might will would shall should do does did done have has had over under between within per via using use used
each other more most less least very also which who whom whose what when where why how all any both few some only""".split())


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokenize(text: str) -> list[str]:
    text = (text or "").lower().replace("_", " ")
    return [_stem(t) for t in _TOKEN.findall(text) if t not in _STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(d)) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.n = len(docs)
        self.avgdl = (sum(self.len) / self.n) if self.n else 0.0
        df = Counter()
        for c in self.tf:
            df.update(c.keys())
        self.idf = {t: math.log(1 + (self.n - k + 0.5) / (k + 0.5)) for t, k in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, dl in zip(self.tf, self.len):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out

    def top(self, query: str, k: int) -> list[tuple[int, float]]:
        sc = self.scores(query)
        order = sorted(range(len(sc)), key=lambda i: sc[i], reverse=True)
        return [(i, sc[i]) for i in order[:k]]
