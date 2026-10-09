"""Analytics: reads the warehouse star schema and the analytics views (analytics/sql/views.sql). Parameterized SQL only."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from ..database import query
from ..schemas import ListResponse, ObjectResponse

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

Limit = Query(100, ge=1, le=1000, description="Maximum rows to return")
Offset = Query(0, ge=0, description="Rows to skip (pagination)")
Branch = Query(None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$", description="Branch id, e.g. BR001")


def _page(sql: str, params: dict, limit: int, offset: int) -> dict:
    """Run a query that returns a `total_rows` window column and build the standard list envelope."""
    rows = query(sql + " LIMIT :limit OFFSET :offset", {**params, "limit": limit, "offset": offset})
    total = rows[0].pop("total_rows") if rows else 0
    for r in rows[1:]:
        r.pop("total_rows")
    return {"data": rows, "count": len(rows), "total": total}


@router.get("/sales", response_model=ObjectResponse, summary="Get sales KPIs, monthly trend and category performance",
            description="Revenue, units, transactions and average transaction value from `fact_sales`, optionally restricted to a date range (inclusive).")
def sales(start_date: date | None = Query(None, description="YYYY-MM-DD"), end_date: date | None = Query(None, description="YYYY-MM-DD")):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "start_date must not be after end_date")
    p = {"s": start_date, "e": end_date}
    where = "WHERE (CAST(:s AS date) IS NULL OR d.full_date >= CAST(:s AS date)) AND (CAST(:e AS date) IS NULL OR d.full_date <= CAST(:e AS date))"
    base = "FROM warehouse.fact_sales s JOIN warehouse.dim_date d ON d.date_key = s.date_key "
    totals = query("SELECT COALESCE(SUM(s.total_amount), 0) AS revenue, COALESCE(SUM(s.quantity), 0) AS units, "
                   "COUNT(DISTINCT s.transaction_id) AS transactions, "
                   "ROUND(SUM(s.total_amount) / NULLIF(COUNT(DISTINCT s.transaction_id), 0), 2) AS avg_transaction_value " + base + where, p)[0]
    trend = query("SELECT d.year, d.month, d.month_name, SUM(s.total_amount) AS revenue, SUM(s.quantity) AS units, "
                  "COUNT(DISTINCT s.transaction_id) AS transactions " + base + where + " GROUP BY d.year, d.month, d.month_name ORDER BY d.year, d.month", p)
    cats = query("SELECT c.category_name, SUM(s.total_amount) AS revenue, SUM(s.quantity) AS units, "
                 "COUNT(DISTINCT s.transaction_id) AS transactions, "
                 "ROUND(100.0 * SUM(s.total_amount) / NULLIF(SUM(SUM(s.total_amount)) OVER (), 0), 2) AS revenue_share_pct "
                 + base + "JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key "
                 "JOIN warehouse.dim_category c ON c.category_key = m.category_key " + where +
                 " GROUP BY c.category_name ORDER BY revenue DESC", p)
    return {"data": {**totals, "start_date": start_date, "end_date": end_date, "monthly_trend": trend, "category_performance": cats}}


@router.get("/inventory", summary="Get current inventory with days of cover and stock status",
            description="Rows of `v_current_inventory` (latest snapshot date; stock is never summed across dates). "
                        "Use `status` for low-stock or overstock lists. `summary` gives totals and counts per status.")
def inventory(status: Literal["OUT OF STOCK", "LOW STOCK", "OVERSTOCK", "NORMAL"] | None = None, branch_id: str | None = Branch,
              limit: int = Limit, offset: int = Offset):
    f = "FROM warehouse.v_current_inventory v JOIN warehouse.dim_branch b ON b.branch_key = v.branch_key " \
        "JOIN warehouse.dim_medicine m ON m.medicine_key = v.medicine_key " \
        "WHERE (CAST(:st AS text) IS NULL OR v.stock_status = CAST(:st AS text)) AND (CAST(:b AS text) IS NULL OR b.branch_id = CAST(:b AS text))"
    p = {"st": status, "b": branch_id}
    summary = query("SELECT MAX(v.snapshot_date) AS snapshot_date, COALESCE(SUM(v.stock_units), 0) AS total_units, "
                    "COALESCE(SUM(v.stock_value_at_cost), 0) AS total_value_at_cost, COUNT(*) AS pairs, "
                    "COUNT(*) FILTER (WHERE v.stock_status = 'OUT OF STOCK') AS out_of_stock, "
                    "COUNT(*) FILTER (WHERE v.stock_status = 'LOW STOCK') AS low_stock, "
                    "COUNT(*) FILTER (WHERE v.stock_status = 'OVERSTOCK') AS overstock, "
                    "COUNT(*) FILTER (WHERE v.stock_status = 'NORMAL') AS normal " + f, p)[0]
    out = _page("SELECT b.branch_id, v.branch_name, m.medicine_id, v.medicine_name, v.category_name, v.stock_units, v.stock_value_at_cost, "
                "v.avg_daily_demand_30d, v.days_of_inventory, v.stock_status, COUNT(*) OVER () AS total_rows " + f +
                " ORDER BY v.days_of_inventory ASC NULLS LAST, v.stock_units, b.branch_id, m.medicine_id", p, limit, offset)
    return {"summary": summary, **out}


@router.get("/branches", response_model=ListResponse, summary="Get branch performance, inventory and stockouts",
            description="Per branch: revenue, units, transactions (`v_branch_performance`), current stock and stock value (`v_current_inventory`), "
                        "and stockout days / rate over the whole period (`v_stockout_summary`).")
def branches(limit: int = Limit, offset: int = Offset):
    return _page("""
        SELECT p.branch_id, p.branch_name, p.area, p.revenue, p.units, p.transactions, p.avg_transaction_value, p.active_medicines,
               p.revenue_share_pct, p.revenue_rank, inv.stock_units, inv.stock_value_at_cost, inv.out_of_stock_medicines,
               so.stockout_days, so.days_observed, ROUND(100.0 * so.stockout_days / NULLIF(so.days_observed, 0), 3) AS stockout_rate_pct,
               COUNT(*) OVER () AS total_rows
        FROM warehouse.v_branch_performance p
        LEFT JOIN (SELECT branch_key, SUM(stock_units) AS stock_units, SUM(stock_value_at_cost) AS stock_value_at_cost,
                          COUNT(*) FILTER (WHERE stock_units = 0) AS out_of_stock_medicines
                   FROM warehouse.v_current_inventory GROUP BY branch_key) inv ON inv.branch_key = p.branch_key
        LEFT JOIN (SELECT branch_key, SUM(stockout_days) AS stockout_days, SUM(days_observed) AS days_observed
                   FROM warehouse.v_stockout_summary GROUP BY branch_key) so ON so.branch_key = p.branch_key
        ORDER BY p.revenue_rank""", {}, limit, offset)


_MED_SORT = {"revenue": "p.revenue DESC", "units": "p.units DESC", "days_of_cover": "days_of_cover ASC NULLS LAST", "turnover": "turnover_annualised DESC NULLS LAST"}


@router.get("/medicines", response_model=ListResponse, summary="Get medicine performance, demand, inventory and turnover",
            description="Per medicine: revenue, units, mover class (`v_medicine_performance`), 30-day demand and current stock across branches, "
                        "days of cover, and annualised inventory turnover (cost of goods sold / average inventory value, as in `analytics/sql/inventory.sql`).")
def medicines(sort_by: Literal["revenue", "units", "days_of_cover", "turnover"] = "revenue",
              mover_class: Literal["FAST", "MEDIUM", "SLOW"] | None = None, limit: int = Limit, offset: int = Offset):
    sql = """
        SELECT p.medicine_id, p.medicine_name, p.category_name, p.manufacturer, p.units, p.revenue, p.transactions, p.avg_selling_price,
               p.avg_daily_units, p.revenue_rank, p.mover_class, inv.stock_units, inv.stock_value_at_cost, inv.avg_daily_demand_30d,
               ROUND(inv.stock_units / NULLIF(inv.avg_daily_demand_30d, 0), 1) AS days_of_cover,
               ROUND(cg.cogs / NULLIF(av.avg_value, 0) * 365.25 / cal.days, 3) AS turnover_annualised,
               COUNT(*) OVER () AS total_rows
        FROM warehouse.v_medicine_performance p
        LEFT JOIN (SELECT medicine_key, SUM(stock_units) AS stock_units, SUM(stock_value_at_cost) AS stock_value_at_cost,
                          SUM(avg_daily_demand_30d) AS avg_daily_demand_30d
                   FROM warehouse.v_current_inventory GROUP BY medicine_key) inv ON inv.medicine_key = p.medicine_key
        LEFT JOIN (SELECT s.medicine_key, SUM(s.quantity * b.purchase_price) AS cogs
                   FROM warehouse.fact_sales s JOIN warehouse.dim_batch b ON b.batch_key = s.batch_key
                   GROUP BY s.medicine_key) cg ON cg.medicine_key = p.medicine_key
        LEFT JOIN (SELECT medicine_key, SUM(closing_value_at_cost) / COUNT(DISTINCT date_key) AS avg_value
                   FROM warehouse.fact_inventory GROUP BY medicine_key) av ON av.medicine_key = p.medicine_key
        CROSS JOIN (SELECT COUNT(*)::numeric AS days FROM warehouse.dim_date) cal
        WHERE (CAST(:mc AS text) IS NULL OR p.mover_class = CAST(:mc AS text))
        ORDER BY """ + _MED_SORT[sort_by] + ", p.medicine_id"      # sort column comes from a fixed whitelist, never from the client
    return _page(sql, {"mc": mover_class}, limit, offset)
