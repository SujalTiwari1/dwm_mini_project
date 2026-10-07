import { useState, useMemo } from 'react';
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import PriorityBadge from '../components/PriorityBadge';
import { useFetch } from '../hooks/useFetch';
import {
  fetchStockoutRisk,
  fetchExpiry,
  fetchActionQueue,
} from '../api/client';
import { fmtINR, fmtINR_SI, fmtNum, fmtUnits, fmtDate, fmtPct } from '../utils/format';

// ── Chart colours ─────────────────────────────────────────
const C_DANGER  = '#ef4444'; // CRITICAL
const C_WARNING = '#f59e0b'; // HIGH
const C_INFO    = '#38bdf8'; // MEDIUM
const C_SUCCESS = '#22c55e'; // LOW
const C_ACCENT  = '#6366f1';
const C_PURPLE  = '#a78bfa';

const RISK_COLORS = {
  CRITICAL: C_DANGER,
  HIGH:     C_WARNING,
  MEDIUM:   C_INFO,
  LOW:      C_SUCCESS,
};

// ── Recharts tooltip style ─────────────────────────────────
const tooltipStyle = {
  backgroundColor: '#1a1d27',
  border: '1px solid #2d3147',
  borderRadius: '6px',
  fontSize: '0.75rem',
  color: '#e4e6f0',
};

// ── Custom Tooltips ────────────────────────────────────────
function StockoutRiskTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0];
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.45rem 0.7rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>
        {d.name} Risk
      </div>
      <div style={{ padding: '0.45rem 0.7rem', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span style={{ color: d.payload?.fill ?? '#fff' }}>Pairs:</span>
          <span style={{ fontWeight: 600 }}>{fmtNum(d.value)}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', color: '#8b90a8' }}>
          <span>Share:</span>
          <span>{d.payload?.pct}</span>
        </div>
      </div>
    </div>
  );
}

function ExpiryRiskTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.45rem 0.7rem', borderBottom: '1px solid #2d3147', fontWeight: 600, color: item.fill }}>
        {label ?? item.level} Risk
      </div>
      <div style={{ padding: '0.45rem 0.7rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span style={{ color: '#8b90a8' }}>Batches:</span>
          <span style={{ fontWeight: 600 }}>{fmtNum(item.lots)} lots</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span style={{ color: '#8b90a8' }}>At-Risk Value:</span>
          <span style={{ fontWeight: 600, color: '#fbbf24' }}>{fmtINR(item.exposureValue)}</span>
        </div>
      </div>
    </div>
  );
}

