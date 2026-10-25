import { useState, useMemo } from 'react';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { useFetch } from '../hooks/useFetch';
import { fetchOlap } from '../api/client';
import { fmtINR_SI, fmtNum } from '../utils/format';

// ── Cube definition ──────────────────────────────────────────
// Dimensions are grouped the way a pharmacy owner thinks: when, where, what.
const GROUPS = [
  { name: 'When', dims: { year: 'Year', quarter: 'Quarter', month: 'Month', day: 'Day', weekday: 'Weekday' } },
  { name: 'Where', dims: { city: 'City', branch: 'Branch' } },
  { name: 'What', dims: { category: 'Category', medicine: 'Medicine', dosage_form: 'Dosage form', manufacturer: 'Manufacturer' } },
];
const DIMS = Object.assign({}, ...GROUPS.map((g) => g.dims));
const HIERARCHIES = [['year', 'quarter', 'month', 'day'], ['city', 'branch'], ['category', 'medicine']];
const MEASURES = {
  revenue: { label: 'Revenue', sub: 'Money earned from sales' },
  units: { label: 'Units sold', sub: 'Number of items sold' },
  transactions: { label: 'Transactions', sub: 'Number of customer bills' },
};
const PRESETS = [
  { name: 'Revenue by month', measure: 'revenue', row: 'month', col: '', filters: {} },
  { name: 'Category sales at each branch', measure: 'revenue', row: 'category', col: 'branch', filters: {} },
  { name: 'Busiest weekdays', measure: 'transactions', row: 'weekday', col: '', filters: {} },
  { name: 'Top medicines', measure: 'units', row: 'medicine', col: '', filters: {} },
];

const hierarchyOf = (dim) => HIERARCHIES.find((h) => h.includes(dim));
const parentOf = (dim) => { const h = hierarchyOf(dim); return h && h[h.indexOf(dim) - 1]; };
const childOf = (dim) => { const h = hierarchyOf(dim); return h && h[h.indexOf(dim) + 1]; };

const TIME_DIMS = ['year', 'quarter', 'month', 'day'];
const PALETTE = ['#0d9488', '#6366f1', '#f59e0b', '#0284c7', '#ec4899', '#84cc16', '#ef4444', '#8b5cf6', '#14b8a6', '#fb923c'];
const MAX_BARS = 15;
const MAX_SERIES = 10;
const TABLE_PREVIEW = 12;
const tooltipStyle = { backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: '0.78rem', color: '#0f172a' };
const fmtMeasure = (m, v) => (v == null ? '—' : m === 'revenue' ? fmtINR_SI(v) : fmtNum(v));

function Step({ n, title, help, term, children }) {
  return (
    <section className="step">
      <div className="step-head">
        <span className="step-num">{n}</span>
        <div>
          <div className="step-title">{title}</div>
          <div className="step-help">{help}</div>
        </div>
        {term && <span className="term">{term}</span>}
      </div>
      <div className="step-body">{children}</div>
    </section>
  );
}

