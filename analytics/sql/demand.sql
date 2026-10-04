-- Demand analytics (fact_inventory.sold_quantity is the dense daily demand series, fact_sales for revenue). Run with: python -m analytics.run --file demand
-- All patterns are computed from warehouse-observable sales. Observed demand is censored on stockout days (sales cannot exceed stock).
-- Coefficient of variation (CV) = standard deviation / mean (NULL when the mean is zero).

-- @name: Demand statistics per branch and medicine (top 40 by average daily demand)
SELECT branch_name, medicine_name, category_name, total_units, avg_daily_demand, avg_weekly_demand, avg_monthly_demand,
       sales_days, zero_sales_days, stddev_daily_demand, coefficient_of_variation, weekly_coefficient_of_variation, variability_class
FROM warehouse.v_demand_stats
ORDER BY avg_daily_demand DESC, branch_name, medicine_name
LIMIT 40;

-- @name: Demand overview (all branch-medicine pairs)
SELECT COUNT(*)                                   AS branch_medicine_pairs,
       ROUND(AVG(avg_daily_demand), 3)            AS mean_of_avg_daily_demand,
       ROUND(AVG(sales_days), 1)                  AS avg_sales_days,
       ROUND(AVG(zero_sales_days), 1)             AS avg_zero_sales_days,
       ROUND(AVG(coefficient_of_variation), 3)    AS avg_daily_cv,
       ROUND(AVG(weekly_coefficient_of_variation), 3) AS avg_weekly_cv,
       SUM(total_units)                           AS total_units
FROM warehouse.v_demand_stats;

-- @name: Demand variability classes
-- STABLE = weekly CV under 0.5 / MODERATELY VARIABLE = 0.5 to under 1.0 / HIGHLY VARIABLE = 1.0 or more. Daily counts of slow items are dominated by Poisson noise, hence the weekly basis.
SELECT variability_class, COUNT(*) AS branch_medicine_pairs, ROUND(AVG(avg_daily_demand), 3) AS avg_daily_demand,
       ROUND(AVG(weekly_coefficient_of_variation), 3) AS avg_weekly_cv, SUM(total_units) AS units,
       ROUND(100.0 * SUM(total_units) / SUM(SUM(total_units)) OVER (), 1) AS unit_share_pct
FROM warehouse.v_demand_stats
GROUP BY variability_class
ORDER BY avg_weekly_cv;

-- @name: Most variable and most stable medicines (weekly CV, volume of at least 7 units per week)
-- Medicine level across all branches. The volume floor avoids ranking tiny low-volume items whose CV is just Poisson noise.
WITH weekly AS (
    SELECT i.medicine_key, EXTRACT(isoyear FROM d.full_date) AS iso_year, d.week, SUM(i.sold_quantity) AS units
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date d ON d.date_key = i.date_key
    GROUP BY i.medicine_key, EXTRACT(isoyear FROM d.full_date), d.week
    HAVING COUNT(DISTINCT i.date_key) = 7
),
stats AS (
    SELECT medicine_key, AVG(units) AS mean_weekly, STDDEV_SAMP(units) AS sd_weekly FROM weekly GROUP BY medicine_key
),
ranked AS (
    SELECT s.medicine_key, s.mean_weekly, s.sd_weekly / NULLIF(s.mean_weekly, 0) AS weekly_cv,
           RANK() OVER (ORDER BY s.sd_weekly / NULLIF(s.mean_weekly, 0) DESC) AS r_var,
           RANK() OVER (ORDER BY s.sd_weekly / NULLIF(s.mean_weekly, 0) ASC)  AS r_stable
    FROM stats s
    WHERE s.mean_weekly >= 7
)
SELECT CASE WHEN r.r_var <= 5 THEN 'MOST VARIABLE' ELSE 'MOST STABLE' END AS group_label,
       m.medicine_name, c.category_name, ROUND(r.mean_weekly, 1) AS avg_weekly_units, ROUND(r.weekly_cv, 3) AS weekly_cv
FROM ranked r
JOIN warehouse.dim_medicine m ON m.medicine_key = r.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
WHERE r.r_var <= 5 OR r.r_stable <= 5
ORDER BY group_label DESC, weekly_cv DESC;

-- @name: Demand variability by category (weekly CV of category demand)
-- Category demand = units of all medicines in the category across all branches per ISO week. Lower CV = more stable. Trend and seasonality contribute to the CV.
WITH weekly AS (
    SELECT m.category_key, EXTRACT(isoyear FROM d.full_date) AS iso_year, d.week, SUM(i.sold_quantity) AS units
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date d ON d.date_key = i.date_key
    JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
    GROUP BY m.category_key, EXTRACT(isoyear FROM d.full_date), d.week
    HAVING COUNT(DISTINCT i.date_key) = 7
)
SELECT c.category_name, ROUND(AVG(w.units), 0) AS avg_weekly_units, ROUND(STDDEV_SAMP(w.units), 1) AS stddev_weekly_units,
       ROUND(STDDEV_SAMP(w.units) / NULLIF(AVG(w.units), 0), 4) AS weekly_cv,
       RANK() OVER (ORDER BY STDDEV_SAMP(w.units) / NULLIF(AVG(w.units), 0)) AS stability_rank
