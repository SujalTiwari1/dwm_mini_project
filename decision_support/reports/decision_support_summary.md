# MedStock Decision Support

> Synthetic data. This layer produces inventory-management recommendations only. It makes no clinical, prescribing or substitution recommendation, and it does not treat medicine associations as medical advice.

## 1. Objective

Turn the warehouse, analytics and ML demand forecasts into explainable recommendations that answer: what needs attention, why, how urgent it is, what action could be considered, and what evidence supports it. Every row carries its evidence (stock, demand, forecast, history, batch expiry) and a plain-language reason; there is no black-box score.

## 2. Decision Date

Decision date: **2026-12-31**, determined dynamically as the latest date of the warehouse inventory snapshot. Only information available on that date is used; the demand outlook is the ML forecast issued on that date (`future` split of `forecasts.csv`). A second run for 2026-09-30 proves that decisions never depend on later data (see Validation).

## 3. Inputs

- **Warehouse (as of the decision date):** stock and stock value, units sold in the last 7/28/30/90 days, stockout days (28, 90, all history), stockout events, weekly demand variability (26 blocks of 7 days), recent average selling price, and live batch lots (received minus sold, first-expiry-first-out).
- **ML forecasts:** 7, 14 and 30-day point forecasts and the upper bounds of the approximate 80% interval, for all 2,500 branch-medicine pairs (`ml_selected`).
- **Reused definitions:** low stock under 7 days of cover, overstock (no sales in 30 days or more than 90 days of cover) and the FEFO-aware expiry-risk method come from the analytics layer and are reconciled against its views.
- **Expected daily demand** = the larger of the 7-day forecast rate and the recent 28-day rate. The ML layer measured a systematic under-forecast of totals, and running out is costlier than holding a little extra, so the conservative choice is deliberate.

## 4. Stockout Risk

Days of cover = stock / expected daily demand (NULL, and the separate class NO_DEMAND_DATA, when expected demand is zero). CRITICAL: stock is zero or cover under 3 days. HIGH: under 7 days (the analytics low-stock line). MEDIUM: under 14. LOW: 14 or more. A MEDIUM or LOW pair is escalated by one level (never into CRITICAL) if it had 3 or more stockout days in the last 28 days or a historical stockout rate above 2.5%, or if its stock would last under 7 days at the upper forecast.

Result: CRITICAL 47, HIGH 330, MEDIUM 298, LOW 1825, NO_DEMAND_DATA 0 (of 2,500 pairs).

| branch_id | medicine_name | current_inventory_units | expected_daily_demand | cover | risk_level | primary_reason |
|---|---|---|---|---|---|---|
| BR001 | Paracetamol 500mg | 15 | 5.5714 | 2.69 | CRITICAL | 2.7 days of cover: 15 units in stock at expected demand of 5.57 units/day |
| BR001 | Diclofenac 50mg | 6 | 0.6071 | 9.88 | HIGH | 9.9 days of cover: 6 units in stock at expected demand of 0.61 units/day |
| BR001 | Amoxicillin 500mg | 5 | 0.8214 | 6.09 | HIGH | 6.1 days of cover: 5 units in stock at expected demand of 0.82 units/day |
| BR001 | Azithromycin 500mg | 4 | 0.3571 | 11.2 | HIGH | 11.2 days of cover: 4 units in stock at expected demand of 0.36 units/day |
| BR001 | Paracetamol 650mg | 1 | 3.7857 | 0.26 | CRITICAL | 0.3 days of cover: 1 units in stock at expected demand of 3.79 units/day |
| BR001 | Cetirizine 10mg | 22 | 4.7857 | 4.6 | HIGH | 4.6 days of cover: 22 units in stock at expected demand of 4.79 units/day |
| BR001 | Pantoprazole 40mg | 31 | 3.9286 | 7.89 | HIGH | 7.9 days of cover: 31 units in stock at expected demand of 3.93 units/day |
| BR001 | Metformin 500mg | 52 | 4.9643 | 10.47 | HIGH | 10.5 days of cover: 52 units in stock at expected demand of 4.96 units/day |

## 5. Reorder Recommendations

