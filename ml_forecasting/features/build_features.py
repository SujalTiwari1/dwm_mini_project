"""Forecasting dataset and feature engineering.

Definitions (one forecast = one branch x medicine pair at one origin day O):
  * origin O: the end of day O. Everything known through O may be used as a feature.
  * target future_units_{h}d = observed units sold on days O+1 .. O+h  (the sum of the next h days; strictly after O).
  * lag_k = units sold on day O-k+1, so lag_1 is the origin day itself and every lag is strictly before the first predicted day O+1.
  * rolling_*_w summarise days O-w+1 .. O (the first predicted day O+1 is never included).
  * censored target: end-of-day stock was zero on at least one day of O+1..O+h. Observed sales are then a lower bound of demand. Lost sales are never imputed.

All features are computed vectorised on [days x pairs] matrices from ONE SQL result set. No ground truth is read anywhere in this package.
"""
import json

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from analytics.run import split_statements
from etl.load.postgres import get_engine

from .. import config as C

_STATEMENTS = None


def _statements():
    global _STATEMENTS
    if _STATEMENTS is None:
        _STATEMENTS = dict(split_statements((C.SQL_DIR / "forecasting_data.sql").read_text(encoding="utf-8")))
    return _STATEMENTS


def run_query(conn, name, params=None) -> pd.DataFrame:
    res = conn.exec_driver_sql(_statements()[name], params) if params else conn.exec_driver_sql(_statements()[name])
    return pd.DataFrame(res.fetchall(), columns=list(res.keys()))


def open_connection():
    engine = get_engine()
    conn = engine.connect()
    conn.exec_driver_sql("SET work_mem = '128MB'")
    return engine, conn


def dataset_reference() -> dict:
    meta = json.loads(C.GENERATION_METADATA.read_text(encoding="utf-8"))
    return {k: meta.get(k) for k in ("generator_version", "frozen_on", "random_seed", "date_range", "demand_scale")}


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def load_data(conn):
    dates = run_query(conn, "dates")
    meds = run_query(conn, "medicines")
    branches = run_query(conn, "branches")
    daily = run_query(conn, "daily_series")
    T, B, M = len(dates), len(branches), len(meds)
    if len(daily) != T * B * M:
        raise ValueError(f"daily series is not dense: {len(daily)} rows vs {T * B * M}")
    N = B * M
    units = daily["units"].to_numpy(dtype=np.int64).reshape(T, N)         # rows are ordered by date, branch, medicine
    revenue = daily["revenue"].to_numpy(dtype=np.float64).reshape(T, N)
    inventory = daily["inventory_units"].to_numpy(dtype=np.int64).reshape(T, N)
    seg = run_query(conn, "pair_segments")
    seg_idx = {(b, m): i for i, (b, m) in enumerate(zip(seg["branch_key"], seg["medicine_key"]))}
    order = [seg_idx[(b, m)] for b in branches["branch_key"] for m in meds["medicine_key"]]
    seg = seg.iloc[order].reset_index(drop=True)
    pairs = pd.DataFrame({
        "pair": np.arange(N),
        "branch_id": np.repeat(branches["branch_id"].to_numpy(), M), "medicine_id": np.tile(meds["medicine_id"].to_numpy(), B),
        "medicine_name": np.tile(meds["medicine_name"].to_numpy(), B), "category": np.tile(meds["category"].to_numpy(), B),
        "branch_idx": np.repeat(np.arange(B), M), "category_idx": pd.factorize(np.tile(meds["category"].to_numpy(), B), sort=True)[0],
        "mover_class": seg["mover_class"].to_numpy(), "stockout_rate_pct": seg["stockout_rate_pct"].astype(float).to_numpy(),
        "variability_class": seg["variability_class"].to_numpy(),
    })
    return {"dates": pd.to_datetime(dates["full_date"]).reset_index(drop=True), "units": units, "revenue": revenue, "inventory": inventory, "pairs": pairs,
            "branches": branches, "meds": meds}


# ---------------------------------------------------------------------------
# causal feature cube
# ---------------------------------------------------------------------------
def _shift(a, k):
    """out[t] = a[t-k] (NaN for t < k)."""
    out = np.full(a.shape, np.nan, dtype=np.float32)
    if k == 0:
        out[:] = a
    else:
        out[k:] = a[:-k]
    return out


