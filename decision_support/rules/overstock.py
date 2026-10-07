"""Overstock rules (grain: branch x medicine). The classification is the analytics layer's definition, unchanged:

    OVERSTOCK = stock > 0 and (no units sold in the last 30 days, or days of inventory over 90)
                with days of inventory = stock / (units sold in the last 30 days / 30)

The binary classification is kept: no data-driven threshold justifies a SEVERE level. A low-demand medicine is not bad inventory by itself:
it is flagged only when its stock is large relative to its own demand.

Boundary note: the analytics view evaluates the same rule in decimal arithmetic where 4 / 30 is rounded up slightly, so a pair with exactly 90.0 days of
cover is labelled OVERSTOCK there. Here the rule is exact (90.0 days is not over 90); the reconciliation check lists those boundary pairs.

Excess estimate: units above 90 days of cover, where the demand used is the larger of the recent 30-day rate and the 30-day forecast rate, so
stock that forecast demand will absorb is not called excess. Excess value uses the average unit cost of the stock on hand. These are
estimates of potential exposure, not actual losses.
"""
import numpy as np
import pandas as pd

from .. import config as C


def assess(df: pd.DataFrame, cfg=C) -> pd.DataFrame:
    O = cfg.OVERSTOCK
    stock = df["current_inventory_units"].to_numpy(dtype=float)
    u30 = df["units_30d"].to_numpy(dtype=float)
    d30 = u30 / O["window_days"]
    cover = np.where(d30 > 0, stock / np.where(d30 > 0, d30, 1.0), np.nan)       # for display; the classification below uses exact integer arithmetic
    f30 = df["forecast_30d"].to_numpy(dtype=float)
    f_rate = np.where(np.isfinite(f30), f30 / 30.0, 0.0)
    cover_f = np.where(f_rate > 0, stock / np.where(f_rate > 0, f_rate, 1.0), np.nan)
    # "cover > 90 days" written without division: stock / (u30 / 30) > 90  <=>  stock * 30 > 90 * u30. Exactly 90.0 days is NOT over the limit.
    over = (stock > 0) & ((u30 == 0) | (stock * O["window_days"] > O["max_cover_days"] * u30))
    ref_rate = np.maximum(d30, f_rate)
    excess_units = np.where(over, np.maximum(0.0, stock - O["max_cover_days"] * ref_rate), 0.0)
    excess_units = np.ceil(excess_units - 1e-9)
    unit_cost = df["unit_cost"].to_numpy(dtype=float)
    excess_value = np.where(over, excess_units * np.nan_to_num(unit_cost, nan=0.0), 0.0)

    reason = []
    for i in range(len(df)):
        if not over[i]:
            reason.append("Stock is within " + f"{O['max_cover_days']} days of recent demand" if stock[i] > 0 else "No stock on hand")
        elif u30[i] == 0:
            absorbed = "" if excess_units[i] > 0 else "; forecast demand would absorb the stock"
            reason.append(f"{stock[i]:.0f} units in stock and no units sold in the last {O['window_days']} days{absorbed}")
        else:
            reason.append(f"{cover[i]:.0f} days of cover at the recent {d30[i]:.2f} units/day (limit {O['max_cover_days']}): about {excess_units[i]:.0f} units above the limit")

    out = df[["branch_id", "medicine_id", "medicine_name", "category", "current_inventory_units", "current_inventory_value"]].copy()
    out["expected_daily_demand"] = df["expected_daily_demand"].round(4)
    out["days_of_cover"] = np.round(cover, 1)
    out["forecast_30d"] = df["forecast_30d"].round(3)
    out["forecast_cover_days"] = np.round(cover_f, 1)
    out["recent_30d_units"] = df["units_30d"].astype(int)
    out["overstock_level"] = np.where(over, "OVERSTOCK", "NORMAL")
    out["excess_units_estimate"] = excess_units.astype(int)
    out["excess_value_estimate"] = np.round(excess_value, 2)
    out["reason"] = reason
    return out
