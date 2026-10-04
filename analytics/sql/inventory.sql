-- Inventory analytics (fact_inventory, fact_sales, dim_batch and the analytics views). Run with: python -m analytics.run --file inventory
-- SEMI-ADDITIVE RULE: closing stock may be summed across branches/medicines/categories on ONE date, never across days.
-- "Current" = the latest date (v_current_inventory). Over time use the last day of each period, or an average of daily totals.

-- @name: Current inventory KPIs
SELECT MIN(snapshot_date)                                                  AS snapshot_date,
       SUM(stock_units)                                                    AS current_total_units,
       SUM(stock_value_at_cost)                                            AS current_inventory_value_at_cost,
       COUNT(DISTINCT medicine_key) FILTER (WHERE stock_units > 0)         AS medicines_currently_stocked,
       COUNT(DISTINCT branch_key)   FILTER (WHERE stock_units > 0)         AS branches_with_stock,
       COUNT(*) FILTER (WHERE stock_units = 0)                             AS out_of_stock_branch_medicines
FROM warehouse.v_current_inventory;

-- @name: Current inventory by branch
SELECT branch_name, SUM(stock_units) AS stock_units, SUM(stock_value_at_cost) AS stock_value_at_cost,
       COUNT(*) FILTER (WHERE stock_units > 0) AS medicines_stocked,
       ROUND(100.0 * SUM(stock_value_at_cost) / SUM(SUM(stock_value_at_cost)) OVER (), 2) AS value_share_pct
FROM warehouse.v_current_inventory
GROUP BY branch_name
ORDER BY stock_value_at_cost DESC;

-- @name: Current inventory by category
SELECT category_name, SUM(stock_units) AS stock_units, SUM(stock_value_at_cost) AS stock_value_at_cost,
       COUNT(DISTINCT medicine_key) FILTER (WHERE stock_units > 0) AS medicines_stocked,
       ROUND(100.0 * SUM(stock_value_at_cost) / SUM(SUM(stock_value_at_cost)) OVER (), 2) AS value_share_pct
FROM warehouse.v_current_inventory
GROUP BY category_name
ORDER BY stock_value_at_cost DESC;

-- @name: Current inventory by medicine (top 20 by value, all branches)
SELECT medicine_name, category_name, SUM(stock_units) AS stock_units, SUM(stock_value_at_cost) AS stock_value_at_cost,
       COUNT(*) FILTER (WHERE stock_units > 0) AS branches_with_stock
FROM warehouse.v_current_inventory
GROUP BY medicine_key, medicine_name, category_name
ORDER BY stock_value_at_cost DESC
LIMIT 20;

-- @name: Current inventory by branch > category > medicine (roll-up, top rows)
SELECT CASE WHEN GROUPING(branch_name) = 1 THEN 'ALL BRANCHES' ELSE branch_name END AS branch,
       CASE WHEN GROUPING(category_name) = 1 THEN 'all categories' ELSE category_name END AS category,
       CASE WHEN GROUPING(medicine_name) = 1 THEN 'subtotal' ELSE medicine_name END AS medicine,
       SUM(stock_units) AS stock_units, SUM(stock_value_at_cost) AS stock_value_at_cost
FROM warehouse.v_current_inventory
WHERE branch_name = (SELECT branch_name FROM warehouse.v_branch_performance ORDER BY revenue DESC LIMIT 1)
  AND category_name IN ('Respiratory', 'Cardiovascular')
GROUP BY ROLLUP (branch_name, category_name, medicine_name)
ORDER BY GROUPING(branch_name), GROUPING(category_name), category_name, GROUPING(medicine_name), stock_value_at_cost DESC
LIMIT 25;

-- @name: Stock status summary
-- OUT OF STOCK = 0 units / LOW STOCK = under 7 days of cover / OVERSTOCK = over 90 days of cover or no demand in 30 days / NORMAL otherwise
SELECT stock_status, COUNT(*) AS branch_medicine_pairs, SUM(stock_units) AS stock_units, SUM(stock_value_at_cost) AS stock_value_at_cost,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pair_share_pct,
       ROUND(100.0 * SUM(stock_value_at_cost) / SUM(SUM(stock_value_at_cost)) OVER (), 2) AS value_share_pct
FROM warehouse.v_current_inventory
GROUP BY stock_status
ORDER BY CASE stock_status WHEN 'OUT OF STOCK' THEN 1 WHEN 'LOW STOCK' THEN 2 WHEN 'NORMAL' THEN 3 ELSE 4 END;

-- @name: Stock status by branch
SELECT branch_name,
       COUNT(*) FILTER (WHERE stock_status = 'OUT OF STOCK') AS out_of_stock,
       COUNT(*) FILTER (WHERE stock_status = 'LOW STOCK')    AS low_stock,
       COUNT(*) FILTER (WHERE stock_status = 'NORMAL')       AS normal,
       COUNT(*) FILTER (WHERE stock_status = 'OVERSTOCK')    AS overstock
FROM warehouse.v_current_inventory
GROUP BY branch_name
ORDER BY branch_name;

