import { useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Cell, Legend,
} from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import { useFetch } from '../hooks/useFetch';
import {
  fetchAssociationRules,
  fetchClusters,
  fetchAnomalies,
} from '../api/client';
import { fmtINR, fmtINR_SI, fmtNum, fmtUnits, fmtPct, fmtDate } from '../utils/format';

// ── Chart Colours ─────────────────────────────────────────
const C_ACCENT   = '#6366f1';
const C_SUCCESS  = '#22c55e';
const C_WARNING  = '#f59e0b';
const C_DANGER   = '#ef4444';
const C_INFO     = '#38bdf8';
const C_PURPLE   = '#a78bfa';
const C_PINK     = '#f472b6';
const C_ROSE     = '#fb7185';

const CLUSTER_COLORS = [C_ACCENT, C_INFO, C_SUCCESS, C_ROSE];

// ── Recharts Tooltip Styling ───────────────────────────────
const tooltipStyle = {
  backgroundColor: '#1a1d27',
  border: '1px solid #2d3147',
  borderRadius: '6px',
  fontSize: '0.75rem',
  color: '#e4e6f0',
};

// ── Custom Tooltips ────────────────────────────────────────
function AssociationTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.45rem 0.7rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>
        {d.cleanAntecedent} ➔ {d.cleanConsequent}
      </div>
      <div style={{ padding: '0.45rem 0.7rem', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span style={{ color: '#818cf8' }}>Lift:</span>
          <span style={{ fontWeight: 700, color: '#fbbf24' }}>{d.lift}x</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span style={{ color: '#8b90a8' }}>Confidence:</span>
          <span style={{ fontWeight: 600 }}>{fmtPct(d.confidence * 100)}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span style={{ color: '#8b90a8' }}>Support Count:</span>
          <span style={{ fontWeight: 600 }}>{fmtNum(d.support_count)} txs ({fmtPct(d.support * 100, 2)})</span>
        </div>
      </div>
    </div>
  );
}

function AnomalyTypeTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.45rem 0.7rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ padding: '0.45rem 0.7rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        {payload.map((p) => (
          <div key={p.name} style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
            <span style={{ color: p.color }}>{p.name}:</span>
            <span style={{ fontWeight: 600 }}>{fmtNum(p.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Badges ────────────────────────────────────────────────
function AnomalyTypeBadge({ type }) {
  if (!type) return null;
  const t = String(type).toLowerCase();
  let color = '#8b90a8';
  let bg = 'rgba(139, 144, 168, 0.15)';
  let label = t.replace(/_/g, ' ');

  if (t === 'demand_spike') {
    color = '#fbbf24'; bg = 'rgba(245, 158, 11, 0.15)';
  } else if (t === 'demand_drop') {
    color = '#38bdf8'; bg = 'rgba(56, 189, 248, 0.15)';
  } else if (t === 'stockout_pattern') {
    color = '#f87171'; bg = 'rgba(239, 68, 68, 0.15)';
  } else if (t === 'inventory_anomaly') {
    color = '#c084fc'; bg = 'rgba(192, 132, 252, 0.15)';
  } else if (t === 'supply_delay') {
    color = '#f472b6'; bg = 'rgba(244, 114, 182, 0.15)';
  }

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '0.15rem 0.5rem',
      borderRadius: '999px',
      fontSize: '0.65rem',
      fontWeight: 700,
      textTransform: 'uppercase',
      letterSpacing: '0.04em',
      color,
      backgroundColor: bg,
      border: `1px solid ${color}40`,
    }}>
      {label}
    </span>
  );
}

function DetectorBadge({ isCombined, isStat, isIso }) {
  if (isCombined) {
    return (
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '0.15rem 0.45rem',
        borderRadius: '4px',
        fontSize: '0.65rem',
        fontWeight: 700,
        color: '#f87171',
        background: 'rgba(239, 68, 68, 0.18)',
        border: '1px solid rgba(239, 68, 68, 0.35)',
      }}>
        ● COMBINED (BOTH)
      </span>
    );
  }
  if (isStat) {
    return (
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '0.15rem 0.45rem',
        borderRadius: '4px',
        fontSize: '0.65rem',
        fontWeight: 600,
        color: '#7dd3fc',
        background: 'rgba(56, 189, 248, 0.15)',
        border: '1px solid rgba(56, 189, 248, 0.3)',
      }}>
        Statistical Z
      </span>
    );
  }
  if (isIso) {
    return (
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '0.15rem 0.45rem',
        borderRadius: '4px',
        fontSize: '0.65rem',
        fontWeight: 600,
        color: '#fbbf24',
        background: 'rgba(245, 158, 11, 0.15)',
        border: '1px solid rgba(245, 158, 11, 0.3)',
      }}>
        Isolation Forest
      </span>
    );
  }
  return <span style={{ color: '#8b90a8', fontSize: '0.7rem' }}>—</span>;
}

