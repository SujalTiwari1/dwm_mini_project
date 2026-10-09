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
  fetchActionQueue,
  fetchReorder,
  fetchStockoutRisk,
  fetchOverstock,
  fetchExpiry,
  fetchDashboardSummary,
} from '../api/client';
import { fmtINR, fmtNum, fmtDate, fmtPct } from '../utils/format';

// ── Colours (same palette as Risk page) ───────────────────
const C_DANGER  = '#ef4444';
const C_WARNING = '#f59e0b';
const C_INFO    = '#38bdf8';
const C_SUCCESS = '#22c55e';
const C_ACCENT  = '#6366f1';

const PRIORITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
const PRIORITY_COLOR = { CRITICAL: C_DANGER, HIGH: C_WARNING, MEDIUM: C_INFO, LOW: C_SUCCESS };
const PRIORITY_RANK = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };

const PAGE_LIMIT = 1000; // API maximum per request
const PAGE_SIZE = 12;

const tooltipStyle = {
  backgroundColor: '#1a1d27',
  border: '1px solid #2d3147',
  borderRadius: '6px',
  fontSize: '0.75rem',
  color: '#e4e6f0',
};

// ── Helpers ───────────────────────────────────────────────
/** The API caps `limit` at 1000, so page through the report until `total` rows are loaded. */
async function fetchAll(fetchFn, params = {}) {
  const first = await fetchFn({ ...params, limit: PAGE_LIMIT, offset: 0 });
  let rows = first.data ?? [];
  const total = first.total ?? rows.length;
  for (let offset = PAGE_LIMIT; offset < total; offset += PAGE_LIMIT) {
    const next = await fetchFn({ ...params, limit: PAGE_LIMIT, offset });
    rows = rows.concat(next.data ?? []);
  }
  return { data: rows, total };
}

const label = (s) => String(s ?? '').replace(/_/g, ' ');
const num = (v) => (v == null || v === '' ? 0 : Number(v));
const sumBy = (rows, key) => rows.reduce((acc, r) => acc + num(r[key]), 0);

function ActionBadge({ action }) {
  if (!action) return null;
  const norm = String(action).toUpperCase();
  let cls = 'badge-low';
  if (norm.includes('ORDER_NOW') || norm.startsWith('PRIORITIZE_SALE')) cls = 'badge-critical';
  else if (norm.includes('REORDER_SOON') || norm === 'MONITOR_STOCK_CLOSELY') cls = 'badge-high';
  else if (norm.includes('MONITOR') || norm === 'REVIEW_OVERSTOCK') cls = 'badge-medium';
  return <span className={`badge ${cls}`}>{label(norm)}</span>;
}

function BranchTag({ id }) {
  return <span style={{ fontWeight: 600, color: '#818cf8', fontSize: '0.75rem' }}>{id}</span>;
}

function MedicineCell({ row }) {
  return (
    <>
      <div style={{ fontWeight: 600 }}>{row.medicine_name}</div>
      <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>
        {row.medicine_id}{row.category ? ` • ${row.category}` : ''}
      </div>
    </>
  );
}

function Reason({ text, width = 320 }) {
  return (
    <span className="truncate-text" title={text} style={{ maxWidth: `${width}px` }}>{text ?? '—'}</span>
  );
}

/** Section card with independent loading / error / empty handling and an optional pager. */
function TableSection({ title, subtitle, query, errorMsg, emptyMsg, rows, headerRight, summary, children, pager }) {
  return (
    <div className="card">
      <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <div className="card-title">{title}</div>
          {subtitle && <div className="card-subtitle">{subtitle}</div>}
        </div>
        {headerRight}
      </div>
      <div className="card-body" style={{ padding: 0 }}>
        {query.loading ? (
          <div style={{ padding: '1.5rem' }}>
            <div className="skeleton" style={{ height: '240px', width: '100%', borderRadius: '4px' }} />
          </div>
        ) : query.error ? (
          <div className="error-state">
            <span className="error-icon">⚠</span>
            <span className="error-msg">{errorMsg}</span>
            <button className="retry-btn" onClick={query.refetch}>Retry</button>
          </div>
        ) : (
          <>
            {summary}
            {rows.length === 0 ? (
              <div className="empty-state">{emptyMsg}</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>{children}</div>
            )}
            {pager}
          </>
        )}
      </div>
    </div>
  );
}

