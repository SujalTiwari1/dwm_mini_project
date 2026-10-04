"""Anomaly detection on warehouse-observable operational data.

Two independent method families, run at several grains:
  * robust statistics: median / MAD modified z-scores (plus a stockout-run rule and prior-history purchase checks)
  * Isolation Forest on engineered features

NO LEAKAGE. Every rolling quantity for day D uses observations up to and including D only (baselines are medians/MADs of values that end
before D). `sales_features()` is a pure causal function: validation recomputes it on data truncated at D and requires identical values.
This module never reads data/metadata/ground_truth_private.json.

A flag means "the detector marks this observation as unusual under the specified method". It is not proof that anything is wrong.
"""
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.ensemble import IsolationForest

from .. import config as C

A = C.ANOMALY
EPS = 1e-9


# ---------------------------------------------------------------------------
# causal rolling helpers (rows = days, columns = series)
# ---------------------------------------------------------------------------
def rolling_sum(a, w):
    out = np.full(a.shape, np.nan)
    cs = np.cumsum(np.vstack([np.zeros((1, a.shape[1])), a]), axis=0)
    out[w - 1:] = cs[w:] - cs[:-w]
    return out


def rolling_median_mad(a, window, chunk=250):
    """Median and MAD over rows t-window+1..t (NaN where the window is incomplete or contains NaN)."""
    T, N = a.shape
    med = np.full((T, N), np.nan)
    mad = np.full((T, N), np.nan)
    for c0 in range(0, N, chunk):
        blk = a[:, c0:c0 + chunk]
        win = sliding_window_view(blk, window, axis=0)                  # (T-window+1, n, window)
        m = np.median(win, axis=-1)
        d = np.median(np.abs(win - m[..., None]), axis=-1)
        med[window - 1:, c0:c0 + chunk] = m
        mad[window - 1:, c0:c0 + chunk] = d
    return med, mad


def shift_down(a, k):
    out = np.full(a.shape, np.nan)
    out[k:] = a[:-k]
    return out


def sales_features(units, inventory):
    """Causal feature set for a [T, N] units matrix and its [T, N] closing inventory. Pure function of the data up to each day."""
    w, L = A["short_window"], A["baseline_window"]
    sigma, min_scale = A["mad_to_sigma"], A["min_scale"]
    S = rolling_sum(units, w)                                            # units in the 7 days ending at t (includes t)
    # Variance-stabilising transform for counts: y = sqrt(x + 3/8) has roughly constant spread (sd about 0.5 for Poisson counts),
    # so a robust z-score on y is comparable between slow and fast medicines. Medians commute with the monotone transform.
    Ys = np.sqrt(S + 0.375)
    med_Y, mad_Y = rolling_median_mad(Ys, L)
    base_med_Y, base_mad_Y = shift_down(med_Y, w), shift_down(mad_Y, w)  # baseline = prior 7-day levels that end before the current window
    base_med = base_med_Y ** 2 - 0.375                                   # back to units (7-day sum)
    scale7 = np.maximum(sigma * base_mad_Y, min_scale)
    z7 = (Ys - base_med_Y) / scale7

    Yd = np.sqrt(units + 0.375)
    dmed_Y, dmad_Y = rolling_median_mad(Yd, 28)
    dmed_Y, dmad_Y = shift_down(dmed_Y, 1), shift_down(dmad_Y, 1)        # prior 28 days only
    dmed = dmed_Y ** 2 - 0.375
    dmean = shift_down(rolling_sum(units, 28) / 28.0, 1)
    zd = (Yd - dmed_Y) / np.maximum(sigma * dmad_Y, min_scale)

    inv_mean = shift_down(rolling_sum(inventory, 28) / 28.0, 1)
    run = np.zeros_like(units)
    cur = np.zeros(units.shape[1])
    for t in range(units.shape[0]):
        cur = np.where(inventory[t] == 0, cur + 1, 0)
        run[t] = cur
    return {
        "units": units, "units_7d": S, "baseline_median_7d": base_med, "z7": z7, "zd": zd,
        "units_vs_rolling_median": (units + 1) / (dmed + 1), "units_vs_rolling_mean": (units + 1) / (dmean + 1),
        "rolling_28d_units": dmean * 28, "inventory": inventory, "inventory_vs_prior_mean": (inventory + 1) / (inv_mean + 1),
        "stockout": (inventory == 0).astype(float), "stockout_run_days": run, "dmed": dmed,
        "stockout_days_7d": np.nan_to_num(rolling_sum((inventory == 0).astype(float), w), nan=0.0),
    }


