-- MedStock analytics views (schema "warehouse"). Idempotent: CREATE OR REPLACE.
-- Only views that make repeated analytical queries cleaner are defined (7). All are derived from the star schema,
-- never from generator metadata. "Snapshot date" = the latest date in fact_inventory (inventory is semi-additive:
-- current stock is read on ONE date, never summed across days).
-- (Statements are separated by semicolons: keep semicolons out of comments and strings.)

-- Re-runnable even when a view definition changes (CREATE OR REPLACE cannot change a view's column list).
DROP VIEW IF EXISTS warehouse.v_monthly_sales, warehouse.v_medicine_performance, warehouse.v_branch_performance,
                    warehouse.v_demand_stats, warehouse.v_stockout_summary, warehouse.v_current_inventory, warehouse.v_expiry_risk;

-- ---------------------------------------------------------------------------
-- v_monthly_sales: one row per calendar month. Source: fact_sales + dim_date.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.v_monthly_sales AS
SELECT d.year,
       d.month,
       d.month_name,
       MIN(d.full_date)                         AS month_start,
       SUM(s.quantity)                          AS units,
       SUM(s.total_amount)                      AS revenue,
       SUM(s.discount)                          AS discount,
       COUNT(*)                                 AS sales_lines,
       COUNT(DISTINCT s.transaction_id)         AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.year, d.month, d.month_name;

COMMENT ON VIEW warehouse.v_monthly_sales IS 'Monthly units, revenue, discount, sales lines and transactions (a transaction lies within one day, so monthly transaction counts add up across months).';

-- ---------------------------------------------------------------------------
-- v_medicine_performance: one row per medicine over the whole period.
-- mover_class (observable velocity, percentile of total units): FAST = top 20 percent, MEDIUM = next 30 percent, SLOW = bottom 50 percent.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.v_medicine_performance AS
WITH per_medicine AS (
    SELECT s.medicine_key,
           SUM(s.quantity)                       AS units,
           SUM(s.total_amount)                   AS revenue,
           COUNT(*)                              AS sales_lines,
           COUNT(DISTINCT s.transaction_id)      AS transactions,
           COUNT(DISTINCT s.date_key)            AS sales_days
    FROM warehouse.fact_sales s
    GROUP BY s.medicine_key
),
calendar AS (SELECT COUNT(*)::numeric AS days FROM warehouse.dim_date)
SELECT m.medicine_key,
       m.medicine_id,
       m.medicine_name,
       c.category_name,
       m.manufacturer,
       m.dosage_form,
       p.units,
       p.revenue,
       p.sales_lines,
       p.transactions,
       p.sales_days,
       ROUND(p.revenue / NULLIF(p.units, 0), 2)                         AS avg_selling_price,
       ROUND(p.units / cal.days, 3)                                     AS avg_daily_units,
       ROUND(100.0 * p.revenue / SUM(p.revenue) OVER (), 3)             AS revenue_share_pct,
       RANK() OVER (ORDER BY p.revenue DESC)                            AS revenue_rank,
       RANK() OVER (ORDER BY p.units DESC)                              AS units_rank,
       RANK() OVER (ORDER BY p.transactions DESC)                       AS frequency_rank,
       CASE WHEN PERCENT_RANK() OVER (ORDER BY p.units) >= 0.80 THEN 'FAST'
            WHEN PERCENT_RANK() OVER (ORDER BY p.units) >= 0.50 THEN 'MEDIUM'
            ELSE 'SLOW' END                                             AS mover_class
FROM per_medicine p
JOIN warehouse.dim_medicine m ON m.medicine_key = p.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
CROSS JOIN calendar cal;

COMMENT ON VIEW warehouse.v_medicine_performance IS 'Per-medicine sales performance with ranks and FAST/MEDIUM/SLOW mover class (percentile of units sold).';

-- ---------------------------------------------------------------------------
-- v_branch_performance: one row per branch over the whole period.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.v_branch_performance AS
WITH per_branch AS (
    SELECT s.branch_key,
           SUM(s.quantity)                       AS units,
           SUM(s.total_amount)                   AS revenue,
           COUNT(DISTINCT s.transaction_id)      AS transactions,
           COUNT(DISTINCT s.medicine_key)        AS active_medicines
    FROM warehouse.fact_sales s
    GROUP BY s.branch_key
)
SELECT b.branch_key,
       b.branch_id,
       b.branch_name,
       b.area,
       p.units,
       p.revenue,
       p.transactions,
       p.active_medicines,
       ROUND(p.revenue / NULLIF(p.transactions, 0), 2)                  AS avg_transaction_value,
       ROUND(p.units::numeric / NULLIF(p.transactions, 0), 3)           AS avg_units_per_transaction,
       ROUND(100.0 * p.revenue / SUM(p.revenue) OVER (), 2)             AS revenue_share_pct,
       ROUND(100.0 * p.units / SUM(p.units) OVER (), 2)                 AS unit_share_pct,
       RANK() OVER (ORDER BY p.revenue DESC)                            AS revenue_rank
FROM per_branch p
JOIN warehouse.dim_branch b ON b.branch_key = p.branch_key;

COMMENT ON VIEW warehouse.v_branch_performance IS 'Per-branch revenue, units, transactions, average basket value, active medicines and shares.';

-- ---------------------------------------------------------------------------
-- v_demand_stats: one row per branch x medicine. Daily demand series = fact_inventory.sold_quantity (dense: includes zero days).
-- On stockout days observed demand is censored (sales cannot exceed stock).
--   coefficient_of_variation        = STDDEV_SAMP(daily units) / AVG(daily units)       (the plain formula, NULL when mean = 0)
--   weekly_coefficient_of_variation = same on weekly units over complete ISO weeks
-- Daily counts of slow medicines are dominated by Poisson noise (CV >= 1 / sqrt(mean)), so the class uses the WEEKLY CV:
--   STABLE < 0.5, MODERATELY VARIABLE < 1.0, HIGHLY VARIABLE >= 1.0, NO DEMAND when there were no sales.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.v_demand_stats AS
WITH weekly AS (
    SELECT i.branch_key, i.medicine_key, EXTRACT(isoyear FROM d.full_date) AS iso_year, d.week, SUM(i.sold_quantity) AS units
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date d ON d.date_key = i.date_key
    GROUP BY i.branch_key, i.medicine_key, EXTRACT(isoyear FROM d.full_date), d.week
    HAVING COUNT(*) = 7
),
weekly_stats AS (
    SELECT branch_key, medicine_key, AVG(units) AS mean_weekly, STDDEV_SAMP(units) AS stddev_weekly
    FROM weekly
    GROUP BY branch_key, medicine_key
),
daily AS (
    SELECT i.branch_key, i.medicine_key,
           SUM(i.sold_quantity)                              AS total_units,
           AVG(i.sold_quantity)                              AS mean_daily,
           STDDEV_SAMP(i.sold_quantity)                      AS stddev_daily,
           COUNT(*) FILTER (WHERE i.sold_quantity > 0)       AS sales_days,
           COUNT(*) FILTER (WHERE i.sold_quantity = 0)       AS zero_sales_days
    FROM warehouse.fact_inventory i
    GROUP BY i.branch_key, i.medicine_key
)
SELECT dl.branch_key,
       b.branch_name,
       dl.medicine_key,
       m.medicine_name,
       c.category_name,
       dl.total_units,
       ROUND(dl.mean_daily, 4)                                                   AS avg_daily_demand,
       ROUND(dl.mean_daily * 7, 3)                                               AS avg_weekly_demand,
       ROUND(dl.mean_daily * 365.25 / 12, 2)                                     AS avg_monthly_demand,
       dl.sales_days,
       dl.zero_sales_days,
       ROUND(dl.stddev_daily, 4)                                                 AS stddev_daily_demand,
       ROUND(dl.stddev_daily / NULLIF(dl.mean_daily, 0), 3)                      AS coefficient_of_variation,
       ROUND(ws.stddev_weekly / NULLIF(ws.mean_weekly, 0), 3)                    AS weekly_coefficient_of_variation,
       CASE WHEN dl.mean_daily = 0 THEN 'NO DEMAND'
            WHEN ws.stddev_weekly / ws.mean_weekly < 0.5 THEN 'STABLE'
            WHEN ws.stddev_weekly / ws.mean_weekly < 1.0 THEN 'MODERATELY VARIABLE'
            ELSE 'HIGHLY VARIABLE' END                                           AS variability_class
FROM daily dl
JOIN weekly_stats ws          ON ws.branch_key = dl.branch_key AND ws.medicine_key = dl.medicine_key
JOIN warehouse.dim_branch b   ON b.branch_key = dl.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = dl.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key;

COMMENT ON VIEW warehouse.v_demand_stats IS 'Daily/weekly/monthly demand statistics, daily and weekly coefficient of variation and variability class per branch and medicine.';

-- ---------------------------------------------------------------------------
-- v_stockout_summary: one row per branch x medicine. A stockout day is FACT_INVENTORY.closing_quantity = 0.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.v_stockout_summary AS
SELECT i.branch_key,
       b.branch_name,
       i.medicine_key,
       m.medicine_name,
       c.category_name,
       COUNT(*) FILTER (WHERE i.closing_quantity = 0)                                        AS stockout_days,
       COUNT(*)                                                                              AS days_observed,
       ROUND(100.0 * COUNT(*) FILTER (WHERE i.closing_quantity = 0) / COUNT(*), 3)           AS stockout_rate_pct
FROM warehouse.fact_inventory i
JOIN warehouse.dim_branch b   ON b.branch_key = i.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY i.branch_key, b.branch_name, i.medicine_key, m.medicine_name, c.category_name;

COMMENT ON VIEW warehouse.v_stockout_summary IS 'Stockout days and rate per branch and medicine (closing_quantity = 0).';

-- ---------------------------------------------------------------------------
-- v_current_inventory: one row per branch x medicine on the snapshot date (latest date).
-- avg_daily_demand_30d = units sold in the last 30 days / 30. days_of_inventory = stock / that demand (NULL when there was no demand).
-- stock_status (transparent rules):
--   OUT OF STOCK : stock = 0
--   LOW STOCK    : stock > 0 and days_of_inventory < 7      (under one week of cover)
--   OVERSTOCK    : stock > 0 and (no demand in 30 days or days_of_inventory > 90)   (more than ~3 months of cover)
--   NORMAL       : otherwise
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.v_current_inventory AS
WITH snap AS (
    SELECT d.date_key, d.full_date
    FROM warehouse.dim_date d
    WHERE d.date_key = (SELECT MAX(date_key) FROM warehouse.fact_inventory)
),
demand_30d AS (
    SELECT i.branch_key, i.medicine_key, SUM(i.sold_quantity) AS units_30d
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date d ON d.date_key = i.date_key
    CROSS JOIN snap
    WHERE d.full_date > snap.full_date - 30 AND d.full_date <= snap.full_date
    GROUP BY i.branch_key, i.medicine_key
)
SELECT snap.full_date                                                    AS snapshot_date,
       i.branch_key,
       b.branch_name,
       i.medicine_key,
       m.medicine_name,
       c.category_name,
       i.closing_quantity                                                AS stock_units,
       i.closing_value_at_cost                                           AS stock_value_at_cost,
       ROUND(COALESCE(d30.units_30d, 0) / 30.0, 4)                       AS avg_daily_demand_30d,
       ROUND(i.closing_quantity / NULLIF(COALESCE(d30.units_30d, 0) / 30.0, 0), 1) AS days_of_inventory,
       CASE WHEN i.closing_quantity = 0 THEN 'OUT OF STOCK'
            WHEN COALESCE(d30.units_30d, 0) = 0 THEN 'OVERSTOCK'
            WHEN i.closing_quantity / (d30.units_30d / 30.0) < 7 THEN 'LOW STOCK'
            WHEN i.closing_quantity / (d30.units_30d / 30.0) > 90 THEN 'OVERSTOCK'
            ELSE 'NORMAL' END                                            AS stock_status
FROM warehouse.fact_inventory i
JOIN snap ON snap.date_key = i.date_key
JOIN warehouse.dim_branch b   ON b.branch_key = i.branch_key
JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
LEFT JOIN demand_30d d30 ON d30.branch_key = i.branch_key AND d30.medicine_key = i.medicine_key;

COMMENT ON VIEW warehouse.v_current_inventory IS 'Current (latest-date) stock per branch and medicine with 30-day demand, days of inventory and stock status.';

-- ---------------------------------------------------------------------------
-- v_expiry_risk: one row per (branch, batch) lot that still holds units at the snapshot date.
--   remaining_units = received at the branch - sold from that batch at the branch.
--   EXPIRED lots (expiry_date <= snapshot) are the stock that was written off on its expiry date.
--   For live lots the risk is FEFO-aware: the branch's trailing 90-day demand is projected to expiry, and earlier-expiring
--   lots of the same medicine consume that demand first (units_ahead).
--     expected_sales_before_expiry = daily_demand_90d * days_to_expiry
--     projected_sold   = LEAST(remaining, GREATEST(0, expected_sales_before_expiry - units_ahead))
--     projected_unsold = remaining - projected_sold        (counted only when days_to_expiry <= 365, the projection horizon)
--   risk_class: EXPIRED / CRITICAL (projected_unsold > 0 and <= 30 days) / HIGH (projected_unsold > 0 and <= 90 days) /
--               MEDIUM (projected_unsold > 0 beyond 90 days, or expiring within 90 days but expected to sell out) / SAFE.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.v_expiry_risk AS
WITH snap AS (
    SELECT d.date_key, d.full_date
    FROM warehouse.dim_date d
    WHERE d.date_key = (SELECT MAX(date_key) FROM warehouse.fact_inventory)
),
received AS (
    SELECT branch_key, batch_key, SUM(quantity) AS units FROM warehouse.fact_purchase GROUP BY branch_key, batch_key
),
sold AS (
    SELECT branch_key, batch_key, SUM(quantity) AS units FROM warehouse.fact_sales GROUP BY branch_key, batch_key
),
demand_90d AS (
    SELECT i.branch_key, i.medicine_key, SUM(i.sold_quantity) / 90.0 AS daily_demand
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date d ON d.date_key = i.date_key
    CROSS JOIN snap
    WHERE d.full_date > snap.full_date - 90 AND d.full_date <= snap.full_date
    GROUP BY i.branch_key, i.medicine_key
),
lots AS (
    SELECT r.branch_key,
           bt.medicine_key,
           bt.batch_key,
           bt.batch_id,
           bt.expiry_date,
           bt.purchase_price,
           r.units - COALESCE(s.units, 0)                  AS remaining_units,
           (bt.expiry_date - snap.full_date)               AS days_to_expiry,
           COALESCE(dm.daily_demand, 0)                    AS daily_demand_90d
    FROM received r
    LEFT JOIN sold s ON s.branch_key = r.branch_key AND s.batch_key = r.batch_key
    JOIN warehouse.dim_batch bt ON bt.batch_key = r.batch_key
    CROSS JOIN snap
    LEFT JOIN demand_90d dm ON dm.branch_key = r.branch_key AND dm.medicine_key = bt.medicine_key
    WHERE r.units - COALESCE(s.units, 0) > 0
),
live AS (
    SELECT l.*,
           COALESCE(SUM(l.remaining_units) OVER (PARTITION BY l.branch_key, l.medicine_key
                                                 ORDER BY l.expiry_date, l.batch_key
                                                 ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS units_ahead
    FROM lots l
    WHERE l.days_to_expiry > 0
),
scored AS (
    SELECT lv.branch_key, lv.medicine_key, lv.batch_key, lv.batch_id, lv.expiry_date, lv.purchase_price, lv.remaining_units,
           lv.days_to_expiry, lv.daily_demand_90d, lv.units_ahead,
           lv.daily_demand_90d * lv.days_to_expiry AS expected_sales_before_expiry,
           CASE WHEN lv.days_to_expiry <= 365
                THEN lv.remaining_units - LEAST(lv.remaining_units, GREATEST(0, lv.daily_demand_90d * lv.days_to_expiry - lv.units_ahead))
                ELSE 0 END AS projected_unsold_units
    FROM live lv
    UNION ALL
    SELECT l.branch_key, l.medicine_key, l.batch_key, l.batch_id, l.expiry_date, l.purchase_price, l.remaining_units,
           l.days_to_expiry, l.daily_demand_90d, 0, 0, l.remaining_units      -- written off at expiry
    FROM lots l
    WHERE l.days_to_expiry <= 0
)
SELECT br.branch_key,
       br.branch_name,
       c.category_name,
       m.medicine_key,
       m.medicine_name,
       sc.batch_key,
       sc.batch_id,
       sc.expiry_date,
       sc.days_to_expiry,
       sc.remaining_units,
       sc.purchase_price                                                      AS unit_cost,
       ROUND(sc.remaining_units * sc.purchase_price, 2)                       AS cost_value,
       ROUND(sc.daily_demand_90d, 4)                                          AS daily_demand_90d,
       ROUND(sc.expected_sales_before_expiry, 1)                              AS expected_sales_before_expiry,
       ROUND(sc.projected_unsold_units, 1)                                    AS projected_unsold_units,
       ROUND(sc.projected_unsold_units * sc.purchase_price, 2)                AS value_at_risk,
       (sc.days_to_expiry <= 0)                                               AS is_expired,
       CASE WHEN sc.days_to_expiry <= 0 THEN 'EXPIRED'
            WHEN sc.projected_unsold_units > 0 AND sc.days_to_expiry <= 30 THEN 'CRITICAL'
            WHEN sc.projected_unsold_units > 0 AND sc.days_to_expiry <= 90 THEN 'HIGH'
            WHEN sc.projected_unsold_units > 0 OR sc.days_to_expiry <= 90 THEN 'MEDIUM'
            ELSE 'SAFE' END                                                   AS risk_class
FROM scored sc
JOIN warehouse.dim_branch br   ON br.branch_key = sc.branch_key
JOIN warehouse.dim_medicine m  ON m.medicine_key = sc.medicine_key
JOIN warehouse.dim_category c  ON c.category_key = m.category_key;

COMMENT ON VIEW warehouse.v_expiry_risk IS 'Batch lots holding stock at the snapshot date: expired write-offs plus live lots with FEFO-aware projected unsold units, value at risk and risk class.';
