-- Expiry analytics (v_expiry_risk = purchases - sales per branch+batch, dim_batch expiry dates, trailing demand). Run with: python -m analytics.run --file expiry
-- Snapshot date = latest date. EXPIRED lots = stock that was written off on its expiry date (units match fact_inventory.expired_quantity).
-- Live-lot risk is FEFO-aware (see v_expiry_risk): the trailing 90-day demand is projected to the expiry date, earlier-expiring lots consume it first,
-- projected_unsold_units = what is expected to remain unsold at expiry (only when expiry is within 365 days). Value uses each batch's own purchase price.
-- risk_class: CRITICAL = projected unsold units and expiry within 30 days / HIGH = ... within 90 days / MEDIUM = projected unsold beyond 90 days or expiring within 90 days but expected to sell out / SAFE.

-- @name: Expiry KPIs (expired, near-expiry, expiry risk)
SELECT SUM(remaining_units) FILTER (WHERE is_expired)                                          AS expired_units,
       ROUND(SUM(cost_value) FILTER (WHERE is_expired), 2)                                     AS expired_inventory_value,
       SUM(remaining_units) FILTER (WHERE NOT is_expired AND days_to_expiry <= 90)             AS near_expiry_units_90d,
       ROUND(SUM(cost_value) FILTER (WHERE NOT is_expired AND days_to_expiry <= 90), 2)        AS near_expiry_value_90d,
       ROUND(SUM(projected_unsold_units) FILTER (WHERE NOT is_expired), 0)                     AS expiry_risk_units,
       ROUND(SUM(value_at_risk) FILTER (WHERE NOT is_expired), 2)                              AS expiry_risk_value,
       COUNT(*) FILTER (WHERE NOT is_expired AND risk_class IN ('CRITICAL', 'HIGH'))           AS critical_or_high_lots,
       SUM(remaining_units) FILTER (WHERE NOT is_expired)                                      AS live_stock_units
FROM warehouse.v_expiry_risk;

-- @name: Expiry risk class summary (live and expired lots)
SELECT risk_class, COUNT(*) AS batch_lots, SUM(remaining_units) AS units, ROUND(SUM(cost_value), 2) AS cost_value,
       ROUND(SUM(projected_unsold_units), 0) AS projected_unsold_units, ROUND(SUM(value_at_risk), 2) AS value_at_risk
FROM warehouse.v_expiry_risk
GROUP BY risk_class
ORDER BY CASE risk_class WHEN 'EXPIRED' THEN 1 WHEN 'CRITICAL' THEN 2 WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 4 ELSE 5 END;

-- @name: Expired inventory by category
SELECT category_name, COUNT(*) AS expired_lots, SUM(remaining_units) AS expired_units, ROUND(SUM(cost_value), 2) AS expired_value,
       ROUND(100.0 * SUM(cost_value) / SUM(SUM(cost_value)) OVER (), 2) AS value_share_pct
FROM warehouse.v_expiry_risk
WHERE is_expired
GROUP BY category_name
ORDER BY expired_value DESC;

-- @name: Expired inventory by branch
SELECT branch_name, COUNT(*) AS expired_lots, SUM(remaining_units) AS expired_units, ROUND(SUM(cost_value), 2) AS expired_value
FROM warehouse.v_expiry_risk
WHERE is_expired
GROUP BY branch_name
ORDER BY expired_value DESC;

-- @name: Expired inventory by month of expiry
SELECT date_trunc('month', expiry_date)::date AS expiry_month, COUNT(*) AS expired_lots, SUM(remaining_units) AS expired_units,
       ROUND(SUM(cost_value), 2) AS expired_value
FROM warehouse.v_expiry_risk
WHERE is_expired
GROUP BY date_trunc('month', expiry_date)
ORDER BY expiry_month;

-- @name: Top 15 medicines by expired value
SELECT medicine_name, category_name, COUNT(*) AS expired_lots, SUM(remaining_units) AS expired_units, ROUND(SUM(cost_value), 2) AS expired_value
FROM warehouse.v_expiry_risk
WHERE is_expired
GROUP BY medicine_key, medicine_name, category_name
ORDER BY expired_value DESC
LIMIT 15;

