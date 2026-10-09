import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, Legend,
} from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import { useFetch } from '../hooks/useFetch';
import { fetchForecasts } from '../api/client';
import { useDataset } from '../context/DatasetContext';
import { fmtNum, fmtDate } from '../utils/format';

const C_ACCENT  = '#6366f1';
const C_DANGER  = '#ef4444';
const C_WARNING = '#f59e0b';
const C_INFO    = '#38bdf8';
const C_PURPLE  = '#a78bfa';
const CAT_COLORS = [C_ACCENT, C_INFO, C_PURPLE, '#22c55e', C_WARNING, '#f472b6', '#2dd4bf', '#fb923c', '#94a3b8', '#facc15'];

const HORIZONS = [7, 14, 30];
const PAGE_LIMIT = 1000; // API maximum per request
const PAGE_SIZE = 12;

const tooltipStyle = {
  backgroundColor: '#1a1d27', border: '1px solid #2d3147', borderRadius: '6px', fontSize: '0.75rem', color: '#e4e6f0',
};

const num = (v) => (v == null || v === '' ? 0 : Number(v));
const dec = (v, d = 1) => num(v).toFixed(d);

/** The API caps `limit` at 1000, so page through until `total` rows are loaded. */
async function fetchAll(params = {}) {
  const first = await fetchForecasts({ ...params, limit: PAGE_LIMIT, offset: 0 });
  let rows = first.data ?? [];
  const total = first.total ?? rows.length;
  for (let offset = PAGE_LIMIT; offset < total; offset += PAGE_LIMIT) {
    const next = await fetchForecasts({ ...params, limit: PAGE_LIMIT, offset });
    rows = rows.concat(next.data ?? []);
  }
  return { data: rows, total };
}