function DimChips({ value, onPick, allowNone, exclude }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
      {allowNone && (
        <div><button type="button" className={`chip ${value === '' ? 'on' : ''}`} onClick={() => onPick('')}>Don’t split</button></div>
      )}
      {GROUPS.map((g) => (
        <div key={g.name}>
          <div className="group-label">{g.name}</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
            {Object.entries(g.dims).filter(([k]) => k !== exclude).map(([k, label]) => (
              <button key={k} type="button" className={`chip ${value === k ? 'on' : ''}`} onClick={() => onPick(k)}>{label}</button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function OlapExplorer() {
  const [row, setRow] = useState('month');
  const [col, setCol] = useState('');
  const [measure, setMeasure] = useState('revenue');
  const [filters, setFilters] = useState({});            // { dim: [member, ...] }
  const [filterDim, setFilterDim] = useState('');
  const [draft, setDraft] = useState([]);
  const [chartType, setChartType] = useState('bar');
  const [showAll, setShowAll] = useState(false);

  const filterParams = useMemo(
    () => Object.entries(filters).filter(([, v]) => v.length).map(([d, v]) => `${d}:${v.join('|')}`),
    [filters],
  );
  const cube = useFetch(
    () => fetchOlap({ row, col, measure, filter: filterParams }),
    [row, col, measure, filterParams.join(';')],
  );
  const members = useFetch(
    () => (filterDim ? fetchOlap({ row: filterDim, measure: 'revenue' }) : Promise.resolve(null)),
    [filterDim],
  );

  const result = cube.data;
  const rows = useMemo(() => result?.data ?? [], [result]);
  const columns = result?.columns ?? [];
  const max = Math.max(1, ...rows.flatMap((r) => r.cells.filter((c) => c != null)));
  const activeFilters = Object.entries(filters).filter(([, v]) => v.length);
  const isTime = TIME_DIMS.includes(row);
  const canIn = !!childOf(row);
  const canOut = !!parentOf(row);

  // ── actions ──
  const setGroup = (v) => { if (v === col) setCol(''); setRow(v); setShowAll(false); };
  const zoomOut = () => {
    const p = parentOf(row);
    if (!p) return;
    setFilters((f) => { const n = { ...f }; delete n[p]; return n; });
    setRow(p);
  };
  const zoomInto = (label) => {
    const c = childOf(row);
    if (!c) return;
    setFilters((f) => ({ ...f, [row]: [label] }));
    setRow(c);
  };
  const zoomIn = () => { const c = childOf(row); if (c) setRow(c); };
  const swap = () => { if (col) { setRow(col); setCol(row); } };
  const applyDraft = () => {
    setFilters((f) => ({ ...f, [filterDim]: draft }));
    setFilterDim(''); setDraft([]);
  };
  const removeFilter = (d) => setFilters((f) => ({ ...f, [d]: [] }));
  const reset = () => { setRow('month'); setCol(''); setMeasure('revenue'); setFilters({}); setFilterDim(''); setShowAll(false); };
  const applyPreset = (p) => { setMeasure(p.measure); setRow(p.row); setCol(p.col); setFilters(p.filters); setFilterDim(''); setShowAll(false); };

  // ── chart data ──
  const chart = useMemo(() => {
    const shown = isTime ? rows : rows.slice(0, MAX_BARS);
    const cols = result?.columns ?? [];
    const order = cols.map((c, i) => ({ c, i, t: rows.reduce((a, r) => a + (r.cells[i] ?? 0), 0) })).sort((a, b) => b.t - a.t);
    const keep = order.slice(0, MAX_SERIES);
    const rest = order.slice(MAX_SERIES);
    const series = keep.map((k) => k.c).concat(rest.length ? ['Other'] : []);
    const data = shown.map((r) => {
      const d = { label: r.label, Total: r.total };
      keep.forEach((k) => { d[k.c] = r.cells[k.i] ?? 0; });
      if (rest.length) d.Other = rest.reduce((a, k) => a + (r.cells[k.i] ?? 0), 0);
      return d;
    });
    return { data, series, clipped: !isTime && rows.length > MAX_BARS };
  }, [rows, result, isTime]);
  const seriesKeys = col ? chart.series : [MEASURES[measure].label];
  const chartData = col ? chart.data : chart.data.map((d) => ({ ...d, [MEASURES[measure].label]: d.Total }));
  const onChartClick = (e) => { if (canIn && e?.activeLabel) zoomInto(e.activeLabel); };

  const sentence = `${MEASURES[measure].label} by ${DIMS[row]}${col ? `, split by ${DIMS[col]}` : ''}`
    + (activeFilters.length ? ` — only ${activeFilters.map(([d, v]) => `${DIMS[d]}: ${v.length > 2 ? `${v.length} selected` : v.join(', ')}`).join('; ')}` : '')
    + (result ? ` · Total ${fmtMeasure(measure, result.grand_total)}` : '');

  const axis = { stroke: '#94a3b8', fontSize: 11, tickLine: false };
  const xProps = {
    dataKey: 'label', ...axis, axisLine: { stroke: '#e2e8f0' },
    angle: chartData.length > 8 ? -30 : 0, textAnchor: chartData.length > 8 ? 'end' : 'middle',
    height: chartData.length > 8 ? 70 : 30, tickFormatter: (v) => (String(v).length > 18 ? `${String(v).slice(0, 17)}…` : v),
  };
  const yProps = { ...axis, axisLine: false, width: 60, tickFormatter: (v) => fmtMeasure(measure, v) };
  const cursor = { cursor: canIn ? 'pointer' : 'default' };

  const visibleRows = showAll ? rows : rows.slice(0, TABLE_PREVIEW);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Quick questions */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
        <span className="group-label" style={{ margin: 0 }}>Quick questions</span>
        {PRESETS.map((p) => <button key={p.name} type="button" className="chip" onClick={() => applyPreset(p)}>{p.name}</button>)}
        <button type="button" className="btn" style={{ marginLeft: 'auto' }} onClick={reset}>Start over</button>
      </div>

      <Step n={1} title="What do you want to measure?" help="Pick one number to look at.">
        <div className="choice-grid">
          {Object.entries(MEASURES).map(([k, m]) => (
            <button key={k} type="button" className={`choice ${measure === k ? 'on' : ''}`} onClick={() => setMeasure(k)}>
              <span className="choice-label">{m.label}</span><span className="choice-sub">{m.sub}</span>
            </button>
          ))}
        </div>
      </Step>

      <Step n={2} title="How should it be grouped?" help="Choose what each row of the result stands for." term="Dimensions">
        <div>
          <div className="group-label">Group by</div>
          <DimChips value={row} onPick={setGroup} />
        </div>
        <details open={!!col}>
          <summary style={{ cursor: 'pointer', fontSize: '0.82rem', fontWeight: 600, color: 'var(--color-accent-light)' }}>
            Split further by another dimension (optional) {col && `· ${DIMS[col]}`}
          </summary>
          <div style={{ marginTop: '0.7rem' }}>
            <DimChips value={col} onPick={setCol} allowNone exclude={row} />
          </div>
        </details>
      </Step>

      <Step n={3} title="Narrow it down (optional)" help="Look at just one branch, one category, one year… or a few of them." term="Slice & dice">
        {activeFilters.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
            {activeFilters.map(([d, v]) => (
              <button key={d} type="button" className="chip on" title="Remove this filter" onClick={() => removeFilter(d)}>
                {DIMS[d]}: {v.length > 2 ? `${v.length} selected` : v.join(', ')} ✕
              </button>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
          <label className="step-help" htmlFor="olap-filter-dim">Only show</label>
          <select
            id="olap-filter-dim" className="filter-select" value={filterDim}
            onChange={(e) => { setFilterDim(e.target.value); setDraft(filters[e.target.value] ?? []); }}
          >
            <option value="">Choose a dimension…</option>
            {Object.entries(DIMS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        {filterDim && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {members.loading ? <div className="step-help">Loading options…</div> : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', maxHeight: 170, overflowY: 'auto' }}>
                {(members.data?.data ?? []).map((m) => {
                  const on = draft.includes(m.label);
                  return (
                    <button key={m.label} type="button" className={`chip ${on ? 'on' : ''}`}
                      onClick={() => setDraft((d) => (on ? d.filter((x) => x !== m.label) : [...d, m.label]))}>
                      {m.label}
                    </button>
                  );
                })}
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <button type="button" className="btn btn-primary" onClick={applyDraft}>Apply</button>
              <button type="button" className="btn" onClick={() => setFilterDim('')}>Cancel</button>
              <span className="step-help">Pick one to focus on it, or several to compare them.</span>
            </div>
          </div>
        )}
      </Step>

      <Step n={4} title="Your result" help="Click a bar to zoom into it." term="Roll-up · Drill-down · Pivot">
        <div className="answer">{sentence}</div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
          <button type="button" className="btn" disabled={!canOut} onClick={zoomOut}
            title="Move to a broader level">▲ Zoom out{canOut ? ` to ${DIMS[parentOf(row)]}` : ''}</button>
          <button type="button" className="btn" disabled={!canIn} onClick={zoomIn}
            title="Move to a more detailed level">▼ Zoom in{canIn ? ` to ${DIMS[childOf(row)]}` : ''}</button>
          <button type="button" className="btn" disabled={!col} onClick={swap} title="Swap grouping and split">⇄ Swap</button>
          <div className="btn-toggle-group" style={{ marginLeft: 'auto' }}>
            <button type="button" className={`btn-toggle ${chartType === 'bar' ? 'active' : ''}`} onClick={() => setChartType('bar')}>Bars</button>
            <button type="button" className={`btn-toggle ${chartType === 'line' ? 'active' : ''}`} onClick={() => setChartType('line')}>Line</button>
          </div>
        </div>

        {cube.error ? (
          <div className="error-state">
            <span className="error-icon">⚠</span>
            <span className="error-msg">Unable to load: {cube.error}</span>
            <button className="retry-btn" onClick={cube.refetch}>Retry</button>
          </div>
        ) : cube.loading && !result ? (
          <div className="skeleton" style={{ height: 300 }} />
        ) : chartData.length === 0 ? (
          <div className="empty-state" style={{ minHeight: 200 }}>No data for this selection.</div>
        ) : (
          <div style={{ opacity: cube.loading ? 0.5 : 1 }}>
            <ResponsiveContainer width="100%" height={320}>
              {chartType === 'bar' ? (
                <BarChart data={chartData} margin={{ top: 5, right: 15, left: 0, bottom: 5 }} onClick={onChartClick} style={cursor}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis {...xProps} interval={chartData.length > 12 ? Math.ceil(chartData.length / 8) - 1 : 0} />
                  <YAxis {...yProps} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(13,148,136,0.08)' }} formatter={(v, n) => [fmtMeasure(measure, v), n]} />
                  {col && <Legend wrapperStyle={{ fontSize: '0.72rem' }} />}
                  {seriesKeys.map((k, i) => (
                    <Bar key={k} dataKey={k} stackId={col ? 'a' : undefined} fill={PALETTE[i % PALETTE.length]}
                      radius={!col || i === seriesKeys.length - 1 ? [4, 4, 0, 0] : 0} maxBarSize={48} />
                  ))}
                </BarChart>
              ) : (
                <LineChart data={chartData} margin={{ top: 5, right: 15, left: 0, bottom: 5 }} onClick={onChartClick} style={cursor}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis {...xProps} interval={chartData.length > 12 ? Math.ceil(chartData.length / 8) - 1 : 0} />
                  <YAxis {...yProps} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [fmtMeasure(measure, v), n]} />
                  {col && <Legend wrapperStyle={{ fontSize: '0.72rem' }} />}
                  {seriesKeys.map((k, i) => (
                    <Line key={k} type="monotone" dataKey={k} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2.5}
                      dot={chartData.length <= 31} activeDot={{ r: 4 }} />
                  ))}
                </LineChart>
              )}
            </ResponsiveContainer>
            {chart.clipped && <div className="step-help">Chart shows the top {MAX_BARS} of {rows.length}; the table lists more.</div>}
          </div>
        )}

        {!cube.error && rows.length > 0 && (
          <div style={{ overflowX: 'auto', opacity: cube.loading ? 0.5 : 1 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{DIMS[row]}</th>
                  {columns.map((c) => <th key={c} style={{ textAlign: 'right' }}>{c}</th>)}
                  <th style={{ textAlign: 'right' }}>Total</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((r) => (
                  <tr key={r.label}>
                    <td style={{ fontWeight: 600, whiteSpace: 'normal', minWidth: 140 }}>
                      {canIn ? (
                        <button type="button" onClick={() => zoomInto(r.label)} title={`Zoom into ${r.label}`}
                          style={{ all: 'unset', cursor: 'pointer', color: 'var(--color-accent-light)', textDecoration: 'underline dotted' }}>
                          {r.label}
                        </button>
                      ) : r.label}
                    </td>
                    {r.cells.map((v, i) => (
                      <td key={columns[i]} style={{ textAlign: 'right', background: v != null ? `rgba(13,148,136,${(0.04 + 0.3 * v / max).toFixed(3)})` : 'transparent' }}>
                        {fmtMeasure(measure, v)}
                      </td>
                    ))}
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmtMeasure(measure, r.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > TABLE_PREVIEW && (
              <div style={{ paddingTop: '0.6rem' }}>
                <button type="button" className="btn" onClick={() => setShowAll((s) => !s)}>
                  {showAll ? 'Show fewer rows' : `Show all ${rows.length} rows`}
                </button>
              </div>
            )}
            {(result?.truncated_rows || result?.truncated_cols) && (
              <div className="step-help" style={{ marginTop: 6 }}>Showing the largest results only; narrow it down in step 3 to see the rest.</div>
            )}
          </div>
        )}
      </Step>
    </div>
  );
}
