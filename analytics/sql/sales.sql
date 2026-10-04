-- Sales analytics (fact_sales x dim_date / dim_medicine / dim_category). Run with: python -m analytics.run --file sales
-- Each statement is named with "-- @name:" and ends with a semicolon (keep semicolons out of comments).
-- Money is INR. A transaction lies within one day and one branch, so transaction counts add up across days, months and branches.
-- Additive measures (units, revenue, discount, lines, transactions) may be summed across every dimension.

-- @name: Overall sales KPIs
-- total_revenue = SUM(total_amount) / average_transaction_value = revenue / distinct transactions / daily averages divide by calendar days
-- discount_rate = discount / (revenue + discount), i.e. discount as a share of gross sales
WITH totals AS (
    SELECT SUM(s.total_amount)                AS revenue,
           SUM(s.quantity)                    AS units,
           SUM(s.discount)                    AS discount,
           COUNT(*)                           AS sales_lines,
           COUNT(DISTINCT s.transaction_id)   AS transactions
    FROM warehouse.fact_sales s
),
calendar AS (SELECT COUNT(*)::numeric AS days FROM warehouse.dim_date)
SELECT t.revenue                                                   AS total_revenue,
       t.units                                                     AS total_units_sold,
       t.transactions                                              AS total_transactions,
       t.sales_lines                                               AS total_sales_lines,
       ROUND(t.revenue / NULLIF(t.transactions, 0), 2)             AS average_transaction_value,
       ROUND(t.units::numeric / NULLIF(t.transactions, 0), 3)      AS average_units_per_transaction,
       ROUND(t.revenue / c.days, 2)                                AS average_daily_revenue,
       ROUND(t.units / c.days, 1)                                  AS average_daily_units,
       t.discount                                                  AS total_discount,
       ROUND(100.0 * t.discount / NULLIF(t.revenue + t.discount, 0), 2) AS discount_rate_pct
FROM totals t
CROSS JOIN calendar c;

-- @name: Daily sales trend
SELECT d.full_date,
       d.day_name,
       SUM(s.quantity)                    AS units,
       SUM(s.total_amount)                AS revenue,
       COUNT(DISTINCT s.transaction_id)   AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.full_date, d.day_name
ORDER BY d.full_date;

-- @name: Weekly sales trend (ISO weeks)
-- dim_date.year is the calendar year, so weeks are keyed by ISO year to avoid mixing 29-31 December with early January.
SELECT EXTRACT(isoyear FROM d.full_date)::int  AS iso_year,
       d.week                                  AS iso_week,
       MIN(d.full_date)                        AS week_first_day,
       COUNT(DISTINCT d.date_key)              AS days_in_data,
       SUM(s.quantity)                         AS units,
       SUM(s.total_amount)                     AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY EXTRACT(isoyear FROM d.full_date), d.week
ORDER BY iso_year, iso_week;

-- @name: Monthly sales trend
SELECT year, month, month_name, units, revenue, transactions
FROM warehouse.v_monthly_sales
ORDER BY year, month;

-- @name: Quarterly sales trend
SELECT d.year,
       d.quarter,
       SUM(s.quantity)      AS units,
       SUM(s.total_amount)  AS revenue
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.year, d.quarter
ORDER BY d.year, d.quarter;

-- @name: Yearly sales trend
SELECT d.year,
       SUM(s.quantity)                    AS units,
       SUM(s.total_amount)                AS revenue,
       COUNT(DISTINCT s.transaction_id)   AS transactions
FROM warehouse.fact_sales s
JOIN warehouse.dim_date d ON d.date_key = s.date_key
GROUP BY d.year
ORDER BY d.year;

-- @name: Year-over-year growth by month
-- yoy_growth_pct = (revenue - revenue same month previous year) / revenue same month previous year. LAG partitioned by calendar month.
SELECT year,
       month,
       month_name,
       revenue                                                                    AS current_year_revenue,
       LAG(revenue) OVER (PARTITION BY month ORDER BY year)                       AS previous_year_revenue,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (PARTITION BY month ORDER BY year))
             / NULLIF(LAG(revenue) OVER (PARTITION BY month ORDER BY year), 0), 2) AS yoy_growth_pct,
       units                                                                      AS current_year_units,
       LAG(units) OVER (PARTITION BY month ORDER BY year)                         AS previous_year_units
FROM warehouse.v_monthly_sales
ORDER BY year, month;

-- @name: Top 10 medicines by revenue
SELECT revenue_rank AS rank, medicine_name, category_name, units, revenue, transactions AS transaction_count, revenue_share_pct
FROM warehouse.v_medicine_performance
ORDER BY revenue_rank, medicine_name
LIMIT 10;

-- @name: Top 10 medicines by units
SELECT units_rank AS rank, medicine_name, category_name, units, revenue, transactions AS transaction_count, avg_daily_units
FROM warehouse.v_medicine_performance
ORDER BY units_rank, medicine_name
LIMIT 10;

-- @name: Top 10 medicines by transaction frequency
-- transaction_count = distinct transactions containing the medicine (basket presence), not units
SELECT frequency_rank AS rank, medicine_name, category_name, units, revenue, transactions AS transaction_count, sales_days
FROM warehouse.v_medicine_performance
ORDER BY frequency_rank, medicine_name
LIMIT 10;

-- @name: Category analytics
-- average_selling_price = revenue / units. revenue_share and unit_share = category value / SUM over categories (window function).
SELECT RANK() OVER (ORDER BY SUM(s.total_amount) DESC)                        AS revenue_rank,
       c.category_name,
       COUNT(DISTINCT m.medicine_key)                                         AS medicines,
       SUM(s.quantity)                                                        AS units_sold,
       SUM(s.total_amount)                                                    AS revenue,
       COUNT(DISTINCT s.transaction_id)                                       AS transaction_count,
       ROUND(SUM(s.total_amount) / NULLIF(SUM(s.quantity), 0), 2)             AS average_selling_price,
       ROUND(100.0 * SUM(s.total_amount) / SUM(SUM(s.total_amount)) OVER (), 2) AS revenue_share_pct,
       ROUND(100.0 * SUM(s.quantity) / SUM(SUM(s.quantity)) OVER (), 2)       AS unit_share_pct
FROM warehouse.fact_sales s
JOIN warehouse.dim_medicine m ON m.medicine_key = s.medicine_key
JOIN warehouse.dim_category c ON c.category_key = m.category_key
GROUP BY c.category_name
ORDER BY revenue_rank;
