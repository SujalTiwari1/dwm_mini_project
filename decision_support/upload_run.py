"""Decision support for an UPLOADED dataset (sales + purchases): python -m decision_support.upload_run   (MEDSTOCK_DATASET=<id>)

Uses exactly the same engine and rules as the main run (decision_support.run.decide): warehouse state as of the latest date plus the
demand forecasts issued on that date. It does not run the demo-only historical decision simulation or the checks that depend on the
demo dataset's size; it writes the same report files the API serves and runs structural self-checks instead.
"""
import json
import time
from datetime import datetime, timezone

import pandas as pd

from . import config as C
from . import inputs
from .run import decide, summarize

R = C.REPORT_DIR


def main() -> dict:
    t0 = time.time()
    R.mkdir(parents=True, exist_ok=True)
    engine, conn = inputs.open_connection()
    try:
        D = C.DECISION_DATE or inputs.latest_date(conn)
        res = decide(conn, D)
    finally:
        conn.close()
        engine.dispose()
    q, so, re_, ov, ex = res["queue"], res["stockout"], res["reorder"], res["overstock"], res["expiry"]

    so_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NO_DEMAND_DATA": 4}
    so_cols = ["branch_id", "medicine_id", "medicine_name", "category", "current_inventory_units", "forecast_7d", "forecast_14d", "forecast_30d", "forecast_upper_7d",
               "recent_daily_demand", "expected_daily_demand", "days_of_cover", "days_of_cover_at_upper_forecast", "stockout_days_last_28d", "stockout_days_last_90d",
               "stockout_event_count", "historical_stockout_rate", "demand_cv_weekly", "base_risk_level", "risk_level", "risk_score", "primary_reason", "secondary_reason"]
    so.assign(_r=so["risk_level"].map(so_rank)).sort_values(["_r", "risk_score", "branch_id", "medicine_id"], ascending=[True, False, True, True], kind="mergesort") \
      .drop(columns="_r")[so_cols].to_csv(R / "stockout_risk.csv", index=False)
    rec_rank = {"ORDER_NOW": 0, "REORDER_SOON": 1, "NO_REORDER": 2, "NO_DEMAND_DATA": 3}
    re_.assign(_r=re_["recommendation"].map(rec_rank), _p=re_["priority"].map({k: i for i, k in enumerate(C.PRIORITY_ORDER)})) \
       .sort_values(["_r", "_p", "recommended_order_quantity", "branch_id", "medicine_id"], ascending=[True, True, False, True, True], kind="mergesort") \
       .drop(columns=["_r", "_p"]).to_csv(R / "reorder_recommendations.csv", index=False)
    ov.sort_values(["overstock_level", "excess_value_estimate", "branch_id", "medicine_id"], ascending=[False, False, True, True], kind="mergesort").to_csv(R / "overstock_risk.csv", index=False)
    ex.assign(_r=ex["risk_level"].map({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3})) \
      .sort_values(["_r", "projected_unsold_value", "days_to_expiry", "branch_id", "batch_id"], ascending=[True, False, True, True, True], kind="mergesort") \
      .drop(columns="_r").to_csv(R / "expiry_actions.csv", index=False)
    q.to_csv(R / "action_queue.csv", index=False)

    checks = [
        {"check": "one queue row per branch x medicine", "passed": bool(not q.duplicated(["branch_id", "medicine_id"]).any() and len(q) == len(res["state"]))},
        {"check": "queue positions are 1..n", "passed": bool((q["queue_position"].to_numpy() == range(1, len(q) + 1)).all())},
        {"check": "priorities are valid", "passed": bool(q["priority"].isin(C.PRIORITY_ORDER).all())},
        {"check": "no negative order quantities", "passed": bool((re_["recommended_order_quantity"] >= 0).all())},
        {"check": "decision date equals the forecast origin", "passed": bool(res["forecasts"]["forecast_split"].iloc[0] == "future")},
    ]
    summary = summarize(res)
    summary["validation"] = {"checks": len(checks), "failures": sum(not c["passed"] for c in checks), "results": checks}
    summary["run_timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary["runtime_seconds"] = round(time.time() - t0, 1)
    summary["mode"] = "uploaded dataset (no historical decision simulation)"
    summary["configuration"] = {"planning_lead_time_days": C.PLANNING_LEAD_TIME_DAYS, "service_level": C.SERVICE_LEVEL, "order_cover_days": C.ORDER_COVER_DAYS,
                                "stockout_levels_days_of_cover": C.STOCKOUT_LEVELS, "overstock": C.OVERSTOCK, "expiry": C.EXPIRY}
    (R / "decision_summary.json").write_text(json.dumps(summary, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    if summary["validation"]["failures"]:
        raise SystemExit("decision self-checks failed: " + json.dumps([c for c in checks if not c["passed"]]))
    return {"decision_date": D, "pairs": int(len(q)), "critical": summary["critical_count"], "high": summary["high_count"],
            "order_now": summary["order_now_count"], "reorder_soon": summary["reorder_soon_count"], "overstock": summary["overstock_count"],
            "expiry_lots": summary["expiry_lots_assessed"], "seconds": summary["runtime_seconds"]}
