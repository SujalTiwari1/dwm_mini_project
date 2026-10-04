"""Entry point: python -m data_generator.main"""
import json
import sys

import numpy as np
import pandas as pd

from . import config as C
from .demand.demand_model import DemandModel
from .generators.batches import BatchFactory
from .generators.branches import generate_branches
from .generators.categories import generate_categories
from .generators.medicines import generate_medicines
from .generators.purchases import PurchasePlanner
from .generators.sales import SalesGenerator
from .generators.suppliers import build_supplier_map, generate_suppliers
from .inventory import InventoryLedger
from .utils import spawn_rngs
from .validation.quality_report import anomaly_visibility, build_quality_report, format_report
from .validation.validators import validate

TABLES = ["categories", "medicines", "branches", "suppliers", "batches", "purchases", "sales"]
STREAMS = ["medicines", "suppliers", "supplier_map", "demand", "batches", "purchases", "sales"]
VERSION = C.DATASET_CONFIG["dataset_version"]

PRIVATE_NOTICE = ("This file is NOT part of the analytical dataset and must not be loaded into the warehouse "
                  "or used as an input feature for analytics/ML. It is generator ground truth, kept only to "
                  "evaluate whether later algorithms rediscover the embedded patterns.")


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=_json_default), encoding="utf-8")


def _soft_warnings(R, visibility, anomalies):
    """Plausibility warnings (not integrity errors)."""
    w = []
    inv = R["inventory"]
    if inv["stockout_events"] == 0:
        w.append("no stockouts occurred")
    if inv["stockout_day_pct"] > 5:
        w.append(f"stockouts are not rare ({inv['stockout_day_pct']}% of branch-medicine-days)")
    if inv["expired_quantity"] == 0:
        w.append("no stock expired")
    if inv["expired_pct_of_purchased_units"] > 5:
        w.append(f"expired stock is not rare ({inv['expired_pct_of_purchased_units']}% of purchased units)")
    for r in R["associations"]["planted_rule_check"]:
        if r["lift"] is None or r["lift"] < 2:
            w.append(f"planted rule '{r['rule']}' has weak observed lift ({r['lift']})")
    for a in anomalies:
        v = visibility.get(a["anomaly_id"], {})
        if a["type"] in ("spike", "branch_surge") and (v.get("observed_ratio") or 0) < 1.3:
            w.append(f"{a['anomaly_id']} ({a['type']}) is barely visible: ratio {v.get('observed_ratio')}")
        if a["type"] == "drop" and (v.get("observed_ratio") or 1) > 0.75:
            w.append(f"{a['anomaly_id']} (drop) is barely visible: ratio {v.get('observed_ratio')}")
    return w


def _anomaly_summary(anomalies, sales):
    """Counts and visibility of the planted anomalies (evaluation only; labels never enter the CSVs)."""
    per_med = sales.groupby("medicine_id")["quantity"].sum().sort_values(ascending=False)
    top20 = set(per_med.index[: max(1, round(0.2 * len(per_med)))])
    demand = [a for a in anomalies if a["type"] in ("spike", "drop", "branch_surge")]

    def visible(a):
        v = a.get("observed_in_data", {})
        z = v.get("z_score")
        return z is not None and ((a["type"] == "drop" and z <= -3) or (a["type"] != "drop" and z >= 3))

    return {
        "total": len(anomalies),
        "by_type": dict(pd.Series([a["type"] for a in anomalies]).value_counts()),
        "distinct_medicines": len({a["medicine_id"] for a in anomalies}),
        "events_per_medicine_year": round(len(anomalies) / (per_med.size * len(pd.date_range(
            C.DATASET_CONFIG["start_date"], C.DATASET_CONFIG["end_date"])) / 365.25), 3),
        "affected_branches": dict(pd.Series([a["branch_id"] for a in anomalies]).value_counts()),
        "share_on_top20pct_volume_medicines": round(sum(a["medicine_id"] in top20 for a in anomalies) / max(len(anomalies), 1), 3),
        "demand_events": len(demand),
        "visible_demand_events": sum(visible(a) for a in demand),
        "median_observed_ratio": {t: round(float(pd.Series([a["observed_in_data"].get("observed_ratio") for a in demand
                                                           if a["type"] == t and a["observed_in_data"].get("observed_ratio") is not None]).median()), 2)
                                  for t in ("spike", "drop", "branch_surge")},
    }