def statistical_flags(f):
    """Boolean [T, N] arrays for the statistical rules."""
    T = f["units"].shape[0]
    valid = np.zeros(f["units"].shape, dtype=bool)
    valid[A["burn_in_days"]:] = True
    valid &= np.isfinite(f["z7"]) & np.isfinite(f["zd"])
    big = A["min_abs_units_7d_for_demand_flag"]
    d7 = f["units_7d"] - f["baseline_median_7d"]
    spike = valid & (((f["z7"] >= A["robust_z_threshold"]) & (d7 >= big)) | ((f["zd"] >= A["daily_z_threshold"]) & (f["units"] - f["dmed"] >= big)))
    # observed demand is censored while stock is zero, so a "drop" is only declared for windows with stock on every day
    drop = valid & (f["z7"] <= -A["robust_z_threshold"]) & (-d7 >= big) & (f["stockout_days_7d"] == 0)
    stockout = valid & (f["stockout_run_days"] == A["stockout_run_days"])        # onset of a long stockout
    return {"spike": spike, "drop": drop, "stockout_pattern": stockout, "valid": valid}


def isolation_matrix(f, mask):
    clip = lambda x: np.clip(x, -15, 15)
    cols = [
        clip(f["z7"]), clip(f["zd"]), np.log((f["units_7d"] + 1) / (f["baseline_median_7d"] + 1)), np.log(f["units_vs_rolling_median"]),
        np.log(f["units_vs_rolling_mean"]), np.log1p(f["units_7d"]), np.log1p(f["rolling_28d_units"]), np.log1p(f["inventory"]),
        np.log(f["inventory_vs_prior_mean"]), f["stockout"], np.minimum(f["stockout_run_days"], 30.0),
    ]
    return np.column_stack([c[mask] for c in cols]).astype(np.float32)


def run_isolation(X, contamination):
    """Isolation Forest scores. isolation_score = -score_samples (higher = more isolated). Flag = the top `contamination` share."""
    clf = IsolationForest(n_estimators=A["isolation_estimators"], max_samples=min(A["isolation_max_samples"], len(X)), contamination="auto",
                          random_state=C.RANDOM_STATE, n_jobs=-1).fit(X)
    score = -clf.score_samples(X)
    thr = np.quantile(score, 1 - contamination)
    return score, score >= thr, float(thr)


def sales_type(z7, units_7d, base_med, stockout_run, stockout_days_7d):
    """Anomaly type supported by the observable features (half of the detection threshold is enough to name the type)."""
    half, big = A["robust_z_threshold"] / 2, A["min_abs_units_7d_for_demand_flag"]
    t = np.full(len(z7), "unclassified", dtype=object)
    t[(z7 <= -half) & (base_med - units_7d >= big) & (stockout_days_7d == 0)] = "demand_drop"
    t[(z7 >= half) & (units_7d - base_med >= big)] = "demand_spike"
    t[stockout_run >= A["stockout_run_days"]] = "stockout_pattern"
    return t