def _rolling_mean_std(U, w):
    """Mean and sample std over days t-w+1..t (NaN for t < w-1)."""
    z = np.zeros((1, U.shape[1]))
    cs, cs2 = np.cumsum(np.vstack([z, U]), axis=0), np.cumsum(np.vstack([z, U.astype(np.float64) ** 2]), axis=0)
    mean = np.full(U.shape, np.nan)
    std = np.full(U.shape, np.nan)
    s, s2 = cs[w:] - cs[:-w], cs2[w:] - cs2[:-w]
    mean[w - 1:] = s / w
    std[w - 1:] = np.sqrt(np.maximum((s2 - s * s / w) / (w - 1), 0.0))
    return mean.astype(np.float32), std.astype(np.float32)


def _rolling_median(U, w, chunk=250):
    out = np.full(U.shape, np.nan, dtype=np.float32)
    for c0 in range(0, U.shape[1], chunk):
        win = sliding_window_view(U[:, c0:c0 + chunk].astype(np.float32), w, axis=0)
        out[w - 1:, c0:c0 + chunk] = np.median(win, axis=-1)
    return out


def _rolling_sum(a, w):
    cs = np.cumsum(np.vstack([np.zeros((1, a.shape[1])), a.astype(np.float64)]), axis=0)
    out = np.full(a.shape, np.nan)
    out[w - 1:] = cs[w:] - cs[:-w]
    return out.astype(np.float32)


def feature_names():
    names = [f"lag_{k}" for k in C.LAGS]
    names += [f"rolling_mean_{w}" for w in C.ROLLING_WINDOWS] + [f"rolling_std_{w}" for w in C.ROLLING_WINDOWS]
    names += [f"rolling_median_{w}" for w in C.ROLLING_MEDIAN_WINDOWS]
    names += ["units_ratio_7_28", "rolling_mean_28_instock"]
    names += ["inventory_units", "was_stockout", "stockout_last_7d", "stockout_days_last_7d", "stockout_days_last_28d", "days_since_stockout", "inventory_to_demand_28"]
    names += ["day_of_week", "day_of_month", "month", "quarter", "week_of_year", "is_weekend", "sin_day_of_week", "cos_day_of_week", "sin_month", "cos_month"]
    names += ["branch_idx", "category_idx"]
    return names


CATEGORICAL = ["branch_idx", "category_idx"]
CALENDAR = ["day_of_week", "day_of_month", "month", "quarter", "week_of_year", "is_weekend", "sin_day_of_week", "cos_day_of_week", "sin_month", "cos_month"]
STATIC = ["branch_idx", "category_idx"]


def build_cube(units, inventory, dates, pairs):
    """Feature cube from [T, N] units / inventory. Every value at row t depends only on data up to and including day t."""
    T, N = units.shape
    U = units.astype(np.float32)
    stock0 = (inventory == 0)
    cube = {}
    for k in C.LAGS:
        cube[f"lag_{k}"] = _shift(U, k - 1)
    means = {}
    for w in C.ROLLING_WINDOWS:
        means[w], std = _rolling_mean_std(units.astype(np.float64), w)
        cube[f"rolling_mean_{w}"], cube[f"rolling_std_{w}"] = means[w], std
    for w in C.ROLLING_MEDIAN_WINDOWS:
        cube[f"rolling_median_{w}"] = _rolling_median(U, w)
    cube["units_ratio_7_28"] = means[7] / (means[28] + 0.1)
    # mean daily units over IN-STOCK days of the last 28 days (a censoring-aware level); falls back to the plain mean if never in stock
    in_stock = (~stock0).astype(np.float64)
    s_units = _rolling_sum(units * in_stock, 28)
    s_days = _rolling_sum(in_stock, 28)
    cube["rolling_mean_28_instock"] = np.where(s_days > 0, s_units / np.maximum(s_days, 1), means[28]).astype(np.float32)
    sk = stock0.astype(np.float64)
    cube["inventory_units"] = inventory.astype(np.float32)
    cube["was_stockout"] = stock0.astype(np.float32)
    cube["stockout_days_last_7d"] = _rolling_sum(sk, 7)
    cube["stockout_days_last_28d"] = _rolling_sum(sk, 28)
    cube["stockout_last_7d"] = (cube["stockout_days_last_7d"] > 0).astype(np.float32)
    last = np.full(N, -1.0)
    since = np.zeros((T, N), dtype=np.float32)
    for t in range(T):
        last = np.where(stock0[t], t, last)
        since[t] = np.where(last >= 0, np.minimum(t - last, C.DAYS_SINCE_STOCKOUT_CAP), C.DAYS_SINCE_STOCKOUT_CAP + 1)
    cube["days_since_stockout"] = since
    cube["inventory_to_demand_28"] = (inventory / (means[28] + 0.1)).astype(np.float32)
    # calendar of the FIRST PREDICTED DAY (origin + 1): known in advance, not leakage
    first = pd.DatetimeIndex(dates) + pd.Timedelta(days=1)
    dow = first.dayofweek.to_numpy()
    cal = {"day_of_week": dow, "day_of_month": first.day.to_numpy(), "month": first.month.to_numpy(), "quarter": first.quarter.to_numpy(),
           "week_of_year": first.isocalendar().week.to_numpy().astype(int), "is_weekend": (dow >= 5).astype(int),
           "sin_day_of_week": np.sin(2 * np.pi * dow / 7), "cos_day_of_week": np.cos(2 * np.pi * dow / 7),
           "sin_month": np.sin(2 * np.pi * (first.month.to_numpy() - 1) / 12), "cos_month": np.cos(2 * np.pi * (first.month.to_numpy() - 1) / 12)}
    static = {"branch_idx": pairs["branch_idx"].to_numpy(), "category_idx": pairs["category_idx"].to_numpy()}
    return {"matrix": cube, "calendar": cal, "static": static, "names": feature_names(), "N": N, "T": T}