def main() -> int:
    cfg = C.DATASET_CONFIG
    rngs = spawn_rngs(cfg["random_seed"], STREAMS)
    dates = pd.date_range(cfg["start_date"], cfg["end_date"], freq="D")

    # ---- master data --------------------------------------------------------
    categories = generate_categories()
    medicines, med_internal = generate_medicines(cfg["num_medicines"], rngs["medicines"])
    branches = generate_branches(cfg["num_branches"])
    suppliers, sup_internal = generate_suppliers(cfg["num_suppliers"], rngs["suppliers"])
    supplier_map = build_supplier_map(sup_internal, medicines, rngs["supplier_map"])

    # ---- demand model + day-by-day simulation -------------------------------
    model = DemandModel(medicines, med_internal, branches, dates, rngs["demand"])
    ledger = InventoryLedger(len(branches), len(medicines))
    batches = BatchFactory(rngs["batches"])
    planner = PurchasePlanner(medicines, med_internal, model, supplier_map, sup_internal,
                              batches, ledger, rngs["purchases"])
    sales_gen = SalesGenerator(medicines, model, ledger, dates, rngs["sales"])
    for t, ts in enumerate(dates):
        day = ts.date()
        ledger.expire(day)               # stock reaching expiry is written off
        planner.plan_day(t, day, dates)  # deliveries arrive before the day's sales
        sales_gen.generate_day(t, day)

    tables = {
        "categories": categories, "medicines": medicines, "branches": branches, "suppliers": suppliers,
        "batches": batches.to_frame(), "purchases": planner.to_frame(), "sales": sales_gen.to_frame(),
    }

    # ---- export, then validate what is actually on disk ------------------------
    C.RAW_DIR.mkdir(parents=True, exist_ok=True)
    C.METADATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        tables[name].to_csv(C.RAW_DIR / f"{name}.csv", index=False, float_format="%.2f")
    on_disk = {name: pd.read_csv(C.RAW_DIR / f"{name}.csv") for name in TABLES}
    report = validate(on_disk, supplier_map=supplier_map,
                      ledger_closing=ledger.on_hand_units() + ledger.expired_units(),
                      start=dates[0], end=dates[-1])

    # ---- quality report (statistical) ---------------------------------------------
    R = build_quality_report(on_disk, dates[0], dates[-1], model.resolved_rules, model.resolved_rules)
    anomalies = model.public_anomalies()
    visibility = anomaly_visibility(on_disk, anomalies, dates, R["_stock"])
    for a in anomalies:
        a["observed_in_data"] = visibility.get(a["anomaly_id"], {})
    R["anomalies"] = _anomaly_summary(anomalies, on_disk["sales"])
    warnings = _soft_warnings(R, visibility, anomalies)
    del R["_stock"]
    # the generator ledger and the CSV-derived reconstruction must agree on closing stock and write-offs
    ledger_ok = (R["inventory"]["total_remaining_stock"] == ledger.on_hand_units()
                 and R["inventory"]["expired_quantity"] == ledger.expired_units())
    report.add("CSV-reconstructed closing stock and expired quantity equal the generator ledger", 0 if ledger_ok else 1)

    # ---- metadata ---------------------------------------------------------------
    summary = {
        **R["basic"], "total_revenue": R["sales"]["total_revenue"],
        "total_purchase_value": round(float(on_disk["purchases"]["total_cost"].sum()), 2),
        "unfilled_demand_lines": sales_gen.lost_lines, "short_filled_lines": sales_gen.short_lines,
        "validation_checks": report.checks_run, "validation_failed_checks": len(report.failed),
        "validation_violating_rows": report.total_violations, "validation_warnings": len(warnings),
    }
    _write_json(C.METADATA_DIR / "quality_report.json", {
        "generator_version": VERSION,
        "notice": "Evaluation-only summary of the generated dataset. Not an input to analytics.",
        "validation": {"checks": report.checks_run, "failed_checks": len(report.failed),
                       "violating_rows": report.total_violations,
                       "results": [{"check": n, "violations": b} for n, b in report.results]},
        "warnings": warnings,
        **R,
    })
    _write_json(C.METADATA_DIR / "generation_metadata.json", {
        "generator_version": VERSION,
        "frozen_on": cfg["frozen_on"],
        "notice": "Synthetic data for the MedStock academic DWM project. Not real pharmacy transactions.",
        "random_seed": cfg["random_seed"],
        "date_range": [cfg["start_date"], cfg["end_date"]],
        "demand_scale": cfg["demand_scale"],
        "currency": "INR",
        "counts": {k: R["basic"][k] for k in ("medicines", "branches", "suppliers", "categories", "batches",
                                              "purchases", "sales_lines", "transactions")},
        "anomaly_events": R["anomalies"]["total"],
        "association_rules": {"configured": model.resolved_rules,
                              "probabilistic": True,
                              "add_on_probability_range": [min(r["added_probability"] for r in model.resolved_rules),
                                                           max(r["added_probability"] for r in model.resolved_rules)]},
        "config": {"dataset": cfg, "demand_profiles": C.DEMAND_PROFILES, "category_config": C.CATEGORY_CONFIG,
                   "branch_profiles": C.BRANCH_PROFILES, "trend": {"mix": C.TREND_MIX, "annual_rate": C.TREND_ANNUAL_RATE},
                   "basket_size_probs": C.BASKET_SIZE_PROBS, "sales": C.SALES_CONFIG,
                   "purchase": C.PURCHASE_CONFIG, "anomaly": C.ANOMALY_CONFIG},
        "summary": summary,
        "validation": [{"check": n, "violations": b} for n, b in report.results],
        "warnings": warnings,
        "quality_report_file": "data/metadata/quality_report.json",
        "supplier_medicine_map": {m: s_[0] for m, s_ in supplier_map.items()},
        "files": [f"data/raw/{n}.csv" for n in TABLES],
    })
    lost = {model.med_ids[m]: int(n) for m, n in enumerate(sales_gen.lost_lines_by_med) if n}
    _write_json(C.METADATA_DIR / "ground_truth_private.json", {
        "WARNING": PRIVATE_NOTICE,
        "medicine_demand_parameters": model.params.to_dict(orient="records"),
        "branch_parameters": [
            {"branch_id": model.branch_ids[b], "multiplier": float(model.branch_mult[b]),
             "category_affinity": model.branch_aff[b]} for b in range(model.B)],
        "anomalies": anomalies,
        "association_rules": {"planted": model.resolved_rules, "observed": R["associations"]["planted_rule_check"]},
        "unfilled_demand_lines_by_medicine": lost,
    })

    # ---- terminal ---------------------------------------------------------------------
    print(format_report(R))
    print("=" * 60)
    print(f"Anomalies planted: {len(anomalies)} -> " + str(dict(pd.Series([a['type'] for a in anomalies]).value_counts())))
    print(f"Unfilled demand lines (lost sales): {sales_gen.lost_lines}, short-filled lines: {sales_gen.short_lines}")
    print(f"Validation: {report.checks_run} checks, {len(report.failed)} failed, {report.total_violations} violating rows")
    for name, bad in report.failed:
        print(f"  FAIL: {name}: {bad}")
    print(f"Warnings: {len(warnings)}")
    for w in warnings:
        print(f"  WARN: {w}")
    print("VALIDATION " + ("PASSED" if not report.failed else "FAILED"))
    return 0 if not report.failed else 1


if __name__ == "__main__":
    sys.exit(main())
