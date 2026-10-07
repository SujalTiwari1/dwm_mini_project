import { useMemo } from 'react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import PriorityBadge from '../components/PriorityBadge';
import { useFetch } from '../hooks/useFetch';
import {
  fetchDashboardSummary,
  fetchSales,
  fetchInventory,
  fetchBranches,
  fetchActionQueue,
} from '../api/client';
import { fmtINR_SI, fmtNum, fmtUnits, fmtDate, fmtYearMonth } from '../utils/format';

// ── Chart colours ─────────────────────────────────────────
const C_ACCENT   = '#6366f1';
const C_SUCCESS  = '#22c55e';
const C_WARNING  = '#f59e0b';
const C_DANGER   = '#ef4444';
const C_INFO     = '#38bdf8';
const C_PURPLE   = '#a78bfa';
const C_PINK     = '#f472b6';

const STATUS_COLOURS = {
  'OUT OF STOCK': C_DANGER,
  'LOW STOCK':    C_WARNING,
  'NORMAL':       C_SUCCESS,
  'OVERSTOCK':    C_INFO,
};

const CAT_COLOURS = [C_ACCENT, C_SUCCESS, C_INFO, C_WARNING, C_DANGER, C_PURPLE, C_PINK, '#34d399', '#fb923c', '#e879f9'];

// ── Recharts tooltip style ─────────────────────────────────
const tooltipStyle = {
  backgroundColor: '#1a1d27',
  border: '1px solid #2d3147',
  borderRadius: '6px',
  fontSize: '0.75rem',
  color: '#e4e6f0',
};

// ── Custom area chart tooltip ──────────────────────────────
function RevenueTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>{label}</div>
      <div style={{ padding: '0.5rem 0.75rem' }}>
        <div>Revenue: {fmtINR_SI(payload[0]?.value)}</div>
        <div style={{ color: '#8b90a8' }}>Units: {fmtUnits(payload[1]?.value)}</div>
      </div>
    </div>
  );
}

