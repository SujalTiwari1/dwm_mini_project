# Sample files for the "Upload Data" demo

## Which set to use

| Set | Size | Pipeline time | Use it for |
|---|---|---|---|
| **Full** — `sample_data/full/` (generate with `python sample_data/make_demo_upload.py --full`) | 1,000,591 sales lines · 613,027 bills · 5 branches · 500 medicines · 2 years · 80,363 stock receipts (97 MB + 6 MB) | **about 17 minutes** | Showing *every* analysis exactly as rich as the built-in demo dataset |
| **Small** — `sales_demo.csv` + `purchases_demo.csv` (this folder) | 103k lines · 3 branches · 150 medicines · 11 months | about 1½ minutes | A quick live demonstration of the upload flow |

**Recommended for the mentor demo:** upload the *Full* set **before** the meeting and let it finish (it stays for 14 days, then is removed automatically); during the meeting show the progress screen with the small set live, then switch to the finished full dataset.

### What the full set produces (verified against the built-in demo)

The full export is the same data as the built-in synthetic dataset, rewritten as a store export (`Bill No, Bill Date, Store, Item Code, Item Name, Category, Qty, MRP, Discount` and `GRN Date, Store, Item Code, Batch No, Expiry, Supplier, Qty Received, Cost Price`). After upload:

| Result | Built-in demo | Uploaded full set |
|---|---|---|
| Revenue / units / bills | ₹15.92 cr / 1,582,353 / 613,027 | identical |
| Stock on the last day (rebuilt from purchases − sales − expiry) | 45,473 units | **identical** |
| Critical actions · overstocked pairs | 79 · 593 | identical |
| Expiring lots (critical / high) · critical stockouts | 40 / 19 · 47 | identical |
| Association rules · clustered medicines · anomalies | 14 · 500 · 8,159 | identical |
| Order-now · reorder-soon · high-priority actions | 171 · 280 · 352 | 172 · 279 · 411 |

The last row differs slightly on purpose: forecasts for uploads use the stock-free model (no tuning on your data), so a few borderline pairs rank differently. Forecast error on the full set: 0.398 / 0.307 / 0.239 (7/14/30 days) vs 0.404 / 0.316 / 0.254 for the 28-day average — the model beats the baseline at every horizon; the 80% range covers 80–81% of actual outcomes. Stage times: warehouse 2 min, analytics 2.5 min, association 22 s, clustering 20 s, anomalies 4 min, forecast 7.7 min, decisions 9 s.

---

Two CSV files that look like exports from a real pharmacy chain's own systems (column names differ from MedStock's on purpose).

| File | Contents |
|---|---|
| `sales_demo.csv` | 103,434 bill lines · 81,949 bills · 3 branches (BR001–BR003) · 150 medicines · 1 Jun 2025 – 30 Apr 2026 · revenue ≈ ₹1.40 crore |
| `purchases_demo.csv` | 7,950 stock-receipt (GRN) lines · 4,634 batches with expiry dates · 30 suppliers · opening balance on 1 Jun 2025 plus all receipts to 30 Apr 2026 |

Columns — sales: `Bill No, Bill Date, Store, Item Code, Item Name, Category, Qty, MRP, Discount`; purchases: `GRN Date, Store, Item Code, Batch No, Expiry, Supplier, Qty Received, Cost Price`.

It is a slice of the project's synthetic data, rewritten as a store export (`python sample_data/make_demo_upload.py` regenerates it identically). Say so if asked: the *data* is synthetic, the *upload pipeline* is what is being demonstrated.

## Demo script (about 5 minutes)

1. Start the app (`docker start medstock-postgres`, `uvicorn api.main:app`, `npm run dev`) and open **Upload Data**.
2. Drop **`sales_demo.csv`**. All columns are mapped automatically — point out the left column (MedStock field) vs your column (e.g. *Bill Date* → Date, *MRP* → Unit price).
3. Click **Choose purchases CSV** → `purchases_demo.csv` (again auto-mapped, including *Expiry* and *Batch No*).
4. Name it, click **Upload & analyze**. The progress screen shows the 7 stages (≈ 1½ minutes in total).
5. When it finishes click **Open dashboard** and show that the header dropdown now says *Demo Pharmacy Chain*; switch back to the original demo dataset to show both coexist.
6. Walk through the pages for the uploaded data (numbers below are what the pipeline produced):

| Page | What to point out |
|---|---|
| Dashboard / Sales | ₹1.40 crore revenue, 164,074 units, 81,949 transactions across 3 branches |
| Inventory | 10,784 units in stock, rebuilt from purchases − sales − expiry (first-expiry-first-out) |
| Insights | 14 association rules (e.g. Mupirocin ↔ Clotrimazole, lift ≈ 86); medicine clusters; anomalies |
| Forecast | 450 branch–medicine pairs, 7/14/30-day forecasts with an 80% range |
| Risk & Expiry | 14 critical + 61 high stockout risks, 5 critical + 2 high expiring lots |
| Decisions | 18 critical / 64 high actions, **38 "order now"**, 44 "reorder soon", 3,594 units to order, 89 overstocked pairs |

## Honest notes to have ready

- Forecast accuracy on this smaller set: error (WAPE) 0.36 / 0.28 / 0.22 at 7 / 14 / 30 days, **about level with the 28-day moving average** (0.35 / 0.27 / 0.22) — on 450 pairs the model has less to learn from than on the full 2,500-pair demo, where it beats the baselines by 3–7%. The 80% range covers 79–80% of actual outcomes.
- No opening-stock estimate was needed for these files (the register is consistent with the sales). If you upload sales that exceed recorded purchases, MedStock estimates opening stock and warns you.
- The analytics check "month-end stock = current stock" reports one failure because the data ends on 30 Apr (a month end, but the check is written for the full demo); it does not affect results.
- Delete the dataset afterwards from the Upload page (or it is removed automatically after 14 days).

## Try the error handling too (30 seconds)

Drop any `.xlsx` or a CSV without a quantity column: the app explains what is wrong instead of failing silently.
