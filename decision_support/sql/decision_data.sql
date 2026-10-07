-- Decision-support inputs, AS OF a decision date, aggregated in PostgreSQL (warehouse schema). One query per dataset, never per medicine or per branch.
-- Parameter %s = the decision date. Every table is filtered with full_date <= decision date, so nothing after the decision date can enter.
-- Each statement is named with "-- @name:" and ends with a semicolon (keep semicolons out of comments).

-- @name: latest_date
SELECT MAX(d.full_date)::text AS latest_date
FROM warehouse.fact_inventory i
JOIN warehouse.dim_date d ON d.date_key = i.date_key;

-- @name: pair_state
-- One row per branch x medicine as of the decision date: current stock, recent demand, stockout history, weekly demand variability.
WITH snap AS (
    SELECT %s::date AS d
),
inv AS (
    SELECT i.branch_key, i.medicine_key, d.full_date, i.sold_quantity AS units, i.closing_quantity AS stock, i.closing_value_at_cost AS stock_value,
           LAG(i.closing_quantity) OVER (PARTITION BY i.branch_key, i.medicine_key ORDER BY d.full_date) AS prev_stock
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date d ON d.date_key = i.date_key
    CROSS JOIN snap
    WHERE d.full_date <= snap.d
),
agg AS (
    SELECT inv.branch_key, inv.medicine_key,
           MAX(inv.stock)       FILTER (WHERE inv.full_date = snap.d)                          AS current_inventory_units,
           MAX(inv.stock_value) FILTER (WHERE inv.full_date = snap.d)                          AS current_inventory_value,
           SUM(inv.units) FILTER (WHERE inv.full_date > snap.d - 7)                            AS units_7d,
           SUM(inv.units) FILTER (WHERE inv.full_date > snap.d - 28)                           AS units_28d,
           SUM(inv.units) FILTER (WHERE inv.full_date > snap.d - 30)                           AS units_30d,
           SUM(inv.units) FILTER (WHERE inv.full_date > snap.d - 90)                           AS units_90d,
           COUNT(*) FILTER (WHERE inv.stock = 0 AND inv.full_date > snap.d - 28)               AS stockout_days_last_28d,
           COUNT(*) FILTER (WHERE inv.stock = 0 AND inv.full_date > snap.d - 90)               AS stockout_days_last_90d,
           COUNT(*) FILTER (WHERE inv.stock = 0)                                               AS stockout_days_total,
           COUNT(*)                                                                            AS days_observed,
           COUNT(*) FILTER (WHERE inv.stock = 0 AND COALESCE(inv.prev_stock, 1) <> 0)          AS stockout_event_count,
           MAX(inv.full_date)                                                                  AS last_date_used
    FROM inv CROSS JOIN snap
    GROUP BY inv.branch_key, inv.medicine_key
),
blocks AS (
    -- blocks of 7 days counted back from the decision date (block 0 = the last 7 days): complete, as-of-safe weekly sums
    SELECT inv.branch_key, inv.medicine_key, ((snap.d - inv.full_date) / 7) AS blk, SUM(inv.units) AS units
    FROM inv CROSS JOIN snap
    WHERE inv.full_date > snap.d - (7 * %s)
    GROUP BY inv.branch_key, inv.medicine_key, ((snap.d - inv.full_date) / 7)
),
weekly AS (
    SELECT branch_key, medicine_key, COUNT(*) AS weeks_with_data, AVG(units) AS weekly_mean, STDDEV_SAMP(units) AS weekly_std
    FROM blocks
    GROUP BY branch_key, medicine_key
),
price AS (
    SELECT s.branch_key, s.medicine_key, SUM(s.total_amount) / NULLIF(SUM(s.quantity), 0) AS avg_selling_price
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_date d ON d.date_key = s.date_key
    CROSS JOIN snap
    WHERE d.full_date <= snap.d AND d.full_date > snap.d - %s
    GROUP BY s.branch_key, s.medicine_key
)
SELECT b.branch_id, m.medicine_id, m.medicine_name, c.category_name AS category, a.branch_key, a.medicine_key,
       a.current_inventory_units, a.current_inventory_value,
       COALESCE(a.units_7d, 0) AS units_7d, COALESCE(a.units_28d, 0) AS units_28d, COALESCE(a.units_30d, 0) AS units_30d, COALESCE(a.units_90d, 0) AS units_90d,
       a.stockout_days_last_28d, a.stockout_days_last_90d, a.stockout_days_total, a.days_observed, a.stockout_event_count,
       w.weeks_with_data, w.weekly_mean, w.weekly_std,
       COALESCE(p.avg_selling_price, m.base_price) AS avg_selling_price,
       a.last_date_used::text AS last_date_used
