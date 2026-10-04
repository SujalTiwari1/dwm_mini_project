-- MedStock warehouse validation queries.
-- Every statement returns rows (check_name, actual, expected, status) with status PASS / FAIL / INFO.
-- Run in psql:  psql -h localhost -p 5433 -U medstock -d medstock -f sql/validation.sql
-- The ETL (etl.validation.warehouse_checks) runs this same file and fails on any FAIL.
-- (Statements are separated by semicolons: keep semicolons out of comments and strings.)

-- 1-3. Sales: rows, quantity, revenue
SELECT '01 sales rows' AS check_name, COUNT(*)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_sales;

SELECT '02 sales quantity' AS check_name, SUM(quantity)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_sales;

SELECT '03 sales revenue (INR)' AS check_name, SUM(total_amount)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_sales;

-- 4-6. Purchases: rows, quantity, cost
SELECT '04 purchase rows' AS check_name, COUNT(*)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_purchase;

SELECT '05 purchase quantity' AS check_name, SUM(quantity)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_purchase;

SELECT '06 purchase cost (INR)' AS check_name, SUM(total_cost)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_purchase;

-- 7. Closing inventory on the last day (semi-additive: sum over branches and medicines on ONE date)
SELECT '07 closing inventory, last day (units)' AS check_name,
       SUM(closing_quantity)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_inventory
WHERE date_key = (SELECT MAX(date_key) FROM warehouse.dim_date);

-- 8. Reconciliation: opening + purchased - sold - expired = closing, in every row
SELECT '08 inventory reconciliation errors' AS check_name, COUNT(*)::text AS actual, '0' AS expected,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM warehouse.fact_inventory
WHERE opening_quantity + purchased_quantity - sold_quantity - expired_quantity <> closing_quantity;

-- 8b. Continuity: opening(t) = closing(t-1) for each branch/medicine
SELECT '08b opening <> previous closing' AS check_name, COUNT(*)::text AS actual, '0' AS expected,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM (
    SELECT opening_quantity,
           COALESCE(LAG(closing_quantity) OVER (PARTITION BY branch_key, medicine_key ORDER BY date_key), 0) AS prev_closing
    FROM warehouse.fact_inventory
) x
WHERE opening_quantity <> prev_closing;

-- 9. Negative inventory
SELECT '09 negative inventory rows' AS check_name, COUNT(*)::text AS actual, '0' AS expected,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM warehouse.fact_inventory
WHERE closing_quantity < 0 OR opening_quantity < 0;

-- 10. Sales on or after the batch expiry date
SELECT '10 sales on/after batch expiry' AS check_name, COUNT(*)::text AS actual, '0' AS expected,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d  ON d.date_key = s.date_key
JOIN warehouse.dim_batch b ON b.batch_key = s.batch_key
WHERE d.full_date >= b.expiry_date;

SELECT '10b purchases on/after batch expiry or before manufacture' AS check_name, COUNT(*)::text AS actual, '0' AS expected,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM warehouse.fact_purchase p
JOIN warehouse.dim_date d  ON d.date_key = p.date_key
JOIN warehouse.dim_batch b ON b.batch_key = p.batch_key
WHERE d.full_date >= b.expiry_date OR d.full_date <= b.manufacture_date;

