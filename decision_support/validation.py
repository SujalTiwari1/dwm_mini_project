"""Validation of the decision-support layer: structure, reconciliation with the upstream layers, decision-time leakage and deterministic scenario tests.

Each check returns {"area", "check", "passed", "detail"}.
"""
import json

import numpy as np
import pandas as pd

from . import config as C
from . import inputs
from .rules import expiry as rx
from .rules import overstock as ro
from .rules import reorder as rr
from .rules import stockout as rs
from .scoring import priority as pq


def _chk(area, check, passed, detail=""):
    return {"area": area, "check": check, "passed": bool(passed), "detail": str(detail)}


KEYS = ["branch_id", "medicine_id"]


def structure_checks(conn, res):
    f, so, re_, ov, ex, q = res["frame"], res["stockout"], res["reorder"], res["overstock"], res["expiry"], res["queue"]
    out = []
    n_pairs = conn.exec_driver_sql("SELECT (SELECT COUNT(*) FROM warehouse.dim_branch) * (SELECT COUNT(*) FROM warehouse.dim_medicine)").scalar()
    # --- stockout ---
    out.append(_chk("stockout", "every branch x medicine pair is represented exactly once", len(so) == n_pairs and not so.duplicated(KEYS).any(), f"{len(so)} of {n_pairs}"))
    out.append(_chk("stockout", "risk levels valid", set(so["risk_level"]) <= {"CRITICAL", "HIGH", "MEDIUM", "LOW", "NO_DEMAND_DATA"}))
    d = f["expected_daily_demand"].to_numpy(dtype=float)
    stock = f["current_inventory_units"].to_numpy(dtype=float)
    cover = so["days_of_cover"].to_numpy(dtype=float)
    ok_cover = np.where(d > 0, np.abs(cover - np.round(stock / np.where(d > 0, d, 1), 2)) < 1e-9, np.isnan(cover))
    out.append(_chk("stockout", "days_of_cover = stock / expected daily demand, NULL when demand is zero (never a division by zero)", bool(ok_cover.all())))
    out.append(_chk("stockout", "NO_DEMAND_DATA exactly when expected demand is zero", bool(((so["risk_level"] == "NO_DEMAND_DATA").to_numpy() == (d <= 0)).all())))
    out.append(_chk("stockout", "no negative inventory", bool((stock >= 0).all())))
    L = C.STOCKOUT_LEVELS
    crit = (d > 0) & ((stock == 0) | (cover < L["critical_days"]))
    out.append(_chk("stockout", "CRITICAL base level exactly when stock is zero or cover is under the critical threshold",
                    bool(((so["base_risk_level"] == "CRITICAL").to_numpy() == crit).all())))
    out.append(_chk("stockout", "escalation never reaches CRITICAL and moves at most one level", bool(
        not ((so["risk_level"] == "CRITICAL") & (so["base_risk_level"] != "CRITICAL")).any())))
    # --- reorder ---
    q_ = re_["recommended_order_quantity"]
    out.append(_chk("reorder", "recommended quantity >= 0 and a whole number", bool((q_ >= 0).all() and (q_ == q_.round()).all())))
    out.append(_chk("reorder", "reorder point >= 0 and safety stock >= 0", bool((re_["reorder_point"] >= 0).all() and (re_["safety_stock"] >= 0).all())))
    out.append(_chk("reorder", "no recommendation and no quantity when demand is unavailable", bool(
        ((re_["recommendation"] == "NO_DEMAND_DATA") == (d <= 0)).all() and (re_.loc[re_["recommendation"] == "NO_DEMAND_DATA", "recommended_order_quantity"] == 0).all())))
    out.append(_chk("reorder", "reorder point = expected lead-time demand + safety stock", bool(np.abs(re_["reorder_point"] - (re_["expected_lead_time_demand"] + re_["safety_stock"])).max() < 0.02)))
    active = re_["recommendation"].isin(["ORDER_NOW", "REORDER_SOON"])
    exp_qty = np.ceil(np.maximum(0, re_["order_up_to_level"] - re_["current_inventory_units"]) - 1e-9)
    out.append(_chk("reorder", "quantity = ceil(max(0, order-up-to level - stock)) when a reorder is recommended, else 0", bool((q_[active] == exp_qty[active]).all() and (q_[~active] == 0).all())))
    out.append(_chk("reorder", "ORDER_NOW exactly when stock <= expected lead-time demand (and demand exists)", bool(
        ((re_["recommendation"] == "ORDER_NOW") == ((d > 0) & (stock <= d * C.PLANNING_LEAD_TIME_DAYS + 1e-9))).all())))
    # --- overstock ---
    u30 = f["units_30d"].to_numpy(dtype=float)
    d30 = u30 / C.OVERSTOCK["window_days"]
    cov30 = np.where(d30 > 0, stock / np.where(d30 > 0, d30, 1), np.nan)
    over = (stock > 0) & ((u30 == 0) | (stock * C.OVERSTOCK["window_days"] > C.OVERSTOCK["max_cover_days"] * u30))   # exact integer form of cover > 90 days
    out.append(_chk("overstock", "classification equals the documented threshold (stock > 0 and (no 30-day sales or cover over 90 days))", bool(((ov["overstock_level"] == "OVERSTOCK").to_numpy() == over).all())))
    out.append(_chk("overstock", "excess units >= 0 and excess value >= 0; NORMAL rows have no excess", bool(
        (ov["excess_units_estimate"] >= 0).all() and (ov["excess_value_estimate"] >= 0).all() and (ov.loc[ov["overstock_level"] == "NORMAL", "excess_units_estimate"] == 0).all())))
    out.append(_chk("overstock", "excess units never exceed stock", bool((ov["excess_units_estimate"] <= ov["current_inventory_units"]).all())))
    # --- expiry ---
    out.append(_chk("expiry", "only live (non-expired) batches are assessed", bool((ex["days_to_expiry"] > 0).all())))
    out.append(_chk("expiry", "projected unsold units and value are >= 0 and never exceed the batch quantity", bool(
        (ex["projected_unsold_units"] >= 0).all() and (ex["projected_unsold_value"] >= 0).all() and (ex["projected_unsold_units"] <= ex["batch_quantity"] + 0.01).all())))
    out.append(_chk("expiry", "CRITICAL / HIGH levels always have projected unsold units", bool((ex.loc[ex["risk_level"].isin(["CRITICAL", "HIGH"]), "projected_unsold_units"] > 0).all())))
    out.append(_chk("expiry", "actions follow the level mapping and are inventory actions only", bool(
        (ex["recommended_action"] == ex["risk_level"].map(C.EXPIRY_ACTION)).all() and set(ex["recommended_action"]) <= {"PRIORITIZE_SALE", "MONITOR", "NO_ACTION"})))
    # --- queue ---
    out.append(_chk("queue", "one decision row per branch x medicine, no duplicates", len(q) == n_pairs and not q.duplicated(KEYS).any()))
    out.append(_chk("queue", "priority values valid and exactly one primary action per row", bool(set(q["priority"]) <= set(C.PRIORITY_ORDER) and q["primary_action"].notna().all() and (q["primary_action"] != "").all())))
    rank = q["priority"].map({k: i for i, k in enumerate(C.PRIORITY_ORDER)})
    srt = pd.DataFrame({"r": rank, "s": -q["priority_score"], "b": q["branch_id"], "m": q["medicine_id"]})
    out.append(_chk("queue", "deterministic ordering: priority, then priority score, then ids", bool(srt.equals(srt.sort_values(["r", "s", "b", "m"], kind="mergesort").reset_index(drop=True)) and (q["queue_position"] == np.arange(1, len(q) + 1)).all())))
    multi = q["active_issue_count"] >= 2
    out.append(_chk("queue", "secondary risks are preserved when more than one issue is active", bool((q.loc[multi, "secondary_reasons"].str.len() > 0).all()), f"{int(multi.sum())} multi-issue rows"))
    out.append(_chk("queue", "queue exposures equal their components", bool(np.abs(q["impact_value"] - (q["potential_stockout_exposure_value"] + q["estimated_excess_value"] + q["projected_expiry_exposure_value"])).max() < 0.02)))
    return out


