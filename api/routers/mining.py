"""Data Mining and ML forecasting: serve the already-generated reports. No algorithm is run here."""
import json
from enum import IntEnum

from fastapi import APIRouter, Query

from ..database import list_response, load_report, to_records
from ..schemas import ListResponse

class Horizon(IntEnum):
    week = 7
    two_weeks = 14
    month = 30


mining = APIRouter(prefix="/api/mining", tags=["Data mining"])
forecasts = APIRouter(prefix="/api/forecasts", tags=["ML forecasting"])

Limit = Query(100, ge=1, le=1000, description="Maximum rows to return")
Offset = Query(0, ge=0, description="Rows to skip (pagination)")
Branch = Query(None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$", description="Branch id, e.g. BR001")
Medicine = Query(None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$", description="Medicine id, e.g. MED001")


@mining.get("/association-rules", response_model=ListResponse, summary="Get medicine association rules",
            description="Apriori rules (antecedent -> consequent) with support, confidence and lift, strongest lift first. "
                        "These are co-purchase patterns, not medical advice.")
def association_rules(min_lift: float = Query(0, ge=0), min_confidence: float = Query(0, ge=0, le=1),
                      limit: int = Limit, offset: int = Offset):
    df = load_report("mining", "association_rules.csv")
    df = df[(df["lift"] >= min_lift) & (df["confidence"] >= min_confidence)]
    return list_response(df.sort_values(["lift", "confidence"], ascending=False, kind="stable"), limit, offset)


@mining.get("/clusters", summary="Get medicine clusters",
            description="`summary`: one row per K-Means cluster (size, averages, top categories, centroid z-scores). "
                        "`data`: one row per medicine with its cluster.")
def clusters(cluster_id: int | None = Query(None, ge=0), limit: int = Limit, offset: int = Offset):
    members = load_report("mining", "medicine_clusters.csv")
    summary = load_report("mining", "cluster_summary.csv")
    if cluster_id is not None:
        members = members[members["cluster_id"] == cluster_id]
        summary = summary[summary["cluster_id"] == cluster_id]
    rows = list_response(summary, 1000)["data"]
    for row in rows:      # centroid_z_scores is stored as a JSON string
        try:
            row["centroid_z_scores"] = json.loads(row["centroid_z_scores"])
        except (TypeError, ValueError):
            pass
    return {"summary": rows, **list_response(members, limit, offset)}


@mining.get("/anomalies", response_model=ListResponse, summary="Get detected anomalies",
            description="Statistical (robust z-score) and Isolation Forest anomalies. Filter by type, grain, branch or medicine.")
def anomalies(anomaly_type: str | None = Query(None, max_length=40, pattern=r"^[a-z_]+$"),
              grain: str | None = Query(None, max_length=40, pattern=r"^[a-z_]+$"),
              branch_id: str | None = Branch, medicine_id: str | None = Medicine,
              combined_only: bool = Query(False, description="Only rows flagged by both methods"),
              limit: int = Limit, offset: int = Offset):
    df = load_report("mining", "anomalies.csv")
    for col, val in (("anomaly_type", anomaly_type), ("grain", grain), ("branch_id", branch_id), ("medicine_id", medicine_id)):
        if val is not None:
            df = df[df[col] == val]
    if combined_only:
        df = df[df["combined_anomaly"] == True]  # noqa: E712
    return list_response(df, limit, offset)


@forecasts.get("", response_model=ListResponse, summary="Get demand forecasts",
               description="Stored forecasts of the selected model (`ml_selected`); nothing is trained here. By default the live forecasts issued on the "
                           "latest date (7/14/30-day horizons). Pass `date` for an earlier forecast origin from the test period, which includes `actual_units`.")
def get_forecasts(branch_id: str | None = Branch, medicine_id: str | None = Medicine,
                  horizon: Horizon | None = Query(None, description="Forecast horizon in days: 7, 14 or 30"),
                  date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Forecast origin date, YYYY-MM-DD"),
                  limit: int = Limit, offset: int = Offset):
    df = load_report("forecast", "forecasts.csv")
    df = df[df["model"] == "ml_selected"]
    df = df[df["forecast_date"] == date] if date else df[df["split"] == "future"]
    for col, val in (("branch_id", branch_id), ("medicine_id", medicine_id), ("horizon", None if horizon is None else int(horizon))):
        if val is not None:
            df = df[df[col] == val]
    return list_response(df.sort_values(["branch_id", "medicine_id", "horizon"]), limit, offset)


@forecasts.get("/model-comparison", summary="Compare forecasting models",
               description="Test-period accuracy of every forecasting model (baselines and the selected ML model) per horizon, plus the "
                           "selected model's configuration and feature importance. Read from the stored reports.")
def model_comparison(top_features: int = Query(10, ge=1, le=50)):
    df = load_report("forecast", "model_comparison.csv")
    df = df[(df["split"] == "test") & (df["subset"] == "all")]
    summary = load_report("forecast", "forecast_summary.json")
    importance = load_report("forecast", "feature_importance.csv").head(top_features)
    return {
        "models": to_records(df[["model", "horizon", "sample_count", "MAE", "RMSE", "WAPE", "MASE", "bias_pct"]]),
        "selected_model": summary.get("selected_model"),
        "selected_model_config": summary.get("selected_model_config"),
        "split_dates": summary.get("split_dates"),
        "best_baseline_by_validation_wape": summary.get("best_baseline_by_validation_wape"),
        "feature_importance": to_records(importance),
    }


@mining.get("/model-summary", summary="Summarise the data-mining algorithms",
            description="Evaluation of K-Means clustering (candidate k), Apriori association rules and the two anomaly detectors, "
                        "read from the stored reports.")
def mining_model_summary():
    evaluation = load_report("mining", "cluster_evaluation.csv")
    clusters = load_report("mining", "cluster_summary.csv")
    assoc = load_report("mining", "association_summary.json")
    anomaly = load_report("mining", "anomaly_evaluation.json")
    return {
        "clustering": {
            "evaluation": to_records(evaluation),
            "clusters": to_records(clusters[["cluster_id", "medicine_count", "label", "share_of_units_pct"]]),
        },
        "association": {k: assoc.get(k) for k in (
            "transactions", "unique_medicines", "multi_item_transactions", "min_support", "min_confidence", "min_lift",
            "max_itemset_len", "frequent_itemsets", "useful_rules_after_filter")},
        "anomaly": {
            "ground_truth_events": anomaly.get("ground_truth_events"),
            "detectors": anomaly.get("detector_sets"),
        },
    }


@mining.get("/decision-summary", summary="Summarise the decision-support layer",
            description="Counts of stockout, reorder, overstock and expiry decisions and the assumptions behind them.")
def decision_summary():
    return load_report("decision", "decision_summary.json")