function Pager({ page, setPage, total, noun }) {
  if (total <= PAGE_SIZE) return null;
  const last = Math.ceil(total / PAGE_SIZE) - 1;
  return (
    <div className="table-pagination">
      <span>
        Showing <strong>{page * PAGE_SIZE + 1}</strong>–<strong>{Math.min((page + 1) * PAGE_SIZE, total)}</strong> of{' '}
        <strong>{fmtNum(total)}</strong> {noun}
      </span>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="pagination-btn" disabled={page === 0} onClick={() => setPage(Math.max(0, page - 1))}>Previous</button>
        <button className="pagination-btn" disabled={page >= last} onClick={() => setPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}

function StatStrip({ items }) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.75rem',
      padding: '1rem 1.25rem', borderBottom: '1px solid var(--color-border)',
    }}>
      {items.map((it) => (
        <div key={it.label} style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius)', padding: '0.6rem 0.9rem' }}>
          <div style={{ fontSize: '0.66rem', color: it.color ?? '#8b90a8', fontWeight: 600, textTransform: 'uppercase' }}>{it.label}</div>
          <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#e4e6f0' }}>{it.value}</div>
          {it.note && <div style={{ fontSize: '0.66rem', color: '#8b90a8' }}>{it.note}</div>}
        </div>
      ))}
    </div>
  );
}

function CountTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.45rem 0.7rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>{label(d.name)}</div>
      <div style={{ padding: '0.45rem 0.7rem', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
        <span style={{ color: '#8b90a8' }}>Actions:</span>
        <span style={{ fontWeight: 600 }}>{fmtNum(d.value)} ({d.pct})</span>
      </div>
    </div>
  );
}

const METHOD_STEPS = [
  ['Historical Demand', 'Warehouse sales & inventory'],
  ['Forecast', '7 / 14 / 30-day ML demand'],
  ['Inventory Position', 'Stock, days of cover, batches'],
  ['Risk & Expiry Analysis', 'Stockout, overstock, FEFO'],
  ['Decision Rules', 'Reorder point, thresholds'],
  ['Action Queue', 'Prioritised by severity'],
];