// ── Action Badge ──────────────────────────────────────────
function ActionBadge({ action }) {
  if (!action) return null;
  const norm = String(action).toUpperCase();
  let cls = 'badge-low';
  if (norm.includes('ORDER_NOW') || norm === 'PRIORITIZE_SALE' || norm === 'PRIORITIZE_SALE_EXPIRING_STOCK') {
    cls = 'badge-critical';
  } else if (norm.includes('REORDER_SOON') || norm === 'MONITOR_STOCK_CLOSELY') {
    cls = 'badge-high';
  } else if (norm.includes('MONITOR') || norm === 'REVIEW_OVERSTOCK') {
    cls = 'badge-medium';
  }
  return (
    <span className={`badge ${cls}`}>
      {norm.replace(/_/g, ' ')}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────
// Risk & Expiry Intelligence Page (Phase 5)
// ─────────────────────────────────────────────────────────────
export default function Risk() {
  // ── Filters & pagination state ────────────────────────────
  const [stockoutRiskFilter, setStockoutRiskFilter] = useState('CRITICAL');
  const [stockoutBranchFilter, setStockoutBranchFilter] = useState('');
  const [stockoutSearch, setStockoutSearch] = useState('');
  const [stockoutPage, setStockoutPage] = useState(0);

  const [expiryRiskFilter, setExpiryRiskFilter] = useState('CRITICAL');
  const [expiryActionFilter, setExpiryActionFilter] = useState('');
  const [expiryBranchFilter, setExpiryBranchFilter] = useState('');
  const [expirySearch, setExpirySearch] = useState('');
  const [expiryPage, setExpiryPage] = useState(0);

  const pageSize = 10;

  // ── API queries ───────────────────────────────────────────
  // 1. Stockout risk dataset (fetching top 1000 items covers all CRITICAL, HIGH, MEDIUM pairs)
  const stockoutQuery = useFetch(() => fetchStockoutRisk({ limit: 1000 }), []);

  // 2. Expiry actions dataset (fetching top 1000 items covers all CRITICAL, HIGH, MEDIUM lots)
  const expiryQuery = useFetch(() => fetchExpiry({ limit: 1000 }), []);

  // 3. Action queue dataset (for exposures, priorities and action summary)
  const actionQuery = useFetch(() => fetchActionQueue({ limit: 1000 }), []);

  // ── Derived: KPI metrics & exposures ───────────────────────
  const {
    stockoutExposureVal,
    stockoutExposureUnits,
    expiryExposureVal,
    criticalStockoutCount,
    criticalExpiryCount,
    highPriorityRiskCount,
    snapshotDate,
  } = useMemo(() => {
    const actions = actionQuery.data?.data ?? [];
    const stockouts = stockoutQuery.data?.data ?? [];
    const expiries = expiryQuery.data?.data ?? [];

    // Sum stockout exposure from action queue
    let soVal = 0;
    let soUnits = 0;
    let expVal = 0;
    let highRiskActions = 0;

    actions.forEach((a) => {
      if (a.potential_stockout_exposure_value) soVal += Number(a.potential_stockout_exposure_value);
      if (a.potential_stockout_exposure_units) soUnits += Number(a.potential_stockout_exposure_units);
      if (a.projected_expiry_exposure_value) expVal += Number(a.projected_expiry_exposure_value);
      if (a.priority === 'CRITICAL' || a.priority === 'HIGH') highRiskActions += 1;
    });

    // Fallback for expiry exposure if not fully in action queue
    if (expVal === 0 && expiries.length > 0) {
      expVal = expiries.reduce((acc, e) => acc + (Number(e.projected_unsold_value) || 0), 0);
    }

    const critSo = stockouts.filter((s) => s.risk_level === 'CRITICAL').length;
    const critExp = expiries.filter((e) => e.risk_level === 'CRITICAL').length;

    // Derived snapshot date from earliest expiry date or default
    let snap = null;
    if (expiries.length > 0 && expiries[0].expiry_date) {
      snap = expiries[0].expiry_date;
    }

    return {
      stockoutExposureVal: soVal,
      stockoutExposureUnits: soUnits,
      expiryExposureVal: expVal,
      criticalStockoutCount: critSo || (stockoutQuery.data?.total ? null : 0),
      criticalExpiryCount: critExp || (expiryQuery.data?.total ? null : 0),
      highPriorityRiskCount: highRiskActions,
      snapshotDate: snap,
    };
  }, [actionQuery.data, stockoutQuery.data, expiryQuery.data]);

  // ── Derived: Stockout Risk Distribution ────────────────────
  const stockoutDistData = useMemo(() => {
    const rows = stockoutQuery.data?.data ?? [];
    if (!rows.length) return [];

    const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    rows.forEach((r) => {
      const lvl = r.risk_level?.toUpperCase();
      if (counts[lvl] !== undefined) counts[lvl] += 1;
    });

    const total = rows.length || 1;
    return [
      { name: 'CRITICAL', value: counts.CRITICAL, fill: C_DANGER,  pct: fmtPct((counts.CRITICAL / total) * 100) },
      { name: 'HIGH',     value: counts.HIGH,     fill: C_WARNING, pct: fmtPct((counts.HIGH / total) * 100) },
      { name: 'MEDIUM',   value: counts.MEDIUM,   fill: C_INFO,    pct: fmtPct((counts.MEDIUM / total) * 100) },
      { name: 'LOW',      value: counts.LOW,      fill: C_SUCCESS, pct: fmtPct((counts.LOW / total) * 100) },
    ];
  }, [stockoutQuery.data]);

  // ── Derived: Expiry Risk Distribution ──────────────────────
  const expiryDistData = useMemo(() => {
    const rows = expiryQuery.data?.data ?? [];
    if (!rows.length) return [];

    const counts = {
      CRITICAL: { count: 0, exposure: 0 },
      HIGH:     { count: 0, exposure: 0 },
      MEDIUM:   { count: 0, exposure: 0 },
      LOW:      { count: 0, exposure: 0 },
    };

    rows.forEach((r) => {
      const lvl = r.risk_level?.toUpperCase();
      if (counts[lvl]) {
        counts[lvl].count += 1;
        counts[lvl].exposure += Number(r.projected_unsold_value) || 0;
      }
    });

    return [
      { level: 'CRITICAL', lots: counts.CRITICAL.count, exposureValue: counts.CRITICAL.exposure, fill: C_DANGER },
      { level: 'HIGH',     lots: counts.HIGH.count,     exposureValue: counts.HIGH.exposure,     fill: C_WARNING },
      { level: 'MEDIUM',   lots: counts.MEDIUM.count,   exposureValue: counts.MEDIUM.exposure,   fill: C_INFO },
      { level: 'LOW',      lots: counts.LOW.count,      exposureValue: counts.LOW.exposure,      fill: C_SUCCESS },
    ];
  }, [expiryQuery.data]);

  // ── Derived: Top Urgent Risk Cards ────────────────────────
  const topRisks = useMemo(() => {
    const stockouts = stockoutQuery.data?.data ?? [];
    const expiries = expiryQuery.data?.data ?? [];
    const actions = actionQuery.data?.data ?? [];

    // 1. Highest stockout risk item (by action queue impact/exposure or days_of_cover = 0)
    const topStockoutAction = actions.find(a => a.stockout_risk === 'CRITICAL' && a.potential_stockout_exposure_value > 0)
      || stockouts.find(s => s.risk_level === 'CRITICAL');

    // 2. Highest expiry financial exposure batch
    let highestExpBatch = null;
    let maxExpVal = -1;
    expiries.forEach((e) => {
      const val = Number(e.projected_unsold_value) || 0;
      if (val > maxExpVal) {
        maxExpVal = val;
        highestExpBatch = e;
      }
    });

    // 3. Most urgent expiry (fewest days to expiry)
    let earliestExpiryBatch = null;
    let minDays = 99999;
    expiries.forEach((e) => {
      if (e.days_to_expiry != null && e.days_to_expiry < minDays && e.days_to_expiry >= 0) {
        minDays = e.days_to_expiry;
        earliestExpiryBatch = e;
      }
    });

    return {
      topStockoutAction,
      highestExpBatch,
      earliestExpiryBatch,
    };
  }, [stockoutQuery.data, expiryQuery.data, actionQuery.data]);

  // ── Filtered Stockout Table Rows ───────────────────────────
  const filteredStockouts = useMemo(() => {
    let rows = stockoutQuery.data?.data ?? [];

    if (stockoutRiskFilter && stockoutRiskFilter !== 'ALL') {
      rows = rows.filter((r) => r.risk_level?.toUpperCase() === stockoutRiskFilter.toUpperCase());
    }
    if (stockoutBranchFilter) {
      rows = rows.filter((r) => r.branch_id === stockoutBranchFilter);
    }
    if (stockoutSearch.trim()) {
      const q = stockoutSearch.toLowerCase().trim();
      rows = rows.filter((r) =>
        r.medicine_name?.toLowerCase().includes(q) ||
        r.medicine_id?.toLowerCase().includes(q) ||
        r.category?.toLowerCase().includes(q)
      );
    }
    return rows;
  }, [stockoutQuery.data, stockoutRiskFilter, stockoutBranchFilter, stockoutSearch]);

  const stockoutPageCount = Math.ceil(filteredStockouts.length / pageSize) || 1;
  const pagedStockouts = useMemo(() => {
    const start = stockoutPage * pageSize;
    return filteredStockouts.slice(start, start + pageSize);
  }, [filteredStockouts, stockoutPage, pageSize]);

  // ── Filtered Expiry Table Rows ─────────────────────────────
  const filteredExpiries = useMemo(() => {
    let rows = expiryQuery.data?.data ?? [];

    if (expiryRiskFilter && expiryRiskFilter !== 'ALL') {
      rows = rows.filter((r) => r.risk_level?.toUpperCase() === expiryRiskFilter.toUpperCase());
    }
    if (expiryActionFilter) {
      rows = rows.filter((r) => r.recommended_action?.toUpperCase() === expiryActionFilter.toUpperCase());
    }
    if (expiryBranchFilter) {
      rows = rows.filter((r) => r.branch_id === expiryBranchFilter);
    }
    if (expirySearch.trim()) {
      const q = expirySearch.toLowerCase().trim();
      rows = rows.filter((r) =>
        r.medicine_name?.toLowerCase().includes(q) ||
        r.medicine_id?.toLowerCase().includes(q) ||
        r.batch_id?.toLowerCase().includes(q) ||
        r.category?.toLowerCase().includes(q)
      );
    }
    return rows;
  }, [expiryQuery.data, expiryRiskFilter, expiryActionFilter, expiryBranchFilter, expirySearch]);

  const expiryPageCount = Math.ceil(filteredExpiries.length / pageSize) || 1;
  const pagedExpiries = useMemo(() => {
    const start = expiryPage * pageSize;
    return filteredExpiries.slice(start, start + pageSize);
  }, [filteredExpiries, expiryPage, pageSize]);

  // ── Derived: Action Queue Summary Metrics ──────────────────
  const actionSummaryMetrics = useMemo(() => {
    const actions = actionQuery.data?.data ?? [];
    const counts = {
      ORDER_NOW: 0,
      PRIORITIZE_SALE_EXPIRING_STOCK: 0,
      MONITOR_STOCK_CLOSELY: 0,
      MONITOR_EXPIRY: 0,
      REORDER_SOON: 0,
    };

    actions.forEach((a) => {
      const act = a.primary_action;
      if (counts[act] !== undefined) {
        counts[act] += 1;
      }
    });

    const urgentList = actions.filter(a => a.priority === 'CRITICAL').slice(0, 6);

    return { counts, urgentList };
  }, [actionQuery.data]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* ── 1. Page Header ───────────────────────────────────── */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 className="page-title">Risk & Expiry</h1>
          <p className="page-subtitle">Stockout exposure, expiry risk and inventory actions requiring attention</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span className="header-badge" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: C_DANGER }} />
            Decision Horizon: Active Forecast
          </span>
        </div>
      </div>

      {/* ── Disclaimer Banner ─────────────────────────────────── */}
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
          <span style={{ fontSize: '0.9rem' }}>ℹ</span>
          <span>
            <strong>Analytical Estimation Notice:</strong> Exposure figures represent estimated potential impact under 7-day supplier lead times and FEFO demand projections, not realized losses.
          </span>
        </div>
        <span style={{ fontSize: '0.7rem', color: '#818cf8', fontWeight: 500 }}>
          Decision Support System v1.0
        </span>
      </div>

      {/* ── 2. Risk KPI Cards ─────────────────────────────────── */}
      <div className="kpi-grid">
        <KpiCard
          label="Potential Stockout Exposure"
          value={actionQuery.loading ? null : fmtINR(stockoutExposureVal)}
          note="Revenue at risk during supplier lead time"
          accent="red"
          loading={actionQuery.loading}
        />
        <KpiCard
          label="Projected Expiry Exposure"
          value={expiryQuery.loading ? null : fmtINR(expiryExposureVal)}
          note="At-risk cost value of unsold expiring lots"
          accent="amber"
          loading={expiryQuery.loading}
        />
        <KpiCard
          label="Critical Stockout Risks"
          value={stockoutQuery.loading ? null : fmtNum(criticalStockoutCount)}
          note="Pairs with <3 days cover or active stockout"
          accent="red"
          loading={stockoutQuery.loading}
        />
        <KpiCard
          label="Critical Expiry Lots"
          value={expiryQuery.loading ? null : fmtNum(criticalExpiryCount)}
          note="Batches expiring with unsold stock risk"
          accent="amber"
          loading={expiryQuery.loading}
        />
        <KpiCard
          label="High Priority Actions"
          value={actionQuery.loading ? null : fmtNum(highPriorityRiskCount)}
          note="Urgent mitigation actions queued"
          accent="purple"
          loading={actionQuery.loading}
        />
      </div>

      {/* ── 10. Top Risk Highlights (Most Urgent) ─────────────── */}
      <div className="summary-grid">
        {/* Highest Stockout Risk */}
        <div className="summary-stat-card" style={{ borderLeft: `3px solid ${C_DANGER}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="summary-stat-label">Highest Stockout Exposure</span>
            <span className="badge badge-critical" style={{ fontSize: '0.6rem' }}>CRITICAL</span>
          </div>
          <div className="summary-stat-title">
            {topRisks.topStockoutAction?.medicine_name ?? '—'}
          </div>
          <div className="summary-stat-sub">
            Branch <strong>{topRisks.topStockoutAction?.branch_id ?? '—'}</strong> • Cover: <strong>{topRisks.topStockoutAction?.days_of_cover ?? 0} days</strong> • Exposure: <strong>{fmtINR(topRisks.topStockoutAction?.potential_stockout_exposure_value ?? topRisks.topStockoutAction?.risk_score)}</strong>
          </div>
        </div>

        {/* Highest Expiry Financial Exposure */}
        <div className="summary-stat-card" style={{ borderLeft: `3px solid ${C_WARNING}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="summary-stat-label">Highest Expiry Exposure</span>
            <span className="badge badge-high" style={{ fontSize: '0.6rem' }}>PRIORITIZE SALE</span>
          </div>
          <div className="summary-stat-title">
            {topRisks.highestExpBatch?.medicine_name ?? '—'}
          </div>
          <div className="summary-stat-sub">
            Branch <strong>{topRisks.highestExpBatch?.branch_id ?? '—'}</strong> • Batch <strong>{topRisks.highestExpBatch?.batch_id ?? '—'}</strong> • At-Risk: <strong>{fmtINR(topRisks.highestExpBatch?.projected_unsold_value)}</strong> ({topRisks.highestExpBatch?.days_to_expiry}d left)
          </div>
        </div>

        {/* Most Urgent Expiry Batch */}
        <div className="summary-stat-card" style={{ borderLeft: `3px solid ${C_INFO}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="summary-stat-label">Earliest Expiring Batch</span>
            <span className="badge badge-medium" style={{ fontSize: '0.6rem' }}>URGENT LOT</span>
          </div>
          <div className="summary-stat-title">
            {topRisks.earliestExpiryBatch?.medicine_name ?? '—'}
          </div>
          <div className="summary-stat-sub">
            Branch <strong>{topRisks.earliestExpiryBatch?.branch_id ?? '—'}</strong> • Batch <strong>{topRisks.earliestExpiryBatch?.batch_id ?? '—'}</strong> • Expires in <strong style={{ color: C_DANGER }}>{topRisks.earliestExpiryBatch?.days_to_expiry} day(s)</strong> ({topRisks.earliestExpiryBatch?.batch_quantity} units)
          </div>
        </div>
      </div>

      {/* ── 3 & 4. Risk Distributions (Side by Side) ─────────── */}
      <div className="chart-grid">
        {/* Stockout Risk Distribution */}
        <ChartCard
          title="Stockout Risk Distribution"
          subtitle="How many branch-medicine pairs are at each stockout severity level"
          loading={stockoutQuery.loading}
          error={stockoutQuery.error}
          onRetry={stockoutQuery.refetch}
          isEmpty={!stockoutDistData.length}
          height={260}
        >
          <div style={{ display: 'flex', alignItems: 'center', height: '260px' }}>
            <div style={{ flex: 1, height: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={stockoutDistData}
                    cx="50%"
                    cy="50%"
                    innerRadius={55}
                    outerRadius={90}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {stockoutDistData.map((entry) => (
                      <Cell key={entry.name} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip content={<StockoutRiskTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            {/* Legend breakdown */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', minWidth: '150px', paddingRight: '0.5rem' }}>
              {stockoutDistData.map((item) => (
                <div key={item.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: item.fill }} />
                    <span style={{ fontWeight: 500 }}>{item.name}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', color: '#8b90a8' }}>
                    <span style={{ fontWeight: 600, color: '#e4e6f0' }}>{fmtNum(item.value)}</span>
                    <span style={{ fontSize: '0.7rem' }}>({item.pct})</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </ChartCard>

        {/* Expiry Risk Distribution */}
        <ChartCard
          title="Expiry Risk Distribution"
          subtitle="Batch lots and projected at-risk inventory value by risk level"
          loading={expiryQuery.loading}
          error={expiryQuery.error}
          onRetry={expiryQuery.refetch}
          isEmpty={!expiryDistData.length}
          height={260}
        >
          <div style={{ width: '100%', height: '260px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={expiryDistData} margin={{ top: 10, right: 20, left: -10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
                <XAxis dataKey="level" tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                <YAxis tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                <Tooltip content={<ExpiryRiskTooltip />} />
                <Bar dataKey="lots" name="Lots Count" radius={[4, 4, 0, 0]}>
                  {expiryDistData.map((entry) => (
                    <Cell key={entry.level} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </div>

      {/* ── 5 & 6. Critical Stockout Risks Table ──────────────── */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div className="card-title">Stockout Risk Intelligence</div>
            <div className="card-subtitle">
              Branch-medicine pairs prioritized by insufficient days of cover and forecasted demand
            </div>
          </div>

          {/* Table Filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            {/* Risk Level Toggle */}
            <div className="btn-toggle-group">
              {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((lvl) => (
                <button
                  key={lvl}
                  className={`btn-toggle ${stockoutRiskFilter === lvl ? 'active' : ''}`}
                  onClick={() => { setStockoutRiskFilter(lvl); setStockoutPage(0); }}
                >
                  {lvl}
                </button>
              ))}
            </div>

            {/* Branch select */}
            <select
              className="filter-select"
              value={stockoutBranchFilter}
              onChange={(e) => { setStockoutBranchFilter(e.target.value); setStockoutPage(0); }}
            >
              <option value="">All Branches</option>
              <option value="BR001">BR001 (Main Central)</option>
              <option value="BR002">BR002 (North Clinic)</option>
              <option value="BR003">BR003 (South Plaza)</option>
              <option value="BR004">BR004 (Eastside)</option>
              <option value="BR005">BR005 (West End)</option>
            </select>

            {/* Search */}
            <input
              type="text"
              className="filter-input"
              placeholder="Search medicine / ID..."
              value={stockoutSearch}
              onChange={(e) => { setStockoutSearch(e.target.value); setStockoutPage(0); }}
              style={{ width: '160px' }}
            />
          </div>
        </div>

        <div className="card-body" style={{ padding: 0 }}>
          {stockoutQuery.loading ? (
            <div style={{ padding: '1.5rem' }}>
              <div className="skeleton" style={{ height: '240px', width: '100%', borderRadius: '4px' }} />
            </div>
          ) : stockoutQuery.error ? (
            <div className="error-state">
              <span className="error-icon">⚠</span>
              <span className="error-msg">Unable to load stockout risk data.</span>
              <button className="retry-btn" onClick={stockoutQuery.refetch}>Retry</button>
            </div>
          ) : filteredStockouts.length === 0 ? (
            <div className="empty-state">
              No stockout risks found for the selected filter.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Branch</th>
                    <th>Medicine</th>
                    <th>Current Stock</th>
                    <th>Daily Demand</th>
                    <th>Days of Cover</th>
                    <th>7D Forecast</th>
                    <th>Primary Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedStockouts.map((row) => {
                    const isZeroStock = Number(row.current_inventory_units) === 0;
                    const cover = Number(row.days_of_cover);
                    return (
                      <tr key={`${row.branch_id}-${row.medicine_id}`}>
                        <td>
                          <PriorityBadge level={row.risk_level} />
                        </td>
                        <td>
                          <span style={{ fontWeight: 600, color: '#818cf8', fontSize: '0.75rem' }}>
                            {row.branch_id}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{row.medicine_name}</div>
                          <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>
                            {row.medicine_id} • {row.category}
                          </div>
                        </td>
                        <td>
                          <span style={{
                            fontWeight: 700,
                            color: isZeroStock ? C_DANGER : '#e4e6f0',
                            padding: isZeroStock ? '0.1rem 0.4rem' : '0',
                            background: isZeroStock ? 'rgba(239, 68, 68, 0.15)' : 'transparent',
                            borderRadius: '4px',
                          }}>
                            {fmtNum(row.current_inventory_units)} units
                          </span>
                        </td>
                        <td>{Number(row.expected_daily_demand || row.recent_daily_demand || 0).toFixed(2)}/d</td>
                        <td>
                          <span style={{
                            fontWeight: 600,
                            color: cover <= 3 ? C_DANGER : cover <= 7 ? C_WARNING : '#e4e6f0',
                          }}>
                            {cover.toFixed(1)} days
                          </span>
                        </td>
                        <td>{Number(row.forecast_7d || 0).toFixed(1)} units</td>
                        <td>
                          <span className="truncate-text" title={row.primary_reason} style={{ maxWidth: '320px' }}>
                            {row.primary_reason ?? '—'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Stockout Table Pagination */}
          {filteredStockouts.length > pageSize && (
            <div className="table-pagination">
              <span>
                Showing <strong>{stockoutPage * pageSize + 1}</strong>–
                <strong>{Math.min((stockoutPage + 1) * pageSize, filteredStockouts.length)}</strong> of{' '}
                <strong>{filteredStockouts.length}</strong> matching pairs
              </span>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  className="pagination-btn"
                  disabled={stockoutPage === 0}
                  onClick={() => setStockoutPage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <button
                  className="pagination-btn"
                  disabled={stockoutPage >= stockoutPageCount - 1}
                  onClick={() => setStockoutPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── 7, 8, 9. Expiring Inventory & FEFO Actions ─────────── */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div className="card-title">Expiring Inventory & Batch Actions</div>
            <div className="card-subtitle">
              Live batch lots evaluated under First-Expired, First-Out (FEFO) order with projected unsold exposure
            </div>
          </div>

          {/* Expiry Filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            {/* Risk Level Toggle */}
            <div className="btn-toggle-group">
              {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((lvl) => (
                <button
                  key={lvl}
                  className={`btn-toggle ${expiryRiskFilter === lvl ? 'active' : ''}`}
                  onClick={() => { setExpiryRiskFilter(lvl); setExpiryPage(0); }}
                >
                  {lvl}
                </button>
              ))}
            </div>

            {/* Action filter */}
            <select
              className="filter-select"
              value={expiryActionFilter}
              onChange={(e) => { setExpiryActionFilter(e.target.value); setExpiryPage(0); }}
            >
              <option value="">All Actions</option>
              <option value="PRIORITIZE_SALE">PRIORITIZE SALE</option>
              <option value="MONITOR">MONITOR</option>
              <option value="NO_ACTION">NO ACTION</option>
            </select>

            {/* Branch select */}
            <select
              className="filter-select"
              value={expiryBranchFilter}
              onChange={(e) => { setExpiryBranchFilter(e.target.value); setExpiryPage(0); }}
            >
              <option value="">All Branches</option>
              <option value="BR001">BR001</option>
              <option value="BR002">BR002</option>
              <option value="BR003">BR003</option>
              <option value="BR004">BR004</option>
              <option value="BR005">BR005</option>
            </select>

            {/* Search */}
            <input
              type="text"
              className="filter-input"
              placeholder="Search batch / medicine..."
              value={expirySearch}
              onChange={(e) => { setExpirySearch(e.target.value); setExpiryPage(0); }}
              style={{ width: '160px' }}
            />
          </div>
        </div>

        <div className="card-body" style={{ padding: 0 }}>
          {expiryQuery.loading ? (
            <div style={{ padding: '1.5rem' }}>
              <div className="skeleton" style={{ height: '240px', width: '100%', borderRadius: '4px' }} />
            </div>
          ) : expiryQuery.error ? (
            <div className="error-state">
              <span className="error-icon">⚠</span>
              <span className="error-msg">Unable to load expiring inventory data.</span>
              <button className="retry-btn" onClick={expiryQuery.refetch}>Retry</button>
            </div>
          ) : filteredExpiries.length === 0 ? (
            <div className="empty-state">
              No expiring inventory found for the selected filter.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Branch</th>
                    <th>Medicine</th>
                    <th>Batch ID</th>
                    <th>Batch Qty</th>
                    <th>Days to Expiry</th>
                    <th>Projected Unsold</th>
                    <th>At-Risk Value</th>
                    <th>Recommended Action</th>
                    <th>Assessment Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedExpiries.map((row) => {
                    const days = Number(row.days_to_expiry);
                    const unsoldVal = Number(row.projected_unsold_value || 0);
                    return (
                      <tr key={`${row.branch_id}-${row.batch_id}`}>
                        <td>
                          <PriorityBadge level={row.risk_level} />
                        </td>
                        <td>
                          <span style={{ fontWeight: 600, color: '#818cf8', fontSize: '0.75rem' }}>
                            {row.branch_id}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{row.medicine_name}</div>
                          <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>
                            {row.category}
                          </div>
                        </td>
                        <td>
                          <code style={{
                            fontFamily: 'monospace',
                            fontSize: '0.72rem',
                            color: '#93c5fd',
                            background: '#1e2235',
                            padding: '0.15rem 0.35rem',
                            borderRadius: '3px',
                          }}>
                            {row.batch_id}
                          </code>
                        </td>
                        <td>{fmtNum(row.batch_quantity)} units</td>
                        <td>
                          <div style={{
                            fontWeight: 700,
                            color: days <= 15 ? C_DANGER : days <= 30 ? C_WARNING : '#e4e6f0',
                          }}>
                            {days} days
                          </div>
                          <div style={{ fontSize: '0.65rem', color: '#8b90a8' }}>
                            {fmtDate(row.expiry_date)}
                          </div>
                        </td>
                        <td>
                          <span style={{ fontWeight: 600 }}>
                            {Number(row.projected_unsold_units || 0).toFixed(1)} units
                          </span>
                        </td>
                        <td>
                          <span style={{ fontWeight: 700, color: unsoldVal > 0 ? '#fbbf24' : '#8b90a8' }}>
                            {fmtINR(unsoldVal)}
                          </span>
                        </td>
                        <td>
                          <ActionBadge action={row.recommended_action} />
                        </td>
                        <td>
                          <span className="truncate-text" title={row.reason} style={{ maxWidth: '280px' }}>
                            {row.reason ?? '—'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Expiry Table Pagination */}
          {filteredExpiries.length > pageSize && (
            <div className="table-pagination">
              <span>
                Showing <strong>{expiryPage * pageSize + 1}</strong>–
                <strong>{Math.min((expiryPage + 1) * pageSize, filteredExpiries.length)}</strong> of{' '}
                <strong>{filteredExpiries.length}</strong> matching lots
              </span>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  className="pagination-btn"
                  disabled={expiryPage === 0}
                  onClick={() => setExpiryPage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <button
                  className="pagination-btn"
                  disabled={expiryPage >= expiryPageCount - 1}
                  onClick={() => setExpiryPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── 11. Action Queue Summary (Decision Support Output) ─ */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Risk-Driven Action Summary</div>
            <div className="card-subtitle">Prioritized inventory decisions generated by the Decision Support layer</div>
          </div>
          <span className="badge badge-critical">
            {actionSummaryMetrics.urgentList.length} Immediate Mitigations
          </span>
        </div>
        <div className="card-body">
          {/* Action chips breakdown */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
            gap: '0.75rem',
            marginBottom: '1.25rem'
          }}>
            <div style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius)', padding: '0.75rem 1rem' }}>
              <div style={{ fontSize: '0.68rem', color: '#f87171', fontWeight: 600, textTransform: 'uppercase' }}>ORDER NOW</div>
              <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#e4e6f0' }}>{fmtNum(actionSummaryMetrics.counts.ORDER_NOW)}</div>
              <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>Stockout prevention orders</div>
            </div>
            <div style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius)', padding: '0.75rem 1rem' }}>
              <div style={{ fontSize: '0.68rem', color: '#fbbf24', fontWeight: 600, textTransform: 'uppercase' }}>PRIORITIZE SALE</div>
              <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#e4e6f0' }}>{fmtNum(actionSummaryMetrics.counts.PRIORITIZE_SALE_EXPIRING_STOCK)}</div>
              <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>Near-dated stock promotions</div>
            </div>
            <div style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius)', padding: '0.75rem 1rem' }}>
              <div style={{ fontSize: '0.68rem', color: '#7dd3fc', fontWeight: 600, textTransform: 'uppercase' }}>MONITOR STOCK</div>
              <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#e4e6f0' }}>{fmtNum(actionSummaryMetrics.counts.MONITOR_STOCK_CLOSELY)}</div>
              <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>Fast-depleting item watch</div>
            </div>
            <div style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius)', padding: '0.75rem 1rem' }}>
              <div style={{ fontSize: '0.68rem', color: '#a78bfa', fontWeight: 600, textTransform: 'uppercase' }}>MONITOR EXPIRY</div>
              <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#e4e6f0' }}>{fmtNum(actionSummaryMetrics.counts.MONITOR_EXPIRY)}</div>
              <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>Medium-term expiry watch</div>
            </div>
          </div>

          {/* Top action queue list */}
          {actionQuery.loading ? (
            <div className="skeleton" style={{ height: '140px', width: '100%', borderRadius: '4px' }} />
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Queue #</th>
                    <th>Priority</th>
                    <th>Primary Action</th>
                    <th>Branch</th>
                    <th>Medicine</th>
                    <th>Est. Impact Value</th>
                    <th>Primary Rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {actionSummaryMetrics.urgentList.map((item) => (
                    <tr key={item.queue_position}>
                      <td style={{ fontWeight: 700, color: '#818cf8' }}>#{item.queue_position}</td>
                      <td><PriorityBadge level={item.priority} /></td>
                      <td><ActionBadge action={item.primary_action} /></td>
                      <td><strong style={{ color: '#818cf8' }}>{item.branch_id}</strong></td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{item.medicine_name}</div>
                        <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>{item.category}</div>
                      </td>
                      <td>
                        <span style={{ fontWeight: 700, color: '#fbbf24' }}>
                          {fmtINR(item.impact_value ?? item.potential_stockout_exposure_value)}
                        </span>
                      </td>
                      <td>
                        <span className="truncate-text" title={item.primary_reason} style={{ maxWidth: '300px' }}>
                          {item.primary_reason}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── 12. Risk Explanation Panel ───────────────────────── */}
      <div className="card" style={{ background: '#141722', borderColor: '#2d3147' }}>
        <div className="card-header">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>📖</span> How to Read this Risk & Expiry Intelligence Dashboard
          </div>
        </div>
        <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.25rem', fontSize: '0.8rem', color: '#a0a5bd' }}>
          <div>
            <h4 style={{ color: '#e4e6f0', marginBottom: '0.35rem' }}>Stockout Risk Model</h4>
            <p style={{ fontSize: '0.78rem', lineHeight: '1.5' }}>
              Evaluates branch-medicine combinations where current stock fails to cover expected demand during the 7-day supplier lead time under a 95% service level buffer. Escalated when 28-day historical stockout events occurred.
            </p>
          </div>
          <div>
            <h4 style={{ color: '#e4e6f0', marginBottom: '0.35rem' }}>Expiry Risk Model & FEFO Policy</h4>
            <p style={{ fontSize: '0.78rem', lineHeight: '1.5' }}>
              Assesses active inventory batches under First-Expired, First-Out (FEFO) dispensing order against 90-day recent daily demand and 365-day projection horizons to identify lots that will not sell before expiry.
            </p>
          </div>
          <div>
            <h4 style={{ color: '#e4e6f0', marginBottom: '0.35rem' }}>Analytical Exposure Figures</h4>
            <p style={{ fontSize: '0.78rem', lineHeight: '1.5' }}>
              All financial values represent estimated analytical exposure (potential revenue at risk for stockouts and purchase cost value for expiring stock) to aid management prioritization, rather than realized accounting losses.
            </p>
          </div>
        </div>
      </div>

    </div>
  );
}
