"""Dashboard KPIs: warehouse figures from SQL, decision figures from decision_support/reports/decision_summary.json."""
from fastapi import APIRouter, HTTPException

from ..database import current_dataset, load_report, query
from ..schemas import ObjectResponse

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=ObjectResponse, summary="Get headline KPIs for the dashboard",
            description="Sales and inventory KPIs come from the warehouse (latest snapshot for stock). Overstock, recommended order units and "
                        "action counts are read from the Decision Support summary, not recalculated. Money amounts are INR; exposures are estimates, not losses.")
def summary():
    sales = query("SELECT COALESCE(SUM(total_amount), 0) AS total_revenue, COALESCE(SUM(quantity), 0) AS total_units_sold, "
                  "COUNT(DISTINCT transaction_id) AS total_transactions, "
                  "ROUND(SUM(total_amount) / NULLIF(COUNT(DISTINCT transaction_id), 0), 2) AS average_transaction_value "
                  "FROM warehouse.fact_sales")[0]
    inv = query("SELECT MAX(snapshot_date) AS inventory_snapshot_date, COALESCE(SUM(stock_units), 0) AS current_inventory_units, "
                "COALESCE(SUM(stock_value_at_cost), 0) AS current_inventory_value FROM warehouse.v_current_inventory")[0]
    flows = query("SELECT COUNT(*) FILTER (WHERE closing_quantity = 0) AS stockout_days, SUM(expired_quantity) AS expired_units "
                  "FROM warehouse.fact_inventory")[0]
    exp = query("SELECT COALESCE(SUM(value_at_risk) FILTER (WHERE NOT is_expired), 0) AS expiry_risk_value "
                "FROM warehouse.v_expiry_risk")[0]
    try:
        ds = load_report("decision", "decision_summary.json")
    except HTTPException:
        if current_dataset.get() == "demo":
            raise
        ds = None                                    # uploaded dataset without inventory data: no decision support
    keys = {"decision_date": "decision_date", "overstock_count": "overstock_count", "recommended_order_units": "recommended_units_to_order",
            "critical_actions": "critical_count", "high_actions": "high_count", "medium_actions": "medium_count", "low_actions": "low_count"}
    try:
        decisions = {k: (ds[v] if ds is not None else None) for k, v in keys.items()}
    except KeyError:
        raise HTTPException(500, "Report 'decision_summary.json' could not be read")
    return {"data": {**sales, **inv, **flows, **exp, **decisions,
                     "notes": {"stockout_days": "branch-medicine-days with zero closing stock, whole period",
                               "expired_units": "units written off at expiry, whole period",
                               "expiry_risk_value": "projected unsold cost value of live batches (potential exposure, not a loss)"}}}
