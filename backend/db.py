"""SQLite workspace shared by the API process and the worker process.

Tables follow pair-01 Step 2: generic node/edge plus side tables for passages,
jobs, events (outbox + activity log), artifacts and topic snapshots.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import re
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.environ.get("VRP_WORKSPACE") or os.path.join(ROOT, ".workspace")
DB_PATH = os.path.join(WORKSPACE, "platform.sqlite")
DATA_DIR = os.path.join(WORKSPACE, "data")
PROJECT_ID = "default"
ACTIVE_PROJECT = ContextVar("project", default="default")

def project_dir(project_id=None):
    pid = project_id or ACTIVE_PROJECT.get()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", pid):
        raise ValueError("Invalid project ID")
    return Path(WORKSPACE) / 'projects' / pid

def data_dir():
    p = project_dir() / 'data'
    p.mkdir(parents=True, exist_ok=True)
    return str(p)

SCHEMA = """
CREATE TABLE IF NOT EXISTS project(id TEXT PRIMARY KEY, name TEXT, question TEXT, settings TEXT);
CREATE TABLE IF NOT EXISTS node(
  id TEXT PRIMARY KEY, project_id TEXT, type TEXT, title TEXT, props TEXT,
  origin TEXT, review_status TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS edge(
  id TEXT PRIMARY KEY, project_id TEXT, src_id TEXT, dst_id TEXT, type TEXT,
  confidence REAL, evidence_passage_id TEXT, props TEXT, origin TEXT,
  review_status TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS passage(id TEXT PRIMARY KEY, document_id TEXT, page INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS job(
  id TEXT PRIMARY KEY, kind TEXT, params TEXT, status TEXT, progress REAL, message TEXT,
  steps TEXT, result TEXT, error TEXT, caller TEXT, parent_event_id INTEGER,
  created_at TEXT, started_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS event(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, type TEXT, actor TEXT,
  target_ids TEXT, data TEXT, handled_at TEXT);
CREATE TABLE IF NOT EXISTS artifact(
  id TEXT PRIMARY KEY, kind TEXT, name TEXT, mime TEXT, content TEXT, source_id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS snapshot(id TEXT PRIMARY KEY, created_at TEXT, props TEXT);
CREATE TABLE IF NOT EXISTS seq(prefix TEXT PRIMARY KEY, n INTEGER);
CREATE INDEX IF NOT EXISTS node_type ON node(type);
CREATE INDEX IF NOT EXISTS edge_src ON edge(src_id);
CREATE INDEX IF NOT EXISTS edge_dst ON edge(dst_id);
CREATE INDEX IF NOT EXISTS passage_doc ON passage(document_id);
CREATE INDEX IF NOT EXISTS job_status ON job(status);
CREATE INDEX IF NOT EXISTS event_unhandled ON event(handled_at);
CREATE TABLE IF NOT EXISTS upload(id TEXT PRIMARY KEY, name TEXT, path TEXT, sha256 TEXT, bytes INTEGER, imported_id TEXT, relative_path TEXT);
CREATE TABLE IF NOT EXISTS candidate(id TEXT PRIMARY KEY, search_id TEXT, props TEXT);
CREATE TABLE IF NOT EXISTS conversation(id TEXT, seq INTEGER, role TEXT, content TEXT, created_at TEXT, PRIMARY KEY(id,seq));
"""

PREFIX = {
    "paper": "pap", "claim": "clm", "assumption": "asm", "method": "mth", "dataset": "ds",
    "topic": "top", "gap": "gap", "search": "srch", "note": "note", "experiment": "exp",
    "run": "run", "grant": "grt", "researcher": "res", "draft": "drf", "report": "rep",
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def connect(project_id=None) -> sqlite3.Connection:
    folder = project_dir(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(folder / 'platform.sqlite'), timeout=20, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=20000")
    return c


def init_schema(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA)


@contextmanager
def tx(c: sqlite3.Connection):
    """One write transaction. A graph change and its events commit together."""
    for attempt in range(50):
        try:
            c.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError:
            time.sleep(0.05 * (attempt + 1))
    else:
        c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def next_id(c: sqlite3.Connection, prefix: str) -> str:
    cur = c.execute("UPDATE seq SET n = n + 1 WHERE prefix = ?", (prefix,))
    if cur.rowcount == 0:
        c.execute("INSERT INTO seq(prefix, n) VALUES(?, 1)", (prefix,))
    n = c.execute("SELECT n FROM seq WHERE prefix = ?", (prefix,)).fetchone()[0]
    return "%s-%d" % (prefix, n)


def emit(c, type_: str, actor: str, target_ids=None, data=None, handled: bool = False) -> int:
    cur = c.execute(
        "INSERT INTO event(ts, type, actor, target_ids, data, handled_at) VALUES(?,?,?,?,?,?)",
        (now(), type_, actor, json.dumps(target_ids or []), json.dumps(data or {}), now() if handled else None),
    )
    return cur.lastrowid


def add_node(c, type_: str, title: str, props=None, origin="ai", review_status=None,
             created_by="system", id_=None, quiet=False) -> str:
    nid = id_ or next_id(c, PREFIX.get(type_, type_[:4]))
    if review_status is None:
        review_status = "unreviewed" if origin == "ai" else "accepted"
    c.execute(
        "INSERT INTO node VALUES(?,?,?,?,?,?,?,?,?)",
        (nid, ACTIVE_PROJECT.get(), type_, title, json.dumps(props or {}), origin, review_status, created_by, now()),
    )
    if not quiet:
        emit(c, "node.created", created_by, [nid], {"type": type_, "title": title}, handled=True)
    return nid


def update_props(c, node_id: str, **changes) -> dict:
    row = c.execute("SELECT props FROM node WHERE id = ?", (node_id,)).fetchone()
    props = json.loads(row["props"]) if row else {}
    props.update(changes)
    c.execute("UPDATE node SET props = ? WHERE id = ?", (json.dumps(props), node_id))
    return props


def add_edge(c, src: str, dst: str, type_: str, confidence: float = 0.7, props=None,
             origin="ai", created_by="system", passage_id=None, review_status=None, quiet=False):
    if not get_node(c, src) or not get_node(c, dst):
        raise ValueError("Both edge endpoints must exist in this project")
    existing = c.execute(
        "SELECT id FROM edge WHERE src_id=? AND dst_id=? AND type=?", (src, dst, type_)
    ).fetchone()
    if existing:
        return existing["id"]
    eid = next_id(c, "e")
    if review_status is None:
        review_status = "unreviewed" if origin == "ai" else "accepted"
    c.execute(
        "INSERT INTO edge VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, ACTIVE_PROJECT.get(), src, dst, type_, confidence, passage_id, json.dumps(props or {}),
         origin, review_status, created_by, now()),
    )
    if not quiet:
        emit(c, "edge.created", created_by, [eid, src, dst], {"type": type_}, handled=True)
    return eid


def node_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    d["props"] = json.loads(d["props"] or "{}")
    d.pop("project_id", None)
    return d


def edge_dict(row) -> dict:
    d = dict(row)
    d["props"] = json.loads(d["props"] or "{}")
    d.pop("project_id", None)
    return d


def get_node(c, node_id: str):
    return node_dict(c.execute("SELECT * FROM node WHERE id = ?", (node_id,)).fetchone())


def nodes(c, type_=None, include_dismissed=True):
    sql, args = "SELECT * FROM node", []
    where = []
    if type_:
        where.append("type = ?")
        args.append(type_)
    if not include_dismissed:
        where.append("review_status != 'dismissed'")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at, id"
    return [node_dict(r) for r in c.execute(sql, args)]


def edges(c, node_id=None, type_=None):
    sql, args, where = "SELECT * FROM edge", [], []
    if node_id:
        where.append("(src_id = ? OR dst_id = ?)")
        args += [node_id, node_id]
    if type_:
        where.append("type = ?")
        args.append(type_)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return [edge_dict(r) for r in c.execute(sql + " ORDER BY id", args)]


def passages(c, document_id: str):
    return [dict(r) for r in c.execute(
        "SELECT * FROM passage WHERE document_id = ? ORDER BY page, id", (document_id,))]


def add_artifact(c, kind: str, name: str, mime: str, content: str, source_id=None) -> str:
    aid = next_id(c, "art")
    c.execute("INSERT INTO artifact VALUES(?,?,?,?,?,?,?)", (aid, kind, name, mime, content, source_id, now()))
    return aid


def job_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    for k in ("params", "result", "steps", "error"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def reset_all(c) -> None:
    with tx(c):
        for t in ("node", "edge", "passage", "job", "artifact", "snapshot", "seq", "project"):
            c.execute("DELETE FROM %s" % t)
        c.execute("UPDATE event SET handled_at = COALESCE(handled_at, ?)", (now(),))