-- 11. Orphan foreign keys (every fact key must resolve)
SELECT '11 orphan ' || fk AS check_name, n::text AS actual, '0' AS expected,
       CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM (
    SELECT 'fact_sales.date_key' AS fk, COUNT(*) AS n FROM warehouse.fact_sales f LEFT JOIN warehouse.dim_date d ON d.date_key = f.date_key WHERE d.date_key IS NULL
    UNION ALL SELECT 'fact_sales.medicine_key', COUNT(*) FROM warehouse.fact_sales f LEFT JOIN warehouse.dim_medicine d ON d.medicine_key = f.medicine_key WHERE d.medicine_key IS NULL
    UNION ALL SELECT 'fact_sales.branch_key', COUNT(*) FROM warehouse.fact_sales f LEFT JOIN warehouse.dim_branch d ON d.branch_key = f.branch_key WHERE d.branch_key IS NULL
    UNION ALL SELECT 'fact_sales.batch_key', COUNT(*) FROM warehouse.fact_sales f LEFT JOIN warehouse.dim_batch d ON d.batch_key = f.batch_key WHERE d.batch_key IS NULL
    UNION ALL SELECT 'fact_purchase.date_key', COUNT(*) FROM warehouse.fact_purchase f LEFT JOIN warehouse.dim_date d ON d.date_key = f.date_key WHERE d.date_key IS NULL
    UNION ALL SELECT 'fact_purchase.medicine_key', COUNT(*) FROM warehouse.fact_purchase f LEFT JOIN warehouse.dim_medicine d ON d.medicine_key = f.medicine_key WHERE d.medicine_key IS NULL
    UNION ALL SELECT 'fact_purchase.branch_key', COUNT(*) FROM warehouse.fact_purchase f LEFT JOIN warehouse.dim_branch d ON d.branch_key = f.branch_key WHERE d.branch_key IS NULL
    UNION ALL SELECT 'fact_purchase.supplier_key', COUNT(*) FROM warehouse.fact_purchase f LEFT JOIN warehouse.dim_supplier d ON d.supplier_key = f.supplier_key WHERE d.supplier_key IS NULL
    UNION ALL SELECT 'fact_purchase.batch_key', COUNT(*) FROM warehouse.fact_purchase f LEFT JOIN warehouse.dim_batch d ON d.batch_key = f.batch_key WHERE d.batch_key IS NULL
    UNION ALL SELECT 'fact_inventory.date_key', COUNT(*) FROM warehouse.fact_inventory f LEFT JOIN warehouse.dim_date d ON d.date_key = f.date_key WHERE d.date_key IS NULL
    UNION ALL SELECT 'fact_inventory.medicine_key', COUNT(*) FROM warehouse.fact_inventory f LEFT JOIN warehouse.dim_medicine d ON d.medicine_key = f.medicine_key WHERE d.medicine_key IS NULL
    UNION ALL SELECT 'fact_inventory.branch_key', COUNT(*) FROM warehouse.fact_inventory f LEFT JOIN warehouse.dim_branch d ON d.branch_key = f.branch_key WHERE d.branch_key IS NULL
    UNION ALL SELECT 'dim_medicine.category_key', COUNT(*) FROM warehouse.dim_medicine f LEFT JOIN warehouse.dim_category d ON d.category_key = f.category_key WHERE d.category_key IS NULL
    UNION ALL SELECT 'dim_batch.medicine_key', COUNT(*) FROM warehouse.dim_batch f LEFT JOIN warehouse.dim_medicine d ON d.medicine_key = f.medicine_key WHERE d.medicine_key IS NULL
    UNION ALL SELECT 'dim_batch.supplier_key', COUNT(*) FROM warehouse.dim_batch f LEFT JOIN warehouse.dim_supplier d ON d.supplier_key = f.supplier_key WHERE d.supplier_key IS NULL
) o;

-- 12. Duplicate natural / source keys
SELECT '12 duplicate ' || k AS check_name, n::text AS actual, '0' AS expected,
       CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM (
    SELECT 'category_id' AS k, COUNT(*) - COUNT(DISTINCT category_id) AS n FROM warehouse.dim_category
    UNION ALL SELECT 'medicine_id', COUNT(*) - COUNT(DISTINCT medicine_id) FROM warehouse.dim_medicine
    UNION ALL SELECT 'branch_id', COUNT(*) - COUNT(DISTINCT branch_id) FROM warehouse.dim_branch
    UNION ALL SELECT 'supplier_id', COUNT(*) - COUNT(DISTINCT supplier_id) FROM warehouse.dim_supplier
    UNION ALL SELECT 'batch_id', COUNT(*) - COUNT(DISTINCT batch_id) FROM warehouse.dim_batch
    UNION ALL SELECT 'purchase_id', COUNT(*) - COUNT(DISTINCT purchase_id) FROM warehouse.fact_purchase
    UNION ALL SELECT 'sales grain (transaction, medicine, batch)', COUNT(*) - COUNT(DISTINCT (transaction_id, medicine_key, batch_key)) FROM warehouse.fact_sales
) d;

-- 13. Date coverage: dim_date spans every fact date, with no gaps
SELECT '13 date coverage: fact dates outside dim_date or gaps' AS check_name,
       ((SELECT COUNT(*) FROM warehouse.fact_sales s LEFT JOIN warehouse.dim_date d USING (date_key) WHERE d.date_key IS NULL)
      + (SELECT (MAX(full_date) - MIN(full_date) + 1) - COUNT(*) FROM warehouse.dim_date))::text AS actual,
       '0' AS expected,
       CASE WHEN (SELECT COUNT(*) FROM warehouse.fact_sales s LEFT JOIN warehouse.dim_date d USING (date_key) WHERE d.date_key IS NULL)
               + (SELECT (MAX(full_date) - MIN(full_date) + 1) - COUNT(*) FROM warehouse.dim_date) = 0 THEN 'PASS' ELSE 'FAIL' END AS status;

SELECT '13b calendar span' AS check_name, MIN(full_date)::text || ' to ' || MAX(full_date)::text AS actual,
       'info' AS expected, 'INFO' AS status
FROM warehouse.dim_date;

-- 14. Coverage of branches, medicines, suppliers
SELECT '14 branch coverage (branches with sales / branches)' AS check_name,
       (SELECT COUNT(DISTINCT branch_key) FROM warehouse.fact_sales)::text || ' / ' || (SELECT COUNT(*) FROM warehouse.dim_branch)::text AS actual,
       'all' AS expected,
       CASE WHEN (SELECT COUNT(DISTINCT branch_key) FROM warehouse.fact_sales) = (SELECT COUNT(*) FROM warehouse.dim_branch) THEN 'PASS' ELSE 'FAIL' END AS status;

SELECT '15 medicine coverage (medicines with sales / medicines)' AS check_name,
       (SELECT COUNT(DISTINCT medicine_key) FROM warehouse.fact_sales)::text || ' / ' || (SELECT COUNT(*) FROM warehouse.dim_medicine)::text AS actual,
       'info' AS expected, 'INFO' AS status;

