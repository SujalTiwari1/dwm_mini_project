-- Mining datasets, extracted and aggregated in PostgreSQL (warehouse schema). Python reads these and never touches raw CSVs.
-- Each statement is named with "-- @name:" and ends with a semicolon (keep semicolons out of comments).
-- Existing analytics views are reused where they already define a metric (v_medicine_performance, v_current_inventory,
-- v_stockout_summary, v_expiry_risk). No hidden generator metadata is used anywhere.

-- @name: medicines
SELECT m.medicine_key, m.medicine_id, m.medicine_name, c.category_name AS category
FROM warehouse.dim_medicine m
JOIN warehouse.dim_category c ON c.category_key = m.category_key
ORDER BY m.medicine_key;

-- @name: branches
SELECT branch_key, branch_id, branch_name
FROM warehouse.dim_branch
ORDER BY branch_key;

-- @name: dates
SELECT date_key, full_date
FROM warehouse.dim_date
ORDER BY date_key;

-- @name: baskets
-- One row per (transaction, medicine): the item is the MEDICINE, not the batch, so a medicine split over two batches counts once.
SELECT s.transaction_id, s.medicine_key
FROM warehouse.fact_sales s
GROUP BY s.transaction_id, s.medicine_key
ORDER BY s.transaction_id, s.medicine_key;

-- @name: warehouse_counts
SELECT (SELECT COUNT(DISTINCT transaction_id) FROM warehouse.fact_sales) AS transactions,
       (SELECT COUNT(DISTINCT medicine_key) FROM warehouse.fact_sales)   AS medicines_sold,
       (SELECT COUNT(*) FROM warehouse.dim_medicine)                     AS medicines,
       (SELECT COUNT(*) FROM warehouse.dim_branch)                       AS branches,
       (SELECT MIN(full_date)::text FROM warehouse.dim_date)             AS first_date,
       (SELECT MAX(full_date)::text FROM warehouse.dim_date)             AS last_date;

-- @name: daily_series
-- Dense daily series at date x branch x medicine: units sold and revenue (sales), closing stock (inventory snapshot).
SELECT i.date_key,
       i.branch_key,
       i.medicine_key,
       i.sold_quantity                AS units,
       COALESCE(r.revenue, 0)         AS revenue,
       i.closing_quantity             AS inventory_units
FROM warehouse.fact_inventory i
LEFT JOIN (
    SELECT date_key, branch_key, medicine_key, SUM(total_amount) AS revenue
    FROM warehouse.fact_sales
    GROUP BY date_key, branch_key, medicine_key
) r ON r.date_key = i.date_key AND r.branch_key = i.branch_key AND r.medicine_key = i.medicine_key
ORDER BY i.date_key, i.branch_key, i.medicine_key;

-- @name: purchase_lots
-- One row per received batch lot (a lot may be delivered to several branches on the same day).
SELECT p.batch_key,
       MIN(p.date_key)                AS date_key,
       p.medicine_key,
       p.supplier_key,
       SUM(p.quantity)                AS lot_quantity,
       MAX(p.unit_purchase_price)     AS unit_cost,
       COUNT(*)                       AS branches_delivered
FROM warehouse.fact_purchase p
GROUP BY p.batch_key, p.medicine_key, p.supplier_key
ORDER BY MIN(p.date_key), p.batch_key;

