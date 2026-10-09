import { useState, useMemo } from 'react';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { useFetch } from '../hooks/useFetch';
import { fetchOlap } from '../api/client';
import { fmtINR_SI, fmtNum } from '../utils/format';

// Dimension levels, grouped into hierarchies. Roll-up / drill-down move along a hierarchy.
const DIMS = {
  year: 'Year', quarter: 'Quarter', month: 'Month', day: 'Day', weekday: 'Weekday',
  city: 'City', branch: 'Branch', category: 'Category', medicine: 'Medicine',
  dosage_form: 'Dosage form', manufacturer: 'Manufacturer',
};
const HIERARCHIES = [['year', 'quarter', 'month', 'day'], ['city', 'branch'], ['category', 'medicine']];
const MEASURES = { revenue: 'Revenue', units: 'Units sold', transactions: 'Transactions' };

const hierarchyOf = (dim) => HIERARCHIES.find((h) => h.includes(dim));
const parentOf = (dim) => { const h = hierarchyOf(dim); return h && h[h.indexOf(dim) - 1]; };
const childOf = (dim) => { const h = hierarchyOf(dim); return h && h[h.indexOf(dim) + 1]; };

const TIME_DIMS = ['year', 'quarter', 'month', 'day'];
const PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#38bdf8', '#a78bfa', '#ef4444', '#14b8a6', '#f472b6', '#84cc16', '#fb923c'];
const MAX_BARS = 15;       // rows shown on a chart; the table still lists every row
const MAX_SERIES = 10;     // series shown on a chart; the rest are grouped as "Other"
const tooltipStyle = {
  backgroundColor: '#1a1d27', border: '1px solid #2d3147', borderRadius: 6, fontSize: '0.75rem', color: '#e4e6f0',
};
const fmtAxis = (m, v) => (m === 'revenue' ? fmtINR_SI(v) : fmtNum(v));

const fmtMeasure = (m, v) => (v == null ? '—' : m === 'revenue' ? fmtINR_SI(v) : fmtNum(v));

