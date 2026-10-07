"""Human-readable decision-support report, generated from the actual results."""
import pandas as pd

from . import config as C


def _table(df, cols):
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return lines


def render(S, res, hist, checks):
    so, re_, ov, ex, q, f = res["stockout"], res["reorder"], res["overstock"], res["expiry"], res["queue"], res["frame"]
    inr = lambda v: f"INR {v:,.0f}"
    L = ["# MedStock Decision Support", "",
         "> Synthetic data. This layer produces inventory-management recommendations only. It makes no clinical, prescribing or substitution recommendation, and it does not treat medicine associations as medical advice.", "",
         "## 1. Objective", "",
         "Turn the warehouse, analytics and ML demand forecasts into explainable recommendations that answer: what needs attention, why, how urgent it is, what action could be considered, and what evidence supports it. "
         "Every row carries its evidence (stock, demand, forecast, history, batch expiry) and a plain-language reason; there is no black-box score.", "",
         "## 2. Decision Date", "",
         f"Decision date: **{S['decision_date']}**, determined dynamically as the latest date of the warehouse inventory snapshot. Only information available on that date is used; the demand outlook is the ML forecast issued on that date "
         f"(`{S['forecast_origin_split']}` split of `forecasts.csv`). A second run for {S['historical_simulation']['decision_date']} proves that decisions never depend on later data (see Validation).", "",
         "## 3. Inputs", "",
         "- **Warehouse (as of the decision date):** stock and stock value, units sold in the last 7/28/30/90 days, stockout days (28, 90, all history), stockout events, weekly demand variability (26 blocks of 7 days), recent average selling price, and live batch lots (received minus sold, first-expiry-first-out).",
         f"- **ML forecasts:** 7, 14 and 30-day point forecasts and the upper bounds of the approximate 80% interval, for all {S['total_branch_medicine_pairs']:,} branch-medicine pairs (`{C.FORECAST_MODEL}`).",
         "- **Reused definitions:** low stock under 7 days of cover, overstock (no sales in 30 days or more than 90 days of cover) and the FEFO-aware expiry-risk method come from the analytics layer and are reconciled against its views.",
         "- **Expected daily demand** = the larger of the 7-day forecast rate and the recent 28-day rate. The ML layer measured a systematic under-forecast of totals, and running out is costlier than holding a little extra, so the conservative choice is deliberate.", "",
         "## 4. Stockout Risk", "",
         "Days of cover = stock / expected daily demand (NULL, and the separate class NO_DEMAND_DATA, when expected demand is zero). CRITICAL: stock is zero or cover under 3 days. HIGH: under 7 days (the analytics low-stock line). MEDIUM: under 14. LOW: 14 or more. "
         "A MEDIUM or LOW pair is escalated by one level (never into CRITICAL) if it had 3 or more stockout days in the last 28 days or a historical stockout rate above 2.5%, or if its stock would last under 7 days at the upper forecast.", ""]
    c = S["stockout_risk_counts"]
    L += [f"Result: CRITICAL {c['CRITICAL']}, HIGH {c['HIGH']}, MEDIUM {c['MEDIUM']}, LOW {c['LOW']}, NO_DEMAND_DATA {c['NO_DEMAND_DATA']} (of {S['total_branch_medicine_pairs']:,} pairs).", ""]
    top = so[so["risk_level"].isin(["CRITICAL", "HIGH"])].head(8)
    L += _table(top.assign(cover=top["days_of_cover"]), ["branch_id", "medicine_name", "current_inventory_units", "expected_daily_demand", "cover", "risk_level", "primary_reason"]) + ["",
         "## 5. Reorder Recommendations", "",
         f"Planning assumptions (not in the data): lead time {C.PLANNING_LEAD_TIME_DAYS} days, service level {C.SERVICE_LEVEL:.0%} (z = 1.645), each order covers {C.ORDER_COVER_DAYS} days beyond the lead time, no minimum order quantity, no open orders. "
         "expected lead-time demand = expected daily demand x lead time; safety stock = z x daily demand std x sqrt(lead time) with daily std = weekly std / sqrt(7); reorder point = lead-time demand + safety stock; "
         "order quantity = ceil(max(0, reorder point + expected daily demand x order cover days - stock)). ORDER_NOW: stock <= lead-time demand. REORDER_SOON: stock below the reorder point. NO_REORDER otherwise. NO_DEMAND_DATA when no demand evidence exists.", "",
         f"Result: ORDER_NOW {S['order_now_count']}, REORDER_SOON {S['reorder_soon_count']}, NO_REORDER {S['no_reorder_count']}, NO_DEMAND_DATA {S['no_demand_data_count']}; {S['recommended_units_to_order']:,} units recommended in total.", ""]
    top = re_[re_["recommendation"] == "ORDER_NOW"].head(8)
    L += _table(top, ["branch_id", "medicine_name", "current_inventory_units", "reorder_point", "recommended_order_quantity", "priority"]) + ["",
         "## 6. Overstock Risk", "",
         "Analytics definition, unchanged: OVERSTOCK = stock > 0 and (no units sold in the last 30 days or more than 90 days of cover). Binary classification (no data-driven threshold justifies a SEVERE level). "
         "Excess = units above 90 days of cover at the larger of the recent and forecast 30-day rate; value at average unit cost. A low-demand medicine is flagged only when its stock is large relative to its own demand.", "",
         f"Result: {S['overstock_count']} overstock pairs, about {S['estimated_excess_units']:,} excess units, estimated excess value {inr(S['estimated_overstock_value']['value_inr'])} (an estimate of exposure, not a loss).", ""]
    top = ov[ov["overstock_level"] == "OVERSTOCK"].head(6)
    L += _table(top, ["branch_id", "medicine_name", "current_inventory_units", "days_of_cover", "excess_units_estimate", "excess_value_estimate"]) + ["",
         "## 7. Expiry Actions", "",
         "The analytics expiry-risk method is reused and reconciled lot by lot: recent 90-day demand is projected to the expiry date, earlier-expiring lots of the same branch and medicine sell first, and the projection horizon is 365 days. "
         "CRITICAL / HIGH (expected unsold units, expiry within 30 / 90 days) -> PRIORITIZE_SALE; MEDIUM -> MONITOR; LOW -> NO_ACTION. Only live batches are assessed. Inventory actions only. "
         f"In the unified queue (not in this lot-level file) a CRITICAL/HIGH lot expecting less than {C.EXPIRY_MIN_UNSOLD_UNITS_FOR_ALERT:g} unit of waste ranks as MEDIUM, because a fraction of a unit should not outrank a real stockout.", "",
         f"Result over {S['expiry_lots_assessed']:,} live batch lots: CRITICAL {S['expiry_critical_count']}, HIGH {S['expiry_high_count']}, MEDIUM {S['expiry_medium_count']}, LOW {S['expiry_low_count']}; "
         f"projected at-risk cost value {inr(S['projected_expiry_exposure']['value_inr'])}.", ""]
    top = ex[ex["risk_level"].isin(["CRITICAL", "HIGH"])].head(6)
    L += _table(top, ["branch_id", "medicine_name", "batch_id", "batch_quantity", "days_to_expiry", "projected_unsold_units", "projected_unsold_value", "risk_level"]) + ["",
         "## 8. Unified Action Queue", "",
         "One row per branch x medicine. Explicit rules set the priority (the most severe of the stock-side, expiry and overstock issues); the primary action is the winning issue (ties: stock, then expiry, then overstock); "
         "all other active issues stay visible in `secondary_reasons`. `priority_score` = 400/300/200/100 by priority + 5 x active issues + min(impact / 1000, 50) and only orders rows inside a priority.", "",
         f"Priorities: CRITICAL {S['critical_count']}, HIGH {S['high_count']}, MEDIUM {S['medium_count']}, LOW {S['low_count']}.", "",
         "Top of the queue:", ""]
    top = q.head(12).copy()
    top["primary_reason"] = top["primary_reason"].str.slice(0, 150)
    L += _table(top, ["queue_position", "priority", "branch_id", "medicine_name", "primary_action", "primary_reason"]) + ["",
         "## 9. Business Impact", "",
         "All amounts are potential exposure or estimates, never actual financial losses.", "",
         f"- Potential stockout exposure: {S['potential_stockout_exposure']['units']:,.0f} units, {inr(S['potential_stockout_exposure']['value_inr'])} ({S['potential_stockout_exposure']['label']}).",
         f"- Estimated overstock value: {inr(S['estimated_overstock_value']['value_inr'])} ({S['estimated_overstock_value']['label']}).",
         f"- Projected expiry exposure: {inr(S['projected_expiry_exposure']['value_inr'])} ({S['projected_expiry_exposure']['label']}).", "",
         "## 10. Validation", "",
         f"{S['validation']['checks']} checks, {S['validation']['failures']} failures. Areas: " + ", ".join(sorted({x['area'].replace('historical:', '') for x in checks})) + ". "
         "The decision-time test rebuilds the decision for " + S["historical_simulation"]["decision_date"] + " and shows that its inputs equal an independent recomputation from data truncated at that date and do not change when every later observation is scrambled; "
         "the ML forecast used was issued on that date by a model trained on earlier targets only. Reconciliation ties inventory, stockout days, overstock status, expiry lots and forecasts to the analytics views and `forecasts.csv`. "
         "Five deterministic scenarios (zero stock, large stock with no demand, an expiring batch, healthy stock, no reliable demand) plus an escalation case pass.", "",
         "## 11. Planning Assumptions", "",
         "These are NOT present in, or learned from, the synthetic dataset:",
         f"- supplier lead time = {C.PLANNING_LEAD_TIME_DAYS} days (the data records receipt dates only, not order dates)",
         f"- service level {C.SERVICE_LEVEL:.0%} for safety stock (a planning assumption, not an optimised value)",
         f"- each order covers {C.ORDER_COVER_DAYS} days of demand beyond the lead time",
         "- no minimum order quantities, pack sizes or supplier availability limits; open (in-transit) orders assumed to be zero",
         f"- queue materiality for expiry: lots expecting under {C.EXPIRY_MIN_UNSOLD_UNITS_FOR_ALERT:g} unit of waste rank as MEDIUM",
         f"- stockout level cut-offs (3, 7, 14 days), the escalation rule (3 stockout days in 28, or a 2.5% stockout rate) and the materiality threshold for overstock priority (INR {C.OVERSTOCK_MEDIUM_EXCESS_VALUE:,.0f} excess value) are business parameters in `config.py`", "",
         "## 12. Limitations", "",
         "- Forecasts are estimates (the ML layer reports an under-forecast bias and an approximate 80% interval); decisions inherit that uncertainty.",
         "- Stockout history censors observed demand, so recent demand may understate true demand for pairs that were out of stock.",
         "- Lead time, service level and order cover are assumptions; recommended quantities are only as good as those assumptions and ignore supplier constraints.",
         "- The expiry method uses trailing demand and does not model returns, transfers between branches or discounting.",
         "- Exposure figures mix revenue (stockout) and cost (overstock, expiry) bases and are potential exposures, not losses; their sum is used only to order rows.",
         "- Upstream boundary finding: for pairs with exactly 90.0 days of cover (for example 12 units and 4 sold in 30 days) the analytics view labels OVERSTOCK because its decimal division rounds 4/30 up. This layer applies the rule exactly (90.0 is not over 90), so those pairs are NORMAL here. The analytics view was not changed; the reconciliation check lists the boundary pairs.",
         "- Synthetic data: results show how the method works, not what a real pharmacy should order.",
         "- Inventory management only: no clinical recommendation of any kind.", "",
         "## 13. Reproducibility", "",
         f"The engine is deterministic: no random numbers are used, all orderings are explicit, and inputs are the warehouse as of the decision date and the fixed forecast file. Running `python -m decision_support.run` twice gives identical reports "
         f"except `run_timestamp` and `runtime_seconds` in `decision_summary.json`. Python {S['python']}."]
    return "\n".join(L) + "\n"
