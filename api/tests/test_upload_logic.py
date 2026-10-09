"""Unit tests for the upload pipeline logic that needs no database: cleaning invariants and FEFO stock allocation."""
import pandas as pd
import pytest

from datasets import purchase_validation as pv
from datasets import sales_validation as sv
from datasets.allocation import allocate_fefo


def _sales_csv(tmp_path, rows):
    p = tmp_path / "sales.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def _many(n=150, **kw):
    base = {"transaction_date": "2025-01-05", "medicine_id": "M1", "quantity": 2, "unit_selling_price": 10.0}
    return [{**base, "transaction_id": f"T{i}", **kw} for i in range(n)]


def test_cleaned_sales_satisfy_the_warehouse_money_rule(tmp_path):
    rows = _many(120, discount=1.0) + [
        {"transaction_id": "TX", "transaction_date": "2025-01-06", "medicine_id": "M2", "quantity": 3, "unit_selling_price": 0.0, "discount": 0},       # zero price: dropped
        {"transaction_id": "TY", "transaction_date": "2025-01-07", "medicine_id": "M2", "quantity": 4, "unit_selling_price": 5.555, "discount": 99},   # discount > value
        {"transaction_id": "T0", "transaction_date": "2025-01-05", "medicine_id": "M1", "quantity": 1, "unit_selling_price": 12.0, "discount": 0},     # duplicate line: merged
    ]
    sales, meds, report = sv.clean_sales(_sales_csv(tmp_path, rows), None)
    q, price, disc, total = (sales[c].astype(float) for c in ("quantity", "unit_selling_price", "discount", "total_amount"))
    assert ((q * price - disc).round(2) == total).all() and (price > 0).all() and (disc >= 0).all() and (total >= 0).all()
    assert report["dropped"]["zero or negative price"] == 1 and report["dropped"]["duplicate lines merged into one"] == 1
    assert not sales.duplicated(["transaction_id", "medicine_id"]).any()      # one row per (transaction, medicine)


def test_sales_without_required_columns_are_rejected(tmp_path):
    with pytest.raises(sv.ValidationError) as e:
        sv.clean_sales(_sales_csv(tmp_path, [{"a": i, "b": i} for i in range(200)]), None)
    assert "Missing required column" in e.value.messages[0]


def _lot(batch, exp, qty, recv="2025-01-01"):
    return {"purchase_id": batch, "purchase_date": recv, "branch_id": "B1", "supplier_id": "S", "medicine_id": "M1", "batch_id": batch,
            "quantity": qty, "unit_purchase_price": "5.00", "total_cost": f"{qty * 5:.2f}"}, {"batch_id": batch, "expiry_date": exp}


def _line(txn, date, qty, discount="0.00"):
    return {"transaction_id": txn, "transaction_date": date, "branch_id": "B1", "medicine_id": "M1", "batch_id": "NOBATCH-M1", "quantity": qty,
            "unit_selling_price": "10.00", "discount": discount, "total_amount": f"{qty * 10 - float(discount):.2f}"}


def test_fefo_allocation_uses_earliest_expiry_skips_expired_and_estimates_opening_stock():
    (pa, ba), (pb, bb) = _lot("A", "2025-03-01", 10), _lot("B", "2025-06-01", 10)
    purchases, batches = pd.DataFrame([pa, pb]), pd.DataFrame([ba, bb])
    sales = pd.DataFrame([_line("T1", "2025-01-10", 12, discount="3.00"),      # 10 from A (earliest expiry), 2 from B
                          _line("T2", "2025-03-05", 5),                         # A expired: from B (8 -> 3 left)
                          _line("T3", "2025-03-06", 10)])                       # only 3 left in B: 7 are unexplained -> implied opening stock
    out, op_p, op_b, stats = allocate_fefo(sales, purchases, batches, "2025-01-01")

    t1 = out[out["transaction_id"] == "T1"].set_index("batch_id")["quantity"].to_dict()
    assert t1 == {"A": 10, "B": 2}
    assert out[out["transaction_id"] == "T2"]["batch_id"].tolist() == ["B"]
    t3 = out[out["transaction_id"] == "T3"].set_index("batch_id")["quantity"].to_dict()
    assert t3 == {"B": 3, "OPENING-M1": 7}
    assert op_p["quantity"].sum() == 7 and op_b["initial_quantity"].sum() == 7 and stats["opening_units_estimated"] == 7
    # units are conserved and every split line still satisfies total = quantity x price - discount
    assert out["quantity"].sum() == sales["quantity"].sum()
    q, price, disc, total = (out[c].astype(float) for c in ("quantity", "unit_selling_price", "discount", "total_amount"))
    assert ((q * price - disc).round(2) == total).all()
    assert round(disc[out["transaction_id"] == "T1"].sum(), 2) == 3.00
    # no sale is dated on or after the expiry of the lot it was filled from
    exp = batches.set_index("batch_id")["expiry_date"].to_dict()
    assert all(d < exp.get(b, "2099-12-31") for d, b in zip(out["transaction_date"], out["batch_id"]))