const selectStyle = {
  background: 'transparent', color: 'inherit', border: '1px solid var(--color-border)',
  borderRadius: 6, padding: '0.3rem 0.5rem', fontSize: '0.78rem',
};
const btnStyle = (active = false, disabled = false) => ({
  fontSize: '0.75rem', fontWeight: 600, padding: '0.35rem 0.75rem', borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
  border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`, background: 'transparent',
  color: active ? 'var(--color-accent-light, #818cf8)' : 'inherit', opacity: disabled ? 0.4 : 1, whiteSpace: 'nowrap',
});
const labelStyle = { fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--color-muted)', fontWeight: 600 };

export default function OlapExplorer() {
  const [row, setRow] = useState('year');
  const [col, setCol] = useState('');
  const [measure, setMeasure] = useState('revenue');
  const [filters, setFilters] = useState({});          // { dim: [member, ...] }  1 member = slice, 2+ = dice
  const [note, setNote] = useState('Showing sales by Year.');
  const [picker, setPicker] = useState({ dim: '', open: false });
  const [draft, setDraft] = useState([]);
  const [chartType, setChartType] = useState('bar');

  const filterParams = useMemo(
    () => Object.entries(filters).filter(([, v]) => v.length).map(([d, v]) => `${d}:${v.join('|')}`),
    [filters],
  );
  const cube = useFetch(
    () => fetchOlap({ row, col, measure, filter: filterParams }),
    [row, col, measure, filterParams.join(';')],
  );
  // Members available in the slice/dice picker
  const members = useFetch(
    () => (picker.dim ? fetchOlap({ row: picker.dim, measure: 'revenue' }) : Promise.resolve(null)),
    [picker.dim],
  );

  const result = cube.data;
  const rows = useMemo(() => result?.data ?? [], [result]);
  const columns = result?.columns ?? [];
  const max = Math.max(1, ...rows.flatMap((r) => r.cells.filter((c) => c != null)));

  // ── OLAP operations ────────────────────────────────────
  const rollUp = () => {
    const p = parentOf(row);
    if (!p) return;
    setFilters((f) => { const n = { ...f }; delete n[p]; return n; });
    setRow(p);
    setNote(`Roll-up: ${DIMS[row]} → ${DIMS[p]} (less detail).`);
  };
  const drillInto = (label) => {
    const c = childOf(row);
    if (!c) return;
    setFilters((f) => ({ ...f, [row]: [label] }));
    setRow(c);
    setNote(`Drill-down: ${DIMS[row]} ${label} → ${DIMS[c]} (more detail).`);
  };
  const drillDown = () => {
    const c = childOf(row);
    if (!c) return;
    setRow(c);
    setNote(`Drill-down: ${DIMS[row]} → ${DIMS[c]} (more detail).`);
  };
  const pivot = () => {
    if (!col) return;
    setRow(col);
    setCol(row);
    setNote(`Pivot: rows and columns swapped (${DIMS[col]} now on rows).`);
  };
  const applyFilter = (dim, vals) => {
    setFilters((f) => ({ ...f, [dim]: vals }));
    setNote(
      vals.length === 1 ? `Slice: ${DIMS[dim]} = ${vals[0]}.`
        : vals.length > 1 ? `Dice: ${DIMS[dim]} in ${vals.length} members.`
          : `Filter on ${DIMS[dim]} removed.`,
    );
  };
  const reset = () => {
    setRow('year'); setCol(''); setMeasure('revenue'); setFilters({});
    setNote('Reset: showing sales by Year.');
    setPicker({ dim: '', open: false });
  };
  const openPicker = (dim) => { setPicker({ dim, open: true }); setDraft(filters[dim] ?? []); };

  const activeFilters = Object.entries(filters).filter(([, v]) => v.length);
  const colSum = (i) => rows.reduce((a, r) => a + (r.cells[i] ?? 0), 0);

  // ── Chart data (same cube result as the table) ─────────
  const isTime = TIME_DIMS.includes(row);
  const chart = useMemo(() => {
    const shown = isTime ? rows : rows.slice(0, MAX_BARS);
    const cols = result?.columns ?? [];
    // keep the biggest series; fold the remainder into "Other" so stacks stay readable
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
  const seriesKeys = col ? chart.series : ['Total'];
  const canDrill = !!childOf(row);
  const onChartClick = (e) => { if (canDrill && e?.activeLabel) drillInto(e.activeLabel); };

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">OLAP Explorer</div>
          <div className="card-subtitle">Slice, dice, roll-up, drill-down and pivot the sales cube</div>
        </div>
        <button type="button" style={btnStyle()} onClick={reset}>Reset</button>
      </div>

      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Axes */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', alignItems: 'flex-end' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={labelStyle}>Rows</span>
          <select
            style={selectStyle}
            value={row}
            onChange={(e) => {
              const v = e.target.value;
              if (v === col) setCol('');
              setRow(v);
              setNote(`Rows set to ${DIMS[v]}.`);
            }}
          >
            {Object.entries(DIMS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={labelStyle}>Columns (pivot)</span>
          <select
            style={selectStyle}
            value={col}
            onChange={(e) => {
              setCol(e.target.value);
              setNote(e.target.value ? `Columns set to ${DIMS[e.target.value]}.` : 'Columns removed.');
            }}
          >
            <option value="">None</option>
            {Object.entries(DIMS).filter(([k]) => k !== row).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={labelStyle}>Measure</span>
          <select style={selectStyle} value={measure} onChange={(e) => setMeasure(e.target.value)}>
            {Object.entries(MEASURES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </div>

      {/* Operations */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
        <span style={labelStyle}>Operations</span>
        <button
          type="button" style={btnStyle(false, !parentOf(row))} disabled={!parentOf(row)} onClick={rollUp}
          title="Move to the coarser level of the hierarchy"
        >
          ▲ Roll-up{parentOf(row) ? ` to ${DIMS[parentOf(row)]}` : ''}
        </button>
        <button
          type="button" style={btnStyle(false, !childOf(row))} disabled={!childOf(row)} onClick={drillDown}
          title="Move to the finer level of the hierarchy (or click a row name to drill into just that member)"
        >
          ▼ Drill-down{childOf(row) ? ` to ${DIMS[childOf(row)]}` : ''}
        </button>
        <button type="button" style={btnStyle(false, !col)} disabled={!col} onClick={pivot} title="Swap rows and columns">
          ⇄ Pivot
        </button>
        <button
          type="button" style={btnStyle(picker.open)}
          onClick={() => (picker.open ? setPicker({ dim: '', open: false }) : openPicker(row))}
          title="Pick one member to slice, several to dice"
        >
          ▦ Slice / Dice
        </button>
      </div>

      {/* Slice / dice picker */}
      {picker.open && (
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={labelStyle}>Filter dimension</span>
            <select style={selectStyle} value={picker.dim} onChange={(e) => openPicker(e.target.value)}>
              {Object.entries(DIMS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <span style={{ fontSize: '0.72rem', color: 'var(--color-muted)' }}>1 member = slice · several = dice</span>
          </div>
          {members.loading ? (
            <div style={{ fontSize: '0.75rem', color: 'var(--color-muted)' }}>Loading members…</div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', maxHeight: 160, overflowY: 'auto' }}>
              {(members.data?.data ?? []).map((m) => {
                const on = draft.includes(m.label);
                return (
                  <button
                    key={m.label} type="button" style={btnStyle(on)}
                    onClick={() => setDraft((d) => (on ? d.filter((x) => x !== m.label) : [...d, m.label]))}
                  >
                    {on ? '✓ ' : ''}{m.label}
                  </button>
                );
              })}
            </div>
          )}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="button" style={btnStyle(true)}
              onClick={() => { applyFilter(picker.dim, draft); setPicker({ dim: '', open: false }); }}
            >
              Apply
            </button>
            <button type="button" style={btnStyle()} onClick={() => setDraft([])}>Clear selection</button>
          </div>
        </div>
      )}

      {/* Active filters */}
      {activeFilters.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', alignItems: 'center' }}>
          <span style={labelStyle}>Filters</span>
          {activeFilters.map(([d, v]) => (
            <button key={d} type="button" style={btnStyle(true)} title="Remove this filter" onClick={() => applyFilter(d, [])}>
              {DIMS[d]}: {v.length > 2 ? `${v.length} members` : v.join(', ')} ✕
            </button>
          ))}
        </div>
      )}

      <div style={{ fontSize: '0.75rem', color: 'var(--color-muted)' }}>{note}</div>

      {/* Chart */}
      {!cube.error && (
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, padding: '0.75rem 0.5rem 0.25rem', background: 'var(--color-surface-2)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 0.5rem 0.5rem', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span style={labelStyle}>
              {MEASURES[measure]} by {DIMS[row]}{col ? ` × ${DIMS[col]}` : ''}
              {canDrill ? ' · click a bar to drill down' : ''}
            </span>
            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <button type="button" style={btnStyle(chartType === 'bar')} onClick={() => setChartType('bar')}>Bars</button>
              <button type="button" style={btnStyle(chartType === 'line')} onClick={() => setChartType('line')}>Lines</button>
            </div>
          </div>
          {cube.loading && !result ? (
            <div className="skeleton" style={{ height: 300, borderRadius: 6 }} />
          ) : chart.data.length === 0 ? (
            <div className="empty-state" style={{ minHeight: 200 }}>No data available for this view.</div>
          ) : (
            <div style={{ opacity: cube.loading ? 0.5 : 1 }}>
              <ResponsiveContainer width="100%" height={320}>
                {chartType === 'bar' ? (
                  <BarChart data={chart.data} margin={{ top: 5, right: 15, left: 0, bottom: 5 }} onClick={onChartClick} style={{ cursor: canDrill ? 'pointer' : 'default' }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
                    <XAxis
                      dataKey="label" stroke="#8b90a8" fontSize={10} tickLine={false} axisLine={{ stroke: '#2d3147' }}
                      interval={0} angle={chart.data.length > 8 ? -30 : 0} textAnchor={chart.data.length > 8 ? 'end' : 'middle'}
                      height={chart.data.length > 8 ? 70 : 30} tickFormatter={(v) => (v.length > 18 ? `${v.slice(0, 17)}…` : v)}
                    />
                    <YAxis stroke="#8b90a8" fontSize={11} tickLine={false} axisLine={false} width={60} tickFormatter={(v) => fmtAxis(measure, v)} />
                    <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(99,102,241,0.08)' }} formatter={(v, n) => [fmtMeasure(measure, v), n]} />
                    {col && <Legend wrapperStyle={{ fontSize: '0.7rem', color: '#8b90a8' }} />}
                    {seriesKeys.map((k, i) => (
                      <Bar
                        key={k} dataKey={k} stackId={col ? 'a' : undefined} fill={PALETTE[i % PALETTE.length]}
                        radius={!col || i === seriesKeys.length - 1 ? [3, 3, 0, 0] : 0} maxBarSize={48}
                      />
                    ))}
                  </BarChart>
                ) : (
                  <LineChart data={chart.data} margin={{ top: 5, right: 15, left: 0, bottom: 5 }} onClick={onChartClick} style={{ cursor: canDrill ? 'pointer' : 'default' }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2d3147" vertical={false} />
                    <XAxis
                      dataKey="label" stroke="#8b90a8" fontSize={10} tickLine={false} axisLine={{ stroke: '#2d3147' }}
                      interval={chart.data.length > 24 ? Math.ceil(chart.data.length / 12) : 0}
                      angle={chart.data.length > 8 ? -30 : 0} textAnchor={chart.data.length > 8 ? 'end' : 'middle'}
                      height={chart.data.length > 8 ? 70 : 30} tickFormatter={(v) => (v.length > 18 ? `${v.slice(0, 17)}…` : v)}
                    />
                    <YAxis stroke="#8b90a8" fontSize={11} tickLine={false} axisLine={false} width={60} tickFormatter={(v) => fmtAxis(measure, v)} />
                    <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [fmtMeasure(measure, v), n]} />
                    {col && <Legend wrapperStyle={{ fontSize: '0.7rem', color: '#8b90a8' }} />}
                    {seriesKeys.map((k, i) => (
                      <Line
                        key={k} type="monotone" dataKey={k} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2}
                        dot={chart.data.length <= 31} activeDot={{ r: 4 }}
                      />
                    ))}
                  </LineChart>
                )}
              </ResponsiveContainer>
              {chart.clipped && (
                <div style={{ fontSize: '0.7rem', color: 'var(--color-muted)', padding: '0 0.5rem 0.5rem' }}>
                  Chart shows the top {MAX_BARS} of {rows.length} rows; the table below lists all of them.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Result */}
      {cube.error ? (
        <div className="error-state" style={{ minHeight: 120 }}>
          <span className="error-icon">⚠</span>
          <span className="error-msg">Unable to load: {cube.error}</span>
          <button className="retry-btn" onClick={cube.refetch}>Retry</button>
        </div>
      ) : (
        <div style={{ overflowX: 'auto', opacity: cube.loading ? 0.5 : 1 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>{DIMS[row]}{childOf(row) ? ' (click to drill)' : ''}</th>
                {columns.map((c) => <th key={c} style={{ textAlign: 'right' }}>{c}</th>)}
                <th style={{ textAlign: 'right' }}>Total</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label}>
                  <td style={{ fontWeight: 600, whiteSpace: 'normal', minWidth: 140 }}>
                    {childOf(row) ? (
                      <button
                        type="button" onClick={() => drillInto(r.label)} title={`Drill into ${r.label}`}
                        style={{ all: 'unset', cursor: 'pointer', color: 'var(--color-accent-light, #818cf8)', textDecoration: 'underline dotted' }}
                      >
                        {r.label}
                      </button>
                    ) : r.label}
                  </td>
                  {r.cells.map((v, i) => (
                    <td
                      key={columns[i]}
                      style={{ textAlign: 'right', background: v != null ? `rgba(99,102,241,${(0.05 + 0.4 * v / max).toFixed(3)})` : 'transparent' }}
                    >
                      {fmtMeasure(measure, v)}
                    </td>
                  ))}
                  <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmtMeasure(measure, r.total)}</td>
                </tr>
              ))}
              {result && (
                <tr>
                  <td style={{ fontWeight: 700 }}>Grand total</td>
                  {columns.map((c, i) => (
                    <td key={c} style={{ textAlign: 'right', fontWeight: 700 }}>{fmtMeasure(measure, colSum(i))}</td>
                  ))}
                  <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmtMeasure(measure, result.grand_total)}</td>
                </tr>
              )}
            </tbody>
          </table>
          {!cube.loading && rows.length === 0 && (
            <div style={{ padding: '1rem', color: 'var(--color-muted)', fontSize: '0.8rem' }}>No data for this selection.</div>
          )}
          {(result?.truncated_rows || result?.truncated_cols) && (
            <div style={{ fontSize: '0.7rem', color: 'var(--color-muted)', marginTop: 6 }}>
              Showing the largest {result.truncated_rows ? '200 rows' : ''}
              {result.truncated_rows && result.truncated_cols ? ' and ' : ''}
              {result.truncated_cols ? '24 columns' : ''}; use slice/dice to narrow.
            </div>
          )}
        </div>
      )}
      </div>
    </div>
  );
}
