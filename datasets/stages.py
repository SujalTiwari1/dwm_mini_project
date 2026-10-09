"""Pipeline stages for an uploaded dataset. Each stage runs in its own process:

    MEDSTOCK_DATASET=<id> DATABASE_URL=<dataset db> python -m datasets.stages <stage>

and prints one final line `RESULT {json}`; a stage that cannot apply returns {"skipped": "<reason>"}.
Stages: etl, analytics, association, clustering, anomaly, forecast, decisions.
Two shapes of upload: sales only (no inventory) and sales + purchases (inventory, expiry and decisions as well).
"""
import json
import sys
import time
import warnings

import pandas as pd
from sqlalchemy import create_engine, text

from . import paths

warnings.filterwarnings("ignore")
UNKNOWN_SUPPLIER = "SUP_UNKNOWN"
FAR_FUTURE = "2099-12-31"
MIN_MEDICINES_FOR_CLUSTERING = 30


def _money(s: pd.Series) -> pd.Series:
    return s.astype(float).map("{:.2f}".format)


def build_raw_tables(sales: pd.DataFrame, meds: pd.DataFrame, purchases=None, batches=None, suppliers=None) -> dict:
    """The 7 source tables in the shape the ETL expects.

    Sales only: master data a sales file cannot provide is filled with explicit 'Unknown' values; placeholder batches
    ('NOBATCH-<medicine>') exist only so each sales line has a batch; no purchases and no inventory are created.
    With purchases: real lots (plus the implied OPENING lots) and the FEFO-allocated sales are used.
    """
    cats = sorted(meds["category"].unique())
    cat_id = {c: f"CAT{i:03d}" for i, c in enumerate(cats, 1)}
    sell = sales.assign(_v=sales["quantity"] * sales["unit_selling_price"].astype(float)).groupby("medicine_id").agg(v=("_v", "sum"), q=("quantity", "sum"))
    price = (sell["v"] / sell["q"])
    if purchases is not None:
        cost = purchases.assign(_v=purchases["quantity"] * purchases["unit_purchase_price"].astype(float)).groupby("medicine_id").agg(v=("_v", "sum"), q=("quantity", "sum"))
        price = price.combine_first(cost["v"] / cost["q"])
    price = price.reindex(meds["medicine_id"]).fillna(1.0).clip(lower=0.01)
    medicines = pd.DataFrame({
        "medicine_id": meds["medicine_id"], "medicine_name": meds["medicine_name"], "category_id": meds["category"].map(cat_id),
        "manufacturer": "Unknown", "dosage_form": "Unknown", "strength": "Unknown",
        "base_price": meds["medicine_id"].map(price).map("{:.2f}".format), "demand_profile": "UNKNOWN"})
    branch_ids = set(sales["branch_id"])
    if purchases is not None:
        branch_ids |= set(purchases["branch_id"])
    branch_ids = sorted(branch_ids)
    out = {
        "categories": pd.DataFrame({"category_id": list(cat_id.values()), "category_name": list(cat_id.keys())}),
        "medicines": medicines,
        "branches": pd.DataFrame({"branch_id": branch_ids, "branch_name": branch_ids, "city": "Unknown", "area": "Unknown"}),
    }
    if purchases is None:
        units = sales.groupby("medicine_id")["quantity"].sum()
        first = sales["transaction_date"].min()
        out["suppliers"] = pd.DataFrame({"supplier_id": [UNKNOWN_SUPPLIER], "supplier_name": ["Unknown supplier"], "city": ["Unknown"]})
        out["batches"] = pd.DataFrame({
            "batch_id": "NOBATCH-" + medicines["medicine_id"], "medicine_id": medicines["medicine_id"], "supplier_id": UNKNOWN_SUPPLIER,
            "manufacture_date": first, "expiry_date": FAR_FUTURE,
            "initial_quantity": medicines["medicine_id"].map(units).fillna(1).clip(lower=1).astype("int64"), "purchase_price": medicines["base_price"]})
        out["purchases"] = pd.DataFrame(columns=["purchase_id", "purchase_date", "branch_id", "supplier_id", "medicine_id", "batch_id",
                                                 "quantity", "unit_purchase_price", "total_cost"])
    else:
        sup = suppliers.copy()
        if UNKNOWN_SUPPLIER in set(batches["supplier_id"]) and not (sup["supplier_id"] == UNKNOWN_SUPPLIER).any():
            sup = pd.concat([sup, pd.DataFrame({"supplier_id": [UNKNOWN_SUPPLIER], "supplier_name": ["Unknown supplier"], "city": ["Unknown"]})], ignore_index=True)
        out["suppliers"] = sup.drop_duplicates("supplier_id").reset_index(drop=True)
        out["batches"] = batches
        out["purchases"] = purchases
    out["sales"] = sales
    return out