-- @name: Out-of-stock and low-stock items needing replenishment (top 30 by demand)
SELECT branch_name, medicine_name, category_name, stock_units, avg_daily_demand_30d, days_of_inventory, stock_status
FROM warehouse.v_current_inventory
WHERE stock_status IN ('OUT OF STOCK', 'LOW STOCK')
ORDER BY avg_daily_demand_30d DESC, branch_name, medicine_name
LIMIT 30;

-- @name: Overstock with the most capital tied up (top 20)
SELECT branch_name, medicine_name, category_name, stock_units, stock_value_at_cost, avg_daily_demand_30d, days_of_inventory
FROM warehouse.v_current_inventory
WHERE stock_status = 'OVERSTOCK'
ORDER BY stock_value_at_cost DESC
LIMIT 20;

-- @name: Days of inventory by category (stock cover)
-- days_of_inventory = current stock / average daily demand over the last 30 days (NULL when demand is zero)
SELECT category_name,
       SUM(stock_units)                                                              AS stock_units,
       ROUND(SUM(avg_daily_demand_30d), 2)                                           AS daily_demand_30d,
       ROUND(SUM(stock_units) / NULLIF(SUM(avg_daily_demand_30d), 0), 1)             AS days_of_inventory
FROM warehouse.v_current_inventory
GROUP BY category_name
ORDER BY days_of_inventory DESC NULLS LAST;

-- @name: Month-end inventory (semi-additive: last day of each month)
WITH month_end AS (
    SELECT year, month, MAX(date_key) AS date_key FROM warehouse.dim_date GROUP BY year, month
)
SELECT me.year, me.month,
       SUM(i.closing_quantity)        AS month_end_units,
       SUM(i.closing_value_at_cost)   AS month_end_value_at_cost
FROM month_end me
JOIN warehouse.fact_inventory i ON i.date_key = me.date_key
GROUP BY me.year, me.month
ORDER BY me.year, me.month;

-- @name: Inventory turnover overall
-- COGS = SUM(units sold x the purchase price of the batch they came from) (cost basis, never selling price)
-- Average inventory value = average over days of the daily total closing_value_at_cost
-- Turnover = COGS / average inventory value (for the 24-month period). Annualised = turnover x 365.25 / days. Days inventory outstanding = 365.25 / annualised turnover.
WITH cogs AS (
    SELECT SUM(s.quantity * b.purchase_price) AS cogs
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_batch b ON b.batch_key = s.batch_key
),
daily_value AS (
    SELECT date_key, SUM(closing_value_at_cost) AS inventory_value FROM warehouse.fact_inventory GROUP BY date_key
),
avg_inv AS (SELECT AVG(inventory_value) AS avg_value, COUNT(*)::numeric AS days FROM daily_value)
SELECT ROUND(cogs.cogs, 2)                                                    AS cost_of_goods_sold,
       ROUND(a.avg_value, 2)                                                  AS average_inventory_value,
       ROUND(cogs.cogs / NULLIF(a.avg_value, 0), 3)                           AS turnover_period,
       ROUND(cogs.cogs / NULLIF(a.avg_value, 0) * 365.25 / a.days, 3)         AS turnover_annualised,
       ROUND(365.25 / NULLIF(cogs.cogs / NULLIF(a.avg_value, 0) * 365.25 / a.days, 0), 1) AS days_inventory_outstanding
FROM cogs
CROSS JOIN avg_inv a;

-- @name: Inventory turnover by category
WITH cogs AS (
    SELECT s.branch_key, s.medicine_key, SUM(s.quantity * b.purchase_price) AS cogs
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_batch b ON b.batch_key = s.batch_key
    GROUP BY s.branch_key, s.medicine_key
),
inv AS (
    SELECT branch_key, medicine_key, AVG(closing_value_at_cost) AS avg_value
    FROM warehouse.fact_inventory
    GROUP BY branch_key, medicine_key
),
cal AS (SELECT COUNT(*)::numeric AS days FROM warehouse.dim_date)
SELECT c.category_name,
       ROUND(SUM(cg.cogs), 2)                                                          AS cost_of_goods_sold,
       ROUND(SUM(iv.avg_value), 2)                                                     AS average_inventory_value,
       ROUND(SUM(cg.cogs) / NULLIF(SUM(iv.avg_value), 0), 3)                           AS turnover_period,
       ROUND(SUM(cg.cogs) / NULLIF(SUM(iv.avg_value), 0) * 365.25 / MAX(cal.days), 3)  AS turnover_annualised
FROM cogs cg
JOIN inv iv ON iv.branch_key = cg.branch_key AND iv.medicine_key = cg.medicine_key
JOIN warehouse.dim_medicine m ON m.medicine_key = cg.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
CROSS JOIN cal
GROUP BY c.category_name
ORDER BY turnover_annualised DESC;