SELECT '16 supplier coverage (suppliers with purchases / suppliers)' AS check_name,
       (SELECT COUNT(DISTINCT supplier_key) FROM warehouse.fact_purchase)::text || ' / ' || (SELECT COUNT(*) FROM warehouse.dim_supplier)::text AS actual,
       'all' AS expected,
       CASE WHEN (SELECT COUNT(DISTINCT supplier_key) FROM warehouse.fact_purchase) = (SELECT COUNT(*) FROM warehouse.dim_supplier) THEN 'PASS' ELSE 'FAIL' END AS status;

-- 17. Batch consistency: fact medicine/supplier agree with the batch dimension
SELECT '17 batch consistency mismatches (' || t || ')' AS check_name, n::text AS actual, '0' AS expected,
       CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM (
    SELECT 'sales medicine' AS t, COUNT(*) AS n FROM warehouse.fact_sales s JOIN warehouse.dim_batch b USING (batch_key) WHERE s.medicine_key <> b.medicine_key
    UNION ALL SELECT 'purchase medicine', COUNT(*) FROM warehouse.fact_purchase p JOIN warehouse.dim_batch b USING (batch_key) WHERE p.medicine_key <> b.medicine_key
    UNION ALL SELECT 'purchase supplier', COUNT(*) FROM warehouse.fact_purchase p JOIN warehouse.dim_batch b USING (batch_key) WHERE p.supplier_key <> b.supplier_key
    UNION ALL SELECT 'purchase price', COUNT(*) FROM warehouse.fact_purchase p JOIN warehouse.dim_batch b USING (batch_key) WHERE p.unit_purchase_price <> b.purchase_price
    UNION ALL SELECT 'batch initial_quantity vs purchases', COUNT(*) FROM warehouse.dim_batch b
        LEFT JOIN (SELECT batch_key, SUM(quantity) AS q FROM warehouse.fact_purchase GROUP BY batch_key) p USING (batch_key)
        WHERE b.initial_quantity <> COALESCE(p.q, 0)
) c;

-- 18. Inventory flows agree with the facts (additive totals and every cell)
SELECT '18 inventory flows vs facts: total mismatch (units)' AS check_name,
       (ABS((SELECT SUM(purchased_quantity) FROM warehouse.fact_inventory) - (SELECT SUM(quantity) FROM warehouse.fact_purchase))
      + ABS((SELECT SUM(sold_quantity) FROM warehouse.fact_inventory) - (SELECT SUM(quantity) FROM warehouse.fact_sales)))::text AS actual,
       '0' AS expected,
       CASE WHEN (SELECT SUM(purchased_quantity) FROM warehouse.fact_inventory) = (SELECT SUM(quantity) FROM warehouse.fact_purchase)
             AND (SELECT SUM(sold_quantity) FROM warehouse.fact_inventory) = (SELECT SUM(quantity) FROM warehouse.fact_sales)
            THEN 'PASS' ELSE 'FAIL' END AS status;

SELECT '18b inventory flows vs facts: cell mismatches' AS check_name, COUNT(*)::text AS actual, '0' AS expected,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM warehouse.fact_inventory i
LEFT JOIN (SELECT date_key, branch_key, medicine_key, SUM(quantity) AS q FROM warehouse.fact_sales GROUP BY 1, 2, 3) s
       USING (date_key, branch_key, medicine_key)
LEFT JOIN (SELECT date_key, branch_key, medicine_key, SUM(quantity) AS q FROM warehouse.fact_purchase GROUP BY 1, 2, 3) p
       USING (date_key, branch_key, medicine_key)
WHERE i.sold_quantity <> COALESCE(s.q, 0) OR i.purchased_quantity <> COALESCE(p.q, 0);

-- 19. Inventory snapshot is dense (dates x branches x medicines)
SELECT '19 inventory rows vs dates x branches x medicines' AS check_name,
       (SELECT COUNT(*) FROM warehouse.fact_inventory)::text AS actual,
       ((SELECT COUNT(*) FROM warehouse.dim_date) * (SELECT COUNT(*) FROM warehouse.dim_branch) * (SELECT COUNT(*) FROM warehouse.dim_medicine))::text AS expected,
       CASE WHEN (SELECT COUNT(*) FROM warehouse.fact_inventory)
               = (SELECT COUNT(*) FROM warehouse.dim_date) * (SELECT COUNT(*) FROM warehouse.dim_branch) * (SELECT COUNT(*) FROM warehouse.dim_medicine)
            THEN 'PASS' ELSE 'FAIL' END AS status;

-- 20. Information: stockout branch-medicine-days and expired units derived from the snapshot
SELECT '20 stockout days (closing = 0)' AS check_name, COUNT(*)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_inventory WHERE closing_quantity = 0;

SELECT '20b expired units written off' AS check_name, SUM(expired_quantity)::text AS actual, 'info' AS expected, 'INFO' AS status
FROM warehouse.fact_inventory;
