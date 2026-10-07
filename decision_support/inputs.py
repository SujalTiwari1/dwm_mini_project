"""Decision inputs: warehouse state AS OF the decision date (SQL, one query per dataset) merged with the ML forecasts made on that date.

Decision-time rule: only information available on the decision date is used. The warehouse queries filter full_date <= decision date, the
forecasts are the ones issued with that date as the forecast origin, and nothing here ever reads a later sales, inventory, stockout or expiry value.
"""
import numpy as np
import pandas as pd

from analytics.run import split_statements
from etl.load.postgres import get_engine

from . import config as C

_STATEMENTS = None


def _statements():
    global _STATEMENTS
    if _STATEMENTS is None:
        _STATEMENTS = dict(split_statements((C.SQL_DIR / "decision_data.sql").read_text(encoding="utf-8")))
    return _STATEMENTS


def run_query(conn, name, params=None) -> pd.DataFrame:
    res = conn.exec_driver_sql(_statements()[name], params) if params is not None else conn.exec_driver_sql(_statements()[name])
    return pd.DataFrame(res.fetchall(), columns=list(res.keys()))


def open_connection():
    engine = get_engine()
    conn = engine.connect()
    conn.exec_driver_sql("SET work_mem = '128MB'")
    return engine, conn


def latest_date(conn) -> str:
    return run_query(conn, "latest_date").iloc[0, 0]


def load_state(conn, decision_date: str) -> pd.DataFrame:
    df = run_query(conn, "pair_state", (decision_date, C.VARIABILITY_WEEKS, C.PRICE_WINDOW_DAYS))
    for c in df.columns:
        if c not in ("branch_id", "medicine_id", "medicine_name", "category", "last_date_used"):
            df[c] = pd.to_numeric(df[c])
    return df


def load_lots(conn, decision_date: str) -> pd.DataFrame:
    w = C.EXPIRY["demand_window_days"]
    df = run_query(conn, "live_lots", (decision_date, w, w))
    for c in ("days_to_expiry", "remaining_units", "unit_cost", "daily_demand_90d", "units_ahead"):
        df[c] = pd.to_numeric(df[c])
    return df


def load_forecasts(decision_date: str) -> pd.DataFrame:
    """ML forecasts whose forecast origin is the decision date: one row per branch x medicine with 7/14/30-day point forecasts and upper bounds."""
    f = pd.read_csv(C.FORECASTS_CSV)
    f = f[(f["model"] == C.FORECAST_MODEL) & (f["forecast_date"] == decision_date)]
    if f.empty:
        raise ValueError(f"no {C.FORECAST_MODEL} forecasts with forecast origin {decision_date} in {C.FORECASTS_CSV.name}")
    out = None
    for h in (7, 14, 30):
        g = f[f["horizon"] == h][["branch_id", "medicine_id", "predicted_units", "lower_bound", "upper_bound"]]
        g = g.rename(columns={"predicted_units": f"forecast_{h}d", "lower_bound": f"forecast_lower_{h}d", "upper_bound": f"forecast_upper_{h}d"})
        out = g if out is None else out.merge(g, on=["branch_id", "medicine_id"], how="outer", validate="one_to_one")
    out["forecast_split"] = f["split"].iloc[0]
    return out


def build_frame(state: pd.DataFrame, fc: pd.DataFrame) -> pd.DataFrame:
    """One row per branch x medicine with every input the rules need (all as of the decision date)."""
    df = state.merge(fc, on=["branch_id", "medicine_id"], how="left", validate="one_to_one")
    df["recent_daily_demand"] = df["units_28d"] / C.RECENT_DEMAND_DAYS
    f7 = df["forecast_7d"].fillna(0.0)
    # conservative planning demand: the larger of the 7-day forecast rate and the recent 28-day rate
    df["expected_daily_demand"] = np.maximum(f7 / 7.0, df["recent_daily_demand"])
    df["has_forecast"] = df["forecast_7d"].notna()
    ok = df["weeks_with_data"].fillna(0) >= C.MIN_VARIABILITY_WEEKS_WITH_DATA
    df["demand_std_daily"] = np.where(ok, df["weekly_std"] / np.sqrt(7.0), np.nan)    # weekly std -> daily std (independent days: var_week = 7 var_day)
    df["demand_cv_weekly"] = np.where(ok & (df["weekly_mean"] > 0), df["weekly_std"] / df["weekly_mean"], np.nan)
    df["historical_stockout_rate"] = df["stockout_days_total"] / df["days_observed"]
    df["unit_cost"] = np.where(df["current_inventory_units"] > 0, df["current_inventory_value"] / df["current_inventory_units"].replace(0, np.nan), np.nan)
    return df
