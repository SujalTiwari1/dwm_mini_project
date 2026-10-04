"""Demand model.

Builds, for every (day, branch, medicine), the *expected* number of sale
lines and a *realized* number (expected x lognormal noise x anomaly
multiplier). The realized values are later used as sampling weights for
basket generation; the expected values (units) drive the reorder policy.

Demand per medicine/branch/day =
    base_lines[profile] x branch_multiplier x branch-category affinity
    x day-of-week x (1 + seasonal amplitude x cos(annual cycle))
    x exp(trend x t) x noise(variability) x anomaly multiplier
"""
import numpy as np
import pandas as pd

from .. import config as C


class DemandModel:
    def __init__(self, medicines, internal, branches, dates, rng):
        cat_cfg = C.CATEGORY_CONFIG
        M, B, T = len(medicines), len(branches), len(dates)
        self.M, self.B, self.T = M, B, T
        self.dates = dates
        self.med_ids = medicines["medicine_id"].tolist()
        self.branch_ids = branches["branch_id"].tolist()
        profiles = medicines["demand_profile"].tolist()
        cats = medicines["category_id"].tolist()

        # ---- per-medicine parameters --------------------------------------
        lo = np.array([C.DEMAND_PROFILES[p]["base_lines"][0] for p in profiles])
        hi = np.array([C.DEMAND_PROFILES[p]["base_lines"][1] for p in profiles])
        skew = np.array([C.DEMAND_PROFILES[p]["skew"] for p in profiles])
        base = (lo + (hi - lo) * rng.beta(skew[:, 0], skew[:, 1])) * C.DATASET_CONFIG["demand_scale"]
        self.base = base
        vlo = np.array([C.DEMAND_PROFILES[p]["variability"][0] for p in profiles])
        vhi = np.array([C.DEMAND_PROFILES[p]["variability"][1] for p in profiles])
        vscale = np.array([cat_cfg[c]["variability_scale"] for c in cats])
        variability = rng.uniform(vlo, vhi) * vscale
        amp = np.array([cat_cfg[c]["season_amp"] for c in cats]) * rng.uniform(0.6, 1.4, M)
        peak = np.array([cat_cfg[c]["season_peak_doy"] for c in cats]) + rng.normal(0, 15, M)
        labels = list(C.TREND_MIX)
        trend_label = rng.choice(labels, size=M, p=[C.TREND_MIX[k] for k in labels])
        rate = np.array([rng.uniform(*C.TREND_ANNUAL_RATE[k]) for k in trend_label])
        qty_lambda = np.array([cat_cfg[c]["qty_lambda"] for c in cats])
        self.mean_qty = 1.0 + qty_lambda
        self.qty_lambda = qty_lambda

        # ---- per-branch parameters ----------------------------------------
        cat_ids = [c[0] for c in C.CATEGORIES]
        branch_mult = np.zeros(B)
        branch_aff = {}
        for b in range(B):
            if b < len(C.BRANCH_PROFILES):
                bp = C.BRANCH_PROFILES[b]
                branch_mult[b] = bp["multiplier"]
                branch_aff[b] = dict(bp["category_affinity"])
            else:
                branch_mult[b] = rng.uniform(*C.RANDOM_BRANCH_MULTIPLIER)
                picks = rng.choice(len(cat_ids), size=int(rng.integers(1, 3)), replace=False)
                branch_aff[b] = {cat_ids[j]: float(rng.uniform(*C.RANDOM_BRANCH_AFFINITY)) for j in picks}
        affinity = np.array([[branch_aff[b].get(c, 1.0) for c in cats] for b in range(B)])  # [B, M]
        self.branch_mult, self.branch_aff = branch_mult, branch_aff

        # ---- time factors ---------------------------------------------------
        doy = np.array([d.dayofyear for d in dates])
        dow = np.array([C.DOW_FACTORS[d.dayofweek] for d in dates])
        tdays = np.arange(T)
        season = 1 + amp[None, :] * np.cos(2 * np.pi * (doy[:, None] - peak[None, :]) / 365.25)
        trend = np.exp(rate[None, :] * tdays[:, None] / 365.25)
        static = base[None, :] * affinity * branch_mult[:, None]                      # [B, M]
        self.expected_lines = dow[:, None, None] * (season * trend)[:, None, :] * static[None, :, :]
        self.expected_units = self.expected_lines * self.mean_qty[None, None, :]

        noise = np.exp(rng.normal(-(variability ** 2) / 2, variability, size=(T, B, M)))
        self.rules = {}  # medicine_idx -> [(consequent_idx, prob)]
        self.resolved_rules = []
        self._resolve_rules(internal)
        # Forecast used by the replenishment planner: baseline demand plus the extra lines that the
        # (latent) association rules add to consequents, so planning is not systematically biased.
        extra = np.zeros_like(self.expected_lines)
        for a_idx, lst in self.rules.items():
            for c_idx, prob in lst:
                extra[:, :, c_idx] += prob * self.expected_lines[:, :, a_idx]
        self.forecast_units = (self.expected_lines + extra) * self.mean_qty[None, None, :]
        self.anomalies, anomaly_mult = self._generate_anomalies(rng)
        self.realized_lines = self.expected_lines * noise * anomaly_mult
        self.anomaly_mult = anomaly_mult   # also scales rule-driven (association) demand in sales

        # bulk-purchase anomalies keyed by day index -> {medicine_idx: record}
        self.bulk_by_day = {}
        for a in self.anomalies:
            if a["type"] == "bulk_purchase":
                self.bulk_by_day.setdefault(a["_day"], {})[a["_m"]] = a

        self.disruptions = [a for a in self.anomalies if a["type"] == "supply_disruption"]
        # ---- private metadata ----------------------------------------------
        self.params = pd.DataFrame({
            "medicine_id": self.med_ids,
            "category_id": cats,
            "demand_profile": profiles,
            "base_demand_lines_per_day": base.round(3),
            "demand_variability": variability.round(3),
            "seasonality_amplitude": amp.round(3),
            "seasonality_peak_day_of_year": peak.round(1),
            "seasonality_level": ["low" if a < 0.06 else "medium" if a < 0.14 else "high" for a in amp],
            "trend": trend_label,
            "trend_annual_rate": rate.round(3),
            "mean_units_per_line": self.mean_qty.round(2),
        })

    # ------------------------------------------------------------------
    def _generate_anomalies(self, rng):
        cfg = C.ANOMALY_CONFIG
        M, B, T = self.M, self.B, self.T
        mult = np.ones((T, B, M))
        n = max(cfg["min_events"], int(round(cfg["rate_per_medicine_year"] * M * T / 365.25)))
        types = list(cfg["type_weights"])
        # stratified allocation (largest remainder) so every type appears in proportion to its weight
        raw = np.array([cfg["type_weights"][t] for t in types]) * n
        counts = np.floor(raw).astype(int)
        for k in np.argsort(-(raw - counts))[: n - counts.sum()]:
            counts[k] += 1
        drawn = rng.permutation(np.repeat(types, counts))
        pick_p = np.sqrt(self.base) / np.sqrt(self.base).sum()   # favour medicines with visible volume
        min_dev = cfg["min_expected_deviation_lines"]
        windows = {}   # medicine idx -> [(start, end)] demand windows already used
        events = []

        def free(m, start, end):
            return all(end <= s0 or start >= e0 for s0, e0 in windows.get(m, []))

        for i, typ in enumerate(drawn):
            rec = {"anomaly_id": f"ANOM{i + 1:03d}", "type": str(typ)}
            if typ == "bulk_purchase":
                m = int(rng.choice(M, p=pick_p))
                day = int(rng.integers(min(3, T - 1), max(4, T - 15)))
                rec.update(medicine_id=self.med_ids[m], _m=m, branch_id="ALL",
                           start_date=str(self.dates[day].date()), end_date=str(self.dates[day].date()),
                           _day=day, multiplier=round(float(rng.uniform(*cfg["bulk_purchase"]["multiplier"])), 2),
                           purchase_ids=[])
                events.append(rec)
                continue
            lo_d, hi_d = cfg[typ]["duration"]
            for _attempt in range(30):
                m = int(rng.choice(M, p=pick_p))
                dur = int(rng.integers(lo_d, hi_d + 1))
                start = int(rng.integers(min(3, T - 1), max(4, T - cfg.get("max_duration", 30) - 5)))
                if typ == "supply_disruption":
                    extra = int(rng.integers(cfg[typ]["extra_lead_days"][0], cfg[typ]["extra_lead_days"][1] + 1))
                    end = min(T, start + dur)
                    if free(m, start, end):
                        break
                    continue
                b = int(rng.integers(B)) if typ == "branch_surge" else None
                m_val = float(rng.uniform(*cfg[typ]["multiplier"]))
                share = self.expected_lines[:, :, m].mean(axis=0)            # per-branch daily baseline
                daily = share[b] if b is not None else share.sum()
                # visibility guard: deviation measured relative to the medicine's own baseline
                dur = min(dur, T - start - 1)
                while dur < cfg["max_duration"] and abs(m_val - 1) * daily * dur < min_dev and start + dur < T - 1:
                    dur += 1
                if typ == "drop":
                    ok = (1 - m_val) * daily * dur >= min_dev
                else:
                    if (m_val - 1) * daily * dur < min_dev:
                        m_val = min(cfg["max_spike_multiplier"], 1 + min_dev / (daily * dur))
                    ok = (m_val - 1) * daily * dur >= min_dev
                end = min(T, start + dur)
                if ok and free(m, start, end):
                    break
            else:
                continue   # could not place a visible, non-overlapping event; skip it
            windows.setdefault(m, []).append((start, end))
            if typ == "supply_disruption":
                rec.update(medicine_id=self.med_ids[m], _m=m, branch_id="ALL", start_date=str(self.dates[start].date()),
                           end_date=str(self.dates[end - 1].date()), extra_lead_days=extra, _day=start, _end=end)
            else:
                if b is not None:
                    mult[start:end, b, m] *= m_val
                else:
                    mult[start:end, :, m] *= m_val
                rec.update(medicine_id=self.med_ids[m], _m=m,
                           branch_id=self.branch_ids[b] if b is not None else "ALL",
                           start_date=str(self.dates[start].date()), end_date=str(self.dates[end - 1].date()),
                           multiplier=round(m_val, 2), _day=start, _end=end)
            events.append(rec)
        for k, rec in enumerate(events):
            rec["anomaly_id"] = f"ANOM{k + 1:03d}"
        return events, mult

    def _resolve_rules(self, internal):
        key_to_idx = {}
        for i, (k, is_var) in enumerate(zip(internal["key"], internal["is_variant"])):
            if not is_var:
                key_to_idx[k] = i
        for a_key, c_key, p in C.ASSOCIATION_RULES:
            if a_key in key_to_idx and c_key in key_to_idx:
                a, c = key_to_idx[a_key], key_to_idx[c_key]
                self.rules.setdefault(a, []).append((c, p))
                self.resolved_rules.append({
                    "antecedent_id": self.med_ids[a], "consequent_id": self.med_ids[c], "added_probability": p,
                })

    def public_anomalies(self):
        return [{k: v for k, v in a.items() if not k.startswith("_")} for a in self.anomalies]
