"""Stockout-risk rules (grain: branch x medicine).

days_of_cover = current stock / expected daily demand (NULL when expected demand is zero: that case is NO_DEMAND_DATA, never LOW risk or overstock).
Base level from days of cover:  CRITICAL (stock 0 or under 3 days) / HIGH (under 7) / MEDIUM (under 14) / LOW (14 or more).
HIGH follows the analytics layer's 7-day LOW STOCK line; CRITICAL and MEDIUM add granularity for a prioritised queue.
Escalation (at most ONE step in total, never into CRITICAL): the pair had many recent or frequent stockouts, or its stock would not last a
week even at the upper forecast. CRITICAL is reserved for immediate depletion.
"""
import numpy as np
import pandas as pd

from .. import config as C

LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def assess(df: pd.DataFrame, cfg=C) -> pd.DataFrame:
    L = cfg.STOCKOUT_LEVELS
    esc = cfg.STOCKOUT_ESCALATION
    stock = df["current_inventory_units"].to_numpy(dtype=float)
    d = df["expected_daily_demand"].to_numpy(dtype=float)
    has_demand = d > 0
    cover = np.where(has_demand, stock / np.where(has_demand, d, 1.0), np.nan)
    upper7 = df["forecast_upper_7d"].to_numpy(dtype=float) / 7.0
    cover_upper = np.where(np.isfinite(upper7) & (upper7 > 0), stock / np.where(upper7 > 0, upper7, 1.0), np.nan)

    base = np.full(len(df), "LOW", dtype=object)
    base[has_demand & (cover < L["medium_days"])] = "MEDIUM"
    base[has_demand & (cover < L["high_days"])] = "HIGH"
    base[has_demand & ((cover < L["critical_days"]) | (stock == 0))] = "CRITICAL"
    base[~has_demand] = "NO_DEMAND_DATA"

    hist = (df["stockout_days_last_28d"].to_numpy() >= esc["stockout_days_28d"]) | (df["historical_stockout_rate"].to_numpy() > esc["historical_rate"])
    upper_short = np.isfinite(cover_upper) & (cover_upper < L["high_days"]) & np.isin(base, ["LOW", "MEDIUM"])
    escalate = has_demand & np.isin(base, ["LOW", "MEDIUM"]) & (hist | upper_short)
    level = base.copy()
    for lo, hi in (("LOW", "MEDIUM"), ("MEDIUM", "HIGH")):
        level[escalate & (base == lo)] = hi

    score = np.where(has_demand, 100.0 * (1.0 - np.minimum(np.nan_to_num(cover, nan=0.0), L["medium_days"]) / L["medium_days"]), 0.0)
    score = np.where(has_demand & (stock == 0), 100.0, score)

    primary, secondary = [], []
    for i in range(len(df)):
        r = df.iloc[i]
        if not has_demand[i]:
            primary.append("No observed or forecast demand: stockout risk cannot be assessed")
            secondary.append("")
            continue
        if stock[i] == 0:
            primary.append(f"Out of stock with expected demand of {d[i]:.2f} units/day (7-day forecast {r['forecast_7d']:.1f} units)")
        else:
            primary.append(f"{cover[i]:.1f} days of cover: {stock[i]:.0f} units in stock at expected demand of {d[i]:.2f} units/day")
        sec = []
        if level[i] != base[i]:
            sec.append(f"escalated from {base[i]} because of " + " and ".join(
                x for x, on in ((f"stockout history ({int(r['stockout_days_last_28d'])} days in the last 28; out of stock on {r['historical_stockout_rate']:.1%} of all days observed)", hist[i]),
                                (f"only {cover_upper[i]:.1f} days of cover at the upper forecast", upper_short[i])) if on))
        elif hist[i] and level[i] in ("CRITICAL", "HIGH"):
            sec.append(f"stockout history: {int(r['stockout_days_last_28d'])} days in the last 28, out of stock on {r['historical_stockout_rate']:.1%} of all days observed")
        if np.isfinite(r["forecast_7d"]) and r["forecast_7d"] > stock[i] > 0:
            sec.append(f"7-day forecast ({r['forecast_7d']:.1f}) exceeds current stock ({stock[i]:.0f})")
        if np.isfinite(r["demand_cv_weekly"]) and r["demand_cv_weekly"] >= 1.0:
            sec.append(f"highly variable weekly demand (CV {r['demand_cv_weekly']:.2f})")
        secondary.append("; ".join(sec))

    out = df[["branch_id", "medicine_id", "medicine_name", "category", "current_inventory_units"]].copy()
    out["forecast_7d"] = df["forecast_7d"].round(3)
    out["forecast_14d"] = df["forecast_14d"].round(3)
    out["forecast_30d"] = df["forecast_30d"].round(3)
    out["forecast_upper_7d"] = df["forecast_upper_7d"].round(3)
    out["recent_daily_demand"] = df["recent_daily_demand"].round(4)
    out["expected_daily_demand"] = df["expected_daily_demand"].round(4)
    out["days_of_cover"] = np.round(cover, 2)
    out["days_of_cover_at_upper_forecast"] = np.round(cover_upper, 2)
    out["stockout_days_last_28d"] = df["stockout_days_last_28d"].astype(int)
    out["stockout_days_last_90d"] = df["stockout_days_last_90d"].astype(int)
    out["stockout_event_count"] = df["stockout_event_count"].astype(int)
    out["historical_stockout_rate"] = df["historical_stockout_rate"].round(5)
    out["demand_cv_weekly"] = df["demand_cv_weekly"].round(3)
    out["base_risk_level"] = base
    out["risk_level"] = level
    out["risk_score"] = np.round(score, 1)
    out["primary_reason"] = primary
    out["secondary_reason"] = secondary
    return out
