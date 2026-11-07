"""Pure evidence validation and comparison rules. No network or model calls."""
import hashlib
import json
import re
import unicodedata

RELATIONS = {"consistent", "mixed", "potential_conflict", "not_comparable", "uncertain"}
DIRECTIONS = {"positive", "negative", "null", "mixed", "unclear"}
AXES = ("population", "intervention", "comparator", "outcome", "timeframe", "design")


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def normalize(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text))).strip()


def sentences(passage):
    """Index exact source spans; models select IDs instead of rewriting quotations."""
    text = normalize(passage["text"])
    spans, start = [], 0
    for boundary in re.finditer(r"(?<=[.!?])\s+", text):
        end = boundary.start()
        if end > start:
            spans.append({"id": f"{passage['id']}.s{len(spans):03d}", "text": text[start:end], "start": start, "end": end})
        start = boundary.end()
    if start < len(text):
        spans.append({"id": f"{passage['id']}.s{len(spans):03d}", "text": text[start:], "start": start, "end": len(text)})
    return spans


def validate_quote(evidence, passages):
    """Return exact offsets in the normalized passage; never fuzzy-match evidence."""
    if not isinstance(evidence, dict):
        return None
    sentence_id = evidence.get("sentence_id")
    if sentence_id:
        for passage in passages:
            for sentence in sentences(passage):
                if sentence["id"] == sentence_id:
                    return {"passage_id": passage["id"], "sentence_id": sentence_id,
                            "quote": sentence["text"], "start": sentence["start"], "end": sentence["end"],
                            "section": passage.get("section", "Text"), "page": passage.get("page")}
        return None
    pid, quote = evidence.get("passage_id"), normalize(evidence.get("quote", ""))
    passage = next((p for p in passages if p["id"] == pid), None)
    if not passage or len(quote) < 12:
        return None
    text = normalize(passage["text"])
    start = text.find(quote)
    if start < 0:
        return None
    return {"passage_id": pid, "quote": quote, "start": start, "end": start + len(quote),
            "section": passage.get("section", "Text"), "page": passage.get("page")}


def validate_extraction(raw, document):
    """Reject ungrounded findings and remove metadata without a valid source span."""
    if not isinstance(raw, dict) or not isinstance(raw.get("claims"), list):
        raise ValueError("The model did not return a claims array.")
    accepted, rejected = [], []
    for i, item in enumerate(raw["claims"][:5]):
        if not isinstance(item, dict):
            rejected.append({"index": i, "reason": "Malformed claim"})
            continue
        evidence = validate_quote(item.get("evidence"), document["passages"])
        direction = item.get("direction")
        if not evidence or direction not in DIRECTIONS or not isinstance(item.get("finding"), str):
            rejected.append({"index": i, "reason": "Finding lacks a valid source quote or direction"})
            continue
        fields, warnings = {}, []
        for name in (*AXES, "sample_size", "effect_size"):
            field = item.get("fields", {}).get(name, {}) if isinstance(item.get("fields"), dict) else {}
            proof = validate_quote(field.get("evidence"), document["passages"]) if isinstance(field, dict) else None
            value = str(field.get("value", ""))[:600] if isinstance(field, dict) else ""
            if proof and value.strip():
                fields[name] = {"value": value, "evidence": proof}
            else:
                fields[name] = {"value": "Not established in supplied text", "evidence": None}
                warnings.append(name)
        tags = item.get("tags", {})
        # Tags are model interpretations used for retrieval, never evidence of comparability.
        tags = {k: str(tags.get(k, "unknown"))[:120] for k in AXES} if isinstance(tags, dict) else {}
        limitations = []
        for lim in item.get("limitations", [])[:3]:
            if isinstance(lim, dict) and (proof := validate_quote(lim.get("evidence"), document["passages"])):
                limitations.append({"text": str(lim.get("text", ""))[:600], "evidence": proof})
        accepted.append({"id": stable_id(document["id"], evidence["passage_id"], evidence["quote"], item["finding"]),
                         "document_id": document["id"], "finding": item["finding"][:1200],
                         "direction": direction, "evidence": evidence, "fields": fields,
                         "tags": tags, "limitations": limitations, "missing_fields": warnings,
                         "review_status": "unreviewed"})
    return accepted, rejected


def guard_comparison(a, b, proposed):
    """Conservative safeguards, independent of the LLM's proposed classification."""
    if not isinstance(proposed, dict):
        raise ValueError("The model did not return a comparison object.")
    label = proposed.get("relation", "uncertain")
    label = label if label in RELATIONS else "uncertain"
    checks = proposed.get("axes", {})
    axes = {k: checks.get(k, "unknown") if checks.get(k) in {"matched", "different", "unknown"} else "unknown" for k in AXES}
    reasons = []
    for k in AXES:
        if not a["fields"].get(k, {}).get("evidence") or not b["fields"].get(k, {}).get("evidence"):
            axes[k] = "unknown"
    core = ("population", "intervention", "comparator", "outcome", "timeframe", "design")
    if any(axes[k] == "different" for k in ("intervention", "comparator", "outcome")):
        label = "not_comparable"
        reasons.append("The intervention, comparator, or outcome differs.")
    elif any(axes[k] == "unknown" for k in core):
        label = "uncertain"
        reasons.append("At least one comparison dimension lacks enough evidence.")
    elif any(axes[k] == "different" for k in core):
        label = "not_comparable"
        reasons.append("Population, design, or assessment timing differs.")
    else:
        directions = {a["direction"], b["direction"]}
        if "unclear" in directions or "mixed" in directions:
            label = "uncertain"
        elif directions == {"positive", "negative"}:
            label = "potential_conflict"
            reasons.append("Opposite reported directions warrant review of effect estimates and uncertainty.")
        elif "null" in directions and len(directions) > 1:
            label = "mixed"
            reasons.append("A significant finding and a non-significant finding do not establish a statistical contradiction.")
        elif len(directions) == 1:
            label = "consistent"
    return {"relation": label, "proposed_relation": proposed.get("relation"), "axes": axes,
            "guard_notes": reasons,
            "explanation": str(proposed.get("explanation", ""))[:2000],
            "hypotheses": [str(x)[:600] for x in proposed.get("hypotheses", [])[:3]] if isinstance(proposed.get("hypotheses", []), list) else [],
            "review_status": "unreviewed"}


def candidate_pairs(claims, limit=30):
    """Cheap retrieval: typed tags plus word overlap. This never decides relations."""
    pairs = []
    for i, a in enumerate(claims):
        for b in claims[i+1:]:
            if a["document_id"] == b["document_id"]:
                continue
            score = sum(weight for k, weight in [("outcome", 5), ("intervention", 3), ("comparator", 2), ("population", 1)]
                        if a.get("tags", {}).get(k) not in (None, "unknown", "") and a.get("tags", {}).get(k) == b.get("tags", {}).get(k))
            wa, wb = set(re.findall(r"[a-z]{4,}", a["finding"].lower())), set(re.findall(r"[a-z]{4,}", b["finding"].lower()))
            score += len(wa & wb) / max(1, len(wa | wb))
            pairs.append((score, a["id"], b["id"]))
    return sorted(pairs, key=lambda p: (-p[0], p[1], p[2]))[:limit]
