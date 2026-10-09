import { useState, useMemo } from 'react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import OlapExplorer from '../components/OlapExplorer';
import { useFetch } from '../hooks/useFetch';
import { fetchSales, fetchBranches, fetchMedicines } from '../api/client';
import { fmtINR_SI, fmtNum, fmtUnits, fmtPct } from '../utils/format';

// ── Chart colours ─────────────────────────────────────────
const C_ACCENT   = '#6366f1';
const C_SUCCESS  = '#22c55e';
const C_WARNING  = '#f59e0b';
const C_INFO     = '#38bdf8';
const C_PURPLE   = '#a78bfa';

// ── Recharts tooltip style ─────────────────────────────────
const tooltipStyle = {
  backgroundColor: '#1a1d27',
  border: '1px solid #2d3147',
  borderRadius: '6px',
  fontSize: '0.75rem',
  color: '#e4e6f0',
};

// ── Custom Revenue Trend Tooltip ───────────────────────────
function RevenueTrendTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ padding: '0.5rem 0.75rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        {payload.map((p) => (
          <div key={p.name} style={{ color: p.color, display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
            <span>{p.name}:</span>
            <span style={{ fontWeight: 600 }}>
              {p.name === 'Revenue' ? fmtINR_SI(p.value) : fmtUnits(p.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Custom Category Tooltip ────────────────────────────────
function CategoryTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>
        {item.category_name}
      </div>
      <div style={{ padding: '0.5rem 0.75rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        <div style={{ color: C_ACCENT, display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span>Revenue:</span>
          <span style={{ fontWeight: 600 }}>{fmtINR_SI(item.revenue)}</span>
        </div>
        {item.revenue_share_pct != null && (
          <div style={{ color: '#8b90a8', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
            <span>Revenue Share:</span>
            <span style={{ fontWeight: 600 }}>{fmtPct(item.revenue_share_pct)}</span>
          </div>
        )}
        <div style={{ color: C_INFO, display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span>Units Sold:</span>
          <span style={{ fontWeight: 600 }}>{fmtUnits(item.units)}</span>
        </div>
        <div style={{ color: C_SUCCESS, display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span>Transactions:</span>
          <span style={{ fontWeight: 600 }}>{fmtNum(item.transactions)}</span>
        </div>
      </div>
    </div>
  );
}

// ── Custom Branch Tooltip ──────────────────────────────────
function BranchTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>
        {item.branch_name} {item.area && `(${item.area})`}
      </div>
      <div style={{ padding: '0.5rem 0.75rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        <div style={{ color: C_SUCCESS, display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span>Revenue:</span>
          <span style={{ fontWeight: 600 }}>{fmtINR_SI(item.revenue)}</span>
        </div>
        <div style={{ color: '#8b90a8', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span>Share:</span>
          <span style={{ fontWeight: 600 }}>{fmtPct(item.revenue_share_pct)}</span>
        </div>
        <div style={{ color: C_INFO, display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span>Units Sold:</span>
          <span style={{ fontWeight: 600 }}>{fmtUnits(item.units)}</span>
        </div>
        <div style={{ color: C_WARNING, display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
          <span>AOV:</span>
          <span style={{ fontWeight: 600 }}>{fmtINR_SI(item.avg_transaction_value)}</span>
        </div>
      </div>
    </div>
  );
}

// ── Formatters ─────────────────────────────────────────────
const fmtYAxisINR = (v) => fmtINR_SI(v);
const fmtYAxisUnits = (v) => fmtUnits(v);

// ─────────────────────────────────────────────────────────────
// Sales & Analytics Page
// ─────────────────────────────────────────────────────────────
export default function Sales() {
  // Filter form state
  const [startDateInput, setStartDateInput] = useState('');
  const [endDateInput, setEndDateInput]     = useState('');

  // Applied filter state (triggers API call)
  const [appliedDates, setAppliedDates] = useState({ start_date: '', end_date: '' });

  // Medicine sorting state
  const [medSort, setMedSort] = useState('revenue');

  // Independent API queries
  const salesQuery = useFetch(
    () => fetchSales({
      start_date: appliedDates.start_date || undefined,
      end_date: appliedDates.end_date || undefined,
    }),
    [appliedDates.start_date, appliedDates.end_date]
  );

  const branchesQuery = useFetch(() => fetchBranches({ limit: 20 }), []);

  const medicinesQuery = useFetch(
    () => fetchMedicines({ sort_by: medSort, limit: 10 }),
    [medSort]
  );

  // ── Handlers ──────────────────────────────────────────────
  const handleApplyFilter = (e) => {
    e.preventDefault();
    if (startDateInput && endDateInput && startDateInput > endDateInput) return;
    setAppliedDates({
      start_date: startDateInput,
      end_date: endDateInput,
    });
  };

  const handleResetFilter = () => {
    setStartDateInput('');
    setEndDateInput('');
    setAppliedDates({ start_date: '', end_date: '' });
  };

  // ── Derived: Sales Data ───────────────────────────────────
  const s = salesQuery.data?.data;

  // Monthly trend for Recharts
  const monthlyTrend = useMemo(() => {
    const rows = s?.monthly_trend ?? [];
    return rows.map((r) => {
      const shortMonth = r.month_name ? r.month_name.slice(0, 3) : `M${r.month}`;
      const yr = r.year ? String(r.year).slice(2) : '';
      return {
        ...r,
        label: `${shortMonth} '${yr}`,
      };
    });
  }, [s?.monthly_trend]);

  // Category performance for horizontal bar chart
  const categoryData = useMemo(() => {
    const rows = s?.category_performance ?? [];
    return [...rows].sort((a, b) => b.revenue - a.revenue);
  }, [s?.category_performance]);

  // Branch performance rows
  const branchRows = useMemo(() => {
    return branchesQuery.data?.data ?? [];
  }, [branchesQuery.data]);

  // Medicine performance rows
  const medicineRows = useMemo(() => {
    return medicinesQuery.data?.data ?? [];
  }, [medicinesQuery.data]);

  // ── Derived: Insights ─────────────────────────────────────
  const insights = useMemo(() => {
    const topCat = categoryData[0];
    const topMed = medicineRows[0];
    const topBranch = branchRows[0];
    return {
      topCategory: topCat ? { name: topCat.category_name, revenue: topCat.revenue, share: topCat.revenue_share_pct } : null,
      topMedicine: topMed ? { name: topMed.medicine_name, revenue: topMed.revenue, units: topMed.units } : null,
      topBranch: topBranch ? { name: topBranch.branch_name, revenue: topBranch.revenue, share: topBranch.revenue_share_pct } : null,
      avgBasket: s?.avg_transaction_value,
    };
  }, [categoryData, medicineRows, branchRows, s]);

  const hasFilter = Boolean(appliedDates.start_date || appliedDates.end_date);
  const isDateInvalid = Boolean(startDateInput && endDateInput && startDateInput > endDateInput);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* ── Page Header ───────────────────────────────── */}
      <div className="page-header">
        <div className="page-title">Sales & Analytics</div>
        <div className="page-subtitle">
          Revenue, demand and sales performance across MedStock
          {hasFilter && ` · Filtered: ${appliedDates.start_date || 'Start'} to ${appliedDates.end_date || 'Present'}`}
        </div>
      </div>

      {/* ── Filter Bar ────────────────────────────────── */}
      <form className="filter-bar" onSubmit={handleApplyFilter}>
        <div className="filter-group">
          <span className="filter-label">Start Date</span>
          <input
            type="date"
            className="filter-input"
            value={startDateInput}
            min="2025-01-01"
            max="2026-12-31"
            onChange={(e) => setStartDateInput(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <span className="filter-label">End Date</span>
          <input
            type="date"
            className="filter-input"
            value={endDateInput}
            min="2025-01-01"
            max="2026-12-31"
            onChange={(e) => setEndDateInput(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            type="submit"
            className="filter-btn-apply"
            disabled={isDateInvalid || (!startDateInput && !endDateInput && !hasFilter)}
          >
            Apply
          </button>
          {hasFilter && (
            <button
              type="button"
              className="filter-btn-reset"
              onClick={handleResetFilter}
            >
              Reset
            </button>
          )}
        </div>

        {isDateInvalid && (
          <span style={{ fontSize: '0.75rem', color: 'var(--color-danger)' }}>
            Start date cannot be after end date
          </span>
        )}
      </form>

      {/* ── Insights / Summary Cards ──────────────────── */}
      <div className="summary-grid">
        <div className="summary-stat-card">
          <span className="summary-stat-label">Top Category</span>
          <div className="summary-stat-title">{insights.topCategory?.name ?? '—'}</div>
          <div className="summary-stat-sub">
            {insights.topCategory
              ? `${fmtINR_SI(insights.topCategory.revenue)} (${fmtPct(insights.topCategory.share)})`
              : 'Leading category by revenue'}
          </div>
        </div>

        <div className="summary-stat-card">
          <span className="summary-stat-label">Top Medicine ({medSort === 'revenue' ? 'Revenue' : 'Units'})</span>
          <div className="summary-stat-title" title={insights.topMedicine?.name}>
            {insights.topMedicine?.name ?? '—'}
          </div>
          <div className="summary-stat-sub">
            {insights.topMedicine
              ? `${fmtINR_SI(insights.topMedicine.revenue)} · ${fmtUnits(insights.topMedicine.units)} units`
              : 'Highest volume SKU'}
          </div>
        </div>

        <div className="summary-stat-card">
          <span className="summary-stat-label">Top Branch</span>
          <div className="summary-stat-title">{insights.topBranch?.name ?? '—'}</div>
          <div className="summary-stat-sub">
            {insights.topBranch
              ? `${fmtINR_SI(insights.topBranch.revenue)} (${fmtPct(insights.topBranch.share)})`
              : 'Leading retail branch'}
          </div>
        </div>

        <div className="summary-stat-card">
          <span className="summary-stat-label">Average Basket</span>
          <div className="summary-stat-title">
            {insights.avgBasket != null ? fmtINR_SI(insights.avgBasket) : '—'}
          </div>
          <div className="summary-stat-sub">Across all customer orders</div>
        </div>
      </div>

      {/* ── KPI Cards ─────────────────────────────────── */}
      <section>
        <div style={{
          fontSize: '0.7rem',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--color-muted)',
          fontWeight: 600,
          marginBottom: '0.6rem',
        }}>
          Sales Metrics {hasFilter ? '(Filtered Period)' : '(Full Period)'}
        </div>
        <div className="kpi-grid">
          <KpiCard
            label="Total Revenue"
            value={fmtINR_SI(s?.revenue)}
            note={hasFilter ? 'Filtered period' : 'All branches, full period'}
            accent="purple"
            loading={salesQuery.loading}
          />
          <KpiCard
            label="Units Sold"
            value={fmtUnits(s?.units)}
            note="Sale lines fulfilled"
            accent="blue"
            loading={salesQuery.loading}
          />
          <KpiCard
            label="Transactions"
            value={fmtNum(s?.transactions)}
            note="Unique customer visits"
            accent="green"
            loading={salesQuery.loading}
          />
          <KpiCard
            label="Avg Transaction Value"
            value={fmtINR_SI(s?.avg_transaction_value)}
            note="Revenue ÷ transactions"
            accent="amber"
            loading={salesQuery.loading}
          />
        </div>
      </section>

      {/* ── Charts: Revenue Trend + Category Performance */}
      <div className="chart-grid-3">
        {/* Revenue Trend Area Chart */}
        <ChartCard
          title="Revenue Trend"
          subtitle="Monthly sales performance and volume"
          loading={salesQuery.loading}
          error={salesQuery.error}
          onRetry={salesQuery.refetch}
          isEmpty={monthlyTrend.length === 0}
          height={320}
        >
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={monthlyTrend} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <defs>
                <linearGradient id="salesRevGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={C_ACCENT} stopOpacity={0.4} />
                  <stop offset="95%" stopColor={C_ACCENT} stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="salesUnitsGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={C_INFO} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={C_INFO} stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
              <XAxis
                dataKey="label"
                stroke="#8b90a8"
                fontSize={11}
                tickLine={false}
                axisLine={{ stroke: '#2d3147' }}
              />
              <YAxis
                yAxisId="rev"
                stroke="#8b90a8"
                fontSize={11}
                tickLine={false}
                axisLine={false}
                tickFormatter={fmtYAxisINR}
                width={56}
              />
              <YAxis
                yAxisId="units"
                orientation="right"
                stroke="#8b90a8"
                fontSize={11}
                tickLine={false}
                axisLine={false}
                tickFormatter={fmtYAxisUnits}
                width={48}
              />
              <Tooltip content={<RevenueTrendTooltip />} />
              <Area
                yAxisId="rev"
                type="monotone"
                dataKey="revenue"
                name="Revenue"
                stroke={C_ACCENT}
                strokeWidth={2}
                fill="url(#salesRevGrad)"
              />
              <Area
                yAxisId="units"
                type="monotone"
                dataKey="units"
                name="Units"
                stroke={C_INFO}
                strokeWidth={1.5}
                strokeDasharray="4 4"
                fill="url(#salesUnitsGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Category Performance Bar Chart */}
        <ChartCard
          title="Category Performance"
          subtitle="Revenue distribution by category"
          loading={salesQuery.loading}
          error={salesQuery.error}
          onRetry={salesQuery.refetch}
          isEmpty={categoryData.length === 0}
          height={320}
        >
          <ResponsiveContainer width="100%" height={320}>
            <BarChart
              data={categoryData}
              layout="vertical"
              margin={{ top: 5, right: 15, left: 10, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" horizontal={false} />
              <XAxis
                type="number"
                stroke="#8b90a8"
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: '#2d3147' }}
                tickFormatter={fmtYAxisINR}
              />
              <YAxis
                type="category"
                dataKey="category_name"
                stroke="#8b90a8"
                fontSize={10.5}
                tickLine={false}
                axisLine={false}
                width={100}
              />
              <Tooltip content={<CategoryTooltip />} />
              <Bar dataKey="revenue" name="Revenue" fill={C_ACCENT} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* ── Top Medicines Section ───────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Top Performing Medicines</div>
            <div className="card-subtitle">
              Ranked by {medSort === 'revenue' ? 'total revenue generated' : 'total units sold'} (Top 10)
            </div>
          </div>
          <div className="btn-toggle-group">
            <button
              type="button"
              className={`btn-toggle ${medSort === 'revenue' ? 'active' : ''}`}
              onClick={() => setMedSort('revenue')}
            >
              Revenue
            </button>
            <button
              type="button"
              className={`btn-toggle ${medSort === 'units' ? 'active' : ''}`}
              onClick={() => setMedSort('units')}
            >
              Units
            </button>
          </div>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {medicinesQuery.loading ? (
            <div style={{ padding: '1.25rem' }}>
              <div className="skeleton" style={{ height: '240px', width: '100%', borderRadius: '4px' }} />
            </div>
          ) : medicinesQuery.error ? (
            <div className="error-state" style={{ minHeight: '200px' }}>
              <span className="error-icon">⚠</span>
              <span className="error-msg">{medicinesQuery.error}</span>
              <button className="retry-btn" onClick={medicinesQuery.refetch}>Retry</button>
            </div>
          ) : medicineRows.length === 0 ? (
            <div className="empty-state" style={{ minHeight: '160px' }}>
              No medicine performance data available.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: '48px', textAlign: 'center' }}>Rank</th>
                    <th>Medicine</th>
                    <th>Category</th>
                    <th style={{ textAlign: 'right' }}>Revenue</th>
                    <th style={{ textAlign: 'right' }}>Units Sold</th>
                    <th style={{ textAlign: 'right' }}>Transactions</th>
                    <th style={{ textAlign: 'right' }}>AOV</th>
                  </tr>
                </thead>
                <tbody>
                  {medicineRows.map((med, idx) => {
                    const aov = med.revenue && med.transactions ? med.revenue / med.transactions : null;
                    return (
                      <tr key={med.medicine_id ?? idx}>
                        <td style={{ textAlign: 'center', fontWeight: 700, color: idx < 3 ? 'var(--color-accent-light)' : 'var(--color-muted)' }}>
                          #{idx + 1}
                        </td>
                        <td>
                          <div style={{ fontWeight: 600, color: 'var(--color-text)' }}>
                            {med.medicine_name}
                          </div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--color-muted)' }}>
                            {med.manufacturer ?? med.medicine_id}
                          </div>
                        </td>
                        <td>
                          <span style={{
                            fontSize: '0.7rem',
                            padding: '0.15rem 0.45rem',
                            borderRadius: '4px',
                            background: 'var(--color-surface-2)',
                            color: 'var(--color-muted)',
                            border: '1px solid var(--color-border)',
                          }}>
                            {med.category_name}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>
                          {fmtINR_SI(med.revenue)}
                        </td>
                        <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                          {fmtUnits(med.units)}
                        </td>
                        <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                          {fmtNum(med.transactions)}
                        </td>
                        <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                          {aov != null ? fmtINR_SI(aov) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── Branch Performance Section ──────────────────── */}
      <div className="chart-grid">
        {/* Branch Bar Chart */}
        <ChartCard
          title="Branch Performance"
          subtitle="Revenue across retail locations"
          loading={branchesQuery.loading}
          error={branchesQuery.error}
          onRetry={branchesQuery.refetch}
          isEmpty={branchRows.length === 0}
          height={260}
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={branchRows}
              margin={{ top: 10, right: 15, left: 0, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
              <XAxis
                dataKey="branch_name"
                stroke="#8b90a8"
                fontSize={10.5}
                tickLine={false}
                axisLine={{ stroke: '#2d3147' }}
                tickFormatter={(name) => name.replace('MedStock ', '')}
              />
              <YAxis
                stroke="#8b90a8"
                fontSize={10.5}
                tickLine={false}
                axisLine={false}
                tickFormatter={fmtYAxisINR}
                width={56}
              />
              <Tooltip content={<BranchTooltip />} />
              <Bar dataKey="revenue" name="Revenue" fill={C_SUCCESS} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Compact Branch Table */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Branch Overview</div>
              <div className="card-subtitle">Retail branch metrics sorted by revenue</div>
            </div>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {branchesQuery.loading ? (
              <div style={{ padding: '1rem' }}>
                <div className="skeleton" style={{ height: '220px', width: '100%', borderRadius: '4px' }} />
              </div>
            ) : branchesQuery.error ? (
              <div className="error-state" style={{ minHeight: '180px' }}>
                <span className="error-icon">⚠</span>
                <span className="error-msg">{branchesQuery.error}</span>
                <button className="retry-btn" onClick={branchesQuery.refetch}>Retry</button>
              </div>
            ) : branchRows.length === 0 ? (
              <div className="empty-state" style={{ minHeight: '160px' }}>
                No branch data available.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Branch</th>
                      <th style={{ textAlign: 'right' }}>Revenue</th>
                      <th style={{ textAlign: 'right' }}>Units</th>
                      <th style={{ textAlign: 'right' }}>Transactions</th>
                      <th style={{ textAlign: 'right' }}>AOV</th>
                      <th style={{ textAlign: 'right' }}>Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {branchRows.map((b) => (
                      <tr key={b.branch_id}>
                        <td>
                          <div style={{ fontWeight: 600 }}>{b.branch_name}</div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--color-muted)' }}>
                            {b.area ?? b.branch_id}
                          </div>
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>
                          {fmtINR_SI(b.revenue)}
                        </td>
                        <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                          {fmtUnits(b.units)}
                        </td>
                        <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                          {fmtNum(b.transactions)}
                        </td>
                        <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                          {fmtINR_SI(b.avg_transaction_value)}
                        </td>
                        <td style={{ textAlign: 'right', color: 'var(--color-accent-light)' }}>
                          {fmtPct(b.revenue_share_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      <OlapExplorer />

    </div>
  );
}