# ---------------------------------------------------------------------------
# sales / inventory detection at one grain
# ---------------------------------------------------------------------------
def detect_grain(grain, units, revenue, inventory, dates, branch_ids, med_ids, med_names, categories):
    """units/revenue/inventory: [T, N]. branch_ids/med_ids/med_names/categories: length-N lists (branch_id 'ALL' for the medicine grain)."""
    f = sales_features(units, inventory)
    st = statistical_flags(f)
    is_stat = st["spike"] | st["drop"] | st["stockout_pattern"]
    mask = st["valid"]
    X = isolation_matrix(f, mask)
    score, flag, thr = run_isolation(X, A["isolation_contamination"])
    iso_score = np.full(units.shape, np.nan)
    iso_flag = np.zeros(units.shape, dtype=bool)
    iso_score[mask] = score
    iso_flag[mask] = flag
    keep = is_stat | iso_flag
    t_idx, n_idx = np.nonzero(keep)
    z7 = f["z7"][t_idx, n_idx]
    rows = pd.DataFrame({
        "date": dates[t_idx], "branch_id": np.array(branch_ids, dtype=object)[n_idx], "medicine_id": np.array(med_ids, dtype=object)[n_idx],
        "medicine_name": np.array(med_names, dtype=object)[n_idx], "category": np.array(categories, dtype=object)[n_idx], "grain": grain,
        "units_sold": units[t_idx, n_idx], "units_7d": f["units_7d"][t_idx, n_idx], "revenue": np.round(revenue[t_idx, n_idx], 2),
        "inventory_units": inventory[t_idx, n_idx], "stockout_indicator": f["stockout"][t_idx, n_idx].astype(int),
        "stockout_run_days": f["stockout_run_days"][t_idx, n_idx].astype(int),
        "robust_z_score": np.round(z7, 3), "robust_z_daily": np.round(f["zd"][t_idx, n_idx], 3),
        "is_statistical_anomaly": is_stat[t_idx, n_idx], "isolation_score": np.round(iso_score[t_idx, n_idx], 5),
        "is_isolation_anomaly": iso_flag[t_idx, n_idx],
    })
    rows["anomaly_type"] = sales_type(z7, f["units_7d"][t_idx, n_idx], f["baseline_median_7d"][t_idx, n_idx], f["stockout_run_days"][t_idx, n_idx],
                              f["stockout_days_7d"][t_idx, n_idx])
    for col in ("purchase_quantity", "purchase_unit_cost", "purchase_gap_days"):
        rows[col] = np.nan
    info = {"grain": grain, "series": int(units.shape[1]), "scored_rows": int(mask.sum()), "isolation_threshold": round(thr, 5),
            "statistical_rows": int(is_stat.sum()), "isolation_rows": int(iso_flag.sum()),
            "statistical_by_rule": {k: int(st[k].sum()) for k in ("spike", "drop", "stockout_pattern")}}
    return rows, info


# ---------------------------------------------------------------------------
# purchase lots (grain: one received batch lot)
# ---------------------------------------------------------------------------
def purchase_features(lots, date_index):
    """Per-lot features against the medicine's PRIOR lots only (expanding history)."""
    sigma = A["mad_to_sigma"]
    recs = []
    for med_key, g in lots.sort_values(["date_key", "batch_key"]).groupby("medicine_key", sort=True):
        d = g["date_key"].map(date_index).to_numpy(dtype=float)
        q = (g["lot_quantity"] / g["branches_delivered"]).to_numpy(dtype=float)       # units per delivered branch
        c = g["unit_cost"].to_numpy(dtype=float)
        gaps = np.concatenate([[np.nan], np.diff(d)])
        for i in range(len(g)):
            rec = {"batch_key": g["batch_key"].iloc[i], "medicine_key": med_key, "date_idx": d[i], "branches_delivered": g["branches_delivered"].iloc[i],
                   "purchase_quantity": g["lot_quantity"].iloc[i], "purchase_unit_cost": c[i], "purchase_gap_days": gaps[i], "qty_z": np.nan, "qty_ratio": np.nan,
                   "gap_z": np.nan, "gap_ratio": np.nan, "cost_z": np.nan, "cost_rel_dev": np.nan}
            if i >= A["purchase_baseline_lots"]:
                pq, pg, pc = q[:i], gaps[1:i], c[:i]               # gaps of lots 1..i-1 (the gap into lot i is the thing being judged)
                mq, mg, mc = np.median(pq), np.median(pg), np.median(pc)
                rec["qty_z"] = (q[i] - mq) / max(sigma * np.median(np.abs(pq - mq)), 1.0, 0.25 * mq)
                rec["qty_ratio"] = q[i] / max(mq, 1.0)
                rec["gap_z"] = (gaps[i] - mg) / max(sigma * np.median(np.abs(pg - mg)), 1.0)
                rec["gap_ratio"] = gaps[i] / max(mg, 1.0)
                rec["cost_z"] = (c[i] - mc) / max(sigma * np.median(np.abs(pc - mc)), 0.01 * mc, 1e-6)
                rec["cost_rel_dev"] = c[i] / mc - 1
            recs.append(rec)
    return pd.DataFrame(recs)