// ─────────────────────────────────────────────────────────────
// Decision Support Page (Phase 7)
// ─────────────────────────────────────────────────────────────
export default function Decisions() {
  // Queue filters
  const [priorityFilter, setPriorityFilter] = useState('ALL');
  const [actionFilter, setActionFilter] = useState('');
  const [branchFilter, setBranchFilter] = useState('');
  const [search, setSearch] = useState('');
  const [queuePage, setQueuePage] = useState(0);
  // Section state
  const [actionableOnly, setActionableOnly] = useState(true);
  const [reorderPage, setReorderPage] = useState(0);
  const [expiryPage, setExpiryPage] = useState(0);
  const [overstockPage, setOverstockPage] = useState(0);
  const [stockoutPage, setStockoutPage] = useState(0);
  const [showMethod, setShowMethod] = useState(false);

  // ── API queries (one per decision endpoint, independent errors) ──
  const queueQ     = useFetch(() => fetchAll(fetchActionQueue), []);
  const reorderQ   = useFetch(() => fetchAll(fetchReorder), []);
  const stockoutQ  = useFetch(() => fetchStockoutRisk({ limit: PAGE_LIMIT }), []);
  const overstockQ = useFetch(() => fetchAll(fetchOverstock), []);
  const expiryQ    = useFetch(() => fetchExpiry({ limit: PAGE_LIMIT }), []);
  const summaryQ   = useFetch(() => fetchDashboardSummary(), []); // only for the decision date

  const queue = useMemo(() => {
    const rows = queueQ.data?.data ?? [];
    // Priority first; sort is stable so backend queue_position order is kept within a priority.
    return [...rows].sort((a, b) => (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9));
  }, [queueQ.data]);

  // ── Queue summaries ───────────────────────────────────────
  const queueStats = useMemo(() => {
    const prio = Object.fromEntries(PRIORITIES.map((p) => [p, 0]));
    const actions = {};
    queue.forEach((r) => {
      if (prio[r.priority] !== undefined) prio[r.priority] += 1;
      actions[r.primary_action] = (actions[r.primary_action] ?? 0) + 1;
    });
    const total = queue.length || 1;
    return {
      prio,
      actions,
      exposure: sumBy(queue, 'potential_stockout_exposure_value') + sumBy(queue, 'projected_expiry_exposure_value'),
      priorityData: PRIORITIES.map((p) => ({ name: p, value: prio[p], fill: PRIORITY_COLOR[p], pct: fmtPct((prio[p] / total) * 100) })),
      actionData: Object.entries(actions)
        .sort((a, b) => b[1] - a[1])
        .map(([name, value]) => ({ name, value, pct: fmtPct((value / total) * 100) })),
    };
  }, [queue]);

  const branches = useMemo(() => [...new Set(queue.map((r) => r.branch_id))].sort(), [queue]);
  const actionTypes = useMemo(() => Object.keys(queueStats.actions).sort(), [queueStats]);

  const filteredQueue = useMemo(() => {
    const q = search.trim().toLowerCase();
    return queue.filter((r) => {
      if (priorityFilter !== 'ALL' && r.priority !== priorityFilter) return false;
      if (actionFilter && r.primary_action !== actionFilter) return false;
      if (branchFilter && r.branch_id !== branchFilter) return false;
      if (q) {
        const hay = [r.medicine_name, r.medicine_id, r.branch_id, r.category, r.primary_action, r.primary_reason]
          .join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [queue, priorityFilter, actionFilter, branchFilter, search]);

  const page = (rows, p) => rows.slice(p * PAGE_SIZE, (p + 1) * PAGE_SIZE);
  const pagedQueue = page(filteredQueue, queuePage);
  const topActions = queue.slice(0, 6);
  const resetPage = (setter) => (v) => { setter(v); setQueuePage(0); };

  // ── Reorder ───────────────────────────────────────────────
  const reorderRows = useMemo(() => reorderQ.data?.data ?? [], [reorderQ.data]);
  const reorderCounts = useMemo(() => {
    const c = {};
    reorderRows.forEach((r) => { c[r.recommendation] = (c[r.recommendation] ?? 0) + 1; });
    return c;
  }, [reorderRows]);
  const reorderShown = useMemo(
    () => (actionableOnly ? reorderRows.filter((r) => r.recommendation === 'ORDER_NOW' || r.recommendation === 'REORDER_SOON') : reorderRows),
    [reorderRows, actionableOnly],
  );

  // ── Stockout / overstock / expiry subsets (API order retained) ──
  const stockoutRows = useMemo(
    () => (stockoutQ.data?.data ?? []).filter((r) => r.risk_level === 'CRITICAL' || r.risk_level === 'HIGH'),
    [stockoutQ.data],
  );
  const stockoutCounts = useMemo(() => {
    const c = {};
    (stockoutQ.data?.data ?? []).forEach((r) => { c[r.risk_level] = (c[r.risk_level] ?? 0) + 1; });
    return c;
  }, [stockoutQ.data]);
  const overstockRows = useMemo(() => overstockQ.data?.data ?? [], [overstockQ.data]);
  const expiryRows = useMemo(
    () => (expiryQ.data?.data ?? []).filter((r) => r.recommended_action && r.recommended_action !== 'NO_ACTION' && r.risk_level !== 'LOW'),
    [expiryQ.data],
  );
  const expiryPrioritySale = expiryRows.filter((r) => r.recommended_action === 'PRIORITIZE_SALE');

  const decisionDate = summaryQ.data?.data?.decision_date;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* ── Header ─────────────────────────────────────────── */}
      <div className="page-header" style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 className="page-title">Decision Support</h1>
          <p className="page-subtitle">
            Recommended actions derived from demand forecasts, inventory risk, expiry exposure, and operational analytics.
          </p>
        </div>
        <span className="header-badge" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: C_ACCENT }} />
          Decision Engine · Forecast + Risk + Inventory
        </span>
      </div>

      {/* ── Context banner ─────────────────────────────────── */}
      <div style={{
        background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99, 102, 241, 0.25)',
        borderRadius: 'var(--radius)', padding: '0.65rem 1rem', fontSize: '0.75rem', color: '#c7d2fe',
        display: 'flex', flexDirection: 'column', gap: '0.25rem',
      }}>
        <div>
          <strong>Recommended operational actions</strong> based on the current decision date
          {decisionDate ? <> (<strong>{fmtDate(decisionDate)}</strong>)</> : null} and available historical demand/inventory data.
        </div>
        <div style={{ color: '#a5b4fc' }}>
          Recommendations are analytical estimates to support inventory planning. Exposure values represent potential impact, not realized financial losses or accounting outcomes.
        </div>
      </div>

      {/* ── KPI row ────────────────────────────────────────── */}
      <div className="kpi-grid">
        <KpiCard label="Priority Actions" accent="blue" loading={queueQ.loading}
          value={queueQ.error ? '—' : fmtNum(queueQ.data?.total)} note="Branch–medicine pairs in the action queue" />
        <KpiCard label="Critical Actions" accent="red" loading={queueQ.loading}
          value={queueQ.error ? '—' : fmtNum(queueStats.prio.CRITICAL)} note={`${fmtNum(queueStats.prio.HIGH)} more rated High`} />
        <KpiCard label="Order Now" accent="red" loading={reorderQ.loading}
          value={reorderQ.error ? '—' : fmtNum(reorderCounts.ORDER_NOW ?? 0)} note="Stock ≤ lead-time demand" />
        <KpiCard label="Reorder Soon" accent="amber" loading={reorderQ.loading}
          value={reorderQ.error ? '—' : fmtNum(reorderCounts.REORDER_SOON ?? 0)} note="Stock below reorder point" />
        <KpiCard label="Potential Exposure" accent="purple" loading={queueQ.loading}
          value={queueQ.error ? '—' : fmtINR(queueStats.exposure)} note="Stockout + expiry exposure in queue (estimate)" />
      </div>

      {/* ── Most urgent actions ────────────────────────────── */}
      <div>
        <div style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: '0.6rem' }}>Most Urgent Actions</div>
        {queueQ.loading ? (
          <div className="summary-grid">
            {[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: '150px', borderRadius: 'var(--radius)' }} />)}
          </div>
        ) : queueQ.error ? (
          <div className="card"><div className="error-state">
            <span className="error-icon">⚠</span><span className="error-msg">Unable to load the action queue.</span>
            <button className="retry-btn" onClick={queueQ.refetch}>Retry</button>
          </div></div>
        ) : topActions.length === 0 ? (
          <div className="card"><div className="empty-state">No actions are currently queued.</div></div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(270px, 1fr))', gap: '0.75rem' }}>
            {topActions.map((a) => (
              <div key={`${a.branch_id}-${a.medicine_id}`} className="summary-stat-card"
                style={{ borderLeft: `3px solid ${PRIORITY_COLOR[a.priority] ?? C_ACCENT}`, gap: '0.35rem' }}>
                <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <PriorityBadge level={a.priority} />
                  <ActionBadge action={a.primary_action} />
                  <span style={{ marginLeft: 'auto', fontSize: '0.68rem', color: '#8b90a8' }}>#{a.queue_position}</span>
                </div>
                <div className="summary-stat-title" title={a.medicine_name}>{a.medicine_name}</div>
                <div className="summary-stat-sub"><BranchTag id={a.branch_id} /> • {a.category}</div>
                <div style={{ fontSize: '1.15rem', fontWeight: 700, color: PRIORITY_COLOR[a.priority] }}>
                  {num(a.days_of_cover).toFixed(1)} days cover
                </div>
                <div className="summary-stat-sub">
                  {fmtNum(a.current_inventory_units)} units in stock • 7-day forecast {num(a.forecast_7d).toFixed(1)}
                </div>
                {num(a.recommended_order_quantity) > 0 && (
                  <div style={{ fontSize: '0.78rem', fontWeight: 600 }}>Suggested order: {fmtNum(a.recommended_order_quantity)} units</div>
                )}
                {num(a.impact_value) > 0 && (
                  <div className="summary-stat-sub">Est. exposure: <strong style={{ color: '#fbbf24' }}>{fmtINR(a.impact_value)}</strong></div>
                )}
                <div className="summary-stat-sub" title={a.primary_reason}
                  style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                  {a.primary_reason}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Distribution charts ────────────────────────────── */}
      <div className="chart-grid">
        <ChartCard title="Action Priority Distribution" subtitle="How urgent is the current decision queue?"
          loading={queueQ.loading} error={queueQ.error ? 'Unable to load the action queue.' : null} onRetry={queueQ.refetch}
          isEmpty={!queue.length} height={240}>
          <div style={{ display: 'flex', alignItems: 'center', height: '240px', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 180px', height: '100%', minWidth: '180px' }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={queueStats.priorityData} cx="50%" cy="50%" innerRadius={50} outerRadius={85} paddingAngle={3} dataKey="value">
                    {queueStats.priorityData.map((e) => <Cell key={e.name} fill={e.fill} />)}
                  </Pie>
                  <Tooltip content={<CountTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', minWidth: '160px', paddingRight: '0.5rem' }}>
              {queueStats.priorityData.map((item) => (
                <div key={item.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', gap: '0.75rem' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 500 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: item.fill }} />{item.name}
                  </span>
                  <span style={{ color: '#8b90a8' }}>
                    <strong style={{ color: '#e4e6f0' }}>{fmtNum(item.value)}</strong> ({item.pct})
                  </span>
                </div>
              ))}
            </div>
          </div>
        </ChartCard>

        <ChartCard title="Action Type Distribution" subtitle="What kind of work does the queue require?"
          loading={queueQ.loading} error={queueQ.error ? 'Unable to load the action queue.' : null} onRetry={queueQ.refetch}
          isEmpty={!queueStats.actionData.length} height={240}>
          <div style={{ width: '100%', height: '240px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={queueStats.actionData} layout="vertical" margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                <YAxis type="category" dataKey="name" width={170} tickFormatter={label}
                  tick={{ fill: '#8b90a8', fontSize: 10 }} axisLine={{ stroke: '#2d3147' }} />
                <Tooltip content={<CountTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                <Bar dataKey="value" fill={C_ACCENT} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </div>

      {/* ── Recommended Actions (action queue) ─────────────── */}
      <TableSection
        title="Recommended Actions"
        subtitle="Full prioritised action queue — one row per branch × medicine"
        query={queueQ}
        errorMsg="Unable to load the action queue."
        emptyMsg="No actions match the selected filters."
        rows={filteredQueue}
        headerRight={
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <div className="btn-toggle-group">
              {['ALL', ...PRIORITIES].map((p) => (
                <button key={p} className={`btn-toggle ${priorityFilter === p ? 'active' : ''}`}
                  onClick={() => resetPage(setPriorityFilter)(p)}>{p}</button>
              ))}
            </div>
            <select className="filter-select" value={actionFilter} onChange={(e) => resetPage(setActionFilter)(e.target.value)}>
              <option value="">All Actions</option>
              {actionTypes.map((a) => <option key={a} value={a}>{label(a)}</option>)}
            </select>
            <select className="filter-select" value={branchFilter} onChange={(e) => resetPage(setBranchFilter)(e.target.value)}>
              <option value="">All Branches</option>
              {branches.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
            <input type="text" className="filter-input" placeholder="Search medicine, branch, reason..."
              value={search} onChange={(e) => resetPage(setSearch)(e.target.value)} style={{ width: '200px' }} />
          </div>
        }
        pager={<Pager page={queuePage} setPage={setQueuePage} total={filteredQueue.length} noun="actions" />}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>#</th><th>Priority</th><th>Action</th><th>Branch</th><th>Medicine</th>
              <th>Stock</th><th>Days Cover</th><th>7D Forecast</th><th>Suggested Order</th><th>Exposure</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {pagedQueue.map((r) => (
              <tr key={`${r.branch_id}-${r.medicine_id}`}>
                <td style={{ fontWeight: 700, color: '#818cf8' }}>{r.queue_position}</td>
                <td><PriorityBadge level={r.priority} /></td>
                <td><ActionBadge action={r.primary_action} /></td>
                <td><BranchTag id={r.branch_id} /></td>
                <td><MedicineCell row={r} /></td>
                <td>{fmtNum(r.current_inventory_units)}</td>
                <td style={{ fontWeight: 600, color: num(r.days_of_cover) <= 3 ? C_DANGER : num(r.days_of_cover) <= 7 ? C_WARNING : '#e4e6f0' }}>
                  {num(r.days_of_cover).toFixed(1)}
                </td>
                <td>{num(r.forecast_7d).toFixed(1)}</td>
                <td style={{ fontWeight: 600 }}>{num(r.recommended_order_quantity) > 0 ? `${fmtNum(r.recommended_order_quantity)} units` : '—'}</td>
                <td style={{ fontWeight: 600, color: num(r.impact_value) > 0 ? '#fbbf24' : '#8b90a8' }}>
                  {num(r.impact_value) > 0 ? fmtINR(r.impact_value) : '—'}
                </td>
                <td><Reason text={r.primary_reason} width={300} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableSection>

      {/* ── Reorder decisions ──────────────────────────────── */}
      <TableSection
        title="Reorder Decisions"
        subtitle="What should we purchase? Reorder point, safety stock and suggested quantity under documented planning assumptions"
        query={reorderQ}
        errorMsg="Unable to load reorder recommendations."
        emptyMsg="No reorder recommendations to show."
        rows={reorderShown}
        headerRight={
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', color: '#a0a5bd', cursor: 'pointer' }}>
            <input type="checkbox" checked={actionableOnly} onChange={(e) => { setActionableOnly(e.target.checked); setReorderPage(0); }} />
            Show actionable only
          </label>
        }
        summary={
          <StatStrip items={[
            { label: 'Order Now', value: fmtNum(reorderCounts.ORDER_NOW ?? 0), color: '#f87171' },
            { label: 'Reorder Soon', value: fmtNum(reorderCounts.REORDER_SOON ?? 0), color: '#fbbf24' },
            { label: 'No Reorder', value: fmtNum(reorderCounts.NO_REORDER ?? 0), color: '#86efac' },
            { label: 'Units to Order', value: fmtNum(sumBy(reorderRows, 'recommended_order_quantity')), note: 'Sum of recommended quantities' },
          ]} />
        }
        pager={<Pager page={reorderPage} setPage={setReorderPage} total={reorderShown.length} noun="recommendations" />}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Priority</th><th>Recommendation</th><th>Branch</th><th>Medicine</th><th>Stock</th>
              <th>Daily Demand</th><th>7D Forecast</th><th>Reorder Point</th><th>Order Qty</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {page(reorderShown, reorderPage).map((r) => (
              <tr key={`${r.branch_id}-${r.medicine_id}`}>
                <td><PriorityBadge level={r.priority} /></td>
                <td><ActionBadge action={r.recommendation} /></td>
                <td><BranchTag id={r.branch_id} /></td>
                <td><MedicineCell row={r} /></td>
                <td>{fmtNum(r.current_inventory_units)}</td>
                <td>{num(r.expected_daily_demand).toFixed(2)}/d</td>
                <td>{num(r.forecast_7d).toFixed(1)}</td>
                <td>{num(r.reorder_point).toFixed(1)}</td>
                <td style={{ fontWeight: 700 }}>{num(r.recommended_order_quantity) > 0 ? `${fmtNum(r.recommended_order_quantity)} units` : '—'}</td>
                <td><Reason text={r.reason} width={280} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableSection>

      {/* ── Expiry actions ─────────────────────────────────── */}
      <TableSection
        title="Expiry Actions"
        subtitle="Which stock should we prioritise selling before it expires? Lots are assessed in FEFO order — earlier-expiring stock sells first"
        query={expiryQ}
        errorMsg="Unable to load expiry actions."
        emptyMsg="No expiry actions are currently required."
        rows={expiryRows}
        summary={
          <StatStrip items={[
            { label: 'Prioritize Sale', value: fmtNum(expiryPrioritySale.length), color: '#f87171', note: 'Lots to move first' },
            { label: 'Monitor', value: fmtNum(expiryRows.length - expiryPrioritySale.length), color: '#7dd3fc' },
            { label: 'Projected Unsold Value', value: fmtINR(sumBy(expiryRows, 'projected_unsold_value')), note: 'Estimated exposure, not a loss' },
          ]} />
        }
        pager={<Pager page={expiryPage} setPage={setExpiryPage} total={expiryRows.length} noun="lots" />}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Risk</th><th>Action</th><th>Branch</th><th>Medicine</th><th>Batch</th><th>Qty</th>
              <th>Days to Expiry</th><th>Unsold (proj.)</th><th>Value</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {page(expiryRows, expiryPage).map((r) => (
              <tr key={`${r.branch_id}-${r.batch_id}`}>
                <td><PriorityBadge level={r.risk_level} /></td>
                <td><ActionBadge action={r.recommended_action} /></td>
                <td><BranchTag id={r.branch_id} /></td>
                <td><MedicineCell row={r} /></td>
                <td><code style={{ fontSize: '0.72rem', color: '#93c5fd' }}>{r.batch_id}</code></td>
                <td>{fmtNum(r.batch_quantity)}</td>
                <td>
                  <div style={{ fontWeight: 700, color: num(r.days_to_expiry) <= 15 ? C_DANGER : num(r.days_to_expiry) <= 30 ? C_WARNING : '#e4e6f0' }}>
                    {r.days_to_expiry} days
                  </div>
                  <div style={{ fontSize: '0.65rem', color: '#8b90a8' }}>{fmtDate(r.expiry_date)}</div>
                </td>
                <td>{num(r.projected_unsold_units).toFixed(1)}</td>
                <td style={{ fontWeight: 700, color: '#fbbf24' }}>{fmtINR(r.projected_unsold_value)}</td>
                <td><Reason text={r.reason} width={300} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableSection>

      {/* ── Stockout + overstock ───────────────────────────── */}
      <TableSection
        title="Stockout Prevention"
        subtitle="Critical and high stockout risks — which products are most likely to become unavailable?"
        query={stockoutQ}
        errorMsg="Unable to load stockout risk."
        emptyMsg="No critical or high stockout risks."
        rows={stockoutRows}
        summary={
          <StatStrip items={[
            { label: 'Critical', value: fmtNum(stockoutCounts.CRITICAL ?? 0), color: '#f87171' },
            { label: 'High', value: fmtNum(stockoutCounts.HIGH ?? 0), color: '#fbbf24' },
          ]} />
        }
        pager={<Pager page={stockoutPage} setPage={setStockoutPage} total={stockoutRows.length} noun="pairs" />}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Severity</th><th>Branch</th><th>Medicine</th><th>Stock</th><th>Daily Demand</th>
              <th>Days Cover</th><th>7D Forecast</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {page(stockoutRows, stockoutPage).map((r) => (
              <tr key={`${r.branch_id}-${r.medicine_id}`}>
                <td><PriorityBadge level={r.risk_level} /></td>
                <td><BranchTag id={r.branch_id} /></td>
                <td><MedicineCell row={r} /></td>
                <td style={{ fontWeight: 700, color: num(r.current_inventory_units) === 0 ? C_DANGER : '#e4e6f0' }}>
                  {fmtNum(r.current_inventory_units)}
                </td>
                <td>{num(r.expected_daily_demand).toFixed(2)}/d</td>
                <td style={{ fontWeight: 600, color: num(r.days_of_cover) <= 3 ? C_DANGER : C_WARNING }}>{num(r.days_of_cover).toFixed(1)}</td>
                <td>{num(r.forecast_7d).toFixed(1)}</td>
                <td><Reason text={r.primary_reason} width={320} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableSection>

      <TableSection
        title="Overstock Review"
        subtitle="Branch–medicine pairs above 90 days of cover, in the report's own order (highest excess value first)"
        query={overstockQ}
        errorMsg="Unable to load overstock data."
        emptyMsg="No overstocked branch–medicine pairs."
        rows={overstockRows}
        summary={
          <StatStrip items={[
            { label: 'Overstocked Pairs', value: fmtNum(overstockQ.data?.total ?? 0), color: '#7dd3fc' },
            { label: 'Estimated Excess Units', value: fmtNum(sumBy(overstockRows, 'excess_units_estimate')) },
            { label: 'Estimated Excess Value', value: fmtINR(sumBy(overstockRows, 'excess_value_estimate')), note: 'Cost value, not a loss' },
          ]} />
        }
        pager={<Pager page={overstockPage} setPage={setOverstockPage} total={overstockRows.length} noun="pairs" />}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Branch</th><th>Medicine</th><th>Stock</th><th>Stock Value</th><th>Daily Demand</th>
              <th>Days Cover</th><th>Excess Units</th><th>Excess Value</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {page(overstockRows, overstockPage).map((r) => (
              <tr key={`${r.branch_id}-${r.medicine_id}`}>
                <td><BranchTag id={r.branch_id} /></td>
                <td><MedicineCell row={r} /></td>
                <td>{fmtNum(r.current_inventory_units)}</td>
                <td>{fmtINR(r.current_inventory_value)}</td>
                <td>{num(r.expected_daily_demand).toFixed(2)}/d</td>
                <td>{num(r.days_of_cover).toFixed(0)}</td>
                <td>{fmtNum(r.excess_units_estimate)}</td>
                <td style={{ fontWeight: 700, color: '#7dd3fc' }}>{fmtINR(r.excess_value_estimate)}</td>
                <td><Reason text={r.reason} width={300} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableSection>

      {/* ── Decision flow ──────────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">From Data to Decision</div>
            <div className="card-subtitle">Data Warehouse → OLAP → Mining → ML → Decision Support</div>
          </div>
        </div>
        <div className="card-body" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'stretch', gap: '0.5rem' }}>
          {METHOD_STEPS.map(([title, sub], i) => (
            <div key={title} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: '1 1 140px' }}>
              <div style={{
                flex: 1, background: 'var(--color-surface-2)', border: '1px solid var(--color-border)',
                borderTop: `2px solid ${i === METHOD_STEPS.length - 1 ? C_ACCENT : '#2d3147'}`,
                borderRadius: 'var(--radius)', padding: '0.6rem 0.8rem', height: '100%',
              }}>
                <div style={{ fontSize: '0.78rem', fontWeight: 600 }}>{title}</div>
                <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>{sub}</div>
              </div>
              {i < METHOD_STEPS.length - 1 && <span style={{ color: '#8b90a8' }}>→</span>}
            </div>
          ))}
        </div>
      </div>

      {/* ── Methodology & assumptions ──────────────────────── */}
      <div className="card" style={{ background: '#141722', borderColor: '#2d3147' }}>
        <div className="card-header" style={{ cursor: 'pointer' }} onClick={() => setShowMethod((s) => !s)}>
          <div className="card-title">Methodology & Assumptions</div>
          <button className="pagination-btn" onClick={(e) => { e.stopPropagation(); setShowMethod((s) => !s); }}>
            {showMethod ? 'Hide' : 'Show'}
          </button>
        </div>
        {showMethod && (
          <div className="card-body" style={{ fontSize: '0.78rem', color: '#a0a5bd', lineHeight: 1.6 }}>
            <ul style={{ paddingLeft: '1.1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <li>Decision date: {decisionDate ? fmtDate(decisionDate) : '—'} (from the decision-support run).</li>
              <li>Supplier lead time 7 days; service level 95% (z = 1.645); each order covers 14 days of demand beyond the lead time.</li>
              <li>Reorder point = lead-time demand + safety stock. ORDER_NOW: stock ≤ lead-time demand. REORDER_SOON: stock below the reorder point.</li>
              <li>Demand combines recent sales with the 7/14/30-day ML forecast; stockout escalates after repeated stockout days in the last 28 days.</li>
              <li>Overstock: stock above 90 days of cover (or no sales in 30 days); excess valued at average unit cost.</li>
              <li>Expiry risk: recent 90-day demand projected to each batch’s expiry date, earlier-expiring lots selling first (FEFO).</li>
              <li>No minimum order quantities, pack sizes or supplier limits; open orders assumed to be zero.</li>
              <li>The dataset is synthetic; exposure figures are estimates of potential impact, not realized losses.</li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
