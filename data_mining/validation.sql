-- SQL used by data_mining/validation.py to verify mining results against the warehouse independently of the mining code.
-- Statements are named with "-- @name:" and end with a semicolon (keep semicolons out of comments). %s marks a bound parameter.

-- @name: transaction_count
-- distinct transactions in the warehouse, and the same count taken from the basket grain (transaction, medicine)
SELECT (SELECT COUNT(DISTINCT transaction_id) FROM warehouse.fact_sales) AS transactions,
       (SELECT COUNT(*) FROM (SELECT transaction_id FROM warehouse.fact_sales GROUP BY transaction_id) t) AS transactions_from_baskets;

-- @name: medicine_ids
SELECT medicine_id FROM warehouse.dim_medicine ORDER BY medicine_id;

-- @name: branch_ids
SELECT branch_id FROM warehouse.dim_branch ORDER BY branch_id;

-- @name: date_range
SELECT MIN(full_date)::text AS first_date, MAX(full_date)::text AS last_date FROM warehouse.dim_date;

-- @name: itemset_support
-- number of transactions that contain ALL of the given medicines (parameters: array of medicine ids, number of ids)
SELECT COUNT(*) AS transactions_with_all
FROM (
    SELECT s.transaction_id
    FROM warehouse.fact_sales s
    JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
    WHERE m.medicine_id = ANY(%s)
    GROUP BY s.transaction_id
    HAVING COUNT(DISTINCT m.medicine_id) = %s
) x;

-- @name: single_support
SELECT COUNT(DISTINCT s.transaction_id) AS transactions_with_medicine
FROM warehouse.fact_sales s
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
WHERE m.medicine_id = ANY(%s);
