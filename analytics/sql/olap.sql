-- OLAP operations on the MedStock star schema: roll-up, drill-down, slice, dice, pivot (and CUBE). Run with: python -m analytics.run --file olap
-- Complements sql/olap_examples.sql (the first basic examples). Hierarchies: Time Day > Month > Quarter > Year, Product Medicine > Category,
-- Geography Branch. Measures: units, revenue, transactions (additive).

-- ===========================================================================
-- ROLL-UP: aggregate to coarser levels of a hierarchy (ROLLUP adds subtotals and a grand total)
-- ===========================================================================

-- @name: Roll-up Day > Month > Quarter > Year with subtotal rows
-- GROUPING(year, quarter, month, day) is a bitmask: 0 = day row, 1 = month subtotal, 3 = quarter subtotal, 7 = year subtotal, 15 = grand total
SELECT CASE GROUPING(d.year, d.quarter, d.month, d.full_date)
            WHEN 0 THEN 'Day' WHEN 1 THEN 'MONTH SUBTOTAL' WHEN 3 THEN 'QUARTER SUBTOTAL' WHEN 7 THEN 'YEAR SUBTOTAL' ELSE 'GRAND TOTAL' END AS level,
       d.year, d.quarter, d.month, d.full_date AS day,
       SUM(s.quantity)                    AS units,
       SUM(s.total_amount)                AS revenue,
       COUNT(DISTINCT s.transaction_id)   AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY ROLLUP (d.year, d.quarter, d.month, d.full_date)
ORDER BY d.year NULLS LAST, d.quarter NULLS LAST, d.month NULLS LAST, d.full_date NULLS LAST;

-- @name: Roll-up Category > Medicine with category subtotals (top categories)
SELECT CASE GROUPING(c.category_name, m.medicine_name) WHEN 0 THEN 'Medicine' WHEN 1 THEN 'CATEGORY SUBTOTAL' ELSE 'GRAND TOTAL' END AS level,
       c.category_name, m.medicine_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE c.category_name IN ('Respiratory', 'Dermatological')
GROUP BY ROLLUP (c.category_name, m.medicine_name)
ORDER BY c.category_name NULLS LAST, GROUPING(m.medicine_name), revenue DESC
LIMIT 30;

-- ===========================================================================
-- DRILL-DOWN: move from a coarse level to a finer level inside one member
-- ===========================================================================

-- @name: Drill-down time 1 of 4: Year
SELECT d.year, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.year
ORDER BY d.year;

-- @name: Drill-down time 2 of 4: Quarters of 2026
SELECT d.year, d.quarter, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
WHERE d.year = 2026
GROUP BY d.year, d.quarter
ORDER BY d.quarter;

-- @name: Drill-down time 3 of 4: Months of 2026 Q2
SELECT d.year, d.quarter, d.month, d.month_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
WHERE d.year = 2026 AND d.quarter = 2
GROUP BY d.year, d.quarter, d.month, d.month_name
ORDER BY d.month;

-- @name: Drill-down time 4 of 4: Days of May 2026
SELECT d.full_date, d.day_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
WHERE d.year = 2026 AND d.month = 5
GROUP BY d.full_date, d.day_name
ORDER BY d.full_date;

-- @name: Drill-down product 1 of 2: Categories
SELECT c.category_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY c.category_name
ORDER BY revenue DESC;

-- @name: Drill-down product 2 of 2: Medicines of the Respiratory category
SELECT m.medicine_name, m.dosage_form, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE c.category_name = 'Respiratory'
GROUP BY m.medicine_key, m.medicine_name, m.dosage_form
ORDER BY revenue DESC
LIMIT 15;

-- @name: Drill-down geography 1 of 3: Branches
SELECT b.branch_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_branch b ON b.branch_key = s.branch_key
GROUP BY b.branch_name
ORDER BY revenue DESC;

-- @name: Drill-down geography 2 of 3: Categories within branch BR001
SELECT b.branch_name, c.category_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE b.branch_id = 'BR001'
GROUP BY b.branch_name, c.category_name
ORDER BY revenue DESC;

-- @name: Drill-down geography 3 of 3: Medicines of Respiratory within branch BR001
SELECT b.branch_name, c.category_name, m.medicine_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE b.branch_id = 'BR001' AND c.category_name = 'Respiratory'
GROUP BY b.branch_name, c.category_name, m.medicine_name
ORDER BY revenue DESC
LIMIT 10;

