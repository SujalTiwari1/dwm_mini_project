# MedStock Analytics + OLAP Layer

> Source data is synthetic (generated for the MedStock academic DWM project) and does not represent actual pharmacy transactions.

SQL on the PostgreSQL star schema is the analytical engine. Python only runs the files (`python -m analytics.run`) and writes the results to
`analytics/reports/`. Nothing here uses `ground_truth_private.json` or generator parameters: every classification is derived from warehouse-observable
facts (sales, purchases, inventory, batch expiry dates). Money is INR.

```
fact_sales / fact_purchase / fact_inventory + dimensions   (warehouse schema)
        │
        ├─ 7 analytics views  (analytics/sql/views.sql)
        └─ 8 query files      (sales, branches, inventory, expiry, purchases, demand, stockouts, olap)  +  analytics/validation.sql
```

## 1. Conventions

* **Additive measures** (units, revenue, discount, purchase quantity/cost, flows `purchased/sold/expired_quantity`) can be summed across every dimension.
* **Semi-additive inventory.** `closing_quantity` and `closing_value_at_cost` are summed across branches, medicines and categories on **one date only**.
  "Current" = the latest date (`2026-12-31`). Over time the analytics use the **last day of each month** (month-end inventory) or an **average of daily totals**
  (turnover), never a sum over days.
* **Transactions** are counted as distinct `transaction_id`. A transaction belongs to one day and one branch, so counts add up across days, months and branches.
* **ISO weeks.** `dim_date.year` is the calendar year while `week` is the ISO week, so weekly queries key on `EXTRACT(isoyear ...)` (otherwise 29-31 December would
  merge with early January).
* No `SELECT *`, divisions use `NULLIF`, NULLs are handled explicitly.

## 2. Views (schema `warehouse`)

| View | Grain | Purpose |
|---|---|---|
| `v_monthly_sales` | month | units, revenue, discount, sales lines, transactions per month |
| `v_medicine_performance` | medicine | units, revenue, transactions, average price, ranks, revenue share, FAST/MEDIUM/SLOW `mover_class` |
| `v_branch_performance` | branch | revenue, units, transactions, average basket value, active medicines, shares, rank |
| `v_demand_stats` | branch x medicine | total/average daily-weekly-monthly demand, sales/zero days, daily and weekly CV, `variability_class` |
| `v_stockout_summary` | branch x medicine | stockout days, days observed, stockout rate |
| `v_current_inventory` | branch x medicine (latest date) | stock units/value, 30-day demand, days of inventory, `stock_status` |
| `v_expiry_risk` | branch x batch lot holding stock | remaining units/value, days to expiry, projected unsold units, value at risk, `risk_class`, `is_expired` |

`analytics/sql/views.sql` drops and re-creates all seven (re-runnable even if a definition changes). Each view has a `COMMENT`.

## 3. Sales KPIs (`sales.sql`)

| KPI | Formula | Source |
|---|---|---|
| total_revenue | `SUM(total_amount)` | fact_sales |
| total_units_sold | `SUM(quantity)` | fact_sales |
| total_transactions | `COUNT(DISTINCT transaction_id)` | fact_sales |
| total_sales_lines | `COUNT(*)` | fact_sales |
| average_transaction_value | revenue / transactions | |
| average_units_per_transaction | units / transactions | |
| average_daily_revenue / units | total / number of calendar days (`dim_date`) | |
| discount_rate | `SUM(discount) / (SUM(total_amount) + SUM(discount))` | gross-sales basis |
| revenue_share, unit_share | value / `SUM(value) OVER ()` | window function |
| average_selling_price | revenue / units | |

Trends: daily, weekly (ISO), monthly, quarterly, yearly. **Year-over-year** growth by month uses
`LAG(revenue) OVER (PARTITION BY month ORDER BY year)` and `yoy_growth_pct = (revenue - previous) / previous`. Top-10 lists rank by revenue, by units, and by
transaction frequency (distinct baskets containing the medicine), each with category, units, revenue and transaction count.

## 4. Inventory KPIs (`inventory.sql`, `v_current_inventory`)

* **Current inventory:** read on the latest date from `fact_inventory`: units, value at cost, medicines stocked, branches with stock.
* **Days of inventory** = `current stock / average daily demand over the last 30 days` (30-day units / 30). NULL when there was no demand.
  A 30-day window is short enough to reflect current demand and long enough to smooth daily noise.
* **Stock status** (transparent, observable-only rules):

