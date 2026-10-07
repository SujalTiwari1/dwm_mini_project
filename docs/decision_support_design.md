# MedStock Decision Support: Design

> Source data is synthetic (generated for the MedStock academic DWM project). The layer makes inventory-management recommendations only; it makes no clinical, prescribing or drug-substitution recommendation and never treats an association rule as medical advice.

## 1. Objective
Convert warehouse state, analytics definitions and ML demand forecasts into explainable inventory recommendations that answer: *what needs attention, why, how urgent it is, what action could be considered, and what evidence supports it.*
Four decision areas (stockout risk, reorder, overstock, expiry) are combined into one **action queue**. There is no black-box score: every row has evidence fields and a plain-language reason, and the numeric `priority_score` only orders rows inside a priority.

## 2. Decision grain
| Decision | Grain |
|---|---|
| stockout risk, reorder, overstock, action queue | branch x medicine (2,500 rows) |
| expiry actions | branch x medicine x batch (live lots only) |

## 3. Input sources
* **Warehouse, as of the decision date** (`sql/decision_data.sql`, one query per dataset, every filter `full_date <= decision date`): current stock and value, units sold over the last 7/28/30/90 days, stockout days (28, 90, all history) and events, weekly demand mean/std over 26 blocks of 7 days ending on the decision date, recent average selling price, live batch lots (received minus sold) with first-expiry-first-out position.
* **ML forecasts** (`ml_forecasting/reports/forecasts.csv`, model `ml_selected`): 7/14/30-day point forecasts and the approximate 80% upper bound, for the forecast origin equal to the decision date.
* **Analytics views** are the reference definitions (low stock under 7 days, overstock, FEFO-aware expiry risk) and are reconciled against, not recomputed from scratch.
* The **decision date** is the latest date of `fact_inventory` (determined dynamically; currently 2026-12-31).

## 4. Stockout risk
* **Expected daily demand** = max(7-day forecast / 7, recent 28-day daily demand). The larger value is deliberate: the ML layer measured a systematic under-forecast of totals, and a stockout costs more than a little extra stock.
* **Days of cover** = stock / expected daily demand; NULL when expected demand is zero (class `NO_DEMAND_DATA`, never LOW risk and never automatically overstock).
* **Levels:** CRITICAL (stock 0, or under 3 days), HIGH (under 7: the analytics low-stock line), MEDIUM (under 14), LOW (14+). The 3 and 14-day cut-offs add granularity for a queue; all are configurable.
* **History and uncertainty:** a MEDIUM or LOW pair is escalated by exactly one level (never into CRITICAL) if it had 3 or more stockout days in the last 28, or a historical stockout rate over 2.5% (about 2.5x the average pair), or would have under 7 days of cover at the upper forecast. One step in total, so history and uncertainty are not stacked.
* **Output** `stockout_risk.csv`: stock, forecasts, expected demand, cover, stockout history, `base_risk_level`, `risk_level`, `risk_score` (100 x (1 - min(cover, 14) / 14), for ordering inside a level), `primary_reason`, `secondary_reason`.

## 5. Reorder logic and safety stock
```
expected_lead_time_demand = expected_daily_demand x planning_lead_time_days
safety_stock              = z x daily_demand_std x sqrt(planning_lead_time_days)
reorder_point             = expected_lead_time_demand + safety_stock
order_up_to_level         = reorder_point + expected_daily_demand x order_cover_days
recommended_order_quantity= ceil(max(0, order_up_to_level - current_inventory))        (open orders assumed zero)
```
* Units are kept consistent: the validated variability is **weekly**, so daily std = weekly std / sqrt(7) (independent days), over the last 26 blocks of 7 days. If fewer than 8 blocks exist the layer falls back to a Poisson std (sqrt of the mean) and says so in `variability_source`.
* **ORDER_NOW:** stock <= expected lead-time demand (a stockout is expected before a new order can arrive, includes stock = 0). **REORDER_SOON:** stock below the reorder point. **NO_REORDER:** otherwise. **NO_DEMAND_DATA:** no demand evidence, so no quantity is invented.
* **Uncertainty:** a REORDER_SOON whose stock would not cover the lead time at the upper forecast is raised to HIGH priority (it does not change the quantity, to avoid double counting the safety stock).

## 6. Overstock logic
Exactly the analytics definition: OVERSTOCK = stock > 0 and (no sales in the last 30 days or more than 90 days of cover, where cover = stock / (units sold in the last 30 days / 30)). Binary: no data-driven threshold justifies a SEVERE level.
Excess = units above 90 days of cover at the larger of the recent and forecast 30-day rate (stock the forecast will absorb is not called excess); value at the average unit cost of the stock on hand. A low-demand medicine is only flagged when its stock is large relative to its own demand.
The rule is evaluated with integer arithmetic (`stock x 30 > 90 x units_30d`). **Upstream boundary finding:** the analytics view labels a pair with exactly 90.0 days of cover (for example 12 units and 4 sold) as OVERSTOCK because its decimal division rounds 4/30 up; mathematically 90.0 is not over 90. The view was not changed; the reconciliation check requires that the only differences are those boundary pairs.

