-- Branch analytics (fact_sales, fact_inventory and the analytics views). Run with: python -m analytics.run --file branches
-- Stepwise Branch > Category > Medicine drill-down examples live in olap.sql.

-- @name: Branch performance
SELECT revenue_rank AS rank, branch_name, area, revenue, units, transactions, avg_transaction_value,
       avg_units_per_transaction, active_medicines, revenue_share_pct, unit_share_pct
FROM warehouse.v_branch_performance
ORDER BY revenue_rank;

-- @name: Branch x category revenue matrix (long form)
-- category_share_index = the branch's share of its own revenue in the category / the all-branch share. 1.00 = typical mix, above 1.00 = relative specialty.
WITH bc AS (
    SELECT s.branch_key, m.category_key, SUM(s.total_amount) AS revenue
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
    GROUP BY s.branch_key, m.category_key
),
shares AS (
    SELECT branch_key, category_key, revenue,
           revenue / SUM(revenue) OVER (PARTITION BY branch_key)   AS share_in_branch,
           SUM(revenue) OVER (PARTITION BY category_key) / SUM(revenue) OVER () AS share_overall
    FROM bc
)
SELECT b.branch_name, c.category_name, sh.revenue,
       ROUND(100.0 * sh.share_in_branch, 2)                         AS share_of_branch_revenue_pct,
       ROUND(sh.share_in_branch / sh.share_overall, 3)              AS category_share_index
FROM shares sh
JOIN warehouse.dim_branch b   ON b.branch_key = sh.branch_key
JOIN warehouse.dim_category c ON c.category_key = sh.category_key
ORDER BY b.branch_name, sh.revenue DESC;

-- @name: Branch > Category roll-up with subtotals
SELECT CASE WHEN GROUPING(b.branch_name) = 1 THEN 'ALL BRANCHES' ELSE b.branch_name END AS branch,
       CASE WHEN GROUPING(c.category_name) = 1 THEN 'all categories' ELSE c.category_name END AS category,
       SUM(s.quantity)      AS units,
       SUM(s.total_amount)  AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY ROLLUP (b.branch_name, c.category_name)
ORDER BY GROUPING(b.branch_name), b.branch_name, GROUPING(c.category_name), revenue DESC;

-- @name: Top 3 medicines per category in each branch (Branch > Category > Medicine)
WITH ranked AS (
    SELECT b.branch_name, c.category_name, m.medicine_name,
           SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue,
           ROW_NUMBER() OVER (PARTITION BY b.branch_name, c.category_name ORDER BY SUM(s.total_amount) DESC, m.medicine_name) AS rn
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
    JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
    JOIN warehouse.dim_category c ON c.category_key = m.category_key
    GROUP BY b.branch_name, c.category_name, m.medicine_name
)
SELECT branch_name, category_name, rn AS rank_in_category, medicine_name, units, revenue
FROM ranked
WHERE rn <= 3
ORDER BY branch_name, category_name, rn;

-- @name: Branch scorecard (sales, stock, stockouts, expiry)
-- Inventory figures are read on the snapshot date (latest day), never summed over time.
WITH inv AS (
    SELECT branch_key, SUM(stock_units) AS stock_units, SUM(stock_value_at_cost) AS stock_value,
           COUNT(*) FILTER (WHERE stock_status = 'OUT OF STOCK') AS out_of_stock_items,
           COUNT(*) FILTER (WHERE stock_status = 'LOW STOCK')    AS low_stock_items,
           COUNT(*) FILTER (WHERE stock_status = 'OVERSTOCK')    AS overstock_items
    FROM warehouse.v_current_inventory
    GROUP BY branch_key
),
so AS (
    SELECT branch_key, SUM(stockout_days) AS stockout_days, ROUND(100.0 * SUM(stockout_days) / SUM(days_observed), 2) AS stockout_rate_pct
    FROM warehouse.v_stockout_summary
    GROUP BY branch_key
),
ex AS (
    SELECT branch_key,
           SUM(cost_value) FILTER (WHERE is_expired) AS expired_value,
           SUM(value_at_risk) FILTER (WHERE NOT is_expired) AS expiry_value_at_risk
    FROM warehouse.v_expiry_risk
    GROUP BY branch_key
)
SELECT bp.branch_name, bp.revenue, bp.units,
       inv.stock_units, inv.stock_value, inv.out_of_stock_items, inv.low_stock_items, inv.overstock_items,
       so.stockout_days, so.stockout_rate_pct,
       ex.expired_value, ex.expiry_value_at_risk
FROM warehouse.v_branch_performance bp
JOIN inv ON inv.branch_key = bp.branch_key
JOIN so  ON so.branch_key = bp.branch_key
JOIN ex  ON ex.branch_key = bp.branch_key
ORDER BY bp.revenue DESC;