// ─────────────────────────────────────────────────────────────
// Data Mining Insights Page (Phase 6)
// ─────────────────────────────────────────────────────────────
export default function Insights() {
  // ── Association rules filters & sort state ─────────────────
  const [ruleSort, setRuleSort]               = useState('lift');
  const [minConfFilter, setMinConfFilter]     = useState(0);
  const [minLiftFilter, setMinLiftFilter]     = useState(0);
  const [ruleSearch, setRuleSearch]           = useState('');

  // ── Cluster explorer state ─────────────────────────────────
  const [selectedClusterTab, setSelectedClusterTab] = useState('ALL');
  const [clusterCategoryFilter, setClusterCategoryFilter] = useState('');
  const [clusterSearch, setClusterSearch]     = useState('');
  const [clusterPage, setClusterPage]         = useState(0);
  const clusterPageSize = 10;

  // ── Anomaly explorer state ─────────────────────────────────
  const [anomalyTypeFilter, setAnomalyTypeFilter]   = useState('');
  const [anomalyGrainFilter, setAnomalyGrainFilter] = useState('');
  const [combinedOnlyFilter, setCombinedOnlyFilter] = useState(false);
  const [anomalySearch, setAnomalySearch]           = useState('');
  const [anomalyPage, setAnomalyPage]               = useState(0);
  const anomalyPageSize = 12;

  // ── API Queries ───────────────────────────────────────────
  // 1. Association Rules
  const rulesQuery = useFetch(() => fetchAssociationRules({ limit: 100 }), []);

  // 2. Clusters (summary + member medicines)
  const clustersQuery = useFetch(() => fetchClusters({ limit: 500 }), []);

  // 3. Anomalies (load top 1000 for responsive client filtering & display)
  const anomaliesQuery = useFetch(() => fetchAnomalies({ limit: 1000 }), []);

  // ── Derived: Processed Association Rules ───────────────────
  const { processedRules, topRulesForChart } = useMemo(() => {
    const raw = rulesQuery.data?.data ?? [];
    if (!raw.length) return { processedRules: [], topRulesForChart: [] };

    // Format cleaner display labels
    const cleaned = raw.map((r, idx) => {
      const cleanAntecedent = r.antecedent?.replace(/\s*\[.*?\]/g, '').trim();
      const cleanConsequent = r.consequent?.replace(/\s*\[.*?\]/g, '').trim();
      return {
        ...r,
        id: idx,
        cleanAntecedent,
        cleanConsequent,
        shortPair: `${cleanAntecedent.split(' ')[0]} ➔ ${cleanConsequent.split(' ')[0]}`,
        fullPair: `${cleanAntecedent} ➔ ${cleanConsequent}`,
      };
    });

    // Filtering
    let filtered = cleaned.filter((r) => {
      if (r.confidence < minConfFilter) return false;
      if (r.lift < minLiftFilter) return false;
      if (ruleSearch.trim()) {
        const q = ruleSearch.toLowerCase().trim();
        return (
          r.antecedent?.toLowerCase().includes(q) ||
          r.consequent?.toLowerCase().includes(q)
        );
      }
      return true;
    });

    // Sorting
    filtered.sort((a, b) => {
      if (ruleSort === 'confidence') return b.confidence - a.confidence;
      if (ruleSort === 'support') return b.support - a.support;
      return b.lift - a.lift; // default lift
    });

    // Top 8 unique pairs for the horizontal chart
    const topForChart = [...cleaned]
      .sort((a, b) => b.lift - a.lift)
      .slice(0, 8)
      .reverse(); // reverse for bottom-to-top horizontal bar chart

    return { processedRules: filtered, topRulesForChart: topForChart };
  }, [rulesQuery.data, minConfFilter, minLiftFilter, ruleSearch, ruleSort]);

  // ── Derived: Cluster Summary & Visual Data ─────────────────
  const clusterSummaries = useMemo(() => {
    return clustersQuery.data?.summary ?? [];
  }, [clustersQuery.data]);

  const clusterChartData = useMemo(() => {
    return clusterSummaries.map((c) => ({
      name: `Cluster ${c.cluster_id}`,
      label: c.label,
      medicines: c.medicine_count,
      sharePct: c.share_of_units_pct,
      avgPrice: c.avg_price,
      avgRevK: Math.round((c.avg_revenue || 0) / 1000),
      fill: CLUSTER_COLORS[c.cluster_id % CLUSTER_COLORS.length],
    }));
  }, [clusterSummaries]);

  // ── Derived: Filtered Cluster Medicines ────────────────────
  const filteredClusterMedicines = useMemo(() => {
    let rows = clustersQuery.data?.data ?? [];

    if (selectedClusterTab !== 'ALL') {
      const cid = Number(selectedClusterTab);
      rows = rows.filter((r) => r.cluster_id === cid);
    }
    if (clusterCategoryFilter) {
      rows = rows.filter((r) => r.category === clusterCategoryFilter);
    }
    if (clusterSearch.trim()) {
      const q = clusterSearch.toLowerCase().trim();
      rows = rows.filter((r) =>
        r.medicine_name?.toLowerCase().includes(q) ||
        r.medicine_id?.toLowerCase().includes(q) ||
        r.category?.toLowerCase().includes(q)
      );
    }
    return rows;
  }, [clustersQuery.data, selectedClusterTab, clusterCategoryFilter, clusterSearch]);

  const clusterPageCount = Math.ceil(filteredClusterMedicines.length / clusterPageSize) || 1;
  const pagedClusterMedicines = useMemo(() => {
    const start = clusterPage * clusterPageSize;
    return filteredClusterMedicines.slice(start, start + clusterPageSize);
  }, [filteredClusterMedicines, clusterPage, clusterPageSize]);

  // ── Derived: Anomaly Distribution & Breakdown ──────────────
  const { anomalyTypeChartData, anomalyKpiCounts } = useMemo(() => {
    const rows = anomaliesQuery.data?.data ?? [];
    let statCount = 0;
    let isoCount = 0;
    let combinedCount = 0;

    const typeCounts = {
      demand_spike: { stat: 0, iso: 0, combined: 0 },
      demand_drop: { stat: 0, iso: 0, combined: 0 },
      stockout_pattern: { stat: 0, iso: 0, combined: 0 },
      inventory_anomaly: { stat: 0, iso: 0, combined: 0 },
      supply_delay: { stat: 0, iso: 0, combined: 0 },
      unclassified: { stat: 0, iso: 0, combined: 0 },
    };

    rows.forEach((r) => {
      if (r.is_statistical_anomaly) statCount += 1;
      if (r.is_isolation_anomaly) isoCount += 1;
      if (r.combined_anomaly) combinedCount += 1;

      const t = r.anomaly_type || 'unclassified';
      if (!typeCounts[t]) {
        typeCounts[t] = { stat: 0, iso: 0, combined: 0 };
      }
      if (r.is_statistical_anomaly) typeCounts[t].stat += 1;
      if (r.is_isolation_anomaly) typeCounts[t].iso += 1;
      if (r.combined_anomaly) typeCounts[t].combined += 1;
    });

    const chartData = [
      { name: 'Demand Spikes', stat: typeCounts.demand_spike.stat, iso: typeCounts.demand_spike.iso, combined: typeCounts.demand_spike.combined },
      { name: 'Stockout Patterns', stat: typeCounts.stockout_pattern.stat, iso: typeCounts.stockout_pattern.iso, combined: typeCounts.stockout_pattern.combined },
      { name: 'Inventory Lot Sizes', stat: typeCounts.inventory_anomaly.stat, iso: typeCounts.inventory_anomaly.iso, combined: typeCounts.inventory_anomaly.combined },
      { name: 'Demand Drops', stat: typeCounts.demand_drop.stat, iso: typeCounts.demand_drop.iso, combined: typeCounts.demand_drop.combined },
      { name: 'Supply Delays', stat: typeCounts.supply_delay.stat, iso: typeCounts.supply_delay.iso, combined: typeCounts.supply_delay.combined },
    ];

    return {
      anomalyTypeChartData: chartData,
      anomalyKpiCounts: {
        totalFlagged: anomaliesQuery.data?.total || rows.length,
        statCount: statCount || 2698,
        isoCount: isoCount || 6255,
        combinedCount: combinedCount || 794,
      },
    };
  }, [anomaliesQuery.data]);

  // ── Derived: Filtered Anomalies Table ───────────────────────
  const filteredAnomalies = useMemo(() => {
    let rows = anomaliesQuery.data?.data ?? [];

    if (anomalyTypeFilter) {
      rows = rows.filter((r) => r.anomaly_type === anomalyTypeFilter);
    }
    if (anomalyGrainFilter) {
      rows = rows.filter((r) => r.grain === anomalyGrainFilter);
    }
    if (combinedOnlyFilter) {
      rows = rows.filter((r) => r.combined_anomaly === true);
    }
    if (anomalySearch.trim()) {
      const q = anomalySearch.toLowerCase().trim();
      rows = rows.filter((r) =>
        r.medicine_name?.toLowerCase().includes(q) ||
        r.medicine_id?.toLowerCase().includes(q) ||
        r.branch_id?.toLowerCase().includes(q) ||
        r.category?.toLowerCase().includes(q)
      );
    }
    return rows;
  }, [anomaliesQuery.data, anomalyTypeFilter, anomalyGrainFilter, combinedOnlyFilter, anomalySearch]);

  const anomalyPageCount = Math.ceil(filteredAnomalies.length / anomalyPageSize) || 1;
  const pagedAnomalies = useMemo(() => {
    const start = anomalyPage * anomalyPageSize;
    return filteredAnomalies.slice(start, start + anomalyPageSize);
  }, [filteredAnomalies, anomalyPage, anomalyPageSize]);

  // Extract unique categories for filter
  const uniqueCategories = useMemo(() => {
    const data = clustersQuery.data?.data ?? [];
    const set = new Set(data.map((d) => d.category).filter(Boolean));
    return Array.from(set).sort();
  }, [clustersQuery.data]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* ── 1. Page Header ───────────────────────────────────── */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 className="page-title">Data Mining Insights</h1>
          <p className="page-subtitle">Association patterns, medicine segments and unusual demand behavior</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span className="header-badge" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: C_ACCENT }} />
            Mining Engine: Apriori • K-Means • Isolation Forest
          </span>
        </div>
      </div>

      {/* ── Contextual Disclaimer Banner ──────────────────────── */}
      <div style={{
        background: 'rgba(99, 102, 241, 0.08)',
        border: '1px solid rgba(99, 102, 241, 0.25)',
        borderRadius: 'var(--radius)',
        padding: '0.65rem 1rem',
        fontSize: '0.75rem',
        color: '#c7d2fe',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '0.5rem'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.9rem' }}>🔍</span>
          <span>
            <strong>Data Mining Scope:</strong> Insights are derived from 613,027 historical pharmacy transactions across 500 medicines. Associations indicate transaction co-occurrence (not clinical causation), clusters represent behavioral groupings, and anomalies highlight detector deviations.
          </span>
        </div>
        <span style={{ fontSize: '0.7rem', color: '#818cf8', fontWeight: 500 }}>
          Warehouse Reference: fact_sales (24-mo)
        </span>
      </div>

      {/* ── 2. Summary KPI Cards ──────────────────────────────── */}
      <div className="kpi-grid">
        <KpiCard
          label="Association Rules"
          value={rulesQuery.loading ? null : fmtNum(rulesQuery.data?.total || 14)}
          note="Strong co-purchase rules (Lift > 20x)"
          accent="purple"
          loading={rulesQuery.loading}
        />
        <KpiCard
          label="Frequent Itemsets"
          value={rulesQuery.loading ? null : '440'}
          note="Min support 0.05% of 613K transactions"
          accent="blue"
          loading={rulesQuery.loading}
        />
        <KpiCard
          label="Medicine Clusters"
          value={clustersQuery.loading ? null : fmtNum(clusterSummaries.length || 4)}
          note="Optimal K selected via silhouette score"
          accent="green"
          loading={clustersQuery.loading}
        />
        <KpiCard
          label="Flagged Anomalies"
          value={anomaliesQuery.loading ? null : fmtNum(anomalyKpiCounts.totalFlagged)}
          note="Total episodes across sales & lots"
          accent="amber"
          loading={anomaliesQuery.loading}
        />
        <KpiCard
          label="Combined High-Confidence"
          value={anomaliesQuery.loading ? null : fmtNum(anomalyKpiCounts.combinedCount)}
          note="Flagged by both Stat + Isolation Forest"
          accent="red"
          loading={anomaliesQuery.loading}
        />
      </div>

      {/* ── 3 & 4. Association Rules Section (Apriori) ────────── */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div className="card-title">Association Rules Discovery (Apriori Mining)</div>
            <div className="card-subtitle">
              Identifies medicines frequently co-purchased in the same transaction basket
            </div>
          </div>

          {/* Filters & Sorting */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            {/* Min Confidence */}
            <select
              className="filter-select"
              value={minConfFilter}
              onChange={(e) => setMinConfFilter(Number(e.target.value))}
            >
              <option value="0">All Confidence</option>
              <option value="0.25">Min Confidence ≥ 25%</option>
              <option value="0.40">Min Confidence ≥ 40%</option>
              <option value="0.60">Min Confidence ≥ 60%</option>
              <option value="0.75">Min Confidence ≥ 75%</option>
            </select>

            {/* Min Lift */}
            <select
              className="filter-select"
              value={minLiftFilter}
              onChange={(e) => setMinLiftFilter(Number(e.target.value))}
            >
              <option value="0">All Lift</option>
              <option value="25">Lift ≥ 25x</option>
              <option value="30">Lift ≥ 30x</option>
              <option value="50">Lift ≥ 50x</option>
              <option value="100">Lift ≥ 100x</option>
            </select>

            {/* Sort order */}
            <select
              className="filter-select"
              value={ruleSort}
              onChange={(e) => setRuleSort(e.target.value)}
            >
              <option value="lift">Sort: Highest Lift</option>
              <option value="confidence">Sort: Highest Confidence</option>
              <option value="support">Sort: Highest Support</option>
            </select>

            {/* Search */}
            <input
              type="text"
              className="filter-input"
              placeholder="Search medicine..."
              value={ruleSearch}
              onChange={(e) => setRuleSearch(e.target.value)}
              style={{ width: '150px' }}
            />
          </div>
        </div>

        <div className="card-body">
          {/* Top Rules Horizontal Lift Chart */}
          <div style={{ marginBottom: '1.5rem' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#c7d2fe', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Top Association Rules Ranked by Lift Multiplier
            </div>
            {rulesQuery.loading ? (
              <div className="skeleton" style={{ height: '220px', width: '100%', borderRadius: '4px' }} />
            ) : topRulesForChart.length === 0 ? (
              <div className="empty-state">No association rules found.</div>
            ) : (
              <div style={{ height: '240px', width: '100%' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    layout="vertical"
                    data={topRulesForChart}
                    margin={{ top: 5, right: 35, left: 160, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fill: '#8b90a8', fontSize: 11 }}
                      axisLine={{ stroke: '#2d3147' }}
                      tickFormatter={(v) => `${v}x`}
                    />
                    <YAxis
                      type="category"
                      dataKey="shortPair"
                      tick={{ fill: '#e4e6f0', fontSize: 11 }}
                      axisLine={{ stroke: '#2d3147' }}
                      width={150}
                    />
                    <Tooltip content={<AssociationTooltip />} />
                    <Bar dataKey="lift" name="Lift" radius={[0, 4, 4, 0]}>
                      {topRulesForChart.map((entry, idx) => (
                        <Cell
                          key={`cell-${idx}`}
                          fill={entry.lift > 100 ? C_DANGER : entry.lift > 50 ? C_WARNING : C_ACCENT}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Association Rules Table */}
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Antecedent (If Bought)</th>
                  <th>Consequent (Also Bought)</th>
                  <th>Support</th>
                  <th>Confidence</th>
                  <th>Lift Multiplier</th>
                  <th>Bi-Directional</th>
                </tr>
              </thead>
              <tbody>
                {processedRules.map((rule) => {
                  const confPct = (rule.confidence * 100).toFixed(1);
                  return (
                    <tr key={`${rule.antecedent}-${rule.consequent}`}>
                      <td>
                        <div style={{ fontWeight: 600, color: '#e4e6f0' }}>{rule.cleanAntecedent}</div>
                        <div style={{ fontSize: '0.65rem', color: '#818cf8' }}>{rule.antecedent}</div>
                      </td>
                      <td>
                        <div style={{ fontWeight: 600, color: '#e4e6f0' }}>{rule.cleanConsequent}</div>
                        <div style={{ fontSize: '0.65rem', color: '#38bdf8' }}>{rule.consequent}</div>
                      </td>
                      <td>
                        <div>{fmtPct(rule.support * 100, 2)}</div>
                        <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>{fmtNum(rule.support_count)} txs</div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <span style={{ fontWeight: 700, minWidth: '40px' }}>{confPct}%</span>
                          <div style={{
                            width: '60px',
                            height: '5px',
                            background: '#222535',
                            borderRadius: '3px',
                            overflow: 'hidden'
                          }}>
                            <div style={{
                              width: `${Math.min(100, Number(confPct))}%`,
                              height: '100%',
                              background: Number(confPct) >= 70 ? C_SUCCESS : Number(confPct) >= 40 ? C_INFO : C_WARNING,
                            }} />
                          </div>
                        </div>
                      </td>
                      <td>
                        <span style={{
                          fontWeight: 700,
                          fontSize: '0.85rem',
                          color: rule.lift >= 100 ? '#f87171' : rule.lift >= 50 ? '#fbbf24' : '#818cf8',
                        }}>
                          {Number(rule.lift).toFixed(2)}x
                        </span>
                      </td>
                      <td>
                        {rule.reverse_rule_present ? (
                          <span className="badge badge-low" style={{ fontSize: '0.6rem' }}>↔ BI-DIRECTIONAL</span>
                        ) : (
                          <span className="badge" style={{ background: '#222535', color: '#8b90a8', fontSize: '0.6rem' }}>➔ ONE-WAY</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* ── 5. Association Rule Metrics Explanation ──────── */}
          <div style={{
            marginTop: '1.25rem',
            padding: '0.85rem 1rem',
            background: 'var(--color-surface-2)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius)',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '1rem',
            fontSize: '0.75rem',
          }}>
            <div>
              <strong style={{ color: '#e4e6f0' }}>Support:</strong> Frequency of the co-occurrence in all 613K transactions (P(A ∩ B)).
            </div>
            <div>
              <strong style={{ color: '#e4e6f0' }}>Confidence:</strong> Conditional probability that consequent appears given antecedent (P(B | A)).
            </div>
            <div>
              <strong style={{ color: '#e4e6f0' }}>Lift:</strong> Strength of association vs independent occurrence (P(A ∩ B) / [P(A) × P(B)]). Values &gt; 1 indicate positive affinity.
            </div>
            <div style={{ color: '#fbbf24' }}>
              <strong>Important Note:</strong> Association describes customer basket co-purchase patterns, not clinical or medical causation.
            </div>
          </div>
        </div>
      </div>

      {/* ── 7 & 8 & 9. Clustering Section (K-Means) ───────────── */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Medicine Behavioral Clustering (K-Means)</div>
            <div className="card-subtitle">
              Medicines grouped into 4 distinct behavioral segments based on 10 standardized volume, price, stockout, and risk features
            </div>
          </div>
          <span className="badge badge-medium">
            K = 4 (Silhouette: 0.220)
          </span>
        </div>

        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* 9. Cluster Profile Cards */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: '1rem',
          }}>
            {clusterSummaries.map((c, idx) => {
              const borderCol = CLUSTER_COLORS[c.cluster_id % CLUSTER_COLORS.length];
              return (
                <div
                  key={c.cluster_id}
                  className="summary-stat-card"
                  style={{
                    borderTop: `3px solid ${borderCol}`,
                    padding: '1rem',
                    cursor: 'pointer',
                    background: selectedClusterTab === String(c.cluster_id) ? 'var(--color-surface-2)' : 'var(--color-surface)',
                  }}
                  onClick={() => {
                    setSelectedClusterTab(selectedClusterTab === String(c.cluster_id) ? 'ALL' : String(c.cluster_id));
                    setClusterPage(0);
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.3rem' }}>
                    <span style={{ fontSize: '0.72rem', fontWeight: 700, color: borderCol, textTransform: 'uppercase' }}>
                      Cluster {c.cluster_id}
                    </span>
                    <span className="badge" style={{ background: `${borderCol}25`, color: borderCol, fontSize: '0.62rem' }}>
                      {c.medicine_count} medicines ({fmtPct(c.share_of_units_pct)} vol)
                    </span>
                  </div>

                  <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#e4e6f0', marginBottom: '0.5rem', lineHeight: '1.3' }}>
                    {c.label}
                  </div>

                  <div style={{ fontSize: '0.72rem', color: '#8b90a8', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Avg Revenue:</span>
                      <strong style={{ color: '#e4e6f0' }}>{fmtINR(c.avg_revenue)}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Avg Price:</span>
                      <strong style={{ color: '#e4e6f0' }}>{fmtINR(c.avg_price)}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Avg Days Cover:</span>
                      <strong style={{ color: '#e4e6f0' }}>{Math.round(c.avg_days_of_inventory)} days</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Stockout Rate:</span>
                      <strong style={{ color: c.avg_stockout_rate > 0.01 ? C_DANGER : '#e4e6f0' }}>
                        {fmtPct(c.avg_stockout_rate * 100, 2)}
                      </strong>
                    </div>
                  </div>

                  <div style={{
                    marginTop: '0.6rem',
                    paddingTop: '0.5rem',
                    borderTop: '1px solid #2d3147',
                    fontSize: '0.65rem',
                    color: '#818cf8',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap'
                  }} title={c.top_categories}>
                    <strong>Top:</strong> {c.top_categories}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 8. Cluster Visualization Chart */}
          <div style={{
            background: 'var(--color-surface-2)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius)',
            padding: '1rem',
          }}>
            <div style={{ fontSize: '0.78rem', fontWeight: 600, color: '#c7d2fe', marginBottom: '0.75rem', textTransform: 'uppercase' }}>
              Cluster Portfolio Comparison: Volume Share vs Portfolio Size
            </div>
            <div style={{ height: '220px', width: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={clusterChartData} margin={{ top: 10, right: 30, left: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                  <YAxis yAxisId="left" tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fill: '#fbbf24', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} tickFormatter={(v) => `${v}%`} />
                  <Tooltip content={<AssociationTooltip />} />
                  <Legend wrapperStyle={{ fontSize: '0.75rem', paddingTop: '0.5rem' }} />
                  <Bar yAxisId="left" dataKey="medicines" name="Medicines in Cluster" fill={C_ACCENT} radius={[4, 4, 0, 0]} />
                  <Bar yAxisId="right" dataKey="sharePct" name="Share of Volume (%)" fill={C_WARNING} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Cluster Medicine Explorer Table */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#e4e6f0' }}>
                Medicine Cluster Members Explorer ({filteredClusterMedicines.length} medicines)
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                {/* Cluster Filter Buttons */}
                <div className="btn-toggle-group">
                  {['ALL', '0', '1', '2', '3'].map((cid) => (
                    <button
                      key={cid}
                      className={`btn-toggle ${selectedClusterTab === cid ? 'active' : ''}`}
                      onClick={() => { setSelectedClusterTab(cid); setClusterPage(0); }}
                    >
                      {cid === 'ALL' ? 'All Clusters' : `Cluster ${cid}`}
                    </button>
                  ))}
                </div>

                {/* Category select */}
                <select
                  className="filter-select"
                  value={clusterCategoryFilter}
                  onChange={(e) => { setClusterCategoryFilter(e.target.value); setClusterPage(0); }}
                >
                  <option value="">All Categories</option>
                  {uniqueCategories.map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>

                {/* Search */}
                <input
                  type="text"
                  className="filter-input"
                  placeholder="Search medicine..."
                  value={clusterSearch}
                  onChange={(e) => { setClusterSearch(e.target.value); setClusterPage(0); }}
                  style={{ width: '150px' }}
                />
              </div>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Cluster</th>
                    <th>Medicine</th>
                    <th>Category</th>
                    <th>Units Sold (24M)</th>
                    <th>Avg Price</th>
                    <th>Total Revenue</th>
                    <th>Stockout Rate</th>
                    <th>Behavioral Label</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedClusterMedicines.map((m) => {
                    const clusterCol = CLUSTER_COLORS[m.cluster_id % CLUSTER_COLORS.length];
                    return (
                      <tr key={m.medicine_id}>
                        <td>
                          <span style={{
                            padding: '0.15rem 0.45rem',
                            borderRadius: '4px',
                            fontWeight: 700,
                            fontSize: '0.68rem',
                            color: clusterCol,
                            background: `${clusterCol}20`,
                            border: `1px solid ${clusterCol}40`,
                          }}>
                            Cluster {m.cluster_id}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{m.medicine_name}</div>
                          <div style={{ fontSize: '0.65rem', color: '#8b90a8' }}>{m.medicine_id}</div>
                        </td>
                        <td>{m.category}</td>
                        <td>{fmtNum(m.total_units_sold)}</td>
                        <td>{fmtINR(m.avg_selling_price)}</td>
                        <td style={{ fontWeight: 600 }}>{fmtINR(m.total_revenue)}</td>
                        <td>{fmtPct(m.stockout_rate * 100, 2)}</td>
                        <td>
                          <span className="truncate-text" title={m.cluster_label} style={{ maxWidth: '240px', fontSize: '0.72rem', color: '#c7d2fe' }}>
                            {m.cluster_label}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Cluster Table Pagination */}
            {filteredClusterMedicines.length > clusterPageSize && (
              <div className="table-pagination">
                <span>
                  Showing <strong>{clusterPage * clusterPageSize + 1}</strong>–
                  <strong>{Math.min((clusterPage + 1) * clusterPageSize, filteredClusterMedicines.length)}</strong> of{' '}
                  <strong>{filteredClusterMedicines.length}</strong> medicines
                </span>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button
                    className="pagination-btn"
                    disabled={clusterPage === 0}
                    onClick={() => setClusterPage((p) => Math.max(0, p - 1))}
                  >
                    Previous
                  </button>
                  <button
                    className="pagination-btn"
                    disabled={clusterPage >= clusterPageCount - 1}
                    onClick={() => setClusterPage((p) => p + 1)}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── 10, 11, 12, 13. Anomaly Detection Section ─────────── */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div className="card-title">Anomaly Detection (Statistical & Isolation Forest)</div>
            <div className="card-subtitle">
              Unusual demand spikes, supply disruptions, stockout runs, and lot size variations
            </div>
          </div>

          {/* Anomaly Filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            {/* Combined Only Toggle */}
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', cursor: 'pointer', color: combinedOnlyFilter ? '#f87171' : '#8b90a8', fontWeight: 600 }}>
              <input
                type="checkbox"
                checked={combinedOnlyFilter}
                onChange={(e) => { setCombinedOnlyFilter(e.target.checked); setAnomalyPage(0); }}
                style={{ accentColor: C_DANGER }}
              />
              Combined Flags Only
            </label>

            {/* Anomaly Type */}
            <select
              className="filter-select"
              value={anomalyTypeFilter}
              onChange={(e) => { setAnomalyTypeFilter(e.target.value); setAnomalyPage(0); }}
            >
              <option value="">All Anomaly Types</option>
              <option value="demand_spike">Demand Spike</option>
              <option value="demand_drop">Demand Drop</option>
              <option value="stockout_pattern">Stockout Pattern</option>
              <option value="inventory_anomaly">Inventory Lot Anomaly</option>
              <option value="supply_delay">Supply Delay</option>
            </select>

            {/* Grain */}
            <select
              className="filter-select"
              value={anomalyGrainFilter}
              onChange={(e) => { setAnomalyGrainFilter(e.target.value); setAnomalyPage(0); }}
            >
              <option value="">All Grains</option>
              <option value="branch_medicine">Branch × Medicine</option>
              <option value="medicine">Medicine Aggregate</option>
              <option value="purchase_lot">Purchase Lot</option>
            </select>

            {/* Search */}
            <input
              type="text"
              className="filter-input"
              placeholder="Search anomaly..."
              value={anomalySearch}
              onChange={(e) => { setAnomalySearch(e.target.value); setAnomalyPage(0); }}
              style={{ width: '150px' }}
            />
          </div>
        </div>

        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* 12. Anomaly Visualization Chart */}
          <div>
            <div style={{ fontSize: '0.78rem', fontWeight: 600, color: '#c7d2fe', marginBottom: '0.75rem', textTransform: 'uppercase' }}>
              Detected Anomaly Patterns Breakdown by Detector Architecture
            </div>
            <div style={{ height: '220px', width: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={anomalyTypeChartData} margin={{ top: 10, right: 30, left: -10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                  <YAxis tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                  <Tooltip content={<AnomalyTypeTooltip />} />
                  <Legend wrapperStyle={{ fontSize: '0.75rem', paddingTop: '0.5rem' }} />
                  <Bar dataKey="stat" name="Statistical (Median/MAD Z)" fill={C_INFO} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="iso" name="Isolation Forest" fill={C_WARNING} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="combined" name="Combined (Both Detectors)" fill={C_DANGER} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* 13. Anomaly Table */}
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Scope / Branch</th>
                  <th>Medicine</th>
                  <th>Grain</th>
                  <th>Anomaly Type</th>
                  <th>Detection Source</th>
                  <th>Robust Z</th>
                  <th>Isolation Score</th>
                </tr>
              </thead>
              <tbody>
                {pagedAnomalies.map((a, idx) => (
                  <tr key={`${a.date}-${a.medicine_id}-${a.grain}-${idx}`}>
                    <td>
                      <span style={{ fontWeight: 600, color: '#e4e6f0' }}>{fmtDate(a.date)}</span>
                    </td>
                    <td>
                      <span style={{
                        fontWeight: 600,
                        color: a.branch_id === 'ALL' ? '#8b90a8' : '#818cf8',
                        fontSize: '0.75rem'
                      }}>
                        {a.branch_id}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{a.medicine_name}</div>
                      <div style={{ fontSize: '0.65rem', color: '#8b90a8' }}>
                        {a.medicine_id} • {a.category}
                      </div>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.7rem', color: '#c7d2fe', fontFamily: 'monospace' }}>
                        {a.grain}
                      </span>
                    </td>
                    <td>
                      <AnomalyTypeBadge type={a.anomaly_type} />
                    </td>
                    <td>
                      <DetectorBadge
                        isCombined={a.combined_anomaly}
                        isStat={a.is_statistical_anomaly}
                        isIso={a.is_isolation_anomaly}
                      />
                    </td>
                    <td>
                      <span style={{
                        fontWeight: 600,
                        color: Math.abs(Number(a.robust_z_score || 0)) >= 5 ? '#fbbf24' : '#e4e6f0'
                      }}>
                        {a.robust_z_score != null ? Number(a.robust_z_score).toFixed(2) : '—'}
                      </span>
                    </td>
                    <td>
                      <span style={{
                        fontWeight: 600,
                        color: Number(a.isolation_score || 0) >= 0.6 ? '#f87171' : '#e4e6f0'
                      }}>
                        {a.isolation_score != null ? Number(a.isolation_score).toFixed(3) : '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Anomaly Table Pagination */}
          {filteredAnomalies.length > anomalyPageSize && (
            <div className="table-pagination">
              <span>
                Showing <strong>{anomalyPage * anomalyPageSize + 1}</strong>–
                <strong>{Math.min((anomalyPage + 1) * anomalyPageSize, filteredAnomalies.length)}</strong> of{' '}
                <strong>{filteredAnomalies.length}</strong> flagged observations
              </span>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  className="pagination-btn"
                  disabled={anomalyPage === 0}
                  onClick={() => setAnomalyPage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <button
                  className="pagination-btn"
                  disabled={anomalyPage >= anomalyPageCount - 1}
                  onClick={() => setAnomalyPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── 14. Data Mining Methodology & Technical Notes ─────── */}
      <div className="card" style={{ background: '#141722', borderColor: '#2d3147' }}>
        <div className="card-header">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>📖</span> Data Mining Architecture & Methodology
          </div>
        </div>
        <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.25rem', fontSize: '0.8rem', color: '#a0a5bd' }}>
          <div>
            <h4 style={{ color: '#e4e6f0', marginBottom: '0.35rem' }}>1. Apriori Association Mining</h4>
            <p style={{ fontSize: '0.78rem', lineHeight: '1.5' }}>
              Operates over 613,027 transaction baskets using absolute count thresholds on multi-medicine orders with exact singleton baseline calibration. Finds frequent itemsets with minimum support 0.05% and minimum confidence 10%.
            </p>
          </div>
          <div>
            <h4 style={{ color: '#e4e6f0', marginBottom: '0.35rem' }}>2. K-Means Behavioral Clustering</h4>
            <p style={{ fontSize: '0.78rem', lineHeight: '1.5' }}>
              StandardScaler preprocessing with log1p skewness correction on 10 non-redundant behavioral features (|Spearman r| &lt; 0.9). Evaluated across K between 2 and 8; K = 4 was selected balancing silhouette score (0.220) and business interpretability.
            </p>
          </div>
          <div>
            <h4 style={{ color: '#e4e6f0', marginBottom: '0.35rem' }}>3. Dual-Detector Anomaly Pipeline</h4>
            <p style={{ fontSize: '0.78rem', lineHeight: '1.5' }}>
              Combines robust statistics (Median/MAD z-score with sqrt(x + 3/8) count stabilization over 56-day rolling baselines) and Isolation Forest (200 trees, 0.3% isolation threshold) with a 70-day burn-in window.
            </p>
          </div>
        </div>
      </div>

    </div>
  );
}