def detect_purchases(lots, dates, meds):
    pf = purchase_features(lots, {k: i for i, k in enumerate(dates["date_key"])})
    ok = pf["qty_z"].notna()
    big_lot = ok & (pf["qty_z"] >= A["purchase_qty_z_threshold"]) & (pf["qty_ratio"] >= A["purchase_qty_min_ratio"])
    delay = ok & (pf["gap_z"] >= A["purchase_gap_z_threshold"]) & (pf["gap_ratio"] >= A["purchase_gap_min_ratio"])
    price = ok & (pf["cost_z"].abs() >= A["purchase_cost_z_threshold"]) & (pf["cost_rel_dev"].abs() >= A["purchase_cost_min_rel_dev"])
    is_stat = big_lot | delay | price
    X = np.column_stack([
        np.clip(pf["qty_z"], -15, 15), np.log(pf["qty_ratio"].clip(lower=1e-3)), np.clip(pf["gap_z"], -15, 15),
        np.log(pf["gap_ratio"].clip(lower=1e-3)), np.clip(pf["cost_z"], -15, 15), pf["cost_rel_dev"], np.log1p(pf["purchase_quantity"]),
        pf["branches_delivered"],
    ])[ok.to_numpy()].astype(np.float32)
    contamination = A["purchase_isolation_contamination"]
    clf = IsolationForest(n_estimators=A["isolation_estimators"], max_samples=min(A["isolation_max_samples"], len(X)), contamination="auto",
                          random_state=C.RANDOM_STATE, n_jobs=-1).fit(X)
    score = -clf.score_samples(X)
    thr = np.quantile(score, 1 - contamination)
    pf["isolation_score"] = np.nan
    pf.loc[ok, "isolation_score"] = score
    pf["is_isolation_anomaly"] = False
    pf.loc[ok, "is_isolation_anomaly"] = score >= thr
    pf["is_statistical_anomaly"] = is_stat
    # type supported by the features (half threshold names the type)
    half = A["purchase_qty_z_threshold"] / 2
    t = np.full(len(pf), "unclassified", dtype=object)
    t[(pf["cost_rel_dev"].abs() >= A["purchase_cost_min_rel_dev"]).to_numpy()] = "purchase_price_anomaly"
    t[((pf["gap_z"] >= half) & (pf["gap_ratio"] >= A["purchase_gap_min_ratio"])).to_numpy()] = "supply_delay"
    t[((pf["qty_z"] >= half) & (pf["qty_ratio"] >= A["purchase_qty_min_ratio"] / 1.25)).to_numpy()] = "inventory_anomaly"
    pf["anomaly_type"] = t
    keep = pf[pf["is_statistical_anomaly"] | pf["is_isolation_anomaly"]].copy()
    med_idx = meds.set_index("medicine_key")
    inv_note = np.nan
    rows = pd.DataFrame({
        "date": dates["full_date"].iloc[keep["date_idx"].astype(int)].to_numpy(), "branch_id": "ALL",
        "medicine_id": med_idx.loc[keep["medicine_key"], "medicine_id"].to_numpy(),
        "medicine_name": med_idx.loc[keep["medicine_key"], "medicine_name"].to_numpy(),
        "category": med_idx.loc[keep["medicine_key"], "category"].to_numpy(), "grain": "purchase_lot",
        "units_sold": np.nan, "units_7d": np.nan, "revenue": np.nan, "inventory_units": inv_note, "stockout_indicator": np.nan,
        "stockout_run_days": np.nan, "robust_z_score": keep["qty_z"].round(3).to_numpy(), "robust_z_daily": np.nan,
        "is_statistical_anomaly": keep["is_statistical_anomaly"].to_numpy(), "isolation_score": keep["isolation_score"].round(5).to_numpy(),
        "is_isolation_anomaly": keep["is_isolation_anomaly"].to_numpy(), "anomaly_type": keep["anomaly_type"].to_numpy(),
        "purchase_quantity": keep["purchase_quantity"].to_numpy(), "purchase_unit_cost": keep["purchase_unit_cost"].round(2).to_numpy(),
        "purchase_gap_days": keep["purchase_gap_days"].to_numpy(),
    })
    info = {"grain": "purchase_lot", "lots": int(len(pf)), "scored_lots": int(ok.sum()), "isolation_threshold": round(float(thr), 5),
            "statistical_rows": int(is_stat.sum()), "isolation_rows": int(pf["is_isolation_anomaly"].sum()),
            "statistical_by_rule": {"large_lot": int(big_lot.sum()), "long_receipt_gap": int(delay.sum()), "unit_cost_deviation": int(price.sum())}}
    return rows, info, pf


