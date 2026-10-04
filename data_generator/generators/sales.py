"""Basket-based sales generation.

Per branch and day:
  1. number of transactions ~ Poisson(total realized lines / avg basket size)
  2. each basket starts with a medicine drawn proportional to realized demand
  3. extra items are drawn the same way (basket size distribution in config)
  4. latent association rules may add further medicines (probabilistic)
  5. each line is filled FEFO from branch stock; lines that cannot be filled
     (stock-out) are dropped, partially filled lines are shortened.
"""
import numpy as np
import pandas as pd

from .. import config as C
from ..utils import make_id

COLUMNS = [
    "transaction_id", "transaction_date", "branch_id", "medicine_id", "batch_id",
    "quantity", "unit_selling_price", "discount", "total_amount",
]


class SalesGenerator:
    def __init__(self, medicines, model, ledger, dates, rng):
        self.model, self.ledger, self.rng = model, ledger, rng
        self.dates = dates
        sizes = list(C.BASKET_SIZE_PROBS)
        self.sizes = np.array(sizes)
        self.size_p = np.array([C.BASKET_SIZE_PROBS[s] for s in sizes])
        self.avg_basket = float((self.sizes * self.size_p).sum())
        # Monthly selling price per medicine: base price +- small jitter.
        n_months = (dates[-1].year - dates[0].year) * 12 + dates[-1].month - dates[0].month + 1
        jit = C.SALES_CONFIG["monthly_price_jitter"]
        base = medicines["base_price"].to_numpy()
        self.price = np.round(base[None, :] * (1 + rng.uniform(-jit, jit, size=(n_months, len(base)))), 2)
        self.price = np.maximum(self.price, 0.01)
        self.first_month = (dates[0].year, dates[0].month)
        self.rows = []
        self.txn_count = 0
        self.lost_lines = 0       # lines with zero stock
        self.short_lines = 0      # lines partially filled
        self.lost_lines_by_med = np.zeros(model.M, dtype=np.int64)

    def generate_day(self, t, date):
        model, ledger, rng = self.model, self.ledger, self.rng
        month_idx = (date.year - self.first_month[0]) * 12 + date.month - self.first_month[1]
        prices = self.price[month_idx]
        M = model.M
        for b in range(model.B):
            w = model.realized_lines[t, b]
            total = w.sum()
            n_txn = int(rng.poisson(total / self.avg_basket))
            if n_txn == 0:
                continue
            p = w / total
            first = rng.choice(M, size=n_txn, p=p)
            sizes = rng.choice(self.sizes, size=n_txn, p=self.size_p)
            extras = rng.choice(M, size=int((sizes - 1).sum()), p=p)
            pos = 0
            for i in range(n_txn):
                basket = [int(first[i])]
                for _ in range(int(sizes[i]) - 1):
                    m = int(extras[pos])
                    pos += 1
                    if m not in basket:
                        basket.append(m)
                for a in list(basket):
                    for c, prob in model.rules.get(a, ()):
                        # an anomaly on the consequent scales its rule-driven demand too
                        prob = min(0.95, prob * model.anomaly_mult[t, b, c])
                        if c not in basket and rng.random() < prob:
                            basket.append(c)
                self._fill_basket(b, basket, date, prices)

    def _fill_basket(self, b, basket, date, prices):
        model, ledger, rng = self.model, self.ledger, self.rng
        txn_id = None
        for m in basket:
            want = 1 + int(rng.poisson(model.qty_lambda[m]))
            have = int(ledger.avail[b, m])
            if have <= 0:
                self.lost_lines += 1
                self.lost_lines_by_med[m] += 1
                continue
            if have < want:
                self.short_lines += 1
            for batch_id, qty in ledger.sell(b, m, min(want, have)):
                if txn_id is None:
                    self.txn_count += 1
                    txn_id = make_id("TXN", self.txn_count, 6)
                price = float(prices[m])
                gross = qty * price
                discount = 0.0
                if rng.random() < C.SALES_CONFIG["discount_prob"]:
                    pct = float(rng.choice(C.SALES_CONFIG["discount_pcts"]))
                    discount = round(gross * pct, 2)
                self.rows.append((txn_id, date, model.branch_ids[b], model.med_ids[m], batch_id,
                                  qty, price, discount, round(gross - discount, 2)))

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=COLUMNS)
