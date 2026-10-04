-- MedStock: sample OLAP queries over the star schema (schema "warehouse").
-- They demonstrate slice / dice / roll-up / drill-down with ROLLUP and GROUPING SETS. Not the full analytics layer.
-- Run in psql:  psql -h localhost -p 5433 -U medstock -d medstock -f sql/olap_examples.sql
-- (Statements are separated by semicolons: keep semicolons out of comments and strings.)

-- ============================================================================
-- 1. TIME ANALYSIS (fact_sales x dim_date)
-- ============================================================================

-- 1a. Revenue by year
SELECT d.year, COUNT(DISTINCT s.transaction_id) AS transactions, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.year
ORDER BY d.year;

-- 1b. Revenue by quarter
SELECT d.year, d.quarter, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.year, d.quarter
ORDER BY d.year, d.quarter;

-- 1c. Revenue by month, with a growth percentage vs the same month a year earlier (window function)
SELECT year, month, month_name, revenue,
       ROUND(100.0 * (revenue - LAG(revenue, 12) OVER (ORDER BY year, month)) / NULLIF(LAG(revenue, 12) OVER (ORDER BY year, month), 0), 1) AS yoy_pct
FROM (
    SELECT d.year, d.month, d.month_name, SUM(s.total_amount) AS revenue
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_date d ON d.date_key = s.date_key
    GROUP BY d.year, d.month, d.month_name
) m
ORDER BY year, month;

-- 1d. Revenue by day (the last 14 days of the calendar)
SELECT d.full_date, d.day_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
WHERE d.full_date > (SELECT MAX(full_date) FROM warehouse.dim_date) - 14
GROUP BY d.full_date, d.day_name
ORDER BY d.full_date;

-- 1e. Roll-up across the time hierarchy: year > quarter > month, with subtotals and a grand total
SELECT COALESCE(d.year::text, 'ALL YEARS') AS year,
       COALESCE(d.quarter::text, 'all') AS quarter,
       COALESCE(d.month::text, 'all') AS month,
       SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY ROLLUP (d.year, d.quarter, d.month)
ORDER BY GROUPING(d.year), d.year, GROUPING(d.quarter), d.quarter, GROUPING(d.month), d.month;

-- 1f. Weekday vs weekend (dice on a dim_date attribute)
SELECT d.is_weekend, SUM(s.quantity) AS units, ROUND(SUM(s.total_amount) / COUNT(DISTINCT d.date_key), 2) AS revenue_per_day
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.is_weekend;

-- ============================================================================
-- 2. CATEGORY DRILL-DOWN: Year > Category > Medicine
-- ============================================================================

-- 2a. Year x category (top of the hierarchy)
SELECT d.year, c.category_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d     ON d.date_key = s.date_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY d.year, c.category_name
ORDER BY d.year, revenue DESC;

-- 2a-i. Revenue by category (all years)
SELECT c.category_name, COUNT(DISTINCT m.medicine_key) AS medicines, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue,
       ROUND(100.0 * SUM(s.total_amount) / SUM(SUM(s.total_amount)) OVER (), 1) AS revenue_share_pct
FROM warehouse.fact_sales s
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY c.category_name
ORDER BY revenue DESC;

-- 2a-ii. Top 10 medicines by revenue (with category and share of total)
SELECT m.medicine_name, c.category_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue,
       ROUND(100.0 * SUM(s.total_amount) / SUM(SUM(s.total_amount)) OVER (), 2) AS revenue_share_pct
FROM warehouse.fact_sales s
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY m.medicine_name, c.category_name
ORDER BY revenue DESC
LIMIT 10;

-- 2b. Drill down into one cell (2026, Respiratory): medicines, with ROLLUP subtotal rows
SELECT COALESCE(c.category_name, 'ALL') AS category, COALESCE(m.medicine_name, 'subtotal') AS medicine,
       SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d     ON d.date_key = s.date_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE d.year = 2026 AND c.category_name = 'Respiratory'
GROUP BY ROLLUP (c.category_name, m.medicine_name)
ORDER BY GROUPING(m.medicine_name), revenue DESC
LIMIT 12;

-- ============================================================================
-- 3. BRANCH ANALYSIS: Branch > Category > Medicine
-- ============================================================================

