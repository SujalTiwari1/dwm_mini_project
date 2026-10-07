"""Reorder rules (grain: branch x medicine).

    expected_lead_time_demand = expected_daily_demand x planning_lead_time_days
    safety_stock              = z x daily_demand_std x sqrt(planning_lead_time_days)        (daily std = weekly std / sqrt(7))
    reorder_point             = expected_lead_time_demand + safety_stock
    order_up_to_level         = reorder_point + expected_daily_demand x order_cover_days     (no double counting: the lead-time demand is inside the reorder point)
    recommended_order_quantity= ceil(max(0, order_up_to_level - current_inventory))          (open orders are assumed to be zero)

    ORDER_NOW      stock <= expected lead-time demand (a stockout is expected before a new order could arrive; includes stock = 0)
    REORDER_SOON   expected lead-time demand < stock < reorder point (inside the safety-stock band)
    NO_REORDER     stock >= reorder point
    NO_DEMAND_DATA no observed or forecast demand: no quantity is invented

Lead time, service level, order cover and the absence of minimum order quantities are planning assumptions (see config.py), not learned from the data.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

from .. import config as C


def recommend(df: pd.DataFrame, stockout: pd.DataFrame, cfg=C) -> pd.DataFrame:
    L = cfg.PLANNING_LEAD_TIME_DAYS
    z = float(norm.ppf(cfg.SERVICE_LEVEL))
    stock = df["current_inventory_units"].to_numpy(dtype=float)
    d = df["expected_daily_demand"].to_numpy(dtype=float)
    has_demand = d > 0
    sigma = df["demand_std_daily"].to_numpy(dtype=float)
    fallback = ~np.isfinite(sigma)
    sigma = np.where(fallback, np.sqrt(np.maximum(d, 0.0)), sigma)       # Poisson fallback when fewer than 8 weeks of history exist
    lead_demand = d * L
    safety = np.maximum(0.0, z * sigma * np.sqrt(L))
    rop = lead_demand + safety
    order_up_to = np.round(rop + d * cfg.ORDER_COVER_DAYS, 2)       # rounded first, so the quantity can be reproduced from the report columns
    qty = np.ceil(np.maximum(0.0, order_up_to - stock) - 1e-9)

    rec = np.full(len(df), "NO_REORDER", dtype=object)
    rec[has_demand & (stock < rop)] = "REORDER_SOON"
    rec[has_demand & (stock <= lead_demand)] = "ORDER_NOW"
    rec[~has_demand] = "NO_DEMAND_DATA"
    qty = np.where(np.isin(rec, ["ORDER_NOW", "REORDER_SOON"]), qty, 0.0)

    upper7 = df["forecast_upper_7d"].to_numpy(dtype=float) / 7.0
    covers_upper = np.where(np.isfinite(upper7), stock >= L * upper7, True)
    cover = stockout["days_of_cover"].to_numpy(dtype=float)
    priority = np.full(len(df), "LOW", dtype=object)
    priority[rec == "REORDER_SOON"] = "MEDIUM"
    priority[(rec == "REORDER_SOON") & ~covers_upper] = "HIGH"             # forecast uncertainty: stock may not cover the lead time at the upper forecast
    priority[rec == "ORDER_NOW"] = "HIGH"
    priority[(rec == "ORDER_NOW") & ((stock == 0) | (cover < cfg.STOCKOUT_LEVELS["critical_days"]))] = "CRITICAL"

    reason = []
    for i in range(len(df)):
        if rec[i] == "NO_DEMAND_DATA":
            reason.append("No observed or forecast demand: no order quantity is recommended")
        elif rec[i] == "ORDER_NOW":
            reason.append(f"Stock {stock[i]:.0f} <= expected demand during the {L}-day lead time ({lead_demand[i]:.1f}): a stockout is expected before a new order could arrive; "
                          f"order up to {order_up_to[i]:.1f} units")
        elif rec[i] == "REORDER_SOON":
            extra = "" if covers_upper[i] else f"; stock may not cover the lead time at the upper forecast ({L * upper7[i]:.1f} units)"
            reason.append(f"Stock {stock[i]:.0f} is below the reorder point {rop[i]:.1f} (lead-time demand {lead_demand[i]:.1f} + safety stock {safety[i]:.1f}){extra}")
        else:
            reason.append(f"Stock {stock[i]:.0f} is at or above the reorder point {rop[i]:.1f}")

    out = df[["branch_id", "medicine_id", "medicine_name", "category", "current_inventory_units"]].copy()
    out["forecast_7d"] = df["forecast_7d"].round(3)
    out["forecast_14d"] = df["forecast_14d"].round(3)
    out["forecast_30d"] = df["forecast_30d"].round(3)
    out["expected_daily_demand"] = df["expected_daily_demand"].round(4)
    out["planning_lead_time_days"] = L
    out["expected_lead_time_demand"] = np.round(lead_demand, 2)
    out["demand_std_daily"] = np.round(np.where(fallback, np.nan, df["demand_std_daily"]), 4)
    out["variability_source"] = np.where(fallback, "poisson fallback (under 8 weeks of data)", "weekly demand std / sqrt(7)")
    out["service_level"] = cfg.SERVICE_LEVEL
    out["safety_stock"] = np.round(safety, 2)
    out["reorder_point"] = np.round(rop, 2)
    out["order_up_to_level"] = np.round(order_up_to, 2)
    out["recommended_order_quantity"] = qty.astype(int)
    out["recommendation"] = rec
    out["priority"] = priority
    out["reason"] = reason
    return out