-- @name: Live stock by days-to-expiry bucket (aging)
SELECT CASE WHEN days_to_expiry <= 30 THEN '1: 1-30 days'
            WHEN days_to_expiry <= 90 THEN '2: 31-90 days'
            WHEN days_to_expiry <= 180 THEN '3: 91-180 days'
            WHEN days_to_expiry <= 365 THEN '4: 181-365 days'
            ELSE '5: over 365 days' END AS days_to_expiry_bucket,
       COUNT(*) AS batch_lots, SUM(remaining_units) AS units, ROUND(SUM(cost_value), 2) AS cost_value,
       ROUND(SUM(projected_unsold_units), 0) AS projected_unsold_units, ROUND(SUM(value_at_risk), 2) AS value_at_risk
FROM warehouse.v_expiry_risk
WHERE NOT is_expired
GROUP BY 1
ORDER BY 1;

-- @name: Near-expiry stock (within 90 days) by category
SELECT category_name, COUNT(*) AS batch_lots, SUM(remaining_units) AS near_expiry_units, ROUND(SUM(cost_value), 2) AS near_expiry_value,
       ROUND(SUM(value_at_risk), 2) AS value_at_risk
FROM warehouse.v_expiry_risk
WHERE NOT is_expired AND days_to_expiry <= 90
GROUP BY category_name
ORDER BY near_expiry_value DESC;

-- @name: Expiry-risk value by category (live lots)
SELECT category_name, COUNT(*) FILTER (WHERE projected_unsold_units > 0) AS lots_at_risk,
       ROUND(SUM(projected_unsold_units), 0) AS expiry_risk_units, ROUND(SUM(value_at_risk), 2) AS expiry_risk_value,
       ROUND(100.0 * SUM(value_at_risk) / NULLIF(SUM(SUM(value_at_risk)) OVER (), 0), 2) AS share_of_risk_pct
FROM warehouse.v_expiry_risk
WHERE NOT is_expired
GROUP BY category_name
ORDER BY expiry_risk_value DESC;

-- @name: Expiry-risk value by branch (live lots)
SELECT branch_name, COUNT(*) FILTER (WHERE projected_unsold_units > 0) AS lots_at_risk,
       ROUND(SUM(projected_unsold_units), 0) AS expiry_risk_units, ROUND(SUM(value_at_risk), 2) AS expiry_risk_value
FROM warehouse.v_expiry_risk
WHERE NOT is_expired
GROUP BY branch_name
ORDER BY expiry_risk_value DESC;

-- @name: Expiry risk roll-up Branch > Category > Medicine (live lots with projected loss)
SELECT CASE WHEN GROUPING(branch_name) = 1 THEN 'ALL BRANCHES' ELSE branch_name END AS branch,
       CASE WHEN GROUPING(category_name) = 1 THEN 'all categories' ELSE category_name END AS category,
       CASE WHEN GROUPING(medicine_name) = 1 THEN 'subtotal' ELSE medicine_name END AS medicine,
       COUNT(*) AS lots, ROUND(SUM(projected_unsold_units), 0) AS expiry_risk_units, ROUND(SUM(value_at_risk), 2) AS expiry_risk_value
FROM warehouse.v_expiry_risk
WHERE NOT is_expired AND projected_unsold_units > 0
GROUP BY ROLLUP (branch_name, category_name, medicine_name)
ORDER BY GROUPING(branch_name), branch_name, GROUPING(category_name), category_name, GROUPING(medicine_name), expiry_risk_value DESC
LIMIT 40;

-- @name: High-value expiring stock (top 20 lots by value at risk)
SELECT medicine_name, batch_id, branch_name, remaining_units AS quantity, expiry_date, days_to_expiry, cost_value,
       daily_demand_90d, projected_unsold_units, value_at_risk, risk_class
FROM warehouse.v_expiry_risk
WHERE NOT is_expired AND value_at_risk > 0
ORDER BY value_at_risk DESC, batch_id
LIMIT 20;

-- @name: Illustration of demand-aware risk (same days to expiry, different demand)
-- lots expiring within 30 days: units on hand versus demand decide the class, not the date alone
SELECT medicine_name, branch_name, days_to_expiry, remaining_units AS units_on_hand, daily_demand_90d,
       expected_sales_before_expiry, projected_unsold_units, risk_class
FROM warehouse.v_expiry_risk
WHERE NOT is_expired AND days_to_expiry <= 30
ORDER BY days_to_expiry, projected_unsold_units DESC, medicine_name
LIMIT 20;
