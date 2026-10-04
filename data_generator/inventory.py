"""In-memory inventory ledger keyed by (branch, medicine, batch).

Inventory is never generated directly: it only changes through receive()
(purchases), sell() (sales) and expire() (written off at expiry).
"""
from collections import defaultdict

import numpy as np


class InventoryLedger:
    def __init__(self, n_branches: int, n_medicines: int):
        self.avail = np.zeros((n_branches, n_medicines), dtype=np.int64)  # sellable (non-expired) units
        self.lots = defaultdict(list)       # (b, m) -> [[batch_id, expiry_date, qty], ...] sorted by expiry (FEFO)
        self.expiring = defaultdict(list)   # expiry_date -> [(b, m, lot)]
        self.expired_log = []               # (date, b, m, batch_id, qty)

    def receive(self, b, m, batch_id, expiry, qty):
        lot = [batch_id, expiry, int(qty)]
        self.lots[(b, m)].append(lot)
        self.lots[(b, m)].sort(key=lambda x: x[1])
        self.expiring[expiry].append((b, m, lot))
        self.avail[b, m] += qty

    def expire(self, date):
        """Write off lots that reach their expiry date (unsellable from that day)."""
        for b, m, lot in self.expiring.pop(date, []):
            if lot[2] > 0:
                self.avail[b, m] -= lot[2]
                self.expired_log.append((date, b, m, lot[0], lot[2]))
                lot[2] = 0
                self.lots[(b, m)].remove(lot)

    def sell(self, b, m, qty):
        """Take up to qty units, earliest-expiry-first. Returns [(batch_id, qty)]."""
        out = []
        remaining = int(qty)
        for lot in self.lots[(b, m)]:
            if remaining <= 0:
                break
            take = min(lot[2], remaining)
            if take > 0:
                lot[2] -= take
                remaining -= take
                out.append((lot[0], take))
        self.lots[(b, m)] = [lot for lot in self.lots[(b, m)] if lot[2] > 0]
        sold = sum(q for _, q in out)
        self.avail[b, m] -= sold
        return out

    def on_hand_units(self) -> int:
        return int(self.avail.sum())

    def expired_units(self) -> int:
        return int(sum(e[4] for e in self.expired_log))
