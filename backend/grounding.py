"""Grounding Guard and keyword similarity (real logic, not simulated).

check_quote follows runawayfromearth a3 grounding.py: exact match first, then a
difflib fuzzy match. Pair-01 Step 2 rule: exact = verified, fuzzy = a candidate
for human review, nothing = dropped. bm25 follows the Paper Radar idea.
"""
from __future__ import annotations

import difflib
import math
import re
import unicodedata

STOP = set("""a an the and or of to in on for with by from at as is are was were be been being this that
these those it its into than then there their they them we our you your he she his her not no
but if so such can may might will would should could about over under after before during each
per also only more most less least very how what which who whom whose why when where""".split())


def _norm(text: str) -> str:
    t = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", t).strip().lower()


def check_quote(quote: str, text: str, fuzzy_threshold: float = 0.85) -> dict:
    q, t = _norm(quote), _norm(text)
    if len(q) < 8 or not t:
        return {"match": "none", "ratio": 0.0}
    if q in t:
        exact = lambda s: re.sub(r'\s+', ' ', unicodedata.normalize('NFKC',s)).strip()
        return {"match": "exact" if exact(quote) in exact(text) else "fuzzy_candidate", "ratio": 1.0}
    best = 0.0
    n = len(q)
    step = max(1, n // 6)
    for size in (n, int(n * 1.1)):
        for i in range(0, max(1, len(t) - size + 1), step):
            r = difflib.SequenceMatcher(None, q, t[i:i + size]).ratio()
            if r > best:
                best = r
    best = round(best, 3)
    return {"match": "fuzzy_candidate" if best >= fuzzy_threshold else "none", "ratio": best}


def locate(quote: str, passages: list) -> dict:
    """Best match of a quote across a document's passages."""
    best = {"match": "none", "ratio": 0.0, "passage_id": None, "page": None}
    for p in passages:
        r = check_quote(quote, p["text"])
        rank = {"exact": 2, "fuzzy_candidate": 1, "none": 0}
        if (rank[r["match"]], r["ratio"]) > (rank[best["match"]], best["ratio"]):
            best = dict(r, passage_id=p["id"], page=p["page"])
        if best["match"] == "exact":
            break
    return best


def tokens(text: str) -> list:
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9\-]+", _norm(text)):
        if w in STOP or len(w) < 3:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def overlap(a: str, b: str) -> int:
    return len(set(tokens(a)) & set(tokens(b)))


def bm25(query: str, docs: list, k1: float = 1.4, b: float = 0.75) -> list:
    """docs: list of (key, text). Returns [(key, score)] sorted, score > 0 only."""
    toks = [tokens(t) for _, t in docs]
    if not toks:
        return []
    avg = sum(len(t) for t in toks) / len(toks) or 1.0
    df = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    n = len(toks)
    q = tokens(query)
    scored = []
    for (key, _), t in zip(docs, toks):
        tf = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
        if s > 0:
            scored.append((key, round(s, 3)))
    scored.sort(key=lambda x: -x[1])
    return scored


def jaccard(a: str, b: str) -> float:
    sa, sb = set(tokens(a)), set(tokens(b))
    return len(sa & sb) / float(len(sa | sb) or 1)
