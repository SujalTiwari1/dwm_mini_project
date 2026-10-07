"""Unified action queue (grain: branch x medicine). Explicit rules decide the priority; the numeric score only orders rows inside a priority.

Per-pair issue priorities (most severe wins):
  stock side : the more severe of the stockout risk level and the reorder priority (NO_DEMAND_DATA and LOW count as LOW)
  expiry     : worst live batch of the pair: CRITICAL / HIGH as is, MEDIUM only if some units are projected unsold (MEDIUM with no projected loss is a monitor item = LOW)
  overstock  : MEDIUM if OVERSTOCK with an excess value at or above the materiality threshold in config, otherwise LOW
priority = the most severe issue.  primary action = the winning issue (ties: stock side, then expiry, then overstock). Every other active issue is kept in secondary_reasons.

priority_score = base(priority) + 5 x number of active issues + min(impact_value / 1000, 50)  where base is 400 / 300 / 200 / 100 for CRITICAL / HIGH / MEDIUM / LOW.
It exists for deterministic ordering inside a priority and carries no meaning on its own. Exposures are potential exposure / estimated values, not actual losses.
"""
import numpy as np
import pandas as pd

from .. import config as C

RANK = {p: i for i, p in enumerate(C.PRIORITY_ORDER)}
BASE = {"CRITICAL": 400, "HIGH": 300, "MEDIUM": 200, "LOW": 100}
SEV_FROM_STOCKOUT = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "NO_DEMAND_DATA": "LOW"}


def _worst(a, b):
    return a if RANK[a] <= RANK[b] else b


def expiry_by_pair(expiry: pd.DataFrame) -> pd.DataFrame:
    if expiry.empty:
        return pd.DataFrame(columns=["branch_id", "medicine_id", "expiry_risk", "expiry_worst_batch", "expiry_worst_days", "expiry_reason", "expiry_lots",
                                     "expiry_lots_at_risk", "projected_expiry_exposure_value", "expiry_actionable"])
    e = expiry.copy()
    # queue materiality: a CRITICAL/HIGH lot expecting less than one unit of waste ranks as MEDIUM (monitor); the lot-level classification is unchanged
    e["eff_level"] = np.where(e["risk_level"].isin(["CRITICAL", "HIGH"]) & (e["projected_unsold_units"] < C.EXPIRY_MIN_UNSOLD_UNITS_FOR_ALERT), "MEDIUM", e["risk_level"])
    e["sev"] = e["eff_level"].map(RANK)
    e["actionable"] = (e["eff_level"].isin(["CRITICAL", "HIGH"])) | ((e["eff_level"] == "MEDIUM") & (e["projected_unsold_units"] > 0))
    worst = e.sort_values(["branch_id", "medicine_id", "sev", "projected_unsold_value", "days_to_expiry"], ascending=[True, True, True, False, True], kind="mergesort") \
             .drop_duplicates(["branch_id", "medicine_id"])[["branch_id", "medicine_id", "eff_level", "batch_id", "days_to_expiry", "reason"]]
    worst = worst.rename(columns={"eff_level": "expiry_risk", "batch_id": "expiry_worst_batch", "days_to_expiry": "expiry_worst_days", "reason": "expiry_reason"})
    agg = e.groupby(["branch_id", "medicine_id"], sort=True).agg(
        expiry_lots=("batch_id", "size"), expiry_lots_at_risk=("projected_unsold_units", lambda s: int((s > 0).sum())),
        projected_expiry_exposure_value=("projected_unsold_value", "sum"), expiry_actionable=("actionable", "max")).reset_index()
    return worst.merge(agg, on=["branch_id", "medicine_id"])