-- 3a. Branch x category revenue cross-tab (dice)
SELECT b.branch_name,
       SUM(s.total_amount) FILTER (WHERE c.category_name = 'Respiratory')     AS respiratory,
       SUM(s.total_amount) FILTER (WHERE c.category_name = 'Cardiovascular')  AS cardiovascular,
       SUM(s.total_amount) FILTER (WHERE c.category_name = 'Antidiabetic')    AS antidiabetic,
       SUM(s.total_amount) AS all_categories
FROM warehouse.fact_sales s
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY b.branch_name
ORDER BY all_categories DESC;

-- 3b. Roll-up Branch > Category (subtotal per branch and grand total)
SELECT COALESCE(b.branch_name, 'ALL BRANCHES') AS branch, COALESCE(c.category_name, 'all categories') AS category,
       SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY ROLLUP (b.branch_name, c.category_name)
ORDER BY GROUPING(b.branch_name), b.branch_name, GROUPING(c.category_name), revenue DESC;

-- 3c. Drill down: top medicines of one branch within one category
SELECT b.branch_name, c.category_name, m.medicine_name, SUM(s.quantity) AS units, SUM(s.total_amount) AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_branch b   ON b.branch_key = s.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE b.branch_id = 'BR001' AND c.category_name = 'Respiratory'
GROUP BY b.branch_name, c.category_name, m.medicine_name
ORDER BY revenue DESC
LIMIT 10;

-- ============================================================================
-- 4. INVENTORY (fact_inventory: semi-additive)
-- ============================================================================

-- 4a. Current stock (last calendar day): Branch > Medicine, top 15 by units, with units valued at cost
SELECT b.branch_name, m.medicine_name, i.closing_quantity AS current_units, i.closing_value_at_cost AS value_at_cost
FROM warehouse.fact_inventory i
JOIN warehouse.dim_branch b   ON b.branch_key = i.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
WHERE i.date_key = (SELECT MAX(date_key) FROM warehouse.dim_date)
ORDER BY i.closing_quantity DESC
LIMIT 15;

-- 4b. Current stock rolled up: Branch > Category (valid to SUM across branches and categories ON ONE DATE)
SELECT COALESCE(b.branch_name, 'ALL BRANCHES') AS branch, COALESCE(c.category_name, 'all categories') AS category,
       SUM(i.closing_quantity) AS current_units, SUM(i.closing_value_at_cost) AS value_at_cost
FROM warehouse.fact_inventory i
JOIN warehouse.dim_branch b   ON b.branch_key = i.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE i.date_key = (SELECT MAX(date_key) FROM warehouse.dim_date)
GROUP BY ROLLUP (b.branch_name, c.category_name)
ORDER BY GROUPING(b.branch_name), b.branch_name, GROUPING(c.category_name), current_units DESC;

-- 4c. Semi-additivity: stock over time uses the LAST day of each period (or an average), never SUM over days
SELECT me.year, me.month, SUM(i.closing_quantity) AS month_end_units, SUM(i.closing_value_at_cost) AS month_end_value
FROM (SELECT year, month, MAX(date_key) AS date_key FROM warehouse.dim_date GROUP BY year, month) me
JOIN warehouse.fact_inventory i ON i.date_key = me.date_key
GROUP BY me.year, me.month
ORDER BY me.year, me.month;

-- 4d. Stockout analysis: branch-medicine-days with zero stock, by branch and category
SELECT b.branch_name, c.category_name, COUNT(*) FILTER (WHERE i.closing_quantity = 0) AS stockout_days,
       ROUND(100.0 * COUNT(*) FILTER (WHERE i.closing_quantity = 0) / COUNT(*), 2) AS stockout_pct
FROM warehouse.fact_inventory i
JOIN warehouse.dim_branch b   ON b.branch_key = i.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY b.branch_name, c.category_name
ORDER BY stockout_pct DESC
LIMIT 10;

-- ============================================================================
-- 5. SUPPLIER: Supplier > Medicine > Purchase value (fact_purchase)
-- ============================================================================

-- 5a. Purchase value per supplier
SELECT sp.supplier_name, sp.city, COUNT(*) AS delivery_lines, SUM(p.quantity) AS units, SUM(p.total_cost) AS purchase_value
FROM warehouse.fact_purchase p
JOIN warehouse.dim_supplier sp ON sp.supplier_key = p.supplier_key
GROUP BY sp.supplier_name, sp.city
ORDER BY purchase_value DESC
LIMIT 10;