Planning assumptions (not in the data): lead time 7 days, service level 95% (z = 1.645), each order covers 14 days beyond the lead time, no minimum order quantity, no open orders. expected lead-time demand = expected daily demand x lead time; safety stock = z x daily demand std x sqrt(lead time) with daily std = weekly std / sqrt(7); reorder point = lead-time demand + safety stock; order quantity = ceil(max(0, reorder point + expected daily demand x order cover days - stock)). ORDER_NOW: stock <= lead-time demand. REORDER_SOON: stock below the reorder point. NO_REORDER otherwise. NO_DEMAND_DATA when no demand evidence exists.

Result: ORDER_NOW 171, REORDER_SOON 280, NO_REORDER 2049, NO_DEMAND_DATA 0; 14,431 units recommended in total.

| branch_id | medicine_name | current_inventory_units | reorder_point | recommended_order_quantity | priority |
|---|---|---|---|---|---|
| BR001 | Paracetamol 500mg | 15 | 49.26 | 113 | CRITICAL |
| BR001 | Amoxicillin 500mg | 5 | 8.92 | 16 | HIGH |
| BR001 | Paracetamol 650mg | 1 | 41.13 | 94 | CRITICAL |
| BR001 | Cetirizine 10mg | 22 | 40.2 | 86 | HIGH |
| BR001 | Metoprolol 50mg | 4 | 21.17 | 41 | CRITICAL |
| BR001 | Amoxicillin 250mg | 5 | 10.93 | 19 | HIGH |
| BR001 | Amoxicillin + Clavulanic Acid 375mg | 12 | 28.29 | 51 | HIGH |
| BR001 | Azithromycin 500mg (ApexLife Pharma) | 6 | 12.25 | 22 | HIGH |

## 6. Overstock Risk

Analytics definition, unchanged: OVERSTOCK = stock > 0 and (no units sold in the last 30 days or more than 90 days of cover). Binary classification (no data-driven threshold justifies a SEVERE level). Excess = units above 90 days of cover at the larger of the recent and forecast 30-day rate; value at average unit cost. A low-demand medicine is flagged only when its stock is large relative to its own demand.

Result: 593 overstock pairs, about 2,867 excess units, estimated excess value INR 211,770 (an estimate of exposure, not a loss).

| branch_id | medicine_name | current_inventory_units | days_of_cover | excess_units_estimate | excess_value_estimate |
|---|---|---|---|---|---|
| BR001 | Fexofenadine 120mg | 23 | 230.0 | 8 | 1176.22 |
| BR001 | Salbutamol Inhaler 100mcg | 11 | 110.0 | 1 | 125.79 |
| BR001 | Mupirocin Ointment 2% | 25 | 107.1 | 2 | 216.03 |
| BR001 | Naproxen 250mg | 12 | 360.0 | 5 | 285.74 |
| BR001 | Doxycycline 100mg | 19 | 285.0 | 6 | 342.73 |
| BR001 | Mefenamic Acid 250mg | 19 | 142.5 | 4 | 131.39 |

## 7. Expiry Actions

The analytics expiry-risk method is reused and reconciled lot by lot: recent 90-day demand is projected to the expiry date, earlier-expiring lots of the same branch and medicine sell first, and the projection horizon is 365 days. CRITICAL / HIGH (expected unsold units, expiry within 30 / 90 days) -> PRIORITIZE_SALE; MEDIUM -> MONITOR; LOW -> NO_ACTION. Only live batches are assessed. Inventory actions only. In the unified queue (not in this lot-level file) a CRITICAL/HIGH lot expecting less than 1 unit of waste ranks as MEDIUM, because a fraction of a unit should not outrank a real stockout.

Result over 5,500 live batch lots: CRITICAL 40, HIGH 19, MEDIUM 205, LOW 5236; projected at-risk cost value INR 25,110.

