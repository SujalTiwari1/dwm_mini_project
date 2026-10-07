"""Run the decision-support layer:   python -m decision_support.run

Flow: warehouse state as of the decision date (SQL) + ML forecasts issued on that date -> stockout risk -> reorder -> overstock -> expiry -> unified action queue.
The same engine is also run for a historical decision date (config.HISTORICAL_DECISION_DATE) to prove that a decision uses only information available on its date.
"""
import json
import platform
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as C
from . import inputs
from . import validation as V
from .report import render
from .rules import expiry as rx
from .rules import overstock as ro
from .rules import reorder as rr
from .rules import stockout as rs
from .scoring import priority as pq

R = C.REPORT_DIR


def decide(conn, decision_date):
    state = inputs.load_state(conn, decision_date)
    lots = inputs.load_lots(conn, decision_date)
    fc = inputs.load_forecasts(decision_date)
    frame = inputs.build_frame(state, fc)
    so = rs.assess(frame)
    re_ = rr.recommend(frame, so)
    ov = ro.assess(frame)
    ex = rx.assess(lots, fc)
    q = pq.build_queue(frame, so, re_, ov, ex)
    return {"date": decision_date, "state": state, "lots": lots, "forecasts": fc, "frame": frame, "stockout": so, "reorder": re_, "overstock": ov, "expiry": ex, "queue": q}