-- ===========================================================================
-- SLICE: fix ONE dimension member (here Year = 2026) and look at the remaining dimensions
-- ===========================================================================

-- @name: Slice: 2026 sales only (by category)
SELECT c.category_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d     ON d.date_key = s.date_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE d.year = 2026
GROUP BY c.category_name
ORDER BY revenue DESC;

-- ===========================================================================
-- DICE: restrict SEVERAL dimensions at once (Year = 2026, Category = Respiratory, Branch in BR001 or BR002)
-- ===========================================================================

-- @name: Dice: 2026 + Respiratory + BR001/BR002 (by branch)
SELECT b.branch_name, SUM(s.total_amount) AS revenue, SUM(s.quantity) AS units, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d     ON d.date_key = s.date_key
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE d.year = 2026 AND c.category_name = 'Respiratory' AND b.branch_id IN ('BR001', 'BR002')
GROUP BY b.branch_name
ORDER BY revenue DESC;

-- @name: Dice: 2026 + Respiratory + BR001/BR002 (by quarter and branch)
SELECT d.quarter, b.branch_name, SUM(s.total_amount) AS revenue, SUM(s.quantity) AS units, COUNT(DISTINCT s.transaction_id) AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d     ON d.date_key = s.date_key
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE d.year = 2026 AND c.category_name = 'Respiratory' AND b.branch_id IN ('BR001', 'BR002')
GROUP BY d.quarter, b.branch_name
ORDER BY d.quarter, b.branch_name;

-- ===========================================================================
-- PIVOT: rotate a dimension into columns (conditional aggregation with FILTER)
-- ===========================================================================

-- @name: Pivot: revenue by branch (rows) and year (columns)
SELECT b.branch_id, b.branch_name,
       SUM(s.total_amount) FILTER (WHERE d.year = 2025) AS revenue_2025,
       SUM(s.total_amount) FILTER (WHERE d.year = 2026) AS revenue_2026,
       ROUND(100.0 * (SUM(s.total_amount) FILTER (WHERE d.year = 2026) - SUM(s.total_amount) FILTER (WHERE d.year = 2025))
             / NULLIF(SUM(s.total_amount) FILTER (WHERE d.year = 2025), 0), 2) AS growth_pct,
       SUM(s.total_amount) AS total
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d   ON d.date_key = s.date_key
JOIN warehouse.dim_branch b ON b.branch_key = s.branch_key
GROUP BY b.branch_id, b.branch_name
ORDER BY b.branch_id;

-- @name: Pivot: revenue by category (rows) and branch (columns)
SELECT c.category_name,
       SUM(s.total_amount) FILTER (WHERE b.branch_id = 'BR001') AS br001,
       SUM(s.total_amount) FILTER (WHERE b.branch_id = 'BR002') AS br002,
       SUM(s.total_amount) FILTER (WHERE b.branch_id = 'BR003') AS br003,
       SUM(s.total_amount) FILTER (WHERE b.branch_id = 'BR004') AS br004,
       SUM(s.total_amount) FILTER (WHERE b.branch_id = 'BR005') AS br005,
       SUM(s.total_amount) AS all_branches
FROM warehouse.fact_sales s
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY c.category_name
ORDER BY all_branches DESC;

-- @name: Pivot: monthly revenue (rows) by year (columns)
SELECT d.month, d.month_name,
       SUM(s.total_amount) FILTER (WHERE d.year = 2025) AS revenue_2025,
       SUM(s.total_amount) FILTER (WHERE d.year = 2026) AS revenue_2026
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.month, d.month_name
ORDER BY d.month;

-- ===========================================================================
-- CUBE: subtotals for every combination of the listed dimensions
-- ===========================================================================

-- @name: Cube: revenue by branch x category x year-slice 2026 (all subtotal combinations)
SELECT COALESCE(b.branch_id, 'ALL')           AS branch,
       COALESCE(c.category_name, 'ALL')       AS category,
       SUM(s.total_amount)                    AS revenue,
       SUM(s.quantity)                        AS units,
       GROUPING(b.branch_id, c.category_name) AS grouping_level
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d     ON d.date_key = s.date_key
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE d.year = 2026 AND c.category_name IN ('Respiratory', 'Antihistamines', 'Vitamins')
GROUP BY CUBE (b.branch_id, c.category_name)
ORDER BY grouping_level, branch, category;
