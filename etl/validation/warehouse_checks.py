"""Warehouse validation.

Two layers:
  1. sql/validation.sql      - self-consistency of the loaded warehouse (orphans, reconciliation, expiry, ...)
  2. raw-vs-warehouse checks - counts and measures recomputed independently from the frozen CSVs
                               (in exact integer cents), plus the inventory closing/expiry totals recomputed
                               from natural IDs with a different code path than the ETL.
Generator metadata (quality_report.json) is used only as an *expectation* to cross-check, never as a source.

Run standalone:  python -m etl.validation.warehouse_checks
"""
import json
import re
import sys
from decimal import Decimal

import pandas as pd

from .. import config as C
from ..extract.csv_loader import extract
from ..load.postgres import get_engine
from ..transform.inventory import money_cents


def _cents(series: pd.Series) -> int:
    return int(money_cents(series).sum())


def _dec(cents: int) -> Decimal:
    return Decimal(cents) / Decimal(100)


def run_sql_file_checks(conn):
    sql = (C.SQL_DIR / "validation.sql").read_text(encoding="utf-8")
    sql = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    results = []
    for stmt in (s.strip() for s in sql.split(";")):
        if not stmt:
            continue
        for check_name, actual, expected, status in conn.exec_driver_sql(stmt).fetchall():
            results.append({"source": "sql", "check": check_name, "actual": actual, "expected": expected, "status": status})
    return results


def independent_inventory_expectation(raw):
    """Closing stock / expired units from natural IDs only (pandas, no warehouse keys)."""
    p, s, b = raw["purchases"], raw["sales"], raw["batches"]
    end = max(s["transaction_date"].max(), p["purchase_date"].max())
    rec = p.groupby(["branch_id", "batch_id"])["quantity"].sum()
    sol = s.groupby(["branch_id", "batch_id"])["quantity"].sum()
    rem = rec.sub(sol, fill_value=0).rename("remaining").reset_index()
    rem = rem.merge(b[["batch_id", "expiry_date"]], on="batch_id")
    expired = int(rem.loc[(rem["expiry_date"] <= end) & (rem["remaining"] > 0), "remaining"].sum())
    purchased, sold = int(p["quantity"].sum()), int(s["quantity"].sum())
    return {"purchased": purchased, "sold": sold, "expired": expired, "closing": purchased - sold - expired}