| Status | Rule |
|---|---|
| OUT OF STOCK | stock = 0 |
| LOW STOCK | stock > 0 and days of inventory < 7 (under one week of cover) |
| OVERSTOCK | stock > 0 and (no sales in the last 30 days, or days of inventory > 90) |
| NORMAL | otherwise |

  The thresholds are business parameters, not hidden metadata: one week is a conventional minimum cover and 90 days is roughly a quarter of unsold supply.
  Result: 19 out of stock, 148 low, 1,726 normal, 607 overstock (2,500 branch-medicine pairs).

## 5. Inventory turnover

```
COGS                    = SUM(quantity sold x purchase_price of the batch sold)      -- cost basis, never selling price
Average inventory value = average over days of the daily total closing_value_at_cost  -- averaging a semi-additive measure over time is valid
Turnover (period)       = COGS / average inventory value                              -- over the 24 months
Turnover (annualised)   = Turnover (period) x 365.25 / 730 days
Days inventory outstanding = 365.25 / annualised turnover
```

By category, branch and medicine: COGS and average inventory value are computed per (branch, medicine) and summed to the requested level (the ratio of sums, not an
average of ratios). Because every unit is valued at its own batch cost, the identity `COGS = purchase cost - closing value - expired value` holds exactly and is
checked in `analytics/validation.sql`.

## 6. Fast and slow movers

`v_medicine_performance.mover_class` uses `PERCENT_RANK()` of total units sold over the period: **FAST** = top 20 percent (>= 0.80), **MEDIUM** = next 30 percent
(0.50 to 0.80), **SLOW** = bottom 50 percent. This yields 100 / 150 / 250 medicines, which account for about 70 / 21 / 9 percent of units. It depends only on sales
history, so it adapts if the dataset changes.

## 7. Stockouts (`stockouts.sql`, `v_stockout_summary`)

* **Stockout day** = a branch-medicine-day with `fact_inventory.closing_quantity = 0` (end-of-day stock is zero).
* **Stockout rate** = stockout days / branch-medicine-days observed.
* **Stockout event** = the first day of an uninterrupted run of stockout days (a `LAG` window finds where a run starts).
* **Concentration:** share of all stockout days contributed by the top 10 and top 20 medicines (ranked by stockout days).
* Caveat: observed demand is censored on stockout days (sales cannot exceed stock) and the source does not record unmet demand.

## 8. Expiry analytics and expiry-risk method (`expiry.sql`, `v_expiry_risk`)

Lots are (branch, batch) pairs with `remaining_units = received - sold`. Value uses each batch's own purchase price.

* **Expired:** `expiry_date <= snapshot date`. The remaining units were written off on the expiry date, so they equal `fact_inventory.expired_quantity` (checked).
* **Near-expiry:** live lots with `days_to_expiry <= 90`, regardless of demand.
* **Expiry risk (live lots) is demand-aware and FEFO-aware.** Recent demand is the branch-medicine average over the last 90 days. The branch sells earliest-expiry lots first,
  so earlier-expiring lots of the same medicine consume projected demand first:

```
expected_sales_before_expiry = daily_demand_90d x days_to_expiry
units_ahead                  = remaining units of earlier-expiring live lots of the same branch+medicine
projected_sold               = LEAST(remaining, GREATEST(0, expected_sales_before_expiry - units_ahead))
projected_unsold_units       = remaining - projected_sold            (only when days_to_expiry <= 365, the projection horizon)
value_at_risk                = projected_unsold_units x batch purchase price
```

| risk_class | Rule |
|---|---|
| EXPIRED | expiry date has passed (written off) |
| CRITICAL | projected unsold units > 0 and expiry within 30 days |
| HIGH | projected unsold units > 0 and expiry within 90 days |
| MEDIUM | projected unsold units > 0 beyond 90 days, or expiring within 90 days but expected to sell out |
| SAFE | otherwise |

A lot with 100 units, 5 days to expiry and low demand projects most units unsold (CRITICAL), while 5 units with high demand and the same date project none unsold
(MEDIUM, a near-expiry watch item). The 365-day horizon avoids extrapolating demand far into the future. Additional reports: aging buckets, by category and branch, a
Branch > Category > Medicine roll-up, and the top 20 high-value expiring lots (`value_at_risk` rank) listing medicine, batch, branch, quantity, expiry date, days to expiry and cost value.

## 9. Purchases and suppliers (`purchases.sql`)

* Totals, by month, supplier, category and medicine. **Average purchase price** = `SUM(total_cost) / SUM(quantity)` (quantity-weighted).
* **Supplier ranking** by spend with medicines and categories supplied, average price and spend share. **Concentration** = share of total spend from the top 1, 5 and 10 suppliers.
* **Purchase price movement** (medicines with at least 10 delivery lines): first, latest, average, minimum and maximum unit purchase price, `price_change_pct = (latest - first) / first`,
  and a `significant_change` flag at +/-15 percent. Purchase cost is independent of selling price. A medicine's cost varies by supplier and lot, so this is realised cost movement, not a market trend.

