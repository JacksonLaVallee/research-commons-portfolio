"""Tool Registry: the pair-01 Step 3 tool contracts, with validated, registered component handlers.

One definition per tool drives GET /api/tools, POST /api/tools/{name}, the chat
tool list and the worker. Handlers read and write the SQLite graph. Live services are installed by components.install().
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import time

from . import db, grounding as G, recipe as R

TOOLS = {}


class ToolError(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


class Cancelled(Exception):
    pass


class Tool:
    def __init__(self, name, component, mode, side_effect, needs_approval, description, inputs, example, handler):
        self.name, self.component, self.mode = name, component, mode
        self.side_effect, self.needs_approval = side_effect, needs_approval
        self.description, self.inputs, self.example, self.handler = description, inputs, example, handler

    def spec(self):
        type_map={'str':'string','int':'integer','bool':'boolean','list':'array','object':'object'}
        schema={'type':'object','properties':{k:{'type':type_map.get(v['type'].split('|')[0],'string'),'description':v.get('desc','')} for k,v in self.inputs.items()},
                'required':[k for k,v in self.inputs.items() if v.get('required')],'additionalProperties':False}
        return {"name": self.name, "component": self.component, "mode": self.mode,
                "side_effect": self.side_effect, "needs_approval": self.needs_approval,
                "description": self.description, "inputs": self.inputs, "input_schema":schema, "example": self.example}


def tool(name, component, mode="sync", side_effect="read", needs_approval=False, desc="", inputs=None, example=None):
    def wrap(fn):
        TOOLS[name] = Tool(name, component, mode, side_effect, needs_approval, desc, inputs or {}, example or {}, fn)
        return fn
    return wrap


def I(type_, required=False, desc="", default=None):
    d = {"type": type_, "required": required, "desc": desc}
    if default is not None:
        d["default"] = default
    return d


class Ctx:
    """Handler context. Sync calls get no-op progress; the worker supplies a live one."""

    def __init__(self, c, caller="ui", job_id=None, live=False):
        self.c, self.caller, self.job_id, self.live = c, caller, job_id, live
        self.steps, self.provenance = [], {"source_ids": []}
        self.actor = caller

    def step(self, msg, progress=None):
        self.steps.append({"t": db.now(), "msg": msg})
        if self.job_id:
            with db.tx(self.c):
                self.c.execute("UPDATE job SET steps=?, message=?, progress=COALESCE(?, progress) WHERE id=?",
                               (json.dumps(self.steps), msg, progress, self.job_id))
                db.emit(self.c, "job.progress", self.actor, [self.job_id],
                        {"message": msg, "progress": progress}, handled=True)
            if self.cancelled():
                raise Cancelled()

    def sleep(self, s):
        if self.live:
            time.sleep(s * float(os.environ.get("VRP_SPEED", "1")))

    def cancelled(self):
        if not self.job_id:
            return False
        row = self.c.execute("SELECT status FROM job WHERE id=?", (self.job_id,)).fetchone()
        return row is not None and row["status"] == "cancel_requested"

    def llm(self, task, model="demo-fast"):
        self.provenance.update({"model": "deterministic", "prompt_version": "%s.v2" % task})


def check_inputs(t: Tool, inp: dict):
    inp = dict(inp or {})
    warnings = []
    for k, spec in t.inputs.items():
        if k not in inp or inp[k] in (None, ""):
            if spec.get("required"):
                raise ToolError("invalid_input", "Missing required input %r." % k)
            if "default" in spec:
                inp[k] = spec["default"]
            continue
        v, ty = inp[k], spec["type"]
        ok = {"str": isinstance(v, str), "int": isinstance(v, int) and not isinstance(v, bool),
              "bool": isinstance(v, bool), "list": isinstance(v, list), "object": isinstance(v, dict)}.get(ty.split("|")[0], True)
        if not ok and "|" not in ty:
            raise ToolError("invalid_input", "Input %r should be %s." % (k, ty))
    for k in inp:
        if k not in t.inputs:
            warnings.append("Unknown input %r ignored." % k)
    return {k: v for k, v in inp.items() if k in t.inputs}, warnings


# ---------------------------------------------------------------- helpers

def papers_by_key(c):
    return {n["props"].get("key"): n for n in db.nodes(c, "paper")}




def keys_to_ids(c, text):
    kmap = {k: n["id"] for k, n in papers_by_key(c).items()}
    return re.sub(r"\[([a-z]+\d{4})\]", lambda m: "[%s]" % kmap.get(m.group(1), m.group(1)), text or "")


def short_cite(n):
    a = n["props"].get("authors") or ["?"]
    first = a[0].split()[-1]
    return "%s%s %s" % (first, " et al." if len(a) > 2 else (" & " + a[1].split()[-1] if len(a) == 2 else ""), n["props"].get("year", ""))




def claims_of_paper(c, pid):
    out = []
    for e in db.edges(c, pid):
        if e["type"] == "derived_from" and e["dst_id"] == pid:
            n = db.get_node(c, e["src_id"])
            if n and n["type"] == "claim":
                out.append(n)
    return out


def node_text(n):
    p = n["props"]
    return " ".join(str(x) for x in [n["title"], p.get("text", ""), p.get("abstract", ""), p.get("query", ""),
                                      p.get("rationale", ""), p.get("objective", ""), p.get("body_md", "")] if x)


def ref_ids(text):
    return re.findall(r"\[((?:pap|clm|asm|gap|run|exp|top|note|grt|drf|rep|srch|mth|ds|res)-\d+)\]", text or "")


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", (text or "").strip()) if s.strip()]


def recipe_hash(steps, base, dataset_ids):
    return hashlib.sha1(json.dumps([steps, base, sorted(dataset_ids)], sort_keys=True).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- C1 Research Graph

@tool("graph.get", "C1 Research Graph", desc="One node with its edge counts.",
      inputs={"node_id": I("str", True)}, example={"node_id": "pap-1"})
def graph_get(ctx, inp):
    n = db.get_node(ctx.c, inp["node_id"])
    if not n:
        raise ToolError("not_found", "No node %s." % inp["node_id"])
    counts = {}
    for e in db.edges(ctx.c, n["id"]):
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return {"node": n, "edge_counts": counts}


@tool("graph.neighbors", "C1 Research Graph", desc="Nodes and edges within 1-2 hops.",
      inputs={"node_id": I("str", True), "hops": I("int", default=1), "node_types": I("list"),
              "edge_types": I("list"), "limit": I("int", default=200)},
      example={"node_id": "asm-1", "hops": 1})
def graph_neighbors(ctx, inp):
    root = db.get_node(ctx.c, inp['node_id'])
    if not root:
        raise ToolError('not_found','Node not found.')
    seen, frontier, edges = {inp["node_id"]}, [inp["node_id"]], {}
    for _ in range(max(1, min(2, inp["hops"]))):
        nxt = []
        for nid in frontier:
            for e in db.edges(ctx.c, nid):
                if e['review_status'] == 'dismissed':
                    continue
                if inp.get("edge_types") and e["type"] not in inp["edge_types"]:
                    continue
                other = e["dst_id"] if e["src_id"] == nid else e["src_id"]
                on = db.get_node(ctx.c, other)
                if not on or on['review_status']=='dismissed' or (inp.get("node_types") and on["type"] not in inp["node_types"]):
                    continue
                edges[e["id"]] = e
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
        frontier = nxt
    ids = [inp['node_id']] + sorted(seen - {inp['node_id']})
    nodes = [db.get_node(ctx.c, i) for i in ids[:max(1,min(200,inp['limit']))]]
    visible = {n['id'] for n in nodes}
    return {"nodes": nodes, "edges": [e for e in edges.values() if e['src_id'] in visible and e['dst_id'] in visible]}


@tool("graph.find", "C1 Research Graph", desc="Keyword search over node titles and text (BM25).",
      inputs={"text": I("str"), "types": I("list"), "review_status": I("str"), "origin": I("str"), "limit": I("int", default=20)},
      example={"text": "self-report sleep", "types": ["claim", "assumption"]})
def graph_find(ctx, inp):
    ns = db.nodes(ctx.c)
    if inp.get("types"):
        ns = [n for n in ns if n["type"] in inp["types"]]
    if inp.get("review_status"):
        ns = [n for n in ns if n["review_status"] == inp["review_status"]]
    if inp.get("origin"):
        ns = [n for n in ns if n["origin"] == inp["origin"]]
    if inp.get("text"):
        scores = dict(G.bm25(inp["text"], [(n["id"], node_text(n)) for n in ns]))
        ns = sorted([n for n in ns if n["id"] in scores], key=lambda n: -scores[n["id"]])
        return {"nodes": [{"id": n["id"], "type": n["type"], "title": n["title"], "score": scores[n["id"]]}
                          for n in ns[: inp["limit"]]]}
    return {"nodes": [{"id": n["id"], "type": n["type"], "title": n["title"], "score": None} for n in ns[: inp["limit"]]]}


@tool("graph.add_note", "C1 Research Graph", side_effect="write", desc="Add a note; [[id]] links become 'about' edges.",
      inputs={"body_md": I("str", True), "about_ids": I("list", default=[])},
      example={"body_md": "Check diary bias in our pilot [[asm-1]]", "about_ids": []})
def graph_add_note(ctx, inp):
    about = list(dict.fromkeys(list(inp["about_ids"]) + re.findall(r"\[\[([a-z]+-\d+)\]\]", inp["body_md"])))
    origin = "researcher" if ctx.caller == "ui" else "ai"
    with db.tx(ctx.c):
        title = re.sub(r"\[\[([a-z]+-\d+)\]\]", r"\1", inp["body_md"])[:70]
        nid = db.add_node(ctx.c, "note", title, {"body_md": inp["body_md"]}, origin=origin, created_by=ctx.actor)
        eids = [db.add_edge(ctx.c, nid, a, "about", 1.0, origin=origin, created_by=ctx.actor, review_status="auto")
                for a in about if db.get_node(ctx.c, a)]
        db.emit(ctx.c, "note.added", ctx.actor, [nid] + about, {}, handled=True)
    return {"node_id": nid, "edge_ids": eids}


@tool("graph.rebuild_links", "C1 Research Graph", mode="job", side_effect="write",
      desc="Rebuild 'cites' (reference matching) and 'similar' (keyword TF-IDF) edges.",
      inputs={"node_ids": I("list", desc="papers to relink; empty = whole project", default=[])},
      example={"node_ids": []})
def graph_rebuild_links(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("graph.export", "C1 Research Graph", desc="Export the graph as GraphML or Cytoscape JSON.",
      inputs={"format": I("str", default="cytoscape_json", desc="graphml | cytoscape_json"), "node_ids": I("list", default=[])},
      example={"format": "graphml"})
def graph_export(ctx, inp):
    ns = [n for n in db.nodes(ctx.c) if not inp["node_ids"] or n["id"] in inp["node_ids"]]
    ids = {n["id"] for n in ns}
    es = [e for e in db.edges(ctx.c) if e["src_id"] in ids and e["dst_id"] in ids]
    if inp["format"] == "graphml":
        esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
        body = ['<?xml version="1.0"?>', '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
                '<key id="type" for="all" attr.name="type" attr.type="string"/>',
                '<key id="title" for="node" attr.name="title" attr.type="string"/>', '<graph edgedefault="directed">']
        body += ['<node id="%s"><data key="type">%s</data><data key="title">%s</data></node>' % (n["id"], n["type"], esc(n["title"])) for n in ns]
        body += ['<edge source="%s" target="%s"><data key="type">%s</data></edge>' % (e["src_id"], e["dst_id"], e["type"]) for e in es]
        body += ["</graph>", "</graphml>"]
        content, mime, name = "\n".join(body), "application/xml", "graph.graphml"
    else:
        content = json.dumps({"elements": {"nodes": [{"data": {"id": n["id"], "type": n["type"], "label": n["title"]}} for n in ns],
                                           "edges": [{"data": {"id": e["id"], "source": e["src_id"], "target": e["dst_id"], "type": e["type"]}} for e in es]}}, indent=1)
        mime, name = "application/json", "graph.cytoscape.json"
    with db.tx(ctx.c):
        aid = db.add_artifact(ctx.c, "graph_export", name, mime, content)
    return {"artifact_id": aid, "nodes": len(ns), "edges": len(es)}


# ---------------------------------------------------------------- C2 Core (library)

@tool("library.import", "C2 Core", mode="job", side_effect="write",
      desc="Import staged files: PDFs become papers (hash, copy, extract text); CSVs become datasets.",
      inputs={"upload_ids": I("list", True, "staged uploads, e.g. upl-1")}, example={"upload_ids": ["upl-1"]})
def library_import(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("library.read", "C2 Core", desc="Read a paper's passages by page or passage id.",
      inputs={"document_id": I("str", True), "pages": I("list"), "passage_ids": I("list"), "max_chars": I("int", default=8000)},
      example={"document_id": "pap-1"})
def library_read(ctx, inp):
    ps = db.passages(ctx.c, inp["document_id"])
    if not ps and not db.get_node(ctx.c, inp["document_id"]):
        raise ToolError("not_found", "No document %s." % inp["document_id"])
    if inp.get("pages"):
        ps = [p for p in ps if p["page"] in inp["pages"]]
    if inp.get("passage_ids"):
        ps = [p for p in ps if p["id"] in inp["passage_ids"]]
    out, total = [], 0
    for p in ps:
        if total + len(p["text"]) > inp["max_chars"]:
            return {"passages": out, "truncated": True}
        total += len(p["text"])
        out.append({"id": p["id"], "page": p["page"], "text": p["text"]})
    return {"passages": out, "truncated": False}


@tool("library.search_passages", "C2 Core", desc="BM25 search over passages of papers in the library.",
      inputs={"query": I("str", True), "document_ids": I("list"), "k": I("int", default=8)},
      example={"query": "diary overestimate sleep night shift"})
def library_search_passages(ctx, inp):
    rows = [dict(r) for r in ctx.c.execute("SELECT * FROM passage")]
    if inp.get("document_ids"):
        rows = [r for r in rows if r["document_id"] in inp["document_ids"]]
    scored = G.bm25(inp["query"], [(r["id"], r["text"]) for r in rows])[: min(50, inp["k"])]
    by_id = {r["id"]: r for r in rows}
    return {"hits": [{"passage_id": pid, "document_id": by_id[pid]["document_id"], "page": by_id[pid]["page"],
                      "snippet": by_id[pid]["text"], "score": s} for pid, s in scored]}


# ---------------------------------------------------------------- C3 Literature Search

def _search(ctx, inp, created_by):
    raise ToolError("configuration", "Component not registered.")


@tool("search.papers", "C3 Literature Search", mode="job", side_effect="external",
      desc="Search sources, merge, de-duplicate and screen. Saves a node in the search history tree.",
      inputs={"query": I("str", True), "sources": I("list", default=["semantic_scholar", "openalex", "arxiv"]),
              "limit": I("int", default=20), "parent_search_id": I("str"), "launched_from": I("object"), "screen": I("bool", default=True)},
      example={"query": "actigraphy sleep diary nurses", "parent_search_id": "srch-1"})
def search_papers(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("search.history", "C3 Literature Search", desc="The search history tree.",
      inputs={"root_search_id": I("str")}, example={})
def search_history(ctx, inp):
    out = []
    for n in db.nodes(ctx.c, "search"):
        p = n["props"]
        out.append({"search_id": n["id"], "parent_id": p.get("parent_search_id"), "query": p["query"],
                    "launched_from": p.get("launched_from"), "result_count": len(p.get("results", [])),
                    "included": sum(1 for r in p.get("results", []) if r.get("screen") == "include"),
                    "origin": n["origin"], "created_at": n["created_at"]})
    if inp.get("root_search_id"):
        keep, changed = {inp["root_search_id"]}, True
        while changed:
            changed = False
            for s in out:
                if s["parent_id"] in keep and s["search_id"] not in keep:
                    keep.add(s["search_id"])
                    changed = True
        out = [s for s in out if s["search_id"] in keep]
    return {"tree": out}


@tool("search.save", "C3 Literature Search", mode="job", side_effect="write",
      desc="Add search candidates to the library as papers; emits paper.added.",
      inputs={"candidate_ids": I("list", True), "search_id": I("str"), "fetch_pdf": I("bool", default=True)},
      example={"candidate_ids": ["osei2024"], "search_id": "srch-1"})
def search_save(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("search.resolve", "C3 Literature Search", desc="Resolve a DOI or title to a canonical record (CiteCheck resolver).",
      inputs={"doi": I("str"), "title": I("str"), "year": I("int")}, example={"title": "Actigraphy versus sleep diaries in shift workers"})
def search_resolve(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("search.summarize", "C3 Literature Search", mode="job", side_effect="write",
      desc="Fixed-schema summary per paper (problem, method, results, limitations), cached.",
      inputs={"paper_ids": I("list", True)}, example={"paper_ids": ["pap-1"]})
def search_summarize(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("search.export_citations", "C3 Literature Search", desc="Deterministic BibTeX / RIS / APA export.",
      inputs={"paper_ids": I("list", default=[]), "format": I("str", default="bibtex", desc="bibtex | ris | apa")},
      example={"format": "apa"})
def search_export_citations(ctx, inp):
    ps = [n for n in db.nodes(ctx.c, "paper") if not inp["paper_ids"] or n["id"] in inp["paper_ids"]]
    lines = []
    for n in ps:
        p = n["props"]
        if inp["format"] == "ris":
            lines += ["TY  - JOUR"] + ["AU  - %s" % a for a in p["authors"]] + [
                "TI  - %s" % n["title"], "JO  - %s" % p.get("venue"), "PY  - %s" % p["year"], "DO  - %s" % p.get("doi"), "ER  - ", ""]
        elif inp["format"] == "apa":
            lines.append("%s (%s). %s. *%s*. https://doi.org/%s" % (", ".join(p["authors"]), p["year"], n["title"], p.get("venue"), p.get("doi")))
        else:
            lines += ["@article{%s," % p["key"], "  author = {%s}," % " and ".join(p["authors"]), "  title = {%s}," % n["title"],
                      "  journal = {%s}," % p.get("venue"), "  year = {%s}," % p["year"], "  doi = {%s}" % p.get("doi"), "}", ""]
    ext = {"ris": "ris", "apa": "md"}.get(inp["format"], "bib")
    with db.tx(ctx.c):
        aid = db.add_artifact(ctx.c, "citations", "references.%s" % ext, "text/plain", "\n".join(lines))
    return {"artifact_id": aid, "count": len(ps)}


# ---------------------------------------------------------------- C4 Field Map





@tool("fieldmap.build", "C4 Field Map & Topics", mode="job", side_effect="write",
      desc="Cluster papers into topics (k chosen by silhouette), label them, save a snapshot.",
      inputs={"scope": I("str", default="project"), "algorithm": I("str", default="kmeans", desc="kmeans | hdbscan")},
      example={"scope": "project"})
def fieldmap_build(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("fieldmap.trends", "C4 Field Map & Topics", desc="Compare a snapshot with the previous one: grew / shrank / new / stable.",
      inputs={"snapshot_id": I("str"), "compare_to": I("str")}, example={})
def fieldmap_trends(ctx, inp):
    snaps = [dict(r, props=json.loads(r["props"])) for r in ctx.c.execute("SELECT * FROM snapshot ORDER BY created_at")]
    if not snaps:
        return {"topics": [], "snapshot_id": None}
    cur = next((s for s in snaps if s["id"] == inp.get("snapshot_id")), snaps[-1])
    idx = snaps.index(cur)
    prev = next((s for s in snaps if s["id"] == inp.get("compare_to")), snaps[idx - 1] if idx > 0 else None)
    prev_sizes = {t["key"]: t["size"] for t in prev["props"]["topics"]} if prev else {}
    out = []
    for t in cur["props"]["topics"]:
        before = prev_sizes.get(t["key"])
        trend = "new" if before is None else "grew" if t["size"] > before else "shrank" if t["size"] < before else "stable"
        out.append({"topic_id": t["topic_id"], "label": t["label"], "size": t["size"], "trend": trend,
                    "delta": t["size"] - (before or 0), "paper_ids": t["paper_ids"]})
    return {"snapshot_id": cur["id"], "compared_to": prev["id"] if prev else None, "created_at": cur["created_at"],
            "k": cur["props"]["k"], "silhouette": cur["props"]["silhouette"], "topics": out}


@tool("fieldmap.assign", "C4 Field Map & Topics", mode="job", side_effect="write",
      desc="Place new papers in existing topics without a rebuild (DocSort incremental).",
      inputs={"paper_ids": I("list", True)}, example={"paper_ids": ["pap-6"]})
def fieldmap_assign(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


# ---------------------------------------------------------------- C5 Claim & Evidence



@tool("evidence.extract", "C5 Claim & Evidence", mode="job", side_effect="write",
      desc="Extract claims, assumptions and methods with verbatim quotes; skeptic pass drops ungrounded claims; emits claims.added.",
      inputs={"paper_ids": I("list", True), "skeptic": I("bool", default=True)}, example={"paper_ids": ["pap-6"]})
def evidence_extract(ctx, inp):
    raise ToolError("configuration", "Component not registered.")




@tool("evidence.compare", "C5 Claim & Evidence", mode="job", side_effect="write",
      desc="Compare study conditions, then label pairs (conflict, measured gap, scope difference, equivalent, unresolved).",
      inputs={"claim_ids": I("list", default=[]), "topic_id": I("str"), "max_pairs": I("int", default=100)},
      example={"claim_ids": []})
def evidence_compare(ctx, inp):
    raise ToolError("configuration", "Component not registered.")




@tool("evidence.check_citations", "C5 Claim & Evidence", mode="job", side_effect="write",
      desc="Dual-prompt citation verdicts: SUPPORTED / PARTIAL / NOT / UNVERIFIABLE (disagreement = NEEDS_REVIEW).",
      inputs={"paper_id": I("str"), "draft_id": I("str")}, example={"paper_id": "pap-2"})
def evidence_check_citations(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("evidence.verify_quote", "C5 Claim & Evidence", desc="Grounding Guard: exact, fuzzy candidate, or none.",
      inputs={"quote": I("str", True), "document_id": I("str", True)},
      example={"quote": "Diaries overestimated sleep duration by a mean of 48 minutes", "document_id": "pap-4"})
def evidence_verify_quote(ctx, inp):
    ps = db.passages(ctx.c, inp["document_id"])
    if not ps:
        raise ToolError("not_found", "No passages for %s." % inp["document_id"])
    return G.locate(inp["quote"], ps)


# ---------------------------------------------------------------- C6 Gaps & Assumptions

def _evidence_item(c, node_id, quote=None, passage_id=None):
    n = db.get_node(c, node_id)
    return {"node_id": node_id, "title": n["title"] if n else node_id, "quote": quote or (n["props"].get("quote") if n else None),
            "passage_id": passage_id or (n["props"].get("passage_id") if n else None)}




@tool("gaps.find", "C6 Gaps & Assumptions", mode="job", side_effect="write",
      desc="Budgeted agent loop (inspect -> retrieve -> verify -> flag or abstain) over a graph area; flags wait for review.",
      inputs={"scope_ids": I("list", default=[]), "gap_types": I("list", default=["untested_condition", "method_not_carried_over", "contradiction", "missing_link"]),
              "budget": I("object", default={"llm_calls": 14, "searches": 2}), "check_literature": I("bool", default=True)},
      example={"scope_ids": ["asm-1"], "budget": {"llm_calls": 14, "searches": 2}})
def gaps_find(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("gaps.explain", "C6 Gaps & Assumptions", desc="Rationale, evidence with quotes, and literature checks for one gap.",
      inputs={"gap_id": I("str", True)}, example={"gap_id": "gap-1"})
def gaps_explain(ctx, inp):
    g = db.get_node(ctx.c, inp["gap_id"])
    if not g or g["type"] != "gap":
        raise ToolError("not_found", "No gap %s." % inp["gap_id"])
    ev = g["props"].get("evidence", [])
    ps = {}
    for e in ev:
        if e.get("passage_id"):
            row = ctx.c.execute("SELECT * FROM passage WHERE id=?", (e["passage_id"],)).fetchone()
            if row:
                ps[e["passage_id"]] = dict(row)
    grounded = [G.check_quote(e["quote"], ps[e["passage_id"]]["text"])["match"] if e.get("quote") and e.get("passage_id") in ps else "none" for e in ev]
    return {"gap": g, "evidence": ev, "grounding": {"exact": grounded.count("exact"), "fuzzy_candidate": grounded.count("fuzzy_candidate"),
                                                   "none": grounded.count("none")}}


# ---------------------------------------------------------------- C7 Chat & Synthesis

@tool("chat.ask", "C7 Unified Chat & Synthesis", mode="stream", desc="Chat turn. Streamed from POST /api/chat; listed here for completeness.",
      inputs={"message": I("str", True), "conversation_id": I("str"), "context": I("object"), "max_steps": I("int", default=8)},
      example={"message": "What supports the self-report assumption?"})
def chat_ask(ctx, inp):
    raise ToolError("invalid_input", "Use POST /api/chat (streamed).")


@tool("chat.synthesize", "C7 Unified Chat & Synthesis", mode="job", side_effect="write",
      desc="Draft a grounded synthesis from papers' claims; verification pass drops ungrounded sentences.",
      inputs={"paper_ids": I("list", True), "question": I("str", default=""), "verify": I("bool", default=True)},
      example={"paper_ids": ["pap-1", "pap-2", "pap-4"]})
def chat_synthesize(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


# ---------------------------------------------------------------- C8 Funding

@tool("funding.identify", "C8 Funding", side_effect="external", desc="Find and confirm a researcher (OpenAlex, ORCID).",
      inputs={"name": I("str", True), "affiliation": I("str"), "orcid": I("str")}, example={"name": "Jordan Avery"})
def funding_identify(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("funding.find", "C8 Funding", mode="job", side_effect="external",
      desc="GrantScout pipeline: research -> hunt -> screen -> rank, with an optional read-deeper agent loop.",
      inputs={"researcher_id": I("str"), "topic_ids": I("list", default=[]), "top": I("int", default=10),
              "sweep": I("bool", default=True), "agent_loop": I("bool", default=True)},
      example={"researcher_id": "res-1"})
def funding_find(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


# ---------------------------------------------------------------- C9 Experiments & Data

def dataset_by_name(c):
    return {n["props"]["name"]: n for n in db.nodes(c, "dataset")}




@tool("experiment.catalog", "C9 Experiments & Data", desc="Registry tools a recipe may use (no arbitrary code).", example={})
def experiment_catalog(ctx, inp):
    return {"tools": R.CATALOG}


@tool("experiment.register_dataset", "C9 Experiments & Data", side_effect="write", desc="Register a staged CSV and profile its columns.",
      inputs={"upload_id": I("str", True)}, example={"upload_id": "upl-3"})
def experiment_register_dataset(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


def _validate(c, steps, base, dataset_ids):
    ds = {n["props"]["name"]: n for n in db.nodes(c, "dataset")}
    cols = {name: n["props"]["columns"] for name, n in ds.items()}
    errors, warnings, final = R.validate(steps, cols, base)
    return {"errors": errors, "warnings": warnings, "output_columns": final}


@tool("experiment.propose", "C9 Experiments & Data", side_effect="write",
      desc="AI drafts a recipe from catalog tools, with review notes and a novelty check. Approval starts 'pending'.",
      inputs={"objective": I("str", True), "dataset_ids": I("list", default=[]), "hypothesis_node_id": I("str"), "gap_id": I("str")},
      example={"objective": "Compare diary and actigraphy sleep in night-shift nurses", "gap_id": "gap-1"})
def experiment_propose(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("experiment.update_recipe", "C9 Experiments & Data", side_effect="write",
      desc="Edit a recipe's steps; revalidates and resets approval if anything changed. (Added in Step 4.)",
      inputs={"recipe_id": I("str", True), "steps": I("list", True)},
      example={"recipe_id": "exp-1", "steps": []})
def experiment_update_recipe(ctx, inp):
    c = ctx.c
    e = db.get_node(c, inp["recipe_id"])
    if not e or e["type"] != "experiment":
        raise ToolError("not_found", "No experiment %s." % inp["recipe_id"])
    p = e["props"]
    val = _validate(c, inp["steps"], p["base"], p["dataset_ids"])
    h = recipe_hash(inp["steps"], p["base"], p["dataset_ids"])
    changed = h != p["hash"]
    with db.tx(c):
        db.update_props(c, e["id"], steps=inp["steps"], validation=val, hash=h,
                        approval={"state": "pending"} if changed else p["approval"])
        if changed and p["approval"].get("state") == "approved":
            db.emit(c, "approval.reset", ctx.actor, [e["id"]], {"reason": "recipe changed"}, handled=True)
    return {"recipe_id": e["id"], "validation": val, "hash": h, "approval": "pending" if changed else p["approval"]["state"]}


def approval_check(c, inp):
    e = db.get_node(c, inp.get("recipe_id") or "")
    if not e or e["type"] != "experiment":
        raise ToolError("not_found", "No experiment %s." % inp.get("recipe_id"))
    a = e["props"].get("approval", {})
    if e["props"]["validation"]["errors"]:
        raise ToolError("invalid_input", "Recipe has validation errors; fix them first.")
    if a.get("state") != "approved" or a.get("hash") != e["props"]["hash"]:
        return {"recipe_id": e["id"], "approval": a.get("state", "pending"), "approve_in": "#/experiments/%s" % e["id"],
                "message": "A researcher must approve this exact recipe in the Experiments view before it runs."}
    return None


@tool("experiment.run", "C9 Experiments & Data", mode="job", side_effect="write", needs_approval=True,
      desc="Run an approved recipe in a child process; writes outputs, diagnostics and a reproduction script; emits run.finished.",
      inputs={"recipe_id": I("str", True)}, example={"recipe_id": "exp-1"})
def experiment_run(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


# ---------------------------------------------------------------- C10 Writing, Review & Reports

def _draft(c, did):
    d = db.get_node(c, did)
    if not d or d["type"] != "draft":
        raise ToolError("not_found", "No draft %s." % did)
    return d


@tool("writing.save", "C10 Writing, Review & Reports", side_effect="write", desc="Save the text of a draft. (Added in Step 4.)",
      inputs={"draft_id": I("str", True), "text": I("str", True)}, example={"draft_id": "drf-1", "text": "..."})
def writing_save(ctx, inp):
    _draft(ctx.c, inp["draft_id"])
    with db.tx(ctx.c):
        db.update_props(ctx.c, inp["draft_id"], text=inp["text"], cited_node_ids=sorted(set(ref_ids(inp["text"]))))
        db.emit(ctx.c, "draft.saved", ctx.actor, [inp["draft_id"]], {}, handled=True)
    return {"draft_id": inp["draft_id"], "chars": len(inp["text"])}


@tool("writing.flag_unsupported", "C10 Writing, Review & Reports", desc="Sentences with no citation, or whose citation does not back them.",
      inputs={"draft_id": I("str", True)}, example={"draft_id": "drf-1"})
def writing_flag_unsupported(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("writing.review", "C10 Writing, Review & Reports", mode="job", side_effect="write",
      desc="Independent reviewer personas; every quoted comment is checked by the Grounding Guard.",
      inputs={"draft_id": I("str", True), "personas": I("list", default=["methods", "evidence", "novelty", "clarity"])},
      example={"draft_id": "drf-1"})
def writing_review(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("writing.revise", "C10 Writing, Review & Reports", mode="job", side_effect="write",
      desc="Apply accepted comments: revision plan, new draft version, diff and response letter.",
      inputs={"draft_id": I("str", True), "review_id": I("str", True), "accept_comment_ids": I("list", default=[])},
      example={"draft_id": "drf-1", "review_id": "rep-1", "accept_comment_ids": ["c1", "c2"]})
def writing_revise(ctx, inp):
    c = ctx.c
    d = _draft(c, inp["draft_id"])
    rv = db.get_node(c, inp["review_id"])
    if not rv:
        raise ToolError("not_found", "No review %s." % inp["review_id"])
    ctx.step("Planning revisions (ReviseMate revision_planner)", 0.3)
    ctx.llm("revision_plan", "demo-smart")
    ctx.sleep(0.6)
    old = d["props"]["text"]
    new = old
    letter = ["# Response to reviewers", "", "Draft: %s" % d["title"], ""]
    applied = []
    for cm in rv["props"]["comments"]:
        accepted = cm["id"] in inp["accept_comment_ids"]
        if accepted and cm.get("fix") and cm["target"] in new:
            new = new.replace(cm["target"], cm["fix"], 1)
            applied.append(cm["id"])
            resp = "Revised. New text: \"%s\"" % cm["fix"]
        elif accepted:
            resp = "Accepted; no automatic edit available, to be addressed by hand."
        else:
            resp = "Not changed in this revision."
        letter += ["**%s reviewer (%s):** %s" % (cm["persona"].title(), cm["id"], cm["text"]), "", "> %s" % resp, ""]
    ctx.step("Rewriting %d sentence(s) and generating the response letter" % len(applied), 0.7)
    ctx.sleep(0.6)
    diff = "\n".join(difflib.unified_diff(split_sentences(old), split_sentences(new), "v%d" % d["props"]["version"],
                                          "v%d" % (d["props"]["version"] + 1), lineterm=""))
    with db.tx(c):
        v = d["props"]["version"] + 1
        nid = db.add_node(c, "draft", re.sub(r"\(v\d+\)", "(v%d)" % v, d["title"]) if "(v" in d["title"] else "%s (v%d)" % (d["title"], v),
                          dict(d["props"], version=v, text=new, cited_node_ids=sorted(set(ref_ids(new))), previous_id=d["id"]),
                          origin="ai", created_by="C10 writing.revise")
        db.add_edge(c, nid, d["id"], "derived_from", 1.0, created_by="C10 writing.revise", review_status="auto")
        a_diff = db.add_artifact(c, "diff", "%s_to_%s.diff" % (d["id"], nid), "text/plain", diff, nid)
        a_letter = db.add_artifact(c, "response_letter", "response_letter_%s.md" % nid, "text/markdown", "\n".join(letter), nid)
    return {"new_draft_id": nid, "applied_comment_ids": applied, "diff_artifact_id": a_diff, "response_letter_id": a_letter}


@tool("writing.brief", "C10 Writing, Review & Reports", mode="job", side_effect="write",
      desc="Portfolio-style brief over experiment runs (thread / executive / attention).",
      inputs={"kind": I("str", default="thread", desc="thread | executive | attention"), "run_ids": I("list", default=[])},
      example={"kind": "thread", "run_ids": ["run-1"]})
def writing_brief(ctx, inp):
    raise ToolError("configuration", "Component not registered.")


@tool("writing.export", "C10 Writing, Review & Reports", desc="Export a draft as Markdown with a reference list.",
      inputs={"draft_id": I("str", True), "format": I("str", default="md")}, example={"draft_id": "drf-1"})
def writing_export(ctx, inp):
    raise ToolError("configuration", "Component not registered.")
