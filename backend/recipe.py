"""Recipe engine: registry tools only, no arbitrary code.

Follows ronah123 a3 core/registry.py + recipe.py: every step names a catalog tool
with typed params; the recipe is validated before it runs. The worker runs this
file in a child process (`python3 recipe.py --stdin`). The same file, with the
recipe embedded, is the downloadable reproduction script.
Standard library only, Python 3.8+.
"""
import csv
import json
import math
import sys

EMBEDDED_RECIPE = None  # replaced in reproduction scripts

CATALOG = [
    {"name": "filter_rows", "params": {"column": "str", "op": "== != > >= < <= contains", "value": "str|number"},
     "limitations": "One condition per step."},
    {"name": "select_columns", "params": {"columns": "list[str]"}, "limitations": "Keeps order given."},
    {"name": "fill_missing", "params": {"column": "str", "value": "str|number"}, "limitations": "Blank cells only."},
    {"name": "join", "params": {"dataset": "str (dataset name)", "on": "str"},
     "limitations": "Left join on one key; right side must be unique per key."},
    {"name": "paired_difference", "params": {"a": "str", "b": "str", "name": "str"},
     "limitations": "Adds column a - b; rows with a blank are skipped."},
    {"name": "aggregate", "params": {"group_by": "list[str]", "metrics": "list[{column, fn: mean|sum|count|min|max}]"},
     "limitations": "Replaces the table with one row per group."},
    {"name": "correlate", "params": {"x": "str", "y": "str"},
     "limitations": "Pearson r, reported as a statistic; does not change the table."},
]
TOOL_NAMES = {t["name"] for t in CATALOG}


def _num(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in str(v) else f
    except (TypeError, ValueError):
        return v


def load_csv(path):
    with open(path, newline="", encoding='utf-8-sig') as fh:
        reader=csv.DictReader(fh)
        if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames):
            raise ValueError('CSV requires unique column names.')
        rows=[]
        for row in reader:
            if len(rows)>=100000: raise ValueError('CSV row limit exceeded (100,000).')
            if None in row: raise ValueError('CSV contains rows wider than its header.')
            converted={k:_num(v) for k,v in row.items()}
            if any(isinstance(v,float) and not math.isfinite(v) for v in converted.values()):
                raise ValueError('CSV contains non-finite numeric values.')
            rows.append(converted)
        return rows


def validate(steps, columns_by_dataset, base):
    """Simulate column flow. Returns (errors, warnings, final_columns)."""
    errors, warnings = [], []
    cols = list(columns_by_dataset.get(base, []))
    if not cols:
        errors.append("Unknown base dataset %r." % base)
    for i, s in enumerate(steps):
        tool, p = s.get("tool"), s.get("params", {})
        where = "Step %d (%s)" % (i + 1, tool)
        if tool not in TOOL_NAMES:
            errors.append("%s: not a catalog tool." % where)
            continue

        def need(col):
            if col not in cols:
                errors.append("%s: column %r does not exist (have: %s)." % (where, col, ", ".join(cols)))

        if tool == "filter_rows":
            need(p.get("column"))
            if p.get("op") not in ("==", "!=", ">", ">=", "<", "<=", "contains"):
                errors.append("%s: unknown operator %r." % (where, p.get("op")))
        elif tool == "select_columns":
            for col in p.get("columns", []):
                need(col)
            cols = [c for c in p.get("columns", []) if c in cols]
        elif tool == "fill_missing":
            need(p.get("column"))
        elif tool == "join":
            other = columns_by_dataset.get(p.get("dataset"))
            if other is None:
                errors.append("%s: unknown dataset %r." % (where, p.get("dataset")))
            else:
                need(p.get("on"))
                if p.get("on") not in other:
                    errors.append("%s: %r is not in %s." % (where, p.get("on"), p.get("dataset")))
                cols += [c for c in other if c not in cols]
        elif tool == "paired_difference":
            need(p.get("a"))
            need(p.get("b"))
            if not p.get("name"):
                errors.append("%s: give the new column a name." % where)
            else:
                cols.append(p["name"])
        elif tool == "aggregate":
            new = []
            for g in p.get("group_by", []):
                need(g)
                new.append(g)
            for m in p.get("metrics", []):
                if m.get("fn") != "count":
                    need(m.get("column"))
                if m.get("fn") not in ("mean", "sum", "count", "min", "max"):
                    errors.append("%s: unknown function %r." % (where, m.get("fn")))
                new.append("%s_%s" % (m.get("fn"), m.get("column") or "rows"))
            if not p.get("metrics"):
                errors.append("%s: add at least one metric." % where)
            cols = new
        elif tool == "correlate":
            need(p.get("x"))
            need(p.get("y"))
    return errors, warnings, cols


def _cmp(a, op, b):
    try:
        if op == "contains":
            return str(b).lower() in str(a).lower()
        if isinstance(a, (int, float)) and not isinstance(b, (int, float)):
            b = float(b)
        import operator
        return {'==':operator.eq,'!=':operator.ne,'>':operator.gt,'>=':operator.ge,'<':operator.lt,'<=':operator.le}[op](a,b)
    except (TypeError, ValueError):
        return False


def _pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pairs)
    if n < 3:
        return None, n
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx == 0 or syy == 0:
        return None, n
    return round(sxy / math.sqrt(sxx * syy), 3), n