# ---------------------------------------------------------------------------
# orchestration and episodes
# ---------------------------------------------------------------------------
def build_episodes(df, gap_days=None):
    """Group flagged rows of one series (grain, branch, medicine, type) into episodes: flags within `gap_days` of each other join."""
    gap_days = A["episode_gap_days"] if gap_days is None else gap_days
    if df.empty:
        return pd.DataFrame(columns=["episode_id", "grain", "branch_id", "medicine_id", "anomaly_type", "start", "end", "n_flags"])
    d = df.sort_values(["grain", "branch_id", "medicine_id", "anomaly_type", "date"]).copy()
    d["date"] = pd.to_datetime(d["date"])
    key = ["grain", "branch_id", "medicine_id", "anomaly_type"]
    new = (d.groupby(key)["date"].diff().dt.days.fillna(10 ** 6) > gap_days)
    d["ep"] = new.cumsum()
    ep = d.groupby("ep").agg(grain=("grain", "first"), branch_id=("branch_id", "first"), medicine_id=("medicine_id", "first"),
                             anomaly_type=("anomaly_type", "first"), start=("date", "min"), end=("date", "max"), n_flags=("date", "size")).reset_index(drop=True)
    ep.insert(0, "episode_id", range(1, len(ep) + 1))
    return ep


def detect_all(cube, lots):
    """Run every detector. Returns (anomalies DataFrame, info dict, purchase feature frame)."""
    dates = pd.to_datetime(cube["dates"]["full_date"]).to_numpy()
    meds, branches = cube["meds"], cube["branches"]
    T, B, M = cube["units"].shape
    infos, parts = [], []

    # grain 1: date x branch x medicine
    rows, info = detect_grain(
        "branch_medicine", cube["units"].reshape(T, B * M), cube["revenue"].reshape(T, B * M), cube["inventory"].reshape(T, B * M), dates,
        [b for b in branches["branch_id"] for _ in range(M)], list(meds["medicine_id"]) * B, list(meds["medicine_name"]) * B, list(meds["category"]) * B)
    parts.append(rows); infos.append(info)

    # grain 2: date x medicine (all branches)
    rows, info = detect_grain(
        "medicine", cube["units"].sum(axis=1), cube["revenue"].sum(axis=1), cube["inventory"].sum(axis=1), dates, ["ALL"] * M,
        list(meds["medicine_id"]), list(meds["medicine_name"]), list(meds["category"]))
    parts.append(rows); infos.append(info)

    # grain 3: purchase lots
    prow, pinfo, pf = detect_purchases(lots, cube["dates"], meds)
    parts.append(prow); infos.append(pinfo)

    out = pd.concat(parts, ignore_index=True)
    out["combined_anomaly"] = out["is_statistical_anomaly"] & out["is_isolation_anomaly"]      # flagged by BOTH methods
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out = out.sort_values(["date", "grain", "medicine_id", "branch_id"], kind="mergesort").reset_index(drop=True)
    cols = ["date", "branch_id", "medicine_id", "medicine_name", "category", "grain", "anomaly_type", "units_sold", "units_7d", "revenue", "inventory_units",
            "stockout_indicator", "stockout_run_days", "robust_z_score", "robust_z_daily", "is_statistical_anomaly", "isolation_score",
            "is_isolation_anomaly", "combined_anomaly", "purchase_quantity", "purchase_unit_cost", "purchase_gap_days"]
    return out[cols], infos, pf