## 7. Expiry logic
The analytics `v_expiry_risk` method is reproduced and reconciled lot by lot: recent 90-day demand x days to expiry = expected sales before expiry; earlier-expiring lots of the same branch and medicine are sold first (`units_ahead`); projected unsold = remaining - min(remaining, max(0, expected - units_ahead)) within a 365-day horizon.
CRITICAL (projected unsold and expiry within 30 days), HIGH (within 90 days), MEDIUM (unsold beyond 90 days, or within 90 days but expected to sell out), LOW. Actions: PRIORITIZE_SALE (CRITICAL, HIGH), MONITOR (MEDIUM), NO_ACTION (LOW). Only live batches are assessed.
The ML forecast is shown as evidence (`forecast_demand_before_expiry`) but does not change the validated class.

## 8. Priority logic (action queue)
* Per-pair issues: **stock side** = the more severe of the stockout level and the reorder priority; **expiry** = the worst live lot (CRITICAL/HIGH, MEDIUM only when units are projected unsold); **overstock** = MEDIUM when OVERSTOCK with an excess value of at least INR 2,500, else LOW.
* **Queue materiality:** a CRITICAL/HIGH lot expecting under 1 unit of waste ranks as MEDIUM, so a fraction of a unit does not outrank a real stockout (the lot-level file keeps the analytics classification).
* **Priority** = the most severe issue. **Primary action** = the winning issue (ties: stock side, then expiry, then overstock): ORDER_NOW, REORDER_SOON, MONITOR_STOCK_CLOSELY, PRIORITIZE_SALE_EXPIRING_STOCK, MONITOR_EXPIRY, REVIEW_OVERSTOCK, MONITOR, NO_DEMAND_DATA. All other active issues are kept in `secondary_reasons`.
* **Order:** priority, then `priority_score` = 400/300/200/100 + 5 x active issues + min(impact / 1000, 50), then ids. Deterministic.
* **Impact** (potential exposure, never an actual loss): stockout = demand expected during the lead time that stock does not cover x recent average selling price (potential revenue exposure); overstock = estimated excess value at cost; expiry = projected unsold value at cost. Their sum orders rows only; it mixes revenue and cost bases.

## 9. Planning assumptions (NOT in the synthetic data)
* Supplier lead time **7 days**: the data has receipt dates only, no order dates, so lead time is unobservable.
* Service level **95%** (z = 1.645) for safety stock, not an optimised value.
* Each order covers **14 days** of demand beyond the lead time. No minimum order quantities, pack sizes or supplier availability limits; open (in-transit) orders assumed zero.
* Business parameters: stockout cut-offs 3/7/14 days, escalation rule, INR 2,500 overstock materiality, 1-unit expiry materiality. All are in `decision_support/config.py`.

## 10. Leakage prevention (decision-time simulation)
A decision for date D may use only information available on D plus forecasts. The warehouse queries filter `full_date <= D`; the forecasts are the ones whose origin is D, produced by a model fitted on earlier targets only. Validation rebuilds the decision for **2026-09-30** and shows:
1. every input row is dated on or before that date;
2. the SQL inputs equal an independent pandas recomputation from the series **truncated at that date** (all pairs, all measures);
3. scrambling every sales, inventory and stockout value **after** the date leaves the inputs unchanged;
4. live batch units equal the inventory snapshot of that date for every pair (lots use only purchases and sales up to the date), and no live lot has expired on the date;
5. the forecasts used have that date as origin and the model behind them was trained on targets up to 2026-09-30 only.

## 11. Validation
Structure (all pairs represented, valid levels, days of cover recomputed, non-negative quantities, ORDER_NOW iff stock <= lead-time demand, overstock matches the threshold, only live batches, one row per pair, deterministic order, secondary risks preserved), **reconciliation** with `fact_inventory`/analytics views and `forecasts.csv` (current inventory units and value, 30-day demand, stockout days, overstock status, every live lot's quantity/days/class/projected unsold, every forecast value), the **leakage** tests above, and **six deterministic scenarios**: zero inventory, large stock with no demand, an expiring batch (and the same date with little stock and high demand), healthy stock, no reliable demand, escalation by history.

## 12. Limitations
* Forecasts are estimates with a known under-forecast bias and an approximate interval; decisions inherit this.
* Stockout history censors observed demand; recent demand may understate true demand.
* Lead time, service level and order cover are assumptions; quantities ignore supplier constraints and cannot be better than those assumptions.
* The expiry method uses trailing demand and does not model returns, inter-branch transfers or discounting.
* Exposures mix revenue and cost bases and are potential exposures, not losses.
* Synthetic data: the output shows how the method works, not what a real pharmacy should order.

## 13. Reproducibility
No random numbers are used by the engine (the leakage test seeds its own scrambling with 42); all orderings are explicit. Inputs are the warehouse as of the decision date and the fixed forecast file. Two runs of `python -m decision_support.run` give identical reports except `run_timestamp` and `runtime_seconds` in `decision_summary.json`.

## Architecture
```
                 Warehouse
                     │
                     ├──────────────┐
                     ↓              ↓
                Analytics       Inventory (as of the decision date)
                     │              │
                     ↓              │
                Data Mining         │
                     │              │
                     ↓              │
                ML Forecast ────────┘
                     │
                     ↓
              Decision Engine
                     │
       ┌─────────────┼─────────────┐
       ↓             ↓             ↓
   Stockout       Reorder       Overstock
     Risk        Recommendation    Risk
       │             │             │
       └─────────────┼─────────────┘
                     ↓
                Expiry Risk (batch level)
                     │
                     ↓
              Priority Engine
                     │
                     ↓
                Action Queue
```
