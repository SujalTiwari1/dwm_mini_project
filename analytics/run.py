"""Run the analytics layer against the warehouse (thin runner: all analytics are SQL).

    python -m analytics.run               # create views, run every analytics/sql/*.sql query, run validation
    python -m analytics.run --file sales  # run just one file (views are always (re)created first)

Statement convention in the .sql files: a comment line "-- @name: <title>" names the statement that follows,
statements end with a semicolon. Results are written as CSV under analytics/reports/results/ and a run summary
under analytics/reports/. Exits non-zero on any query failure or any validation FAIL.
"""
import csv
import json
import re
import sys
import time
from pathlib import Path

from etl import config as C
from etl.load.postgres import get_engine

ROOT = Path(__file__).resolve().parent
SQL_DIR = ROOT / "sql"
from datasets import paths as _ds
REPORT_DIR = _ds.report_dir("analytics")
RESULT_DIR = REPORT_DIR / "results"
QUERY_FILES = ["sales", "branches", "inventory", "expiry", "purchases", "demand", "stockouts", "olap"]


def split_statements(text: str):
    """Yield (name, sql) pairs. Comment lines other than '-- @name:' are dropped."""
    name, buf, out = None, [], []
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"--\s*@name:\s*(.+)$", s)
        if m:
            name = m.group(1).strip()
            continue
        if s.startswith("--"):
            continue
        buf.append(line)
        if s.endswith(";"):
            out.append((name or f"statement {len(out) + 1}", "\n".join(buf).rstrip().rstrip(";")))
            name, buf = None, []
    return out


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:70]


def apply_views(conn):
    conn.exec_driver_sql((SQL_DIR / "views.sql").read_text(encoding="utf-8"))


def run_query_files(conn, files):
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    log = []
    for f in files:
        for i, (name, sql) in enumerate(split_statements((SQL_DIR / f"{f}.sql").read_text(encoding="utf-8")), 1):
            t = time.time()
            try:
                res = conn.exec_driver_sql(sql)
                cols, rows = list(res.keys()), res.fetchall()
                with open(RESULT_DIR / f"{f}__{i:02d}_{slug(name)}.csv", "w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow(cols)
                    w.writerows(rows)
                log.append({"file": f, "n": i, "name": name, "rows": len(rows), "seconds": round(time.time() - t, 2), "status": "OK"})
            except Exception as e:                      # keep going: report every failure
                conn.rollback()
                log.append({"file": f, "n": i, "name": name, "rows": 0, "seconds": round(time.time() - t, 2),
                            "status": "FAIL", "error": str(e).splitlines()[0][:200]})
    return log


def run_validation(conn):
    results = []
    for name, sql in split_statements((ROOT / "validation.sql").read_text(encoding="utf-8")):
        for check, actual, expected, status in conn.exec_driver_sql(sql).fetchall():
            results.append({"check": check, "actual": actual, "expected": expected, "status": status})
    return results


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    files = QUERY_FILES
    if "--file" in argv:
        files = [argv[argv.index("--file") + 1]]
    if "--files" in argv:                               # comma-separated subset (uploaded datasets without inventory data)
        files = argv[argv.index("--files") + 1].split(",")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    t0 = time.time()
    with engine.connect() as conn:
        # Session-level only: the default work_mem (4MB) makes the large sorts/DISTINCT aggregations spill to disk.
        conn.exec_driver_sql("SET work_mem = '128MB'")
        apply_views(conn)
        conn.commit()
        log = run_query_files(conn, files)
        validation = run_validation(conn) if (ROOT / "validation.sql").exists() and files == QUERY_FILES else []
    engine.dispose()

    fails = [q for q in log if q["status"] != "OK"]
    vfails = [v for v in validation if v["status"] == "FAIL"]
    for q in log:
        print(f"  [{q['status']:<4}] {q['file']:<10} {q['n']:>2} {q['name'][:58]:<58} {q['rows']:>5} rows {q['seconds']:>5.1f}s"
              + (f"  {q.get('error', '')}" if q["status"] != "OK" else ""))
    for v in validation:
        print(f"  [{v['status']:<4}] validation: {v['check']}: {v['actual']} (expected {v['expected']})")
    summary = {"queries": len(log), "query_failures": len(fails), "validation_checks": len(validation),
               "validation_failures": len(vfails), "seconds": round(time.time() - t0, 1), "queries_detail": log, "validation": validation}
    (REPORT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(f"Analytics run: {len(log)} queries ({len(fails)} failed), {len(validation)} validation checks ({len(vfails)} failed), {summary['seconds']}s")
    return 1 if (fails or vfails) else 0


if __name__ == "__main__":
    sys.exit(main())