| branch_id | medicine_name | batch_id | batch_quantity | days_to_expiry | projected_unsold_units | projected_unsold_value | risk_level |
|---|---|---|---|---|---|---|---|
| BR001 | Diclofenac 50mg (Aarogya Formulations) | BAT034548 | 9 | 69 | 2.1 | 58.69 | HIGH |
| BR001 | Ibuprofen 200mg (VitaCure Remedies) | BAT034596 | 9 | 12 | 6.2 | 184.7 | CRITICAL |
| BR001 | Cefixime 100mg | BAT029966 | 8 | 30 | 6.67 | 667.87 | CRITICAL |
| BR001 | Mefenamic Acid 500mg (HealthAxis Pharma) | BAT034819 | 6 | 12 | 3.73 | 123.8 | CRITICAL |
| BR001 | Mefenamic Acid 500mg (TrueLife Remedies) | BAT033970 | 4 | 19 | 2.1 | 84.5 | CRITICAL |
| BR001 | Paracetamol Suspension 250mg/5ml (BlueCrest Pharma) | BAT026975 | 6 | 72 | 0.6 | 22.3 | HIGH |

## 8. Unified Action Queue

One row per branch x medicine. Explicit rules set the priority (the most severe of the stock-side, expiry and overstock issues); the primary action is the winning issue (ties: stock, then expiry, then overstock); all other active issues stay visible in `secondary_reasons`. `priority_score` = 400/300/200/100 by priority + 5 x active issues + min(impact / 1000, 50) and only orders rows inside a priority.

Priorities: CRITICAL 79, HIGH 352, MEDIUM 367, LOW 1702.

Top of the queue:

