"""POST-HOC evaluation of the anomaly detectors against the synthetic generator's hidden ground truth.

This is the ONLY module that reads data/metadata/ground_truth_private.json. It runs after anomalies.csv has been written; the ground truth never
reaches feature engineering, thresholds, or model fitting. It is an evaluation of detectors on synthetic data, not a model input.

Matching design (fixed in advance, not tuned on the ground truth)
  * A ground-truth event is a window for one medicine (and, for a branch surge, one branch).
  * Demand events (spike, drop, branch surge): a flag on day t counts if start <= t <= end + 6 (the 7-day detector window ending at t overlaps the event).
  * Supply disruption: deliveries are delayed by extra_lead_days, so the effect appears in [start, end + extra_lead_days + 14].
  * Bulk purchase: the receipt date(s) of the purchase lines that the generator created for it, +/- 1 day.
  * Recall is measured per ground-truth event, in two ways: STRICT (a flag of a compatible detected type) and ANY-FLAG (any flag for that medicine in the window).
  * Precision is measured per detected EPISODE (flags of one series within 3 days merge). An episode is a true positive if it overlaps a compatible event window
    of the same medicine. Episodes the detector could not type ("unclassified") are compatible with every event type.
"""
import json
import time

import pandas as pd

from .. import config as C
from ..anomaly.detect import build_episodes

LABEL = "post-hoc evaluation against synthetic ground truth (NOT model input)"
TOLERANCE_AFTER = C.ANOMALY["short_window"] - 1
COMPATIBLE = {
    "spike": {"demand_spike"}, "drop": {"demand_drop"}, "branch_surge": {"demand_spike"},
    "bulk_purchase": {"inventory_anomaly"}, "supply_disruption": {"supply_delay", "stockout_pattern"},
}


def load_ground_truth():
    """The single place where the hidden ground truth is read."""
    return json.loads(C.GROUND_TRUTH_PRIVATE.read_text(encoding="utf-8"))


def _events(gt, conn):
    ids = [pid for a in gt["anomalies"] if a["type"] == "bulk_purchase" for pid in a.get("purchase_ids", [])]
    receipt = {}
    if ids:
        res = conn.exec_driver_sql(
            "SELECT p.purchase_id, d.full_date FROM warehouse.fact_purchase p JOIN warehouse.dim_date d ON d.date_key = p.date_key "
            "WHERE p.purchase_id = ANY(%s)", (ids,)).fetchall()
        receipt = {r[0]: pd.Timestamp(r[1]) for r in res}
    events = []
    for a in gt["anomalies"]:
        typ, start, end = a["type"], pd.Timestamp(a["start_date"]), pd.Timestamp(a["end_date"])
        if typ in ("spike", "drop", "branch_surge"):
            lo, hi = start, end + pd.Timedelta(days=TOLERANCE_AFTER)
        elif typ == "supply_disruption":
            lo, hi = start, end + pd.Timedelta(days=int(a["extra_lead_days"]) + 14)
        else:  # bulk_purchase
            dates = [receipt[p] for p in a.get("purchase_ids", []) if p in receipt]
            if not dates:
                continue                        # the order never arrived inside the calendar: nothing observable
            lo, hi = min(dates) - pd.Timedelta(days=1), max(dates) + pd.Timedelta(days=1)
        events.append({"id": a["anomaly_id"], "type": typ, "medicine_id": a["medicine_id"], "branch_id": a["branch_id"], "lo": lo, "hi": hi})
    return events


def _compat(event, ep):
    if ep["anomaly_type"] != "unclassified" and ep["anomaly_type"] not in COMPATIBLE[event["type"]]:
        return False
    if event["type"] == "branch_surge" and ep["grain"] == "branch_medicine" and ep["branch_id"] != event["branch_id"]:
        return False
    return True