def run_raw_comparison(conn, raw):
    out = []

    def check(name, expected, actual):
        out.append({"source": "raw", "check": name, "expected": str(expected), "actual": str(actual),
                    "status": "PASS" if expected == actual else "FAIL"})

    def scalar(sql):
        return conn.exec_driver_sql(sql).scalar()

    W = C.SCHEMA
    # dimensions
    for dim, src, label in [("dim_category", "categories", "categories"), ("dim_medicine", "medicines", "medicines"),
                            ("dim_branch", "branches", "branches"), ("dim_supplier", "suppliers", "suppliers"),
                            ("dim_batch", "batches", "batches")]:
        check(f"{dim} rows = raw {label}", len(raw[src]), scalar(f"SELECT COUNT(*) FROM {W}.{dim}"))
    lo = min(raw["sales"]["transaction_date"].min(), raw["purchases"]["purchase_date"].min())
    hi = max(raw["sales"]["transaction_date"].max(), raw["purchases"]["purchase_date"].max())
    days = (pd.Timestamp(hi) - pd.Timestamp(lo)).days + 1
    check("dim_date rows = calendar days of the data", days, scalar(f"SELECT COUNT(*) FROM {W}.dim_date"))
    check("dim_date first date", lo, str(scalar(f"SELECT MIN(full_date) FROM {W}.dim_date")))
    check("dim_date last date", hi, str(scalar(f"SELECT MAX(full_date) FROM {W}.dim_date")))
    # sales
    s, p = raw["sales"], raw["purchases"]
    check("fact_sales rows = raw sales rows", len(s), scalar(f"SELECT COUNT(*) FROM {W}.fact_sales"))
    check("fact_sales distinct transactions", s["transaction_id"].nunique(), scalar(f"SELECT COUNT(DISTINCT transaction_id) FROM {W}.fact_sales"))
    check("fact_sales SUM(quantity)", int(s["quantity"].sum()), int(scalar(f"SELECT SUM(quantity) FROM {W}.fact_sales")))
    check("fact_sales SUM(total_amount)", _dec(_cents(s["total_amount"])), scalar(f"SELECT SUM(total_amount) FROM {W}.fact_sales"))
    check("fact_sales SUM(discount)", _dec(_cents(s["discount"])), scalar(f"SELECT SUM(discount) FROM {W}.fact_sales"))
    # purchases
    check("fact_purchase rows = raw purchases rows", len(p), scalar(f"SELECT COUNT(*) FROM {W}.fact_purchase"))
    check("fact_purchase SUM(quantity)", int(p["quantity"].sum()), int(scalar(f"SELECT SUM(quantity) FROM {W}.fact_purchase")))
    check("fact_purchase SUM(total_cost)", _dec(_cents(p["total_cost"])), scalar(f"SELECT SUM(total_cost) FROM {W}.fact_purchase"))
    # inventory (independent recomputation)
    exp = independent_inventory_expectation(raw)
    days_n = days
    check("fact_inventory rows = days x branches x medicines", days_n * len(raw["branches"]) * len(raw["medicines"]),
          scalar(f"SELECT COUNT(*) FROM {W}.fact_inventory"))
    check("fact_inventory SUM(purchased_quantity)", exp["purchased"], int(scalar(f"SELECT SUM(purchased_quantity) FROM {W}.fact_inventory")))
    check("fact_inventory SUM(sold_quantity)", exp["sold"], int(scalar(f"SELECT SUM(sold_quantity) FROM {W}.fact_inventory")))
    check("fact_inventory SUM(expired_quantity)", exp["expired"], int(scalar(f"SELECT SUM(expired_quantity) FROM {W}.fact_inventory")))
    check("closing inventory (last day) = purchased - sold - expired",
          exp["closing"], int(scalar(f"SELECT SUM(closing_quantity) FROM {W}.fact_inventory WHERE date_key = (SELECT MAX(date_key) FROM {W}.dim_date)")))
    # cross-check against the generator's own ledger (expectation only)
    qr = C.METADATA_DIR / "quality_report.json"
    if qr.exists():
        q = json.loads(qr.read_text(encoding="utf-8"))
        eq = q["inventory"]["inventory_equation"]
        check("closing inventory matches generator ledger", eq["closing"], exp["closing"])
        check("expired units match generator ledger", eq["expired_writeoff"], exp["expired"])
        check("stockout branch-medicine-days match generator quality report", q["inventory"]["stockout_branch_medicine_days"],
              int(scalar(f"SELECT COUNT(*) FROM {W}.fact_inventory WHERE closing_quantity = 0")))
    # dimension leakage guard
    cols = {r[0] for r in conn.exec_driver_sql(
        f"SELECT column_name FROM information_schema.columns WHERE table_schema = '{W}'").fetchall()}
    leaked = sorted(c for c in cols if re.search(r"demand_profile|anomal|association|ground_truth", c))
    check("no generator metadata columns in the warehouse", [], leaked)
    return out


def run_all(conn=None, raw=None):
    own = conn is None
    engine = None
    if own:
        engine = get_engine()
        conn = engine.connect()
    try:
        raw = raw if raw is not None else extract()
        results = run_sql_file_checks(conn) + run_raw_comparison(conn, raw)
    finally:
        if own:
            conn.close()
            engine.dispose()
    return results


def print_results(results):
    for r in results:
        print(f"  [{r['status']:<4}] {r['check']}: {r['actual']}" + (f"  (expected {r['expected']})" if r["expected"] not in ("info",) else ""))
    fails = [r for r in results if r["status"] == "FAIL"]
    print(f"Warehouse validation: {len(results)} checks, {len(fails)} failed")
    return len(fails)


if __name__ == "__main__":
    res = run_all()
    sys.exit(1 if print_results(res) else 0)
