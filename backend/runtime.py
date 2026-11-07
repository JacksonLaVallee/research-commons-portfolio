"""Tool calls, the job queue, the event dispatcher and the worker loop.

call_tool returns the Step 3 envelope. Job tools insert a row in `job`; the
worker process claims it atomically and runs the same handler. The dispatcher
turns graph events into follow-up jobs in the same transaction that marks the
event handled.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback

from . import db
from .tools import TOOLS, Ctx, ToolError, Cancelled, check_inputs, approval_check

# Pair-01 Step 3 event -> job wiring. gaps.find is never event-triggered.
RULES = {
    "paper.added": [
        ("graph.rebuild_links", lambda ids: {"node_ids": ids}),
        ("evidence.extract", lambda ids: {"paper_ids": ids}),
        ("fieldmap.assign", lambda ids: {"paper_ids": ids}),
    ],
    "claims.added": [
        ("evidence.compare", lambda ids: {"claim_ids": [i for i in ids if i.startswith("clm-")]}),
    ],
    "run.finished": [
        ("writing.brief", lambda ids: {"kind": "thread", "run_ids": [ids[0]]}),
    ],
}


def _env(status, component=None, **kw):
    out = {"status": status, "warnings": kw.pop("warnings", []), "provenance": kw.pop("provenance", {"component": component})}
    out.update(kw)
    return out


def enqueue(c, name, inp, caller, parent_event_id=None):
    """Insert a job row. Caller owns the transaction."""
    jid = db.next_id(c, "job")
    c.execute("INSERT INTO job VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (jid, name, json.dumps(inp), "queued", 0.0, "Queued", "[]", None, None, caller, parent_event_id, db.now(), None, None))
    db.emit(c, "job.queued", caller, [jid], {"kind": name, "parent_event_id": parent_event_id}, handled=True)
    return jid


def call_tool(c, name, inp, caller="ui"):
    t = TOOLS.get(name)
    if not t:
        return _env("error", error={"code": "not_found", "message": "No tool %r." % name, "retryable": False})
    try:
        inp, warnings = check_inputs(t, inp)
        if t.mode == "stream":
            raise ToolError("invalid_input", "%s is streamed from POST /api/chat." % name)
        if t.needs_approval:
            pending = approval_check(c, inp)
            if pending:
                return _env("needs_approval", t.component, data=pending, warnings=warnings)
        if t.mode == "job":
            with db.tx(c):
                jid = enqueue(c, name, inp, caller)
            return _env("queued", t.component, job_id=jid, warnings=warnings)
        ctx = Ctx(c, caller)
        data = t.handler(ctx, inp)
        return _env("ok", data=data, warnings=warnings, provenance=dict(ctx.provenance, component=t.component))
    except ToolError as e:
        return _env("error", t.component, error={"code": e.code, "message": e.message, "retryable": e.retryable})
    except Exception as e:  # pragma: no cover - surfaced to the UI
        traceback.print_exc()
        return _env("error", t.component, error={"code": "internal", "message": "%s: %s" % (type(e).__name__, e), "retryable": True})


def summarize(result):
    if not isinstance(result, dict):
        return ""
    parts = []
    for k, v in result.items():
        if isinstance(v, list) and k.endswith("ids") and v:
            parts.append("%d %s" % (len(v), k.replace("_ids", "").replace("_", " ")))
    for k in ("cites_added", "similar_added", "k", "row_count"):
        if k in result:
            parts.append("%s %s" % (result[k], k.replace("_", " ")))
    for k in ("results", "assignments", "checks", "comments", "ranked", "topics", "summaries"):
        if isinstance(result.get(k), list):
            parts.append("%d %s" % (len(result[k]), k))
    if "grounding" in result and isinstance(result["grounding"], dict) and "rate" in result["grounding"]:
        parts.append("grounding rate %s" % result["grounding"]["rate"])
    return ", ".join(parts[:4])


# ---------------------------------------------------------------- worker

def dispatch_once(c):
    rows = c.execute("SELECT * FROM event WHERE handled_at IS NULL ORDER BY id LIMIT 20").fetchall()
    for ev in rows:
        ids = json.loads(ev["target_ids"])
        with db.tx(c):
            if c.execute("SELECT handled_at FROM event WHERE id=?", (ev["id"],)).fetchone()["handled_at"]:
                continue
            for name, make in RULES.get(ev["type"], []):
                inp = make(ids)
                if any(isinstance(v, list) and not v for v in inp.values()):
                    continue
                enqueue(c, name, check_inputs(TOOLS[name], inp)[0], "dispatcher", ev["id"])
            c.execute("UPDATE event SET handled_at=? WHERE id=?", (db.now(), ev["id"]))
    return len(rows)


def claim(c):
    with db.tx(c):
        row = c.execute("SELECT id FROM job WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
        if not row:
            return None
        c.execute("UPDATE job SET status='running', started_at=?, message='Started' WHERE id=? AND status='queued'", (db.now(), row["id"]))
        db.emit(c, "job.started", "worker", [row["id"]], {}, handled=True)
    return row["id"]


def run_job(c, jid):
    job = db.job_dict(c.execute("SELECT * FROM job WHERE id=?", (jid,)).fetchone())
    t = TOOLS[job["kind"]]
    ctx = Ctx(c, job["caller"], jid, live=True)
    ctx.actor = "%s %s" % (t.component.split()[0], t.name)
    status, result, error = "succeeded", None, None
    try:
        result = t.handler(ctx, job["params"])
    except Cancelled:
        status, error = "cancelled", {"code": "cancelled", "message": "Cancelled by the researcher."}
    except ToolError as e:
        status, error = "failed", {"code": e.code, "message": e.message, "retryable": e.retryable}
    except Exception as e:
        traceback.print_exc()
        status, error = "failed", {"code": "internal", "message": "%s: %s" % (type(e).__name__, e), "retryable": True}
    with db.tx(c):
        if not c.execute("SELECT 1 FROM job WHERE id=?", (jid,)).fetchone():
            return  # workspace was reset while the job ran
        c.execute("UPDATE job SET status=?, progress=?, result=?, error=?, finished_at=?, message=?, steps=? WHERE id=?",
                  (status, 1.0 if status == "succeeded" else None, json.dumps(result) if result is not None else None,
                   json.dumps(error) if error else None, db.now(),
                   "Done: " + summarize(result) if status == "succeeded" else (error or {}).get("message"),
                   json.dumps(ctx.steps), jid))
        db.emit(c, "job.%s" % ("finished" if status == "succeeded" else status), ctx.actor, [jid],
                {"kind": job["kind"], "summary": summarize(result), "error": error, "provenance": ctx.provenance}, handled=True)


def worker_main(threads=3, log=print):
    c = db.connect()
    db.init_schema(c)
    with db.tx(c):
        n = c.execute("UPDATE job SET status='interrupted', message='Worker restarted while running; retry from the UI' "
                      "WHERE status IN ('running','cancel_requested')").rowcount
    if n:
        log("worker: marked %d interrupted job(s)" % n)
    stop = threading.Event()

    def loop(i):
        conn = db.connect()
        while not stop.is_set():
            try:
                if i == 0:
                    dispatch_once(conn)
                jid = claim(conn)
                if jid:
                    log("worker[%d]: running %s" % (i, jid))
                    run_job(conn, jid)
                else:
                    time.sleep(0.25)
            except Exception:
                traceback.print_exc()
                time.sleep(1)

    ts = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(threads)]
    for t in ts:
        t.start()
    log("worker: %d threads polling the job table, dispatcher on thread 0" % threads)
    parent = int(os.environ.get("VRP_PARENT_PID") or 0)
    try:
        while True:
            time.sleep(1)
            if parent and os.getppid() != parent:
                log("worker: parent process exited; stopping")
                break
    except KeyboardInterrupt:
        pass
    stop.set()
