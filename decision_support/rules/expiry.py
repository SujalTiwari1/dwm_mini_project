"""Expiry rules (grain: branch x medicine x batch). The methodology is the analytics layer's v_expiry_risk, reproduced so it can be reconciled row by row:

    expected_sales_before_expiry = daily_demand_90d x days_to_expiry
    projected_sold   = min(remaining, max(0, expected_sales_before_expiry - units_ahead))   (earlier-expiring lots of the same branch and medicine are sold first)
    projected_unsold = remaining - projected_sold          (counted only when days_to_expiry <= 365, the projection horizon)
    CRITICAL: projected_unsold > 0 and expiry within 30 days     HIGH: projected_unsold > 0 and within 90 days
    MEDIUM  : projected_unsold > 0 beyond 90 days, or expiring within 90 days but expected to sell out         LOW (analytics: SAFE): otherwise

Only live (non-expired) lots are assessed. Actions are inventory actions only: PRIORITIZE_SALE (CRITICAL, HIGH), MONITOR (MEDIUM), NO_ACTION (LOW).
The ML forecast is shown as evidence (forecast_demand_before_expiry) but does not change the validated risk class.
"""
import numpy as np
import pandas as pd

from .. import config as C

EPS = 1e-9


def assess(lots: pd.DataFrame, forecasts: pd.DataFrame, cfg=C) -> pd.DataFrame:
    E = cfg.EXPIRY
    df = lots[lots["days_to_expiry"] > 0].copy()
    days = df["days_to_expiry"].to_numpy(dtype=float)
    remaining = df["remaining_units"].to_numpy(dtype=float)
    demand = df["daily_demand_90d"].to_numpy(dtype=float)
    expected = demand * days
    sold = np.minimum(remaining, np.maximum(0.0, expected - df["units_ahead"].to_numpy(dtype=float)))
    unsold = np.where(days <= E["projection_horizon_days"], remaining - sold, 0.0)
    unsold = np.where(unsold < EPS, 0.0, unsold)
    level = np.full(len(df), "LOW", dtype=object)
    level[(unsold > 0) | (days <= E["high_days"])] = "MEDIUM"
    level[(unsold > 0) & (days <= E["high_days"])] = "HIGH"
    level[(unsold > 0) & (days <= E["critical_days"])] = "CRITICAL"
    unit_cost = df["unit_cost"].to_numpy(dtype=float)

    fc = df[["branch_id", "medicine_id"]].merge(forecasts[["branch_id", "medicine_id", "forecast_30d"]], on=["branch_id", "medicine_id"], how="left")
    f_rate = (fc["forecast_30d"].to_numpy(dtype=float) / 30.0)
    f_before = f_rate * np.minimum(days, E["projection_horizon_days"])

    reason = []
    for i in range(len(df)):
        if level[i] == "LOW":
            reason.append(f"{remaining[i]:.0f} units expire in {days[i]:.0f} days; expected sales before expiry ({expected[i]:.1f}) cover them")
        else:
            ahead = df["units_ahead"].iloc[i]
            reason.append(f"{remaining[i]:.0f} units expire in {days[i]:.0f} days; expected sales before expiry {expected[i]:.1f} "
                          f"(recent demand {demand[i]:.2f}/day, {ahead:.0f} units of earlier-expiring stock sell first) -> {unsold[i]:.1f} projected unsold"
                          if unsold[i] > 0 else
                          f"{remaining[i]:.0f} units expire in {days[i]:.0f} days (within {E['high_days']}) but expected sales ({expected[i]:.1f}) cover them: monitor")

    out = df[["branch_id", "medicine_id", "medicine_name", "category", "batch_id"]].copy()
    out["batch_quantity"] = df["remaining_units"].astype(int)
    out["days_to_expiry"] = df["days_to_expiry"].astype(int)
    out["expiry_date"] = df["expiry_date"]
    out["unit_cost"] = np.round(unit_cost, 2)
    out["recent_daily_demand_90d"] = np.round(demand, 4)
    out["units_ahead_fefo"] = df["units_ahead"].astype(int)
    out["expected_demand_before_expiry"] = np.round(expected, 2)
    out["forecast_demand_before_expiry"] = np.round(f_before, 2)
    out["projected_unsold_units"] = np.round(unsold, 2)
    out["projected_unsold_value"] = np.round(unsold * unit_cost, 2)
    out["risk_level"] = level
    out["recommended_action"] = [cfg.EXPIRY_ACTION[x] for x in level]
    out["reason"] = reason
    return out.reset_index(drop=True)
