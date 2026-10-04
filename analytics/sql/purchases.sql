-- Purchase and supplier analytics (fact_purchase x dim_supplier / dim_medicine / dim_category / dim_batch). Run with: python -m analytics.run --file purchases
-- average purchase price = SUM(total_cost) / SUM(quantity) (quantity-weighted). Purchases are dated by receipt.
-- Purchase prices are cost prices and are unrelated to selling prices.

-- @name: Purchase KPIs
SELECT SUM(quantity)                              AS total_purchase_quantity,
       SUM(total_cost)                            AS total_purchase_cost,
       COUNT(*)                                   AS delivery_lines,
       COUNT(DISTINCT batch_key)                  AS batches,
       ROUND(SUM(total_cost) / NULLIF(SUM(quantity), 0), 2) AS average_purchase_price
FROM warehouse.fact_purchase;

-- @name: Purchases by month
SELECT d.year, d.month, SUM(p.quantity) AS purchase_quantity, SUM(p.total_cost) AS purchase_cost, COUNT(*) AS delivery_lines
FROM warehouse.fact_purchase p
JOIN warehouse.dim_date d ON d.date_key = p.date_key
GROUP BY d.year, d.month
ORDER BY d.year, d.month;

-- @name: Supplier analytics (ranked by spend)
SELECT RANK() OVER (ORDER BY SUM(p.total_cost) DESC)                              AS spend_rank,
       sp.supplier_name,
       sp.city,
       SUM(p.total_cost)                                                          AS total_purchase_value,
       SUM(p.quantity)                                                            AS total_purchase_quantity,
       COUNT(DISTINCT p.medicine_key)                                             AS medicines_supplied,
       COUNT(DISTINCT m.category_key)                                             AS categories_supplied,
       ROUND(SUM(p.total_cost) / NULLIF(SUM(p.quantity), 0), 2)                   AS average_purchase_price,
       ROUND(100.0 * SUM(p.total_cost) / SUM(SUM(p.total_cost)) OVER (), 2)       AS spend_share_pct
FROM warehouse.fact_purchase p
JOIN warehouse.dim_supplier sp ON sp.supplier_key = p.supplier_key
JOIN warehouse.dim_medicine m  ON m.medicine_key = p.medicine_key
GROUP BY sp.supplier_key, sp.supplier_name, sp.city
ORDER BY spend_rank;

-- @name: Supplier concentration (share of spend by top N suppliers)
WITH spend AS (
    SELECT supplier_key, SUM(total_cost) AS value FROM warehouse.fact_purchase GROUP BY supplier_key
),
ranked AS (
    SELECT value, RANK() OVER (ORDER BY value DESC) AS rnk, SUM(value) OVER () AS total FROM spend
)
SELECT ROUND(100.0 * SUM(value) FILTER (WHERE rnk <= 1) / MAX(total), 2)   AS top_1_share_pct,
       ROUND(100.0 * SUM(value) FILTER (WHERE rnk <= 5) / MAX(total), 2)   AS top_5_share_pct,
       ROUND(100.0 * SUM(value) FILTER (WHERE rnk <= 10) / MAX(total), 2)  AS top_10_share_pct,
       COUNT(*)                                                            AS suppliers,
       ROUND(100.0 * 5 / COUNT(*), 2)                                      AS equal_share_of_5_suppliers_pct
FROM ranked;

-- @name: Purchases by category
SELECT c.category_name, SUM(p.quantity) AS purchase_quantity, SUM(p.total_cost) AS purchase_cost,
       ROUND(100.0 * SUM(p.total_cost) / SUM(SUM(p.total_cost)) OVER (), 2) AS cost_share_pct
FROM warehouse.fact_purchase p
JOIN warehouse.dim_medicine m ON m.medicine_key = p.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY c.category_name
ORDER BY purchase_cost DESC;

-- @name: Purchases by medicine (top 20 by cost)
SELECT m.medicine_name, c.category_name, SUM(p.quantity) AS purchase_quantity, SUM(p.total_cost) AS purchase_cost,
       ROUND(SUM(p.total_cost) / NULLIF(SUM(p.quantity), 0), 2) AS average_purchase_price, COUNT(DISTINCT p.batch_key) AS batches
FROM warehouse.fact_purchase p
JOIN warehouse.dim_medicine m ON m.medicine_key = p.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY m.medicine_key, m.medicine_name, c.category_name
ORDER BY purchase_cost DESC
LIMIT 20;

-- @name: Purchase price changes by medicine (first vs latest purchase, 15 percent flag)
-- Medicines with at least 10 delivery lines. first/latest = unit price of the earliest/latest delivery (ties broken by purchase_key).
-- price_change_pct = (latest - first) / first. price_range_pct = (max - min) / average. significant_change = absolute change of 15 percent or more.
-- Note: a medicine's price differs by supplier and lot (there is no market-wide price trend in the data), so this measures realised cost movement.
WITH per_medicine AS (
    SELECT p.medicine_key,
           COUNT(*)                                                                        AS delivery_lines,
           MIN(p.unit_purchase_price)                                                      AS min_price,
           MAX(p.unit_purchase_price)                                                      AS max_price,
           SUM(p.total_cost) / NULLIF(SUM(p.quantity), 0)                                  AS avg_price,
           (ARRAY_AGG(p.unit_purchase_price ORDER BY p.date_key, p.purchase_key))[1]       AS first_price,
           (ARRAY_AGG(p.unit_purchase_price ORDER BY p.date_key DESC, p.purchase_key DESC))[1] AS latest_price
    FROM warehouse.fact_purchase p
    GROUP BY p.medicine_key
    HAVING COUNT(*) >= 10
)
SELECT m.medicine_name, c.category_name, pm.delivery_lines, pm.first_price, pm.latest_price, ROUND(pm.avg_price, 2) AS average_price,
       pm.min_price, pm.max_price,
       ROUND(100.0 * (pm.latest_price - pm.first_price) / NULLIF(pm.first_price, 0), 1)  AS price_change_pct,
       ROUND(100.0 * (pm.max_price - pm.min_price) / NULLIF(pm.avg_price, 0), 1)         AS price_range_pct,
       (ABS(pm.latest_price - pm.first_price) / NULLIF(pm.first_price, 0) >= 0.15)       AS significant_change
FROM per_medicine pm
JOIN warehouse.dim_medicine m ON m.medicine_key = pm.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
ORDER BY ABS(pm.latest_price - pm.first_price) / NULLIF(pm.first_price, 0) DESC NULLS LAST, m.medicine_name
LIMIT 30;

-- @name: Purchase price change summary
WITH per_medicine AS (
    SELECT p.medicine_key,
           (ARRAY_AGG(p.unit_purchase_price ORDER BY p.date_key, p.purchase_key))[1]           AS first_price,
           (ARRAY_AGG(p.unit_purchase_price ORDER BY p.date_key DESC, p.purchase_key DESC))[1] AS latest_price
    FROM warehouse.fact_purchase p
    GROUP BY p.medicine_key
    HAVING COUNT(*) >= 10
)
SELECT COUNT(*)                                                                         AS medicines_with_history,
       COUNT(*) FILTER (WHERE ABS(latest_price - first_price) / first_price >= 0.15)    AS significant_changes,
       COUNT(*) FILTER (WHERE latest_price > first_price * 1.15)                        AS increases_over_15pct,
       COUNT(*) FILTER (WHERE latest_price < first_price * 0.85)                        AS decreases_over_15pct,
       ROUND(AVG(100.0 * (latest_price - first_price) / first_price), 2)                AS average_change_pct
FROM per_medicine;