## 10. Demand analytics (`demand.sql`, `v_demand_stats`)

The daily demand series is `fact_inventory.sold_quantity` (dense, so zero-sales days exist).

* average daily demand = `AVG(sold_quantity)`, weekly = daily x 7, monthly = daily x 365.25 / 12; `sales_days` and `zero_sales_days` are counts of days with and without sales.
* **Coefficient of variation** `CV = STDDEV_SAMP / AVG` (NULL if the mean is 0), reported for daily and for weekly units (complete ISO weeks).
* **Variability class** uses the weekly CV: **STABLE** < 0.5, **MODERATELY VARIABLE** < 1.0, **HIGHLY VARIABLE** >= 1.0, **NO DEMAND** if there were no sales.
  Weekly rather than daily, because daily counts of slow medicines have a Poisson floor `CV >= 1 / sqrt(mean)`: on a daily basis 85 percent of pairs would be "highly variable" regardless of behaviour.
  Even weekly, class correlates with volume (high-volume pairs are steadier), which is statistically expected.
* "Most variable / most stable medicine" is ranked on medicine-level weekly CV with a volume floor of 7 units per week, for the same Poisson reason. Category stability is the weekly CV of category demand
  (it includes trend and seasonality).

## 11. Seasonality (`demand.sql`)

For each category and calendar month (pooled over both years): `month_rate = units in that month / days in those months`;
`seasonal_index = month_rate / the category's overall daily rate` (1.00 = average day). The peak month, lowest month and
`amplitude = (max index - min index) / 2` are reported, plus the 12-column pivot. Computed entirely from observed sales (no generator parameters).
Result: Respiratory amplitude 0.21 (peak January), Antihistamines 0.20 (March), Antipyretics 0.18 (August), down to Cardiovascular 0.04 and Antidiabetic 0.03 (stable).

## 12. OLAP operations with MedStock examples (`olap.sql`)

| Operation | Meaning | Example in `olap.sql` |
|---|---|---|
| **Roll-up** | aggregate to a coarser hierarchy level; `GROUP BY ROLLUP` adds subtotals and a grand total | Day > Month > Quarter > Year with `GROUPING()` labels (765 rows); Category > Medicine subtotals |
| **Drill-down** | move to finer detail inside one member | Year > 2026 quarters > 2026-Q2 months > May 2026 days; Category > Respiratory medicines; Branch > BR001 categories > Respiratory medicines |
| **Slice** | fix one dimension member | 2026 sales only, by category |
| **Dice** | restrict several dimensions | 2026 + Respiratory + BR001/BR002, by branch and by quarter |
| **Pivot** | rotate a dimension into columns (conditional aggregation `FILTER`) | Branch x Year; Category x Branch (BR001..BR005); Month x Year |
| **Cube** | subtotals for every combination | Branch x Category in 2026 with `GROUP BY CUBE` |

## 13. Validation (`analytics/validation.sql`)

37 reconciliation checks, all PASS: analytics revenue/units/transactions equal the warehouse facts (monthly, yearly, weekly ISO, by medicine, category and branch); month-end and
current inventory reconcile to `purchases - sales - expired`; `COGS = purchases cost - closing value - expired value`; stockout days from the view, by branch and by category equal the zero-stock
rows of `fact_inventory`; expired and live-lot quantities and value equal `fact_inventory`; supplier/category/monthly purchases equal total cost; demand and seasonality units equal total units;
classifications cover every row. Two reference rows compare totals with the earlier warehouse validation (revenue 159,205,192.71 and 1,582,353 units).

## 14. Performance

Every analytic query is a full or near-full scan of the 1.0M-row sales or 1.8M-row inventory table plus joins to tiny dimensions, so the existing indexes (all dimension keys) are already used where a filter applies.
`EXPLAIN ANALYZE` showed the slowest statements were not missing an index: `COUNT(DISTINCT)` and window sorts spilled to disk under the default `work_mem` (4 MB), and one query scanned a view three times.
The fixes were a single-pass rewrite and a session-level `SET work_mem = '128MB'` in the runner, with no schema or index change. Typical queries take 0 to 3 s, the slowest about 8 s.
No materialized views or caching are used.

## 15. Reusing these outputs in the next phase

`v_medicine_performance` and `v_demand_stats` give per-medicine and per-branch features for clustering and demand models; `fact_sales` baskets (`transaction_id` with its medicine lines) are the
input for association mining; the daily series in `fact_inventory.sold_quantity` and the month/ISO-week keys in `dim_date` feed forecasting and anomaly detection.
