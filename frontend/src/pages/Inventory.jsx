import { useState, useMemo } from 'react';
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import PriorityBadge from '../components/PriorityBadge';
import { useFetch } from '../hooks/useFetch';
import {
  fetchInventory,
  fetchStockoutRisk,
  fetchOverstock,
  fetchReorder,
} from '../api/client';
import { fmtINR, fmtINR_SI, fmtNum, fmtUnits, fmtDate, fmtPct } from '../utils/format';

// ── Chart colours ─────────────────────────────────────────
const C_DANGER   = '#ef4444';
const C_WARNING  = '#f59e0b';
const C_SUCCESS  = '#22c55e';
const C_INFO     = '#38bdf8';
const C_ACCENT   = '#6366f1';

const STATUS_COLOURS = {
  'OUT OF STOCK': C_DANGER,
  'LOW STOCK':    C_WARNING,
  'NORMAL':       C_SUCCESS,
  'OVERSTOCK':    C_INFO,
};

// ── Recharts tooltip style ─────────────────────────────────
const tooltipStyle = {
  backgroundColor: '#1a1d27',
  border: '1px solid #2d3147',
  borderRadius: '6px',
  fontSize: '0.75rem',
  color: '#e4e6f0',
};

// ── Donut tooltip ──────────────────────────────────────────
function StatusTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0];
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.4rem 0.65rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>
        {d.name}
      </div>
      <div style={{ padding: '0.4rem 0.65rem', display: 'flex', gap: '1rem', justifyContent: 'space-between' }}>
        <span style={{ color: d.payload?.fill }}>{fmtNum(d.value)} pairs</span>
        <span style={{ color: '#8b90a8' }}>{d.payload?.pct}</span>
      </div>
    </div>
  );
}

// ── Helper to format recommendation badges ────────────────
function RecommendationBadge({ recommendation }) {
  const norm = (recommendation ?? '').toUpperCase();
  if (norm === 'ORDER_NOW') {
    return <span className="badge badge-reorder-now">ORDER NOW</span>;
  }
  if (norm === 'REORDER_SOON') {
    return <span className="badge badge-reorder-soon">REORDER SOON</span>;
  }
  return <span className="badge badge-reorder-none">NO REORDER</span>;
}

// ── Helper to format stock status badges ───────────────────
function StockStatusBadge({ status }) {
  const norm = (status ?? '').toUpperCase();
  if (norm === 'OUT OF STOCK') {
    return <span className="badge badge-status-out-of-stock">OUT OF STOCK</span>;
  }
  if (norm === 'LOW STOCK') {
    return <span className="badge badge-status-low-stock">LOW STOCK</span>;
  }
  if (norm === 'OVERSTOCK') {
    return <span className="badge badge-status-overstock">OVERSTOCK</span>;
  }
  return <span className="badge badge-status-normal">NORMAL</span>;
}