def _score_set(flags, events):
    """flags: DataFrame of flagged rows for one detector set."""
    eps = build_episodes(flags)
    by_med = {}
    for e in events:
        by_med.setdefault(e["medicine_id"], []).append(e)
    flag_dates = {}
    if not flags.empty:
        fd = flags.assign(date=pd.to_datetime(flags["date"]))
        for med, g in fd.groupby("medicine_id"):
            flag_dates[med] = g["date"].to_numpy()
    ep_tp = []
    for _, ep in eps.iterrows():
        ok = any(_compat(e, ep) and ep["start"] <= e["hi"] and ep["end"] >= e["lo"] for e in by_med.get(ep["medicine_id"], []))
        ep_tp.append(ok)
    eps["matched"] = ep_tp
    ev_rows = []
    for e in events:
        strict = ((eps["medicine_id"] == e["medicine_id"]) & eps["matched"] & (eps["start"] <= e["hi"]) & (eps["end"] >= e["lo"]) &
                  eps.apply(lambda ep: _compat(e, ep), axis=1)).any() if len(eps) else False
        d = flag_dates.get(e["medicine_id"])
        any_flag = bool(d is not None and ((d >= e["lo"].to_datetime64()) & (d <= e["hi"].to_datetime64())).any())
        ev_rows.append({**{k: e[k] for k in ("id", "type", "medicine_id", "branch_id")}, "detected_strict": bool(strict), "detected_any_flag": any_flag})
    return eps, pd.DataFrame(ev_rows)


def evaluate(conn, anomalies_csv_path, detection_finished_at):
    anomalies = pd.read_csv(anomalies_csv_path)
    read_at = time.time()
    gt = load_ground_truth()
    events = _events(gt, conn)
    sets = {
        "statistical": anomalies[anomalies["is_statistical_anomaly"]],
        "isolation_forest": anomalies[anomalies["is_isolation_anomaly"]],
        "combined_both_methods": anomalies[anomalies["combined_anomaly"]],
        "either_method": anomalies,
    }
    result = {"label": LABEL, "ground_truth_events": len(events), "ground_truth_events_by_type": pd.Series([e["type"] for e in events]).value_counts().to_dict(),
              "ground_truth_read_after_detection_files_written": bool(detection_finished_at <= read_at),
              "matching": {"demand_event_window": f"start .. end + {TOLERANCE_AFTER} days", "supply_disruption_window": "start .. end + extra_lead_days + 14 days",
                           "bulk_purchase_window": "receipt date +/- 1 day", "episode_gap_days": C.ANOMALY["episode_gap_days"]},
              "detector_sets": {}}
    by_type_rows = []
    for name, flags in sets.items():
        eps, evs = _score_set(flags, events)
        tp_ev, fn_ev = int(evs["detected_strict"].sum()), int((~evs["detected_strict"]).sum())
        tp_ep, fp_ep = int(eps["matched"].sum()), int((~eps["matched"]).sum()) if len(eps) else 0
        precision = tp_ep / (tp_ep + fp_ep) if (tp_ep + fp_ep) else 0.0
        recall = tp_ev / (tp_ev + fn_ev) if (tp_ev + fn_ev) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        result["detector_sets"][name] = {
            "flagged_rows": int(len(flags)), "episodes": int(len(eps)), "true_positive_episodes": tp_ep, "false_positive_episodes": fp_ep,
            "events_detected_strict": tp_ev, "events_missed_strict": fn_ev, "events_total": int(len(evs)),
            "precision_episode_level": round(precision, 4), "recall_event_level_strict": round(recall, 4),
            "recall_event_level_any_flag": round(float(evs["detected_any_flag"].mean()), 4) if len(evs) else 0.0, "f1": round(f1, 4)}
        for typ, g in evs.groupby("type"):
            by_type_rows.append({"detector_set": name, "view": "ground_truth_event_recall", "type": typ, "total": int(len(g)),
                                 "matched": int(g["detected_strict"].sum()), "unmatched": int((~g["detected_strict"]).sum()),
                                 "rate": round(float(g["detected_strict"].mean()), 4), "rate_any_flag": round(float(g["detected_any_flag"].mean()), 4)})
        if len(eps):
            for typ, g in eps.groupby("anomaly_type"):
                by_type_rows.append({"detector_set": name, "view": "detected_episode_precision", "type": typ, "total": int(len(g)),
                                     "matched": int(g["matched"].sum()), "unmatched": int((~g["matched"]).sum()),
                                     "rate": round(float(g["matched"].mean()), 4), "rate_any_flag": None})
    result["notes"] = [
        "Thresholds were fixed before this step and not tuned on the ground truth.",
        "Precision is conservative: a flag on a medicine whose demand moved because another (planted) medicine moved (a rule-driven knock-on), "
        "or a long natural stockout, is real behaviour in the data but not a labelled event, so it counts as a false positive here.",
        "Detected 'unclassified' episodes are compatible with every event type; they cannot be credited to a specific type.",
        "Ground truth covers 5 event types; the detectors also report types (stockout_pattern, purchase_price_anomaly) that have no labelled counterpart except through supply disruption.",
    ]
    return result, pd.DataFrame(by_type_rows), read_at