def _ensure_database(dataset_id: str) -> None:
    admin = create_engine(paths.admin_db_url(), isolation_level="AUTOCOMMIT")
    name = paths.db_name(dataset_id)
    with admin.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first():
            conn.exec_driver_sql(f'CREATE DATABASE "{name}"')       # name is generated server-side (validated id), never user text
    admin.dispose()


def _read(raw_dir, name, **kw):
    return pd.read_csv(raw_dir / name, dtype=str, keep_default_na=False, **kw)


def stage_etl() -> dict:
    from etl.load.dimensions import load_dimensions
    from etl.load.postgres import analyze_all, copy_dataframe, create_schema, truncate_all
    from etl.transform.dimensions import build_dimensions
    from etl.transform.inventory import build_fact_inventory
    from etl.transform.purchases import build_fact_purchase
    from etl.transform.sales import build_fact_sales
    from .allocation import allocate_fefo

    dataset_id = paths.current_id()
    raw_dir = paths.raw_dir(dataset_id)
    sales = _read(raw_dir, "sales_clean.csv")
    sales["quantity"] = sales["quantity"].astype("int64")
    meds = _read(raw_dir, "medicine_master.csv")
    full = (raw_dir / "purchases_clean.csv").exists()
    t = time.time()
    warnings_out, alloc_stats = [], None
    start, end = pd.Timestamp(sales["transaction_date"].min()), pd.Timestamp(sales["transaction_date"].max())

    if full:
        purchases = _read(raw_dir, "purchases_clean.csv")
        purchases["quantity"] = purchases["quantity"].astype("int64")
        batches = _read(raw_dir, "batches_clean.csv")
        batches["initial_quantity"] = batches["initial_quantity"].astype("int64")
        suppliers = _read(raw_dir, "suppliers_clean.csv")
        sales, op_p, op_b, alloc_stats = allocate_fefo(sales, purchases, batches, start.strftime("%Y-%m-%d"))
        purchases = pd.concat([purchases, op_p], ignore_index=True)
        batches = pd.concat([batches, op_b], ignore_index=True)
        raw = build_raw_tables(sales, meds, purchases, batches, suppliers)
        share = alloc_stats["share_of_sales_from_opening_stock"]
        if alloc_stats["opening_units_estimated"]:
            warnings_out.append(
                f"Stock was estimated for {alloc_stats['pairs_with_opening_stock']:,} branch–medicine pairs: {alloc_stats['opening_units_estimated']:,} units "
                f"({share:.0%} of units sold) were sold without a matching purchase and are treated as opening stock. Stock levels are estimates"
                + ("; with this share the stock-based decisions are indicative only." if share > 0.2 else "."))
        sales_clean_path = raw_dir / "sales_allocated.csv"
        sales.to_csv(sales_clean_path, index=False)
    else:
        raw = build_raw_tables(sales, meds)

    dims, keys = build_dimensions(raw, start, end)
    fact_sales = build_fact_sales(raw, keys, dims["dim_date"])
    facts = {"fact_sales": fact_sales}
    inv_totals = None
    if full:
        facts["fact_purchase"] = build_fact_purchase(raw, keys, dims["dim_date"])
        facts["fact_inventory"], inv_totals = build_fact_inventory(dims, fact_sales, facts["fact_purchase"])

    _ensure_database(dataset_id)
    engine = create_engine(paths.db_url(dataset_id), future=True)
    with engine.begin() as conn:
        create_schema(conn)
        truncate_all(conn)
        loaded = load_dimensions(conn, dims)
        for name, df in facts.items():
            loaded[name] = copy_dataframe(conn, name, df)
        analyze_all(conn)
    with engine.connect() as conn:
        n, units, revenue, orphans = conn.execute(text(
            "SELECT COUNT(*), COALESCE(SUM(f.quantity),0), COALESCE(SUM(f.total_amount),0), "
            "COUNT(*) FILTER (WHERE m.medicine_key IS NULL OR b.branch_key IS NULL) "
            "FROM warehouse.fact_sales f LEFT JOIN warehouse.dim_medicine m USING (medicine_key) "
            "LEFT JOIN warehouse.dim_branch b USING (branch_key)")).one()
        inv_check = None
        if full:
            inv_check = conn.execute(text(
                "SELECT COALESCE(SUM(closing_quantity) FILTER (WHERE date_key = (SELECT MAX(date_key) FROM warehouse.fact_inventory)), 0), "
                "COALESCE(SUM(purchased_quantity),0) - COALESCE(SUM(sold_quantity),0) - COALESCE(SUM(expired_quantity),0), "
                "COALESCE(SUM(sold_quantity),0) FROM warehouse.fact_inventory")).one()
    engine.dispose()
    expected_rev = round(float(pd.to_numeric(sales["total_amount"]).sum()), 2)
    exp_units = int(sales["quantity"].sum())
    checks = [
        {"check": "fact_sales rows equal cleaned upload rows", "expected": len(sales), "actual": int(n), "passed": int(n) == len(sales)},
        {"check": "units sold reconcile", "expected": exp_units, "actual": int(units), "passed": int(units) == exp_units},
        {"check": "revenue reconciles (INR)", "expected": expected_rev, "actual": round(float(revenue), 2), "passed": abs(float(revenue) - expected_rev) < 0.01},
        {"check": "no orphan dimension keys", "expected": 0, "actual": int(orphans), "passed": int(orphans) == 0},
    ]
    if full:
        checks += [
            {"check": "final stock = purchased - sold - expired", "expected": int(inv_check[1]), "actual": int(inv_check[0]), "passed": int(inv_check[0]) == int(inv_check[1])},
            {"check": "inventory sold units equal sales units", "expected": exp_units, "actual": int(inv_check[2]), "passed": int(inv_check[2]) == exp_units},
        ]
    if not all(c["passed"] for c in checks):
        raise RuntimeError("warehouse reconciliation failed: " + json.dumps([c for c in checks if not c["passed"]]))
    return {"mode": "sales + purchases" if full else "sales only", "rows_loaded": {k: int(v) for k, v in loaded.items()}, "checks": checks,
            "allocation": alloc_stats, "inventory_totals": inv_totals, "warnings": warnings_out, "seconds": round(time.time() - t, 1)}


