-- Stockout analytics. A stockout day = a branch-medicine-day with FACT_INVENTORY.closing_quantity = 0 (end-of-day stock is zero).
-- stockout rate = stockout days / branch-medicine-days observed. A stockout EVENT = the first day of an uninterrupted run of stockout days.
-- Run with: python -m analytics.run --file stockouts

-- @name: Overall stockout KPIs
-- single pass over fact_inventory (the LAG window finds where a stockout run starts)
WITH flagged AS (
    SELECT branch_key, medicine_key, closing_quantity,
           LAG(closing_quantity) OVER (PARTITION BY branch_key, medicine_key ORDER BY date_key) AS prev_closing
    FROM warehouse.fact_inventory
)
SELECT COUNT(*) FILTER (WHERE closing_quantity = 0)                                         AS total_stockout_days,
       COUNT(*)                                                                             AS branch_medicine_days,
       ROUND(100.0 * COUNT(*) FILTER (WHERE closing_quantity = 0) / COUNT(*), 3)            AS stockout_rate_pct,
       COUNT(*) FILTER (WHERE closing_quantity = 0 AND COALESCE(prev_closing, 1) <> 0)      AS stockout_events,
       COUNT(DISTINCT medicine_key) FILTER (WHERE closing_quantity = 0)                     AS medicines_affected,
       COUNT(DISTINCT branch_key)   FILTER (WHERE closing_quantity = 0)                     AS branches_affected,
       COUNT(DISTINCT (branch_key, medicine_key)) FILTER (WHERE closing_quantity = 0)       AS branch_medicine_pairs_affected
FROM flagged;

-- @name: Stockouts by branch
WITH flagged AS (
    SELECT branch_key, medicine_key, closing_quantity,
           LAG(closing_quantity) OVER (PARTITION BY branch_key, medicine_key ORDER BY date_key) AS prev_closing
    FROM warehouse.fact_inventory
)
SELECT b.branch_name,
       COUNT(*) FILTER (WHERE f.closing_quantity = 0)                                    AS stockout_days,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.closing_quantity = 0) / COUNT(*), 3)       AS stockout_rate_pct,
       COUNT(*) FILTER (WHERE f.closing_quantity = 0 AND COALESCE(f.prev_closing, 1) <> 0) AS stockout_events,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.closing_quantity = 0)
             / SUM(COUNT(*) FILTER (WHERE f.closing_quantity = 0)) OVER (), 2)           AS share_of_all_stockout_days_pct
FROM flagged f
JOIN warehouse.dim_branch b ON b.branch_key = f.branch_key
GROUP BY b.branch_name
ORDER BY stockout_days DESC;

-- @name: Stockouts by category
WITH flagged AS (
    SELECT i.branch_key, i.medicine_key, i.closing_quantity,
           LAG(i.closing_quantity) OVER (PARTITION BY i.branch_key, i.medicine_key ORDER BY i.date_key) AS prev_closing
    FROM warehouse.fact_inventory i
)
SELECT c.category_name,
       COUNT(*) FILTER (WHERE f.closing_quantity = 0)                                    AS stockout_days,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.closing_quantity = 0) / COUNT(*), 3)       AS stockout_rate_pct,
       COUNT(*) FILTER (WHERE f.closing_quantity = 0 AND COALESCE(f.prev_closing, 1) <> 0) AS stockout_events,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.closing_quantity = 0)
             / SUM(COUNT(*) FILTER (WHERE f.closing_quantity = 0)) OVER (), 2)           AS share_of_all_stockout_days_pct
FROM flagged f
JOIN warehouse.dim_medicine m ON m.medicine_key = f.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY c.category_name
ORDER BY stockout_days DESC;

-- @name: Top 20 medicines by stockout days (all branches)
SELECT RANK() OVER (ORDER BY SUM(stockout_days) DESC) AS rank, medicine_name, category_name,
       SUM(stockout_days) AS stockout_days,
       COUNT(*) FILTER (WHERE stockout_days > 0) AS branches_affected,
       ROUND(100.0 * SUM(stockout_days) / SUM(days_observed), 3) AS stockout_rate_pct
FROM warehouse.v_stockout_summary
GROUP BY medicine_key, medicine_name, category_name
ORDER BY stockout_days DESC, medicine_name
LIMIT 20;

-- @name: Top 20 medicine-branch pairs by stockout days
SELECT medicine_name, branch_name, category_name, stockout_days, stockout_rate_pct
FROM warehouse.v_stockout_summary
ORDER BY stockout_days DESC, medicine_name, branch_name
LIMIT 20;

-- @name: Stockout concentration (share of all stockout days in the top 10 and top 20 medicines)
WITH per_medicine AS (
    SELECT medicine_key, SUM(stockout_days) AS days FROM warehouse.v_stockout_summary GROUP BY medicine_key
),
ranked AS (
    SELECT days, ROW_NUMBER() OVER (ORDER BY days DESC, medicine_key) AS rn, SUM(days) OVER () AS total_days FROM per_medicine
)
SELECT MAX(total_days)                                                                    AS total_stockout_days,
       SUM(days) FILTER (WHERE rn <= 10)                                                  AS top_10_medicine_days,
       ROUND(100.0 * SUM(days) FILTER (WHERE rn <= 10) / MAX(total_days), 2)              AS top_10_share_pct,
       SUM(days) FILTER (WHERE rn <= 20)                                                  AS top_20_medicine_days,
       ROUND(100.0 * SUM(days) FILTER (WHERE rn <= 20) / MAX(total_days), 2)              AS top_20_share_pct,
       ROUND(100.0 * 10 / COUNT(*), 2)                                                    AS top_10_share_of_medicines_pct,
       ROUND(100.0 * 20 / COUNT(*), 2)                                                    AS top_20_share_of_medicines_pct
FROM ranked;

-- @name: Stockout days by month
SELECT d.year, d.month, COUNT(*) FILTER (WHERE i.closing_quantity = 0) AS stockout_days,
       ROUND(100.0 * COUNT(*) FILTER (WHERE i.closing_quantity = 0) / COUNT(*), 3) AS stockout_rate_pct
FROM warehouse.fact_inventory i
JOIN warehouse.dim_date d ON d.date_key = i.date_key
GROUP BY d.year, d.month
ORDER BY d.year, d.month;

-- @name: Do stockouts hit fast movers? (stockout days by mover class)
SELECT mp.mover_class, COUNT(DISTINCT so.medicine_key) AS medicines, SUM(so.stockout_days) AS stockout_days,
       ROUND(100.0 * SUM(so.stockout_days) / SUM(SUM(so.stockout_days)) OVER (), 2) AS share_of_stockout_days_pct,
       ROUND(100.0 * SUM(so.stockout_days) / SUM(so.days_observed), 3) AS stockout_rate_pct
FROM warehouse.v_stockout_summary so
JOIN warehouse.v_medicine_performance mp ON mp.medicine_key = so.medicine_key
GROUP BY mp.mover_class
ORDER BY CASE mp.mover_class WHEN 'FAST' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END;