-- @name: Inventory turnover by branch
WITH cogs AS (
    SELECT s.branch_key, s.medicine_key, SUM(s.quantity * b.purchase_price) AS cogs
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_batch b ON b.batch_key = s.batch_key
    GROUP BY s.branch_key, s.medicine_key
),
inv AS (
    SELECT branch_key, medicine_key, AVG(closing_value_at_cost) AS avg_value
    FROM warehouse.fact_inventory
    GROUP BY branch_key, medicine_key
),
cal AS (SELECT COUNT(*)::numeric AS days FROM warehouse.dim_date)
SELECT br.branch_name,
       ROUND(SUM(cg.cogs), 2)                                                          AS cost_of_goods_sold,
       ROUND(SUM(iv.avg_value), 2)                                                     AS average_inventory_value,
       ROUND(SUM(cg.cogs) / NULLIF(SUM(iv.avg_value), 0), 3)                           AS turnover_period,
       ROUND(SUM(cg.cogs) / NULLIF(SUM(iv.avg_value), 0) * 365.25 / MAX(cal.days), 3)  AS turnover_annualised
FROM cogs cg
JOIN inv iv ON iv.branch_key = cg.branch_key AND iv.medicine_key = cg.medicine_key
JOIN warehouse.dim_branch br ON br.branch_key = cg.branch_key
CROSS JOIN cal
GROUP BY br.branch_name
ORDER BY turnover_annualised DESC;

-- @name: Inventory turnover by medicine (top 15 and bottom 15, annualised)
WITH cogs AS (
    SELECT s.medicine_key, SUM(s.quantity * b.purchase_price) AS cogs
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_batch b ON b.batch_key = s.batch_key
    GROUP BY s.medicine_key
),
inv AS (
    SELECT medicine_key, SUM(closing_value_at_cost) / COUNT(DISTINCT date_key) AS avg_value
    FROM warehouse.fact_inventory
    GROUP BY medicine_key
),
cal AS (SELECT COUNT(*)::numeric AS days FROM warehouse.dim_date),
t AS (
    SELECT m.medicine_name, c.category_name, ROUND(cg.cogs, 2) AS cost_of_goods_sold, ROUND(iv.avg_value, 2) AS average_inventory_value,
           ROUND(cg.cogs / NULLIF(iv.avg_value, 0) * 365.25 / cal.days, 3) AS turnover_annualised
    FROM cogs cg
    JOIN inv iv ON iv.medicine_key = cg.medicine_key
    JOIN warehouse.dim_medicine m ON m.medicine_key = cg.medicine_key
    JOIN warehouse.dim_category c ON c.category_key = m.category_key
    CROSS JOIN cal
),
ranked AS (
    SELECT t.*, RANK() OVER (ORDER BY turnover_annualised DESC) AS r_top, RANK() OVER (ORDER BY turnover_annualised ASC) AS r_bottom FROM t
)
SELECT CASE WHEN r_top <= 15 THEN 'TOP' ELSE 'BOTTOM' END AS group_label, medicine_name, category_name, cost_of_goods_sold,
       average_inventory_value, turnover_annualised
FROM ranked
WHERE r_top <= 15 OR r_bottom <= 15
ORDER BY turnover_annualised DESC, medicine_name;

-- @name: Fast, medium and slow movers (summary)
-- mover_class by percentile of total units sold: FAST = top 20 percent, MEDIUM = next 30 percent, SLOW = bottom 50 percent
SELECT mover_class,
       COUNT(*)                                                         AS medicines,
       SUM(units)                                                       AS units,
       SUM(revenue)                                                     AS revenue,
       ROUND(100.0 * SUM(units) / SUM(SUM(units)) OVER (), 2)           AS unit_share_pct,
       ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2)       AS revenue_share_pct,
       MIN(avg_daily_units)                                             AS min_daily_units,
       MAX(avg_daily_units)                                             AS max_daily_units
FROM warehouse.v_medicine_performance
GROUP BY mover_class
ORDER BY CASE mover_class WHEN 'FAST' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END;

-- @name: Top 10 fast-moving medicines
SELECT medicine_name, category_name, units, avg_daily_units, transactions AS transaction_count, revenue
FROM warehouse.v_medicine_performance
WHERE mover_class = 'FAST'
ORDER BY units DESC
LIMIT 10;

-- @name: Top 10 slow-moving medicines (lowest units sold)
SELECT medicine_name, category_name, units, avg_daily_units, transactions AS transaction_count, revenue
FROM warehouse.v_medicine_performance
WHERE mover_class = 'SLOW'
ORDER BY units ASC, medicine_name
LIMIT 10;

-- @name: Slow movers tying up the most stock value
-- joins observable velocity with current stock: capital sitting in slow-moving medicines
SELECT mp.medicine_name, mp.category_name, mp.units AS units_sold_24m, SUM(ci.stock_units) AS stock_units,
       SUM(ci.stock_value_at_cost) AS stock_value_at_cost,
       ROUND(SUM(ci.stock_units) / NULLIF(mp.avg_daily_units, 0), 0) AS days_of_stock_at_average_demand
FROM warehouse.v_medicine_performance mp
JOIN warehouse.v_current_inventory ci ON ci.medicine_key = mp.medicine_key
WHERE mp.mover_class = 'SLOW'
GROUP BY mp.medicine_key, mp.medicine_name, mp.category_name, mp.units, mp.avg_daily_units
ORDER BY stock_value_at_cost DESC
LIMIT 15;
