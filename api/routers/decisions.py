"""Decision Support: serves the reports written by `python -m decision_support.run`. No decision rule is evaluated here."""
from typing import Literal

from fastapi import APIRouter, Query

from ..database import list_response, load_report
from ..schemas import ListResponse

router = APIRouter(prefix="/api/decisions", tags=["Decision support"])

Limit = Query(100, ge=1, le=1000, description="Maximum rows to return")
Offset = Query(0, ge=0, description="Rows to skip (pagination)")
Branch = Query(None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$", description="Branch id, e.g. BR001")
Medicine = Query(None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$", description="Medicine id, e.g. MED001")
Level = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def _filter(df, **eq):
    for col, val in eq.items():
        if val is not None:
            df = df[df[col] == val]
    return df


@router.get("/action-queue", response_model=ListResponse, summary="Get prioritized decision-support actions",
            description="One row per branch x medicine, ordered by `queue_position` (priority, then score). "
                        "Each row carries its evidence, reason and secondary reasons.")
def action_queue(priority: Level | None = None,
                 action: Literal["ORDER_NOW", "REORDER_SOON", "MONITOR_STOCK_CLOSELY", "PRIORITIZE_SALE_EXPIRING_STOCK",
                                 "MONITOR_EXPIRY", "REVIEW_OVERSTOCK", "MONITOR", "NO_DEMAND_DATA"] | None = None,
                 branch_id: str | None = Branch, medicine_id: str | None = Medicine,
                 limit: int = Limit, offset: int = Offset):
    df = _filter(load_report("decision", "action_queue.csv"), priority=priority, primary_action=action,
                 branch_id=branch_id, medicine_id=medicine_id)
    return list_response(df.sort_values("queue_position"), limit, offset)


@router.get("/stockout-risk", response_model=ListResponse, summary="Get stockout risk per branch and medicine",
            description="Stock, expected demand, days of cover, risk level and stockout history, in the report's risk order.")
def stockout_risk(risk_level: Level | Literal["NO_DEMAND_DATA"] | None = None, branch_id: str | None = Branch,
                  medicine_id: str | None = Medicine, limit: int = Limit, offset: int = Offset):
    df = _filter(load_report("decision", "stockout_risk.csv"), risk_level=risk_level, branch_id=branch_id, medicine_id=medicine_id)
    return list_response(df, limit, offset)


@router.get("/reorder", response_model=ListResponse, summary="Get reorder recommendations",
            description="Reorder point, safety stock and suggested order quantity under the documented planning assumptions "
                        "(7-day lead time, 95% service level, 14-day order cover).")
def reorder(recommendation: Literal["ORDER_NOW", "REORDER_SOON", "NO_REORDER", "NO_DEMAND_DATA"] | None = None,
            branch_id: str | None = Branch, medicine_id: str | None = Medicine, limit: int = Limit, offset: int = Offset):
    df = _filter(load_report("decision", "reorder_recommendations.csv"), recommendation=recommendation,
                 branch_id=branch_id, medicine_id=medicine_id)
    return list_response(df, limit, offset)


@router.get("/overstock", response_model=ListResponse, summary="Get overstock risk",
            description="Overstock classification with estimated excess units and value (an estimate of exposure, not a loss). "
                        "Defaults to OVERSTOCK rows; pass overstock_level=NORMAL for the rest.")
def overstock(overstock_level: Literal["OVERSTOCK", "NORMAL"] | None = "OVERSTOCK", branch_id: str | None = Branch,
              medicine_id: str | None = Medicine, limit: int = Limit, offset: int = Offset):
    df = _filter(load_report("decision", "overstock_risk.csv"), overstock_level=overstock_level, branch_id=branch_id, medicine_id=medicine_id)
    return list_response(df, limit, offset)


@router.get("/expiry", response_model=ListResponse, summary="Get batch-level expiry actions",
            description="Live batch lots with days to expiry, projected unsold units and value, risk level and recommended action.")
def expiry(risk_level: Level | None = None, branch_id: str | None = Branch, medicine_id: str | None = Medicine,
           limit: int = Limit, offset: int = Offset):
    df = _filter(load_report("decision", "expiry_actions.csv"), risk_level=risk_level, branch_id=branch_id, medicine_id=medicine_id)
    return list_response(df, limit, offset)
