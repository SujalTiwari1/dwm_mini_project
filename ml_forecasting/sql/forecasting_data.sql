-- Forecasting datasets, aggregated in PostgreSQL (warehouse schema). One query per dataset, never per medicine or per day.
-- Each statement is named with "-- @name:" and ends with a semicolon (keep semicolons out of comments).

-- @name: medicines
SELECT m.medicine_key, m.medicine_id, m.medicine_name, c.category_name AS category
FROM warehouse.dim_medicine m
JOIN warehouse.dim_category c ON c.category_key = m.category_key
ORDER BY m.medicine_key;

-- @name: branches
SELECT branch_key, branch_id, branch_name FROM warehouse.dim_branch ORDER BY branch_key;

-- @name: dates
SELECT date_key, full_date FROM warehouse.dim_date ORDER BY date_key;

-- @name: daily_series
-- Dense daily series at date x branch x medicine: units sold and revenue (sales), closing stock (inventory snapshot).
-- inventory_units = 0 is the stockout flag (end-of-day stock is zero).
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

-- @name: pair_segments
-- DESCRIPTIVE slicing labels for evaluation only (existing analytics views, full 24 months). They are never model features.
SELECT ss.branch_key, ss.medicine_key,
       mp.mover_class,
       ss.stockout_rate_pct,
       ds.variability_class
FROM warehouse.v_stockout_summary ss
JOIN warehouse.v_medicine_performance mp ON mp.medicine_key = ss.medicine_key
JOIN warehouse.v_demand_stats ds ON ds.branch_key = ss.branch_key AND ds.medicine_key = ss.medicine_key
ORDER BY ss.branch_key, ss.medicine_key;

-- @name: warehouse_counts
SELECT (SELECT COUNT(*) FROM warehouse.fact_inventory)                                         AS inventory_rows,
       (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0)              AS stockout_rows,
       (SELECT SUM(sold_quantity) FROM warehouse.fact_inventory)                               AS units_sold,
       (SELECT MIN(full_date)::text FROM warehouse.dim_date)                                   AS first_date,
       (SELECT MAX(full_date)::text FROM warehouse.dim_date)                                   AS last_date;

-- @name: window_check
-- independent recount for validation: units sold and stockout days of one branch/medicine between two dates (parameters: branch_id, medicine_id, from date, to date)
SELECT COALESCE(SUM(i.sold_quantity), 0)                               AS units,
       COUNT(*) FILTER (WHERE i.closing_quantity = 0)                  AS stockout_days,
       COUNT(*)                                                        AS days
FROM warehouse.fact_inventory i
JOIN warehouse.dim_branch b   ON b.branch_key = i.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
JOIN warehouse.dim_date d     ON d.date_key = i.date_key
WHERE b.branch_id = %s AND m.medicine_id = %s AND d.full_date BETWEEN %s AND %s;