-- @name: medicine_features
-- One row per medicine over the full period (730 days x 5 branches). Pure SQL aggregation; clustering preprocessing happens in Python.
--   weekly figures use complete ISO weeks, turnover = annualised COGS / average inventory value (batch cost basis),
--   days_of_inventory = current stock / average daily demand of the last 30 days (NULL when no recent demand).
WITH cal AS (
    SELECT COUNT(*)::numeric AS days FROM warehouse.dim_date
),
daily_med AS (
    SELECT i.medicine_key, i.date_key, SUM(i.sold_quantity) AS units, SUM(i.closing_quantity) AS stock
    FROM warehouse.fact_inventory i
    GROUP BY i.medicine_key, i.date_key
),
demand AS (
    SELECT medicine_key,
           COUNT(*) FILTER (WHERE units > 0)  AS sales_days,
           COUNT(*) FILTER (WHERE units = 0)  AS zero_sales_days,
           AVG(stock)                         AS avg_inventory_units
    FROM daily_med
    GROUP BY medicine_key
),
weekly AS (
    SELECT medicine_key, AVG(units) AS avg_weekly_units, STDDEV_SAMP(units) AS weekly_demand_std
    FROM (
        SELECT i.medicine_key, EXTRACT(isoyear FROM d.full_date) AS iso_year, d.week, SUM(i.sold_quantity) AS units
        FROM warehouse.fact_inventory i
        JOIN warehouse.dim_date d ON d.date_key = i.date_key
        GROUP BY i.medicine_key, EXTRACT(isoyear FROM d.full_date), d.week
        HAVING COUNT(DISTINCT i.date_key) = 7
    ) w
    GROUP BY medicine_key
),
inv AS (
    -- average over days of the daily value held across all branches (sum over branches and days / number of days)
    SELECT i.medicine_key, SUM(i.closing_value_at_cost) / (SELECT days FROM cal) AS avg_inventory_value
    FROM warehouse.fact_inventory i
    GROUP BY i.medicine_key
),
cur AS (
    SELECT medicine_key, SUM(stock_units) AS current_inventory_units, SUM(stock_value_at_cost) AS current_inventory_value,
           SUM(avg_daily_demand_30d) AS demand_30d
    FROM warehouse.v_current_inventory
    GROUP BY medicine_key
),
so AS (
    SELECT medicine_key,
           COUNT(*) FILTER (WHERE closing_quantity = 0)                                      AS stockout_days,
           COUNT(*)                                                                          AS branch_days,
           COUNT(*) FILTER (WHERE closing_quantity = 0 AND COALESCE(prev_closing, 1) <> 0)   AS stockout_event_count
    FROM (
        SELECT medicine_key, closing_quantity,
               LAG(closing_quantity) OVER (PARTITION BY branch_key, medicine_key ORDER BY date_key) AS prev_closing
        FROM warehouse.fact_inventory
    ) x
    GROUP BY medicine_key
),
ex AS (
    SELECT medicine_key,
           COALESCE(SUM(remaining_units) FILTER (WHERE is_expired), 0)  AS expired_units,
           COALESCE(SUM(cost_value) FILTER (WHERE is_expired), 0)       AS expired_value,
           COALESCE(SUM(value_at_risk) FILTER (WHERE NOT is_expired), 0) AS expiry_risk_value
    FROM warehouse.v_expiry_risk
    GROUP BY medicine_key
),
pu AS (
    SELECT medicine_key, SUM(quantity) AS purchase_units, SUM(total_cost) AS purchase_cost
    FROM warehouse.fact_purchase
    GROUP BY medicine_key
),
cogs AS (
    SELECT s.medicine_key, SUM(s.quantity * b.purchase_price) AS cogs
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_batch b ON b.batch_key = s.batch_key
    GROUP BY s.medicine_key
)
SELECT m.medicine_key,
       m.medicine_id,
       m.medicine_name,
       c.category_name                                                         AS category,
       mp.units                                                                AS total_units_sold,
       mp.revenue                                                              AS total_revenue,
       mp.avg_selling_price,
       ROUND(mp.units / cal.days, 4)                                           AS avg_daily_units,
       ROUND(mp.revenue / cal.days, 4)                                         AS avg_daily_revenue,
       ROUND(w.avg_weekly_units, 4)                                            AS avg_weekly_units,
       ROUND(w.weekly_demand_std, 4)                                           AS weekly_demand_std,
       ROUND(w.weekly_demand_std / NULLIF(w.avg_weekly_units, 0), 4)           AS weekly_demand_cv,
       ROUND(w.weekly_demand_std / NULLIF(SQRT(w.avg_weekly_units), 0), 4)     AS demand_dispersion,   -- std / sqrt(mean): about 1 for Poisson demand, volume-independent
       dm.sales_days,
       dm.zero_sales_days,
       ROUND(dm.avg_inventory_units, 4)                                        AS avg_inventory_units,
       ROUND(iv.avg_inventory_value, 4)                                        AS avg_inventory_value,
       cu.current_inventory_units,
       cu.current_inventory_value,
       ROUND(cg.cogs / NULLIF(iv.avg_inventory_value, 0) * 365.25 / cal.days, 4) AS inventory_turnover,
       ROUND(cu.current_inventory_units / NULLIF(cu.demand_30d, 0), 2)         AS days_of_inventory,
       s.stockout_days,
       ROUND(s.stockout_days::numeric / s.branch_days, 6)                      AS stockout_rate,
       s.stockout_event_count,
       e.expired_units,
       e.expired_value,
       e.expiry_risk_value,
       p.purchase_units,
       p.purchase_cost,
       ROUND(p.purchase_cost / NULLIF(p.purchase_units, 0), 4)                 AS avg_purchase_cost
FROM warehouse.dim_medicine m
JOIN warehouse.dim_category c            ON c.category_key = m.category_key
JOIN warehouse.v_medicine_performance mp ON mp.medicine_key = m.medicine_key
JOIN demand dm                           ON dm.medicine_key = m.medicine_key
JOIN weekly w                            ON w.medicine_key = m.medicine_key
JOIN inv iv                              ON iv.medicine_key = m.medicine_key
JOIN cur cu                              ON cu.medicine_key = m.medicine_key
JOIN so s                                ON s.medicine_key = m.medicine_key
JOIN ex e                                ON e.medicine_key = m.medicine_key
JOIN pu p                                ON p.medicine_key = m.medicine_key
JOIN cogs cg                             ON cg.medicine_key = m.medicine_key
CROSS JOIN cal
ORDER BY m.medicine_key;