function SimpleTooltip({ active, payload, label, unit = 'units' }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={tooltipStyle}>
      <div style={{ padding: '0.45rem 0.7rem', borderBottom: '1px solid #2d3147', fontWeight: 600 }}>{label ?? payload[0].payload?.name}</div>
      <div style={{ padding: '0.45rem 0.7rem', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
        {payload.map((p) => (
          <div key={p.dataKey} style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
            <span style={{ color: p.color ?? p.payload?.fill ?? '#8b90a8' }}>{p.name}:</span>
            <span style={{ fontWeight: 600 }}>{fmtNum(Math.round(p.value))} {unit}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Pager({ page, setPage, total }) {
  if (total <= PAGE_SIZE) return null;
  const last = Math.ceil(total / PAGE_SIZE) - 1;
  return (
    <div className="table-pagination">
      <span>
        Showing <strong>{page * PAGE_SIZE + 1}</strong>–<strong>{Math.min((page + 1) * PAGE_SIZE, total)}</strong> of{' '}
        <strong>{fmtNum(total)}</strong> pairs
      </span>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="pagination-btn" disabled={page === 0} onClick={() => setPage(Math.max(0, page - 1))}>Previous</button>
        <button className="pagination-btn" disabled={page >= last} onClick={() => setPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}

const SORTS = {
  demand:   { label: 'Highest forecast demand', fn: (a, b) => b.cur.predicted - a.cur.predicted },
  shortfall: { label: 'Largest forecast − stock', fn: (a, b) => (b.cur.predicted - b.stock) - (a.cur.predicted - a.stock) },
  width:    { label: 'Widest interval', fn: (a, b) => (b.cur.upper - b.cur.lower) - (a.cur.upper - a.cur.lower) },
  stock:    { label: 'Lowest current stock', fn: (a, b) => a.stock - b.stock },
};

// ─────────────────────────────────────────────────────────────
// Demand & Forecast Page
// ─────────────────────────────────────────────────────────────
export default function Forecast() {
  const { caps } = useDataset();
  const hasStock = caps.inventory_expiry_decisions !== false;     // uploads without stock data: hide every stock comparison
  const [horizon, setHorizon] = useState(7);
  const [branchFilter, setBranchFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('demand');
  const [shortfallOnly, setShortfallOnly] = useState(false);
  const [tablePage, setTablePage] = useState(0);
  const [selectedKey, setSelectedKey] = useState(null);
  const [showMethod, setShowMethod] = useState(false);

  const q = useFetch(() => fetchAll(), []);
  const rows = useMemo(() => q.data?.data ?? [], [q.data]);

  // One record per branch × medicine with its three horizons.
  const pairs = useMemo(() => {
    const map = new Map();
    rows.forEach((r) => {
      const key = `${r.branch_id}-${r.medicine_id}`;
      if (!map.has(key)) {
        map.set(key, {
          key, branch_id: r.branch_id, medicine_id: r.medicine_id, medicine_name: r.medicine_name,
          category: r.category, stock: num(r.current_inventory), stockout: Number(r.stockout_flag) === 1,
          recentStockoutDays: num(r.recent_stockout_days), h: {},
        });
      }
      map.get(key).h[r.horizon] = {
        predicted: num(r.predicted_units), lower: num(r.lower_bound), upper: num(r.upper_bound),
        start: r.target_start, end: r.target_end,
      };
    });
    return [...map.values()].map((p) => ({ ...p, cur: p.h[horizon] ?? { predicted: 0, lower: 0, upper: 0 } }));
  }, [rows, horizon]);

  const origin = rows[0]?.forecast_date;
  const window = pairs[0]?.cur?.start ? `${fmtDate(pairs[0].cur.start)} – ${fmtDate(pairs[0].cur.end)}` : null;

  const branches = useMemo(() => [...new Set(pairs.map((p) => p.branch_id))].sort(), [pairs]);
  const categories = useMemo(() => [...new Set(pairs.map((p) => p.category))].sort(), [pairs]);

  // KPI totals per horizon
  const totals = useMemo(() => {
    const t = {};
    HORIZONS.forEach((h) => { t[h] = pairs.reduce((a, p) => a + (p.h[h]?.predicted ?? 0), 0); });
    return t;
  }, [pairs]);
  const exceedStock = useMemo(() => pairs.filter((p) => (p.h[7]?.predicted ?? 0) > p.stock).length, [pairs]);

  // Chart data (selected horizon)
  const branchData = useMemo(() => {
    const m = {};
    pairs.forEach((p) => {
      m[p.branch_id] ??= { name: p.branch_id, predicted: 0, lower: 0, upper: 0, stock: 0 };
      m[p.branch_id].predicted += p.cur.predicted;
      m[p.branch_id].lower += p.cur.lower;
      m[p.branch_id].upper += p.cur.upper;
      m[p.branch_id].stock += p.stock;
    });
    return Object.values(m).sort((a, b) => a.name.localeCompare(b.name));
  }, [pairs]);

  const categoryData = useMemo(() => {
    const m = {};
    pairs.forEach((p) => { m[p.category] = (m[p.category] ?? 0) + p.cur.predicted; });
    return Object.entries(m).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  }, [pairs]);

  // Table
  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    return pairs
      .filter((p) => {
        if (branchFilter && p.branch_id !== branchFilter) return false;
        if (categoryFilter && p.category !== categoryFilter) return false;
        if (shortfallOnly && p.cur.predicted <= p.stock) return false;
        if (s && !`${p.medicine_name} ${p.medicine_id} ${p.category}`.toLowerCase().includes(s)) return false;
        return true;
      })
      .sort(SORTS[sortKey].fn);
  }, [pairs, branchFilter, categoryFilter, shortfallOnly, search, sortKey]);

  const paged = filtered.slice(tablePage * PAGE_SIZE, (tablePage + 1) * PAGE_SIZE);
  const reset = (setter) => (v) => { setter(v); setTablePage(0); };

  const selected = useMemo(
    () => pairs.find((p) => p.key === selectedKey) ?? filtered[0] ?? null,
    [pairs, filtered, selectedKey],
  );
  const selectedChart = selected
    ? HORIZONS.map((h) => ({
      name: `${h} days`, lower: selected.h[h]?.lower ?? 0, predicted: selected.h[h]?.predicted ?? 0, upper: selected.h[h]?.upper ?? 0,
    }))
    : [];

  const error = q.error ? 'Unable to load demand forecasts.' : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* ── Header ─────────────────────────────────────────── */}
      <div className="page-header" style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 className="page-title">Demand &amp; Forecast</h1>
          <p className="page-subtitle">Expected unit demand for every branch and medicine over the next 7, 14 and 30 days.</p>
        </div>
        <span className="header-badge" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: C_ACCENT }} />
          ML Forecast · Gradient Boosting · 7 / 14 / 30 days
        </span>
      </div>

      {/* ── Banner ─────────────────────────────────────────── */}
      <div style={{
        background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99, 102, 241, 0.25)',
        borderRadius: 'var(--radius)', padding: '0.65rem 1rem', fontSize: '0.75rem', color: '#c7d2fe',
        display: 'flex', flexDirection: 'column', gap: '0.25rem',
      }}>
        <div>
          <strong>Forecast issued at the end of {origin ? fmtDate(origin) : '—'}.</strong>{' '}
          Values are model estimates of observed unit sales, not guaranteed demand; the lower/upper bounds are an approximate 80% empirical interval.
        </div>
        <div style={{ color: '#a5b4fc' }}>
          {hasStock ? 'Trained on synthetic pharmacy data, so results describe this dataset only. Purchasing actions are on the ' : 'Based on the sales history you uploaded (no stock data), so stockouts are not considered. '}
          {hasStock && <><Link to="/decisions" style={{ color: '#c7d2fe', textDecoration: 'underline' }}>Decision Support</Link> page.</>}
        </div>
      </div>

      {/* ── KPIs ───────────────────────────────────────────── */}
      <div className="kpi-grid">
        <KpiCard label="Pairs Forecast" accent="blue" loading={q.loading}
          value={error ? '—' : fmtNum(pairs.length)} note="Branch × medicine combinations" />
        <KpiCard label="Next 7 Days" accent="green" loading={q.loading}
          value={error ? '—' : fmtNum(Math.round(totals[7]))} note="Total forecast units, all pairs" />
        <KpiCard label="Next 14 Days" accent="purple" loading={q.loading}
          value={error ? '—' : fmtNum(Math.round(totals[14]))} note="Total forecast units, all pairs" />
        <KpiCard label="Next 30 Days" accent="amber" loading={q.loading}
          value={error ? '—' : fmtNum(Math.round(totals[30]))} note="Total forecast units, all pairs" />
        {hasStock && (
          <KpiCard label="7-Day Demand > Stock" accent="red" loading={q.loading}
            value={error ? '—' : fmtNum(exceedStock)} note="Pairs where forecast exceeds current stock" />
        )}
      </div>

      {/* ── Horizon selector ───────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Forecast horizon</span>
        <div className="btn-toggle-group">
          {HORIZONS.map((h) => (
            <button key={h} className={`btn-toggle ${horizon === h ? 'active' : ''}`}
              onClick={() => { setHorizon(h); setTablePage(0); }}>{h} days</button>
          ))}
        </div>
        {window && <span style={{ fontSize: '0.72rem', color: '#8b90a8' }}>Forecast window: {window}</span>}
      </div>

      {/* ── Charts ─────────────────────────────────────────── */}
      <div className="chart-grid">
        <ChartCard title="Forecast Demand by Branch" subtitle={hasStock ? `Total expected units over ${horizon} days, with current stock` : `Total expected units over ${horizon} days`}
          loading={q.loading} error={error} onRetry={q.refetch} isEmpty={!branchData.length} height={260}>
          <div style={{ width: '100%', height: '260px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={branchData} margin={{ top: 10, right: 20, left: -5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                <YAxis tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                <Tooltip content={<SimpleTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                <Legend wrapperStyle={{ fontSize: '0.72rem', color: '#8b90a8' }} />
                <Bar dataKey="predicted" name="Forecast" fill={C_ACCENT} radius={[4, 4, 0, 0]} />
                {hasStock && <Bar dataKey="stock" name="Current stock" fill="#475569" radius={[4, 4, 0, 0]} />}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Forecast Demand by Category" subtitle={`Total expected units over ${horizon} days`}
          loading={q.loading} error={error} onRetry={q.refetch} isEmpty={!categoryData.length} height={260}>
          <div style={{ width: '100%', height: '260px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={categoryData} layout="vertical" margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                <YAxis type="category" dataKey="name" width={120} tick={{ fill: '#8b90a8', fontSize: 10 }} axisLine={{ stroke: '#2d3147' }} />
                <Tooltip content={<SimpleTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                <Bar dataKey="value" name="Forecast" radius={[0, 4, 4, 0]}>
                  {categoryData.map((e, i) => <Cell key={e.name} fill={CAT_COLORS[i % CAT_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </div>

      {/* ── Forecast explorer ──────────────────────────────── */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div className="card-title">Forecast Explorer</div>
            <div className="card-subtitle">{horizon}-day forecast per branch and medicine — select a row to see all horizons</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <select className="filter-select" value={branchFilter} onChange={(e) => reset(setBranchFilter)(e.target.value)}>
              <option value="">All Branches</option>
              {branches.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
            <select className="filter-select" value={categoryFilter} onChange={(e) => reset(setCategoryFilter)(e.target.value)}>
              <option value="">All Categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select className="filter-select" value={sortKey} onChange={(e) => reset(setSortKey)(e.target.value)}>
              {Object.entries(SORTS).filter(([k]) => hasStock || (k !== 'shortfall' && k !== 'stock')).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
            </select>
            {hasStock && (
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.75rem', color: '#a0a5bd', cursor: 'pointer' }}>
                <input type="checkbox" checked={shortfallOnly} onChange={(e) => reset(setShortfallOnly)(e.target.checked)} />
                Forecast &gt; stock only
              </label>
            )}
            <input type="text" className="filter-input" placeholder="Search medicine / category..."
              value={search} onChange={(e) => reset(setSearch)(e.target.value)} style={{ width: '190px' }} />
          </div>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {q.loading ? (
            <div style={{ padding: '1.5rem' }}><div className="skeleton" style={{ height: '260px', width: '100%', borderRadius: '4px' }} /></div>
          ) : error ? (
            <div className="error-state">
              <span className="error-icon">⚠</span><span className="error-msg">{error}</span>
              <button className="retry-btn" onClick={q.refetch}>Retry</button>
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">No forecasts match the selected filters.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Branch</th><th>Medicine</th>{hasStock && <th>Stock</th>}
                    <th>{horizon}D Forecast</th><th>80% Range</th>{hasStock && <th>Forecast − Stock</th>}{hasStock && <th>Status</th>}
                  </tr>
                </thead>
                <tbody>
                  {paged.map((p) => {
                    const gap = p.cur.predicted - p.stock;
                    const isSel = selected?.key === p.key;
                    return (
                      <tr key={p.key} onClick={() => setSelectedKey(p.key)}
                        style={{ cursor: 'pointer', background: isSel ? 'rgba(99,102,241,0.12)' : undefined }}>
                        <td><span style={{ fontWeight: 600, color: '#818cf8', fontSize: '0.75rem' }}>{p.branch_id}</span></td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{p.medicine_name}</div>
                          <div style={{ fontSize: '0.68rem', color: '#8b90a8' }}>{p.medicine_id} • {p.category}</div>
                        </td>
                        {hasStock && <td style={{ fontWeight: 600, color: p.stock === 0 ? C_DANGER : '#e4e6f0' }}>{fmtNum(p.stock)}</td>}
                        <td style={{ fontWeight: 700 }}>{dec(p.cur.predicted)}</td>
                        <td style={{ color: '#8b90a8' }}>{dec(p.cur.lower)} – {dec(p.cur.upper)}</td>
                        {hasStock && <td style={{ fontWeight: 600, color: gap > 0 ? C_WARNING : '#86efac' }}>{gap > 0 ? '+' : ''}{dec(gap)}</td>}
                        {hasStock && (
                          <td>
                            {p.stockout
                              ? <span className="badge badge-critical">OUT OF STOCK</span>
                              : gap > 0
                                ? <span className="badge badge-high">DEMAND &gt; STOCK</span>
                                : <span className="badge badge-low">COVERED</span>}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!q.loading && !error && <Pager page={tablePage} setPage={setTablePage} total={filtered.length} />}
        </div>
      </div>

      {/* ── Selected pair detail ───────────────────────────── */}
      {selected && !q.loading && !error && (
        <ChartCard
          title={selected.medicine_name}
          subtitle={`${selected.branch_id} • ${selected.medicine_id} • ${selected.category}${hasStock ? ` — ${fmtNum(selected.stock)} units in stock` : ''}`}
          isEmpty={!selectedChart.length} height={260}
        >
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1rem', alignItems: 'center' }}>
            <div style={{ width: '100%', height: '260px' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={selectedChart} margin={{ top: 10, right: 20, left: -5, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                  <YAxis tick={{ fill: '#8b90a8', fontSize: 11 }} axisLine={{ stroke: '#2d3147' }} />
                  <Tooltip content={<SimpleTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                  <Legend wrapperStyle={{ fontSize: '0.72rem', color: '#8b90a8' }} />
                  <Bar dataKey="lower" name="Lower (10%)" fill="#475569" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="predicted" name="Forecast" fill={C_ACCENT} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="upper" name="Upper (90%)" fill={C_INFO} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <table className="data-table">
              <thead><tr><th>Horizon</th><th>Forecast</th><th>Per day</th><th>Range</th>{hasStock && <th>Stock covers</th>}</tr></thead>
              <tbody>
                {HORIZONS.map((h) => {
                  const c = selected.h[h];
                  if (!c) return null;
                  const perDay = c.predicted / h;
                  return (
                    <tr key={h}>
                      <td style={{ fontWeight: 600 }}>{h} days</td>
                      <td style={{ fontWeight: 700 }}>{dec(c.predicted)}</td>
                      <td>{dec(perDay, 2)}</td>
                      <td style={{ color: '#8b90a8' }}>{dec(c.lower)} – {dec(c.upper)}</td>
                      {hasStock && <td>{perDay > 0 ? `${dec(selected.stock / perDay)} days` : '—'}</td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </ChartCard>
      )}

      {/* ── Methodology ────────────────────────────────────── */}
      <div className="card" style={{ background: '#141722', borderColor: '#2d3147' }}>
        <div className="card-header" style={{ cursor: 'pointer' }} onClick={() => setShowMethod((s) => !s)}>
          <div className="card-title">How these forecasts are produced</div>
          <button className="pagination-btn" onClick={(e) => { e.stopPropagation(); setShowMethod((s) => !s); }}>
            {showMethod ? 'Hide' : 'Show'}
          </button>
        </div>
        {showMethod && (
          <div className="card-body" style={{ fontSize: '0.78rem', color: '#a0a5bd', lineHeight: 1.6 }}>
            <ul style={{ paddingLeft: '1.1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <li>One forecast per branch × medicine pair and per horizon (7, 14, 30 days); target is total units sold over the horizon.</li>
              <li>Model: gradient-boosted trees (scikit-learn <em>HistGradientBoostingRegressor</em>), one model per horizon, trained on lagged and rolling demand, stockout context, calendar and branch/category features.</li>
              <li>Evaluated with a chronological split (train → validation → test) against naive and moving-average baselines; no random splitting.</li>
              <li>Observed sales understate demand during stockouts; lost sales are never imputed.</li>
              <li>The lower and upper bounds are empirical 10% / 90% residual quantiles — an approximate 80% interval, not a formal probabilistic forecast.</li>
              <li>“Forecast − stock” and “stock covers” are simple descriptive comparisons; reorder quantities and priorities come from the Decision Support layer.</li>
              <li>The dataset is synthetic; slow-moving medicines are inherently noisy and unpredictable.</li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