// ─────────────────────────────────────────────────────────────
// Inventory Intelligence Page
// ─────────────────────────────────────────────────────────────
export default function Inventory() {
  // ── Filters & pagination state ────────────────────────────
  const [riskFilter, setRiskFilter]         = useState('');
  const [reorderFilter, setReorderFilter]   = useState('ORDER_NOW');
  const [tableStatus, setTableStatus]       = useState('');
  const [tableBranch, setTableBranch]       = useState('');
  const [page, setPage]                     = useState(0);
  const pageSize = 12;

  // ── Independent API queries ───────────────────────────────
  // 1. Inventory headline & summary
  const invSummaryQuery = useFetch(() => fetchInventory({ limit: 1 }), []);

  // 2. Stockout risk table
  const stockoutQuery = useFetch(
    () => fetchStockoutRisk({
      risk_level: riskFilter || undefined,
      limit: 10,
    }),
    [riskFilter]
  );

  // 3. Overstock risk
  const overstockQuery = useFetch(() => fetchOverstock({ limit: 8 }), []);

  // 4. Reorder recommendations
  const reorderQuery = useFetch(
    () => fetchReorder({
      recommendation: reorderFilter || undefined,
      limit: 8,
    }),
    [reorderFilter]
  );

  // 5. Paginated Inventory Details Explorer
  const explorerQuery = useFetch(
    () => fetchInventory({
      status: tableStatus || undefined,
      branch_id: tableBranch || undefined,
      limit: pageSize,
      offset: page * pageSize,
    }),
    [tableStatus, tableBranch, page]
  );

  // ── Derived: KPI figures ──────────────────────────────────
  const sum = invSummaryQuery.data?.summary;
  const snapshotDate = sum?.snapshot_date;

  // Donut chart status data
  const statusChartData = useMemo(() => {
    if (!sum) return [];
    const totalPairs = sum.pairs || 1;
    return [
      { name: 'OUT OF STOCK', value: Number(sum.out_of_stock) || 0, fill: C_DANGER,  pct: fmtPct((sum.out_of_stock / totalPairs) * 100) },
      { name: 'LOW STOCK',    value: Number(sum.low_stock)    || 0, fill: C_WARNING, pct: fmtPct((sum.low_stock / totalPairs) * 100) },
      { name: 'NORMAL',       value: Number(sum.normal)       || 0, fill: C_SUCCESS, pct: fmtPct((sum.normal / totalPairs) * 100) },
      { name: 'OVERSTOCK',    value: Number(sum.overstock)    || 0, fill: C_INFO,    pct: fmtPct((sum.overstock / totalPairs) * 100) },
    ].filter((d) => d.value > 0);
  }, [sum]);

  // Days of cover distribution buckets
  const coverBuckets = useMemo(() => {
    if (!sum) return [];
    return [
      { range: '0 days',    label: 'Stockout', count: sum.out_of_stock ?? 0, fill: C_DANGER },
      { range: '1–7 days',  label: 'Critical', count: sum.low_stock ?? 0,    fill: C_WARNING },
      { range: '8–30 days', label: 'Balanced', count: sum.normal ?? 0,       fill: C_SUCCESS },
      { range: '30+ days',  label: 'Surplus',  count: sum.overstock ?? 0,    fill: C_INFO },
    ];
  }, [sum]);

  // Insights
  const insights = useMemo(() => {
    const topRisk = stockoutQuery.data?.data?.[0];
    const topOver = overstockQuery.data?.data?.[0];
    const topReorder = reorderQuery.data?.data?.[0];
    return {
      topRisk: topRisk ? {
        medicine: topRisk.medicine_name,
        branch: topRisk.branch_id,
        level: topRisk.risk_level,
        stock: topRisk.current_inventory_units,
      } : null,
      topOver: topOver ? {
        medicine: topOver.medicine_name,
        branch: topOver.branch_id,
        excessVal: topOver.excess_value_estimate,
        cover: topOver.days_of_cover,
      } : null,
      topReorder: topReorder ? {
        medicine: topReorder.medicine_name,
        branch: topReorder.branch_id,
        qty: topReorder.recommended_order_quantity,
        rec: topReorder.recommendation,
      } : null,
    };
  }, [stockoutQuery.data, overstockQuery.data, reorderQuery.data]);

  // Explorer total pages
  const totalExplorerRows = explorerQuery.data?.total ?? 0;
  const totalPages = Math.ceil(totalExplorerRows / pageSize);

  const handleStatusChange = (val) => {
    setTableStatus(val);
    setPage(0);
  };

  const handleBranchChange = (val) => {
    setTableBranch(val);
    setPage(0);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* ── Page Header ───────────────────────────────── */}
      <div className="page-header">
        <div className="page-title">Inventory Intelligence</div>
        <div className="page-subtitle">
          Current stock levels, inventory risk and replenishment priorities
          {snapshotDate && ` · Snapshot Date: ${fmtDate(snapshotDate)}`}
        </div>
      </div>

      {/* ── Insights / Summary Cards ──────────────────── */}
      <div className="summary-grid">
        <div className="summary-stat-card">
          <span className="summary-stat-label">Highest Stockout Risk</span>
          <div className="summary-stat-title" title={insights.topRisk?.medicine}>
            {insights.topRisk?.medicine ?? '—'}
          </div>
          <div className="summary-stat-sub">
            {insights.topRisk
              ? `${insights.topRisk.branch} · ${insights.topRisk.stock} units (${insights.topRisk.level})`
              : 'Zero-stock SKU with demand'}
          </div>
        </div>

        <div className="summary-stat-card">
          <span className="summary-stat-label">Largest Overstock Exposure</span>
          <div className="summary-stat-title" title={insights.topOver?.medicine}>
            {insights.topOver?.medicine ?? '—'}
          </div>
          <div className="summary-stat-sub">
            {insights.topOver
              ? `${insights.topOver.branch} · ${fmtINR(insights.topOver.excessVal)} excess (${Math.round(insights.topOver.cover)}d cover)`
              : 'Holding excess capital'}
          </div>
        </div>

        <div className="summary-stat-card">
          <span className="summary-stat-label">Top Reorder Action</span>
          <div className="summary-stat-title" title={insights.topReorder?.medicine}>
            {insights.topReorder?.medicine ?? '—'}
          </div>
          <div className="summary-stat-sub">
            {insights.topReorder
              ? `${insights.topReorder.branch} · Order ${fmtUnits(insights.topReorder.qty)} units`
              : 'Immediate replenishment SKU'}
          </div>
        </div>

        <div className="summary-stat-card">
          <span className="summary-stat-label">Inventory Health Index</span>
          <div className="summary-stat-title">
            {sum ? `${fmtPct((sum.normal / (sum.pairs || 1)) * 100)} Normal` : '—'}
          </div>
          <div className="summary-stat-sub">
            {sum ? `${fmtNum(sum.pairs)} branch-medicine combinations` : 'Active SKU network'}
          </div>
        </div>
      </div>

      {/* ── KPI Row: 5 Cards ──────────────────────────── */}
      <section>
        <div style={{
          fontSize: '0.7rem',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--color-muted)',
          fontWeight: 600,
          marginBottom: '0.6rem',
        }}>
          Current Inventory Overview
        </div>
        <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))' }}>
          <KpiCard
            label="Current Inventory"
            value={fmtUnits(sum?.total_units)}
            note="Units on hand (latest)"
            accent="blue"
            loading={invSummaryQuery.loading}
          />
          <KpiCard
            label="Inventory Value"
            value={fmtINR_SI(sum?.total_value_at_cost)}
            note="At cost across all branches"
            accent="purple"
            loading={invSummaryQuery.loading}
          />
          <KpiCard
            label="Out of Stock"
            value={fmtNum(sum?.out_of_stock)}
            note="SKU pairs with 0 units"
            accent="red"
            loading={invSummaryQuery.loading}
          />
          <KpiCard
            label="Low Stock"
            value={fmtNum(sum?.low_stock)}
            note="Under safety threshold"
            accent="amber"
            loading={invSummaryQuery.loading}
          />
          <KpiCard
            label="Overstock"
            value={fmtNum(sum?.overstock)}
            note=">90 days of cover"
            accent="blue"
            loading={invSummaryQuery.loading}
          />
        </div>
      </section>

      {/* ── Status Visualization: Donut & Days of Cover ── */}
      <div className="chart-grid">
        {/* Status Distribution Donut Chart */}
        <ChartCard
          title="Inventory Status Distribution"
          subtitle="Breakdown of branch-medicine SKU pairs"
          loading={invSummaryQuery.loading}
          error={invSummaryQuery.error}
          onRetry={invSummaryQuery.refetch}
          isEmpty={statusChartData.length === 0}
          height={260}
        >
          <div style={{ display: 'flex', alignItems: 'center', height: '260px' }}>
            <div style={{ flex: 1, height: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={statusChartData}
                    cx="50%"
                    cy="50%"
                    innerRadius={65}
                    outerRadius={95}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {statusChartData.map((entry) => (
                      <Cell key={entry.name} fill={entry.fill} stroke="transparent" />
                    ))}
                  </Pie>
                  <Tooltip content={<StatusTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div style={{ width: '150px', display: 'flex', flexDirection: 'column', gap: '0.6rem', paddingRight: '0.5rem' }}>
              {statusChartData.map((d) => (
                <div key={d.name} style={{ display: 'flex', flexDirection: 'column', gap: '0.1rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.72rem', color: '#e4e6f0' }}>
                    <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: d.fill }} />
                    <span style={{ fontWeight: 600 }}>{d.name}</span>
                  </div>
                  <div style={{ fontSize: '0.7rem', color: '#8b90a8', paddingLeft: '0.9rem' }}>
                    {fmtNum(d.value)} ({d.pct})
                  </div>
                </div>
              ))}
            </div>
          </div>
        </ChartCard>

        {/* Days of Cover Distribution */}
        <ChartCard
          title="Days of Cover Profile"
          subtitle="Stock depth by cover threshold"
          loading={invSummaryQuery.loading}
          error={invSummaryQuery.error}
          onRetry={invSummaryQuery.refetch}
          isEmpty={coverBuckets.length === 0}
          height={260}
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={coverBuckets} margin={{ top: 15, right: 15, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
              <XAxis
                dataKey="range"
                stroke="#8b90a8"
                fontSize={11}
                tickLine={false}
                axisLine={{ stroke: '#2d3147' }}
              />
              <YAxis
                stroke="#8b90a8"
                fontSize={11}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => fmtNum(v)}
                width={45}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const item = payload[0].payload;
                  return (
                    <div style={tooltipStyle}>
                      <div style={{ padding: '0.4rem 0.65rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>
                        {item.range} ({item.label})
                      </div>
                      <div style={{ padding: '0.4rem 0.65rem' }}>
                        Count: <strong>{fmtNum(item.count)}</strong> SKU pairs
                      </div>
                    </div>
                  );
                }}
              />
              <Bar dataKey="count" name="SKUs" radius={[4, 4, 0, 0]}>
                {coverBuckets.map((entry, idx) => (
                  <Cell key={idx} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* ── Section: Stockout Risk Table ────────────────── */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Stockout & Low Stock Risk</div>
            <div className="card-subtitle">
              Prioritized by severity, days of cover and forecast demand
            </div>
          </div>
          <div className="btn-toggle-group">
            {[
              { id: '', label: 'All' },
              { id: 'CRITICAL', label: 'Critical' },
              { id: 'HIGH', label: 'High' },
              { id: 'MEDIUM', label: 'Medium' },
              { id: 'LOW', label: 'Low' },
            ].map((btn) => (
              <button
                key={btn.id}
                type="button"
                className={`btn-toggle ${riskFilter === btn.id ? 'active' : ''}`}
                onClick={() => setRiskFilter(btn.id)}
              >
                {btn.label}
              </button>
            ))}
          </div>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {stockoutQuery.loading ? (
            <div style={{ padding: '1.25rem' }}>
              <div className="skeleton" style={{ height: '220px', width: '100%', borderRadius: '4px' }} />
            </div>
          ) : stockoutQuery.error ? (
            <div className="error-state" style={{ minHeight: '180px' }}>
              <span className="error-icon">⚠</span>
              <span className="error-msg">{stockoutQuery.error}</span>
              <button className="retry-btn" onClick={stockoutQuery.refetch}>Retry</button>
            </div>
          ) : (stockoutQuery.data?.data ?? []).length === 0 ? (
            <div className="empty-state" style={{ minHeight: '140px' }}>
              No items match the selected risk filter.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: '90px' }}>Risk Level</th>
                    <th>Branch</th>
                    <th>Medicine</th>
                    <th style={{ textAlign: 'right' }}>Current Stock</th>
                    <th style={{ textAlign: 'right' }}>Daily Demand</th>
                    <th style={{ textAlign: 'right' }}>Days Cover</th>
                    <th>Primary Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {(stockoutQuery.data?.data ?? []).map((row, idx) => (
                    <tr key={`${row.branch_id}-${row.medicine_id}-${idx}`}>
                      <td>
                        <PriorityBadge priority={row.risk_level} />
                      </td>
                      <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                        {row.branch_id}
                      </td>
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--color-text)' }}>
                          {row.medicine_name}
                        </div>
                        <div style={{ fontSize: '0.68rem', color: 'var(--color-muted)' }}>
                          {row.category ?? row.medicine_id}
                        </div>
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 600, color: row.current_inventory_units === 0 ? 'var(--color-danger)' : 'inherit' }}>
                        {fmtUnits(row.current_inventory_units)}
                      </td>
                      <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                        {Number(row.expected_daily_demand).toFixed(2)}/d
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 600, color: row.days_of_cover < 4 ? 'var(--color-danger)' : 'var(--color-warning)' }}>
                        {Number(row.days_of_cover).toFixed(1)}d
                      </td>
                      <td>
                        <span className="truncate-text" title={row.primary_reason}>
                          {row.primary_reason}
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

      {/* ── Two Columns: Overstock & Reorder ────────────── */}
      <div className="chart-grid">
        {/* Overstock Table */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Overstock Exposure</div>
              <div className="card-subtitle">Highest excess capital exposure (&gt;90d cover)</div>
            </div>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {overstockQuery.loading ? (
              <div style={{ padding: '1rem' }}>
                <div className="skeleton" style={{ height: '220px', width: '100%', borderRadius: '4px' }} />
              </div>
            ) : overstockQuery.error ? (
              <div className="error-state" style={{ minHeight: '180px' }}>
                <span className="error-icon">⚠</span>
                <span className="error-msg">{overstockQuery.error}</span>
                <button className="retry-btn" onClick={overstockQuery.refetch}>Retry</button>
              </div>
            ) : (overstockQuery.data?.data ?? []).length === 0 ? (
              <div className="empty-state" style={{ minHeight: '140px' }}>
                No overstock items detected.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Medicine</th>
                      <th>Branch</th>
                      <th style={{ textAlign: 'right' }}>Stock</th>
                      <th style={{ textAlign: 'right' }}>Days Cover</th>
                      <th style={{ textAlign: 'right' }}>Excess Units</th>
                      <th style={{ textAlign: 'right' }}>Excess Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(overstockQuery.data?.data ?? []).map((row, idx) => (
                      <tr key={`over-${row.branch_id}-${row.medicine_id}-${idx}`}>
                        <td>
                          <div style={{ fontWeight: 600 }}>{row.medicine_name}</div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--color-muted)' }}>{row.category}</div>
                        </td>
                        <td style={{ fontWeight: 600 }}>{row.branch_id}</td>
                        <td style={{ textAlign: 'right' }}>{fmtUnits(row.current_inventory_units)}</td>
                        <td style={{ textAlign: 'right', color: 'var(--color-info)', fontWeight: 600 }}>
                          {Math.round(row.days_of_cover)}d
                        </td>
                        <td style={{ textAlign: 'right' }}>{fmtUnits(row.excess_units_estimate)}</td>
                        <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--color-accent-light)' }}>
                          {fmtINR(row.excess_value_estimate)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Reorder Recommendations */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Reorder Recommendations</div>
              <div className="card-subtitle">Safety-stock replenishment recommendations</div>
            </div>
            <div className="btn-toggle-group">
              <button
                type="button"
                className={`btn-toggle ${reorderFilter === 'ORDER_NOW' ? 'active' : ''}`}
                onClick={() => setReorderFilter('ORDER_NOW')}
              >
                Order Now
              </button>
              <button
                type="button"
                className={`btn-toggle ${reorderFilter === 'REORDER_SOON' ? 'active' : ''}`}
                onClick={() => setReorderFilter('REORDER_SOON')}
              >
                Reorder Soon
              </button>
            </div>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {reorderQuery.loading ? (
              <div style={{ padding: '1rem' }}>
                <div className="skeleton" style={{ height: '220px', width: '100%', borderRadius: '4px' }} />
              </div>
            ) : reorderQuery.error ? (
              <div className="error-state" style={{ minHeight: '180px' }}>
                <span className="error-icon">⚠</span>
                <span className="error-msg">{reorderQuery.error}</span>
                <button className="retry-btn" onClick={reorderQuery.refetch}>Retry</button>
              </div>
            ) : (reorderQuery.data?.data ?? []).length === 0 ? (
              <div className="empty-state" style={{ minHeight: '140px' }}>
                No reorder actions for the selected filter.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Branch</th>
                      <th>Medicine</th>
                      <th style={{ textAlign: 'right' }}>Current Stock</th>
                      <th style={{ textAlign: 'right' }}>Cover</th>
                      <th>Recommendation</th>
                      <th style={{ textAlign: 'right' }}>Suggested Qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(reorderQuery.data?.data ?? []).map((row, idx) => (
                      <tr key={`reord-${row.branch_id}-${row.medicine_id}-${idx}`}>
                        <td style={{ fontWeight: 600 }}>{row.branch_id}</td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{row.medicine_name}</div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--color-muted)' }}>{row.category}</div>
                        </td>
                        <td style={{ textAlign: 'right' }}>{fmtUnits(row.current_inventory_units)}</td>
                        <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                          {row.expected_daily_demand > 0
                            ? `${(row.current_inventory_units / row.expected_daily_demand).toFixed(1)}d`
                            : '—'}
                        </td>
                        <td>
                          <RecommendationBadge recommendation={row.recommendation} />
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 700, color: 'var(--color-accent-light)' }}>
                          +{fmtUnits(row.recommended_order_quantity)}
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

      {/* ── Section: Full Inventory Details Explorer ───── */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div className="card-title">Inventory Explorer</div>
            <div className="card-subtitle">
              Comprehensive stock levels and days of cover across the warehouse
            </div>
          </div>
          {/* Controls: status and branch filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <select
              className="filter-select"
              value={tableStatus}
              onChange={(e) => handleStatusChange(e.target.value)}
            >
              <option value="">All Statuses</option>
              <option value="OUT OF STOCK">Out of Stock</option>
              <option value="LOW STOCK">Low Stock</option>
              <option value="NORMAL">Normal</option>
              <option value="OVERSTOCK">Overstock</option>
            </select>

            <select
              className="filter-select"
              value={tableBranch}
              onChange={(e) => handleBranchChange(e.target.value)}
            >
              <option value="">All Branches</option>
              <option value="BR001">BR001 — Central</option>
              <option value="BR002">BR002 — Metro</option>
              <option value="BR003">BR003 — West</option>
              <option value="BR004">BR004 — Link</option>
              <option value="BR005">BR005 — Harbour</option>
            </select>
          </div>
        </div>

        <div className="card-body" style={{ padding: 0 }}>
          {explorerQuery.loading ? (
            <div style={{ padding: '1.25rem' }}>
              <div className="skeleton" style={{ height: '240px', width: '100%', borderRadius: '4px' }} />
            </div>
          ) : explorerQuery.error ? (
            <div className="error-state" style={{ minHeight: '180px' }}>
              <span className="error-icon">⚠</span>
              <span className="error-msg">{explorerQuery.error}</span>
              <button className="retry-btn" onClick={explorerQuery.refetch}>Retry</button>
            </div>
          ) : (explorerQuery.data?.data ?? []).length === 0 ? (
            <div className="empty-state" style={{ minHeight: '140px' }}>
              No inventory records match the selected filters.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Branch</th>
                    <th>Medicine</th>
                    <th>Category</th>
                    <th style={{ textAlign: 'right' }}>Stock Units</th>
                    <th style={{ textAlign: 'right' }}>Value at Cost</th>
                    <th style={{ textAlign: 'right' }}>30d Demand/Day</th>
                    <th style={{ textAlign: 'right' }}>Days of Cover</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(explorerQuery.data?.data ?? []).map((row, idx) => (
                    <tr key={`exp-${row.branch_id}-${row.medicine_id}-${idx}`}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{row.branch_id}</div>
                        <div style={{ fontSize: '0.68rem', color: 'var(--color-muted)' }}>{row.branch_name}</div>
                      </td>
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--color-text)' }}>{row.medicine_name}</div>
                        <div style={{ fontSize: '0.68rem', color: 'var(--color-muted)' }}>{row.medicine_id}</div>
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
                          {row.category_name}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>
                        {fmtUnits(row.stock_units)}
                      </td>
                      <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                        {fmtINR(row.stock_value_at_cost)}
                      </td>
                      <td style={{ textAlign: 'right', color: 'var(--color-muted)' }}>
                        {row.avg_daily_demand_30d != null ? `${Number(row.avg_daily_demand_30d).toFixed(2)}/d` : '—'}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 600, color: row.days_of_inventory < 4 ? 'var(--color-danger)' : row.days_of_inventory > 90 ? 'var(--color-info)' : 'inherit' }}>
                        {row.days_of_inventory != null ? `${Number(row.days_of_inventory).toFixed(1)}d` : '—'}
                      </td>
                      <td>
                        <StockStatusBadge status={row.stock_status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination Controls */}
          {totalExplorerRows > 0 && (
            <div className="table-pagination">
              <div>
                Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, totalExplorerRows)} of {fmtNum(totalExplorerRows)} records
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <button
                  type="button"
                  className="pagination-btn"
                  disabled={page === 0 || explorerQuery.loading}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <span>Page {page + 1} of {Math.max(1, totalPages)}</span>
                <button
                  type="button"
                  className="pagination-btn"
                  disabled={page >= totalPages - 1 || explorerQuery.loading}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