def build_queue(frame: pd.DataFrame, stockout: pd.DataFrame, reorder: pd.DataFrame, overstock: pd.DataFrame, expiry: pd.DataFrame, cfg=C) -> pd.DataFrame:
    keys = ["branch_id", "medicine_id"]
    q = frame[keys + ["medicine_name", "category", "current_inventory_units", "current_inventory_value", "expected_daily_demand", "avg_selling_price"]].copy()
    q = q.merge(stockout[keys + ["days_of_cover", "forecast_7d", "forecast_30d", "risk_level", "risk_score", "primary_reason", "secondary_reason"]]
                .rename(columns={"risk_level": "stockout_risk", "primary_reason": "stockout_reason", "secondary_reason": "stockout_secondary"}), on=keys, validate="one_to_one")
    q = q.merge(reorder[keys + ["recommendation", "priority", "recommended_order_quantity", "reason", "planning_lead_time_days"]]
                .rename(columns={"recommendation": "reorder_recommendation", "priority": "reorder_priority", "reason": "reorder_reason"}), on=keys, validate="one_to_one")
    q = q.merge(overstock[keys + ["overstock_level", "excess_units_estimate", "excess_value_estimate", "reason"]]
                .rename(columns={"overstock_level": "overstock_risk", "reason": "overstock_reason"}), on=keys, validate="one_to_one")
    ex = expiry_by_pair(expiry)
    q = q.merge(ex, on=keys, how="left")
    q["expiry_risk"] = q["expiry_risk"].astype(object).where(q["expiry_risk"].notna(), "NONE")
    for c in ("expiry_lots", "expiry_lots_at_risk"):
        q[c] = pd.to_numeric(q[c]).fillna(0).astype(int)
    q["projected_expiry_exposure_value"] = pd.to_numeric(q["projected_expiry_exposure_value"]).fillna(0.0)
    q["expiry_actionable"] = q["expiry_actionable"].astype("boolean").fillna(False).astype(bool)

    # issue priorities
    stock_prio = [_worst(SEV_FROM_STOCKOUT[s], r) for s, r in zip(q["stockout_risk"], q["reorder_priority"])]
    expiry_prio = np.where(q["expiry_risk"].isin(["CRITICAL", "HIGH"]), q["expiry_risk"], np.where((q["expiry_risk"] == "MEDIUM") & q["expiry_actionable"], "MEDIUM", "LOW"))
    over_prio = np.where((q["overstock_risk"] == "OVERSTOCK") & (q["excess_value_estimate"] >= cfg.OVERSTOCK_MEDIUM_EXCESS_VALUE), "MEDIUM", "LOW")
    q["stock_priority"], q["expiry_priority"], q["overstock_priority"] = stock_prio, expiry_prio, over_prio

    # business impact (potential exposure, not an actual loss)
    lead_demand = q["expected_daily_demand"] * q["planning_lead_time_days"]
    q["potential_stockout_exposure_units"] = np.round(np.maximum(0.0, lead_demand - q["current_inventory_units"]), 2)
    q["potential_stockout_exposure_value"] = np.round(q["potential_stockout_exposure_units"] * q["avg_selling_price"], 2)
    q["estimated_excess_value"] = q["excess_value_estimate"]
    q["projected_expiry_exposure_value"] = q["projected_expiry_exposure_value"].round(2)
    q["impact_value"] = (q["potential_stockout_exposure_value"] + q["estimated_excess_value"] + q["projected_expiry_exposure_value"]).round(2)

    prio, action, primary, secondary, n_active = [], [], [], [], []
    for r in q.itertuples(index=False):
        issues = []   # (priority, order, action, reason, active)
        stock_active = r.stock_priority != "LOW"
        if r.reorder_recommendation in ("ORDER_NOW", "REORDER_SOON"):
            stock_action = r.reorder_recommendation
        elif stock_active:
            stock_action = "MONITOR_STOCK_CLOSELY"
        else:
            stock_action = None
        if stock_active or r.reorder_recommendation in ("ORDER_NOW", "REORDER_SOON"):
            reason = r.stockout_reason if r.stockout_risk not in ("LOW",) else r.reorder_reason
            if r.reorder_recommendation in ("ORDER_NOW", "REORDER_SOON") and r.stockout_risk != "NO_DEMAND_DATA":
                reason = f"{r.stockout_reason}. {r.reorder_reason}; suggested order {int(r.recommended_order_quantity)} units"
            if r.stockout_secondary:
                reason = f"{reason} ({r.stockout_secondary})"
            issues.append((r.stock_priority, 0, stock_action, reason))
        if r.expiry_priority != "LOW":
            issues.append((r.expiry_priority, 1, "PRIORITIZE_SALE_EXPIRING_STOCK" if r.expiry_priority in ("CRITICAL", "HIGH") else "MONITOR_EXPIRY",
                           f"batch {r.expiry_worst_batch} ({r.expiry_worst_days} days to expiry): {r.expiry_reason}"))
        if r.overstock_priority != "LOW" or (r.overstock_risk == "OVERSTOCK"):
            issues.append((r.overstock_priority, 2, "REVIEW_OVERSTOCK", r.overstock_reason))
        if not issues:
            top = "LOW"
            act = "NO_DEMAND_DATA" if r.stockout_risk == "NO_DEMAND_DATA" else "MONITOR"
            pr = r.stockout_reason if r.stockout_risk == "NO_DEMAND_DATA" else f"No active issue: {r.stockout_reason}"
            sec = ""
        else:
            issues.sort(key=lambda x: (RANK[x[0]], x[1]))
            top, _, act, pr = issues[0]
            sec = " | ".join(f"[{p}] {rs}" for p, _, _, rs in issues[1:])
        prio.append(top)
        action.append(act)
        primary.append(pr)
        secondary.append(sec)
        n_active.append(sum(1 for i in issues if i[0] != "LOW"))
    q["priority"] = prio
    q["primary_action"] = action
    q["primary_reason"] = primary
    q["secondary_reasons"] = secondary
    q["active_issue_count"] = n_active
    q["priority_score"] = [BASE[p] + 5 * n + min(v / 1000.0, 50.0) for p, n, v in zip(q["priority"], q["active_issue_count"], q["impact_value"])]
    q["priority_score"] = q["priority_score"].round(2)
    q["_rank"] = q["priority"].map(RANK)
    q = q.sort_values(["_rank", "priority_score", "branch_id", "medicine_id"], ascending=[True, False, True, True], kind="mergesort").reset_index(drop=True)
    q.insert(0, "queue_position", np.arange(1, len(q) + 1))
    cols = ["queue_position", "priority", "branch_id", "medicine_id", "medicine_name", "category", "current_inventory_units", "days_of_cover", "forecast_7d", "forecast_30d",
            "stockout_risk", "reorder_recommendation", "recommended_order_quantity", "overstock_risk", "expiry_risk", "primary_action", "primary_reason", "secondary_reasons",
            "potential_stockout_exposure_units", "potential_stockout_exposure_value", "estimated_excess_value", "projected_expiry_exposure_value", "impact_value",
            "active_issue_count", "priority_score"]
    return q[cols]