-- 5b. Drill down for the largest supplier: medicines with a subtotal (ROLLUP)
SELECT COALESCE(sp.supplier_name, 'ALL') AS supplier, COALESCE(m.medicine_name, 'subtotal') AS medicine,
       SUM(p.quantity) AS units, SUM(p.total_cost) AS purchase_value
FROM warehouse.fact_purchase p
JOIN warehouse.dim_supplier sp ON sp.supplier_key = p.supplier_key
JOIN warehouse.dim_medicine m  ON m.medicine_key = p.medicine_key
WHERE sp.supplier_key = (SELECT supplier_key FROM warehouse.fact_purchase GROUP BY supplier_key ORDER BY SUM(total_cost) DESC LIMIT 1)
GROUP BY ROLLUP (sp.supplier_name, m.medicine_name)
ORDER BY GROUPING(m.medicine_name), purchase_value DESC
LIMIT 12;

-- ============================================================================
-- 6. EXPIRY RISK: Branch > Category > Medicine (fact_purchase + fact_sales + dim_batch)
-- A batch lot at a branch is at risk when it expires within 180 days of the last calendar day and its remaining
-- units exceed what the branch is expected to sell before expiry (trailing 90-day sales rate of that medicine).
-- ============================================================================

-- 6a. Roll-up of expiry-risk stock (units and value at cost)
WITH snap AS (SELECT MAX(full_date) AS d FROM warehouse.dim_date),
recv AS (SELECT branch_key, batch_key, SUM(quantity) AS q FROM warehouse.fact_purchase GROUP BY branch_key, batch_key),
sold AS (SELECT branch_key, batch_key, SUM(quantity) AS q FROM warehouse.fact_sales GROUP BY branch_key, batch_key),
velocity AS (
    SELECT s.branch_key, s.medicine_key, SUM(s.quantity) / 90.0 AS units_per_day
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_date d ON d.date_key = s.date_key
    CROSS JOIN snap
    WHERE d.full_date > snap.d - 90
    GROUP BY s.branch_key, s.medicine_key
),
risk AS (
    SELECT r.branch_key, b.medicine_key, b.batch_id, b.expiry_date, b.purchase_price,
           r.q - COALESCE(s.q, 0) AS remaining, (b.expiry_date - snap.d) AS days_to_expiry,
           COALESCE(v.units_per_day, 0) AS units_per_day
    FROM recv r
    LEFT JOIN sold s USING (branch_key, batch_key)
    JOIN warehouse.dim_batch b ON b.batch_key = r.batch_key
    LEFT JOIN velocity v ON v.branch_key = r.branch_key AND v.medicine_key = b.medicine_key
    CROSS JOIN snap
    WHERE b.expiry_date > snap.d AND b.expiry_date <= snap.d + 180
)
SELECT COALESCE(br.branch_name, 'ALL BRANCHES') AS branch, COALESCE(c.category_name, 'all categories') AS category,
       COALESCE(m.medicine_name, 'subtotal') AS medicine,
       COUNT(*) AS batch_lots, SUM(k.remaining) AS units_at_risk, ROUND(SUM(k.remaining * k.purchase_price), 2) AS value_at_risk
FROM risk k
JOIN warehouse.dim_branch br   ON br.branch_key = k.branch_key
JOIN warehouse.dim_medicine m  ON m.medicine_key = k.medicine_key
JOIN warehouse.dim_category c  ON c.category_key = m.category_key
WHERE k.remaining > 0 AND k.remaining > k.units_per_day * k.days_to_expiry
GROUP BY ROLLUP (br.branch_name, c.category_name, m.medicine_name)
ORDER BY GROUPING(br.branch_name), br.branch_name, GROUPING(c.category_name), c.category_name, GROUPING(m.medicine_name), value_at_risk DESC
LIMIT 25;

-- 6b. Actual write-offs from the inventory snapshot: expired units and their cost, by category
SELECT c.category_name, SUM(i.expired_quantity) AS expired_units,
       COUNT(*) FILTER (WHERE i.expired_quantity > 0) AS write_off_events
FROM warehouse.fact_inventory i
JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY c.category_name
ORDER BY expired_units DESC;
