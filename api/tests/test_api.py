"""API smoke tests. They need PostgreSQL running with the loaded warehouse and the generated reports.  Run:  python -m pytest api/tests -q"""
import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def get(url, status=200):
    r = client.get(url)
    assert r.status_code == status, r.text
    return r.json()


def test_health():
    assert get("/health") == {"status": "ok"}


def test_ready_checks_database():
    assert get("/ready") == {"status": "ready", "database": "connected"}


def test_dashboard_summary_matches_decision_report():
    d = get("/api/dashboard/summary")["data"]
    for k in ("total_revenue", "total_units_sold", "total_transactions", "average_transaction_value", "current_inventory_units",
              "current_inventory_value", "stockout_days", "expired_units", "expiry_risk_value", "overstock_count",
              "recommended_order_units", "critical_actions", "high_actions", "medium_actions", "low_actions"):
        assert isinstance(d[k], (int, float)), k
    assert d["critical_actions"] + d["high_actions"] + d["medium_actions"] + d["low_actions"] == 2500
    assert d["total_revenue"] > 0 and d["total_transactions"] > 0


def test_sales_with_date_range():
    d = get("/api/analytics/sales?start_date=2026-01-01&end_date=2026-12-31")["data"]
    assert d["revenue"] > 0 and len(d["monthly_trend"]) == 12 and d["category_performance"]
    assert abs(sum(m["revenue"] for m in d["monthly_trend"]) - d["revenue"]) < 0.01
    full = get("/api/analytics/sales")["data"]
    assert full["revenue"] > d["revenue"]


def test_inventory_status_filter_and_pagination():
    j = get("/api/analytics/inventory?status=LOW%20STOCK&limit=5")
    assert j["count"] <= 5 and j["summary"]["low_stock"] == j["total"]
    assert all(r["stock_status"] == "LOW STOCK" for r in j["data"])


def test_branches_and_medicines():
    b = get("/api/analytics/branches")
    assert b["count"] == 5 and b["total"] == 5
    m = get("/api/analytics/medicines?limit=20&sort_by=units")
    assert m["count"] == 20 and m["total"] == 500
    units = [r["units"] for r in m["data"]]
    assert units == sorted(units, reverse=True)


def test_mining_association_rules():
    j = get("/api/mining/association-rules?limit=3&min_lift=2")
    assert j["count"] == 3 and all(r["lift"] >= 2 for r in j["data"])
    assert {"antecedent", "consequent", "support", "confidence", "lift"} <= set(j["data"][0])


def test_mining_clusters_and_anomalies():
    c = get("/api/mining/clusters?limit=5")
    assert c["summary"] and isinstance(c["summary"][0]["centroid_z_scores"], dict) and c["count"] == 5
    a = get("/api/mining/anomalies?anomaly_type=supply_delay&limit=5")
    assert all(r["anomaly_type"] == "supply_delay" for r in a["data"])


def test_forecasts_default_is_live_origin():
    j = get("/api/forecasts?branch_id=BR001&medicine_id=MED001")
    assert j["total"] == 3 and sorted(r["horizon"] for r in j["data"]) == [7, 14, 30]
    assert all(r["forecast_date"] == "2026-12-31" and r["predicted_units"] is not None for r in j["data"])
    assert get("/api/forecasts?horizon=7&limit=1")["total"] == 2500


def test_action_queue_filters():
    j = get("/api/decisions/action-queue?priority=CRITICAL&limit=10")
    assert j["total"] == 79 and j["count"] == 10
    assert [r["queue_position"] for r in j["data"]] == sorted(r["queue_position"] for r in j["data"])
    assert all(r["priority"] == "CRITICAL" for r in j["data"])
    assert get("/api/decisions/action-queue?action=ORDER_NOW&branch_id=BR003")["total"] > 0


@pytest.mark.parametrize("path,total", [("stockout-risk", 2500), ("reorder", 2500), ("overstock", 593), ("expiry", 5500)])
def test_decision_reports(path, total):
    j = get(f"/api/decisions/{path}?limit=2")
    assert j["total"] == total and j["count"] == 2


@pytest.mark.parametrize("url", [
    "/api/decisions/action-queue?priority=URGENT",       # not an allowed value
    "/api/decisions/action-queue?limit=0",
    "/api/decisions/action-queue?limit=100000",
    "/api/decisions/action-queue?branch_id=BR1;DROP",    # fails the id pattern
    "/api/analytics/sales?start_date=not-a-date",
    "/api/analytics/sales?start_date=2026-12-31&end_date=2026-01-01",
    "/api/analytics/inventory?status=BROKEN",
    "/api/forecasts?horizon=5",
])
def test_invalid_filters_are_rejected(url):
    get(url, 422)


def test_missing_report_gives_clear_500(monkeypatch):
    from api import database
    monkeypatch.setitem(database.REPORT_DIRS, "decision", "decision_support/no_such_dir")
    r = client.get("/api/decisions/expiry")
    assert r.status_code == 500 and "not been generated" in r.json()["detail"]
    assert "decision_support" not in r.text and "Users" not in r.text      # no filesystem paths leak


def test_openapi_and_swagger_available():
    assert client.get("/docs").status_code == 200 and client.get("/redoc").status_code == 200
    assert "/api/decisions/action-queue" in get("/openapi.json")["paths"]