def _json(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")


def summarize(res, runtime=None):
    so, re_, ov, ex, q = res["stockout"], res["reorder"], res["overstock"], res["expiry"], res["queue"]
    cnt = lambda s, v: int((s == v).sum())
    return {
        "decision_date": res["date"], "forecast_origin_split": res["forecasts"]["forecast_split"].iloc[0],
        "total_branch_medicine_pairs": int(len(q)),
        "critical_count": cnt(q["priority"], "CRITICAL"), "high_count": cnt(q["priority"], "HIGH"), "medium_count": cnt(q["priority"], "MEDIUM"), "low_count": cnt(q["priority"], "LOW"),
        "stockout_risk_counts": {k: cnt(so["risk_level"], k) for k in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NO_DEMAND_DATA"]},
        "order_now_count": cnt(re_["recommendation"], "ORDER_NOW"), "reorder_soon_count": cnt(re_["recommendation"], "REORDER_SOON"),
        "no_reorder_count": cnt(re_["recommendation"], "NO_REORDER"), "no_demand_data_count": cnt(re_["recommendation"], "NO_DEMAND_DATA"),
        "recommended_units_to_order": int(re_["recommended_order_quantity"].sum()),
        "overstock_count": cnt(ov["overstock_level"], "OVERSTOCK"),
        "estimated_excess_units": int(ov["excess_units_estimate"].sum()),
        "expiry_lots_assessed": int(len(ex)),
        "expiry_critical_count": cnt(ex["risk_level"], "CRITICAL"), "expiry_high_count": cnt(ex["risk_level"], "HIGH"),
        "expiry_medium_count": cnt(ex["risk_level"], "MEDIUM"), "expiry_low_count": cnt(ex["risk_level"], "LOW"),
        "potential_stockout_exposure": {"value_inr": round(float(q["potential_stockout_exposure_value"].sum()), 2), "units": round(float(q["potential_stockout_exposure_units"].sum()), 1),
                                        "label": "potential revenue exposure: demand expected during the lead time that current stock does not cover, at recent average selling price (not an actual loss)"},
        "estimated_overstock_value": {"value_inr": round(float(ov["excess_value_estimate"].sum()), 2), "label": "estimated cost value of units above 90 days of cover (not an actual loss)"},
        "projected_expiry_exposure": {"value_inr": round(float(ex["projected_unsold_value"].sum()), 2), "label": "projected at-risk cost value of batch units expected to remain unsold at expiry (not an actual loss)"},
    }


def main() -> int:
    t0 = time.time()
    R.mkdir(parents=True, exist_ok=True)
    engine, conn = inputs.open_connection()
    latest = inputs.latest_date(conn)
    D = C.DECISION_DATE or latest
    print(f"MedStock decision support | decision date {D} (warehouse latest {latest}) | forecasts {C.FORECASTS_CSV.name}", flush=True)
    res = decide(conn, D)
    q = res["queue"]
    print(f"decisions: {len(q)} branch-medicine pairs | priority CRITICAL {int((q['priority'] == 'CRITICAL').sum())}, HIGH {int((q['priority'] == 'HIGH').sum())}, "
          f"MEDIUM {int((q['priority'] == 'MEDIUM').sum())}, LOW {int((q['priority'] == 'LOW').sum())} | expiry lots assessed {len(res['expiry'])}", flush=True)

    hist = decide(conn, C.HISTORICAL_DECISION_DATE)
    print(f"historical decision-time simulation as of {hist['date']}: {len(hist['queue'])} decisions", flush=True)

    # ---- reports -------------------------------------------------------------------------------------------------------
    so = res["stockout"]
    so_cols = ["branch_id", "medicine_id", "medicine_name", "category", "current_inventory_units", "forecast_7d", "forecast_14d", "forecast_30d", "forecast_upper_7d",
               "recent_daily_demand", "expected_daily_demand", "days_of_cover", "days_of_cover_at_upper_forecast", "stockout_days_last_28d", "stockout_days_last_90d",
               "stockout_event_count", "historical_stockout_rate", "demand_cv_weekly", "base_risk_level", "risk_level", "risk_score", "primary_reason", "secondary_reason"]
    order_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NO_DEMAND_DATA": 4}
    so_out = so[so_cols].assign(_r=so["risk_level"].map(order_rank)).sort_values(["_r", "risk_score", "branch_id", "medicine_id"], ascending=[True, False, True, True], kind="mergesort").drop(columns="_r")
    so_out.to_csv(R / "stockout_risk.csv", index=False)
    re_ = res["reorder"]
    rec_rank = {"ORDER_NOW": 0, "REORDER_SOON": 1, "NO_REORDER": 2, "NO_DEMAND_DATA": 3}
    re_out = re_.assign(_r=re_["recommendation"].map(rec_rank), _p=re_["priority"].map({k: i for i, k in enumerate(C.PRIORITY_ORDER)})) \
                .sort_values(["_r", "_p", "recommended_order_quantity", "branch_id", "medicine_id"], ascending=[True, True, False, True, True], kind="mergesort").drop(columns=["_r", "_p"])
    re_out.to_csv(R / "reorder_recommendations.csv", index=False)
    ov = res["overstock"].sort_values(["overstock_level", "excess_value_estimate", "branch_id", "medicine_id"], ascending=[False, False, True, True], kind="mergesort")
    ov.to_csv(R / "overstock_risk.csv", index=False)
    ex = res["expiry"].assign(_r=res["expiry"]["risk_level"].map({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3})) \
                      .sort_values(["_r", "projected_unsold_value", "days_to_expiry", "branch_id", "batch_id"], ascending=[True, False, True, True, True], kind="mergesort").drop(columns="_r")
    ex.to_csv(R / "expiry_actions.csv", index=False)
    q.to_csv(R / "action_queue.csv", index=False)

    # ---- validation (reconciliation, leakage, deterministic test cases) -----------------------------------------------------
    checks = V.run_all(conn, res, hist)
    failures = [c for c in checks if not c["passed"]]
    _json(R / "validation_results.json", {"checks": len(checks), "failures": len(failures), "results": checks})
    summary = summarize(res)
    summary["historical_simulation"] = {"decision_date": hist["date"], "priority_counts": hist["queue"]["priority"].value_counts().to_dict(),
                                        "forecast_split": hist["forecasts"]["forecast_split"].iloc[0]}
    summary["validation"] = {"checks": len(checks), "failures": len(failures)}
    summary["run_timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary["runtime_seconds"] = round(time.time() - t0, 1)
    summary["python"] = platform.python_version()
    summary["configuration"] = {
        "planning_assumptions_not_in_dataset": {"planning_lead_time_days": C.PLANNING_LEAD_TIME_DAYS, "service_level": C.SERVICE_LEVEL, "order_cover_days": C.ORDER_COVER_DAYS,
                                                 "minimum_order_quantity": "none modelled", "open_orders": "assumed zero", "supplier_availability": "not modelled"},
        "stockout_levels_days_of_cover": C.STOCKOUT_LEVELS, "stockout_escalation": C.STOCKOUT_ESCALATION, "overstock": C.OVERSTOCK,
        "overstock_medium_excess_value_inr": C.OVERSTOCK_MEDIUM_EXCESS_VALUE, "expiry": C.EXPIRY, "expiry_actions": C.EXPIRY_ACTION,
        "recent_demand_days": C.RECENT_DEMAND_DAYS, "variability_weeks": C.VARIABILITY_WEEKS,
        "expected_daily_demand": "max(forecast_7d / 7, recent 28-day daily demand)", "forecast_model": C.FORECAST_MODEL}
    _json(R / "decision_summary.json", summary)
    (R / "decision_support_summary.md").write_text(render(summary, res, hist, checks), encoding="utf-8")
    for c in failures:
        print(f"  FAIL [{c['area']}] {c['check']}: {c['detail']}")
    print(f"Validation: {len(checks)} checks, {len(failures)} failed | runtime {summary['runtime_seconds']}s", flush=True)
    conn.close()
    engine.dispose()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