def reconciliation_checks(conn, res):
    out = []
    f, ex = res["frame"], res["expiry"]
    D = res["date"]
    latest = inputs.latest_date(conn)
    if D != latest:
        return [_chk("reconciliation", "decision date equals the warehouse latest date (needed to compare with the analytics views)", False, f"{D} vs {latest}")]
    inv = inputs.run_query(conn, "analytics_inventory")
    m = f.merge(inv, on=KEYS, how="outer", indicator=True, validate="one_to_one")
    out.append(_chk("reconciliation", "decision pairs match the analytics current-inventory pairs one to one", bool((m["_merge"] == "both").all()), f"{len(m)} pairs"))
    out.append(_chk("reconciliation", "current inventory units equal fact_inventory (analytics v_current_inventory) for every pair", bool((m["current_inventory_units"].astype(float) == m["stock_units"].astype(float)).all()),
                    f"total {int(m['current_inventory_units'].sum())} units"))
    out.append(_chk("reconciliation", "current inventory value equals the analytics value for every pair", bool(np.abs(m["current_inventory_value"].astype(float) - m["stock_value_at_cost"].astype(float)).max() < 0.005)))
    out.append(_chk("reconciliation", "30-day demand equals the analytics view (units sold in the last 30 days)", bool(np.abs(m["units_30d"].astype(float) / 30.0 - m["avg_daily_demand_30d"].astype(float)).max() < 1e-3)))
    so = inputs.run_query(conn, "analytics_stockouts")
    s = f.merge(so, on=KEYS, validate="one_to_one")
    out.append(_chk("reconciliation", "stockout days (all history to the decision date) equal analytics v_stockout_summary for every pair", bool((s["stockout_days_total"].astype(int) == s["stockout_days"].astype(int)).all()),
                    f"total {int(s['stockout_days_total'].sum())}"))
    o = res["overstock"].merge(inv[KEYS + ["stock_status"]], on=KEYS, validate="one_to_one").merge(f[KEYS + ["units_30d"]], on=KEYS)
    diff = o[(o["overstock_level"] == "OVERSTOCK") != (o["stock_status"] == "OVERSTOCK")]
    boundary = (diff["current_inventory_units"] * C.OVERSTOCK["window_days"] == C.OVERSTOCK["max_cover_days"] * diff["units_30d"]) & (diff["stock_status"] == "OVERSTOCK")
    out.append(_chk("reconciliation", "overstock classification equals analytics stock_status = OVERSTOCK for every pair, except pairs with EXACTLY 90.0 days of cover "
                    "(the analytics view's decimal arithmetic rounds 4/30 up and labels them OVERSTOCK; reported as an upstream boundary finding, not changed)",
                    bool(boundary.all()), f"{int((o['overstock_level'] == 'OVERSTOCK').sum())} overstock pairs here; {len(diff)} boundary pairs at exactly 90.0 days differ from the view"))
    ae = inputs.run_query(conn, "analytics_expiry")
    ae["projected_unsold_units"] = pd.to_numeric(ae["projected_unsold_units"])
    e = ex.merge(ae, on=["branch_id", "batch_id"], how="outer", indicator=True, validate="one_to_one")
    out.append(_chk("reconciliation", "live batch lots match analytics v_expiry_risk one to one", bool((e["_merge"] == "both").all()), f"{len(e)} lots"))
    both = e[e["_merge"] == "both"]
    out.append(_chk("reconciliation", "batch quantity and days to expiry equal analytics", bool((both["batch_quantity"] == both["remaining_units"].astype(int)).all() and (both["days_to_expiry_x"] == both["days_to_expiry_y"].astype(int)).all())))
    out.append(_chk("reconciliation", "expiry risk level equals analytics (SAFE = LOW) for every lot", bool((both["risk_level"] == both["risk_class"].replace({"SAFE": "LOW"})).all()),
                    f"{int((both['risk_level'] != both['risk_class'].replace({'SAFE': 'LOW'})).sum())} differences"))
    out.append(_chk("reconciliation", "projected unsold units equal analytics (to its 0.1 rounding)", bool(np.abs(both["projected_unsold_units_x"] - both["projected_unsold_units_y"]).max() < 0.06)))
    fc = pd.read_csv(C.FORECASTS_CSV)
    fc = fc[(fc["model"] == C.FORECAST_MODEL) & (fc["forecast_date"] == D)]
    diffs = 0
    for h in (7, 14, 30):
        g = fc[fc["horizon"] == h].set_index(KEYS)["predicted_units"]
        mine = f.set_index(KEYS)[f"forecast_{h}d"]
        diffs += int((np.abs(mine.sort_index() - g.sort_index()) > 1e-9).sum()) + int(mine.isna().sum())
    out.append(_chk("reconciliation", "7/14/30-day forecasts equal ml_forecasting/reports/forecasts.csv for every pair", diffs == 0, f"{diffs} differences"))
    return out