FROM agg a
JOIN warehouse.dim_branch b   ON b.branch_key = a.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = a.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
LEFT JOIN weekly w ON w.branch_key = a.branch_key AND w.medicine_key = a.medicine_key
LEFT JOIN price p  ON p.branch_key = a.branch_key AND p.medicine_key = a.medicine_key
ORDER BY b.branch_id, m.medicine_id;

-- @name: live_lots
-- Batch lots holding stock at the decision date (received at the branch on or before the date, minus sold on or before it), not yet expired.
-- units_ahead = units of earlier-expiring live lots of the same branch and medicine (first-expiry-first-out). Same definitions as analytics v_expiry_risk.
WITH snap AS (
    SELECT %s::date AS d
),
received AS (
    SELECT p.branch_key, p.batch_key, SUM(p.quantity) AS units
    FROM warehouse.fact_purchase p
    JOIN warehouse.dim_date dd ON dd.date_key = p.date_key
    CROSS JOIN snap
    WHERE dd.full_date <= snap.d
    GROUP BY p.branch_key, p.batch_key
),
sold AS (
    SELECT s.branch_key, s.batch_key, SUM(s.quantity) AS units
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_date dd ON dd.date_key = s.date_key
    CROSS JOIN snap
    WHERE dd.full_date <= snap.d
    GROUP BY s.branch_key, s.batch_key
),
demand AS (
    SELECT i.branch_key, i.medicine_key, SUM(i.sold_quantity) / %s::numeric AS daily_demand
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date dd ON dd.date_key = i.date_key
    CROSS JOIN snap
    WHERE dd.full_date <= snap.d AND dd.full_date > snap.d - %s
    GROUP BY i.branch_key, i.medicine_key
),
lots AS (
    SELECT r.branch_key, bt.medicine_key, bt.batch_key, bt.batch_id, bt.expiry_date, bt.purchase_price,
           r.units - COALESCE(s.units, 0) AS remaining_units,
           (bt.expiry_date - snap.d) AS days_to_expiry,
           COALESCE(dm.daily_demand, 0) AS daily_demand_90d
    FROM received r
    LEFT JOIN sold s ON s.branch_key = r.branch_key AND s.batch_key = r.batch_key
    JOIN warehouse.dim_batch bt ON bt.batch_key = r.batch_key
    CROSS JOIN snap
    LEFT JOIN demand dm ON dm.branch_key = r.branch_key AND dm.medicine_key = bt.medicine_key
    WHERE r.units - COALESCE(s.units, 0) > 0 AND bt.expiry_date > snap.d
)
SELECT b.branch_id, m.medicine_id, m.medicine_name, c.category_name AS category, l.batch_id, l.expiry_date::text AS expiry_date,
       l.days_to_expiry, l.remaining_units, l.purchase_price AS unit_cost, l.daily_demand_90d,
       COALESCE(SUM(l.remaining_units) OVER (PARTITION BY l.branch_key, l.medicine_key ORDER BY l.expiry_date, l.batch_key
                                             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS units_ahead
FROM lots l
JOIN warehouse.dim_branch b   ON b.branch_key = l.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = l.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
ORDER BY b.branch_id, m.medicine_id, l.expiry_date, l.batch_id;

-- @name: daily_series
-- Dense daily series used ONLY by validation to recompute the as-of inputs independently: date x branch x medicine units sold and closing stock.
SELECT d.full_date::text AS full_date, b.branch_id, m.medicine_id, i.sold_quantity AS units, i.closing_quantity AS stock
FROM warehouse.fact_inventory i
JOIN warehouse.dim_date d     ON d.date_key = i.date_key
JOIN warehouse.dim_branch b   ON b.branch_key = i.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
ORDER BY d.full_date, b.branch_id, m.medicine_id;

-- @name: analytics_inventory
-- Analytics view reference (latest date only), for reconciliation.
SELECT b.branch_id, m.medicine_id, v.stock_units, v.stock_value_at_cost, v.avg_daily_demand_30d, v.days_of_inventory, v.stock_status
FROM warehouse.v_current_inventory v
JOIN warehouse.dim_branch b   ON b.branch_key = v.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = v.medicine_key
ORDER BY b.branch_id, m.medicine_id;

-- @name: analytics_stockouts
SELECT b.branch_id, m.medicine_id, v.stockout_days
FROM warehouse.v_stockout_summary v
JOIN warehouse.dim_branch b   ON b.branch_key = v.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = v.medicine_key
ORDER BY b.branch_id, m.medicine_id;

-- @name: analytics_expiry
SELECT b.branch_id, v.batch_id, v.remaining_units, v.days_to_expiry, v.projected_unsold_units, v.risk_class
FROM warehouse.v_expiry_risk v
JOIN warehouse.dim_branch b ON b.branch_key = v.branch_key
WHERE NOT v.is_expired
ORDER BY b.branch_id, v.batch_id;
