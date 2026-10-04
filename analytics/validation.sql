-- Analytics reconciliation: every analytical layer must tie back to the warehouse facts.
-- Each statement returns rows (check_name, actual, expected, status) with status PASS / FAIL / INFO. Run by: python -m analytics.run
-- (or psql -h localhost -p 5433 -U medstock -d medstock -f analytics/validation.sql, after the views exist).
-- Statements end with semicolons, so keep semicolons out of comments and strings.

-- @name: sales totals
SELECT 'sales: view monthly revenue = fact_sales revenue' AS check_name,
       (SELECT SUM(revenue) FROM warehouse.v_monthly_sales)::text AS actual,
       (SELECT SUM(total_amount) FROM warehouse.fact_sales)::text AS expected,
       CASE WHEN (SELECT SUM(revenue) FROM warehouse.v_monthly_sales) = (SELECT SUM(total_amount) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END AS status
UNION ALL
SELECT 'sales: view monthly units = fact_sales units',
       (SELECT SUM(units) FROM warehouse.v_monthly_sales)::text, (SELECT SUM(quantity) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(units) FROM warehouse.v_monthly_sales) = (SELECT SUM(quantity) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'sales: view monthly transactions = distinct transactions',
       (SELECT SUM(transactions) FROM warehouse.v_monthly_sales)::text, (SELECT COUNT(DISTINCT transaction_id) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(transactions) FROM warehouse.v_monthly_sales) = (SELECT COUNT(DISTINCT transaction_id) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'sales: yearly revenue = monthly revenue',
       (SELECT SUM(r) FROM (SELECT SUM(s.total_amount) AS r FROM warehouse.fact_sales s JOIN warehouse.dim_date d USING (date_key) GROUP BY d.year) y)::text,
       (SELECT SUM(revenue) FROM warehouse.v_monthly_sales)::text,
       CASE WHEN (SELECT SUM(r) FROM (SELECT SUM(s.total_amount) AS r FROM warehouse.fact_sales s JOIN warehouse.dim_date d USING (date_key) GROUP BY d.year) y)
               = (SELECT SUM(revenue) FROM warehouse.v_monthly_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'sales: weekly (ISO) revenue = total revenue',
       (SELECT SUM(r) FROM (SELECT SUM(s.total_amount) AS r FROM warehouse.fact_sales s JOIN warehouse.dim_date d USING (date_key)
                            GROUP BY EXTRACT(isoyear FROM d.full_date), d.week) w)::text,
       (SELECT SUM(total_amount) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(r) FROM (SELECT SUM(s.total_amount) AS r FROM warehouse.fact_sales s JOIN warehouse.dim_date d USING (date_key)
                            GROUP BY EXTRACT(isoyear FROM d.full_date), d.week) w) = (SELECT SUM(total_amount) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'sales: medicine performance revenue = fact_sales revenue',
       (SELECT SUM(revenue) FROM warehouse.v_medicine_performance)::text, (SELECT SUM(total_amount) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(revenue) FROM warehouse.v_medicine_performance) = (SELECT SUM(total_amount) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'sales: medicine performance units = fact_sales units',
       (SELECT SUM(units) FROM warehouse.v_medicine_performance)::text, (SELECT SUM(quantity) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(units) FROM warehouse.v_medicine_performance) = (SELECT SUM(quantity) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END;

-- @name: category and branch totals
SELECT 'category totals = overall revenue' AS check_name,
       (SELECT SUM(r) FROM (SELECT SUM(s.total_amount) AS r FROM warehouse.fact_sales s JOIN warehouse.dim_medicine m USING (medicine_key)
                            JOIN warehouse.dim_category c USING (category_key) GROUP BY c.category_name) x)::text AS actual,
       (SELECT SUM(total_amount) FROM warehouse.fact_sales)::text AS expected,
       CASE WHEN (SELECT SUM(r) FROM (SELECT SUM(s.total_amount) AS r FROM warehouse.fact_sales s JOIN warehouse.dim_medicine m USING (medicine_key)
                            JOIN warehouse.dim_category c USING (category_key) GROUP BY c.category_name) x) = (SELECT SUM(total_amount) FROM warehouse.fact_sales)
            THEN 'PASS' ELSE 'FAIL' END AS status
UNION ALL
SELECT 'branch totals = overall revenue',
       (SELECT SUM(revenue) FROM warehouse.v_branch_performance)::text, (SELECT SUM(total_amount) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(revenue) FROM warehouse.v_branch_performance) = (SELECT SUM(total_amount) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'branch totals = overall units',
       (SELECT SUM(units) FROM warehouse.v_branch_performance)::text, (SELECT SUM(quantity) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(units) FROM warehouse.v_branch_performance) = (SELECT SUM(quantity) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'branch totals = overall transactions',
       (SELECT SUM(transactions) FROM warehouse.v_branch_performance)::text, (SELECT COUNT(DISTINCT transaction_id) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(transactions) FROM warehouse.v_branch_performance) = (SELECT COUNT(DISTINCT transaction_id) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'branch revenue shares add to 100',
       (SELECT SUM(revenue_share_pct) FROM warehouse.v_branch_performance)::text, '100',
       CASE WHEN ABS((SELECT SUM(revenue_share_pct) FROM warehouse.v_branch_performance) - 100) < 0.05 THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'mover classes partition all medicines',
       (SELECT COUNT(*) FROM warehouse.v_medicine_performance WHERE mover_class IN ('FAST', 'MEDIUM', 'SLOW'))::text,
       (SELECT COUNT(*) FROM warehouse.dim_medicine)::text,
       CASE WHEN (SELECT COUNT(*) FROM warehouse.v_medicine_performance WHERE mover_class IN ('FAST', 'MEDIUM', 'SLOW')) = (SELECT COUNT(*) FROM warehouse.dim_medicine) THEN 'PASS' ELSE 'FAIL' END;

-- @name: inventory reconciliation
SELECT 'inventory: current units = fact_inventory on the latest date' AS check_name,
       (SELECT SUM(stock_units) FROM warehouse.v_current_inventory)::text AS actual,
       (SELECT SUM(closing_quantity) FROM warehouse.fact_inventory WHERE date_key = (SELECT MAX(date_key) FROM warehouse.fact_inventory))::text AS expected,
       CASE WHEN (SELECT SUM(stock_units) FROM warehouse.v_current_inventory)
               = (SELECT SUM(closing_quantity) FROM warehouse.fact_inventory WHERE date_key = (SELECT MAX(date_key) FROM warehouse.fact_inventory)) THEN 'PASS' ELSE 'FAIL' END AS status
UNION ALL
SELECT 'inventory: current units = purchases - sales - expired',
       (SELECT SUM(stock_units) FROM warehouse.v_current_inventory)::text,
       ((SELECT SUM(quantity) FROM warehouse.fact_purchase) - (SELECT SUM(quantity) FROM warehouse.fact_sales)
        - (SELECT SUM(expired_quantity) FROM warehouse.fact_inventory))::text,
       CASE WHEN (SELECT SUM(stock_units) FROM warehouse.v_current_inventory)
               = (SELECT SUM(quantity) FROM warehouse.fact_purchase) - (SELECT SUM(quantity) FROM warehouse.fact_sales)
                 - (SELECT SUM(expired_quantity) FROM warehouse.fact_inventory) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'inventory: stock status covers every branch-medicine pair',
       (SELECT COUNT(*) FROM warehouse.v_current_inventory WHERE stock_status IN ('OUT OF STOCK', 'LOW STOCK', 'NORMAL', 'OVERSTOCK'))::text,
       ((SELECT COUNT(*) FROM warehouse.dim_branch) * (SELECT COUNT(*) FROM warehouse.dim_medicine))::text,
       CASE WHEN (SELECT COUNT(*) FROM warehouse.v_current_inventory WHERE stock_status IN ('OUT OF STOCK', 'LOW STOCK', 'NORMAL', 'OVERSTOCK'))
               = (SELECT COUNT(*) FROM warehouse.dim_branch) * (SELECT COUNT(*) FROM warehouse.dim_medicine) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'inventory: month-end units for the last month = current units',
       (SELECT SUM(closing_quantity) FROM warehouse.fact_inventory WHERE date_key = (SELECT MAX(date_key) FROM warehouse.dim_date WHERE year = (SELECT MAX(year) FROM warehouse.dim_date) AND month = 12))::text,
       (SELECT SUM(stock_units) FROM warehouse.v_current_inventory)::text,
       CASE WHEN (SELECT SUM(closing_quantity) FROM warehouse.fact_inventory WHERE date_key = (SELECT MAX(date_key) FROM warehouse.dim_date WHERE year = (SELECT MAX(year) FROM warehouse.dim_date) AND month = 12))
               = (SELECT SUM(stock_units) FROM warehouse.v_current_inventory) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'inventory: COGS = purchase cost - closing value - expired value (batch-cost identity)',
       (SELECT ROUND(SUM(s.quantity * b.purchase_price), 2) FROM warehouse.fact_sales s JOIN warehouse.dim_batch b USING (batch_key))::text,
       ((SELECT ROUND(SUM(total_cost), 2) FROM warehouse.fact_purchase)
        - (SELECT ROUND(SUM(stock_value_at_cost), 2) FROM warehouse.v_current_inventory)
        - (SELECT ROUND(SUM(cost_value), 2) FROM warehouse.v_expiry_risk WHERE is_expired))::text,
       CASE WHEN (SELECT ROUND(SUM(s.quantity * b.purchase_price), 2) FROM warehouse.fact_sales s JOIN warehouse.dim_batch b USING (batch_key))
               = (SELECT ROUND(SUM(total_cost), 2) FROM warehouse.fact_purchase)
                 - (SELECT ROUND(SUM(stock_value_at_cost), 2) FROM warehouse.v_current_inventory)
                 - (SELECT ROUND(SUM(cost_value), 2) FROM warehouse.v_expiry_risk WHERE is_expired) THEN 'PASS' ELSE 'FAIL' END;

-- @name: stockout reconciliation
SELECT 'stockouts: view stockout days = fact_inventory zero-stock days' AS check_name,
       (SELECT SUM(stockout_days) FROM warehouse.v_stockout_summary)::text AS actual,
       (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0)::text AS expected,
       CASE WHEN (SELECT SUM(stockout_days) FROM warehouse.v_stockout_summary) = (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0) THEN 'PASS' ELSE 'FAIL' END AS status
UNION ALL
SELECT 'stockouts: by-branch days = total',
       (SELECT SUM(d) FROM (SELECT SUM(stockout_days) AS d FROM warehouse.v_stockout_summary GROUP BY branch_name) x)::text,
       (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0)::text,
       CASE WHEN (SELECT SUM(d) FROM (SELECT SUM(stockout_days) AS d FROM warehouse.v_stockout_summary GROUP BY branch_name) x) = (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'stockouts: by-category days = total',
       (SELECT SUM(d) FROM (SELECT SUM(stockout_days) AS d FROM warehouse.v_stockout_summary GROUP BY category_name) x)::text,
       (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0)::text,
       CASE WHEN (SELECT SUM(d) FROM (SELECT SUM(stockout_days) AS d FROM warehouse.v_stockout_summary GROUP BY category_name) x) = (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'stockouts: out-of-stock items now = zero-stock rows on the latest date',
       (SELECT COUNT(*) FROM warehouse.v_current_inventory WHERE stock_status = 'OUT OF STOCK')::text,
       (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0 AND date_key = (SELECT MAX(date_key) FROM warehouse.fact_inventory))::text,
       CASE WHEN (SELECT COUNT(*) FROM warehouse.v_current_inventory WHERE stock_status = 'OUT OF STOCK')
               = (SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_quantity = 0 AND date_key = (SELECT MAX(date_key) FROM warehouse.fact_inventory)) THEN 'PASS' ELSE 'FAIL' END;

-- @name: expiry reconciliation
SELECT 'expiry: expired units = fact_inventory expired_quantity' AS check_name,
       (SELECT COALESCE(SUM(remaining_units), 0) FROM warehouse.v_expiry_risk WHERE is_expired)::text AS actual,
       (SELECT SUM(expired_quantity) FROM warehouse.fact_inventory)::text AS expected,
       CASE WHEN (SELECT COALESCE(SUM(remaining_units), 0) FROM warehouse.v_expiry_risk WHERE is_expired) = (SELECT SUM(expired_quantity) FROM warehouse.fact_inventory) THEN 'PASS' ELSE 'FAIL' END AS status
UNION ALL
SELECT 'expiry: live-lot units = current inventory units',
       (SELECT SUM(remaining_units) FROM warehouse.v_expiry_risk WHERE NOT is_expired)::text,
       (SELECT SUM(stock_units) FROM warehouse.v_current_inventory)::text,
       CASE WHEN (SELECT SUM(remaining_units) FROM warehouse.v_expiry_risk WHERE NOT is_expired) = (SELECT SUM(stock_units) FROM warehouse.v_current_inventory) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'expiry: live-lot cost value = current inventory value',
       (SELECT ROUND(SUM(cost_value), 2) FROM warehouse.v_expiry_risk WHERE NOT is_expired)::text,
       (SELECT ROUND(SUM(stock_value_at_cost), 2) FROM warehouse.v_current_inventory)::text,
       CASE WHEN (SELECT ROUND(SUM(cost_value), 2) FROM warehouse.v_expiry_risk WHERE NOT is_expired) = (SELECT ROUND(SUM(stock_value_at_cost), 2) FROM warehouse.v_current_inventory) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'expiry: risk classes cover every lot',
       (SELECT COUNT(*) FROM warehouse.v_expiry_risk WHERE risk_class IN ('EXPIRED', 'CRITICAL', 'HIGH', 'MEDIUM', 'SAFE'))::text,
       (SELECT COUNT(*) FROM warehouse.v_expiry_risk)::text,
       CASE WHEN (SELECT COUNT(*) FROM warehouse.v_expiry_risk WHERE risk_class IN ('EXPIRED', 'CRITICAL', 'HIGH', 'MEDIUM', 'SAFE')) = (SELECT COUNT(*) FROM warehouse.v_expiry_risk) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'expiry: projected unsold never exceeds remaining units',
       (SELECT COUNT(*) FROM warehouse.v_expiry_risk WHERE projected_unsold_units > remaining_units + 0.05)::text, '0',
       CASE WHEN (SELECT COUNT(*) FROM warehouse.v_expiry_risk WHERE projected_unsold_units > remaining_units + 0.05) = 0 THEN 'PASS' ELSE 'FAIL' END;

-- @name: purchase reconciliation
SELECT 'purchases: supplier totals = fact_purchase cost' AS check_name,
       (SELECT SUM(v) FROM (SELECT SUM(total_cost) AS v FROM warehouse.fact_purchase GROUP BY supplier_key) x)::text AS actual,
       (SELECT SUM(total_cost) FROM warehouse.fact_purchase)::text AS expected,
       CASE WHEN (SELECT SUM(v) FROM (SELECT SUM(total_cost) AS v FROM warehouse.fact_purchase GROUP BY supplier_key) x) = (SELECT SUM(total_cost) FROM warehouse.fact_purchase) THEN 'PASS' ELSE 'FAIL' END AS status
UNION ALL
SELECT 'purchases: category totals = fact_purchase cost',
       (SELECT SUM(v) FROM (SELECT SUM(p.total_cost) AS v FROM warehouse.fact_purchase p JOIN warehouse.dim_medicine m USING (medicine_key) GROUP BY m.category_key) x)::text,
       (SELECT SUM(total_cost) FROM warehouse.fact_purchase)::text,
       CASE WHEN (SELECT SUM(v) FROM (SELECT SUM(p.total_cost) AS v FROM warehouse.fact_purchase p JOIN warehouse.dim_medicine m USING (medicine_key) GROUP BY m.category_key) x) = (SELECT SUM(total_cost) FROM warehouse.fact_purchase) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'purchases: monthly totals = fact_purchase cost',
       (SELECT SUM(v) FROM (SELECT SUM(p.total_cost) AS v FROM warehouse.fact_purchase p JOIN warehouse.dim_date d USING (date_key) GROUP BY d.year, d.month) x)::text,
       (SELECT SUM(total_cost) FROM warehouse.fact_purchase)::text,
       CASE WHEN (SELECT SUM(v) FROM (SELECT SUM(p.total_cost) AS v FROM warehouse.fact_purchase p JOIN warehouse.dim_date d USING (date_key) GROUP BY d.year, d.month) x) = (SELECT SUM(total_cost) FROM warehouse.fact_purchase) THEN 'PASS' ELSE 'FAIL' END;

-- @name: demand and seasonality reconciliation
SELECT 'demand: v_demand_stats units = fact_sales units' AS check_name,
       (SELECT SUM(total_units) FROM warehouse.v_demand_stats)::text AS actual,
       (SELECT SUM(quantity) FROM warehouse.fact_sales)::text AS expected,
       CASE WHEN (SELECT SUM(total_units) FROM warehouse.v_demand_stats) = (SELECT SUM(quantity) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END AS status
UNION ALL
SELECT 'demand: sales days + zero days = calendar days for every pair',
       (SELECT COUNT(*) FROM warehouse.v_demand_stats WHERE sales_days + zero_sales_days <> (SELECT COUNT(*) FROM warehouse.dim_date))::text, '0',
       CASE WHEN (SELECT COUNT(*) FROM warehouse.v_demand_stats WHERE sales_days + zero_sales_days <> (SELECT COUNT(*) FROM warehouse.dim_date)) = 0 THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'demand: variability classes cover every pair',
       (SELECT COUNT(*) FROM warehouse.v_demand_stats WHERE variability_class IN ('STABLE', 'MODERATELY VARIABLE', 'HIGHLY VARIABLE', 'NO DEMAND'))::text,
       (SELECT COUNT(*) FROM warehouse.v_demand_stats)::text,
       CASE WHEN (SELECT COUNT(*) FROM warehouse.v_demand_stats WHERE variability_class IN ('STABLE', 'MODERATELY VARIABLE', 'HIGHLY VARIABLE', 'NO DEMAND')) = (SELECT COUNT(*) FROM warehouse.v_demand_stats) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'seasonality: category-month units = fact_sales units',
       (SELECT SUM(u) FROM (SELECT SUM(s.quantity) AS u FROM warehouse.fact_sales s JOIN warehouse.dim_date d USING (date_key)
                            JOIN warehouse.dim_medicine m USING (medicine_key) GROUP BY m.category_key, d.month) x)::text,
       (SELECT SUM(quantity) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(u) FROM (SELECT SUM(s.quantity) AS u FROM warehouse.fact_sales s JOIN warehouse.dim_date d USING (date_key)
                            JOIN warehouse.dim_medicine m USING (medicine_key) GROUP BY m.category_key, d.month) x) = (SELECT SUM(quantity) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'demand: weekday + weekend revenue = total revenue',
       (SELECT SUM(r) FROM (SELECT SUM(s.total_amount) AS r FROM warehouse.fact_sales s JOIN warehouse.dim_date d USING (date_key) GROUP BY d.is_weekend) x)::text,
       (SELECT SUM(total_amount) FROM warehouse.fact_sales)::text,
       CASE WHEN (SELECT SUM(r) FROM (SELECT SUM(s.total_amount) AS r FROM warehouse.fact_sales s JOIN warehouse.dim_date d USING (date_key) GROUP BY d.is_weekend) x) = (SELECT SUM(total_amount) FROM warehouse.fact_sales) THEN 'PASS' ELSE 'FAIL' END;

-- @name: reference values from the warehouse validation (information only)
SELECT 'reference: total revenue (warehouse validation reported 159205192.71)' AS check_name,
       (SELECT SUM(total_amount) FROM warehouse.fact_sales)::text AS actual, '159205192.71' AS expected,
       CASE WHEN (SELECT SUM(total_amount) FROM warehouse.fact_sales)::text = '159205192.71' THEN 'PASS' ELSE 'INFO' END AS status
UNION ALL
SELECT 'reference: total units (warehouse validation reported 1582353)',
       (SELECT SUM(quantity) FROM warehouse.fact_sales)::text, '1582353',
       CASE WHEN (SELECT SUM(quantity) FROM warehouse.fact_sales)::text = '1582353' THEN 'PASS' ELSE 'INFO' END;