def run(steps, tables, base):
    rows = [dict(r) for r in tables[base]]
    stats, diagnostics = [], []
    for i, s in enumerate(steps):
        tool, p = s["tool"], s.get("params", {})
        before = len(rows)
        if tool == "filter_rows":
            rows = [r for r in rows if _cmp(r.get(p["column"]), p["op"], _num(p["value"]))]
        elif tool == "select_columns":
            rows = [{c: r.get(c) for c in p["columns"]} for r in rows]
        elif tool == "fill_missing":
            for r in rows:
                if r.get(p["column"]) in (None, ""):
                    r[p["column"]] = _num(p["value"])
        elif tool == "join":
            right = {r[p["on"]]: r for r in tables[p["dataset"]]}
            if len(right)!=len(tables[p['dataset']]):
                raise ValueError('Join right-hand keys must be unique; aggregate first.')
            unmatched = 0
            for r in rows:
                other = right.get(r.get(p["on"]))
                if other is None:
                    unmatched += 1
                    continue
                for k, v in other.items():
                    r.setdefault(k, v)
            if unmatched:
                diagnostics.append({"level": "warning", "step": i + 1,
                                    "text": "%d rows had no match in %s." % (unmatched, p["dataset"])})
        elif tool == "paired_difference":
            skipped = 0
            for r in rows:
                a, b = r.get(p["a"]), r.get(p["b"])
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    r[p["name"]] = round(a - b, 3)
                else:
                    r[p["name"]] = None
                    skipped += 1
            if skipped:
                diagnostics.append({"level": "info", "step": i + 1,
                                    "text": "%d rows skipped (blank %s or %s)." % (skipped, p["a"], p["b"])})
        elif tool == "aggregate":
            groups = {}
            for r in rows:
                key = tuple(r.get(g) for g in p["group_by"])
                groups.setdefault(key, []).append(r)
            out = []
            for key in sorted(groups, key=lambda k: [str(x) for x in k]):
                g = groups[key]
                row = dict(zip(p["group_by"], key))
                for m in p["metrics"]:
                    col, fn = m.get("column"), m["fn"]
                    vals = [x.get(col) for x in g if isinstance(x.get(col), (int, float))]
                    name = "%s_%s" % (fn, col or "rows")
                    if fn == "count":
                        row[name] = len(g)
                    elif not vals:
                        row[name] = None
                    elif fn == "mean":
                        row[name] = round(sum(vals) / len(vals), 3)
                    elif fn == "sum":
                        row[name] = round(sum(vals), 3)
                    elif fn == "min":
                        row[name] = min(vals)
                    elif fn == "max":
                        row[name] = max(vals)
                out.append(row)
            rows = out
        elif tool == "correlate":
            r, n = _pearson([x.get(p["x"]) for x in rows], [x.get(p["y"]) for x in rows])
            stats.append({"step": i + 1, "name": "pearson_r(%s, %s)" % (p["x"], p["y"]), "value": r, "n": n})
            ids = {x.get("nurse_id") for x in rows if x.get("nurse_id") is not None}
            if ids and n > len(ids):
                diagnostics.append({"level": "warning", "step": i + 1, "text": (
                    "Rows are repeated measures: %d rows from %d nurses. Treat nurse as the unit "
                    "(aggregate by nurse_id first) before reading r." % (n, len(ids)))})
        diagnostics.append({"level": "trace", "step": i + 1, "text": "%s: %d -> %d rows" % (tool, before, len(rows))})
    columns = list(rows[0].keys()) if rows else []
    return {"columns": columns, "rows": rows, "row_count": len(rows), "stats": stats, "diagnostics": diagnostics}


def to_csv(columns, rows):
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _main():
    if EMBEDDED_RECIPE is not None:
        # Reproduction script: python3 repro.py name=path.csv [name=path.csv ...]
        from pathlib import Path
        paths = {name:str(Path(__file__).resolve().parent/(name+'.csv')) for name in EMBEDDED_RECIPE['datasets']}
        paths.update(dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a))
        missing = [d for d in EMBEDDED_RECIPE["datasets"] if d not in paths]
        if missing:
            sys.exit("usage: python3 %s %s" % (sys.argv[0], " ".join("%s=<path.csv>" % d for d in missing)))
        tables = {name: load_csv(paths[name]) for name in EMBEDDED_RECIPE["datasets"]}
        out = run(EMBEDDED_RECIPE["steps"], tables, EMBEDDED_RECIPE["base"])
        sys.stdout.write(to_csv(out["columns"], out["rows"]))
        for s in out["stats"]:
            sys.stderr.write("%s = %s (n=%s)\n" % (s["name"], s["value"], s["n"]))
        return
    if "--stdin" in sys.argv:
        job = json.load(sys.stdin)
        tables = {name: load_csv(path) for name, path in job["datasets"].items()}
        cols = {name: list(t[0].keys()) if t else [] for name, t in tables.items()}
        errors, _, _ = validate(job["steps"], cols, job["base"])
        if errors:
            json.dump({"ok": False, "errors": errors}, sys.stdout)
            return
        out = run(job["steps"], tables, job["base"])
        out["ok"] = True
        json.dump(out, sys.stdout)
        return
    print(json.dumps(CATALOG, indent=2))


if __name__ == "__main__":
    _main()