| queue_position | priority | branch_id | medicine_name | primary_action | primary_reason |
|---|---|---|---|---|---|
| 1 | CRITICAL | BR005 | Rosuvastatin 20mg (VitaCure Remedies) | ORDER_NOW | 1.2 days of cover: 12 units in stock at expected demand of 9.64 units/day. Stock 12 <= expected demand during the 7-day lead time (67.5): a stockout i |
| 2 | CRITICAL | BR003 | Rosuvastatin 5mg (NovaMed Laboratories) | ORDER_NOW | 2.7 days of cover: 19 units in stock at expected demand of 7.11 units/day. Stock 19 <= expected demand during the 7-day lead time (49.8): a stockout i |
| 3 | CRITICAL | BR002 | Dextromethorphan Syrup 100ml | PRIORITIZE_SALE_EXPIRING_STOCK | batch BAT034782 (9.0 days to expiry): 14 units expire in 9 days; expected sales before expiry 9.0 (recent demand 1.00/day, 0 units of earlier-expiring |
| 4 | CRITICAL | BR003 | Amoxicillin + Clavulanic Acid 375mg | ORDER_NOW | Out of stock with expected demand of 3.07 units/day (7-day forecast 21.5 units). Stock 0 <= expected demand during the 7-day lead time (21.5): a stock |
| 5 | CRITICAL | BR003 | Sitagliptin 50mg (NovaMed Laboratories) | ORDER_NOW | 2.2 days of cover: 4 units in stock at expected demand of 1.79 units/day. Stock 4 <= expected demand during the 7-day lead time (12.5): a stockout is  |
| 6 | CRITICAL | BR004 | Rosuvastatin 20mg (Stellar Formulations) | ORDER_NOW | 1.9 days of cover: 5 units in stock at expected demand of 2.68 units/day. Stock 5 <= expected demand during the 7-day lead time (18.8): a stockout is  |
| 7 | CRITICAL | BR005 | Sitagliptin 50mg (NovaMed Laboratories) | ORDER_NOW | Out of stock with expected demand of 0.79 units/day (7-day forecast 3.3 units). Stock 0 <= expected demand during the 7-day lead time (5.5): a stockou |
| 8 | CRITICAL | BR003 | Amlodipine 10mg (Stellar Formulations) | ORDER_NOW | 2.5 days of cover: 27 units in stock at expected demand of 11.00 units/day. Stock 27 <= expected demand during the 7-day lead time (77.0): a stockout  |
| 9 | CRITICAL | BR003 | Gliclazide 40mg (Summit Lifesciences) | ORDER_NOW | 1.7 days of cover: 8 units in stock at expected demand of 4.71 units/day. Stock 8 <= expected demand during the 7-day lead time (33.0): a stockout is  |
| 10 | CRITICAL | BR003 | Cefixime 100mg (VitaCure Remedies) | ORDER_NOW | Out of stock with expected demand of 2.30 units/day (7-day forecast 16.1 units). Stock 0 <= expected demand during the 7-day lead time (16.1): a stock |
| 11 | CRITICAL | BR005 | Cefixime 100mg (VitaCure Remedies) | ORDER_NOW | 2.9 days of cover: 10 units in stock at expected demand of 3.43 units/day. Stock 10 <= expected demand during the 7-day lead time (24.0): a stockout i |
| 12 | CRITICAL | BR002 | Montelukast + Levocetirizine 10mg/5mg | ORDER_NOW | Out of stock with expected demand of 1.39 units/day (7-day forecast 6.8 units). Stock 0 <= expected demand during the 7-day lead time (9.8): a stockou |

## 9. Business Impact

All amounts are potential exposure or estimates, never actual financial losses.

- Potential stockout exposure: 1,110 units, INR 111,696 (potential revenue exposure: demand expected during the lead time that current stock does not cover, at recent average selling price (not an actual loss)).
- Estimated overstock value: INR 211,770 (estimated cost value of units above 90 days of cover (not an actual loss)).
- Projected expiry exposure: INR 25,110 (projected at-risk cost value of batch units expected to remain unsold at expiry (not an actual loss)).

## 10. Validation

75 checks, 0 failures. Areas: expiry, leakage, overstock, queue, reconciliation, reorder, scenarios, stockout. The decision-time test rebuilds the decision for 2026-09-30 and shows that its inputs equal an independent recomputation from data truncated at that date and do not change when every later observation is scrambled; the ML forecast used was issued on that date by a model trained on earlier targets only. Reconciliation ties inventory, stockout days, overstock status, expiry lots and forecasts to the analytics views and `forecasts.csv`. Five deterministic scenarios (zero stock, large stock with no demand, an expiring batch, healthy stock, no reliable demand) plus an escalation case pass.

## 11. Planning Assumptions

These are NOT present in, or learned from, the synthetic dataset:
- supplier lead time = 7 days (the data records receipt dates only, not order dates)
- service level 95% for safety stock (a planning assumption, not an optimised value)
- each order covers 14 days of demand beyond the lead time
- no minimum order quantities, pack sizes or supplier availability limits; open (in-transit) orders assumed to be zero
- queue materiality for expiry: lots expecting under 1 unit of waste rank as MEDIUM
- stockout level cut-offs (3, 7, 14 days), the escalation rule (3 stockout days in 28, or a 2.5% stockout rate) and the materiality threshold for overstock priority (INR 2,500 excess value) are business parameters in `config.py`

## 12. Limitations

- Forecasts are estimates (the ML layer reports an under-forecast bias and an approximate 80% interval); decisions inherit that uncertainty.
- Stockout history censors observed demand, so recent demand may understate true demand for pairs that were out of stock.
- Lead time, service level and order cover are assumptions; recommended quantities are only as good as those assumptions and ignore supplier constraints.
- The expiry method uses trailing demand and does not model returns, transfers between branches or discounting.
- Exposure figures mix revenue (stockout) and cost (overstock, expiry) bases and are potential exposures, not losses; their sum is used only to order rows.
- Upstream boundary finding: for pairs with exactly 90.0 days of cover (for example 12 units and 4 sold in 30 days) the analytics view labels OVERSTOCK because its decimal division rounds 4/30 up. This layer applies the rule exactly (90.0 is not over 90), so those pairs are NORMAL here. The analytics view was not changed; the reconciliation check lists the boundary pairs.
- Synthetic data: results show how the method works, not what a real pharmacy should order.
- Inventory management only: no clinical recommendation of any kind.

## 13. Reproducibility

The engine is deterministic: no random numbers are used, all orderings are explicit, and inputs are the warehouse as of the decision date and the fixed forecast file. Running `python -m decision_support.run` twice gives identical reports except `run_timestamp` and `runtime_seconds` in `decision_summary.json`. Python 3.11.0.
