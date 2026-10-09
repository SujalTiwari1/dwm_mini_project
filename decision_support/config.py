"""Configuration for the MedStock decision-support layer.

Two kinds of parameters live here, and each is labelled:
  * ALIGNED  : taken from an already validated upstream layer (analytics / ML) so terminology stays consistent;
  * ASSUMPTION: planning assumptions that are NOT present in, and cannot be learned from, the synthetic dataset.
Nothing here is statistically "optimal" for this synthetic pharmacy.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DS_DIR = Path(__file__).resolve().parent
SQL_DIR = DS_DIR / "sql"
from datasets import paths as _ds
REPORT_DIR = _ds.report_dir("decision")
FORECASTS_CSV = _ds.report_dir("forecast") / "forecasts.csv"
FORECAST_SUMMARY = _ds.report_dir("forecast") / "forecast_summary.json"
FORECAST_MODEL = "ml_selected"
RANDOM_SEED = 42                  # only used to scramble post-decision data in the leakage test; the engine itself is deterministic

# Decision date: None = the latest date of the warehouse inventory snapshot (determined dynamically).
DECISION_DATE = None
# Historical decision-time simulation (leakage test): recommendations rebuilt using only information available on this date.
HISTORICAL_DECISION_DATE = "2026-09-30"

# ---------------------------------------------------------------------------
# Demand signal
# ---------------------------------------------------------------------------
RECENT_DEMAND_DAYS = 28            # recent daily demand = units sold over the last 28 days / 28
# expected_daily_demand = max(forecast_7d / 7, recent_28d daily demand). Taking the larger of the two is a deliberate conservative choice:
# the ML layer measured a systematic under-forecast of totals (about -7% to -11%), and running out of stock is costlier than holding a little extra.
VARIABILITY_WEEKS = 26             # weekly demand standard deviation over the last 26 blocks of 7 days ending on the decision date
MIN_VARIABILITY_WEEKS_WITH_DATA = 8

# ---------------------------------------------------------------------------
# Stockout risk (days of cover = stock / expected daily demand)
# ---------------------------------------------------------------------------
# ALIGNED: the analytics layer calls under 7 days of cover LOW STOCK, so HIGH starts at 7 days. CRITICAL (3 days) and MEDIUM (14 days)
# add granularity for an action queue (a 3-level cut would hide the difference between "tomorrow" and "next week").
STOCKOUT_LEVELS = {"critical_days": 3.0, "high_days": 7.0, "medium_days": 14.0}
STOCKOUT_ESCALATION = {
    "stockout_days_28d": 3,        # 3 or more stockout days in the last 28 days ...
    "historical_rate": 0.025,      # ... or a stockout rate above 2.5 percent of all days observed (about 2.5x the average pair) escalates one level
}
# At most ONE escalation step in total (history and forecast uncertainty are not stacked), to keep the logic explainable.

# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------
# ASSUMPTION: the dataset records receipt dates only (no order dates), so supplier lead times are NOT observable. 7 days is a planning assumption.
PLANNING_LEAD_TIME_DAYS = 7
# ASSUMPTION: service level for safety stock. z = 1.645 is the one-sided 95 percent normal quantile. Not an optimised value.
SERVICE_LEVEL = 0.95
# ASSUMPTION: each order covers this many days of demand beyond the lead time. No minimum order quantities, pack sizes, supplier
# availability or open (in-transit) orders exist in the data, so none are modelled (open orders are assumed to be zero).
ORDER_COVER_DAYS = 14

# ---------------------------------------------------------------------------
# Overstock
# ---------------------------------------------------------------------------
# ALIGNED with analytics v_current_inventory: OVERSTOCK = stock > 0 and (no sales in the last 30 days or days of inventory over 90),
# where days of inventory = stock / (units sold in the last 30 days / 30). The binary classification is kept (no SEVERE level: no
# threshold in the data justifies a second cut-off).
OVERSTOCK = {"window_days": 30, "max_cover_days": 90}
# ASSUMPTION (business materiality, used only for ranking): excess inventory worth at least this at cost is ranked MEDIUM, otherwise LOW.
OVERSTOCK_MEDIUM_EXCESS_VALUE = 2500.0

# ---------------------------------------------------------------------------
# Expiry (ALIGNED with analytics v_expiry_risk: trailing 90-day demand, FEFO-aware projection, 365-day horizon)
# ---------------------------------------------------------------------------
EXPIRY = {"demand_window_days": 90, "projection_horizon_days": 365, "critical_days": 30, "high_days": 90}
EXPIRY_ACTION = {"CRITICAL": "PRIORITIZE_SALE", "HIGH": "PRIORITIZE_SALE", "MEDIUM": "MONITOR", "LOW": "NO_ACTION"}
# ASSUMPTION (materiality, queue ranking only): a lot whose projected waste is under this many units does not raise a CRITICAL/HIGH queue priority
# (it ranks as MEDIUM = monitor). The lot-level expiry_actions.csv keeps the analytics classification unchanged.
EXPIRY_MIN_UNSOLD_UNITS_FOR_ALERT = 1.0

# ---------------------------------------------------------------------------
# Priority (explicit rules first; the numeric score only orders rows inside a priority)
# ---------------------------------------------------------------------------
PRIORITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
PRICE_WINDOW_DAYS = 90             # average selling price over this window converts forecast units to potential revenue exposure