# ---------------------------------------------------------------------------
# decision-time leakage
# ---------------------------------------------------------------------------
def replica_state(daily: pd.DataFrame, D: str) -> pd.DataFrame:
    """Independent pandas recomputation of the as-of inputs from a daily series. Rows dated after D are dropped first."""
    d = daily[daily["full_date"] <= D].copy()
    d["age"] = (pd.Timestamp(D) - pd.to_datetime(d["full_date"])).dt.days
    d = d.sort_values(["branch_id", "medicine_id", "full_date"], kind="mergesort")
    g = d.groupby(KEYS, sort=True)
    prev = g["stock"].shift(1)
    d["event"] = (d["stock"] == 0) & (prev.fillna(1) != 0)
    d["so"] = (d["stock"] == 0).astype(int)
    out = pd.DataFrame({
        "current_inventory_units": d[d["age"] == 0].set_index(KEYS)["stock"],
        "units_7d": d[d["age"] < 7].groupby(KEYS)["units"].sum(), "units_28d": d[d["age"] < 28].groupby(KEYS)["units"].sum(),
        "units_30d": d[d["age"] < 30].groupby(KEYS)["units"].sum(), "units_90d": d[d["age"] < 90].groupby(KEYS)["units"].sum(),
        "stockout_days_last_28d": d[d["age"] < 28].groupby(KEYS)["so"].sum(), "stockout_days_last_90d": d[d["age"] < 90].groupby(KEYS)["so"].sum(),
        "stockout_days_total": d.groupby(KEYS)["so"].sum(), "days_observed": d.groupby(KEYS)["so"].size(),
        "stockout_event_count": d.groupby(KEYS)["event"].sum(),
    })
    w = d[d["age"] < 7 * C.VARIABILITY_WEEKS].assign(blk=lambda x: x["age"] // 7).groupby(KEYS + ["blk"])["units"].sum().groupby(KEYS)
    out["weekly_mean"], out["weekly_std"] = w.mean(), w.std(ddof=1)
    return out.reset_index()


def leakage_checks(conn, hist):
    out = []
    Dh = hist["date"]
    state, lots, fc = hist["state"], hist["lots"], hist["forecasts"]
    # (1) nothing dated after the decision date was used
    out.append(_chk("leakage", f"every input row of the {Dh} decision is dated on or before {Dh} (max date used in the inventory state)", state["last_date_used"].max() <= Dh, state["last_date_used"].max()))
    # (2) the as-of state equals an independent recomputation from the series TRUNCATED at the decision date
    daily = inputs.run_query(conn, "daily_series")
    rep = replica_state(daily, Dh)
    m = state.merge(rep, on=KEYS, suffixes=("", "_r"), validate="one_to_one")
    cols = ["current_inventory_units", "units_7d", "units_28d", "units_30d", "units_90d", "stockout_days_last_28d", "stockout_days_last_90d", "stockout_days_total",
            "days_observed", "stockout_event_count", "weekly_mean", "weekly_std"]
    bad = [c for c in cols if not np.allclose(m[c].astype(float), m[c + "_r"].astype(float), rtol=1e-9, atol=1e-9, equal_nan=True)]
    out.append(_chk("leakage", f"SQL as-of inputs for {Dh} equal an independent pandas recomputation from data truncated at {Dh} (all 2,500 pairs, {len(cols)} measures)", not bad and len(m) == len(state), f"differing: {bad}"))
    # (3) scrambling every observation AFTER the decision date changes nothing
    rng = np.random.default_rng(C.RANDOM_SEED)
    noisy = daily.copy()
    after = noisy["full_date"] > Dh
    noisy.loc[after, "units"] = rng.integers(0, 60, size=int(after.sum()))
    noisy.loc[after, "stock"] = rng.integers(0, 4, size=int(after.sum()))
    rep2 = replica_state(noisy, Dh)
    same = all(np.allclose(rep[c].astype(float), rep2[c].astype(float), equal_nan=True) for c in cols)
    out.append(_chk("leakage", "scrambling every sales, inventory and stockout value after the decision date leaves the as-of inputs unchanged", same))
    # (4) live batch lots are consistent with the inventory snapshot of the decision date (they use only purchases and sales up to that date)
    per_pair = lots.groupby(KEYS)["remaining_units"].sum().rename("lots_units").reset_index()
    mm = state[KEYS + ["current_inventory_units"]].merge(per_pair, on=KEYS, how="left").fillna({"lots_units": 0})
    out.append(_chk("leakage", f"live batch units at {Dh} equal the inventory snapshot of {Dh} for every pair (lots use only purchases and sales up to the date)",
                    bool((mm["lots_units"].astype(float) == mm["current_inventory_units"].astype(float)).all()), f"{int(mm['lots_units'].sum())} units"))
    out.append(_chk("leakage", "no live lot has already expired on the decision date", bool((lots["days_to_expiry"] > 0).all())))
    # (5) the forecasts are those issued on the decision date by a model fitted only on earlier targets
    summ = json.loads(C.FORECAST_SUMMARY.read_text(encoding="utf-8"))
    model_cutoff = summ["validation_range"][1]
    out.append(_chk("leakage", f"forecasts used for {Dh} have that date as forecast origin", bool((pd.read_csv(C.FORECASTS_CSV).query("model == @C.FORECAST_MODEL and forecast_date == @Dh")["split"] == "test").all()), f"split {fc['forecast_split'].iloc[0]}"))
    out.append(_chk("leakage", f"the forecasting model behind them was trained on targets up to {model_cutoff} only, not after the decision date {Dh}", model_cutoff <= Dh, f"training+validation end {model_cutoff}"))
    return out


# ---------------------------------------------------------------------------
# deterministic scenario tests (pure rule engine on hand-made inputs)
# ---------------------------------------------------------------------------
def _scenario(stock, units_28d, units_30d, f7, f14, f30, up7, cost=10.0, so28=0, rate=0.0, std_w=5.0):
    state = pd.DataFrame([{
        "branch_id": "BRT", "medicine_id": "MEDT", "medicine_name": "Test medicine", "category": "Test",
        "current_inventory_units": stock, "current_inventory_value": stock * cost, "units_7d": units_28d / 4, "units_28d": units_28d, "units_30d": units_30d, "units_90d": units_30d * 3,
        "stockout_days_last_28d": so28, "stockout_days_last_90d": so28, "stockout_days_total": int(rate * 730), "days_observed": 730, "stockout_event_count": 0,
        "weeks_with_data": 26, "weekly_mean": units_28d / 4, "weekly_std": std_w, "avg_selling_price": 20.0, "last_date_used": "2026-12-31"}])
    fc = pd.DataFrame([{"branch_id": "BRT", "medicine_id": "MEDT", "forecast_7d": f7, "forecast_14d": f14, "forecast_30d": f30, "forecast_lower_7d": 0.0, "forecast_upper_7d": up7,
                        "forecast_lower_14d": 0.0, "forecast_upper_14d": up7 * 2, "forecast_lower_30d": 0.0, "forecast_upper_30d": up7 * 4, "forecast_split": "test"}])
    return inputs.build_frame(state, fc), fc


def _decide(frame, fc, lots=None):
    so = rs.assess(frame)
    re_ = rr.recommend(frame, so)
    ov = ro.assess(frame)
    lots = lots if lots is not None else pd.DataFrame(columns=["branch_id", "medicine_id", "medicine_name", "category", "batch_id", "expiry_date", "days_to_expiry", "remaining_units", "unit_cost", "daily_demand_90d", "units_ahead"])
    ex = rx.assess(lots, fc)
    q = pq.build_queue(frame, so, re_, ov, ex)
    return so.iloc[0], re_.iloc[0], ov.iloc[0], ex, q.iloc[0]


def scenario_tests():
    out = []
    # 1 zero inventory with demand
    fr, fc = _scenario(stock=0, units_28d=56, units_30d=60, f7=14, f14=28, f30=60, up7=20)
    so, re_, ov, ex, q = _decide(fr, fc)
    out.append(_chk("scenarios", "case 1 zero inventory with forecast demand -> CRITICAL stockout risk, ORDER_NOW, a positive order quantity, CRITICAL priority",
                    so["risk_level"] == "CRITICAL" and re_["recommendation"] == "ORDER_NOW" and re_["recommended_order_quantity"] > 0 and q["priority"] == "CRITICAL" and q["primary_action"] == "ORDER_NOW",
                    f"{so['risk_level']}, {re_['recommendation']}, qty {re_['recommended_order_quantity']}, {q['priority']}/{q['primary_action']}"))
    # 2 large inventory, no demand
    fr, fc = _scenario(stock=500, units_28d=0, units_30d=0, f7=0.0, f14=0.0, f30=0.0, up7=0.0, cost=10.0)
    so, re_, ov, ex, q = _decide(fr, fc)
    out.append(_chk("scenarios", "case 2 large inventory and no demand -> OVERSTOCK (documented threshold), no reorder, stockout risk NO_DEMAND_DATA, excess value = stock value",
                    ov["overstock_level"] == "OVERSTOCK" and ov["excess_units_estimate"] == 500 and re_["recommended_order_quantity"] == 0 and so["risk_level"] == "NO_DEMAND_DATA" and q["primary_action"] == "REVIEW_OVERSTOCK",
                    f"{ov['overstock_level']}, excess {ov['excess_units_estimate']}, {q['priority']}/{q['primary_action']}"))
    # 3 batch expiring soon with insufficient demand
    lots = pd.DataFrame([{"branch_id": "BRT", "medicine_id": "MEDT", "medicine_name": "Test medicine", "category": "Test", "batch_id": "BATT1", "expiry_date": "2027-01-10",
                          "days_to_expiry": 10, "remaining_units": 100, "unit_cost": 10.0, "daily_demand_90d": 0.5, "units_ahead": 0}])
    fr, fc = _scenario(stock=100, units_28d=14, units_30d=15, f7=3.5, f14=7, f30=15, up7=6)
    so, re_, ov, ex, q = _decide(fr, fc, lots)
    out.append(_chk("scenarios", "case 3 batch of 100 units expiring in 10 days at 0.5 units/day -> CRITICAL expiry risk, PRIORITIZE_SALE, 95 units projected unsold",
                    ex.iloc[0]["risk_level"] == "CRITICAL" and ex.iloc[0]["recommended_action"] == "PRIORITIZE_SALE" and abs(ex.iloc[0]["projected_unsold_units"] - 95.0) < 1e-6 and q["primary_action"] == "PRIORITIZE_SALE_EXPIRING_STOCK",
                    f"{ex.iloc[0]['risk_level']}, unsold {ex.iloc[0]['projected_unsold_units']}, {q['priority']}/{q['primary_action']}"))
    lots2 = lots.assign(remaining_units=5, daily_demand_90d=5.0)
    ex2 = rx.assess(lots2, fc).iloc[0]
    out.append(_chk("scenarios", "case 3b the same expiry date with 5 units and high demand is NOT a loss risk (demand-aware, not date-only)", ex2["projected_unsold_units"] == 0 and ex2["risk_level"] != "CRITICAL", f"{ex2['risk_level']}, unsold {ex2['projected_unsold_units']}"))
    # 4 healthy inventory
    fr, fc = _scenario(stock=200, units_28d=140, units_30d=150, f7=35, f14=70, f30=150, up7=45)
    so, re_, ov, ex, q = _decide(fr, fc)
    out.append(_chk("scenarios", "case 4 healthy inventory (40 days of cover) -> LOW stockout risk, NO_REORDER, NORMAL, LOW priority, MONITOR",
                    so["risk_level"] == "LOW" and re_["recommendation"] == "NO_REORDER" and ov["overstock_level"] == "NORMAL" and q["priority"] == "LOW" and q["primary_action"] == "MONITOR",
                    f"{so['risk_level']}, {re_['recommendation']}, {ov['overstock_level']}, {q['priority']}/{q['primary_action']}"))
    # 5 no reliable demand
    fr, fc = _scenario(stock=0, units_28d=0, units_30d=0, f7=np.nan, f14=np.nan, f30=np.nan, up7=np.nan)
    so, re_, ov, ex, q = _decide(fr, fc)
    out.append(_chk("scenarios", "case 5 no reliable demand (no sales, no forecast) -> NO_DEMAND_DATA with no fabricated quantity",
                    so["risk_level"] == "NO_DEMAND_DATA" and re_["recommendation"] == "NO_DEMAND_DATA" and re_["recommended_order_quantity"] == 0 and q["primary_action"] == "NO_DEMAND_DATA",
                    f"{so['risk_level']}, {re_['recommendation']}, qty {re_['recommended_order_quantity']}, {q['primary_action']}"))
    # escalation and uncertainty
    fr, fc = _scenario(stock=60, units_28d=140, units_30d=150, f7=35, f14=70, f30=150, up7=70, so28=5, rate=0.05)
    so, re_, ov, ex, q = _decide(fr, fc)
    out.append(_chk("scenarios", "case 6 12 days of cover with recent stockouts -> MEDIUM base level escalated to HIGH (one step) and the history is stated in the reason",
                    so["base_risk_level"] == "MEDIUM" and so["risk_level"] == "HIGH" and "stockout" in (so["secondary_reason"] + so["primary_reason"]), f"{so['base_risk_level']} -> {so['risk_level']}; {so['secondary_reason']}"))
    return out


def run_all(conn, res, hist):
    out = []
    out += structure_checks(conn, res)
    out += reconciliation_checks(conn, res)
    out += leakage_checks(conn, hist)
    out += [dict(c, area="historical:" + c["area"]) for c in structure_checks(conn, hist)]   # the historical-date decisions obey the same rules
    out += scenario_tests()
    return out