def stage_analytics() -> dict:
    from analytics import run as analytics_run

    has_inventory = (paths.raw_dir() / "purchases_clean.csv").exists()
    analytics_run.main([] if has_inventory else ["--files", "sales,branches,demand,olap"])
    summary = json.loads((analytics_run.REPORT_DIR / "run_summary.json").read_text(encoding="utf-8"))
    failed = [q["name"] for q in summary["queries_detail"] if q["status"] != "OK"]
    vfail = [v["check"] for v in summary.get("validation", []) if v["status"] == "FAIL"]
    return {"queries": summary["queries"], "query_failures": len(failed), "failed_queries": failed[:10],
            "validation_checks": summary["validation_checks"], "validation_failures": len(vfail), "failed_checks": vfail[:10], "seconds": summary["seconds"]}


def stage_association() -> dict:
    from data_mining import config as C
    from data_mining.association import rules as assoc
    from data_mining.features import build_features as bf

    engine, conn = bf.open_connection()
    try:
        n_tx = conn.execute(text("SELECT COUNT(DISTINCT transaction_id) FROM warehouse.fact_sales")).scalar()
        # keep a minimum absolute support of 5 baskets so small uploads do not produce noise rules
        C.ASSOCIATION["min_support"] = max(C.ASSOCIATION["min_support"], 5 / max(n_tx, 1))
        res = assoc.mine(conn, sensitivity=False)
    finally:
        conn.close()
        engine.dispose()
    out = C.REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    res["frequent_itemsets"].to_csv(out / "frequent_itemsets.csv", index=False)
    res["rules"].to_csv(out / "association_rules.csv", index=False)
    summary = json.dumps(res["summary"], indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    (out / "association_summary.json").write_text(summary, encoding="utf-8")
    s = res["summary"]
    return {"transactions": int(s["transactions"]), "frequent_itemsets": int(s["frequent_itemsets"]), "useful_rules": int(s["useful_rules_after_filter"])}


def stage_clustering() -> dict:
    from data_mining import config as C
    from data_mining import run as mining_run
    from data_mining.clustering import medicine_clusters as clus
    from data_mining.features import build_features as bf

    engine, conn = bf.open_connection()
    try:
        n_med = conn.execute(text("SELECT COUNT(*) FROM warehouse.dim_medicine")).scalar()
        if n_med < MIN_MEDICINES_FOR_CLUSTERING:
            return {"skipped": f"Clustering needs at least {MIN_MEDICINES_FOR_CLUSTERING} medicines; this dataset has {n_med}."}
        res = clus.run(conn)
    finally:
        conn.close()
        engine.dispose()
    C.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    mining_run._write_clusters(res)
    return {"clusters": int(res["selected_k"]), "silhouette": round(float(res["silhouette"]), 3), "medicines": int(n_med)}


def stage_anomaly() -> dict:
    from data_mining import config as C
    from data_mining import run as mining_run
    from data_mining.anomaly import detect
    from data_mining.features import build_features as bf

    engine, conn = bf.open_connection()
    try:
        cube = bf.load_daily_cube(conn)
        lots = bf.load_purchase_lots(conn)
        if cube["units"].shape[0] < 120:
            return {"skipped": "Anomaly detection needs at least 120 days of history."}
        anoms, infos, _ = detect.detect_all(cube, lots)
    finally:
        conn.close()
        engine.dispose()
    C.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    anoms.to_csv(C.REPORT_DIR / "anomalies.csv", index=False)
    summary = mining_run._anomaly_summary(anoms, infos)
    (C.REPORT_DIR / "anomaly_summary.json").write_text(json.dumps(summary, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    return {"flagged_rows": int(len(anoms)), "detector_sets": {k: v["flagged_rows"] for k, v in summary["detector_sets"].items()}}


def stage_forecast() -> dict:
    from ml_forecasting import config as C
    from ml_forecasting import upload_run

    upload_run.main()
    s = json.loads((C.REPORT_DIR / "forecast_summary.json").read_text(encoding="utf-8"))
    return {"pairs_forecast": s["pairs_forecast"], "pairs_total": s["pairs_total"], "seconds": s["runtime_seconds"],
            "test_wape": {h: m["ml_selected"]["WAPE"] for h, m in s["metrics_test"].items()}}


def stage_decisions() -> dict:
    from decision_support import config as C
    from decision_support import upload_run

    if not C.FORECASTS_CSV.exists():
        return {"skipped": "Decision support needs the demand forecast, which was not produced (at least 180 days of sales are needed)."}
    return upload_run.main()


STAGES = {"etl": stage_etl, "analytics": stage_analytics, "association": stage_association, "clustering": stage_clustering,
          "anomaly": stage_anomaly, "forecast": stage_forecast, "decisions": stage_decisions}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in STAGES:
        print("usage: python -m datasets.stages {" + "|".join(STAGES) + "}", file=sys.stderr)
        return 2
    result = STAGES[argv[0]]()
    print("RESULT " + json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