// ── Custom bar tooltip ─────────────────────────────────────
function BarTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.4rem 0.65rem', borderBottom: '1px solid #2d3147', fontWeight: 600, fontSize: '0.72rem' }}>{label}</div>
      <div style={{ padding: '0.4rem 0.65rem' }}>
        {payload.map((p) => (
          <div key={p.name} style={{ color: p.color }}>
            {p.name}: {p.name === 'Revenue' ? fmtINR_SI(p.value) : fmtUnits(p.value)}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── YAxis label formatters ────────────────────────────────
const fmtYAxisINR = (v) => fmtINR_SI(v);
const fmtYAxisUnits = (v) => fmtUnits(v);

// ── Action label prettifier ───────────────────────────────
function prettyAction(action) {
  return (action ?? '').replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

// ─────────────────────────────────────────────────────────────
// Dashboard Page
// ─────────────────────────────────────────────────────────────
export default function Dashboard() {
  // Independent fetches so one failure doesn't block others
  const summary   = useFetch(fetchDashboardSummary);
  const salesData = useFetch(fetchSales);
  const invData   = useFetch(fetchInventory);
  const branches  = useFetch(fetchBranches);
  const actions   = useFetch(() => fetchActionQueue({ priority: 'CRITICAL', limit: 8 }));

  // ── Derived: KPI values from summary.data.data ──────────
  const s = summary.data?.data;

  // ── Derived: monthly trend ───────────────────────────────
  const trend = useMemo(() => {
    const rows = salesData.data?.data?.monthly_trend ?? [];
    return rows.map((r) => ({
      ...r,
      label: fmtYearMonth(r),
    }));
  }, [salesData.data]);

  // ── Derived: category performance ───────────────────────
  const cats = useMemo(() => {
    const rows = salesData.data?.data?.category_performance ?? [];
    return [...rows].sort((a, b) => b.revenue - a.revenue);
  }, [salesData.data]);

  // ── Derived: inventory status for donut ─────────────────
  const invStatus = useMemo(() => {
    const sum = invData.data?.summary;
    if (!sum) return [];
    return [
      { name: 'OUT OF STOCK', value: Number(sum.out_of_stock) || 0 },
      { name: 'LOW STOCK',    value: Number(sum.low_stock)    || 0 },
      { name: 'NORMAL',       value: Number(sum.normal)       || 0 },
      { name: 'OVERSTOCK',    value: Number(sum.overstock)    || 0 },
    ].filter((d) => d.value > 0);
  }, [invData.data]);

  // ── Derived: branch revenue bar ─────────────────────────
  const branchRows = useMemo(() => {
    return (branches.data?.data ?? []).map((b) => ({
      name: b.branch_name ?? b.branch_id,
      Revenue: b.revenue,
      Units: b.units,
    }));
  }, [branches.data]);

  // ── Derived: action queue rows ───────────────────────────
  const actionRows = actions.data?.data ?? [];

  // ── Data-through badge ────────────────────────────────────
  // Use inventory snapshot_date from summary if available, else fall back to invData
  const dataBadgeDate = s?.inventory_snapshot_date || invData.data?.summary?.snapshot_date;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* ── Page header ──────────────────────────────── */}
      <div className="page-header">
        <div className="page-title">Dashboard</div>
        <div className="page-subtitle">
          Pharmacy inventory intelligence overview
          {dataBadgeDate && ` · Data through ${fmtDate(dataBadgeDate)}`}
        </div>
      </div>

      {/* ── KPI grid — Sales ─────────────────────────── */}
      <section>
        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--color-muted)', fontWeight: 600, marginBottom: '0.6rem' }}>
          Sales Performance
        </div>
        <div className="kpi-grid">
          <KpiCard
            label="Total Revenue"
            value={fmtINR_SI(s?.total_revenue)}
            note="All branches, full period"
            accent="purple"
            loading={summary.loading}
          />
          <KpiCard
            label="Units Sold"
            value={fmtUnits(s?.total_units_sold)}
            note="Sale lines, full period"
            accent="blue"
            loading={summary.loading}
          />
          <KpiCard
            label="Transactions"
            value={fmtNum(s?.total_transactions)}
            note="Unique basket IDs"
            accent="green"
            loading={summary.loading}
          />
          <KpiCard
            label="Avg Transaction Value"
            value={fmtINR_SI(s?.average_transaction_value)}
            note="Revenue ÷ transactions"
            accent="blue"
            loading={summary.loading}
          />
        </div>
      </section>

      {/* ── KPI grid — Inventory ─────────────────────── */}
      <section>
        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--color-muted)', fontWeight: 600, marginBottom: '0.6rem' }}>
          Inventory Snapshot
        </div>
        <div className="kpi-grid">
          <KpiCard
            label="Current Inventory"
            value={fmtUnits(s?.current_inventory_units)}
            note="Units on hand (latest)"
            accent="blue"
            loading={summary.loading}
          />
          <KpiCard
            label="Inventory Value"
            value={fmtINR_SI(s?.current_inventory_value)}
            note="At cost (latest snapshot)"
            accent="purple"
            loading={summary.loading}
          />
          <KpiCard
            label="Stockout Days"
            value={fmtNum(s?.stockout_days)}
            note="Branch-medicine-days at zero"
            accent="amber"
            loading={summary.loading}
          />
          <KpiCard
            label="Expired Units"
            value={fmtUnits(s?.expired_units)}
            note="Written off at expiry"
            accent="red"
            loading={summary.loading}
          />
        </div>
      </section>

      {/* ── KPI grid — Decision Summary ──────────────── */}
      <section>
        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--color-muted)', fontWeight: 600, marginBottom: '0.6rem' }}>
          Decision Support — Action Queue
        </div>
        {summary.error ? (
          <div className="error-state">
            <span className="error-icon">⚠</span>
            <span className="error-msg">Unable to load decision data. {summary.error}</span>
            <button className="retry-btn" onClick={summary.refetch}>Retry</button>
          </div>
        ) : (
          <div className="decision-grid">
            <div className="decision-count-card">
              {summary.loading
                ? <div className="skeleton" style={{ height: '2.2rem', width: '60%', margin: '0 auto 0.4rem' }} />
                : <div className="decision-count" style={{ color: 'var(--color-danger)' }}>{s?.critical_actions ?? '—'}</div>
              }
              <div className="decision-label">Critical</div>
            </div>
            <div className="decision-count-card">
              {summary.loading
                ? <div className="skeleton" style={{ height: '2.2rem', width: '60%', margin: '0 auto 0.4rem' }} />
                : <div className="decision-count" style={{ color: 'var(--color-warning)' }}>{s?.high_actions ?? '—'}</div>
              }
              <div className="decision-label">High</div>
            </div>
            <div className="decision-count-card">
              {summary.loading
                ? <div className="skeleton" style={{ height: '2.2rem', width: '60%', margin: '0 auto 0.4rem' }} />
                : <div className="decision-count" style={{ color: 'var(--color-info)' }}>{s?.medium_actions ?? '—'}</div>
              }
              <div className="decision-label">Medium</div>
            </div>
            <div className="decision-count-card">
              {summary.loading
                ? <div className="skeleton" style={{ height: '2.2rem', width: '60%', margin: '0 auto 0.4rem' }} />
                : <div className="decision-count" style={{ color: 'var(--color-success)' }}>{s?.low_actions ?? '—'}</div>
              }
              <div className="decision-label">Low</div>
            </div>
          </div>
        )}
      </section>

      {/* ── Charts row 1: Revenue Trend + Category Perf ── */}
      <div className="chart-grid-3">

        {/* Revenue Trend */}
        <ChartCard
          title="Revenue Trend"
          subtitle="Monthly revenue performance"
          loading={salesData.loading}
          error={salesData.error ? `Unable to load sales data. ${salesData.error}` : null}
          onRetry={salesData.refetch}
          isEmpty={!salesData.loading && !salesData.error && trend.length === 0}
          height={280}
        >
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={trend} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <defs>
                <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={C_ACCENT} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={C_ACCENT} stopOpacity={0}    />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#8b90a8' }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis tickFormatter={fmtYAxisINR} tick={{ fontSize: 10, fill: '#8b90a8' }} axisLine={false} tickLine={false} width={60} />
              <Tooltip content={<RevenueTooltip />} />
              <Area type="monotone" dataKey="revenue"  stroke={C_ACCENT}  strokeWidth={2} fill="url(#revGrad)" name="Revenue" dot={false} />
              <Area type="monotone" dataKey="units"    stroke={C_INFO}    strokeWidth={1.5} fill="none" name="Units" dot={false} strokeDasharray="3 3" />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Inventory Status donut */}
        <ChartCard
          title="Inventory Status"
          subtitle="Current stock distribution"
          loading={invData.loading}
          error={invData.error ? `Unable to load inventory. ${invData.error}` : null}
          onRetry={invData.refetch}
          isEmpty={!invData.loading && !invData.error && invStatus.length === 0}
          height={280}
        >
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie
                data={invStatus}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="45%"
                innerRadius={65}
                outerRadius={95}
                paddingAngle={2}
                strokeWidth={0}
              >
                {invStatus.map((entry) => (
                  <Cell key={entry.name} fill={STATUS_COLOURS[entry.name] ?? '#8b90a8'} />
                ))}
              </Pie>
              <Tooltip
                formatter={(v, name) => [fmtNum(v) + ' pairs', name]}
                contentStyle={tooltipStyle}
                itemStyle={{ fontSize: '0.75rem' }}
              />
              <Legend
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: '0.7rem', color: '#8b90a8', paddingTop: '0.5rem' }}
                formatter={(value) => value.toLowerCase().replace(/\b\w/g, c => c.toUpperCase())}
              />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* ── Charts row 2: Category + Branch ──────────── */}
      <div className="chart-grid">

        {/* Category revenue — horizontal bar */}
        <ChartCard
          title="Revenue by Category"
          subtitle="Total sales revenue across medicine categories"
          loading={salesData.loading}
          error={salesData.error ? `Unable to load category data. ${salesData.error}` : null}
          onRetry={salesData.refetch}
          isEmpty={!salesData.loading && !salesData.error && cats.length === 0}
          height={300}
        >
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={cats} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 100 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" horizontal={false} />
              <XAxis type="number" tickFormatter={fmtYAxisINR} tick={{ fontSize: 10, fill: '#8b90a8' }} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="category_name" tick={{ fontSize: 10, fill: '#8b90a8' }} axisLine={false} tickLine={false} width={96} />
              <Tooltip content={<BarTooltip />} />
              <Bar dataKey="revenue" name="Revenue" radius={[0, 3, 3, 0]}>
                {cats.map((_, i) => (
                  <Cell key={i} fill={CAT_COLOURS[i % CAT_COLOURS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Branch performance — vertical bar */}
        <ChartCard
          title="Branch Performance"
          subtitle="Revenue by branch"
          loading={branches.loading}
          error={branches.error ? `Unable to load branch data. ${branches.error}` : null}
          onRetry={branches.refetch}
          isEmpty={!branches.loading && !branches.error && branchRows.length === 0}
          height={300}
        >
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={branchRows} margin={{ top: 4, right: 8, bottom: 20, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#8b90a8' }} axisLine={false} tickLine={false} angle={-20} textAnchor="end" interval={0} />
              <YAxis tickFormatter={fmtYAxisINR} tick={{ fontSize: 10, fill: '#8b90a8' }} axisLine={false} tickLine={false} width={60} />
              <Tooltip content={<BarTooltip />} />
              <Bar dataKey="Revenue" name="Revenue" fill={C_ACCENT} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* ── Top Critical Actions ──────────────────────── */}
      <ChartCard
        title="Critical Action Queue"
        subtitle="Highest-priority items requiring immediate attention"
        loading={actions.loading}
        error={actions.error ? `Unable to load action queue. ${actions.error}` : null}
        onRetry={actions.refetch}
        isEmpty={!actions.loading && !actions.error && actionRows.length === 0}
        height={200}
        headerRight={
          <span style={{ fontSize: '0.7rem', color: 'var(--color-muted)' }}>
            CRITICAL only · top {Math.min(actionRows.length, 8)}
          </span>
        }
      >
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Priority</th>
                <th>Branch</th>
                <th>Medicine</th>
                <th>Action</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {actionRows.map((row, i) => (
                <tr key={row.medicine_id + row.branch_id + i}>
                  <td><PriorityBadge level={row.priority} /></td>
                  <td>{row.branch_name ?? row.branch_id}</td>
                  <td style={{ fontWeight: 500 }}>
                    <span title={row.medicine_name}>
                      {row.medicine_name?.length > 28
                        ? row.medicine_name.slice(0, 26) + '…'
                        : row.medicine_name ?? row.medicine_id}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontSize: '0.72rem', color: 'var(--color-warning)', fontWeight: 500 }}>
                      {prettyAction(row.primary_action)}
                    </span>
                  </td>
                  <td>
                    <span
                      className="truncate-text"
                      title={row.reason}
                      style={{ color: 'var(--color-muted)', fontSize: '0.72rem' }}
                    >
                      {row.reason}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartCard>

    </div>
  );
}