FROM weekly w
JOIN warehouse.dim_category c ON c.category_key = w.category_key
GROUP BY c.category_name
ORDER BY stability_rank;

-- @name: Seasonality index by category and month of year (pivot)
-- month_rate = units sold in the calendar month (pooled over both years) / number of days in those months. index = month_rate / the category's overall daily rate.
-- 1.00 = an average day. Amplitude = (max index - min index) / 2.
WITH cat_month AS (
    SELECT m.category_key, d.month, SUM(i.sold_quantity) AS units, COUNT(DISTINCT d.date_key) AS days
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date d ON d.date_key = i.date_key
    JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
    GROUP BY m.category_key, d.month
),
idx AS (
    SELECT category_key, month, (units::numeric / days) / (SUM(units) OVER (PARTITION BY category_key)::numeric / SUM(days) OVER (PARTITION BY category_key)) AS seasonal_index
    FROM cat_month
)
SELECT c.category_name,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 1), 2)  AS jan,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 2), 2)  AS feb,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 3), 2)  AS mar,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 4), 2)  AS apr,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 5), 2)  AS may,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 6), 2)  AS jun,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 7), 2)  AS jul,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 8), 2)  AS aug,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 9), 2)  AS sep,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 10), 2) AS oct,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 11), 2) AS nov,
       ROUND(MAX(seasonal_index) FILTER (WHERE month = 12), 2) AS dec
FROM idx
JOIN warehouse.dim_category c ON c.category_key = idx.category_key
GROUP BY c.category_name
ORDER BY c.category_name;

-- @name: Seasonality summary by category (peak, lowest, amplitude)
WITH cat_month AS (
    SELECT m.category_key, d.month, SUM(i.sold_quantity) AS units, COUNT(DISTINCT d.date_key) AS days
    FROM warehouse.fact_inventory i
    JOIN warehouse.dim_date d ON d.date_key = i.date_key
    JOIN warehouse.dim_medicine m ON m.medicine_key = i.medicine_key
    GROUP BY m.category_key, d.month
),
idx AS (
    SELECT category_key, month, (units::numeric / days) / (SUM(units) OVER (PARTITION BY category_key)::numeric / SUM(days) OVER (PARTITION BY category_key)) AS seasonal_index
    FROM cat_month
),
ranked AS (
    SELECT category_key, month, seasonal_index,
           ROW_NUMBER() OVER (PARTITION BY category_key ORDER BY seasonal_index DESC) AS r_hi,
           ROW_NUMBER() OVER (PARTITION BY category_key ORDER BY seasonal_index ASC)  AS r_lo
    FROM idx
)
SELECT c.category_name,
       MAX(month) FILTER (WHERE r_hi = 1)                         AS peak_month,
       ROUND(MAX(seasonal_index) FILTER (WHERE r_hi = 1), 3)      AS peak_index,
       MAX(month) FILTER (WHERE r_lo = 1)                         AS lowest_month,
       ROUND(MIN(seasonal_index) FILTER (WHERE r_lo = 1), 3)      AS lowest_index,
       ROUND((MAX(seasonal_index) - MIN(seasonal_index)) / 2, 3)  AS seasonality_amplitude,
       RANK() OVER (ORDER BY (MAX(seasonal_index) - MIN(seasonal_index)) DESC) AS seasonality_rank
FROM ranked
JOIN warehouse.dim_category c ON c.category_key = ranked.category_key
GROUP BY c.category_name
ORDER BY seasonality_rank;

-- @name: Weekday vs weekend
-- per-day figures divide by the number of weekday or weekend days in the calendar
SELECT CASE WHEN d.is_weekend THEN 'WEEKEND' ELSE 'WEEKDAY' END AS day_type,
       COUNT(DISTINCT d.date_key)                                 AS days,
       SUM(s.total_amount)                                        AS revenue,
       SUM(s.quantity)                                            AS units,
       ROUND(SUM(s.total_amount) / COUNT(DISTINCT d.date_key), 2) AS revenue_per_day,
       ROUND(SUM(s.quantity)::numeric / COUNT(DISTINCT d.date_key), 1) AS units_per_day
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.is_weekend
ORDER BY d.is_weekend;

-- @name: Revenue and units by day of week
SELECT d.day_of_week, d.day_name, COUNT(DISTINCT d.date_key) AS days, SUM(s.total_amount) AS revenue, SUM(s.quantity) AS units,
       ROUND(SUM(s.total_amount) / COUNT(DISTINCT d.date_key), 2) AS revenue_per_day
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.day_of_week, d.day_name
ORDER BY d.day_of_week;