def assemble(cube, origins, pair_mask=None):
    """Feature matrix X [len(origins) * n_pairs, F] (origin-major, then pair) and the (origin, pair) index arrays."""
    N = cube["N"]
    pairs = np.arange(N) if pair_mask is None else np.flatnonzero(pair_mask)
    origins = np.asarray(origins)
    X = np.empty((len(origins) * len(pairs), len(cube["names"])), dtype=np.float32)
    for j, name in enumerate(cube["names"]):
        if name in cube["matrix"]:
            X[:, j] = cube["matrix"][name][np.ix_(origins, pairs)].reshape(-1)
        elif name in cube["calendar"]:
            X[:, j] = np.repeat(np.asarray(cube["calendar"][name], dtype=np.float32)[origins], len(pairs))
        else:
            X[:, j] = np.tile(np.asarray(cube["static"][name], dtype=np.float32)[pairs], len(origins))
    return X, np.repeat(origins, len(pairs)), np.tile(pairs, len(origins))


# ---------------------------------------------------------------------------
# targets, censoring and splits
# ---------------------------------------------------------------------------
def targets(units, inventory, h):
    """future_units_{h}d[t] = units on days t+1..t+h and target_stockout_days[t] = days among them with zero end-of-day stock. NaN where the window is not fully observed."""
    T = units.shape[0]
    cs = np.cumsum(units, axis=0).astype(np.float64)
    ck = np.cumsum((inventory == 0), axis=0).astype(np.float64)
    y = np.full(units.shape, np.nan)
    sk = np.full(units.shape, np.nan)
    y[:T - h] = cs[h:] - cs[:T - h]
    sk[:T - h] = ck[h:] - ck[:T - h]
    return y, sk


def split_origins(dates, h):
    """Origins whose WHOLE target window (origin+1 .. origin+h) lies inside one split period, so no target period is shared between splits."""
    idx = {d: i for i, d in enumerate(pd.DatetimeIndex(dates).strftime("%Y-%m-%d"))}
    out = {}
    for name, (a, b) in C.SPLITS.items():
        ia, ib = idx[a], idx[b]
        lo = max(ia - 1, C.MIN_HISTORY_DAYS)          # origin ia-1 predicts days ia .. ia+h-1
        out[name] = np.arange(lo, ib - h + 1)
    return out


def pair_eligibility(units, inventory, dates):
    """Eligible pairs and the reason for every exclusion (training-period information only)."""
    idx = {d: i for i, d in enumerate(pd.DatetimeIndex(dates).strftime("%Y-%m-%d"))}
    ib = idx[C.SPLITS["train"][1]]
    tr_units = units[:ib + 1].sum(axis=0)
    tr_censored = (inventory[:ib + 1] == 0).mean(axis=0)
    reason = np.full(units.shape[1], "", dtype=object)
    reason[tr_units < C.MIN_TRAIN_UNITS_FOR_ELIGIBILITY] = "no observed demand in the training period"
    reason[(tr_censored > C.MAX_CENSORED_SHARE) & (reason == "")] = "excessive censoring (more than half of training days in stockout)"
    return reason == "", reason