def test_purchases_are_aligned_to_the_sales_calendar(tmp_path):
    sales = pd.DataFrame({"transaction_date": ["2025-02-01", "2025-02-28"], "branch_id": ["B1", "B1"], "medicine_id": ["M1", "M1"]})
    p = tmp_path / "p.csv"
    pd.DataFrame([
        {"d": "2025-01-15", "m": "M1", "q": 10, "c": 5, "e": "2026-01-01"},     # before the first sale -> opening stock on day 1
        {"d": "2025-02-10", "m": "M1", "q": 10, "c": 5, "e": "2026-01-01"},
        {"d": "2025-03-15", "m": "M1", "q": 10, "c": 5, "e": "2026-01-01"},     # after the last sale -> ignored
        {"d": "2025-02-10", "m": "M1", "q": 10, "c": 5, "e": "2025-02-01"},     # already expired when received -> dropped
    ]).to_csv(p, index=False)
    mapping = {"purchase_date": "d", "medicine_id": "m", "quantity": "q", "unit_purchase_price": "c", "expiry_date": "e"}
    purchases, batches, _sup, report = pv.clean_purchases(p, mapping, sales, 1, 1)
    assert sorted(purchases["purchase_date"]) == ["2025-02-01", "2025-02-10"]
    assert report["dropped"] == {"received after the last sale date (ignored)": 1, "already expired when received": 1}
    assert (batches["manufacture_date"] < batches["expiry_date"]).all()
    assert report["has_expiry"] is True


def test_multi_branch_sales_require_a_branch_column_in_purchases(tmp_path):
    sales = pd.DataFrame({"transaction_date": ["2025-02-01", "2025-02-28"], "branch_id": ["B1", "B2"], "medicine_id": ["M1", "M1"]})
    p = tmp_path / "p.csv"
    pd.DataFrame([{"d": "2025-02-10", "m": "M1", "q": 10, "c": 5}]).to_csv(p, index=False)
    with pytest.raises(sv.ValidationError) as e:
        pv.clean_purchases(p, {"purchase_date": "d", "medicine_id": "m", "quantity": "q", "unit_purchase_price": "c"}, sales, 1, 2)
    assert "branch" in e.value.messages[0]


# ── hardening: limits, content checks, automatic expiry ──────────────────────
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import app
from datasets import maintenance, paths

client = TestClient(app)


def test_rate_limiter_allows_only_the_configured_number_per_window():
    rl = maintenance.RateLimiter(window=3600)
    assert [rl.allow("a", 2) for _ in range(3)] == [True, True, False]
    assert rl.allow("b", 2) is True                      # another client is not affected
    assert rl.allow("a", 0) is True                      # 0 = unlimited


def test_non_csv_uploads_are_rejected():
    r = client.post("/api/datasets", files={"file": ("sales.xlsx", b"PK\x03\x04\x00\x00", "application/octet-stream")})
    assert r.status_code == 415
    r = client.post("/api/datasets", files={"file": ("sales.csv", b"PK\x03\x04\x00\x00binary", "text/csv")})
    assert r.status_code == 415 and "plain-text" in r.json()["detail"]


def test_stored_dataset_limit_is_enforced(monkeypatch):
    monkeypatch.setenv("MEDSTOCK_MAX_DATASETS", "1")
    monkeypatch.setattr(paths, "list_datasets", lambda: [{"id": "ds_x", "status": "ready"}])
    monkeypatch.setattr(maintenance, "uploads_per_hour", lambda: 0)
    r = client.post("/api/datasets", files={"file": ("s.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 409 and "limit" in r.json()["detail"]


def test_expired_datasets_are_removed_but_running_and_fresh_ones_are_kept(monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    new = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metas = [{"id": "ds_old", "status": "ready", "created_at": old}, {"id": "ds_running", "status": "running", "created_at": old},
             {"id": "ds_new", "status": "ready", "created_at": new}, {"id": "ds_failed", "status": "failed", "created_at": old}]
    dropped = []
    monkeypatch.setattr(paths, "list_datasets", lambda: metas)
    monkeypatch.setattr(maintenance, "drop_dataset", dropped.append)
    monkeypatch.setenv("MEDSTOCK_RETENTION_DAYS", "14")
    assert sorted(maintenance.cleanup_expired()) == ["ds_failed", "ds_old"] and sorted(dropped) == ["ds_failed", "ds_old"]
    monkeypatch.setenv("MEDSTOCK_RETENTION_DAYS", "0")                      # 0 = keep forever
    dropped.clear()
    assert maintenance.cleanup_expired() == [] and dropped == []


def test_the_demo_dataset_can_never_be_dropped():
    with pytest.raises(ValueError):
        maintenance.drop_dataset("demo")
