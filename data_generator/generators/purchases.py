"""Purchase planning (replenishment policy).

Each day, for every medicine whose *inventory position* (on hand + already
ordered) at some branch has fallen below its reorder point, one manufacturing
lot is ordered from one supplier for the branches that need stock. The order
arrives after a supplier-dependent lead time (with jitter, occasional random
delays and anomalous supply disruptions); the purchase is recorded on the
arrival date, when the stock actually enters inventory. The very first day
receives immediate opening stock.

Reorder point, cover and MOQ depend on the demand profile and are jittered per
medicine, so some medicines are managed tightly (stockouts are possible) and
slow movers over-stock (expiry risk).
"""
from collections import defaultdict

import numpy as np
import pandas as pd

from .. import config as C
from ..utils import make_id

COLUMNS = [
    "purchase_id", "purchase_date", "branch_id", "supplier_id", "medicine_id",
    "batch_id", "quantity", "unit_purchase_price", "total_cost",
]


class PurchasePlanner:
    def __init__(self, medicines, internal, model, supplier_map, supplier_internal,
                 batch_factory, ledger, rng):
        self.model, self.ledger, self.rng = model, ledger, rng
        self.supplier_map, self.supplier_internal = supplier_map, supplier_internal
        self.batch_factory = batch_factory
        profs = medicines["demand_profile"].tolist()
        P, M = C.DEMAND_PROFILES, len(profs)
        jlo, jhi = C.PURCHASE_CONFIG["policy_jitter"]
        self.rop = np.array([P[p]["reorder_point_days"] for p in profs], dtype=float) * rng.uniform(jlo, jhi, M)
        self.cover = np.array([P[p]["target_cover_days"] for p in profs], dtype=float) * rng.uniform(jlo, jhi, M)
        self.cover = np.maximum(self.cover, self.rop + 3)
        self.moq = np.array([P[p]["moq_units"] for p in profs], dtype=float)
        if C.PURCHASE_CONFIG["scale_moq_with_demand"]:
            self.moq = np.maximum(self.moq * C.DATASET_CONFIG["demand_scale"], C.PURCHASE_CONFIG["min_moq_units"])
        self.floor = float(C.PURCHASE_CONFIG["min_reorder_point_units"])
        self.base_price = medicines["base_price"].to_numpy()
        self.shelf = internal["shelf_life_months"].tolist()
        self.med_ids = model.med_ids
        self.branch_ids = model.branch_ids
        self.pipeline = np.zeros((model.B, M), dtype=np.int64)   # ordered, not yet received
        self.in_transit = defaultdict(list)                      # arrival day index -> orders
        self.rows = []

    # ------------------------------------------------------------------
    def plan_day(self, t, date, dates):
        for order in self.in_transit.pop(t, []):
            self._receive(order, date)

        exp = self.model.forecast_units[t]            # [B, M] expected units incl. association-driven demand
        position = self.ledger.avail + self.pipeline
        below_rop = position < np.maximum(exp * self.rop[None, :], self.floor)
        forced = self.model.bulk_by_day.get(t, {})
        cand = sorted(set(np.flatnonzero(below_rop.any(axis=0)).tolist()) | set(forced))
        for m in cand:
            target = np.maximum(exp[:, m] * self.cover[m], 2 * self.floor)
            if m in forced:
                need = np.ceil(target)
            else:
                need = np.where(below_rop[:, m], np.ceil(target - position[:, m]), 0)
            need = np.maximum(need, 0).astype(np.int64)
            total = int(need.sum())
            if total == 0:
                continue
            if total < self.moq[m]:
                share = exp[:, m] / exp[:, m].sum()
                need = need + np.ceil((self.moq[m] - total) * share).astype(np.int64)
            if m in forced:      # unusual purchase: a multiple of the normal (MOQ-respecting) lot
                need = np.ceil(need * forced[m]["multiplier"]).astype(np.int64)
            self._order(m, need, t, date, forced.get(m))

    def _order(self, m, need, t, date, anomaly):
        cfg = C.PURCHASE_CONFIG
        sups, weights = self.supplier_map[self.med_ids[m]]
        sid = sups[int(self.rng.choice(len(sups), p=weights))]
        ratio = self.rng.uniform(*cfg["purchase_price_ratio"])
        price = max(round(float(self.base_price[m] * ratio * self.supplier_internal[sid]["price_factor"]), 2), 0.01)
        order = {"m": m, "sid": sid, "price": price, "need": need, "anomaly": anomaly}
        if t == 0:
            lead = 0                                   # opening stock
        else:
            lead = self.supplier_internal[sid]["lead_time_days"] + int(
                self.rng.integers(cfg["lead_noise_days"][0], cfg["lead_noise_days"][1] + 1))
            if self.rng.random() < cfg["delay_prob"]:
                lead += int(self.rng.integers(cfg["delay_days"][0], cfg["delay_days"][1] + 1))
            for d in self.model.disruptions:
                if d["_m"] == m and d["_day"] <= t < d["_end"]:
                    lead += d["extra_lead_days"]
            lead = max(lead, 1)
        order["piped"] = lead > 0
        if lead == 0:
            self._receive(order, date)
        else:
            self.pipeline[:, m] += need
            self.in_transit[t + lead].append(order)   # orders arriving after the last day are never received

    def _receive(self, order, date):
        m, sid, price, need = order["m"], order["sid"], order["price"], order["need"]
        med_id = self.med_ids[m]
        batch_id, expiry = self.batch_factory.create(med_id, sid, date, self.shelf[m], price, int(need.sum()),
                                                  self.supplier_internal[sid]["near_dated_prob"],
                                                  allow_near_dated=order["anomaly"] is None)  # bulk buys are fresh stock
        for b in np.flatnonzero(need):
            qty = int(need[b])
            pid = make_id("PUR", len(self.rows) + 1, 6)
            self.rows.append((pid, date, self.branch_ids[b], sid, med_id, batch_id,
                              qty, price, round(qty * price, 2)))
            self.ledger.receive(int(b), m, batch_id, expiry, qty)
            if order["anomaly"] is not None:
                order["anomaly"]["purchase_ids"].append(pid)
        if order["piped"]:
            self.pipeline[:, m] -= need

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=COLUMNS)
