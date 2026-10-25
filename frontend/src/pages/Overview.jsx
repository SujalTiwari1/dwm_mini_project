import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { AreaChart, Area, BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import { useFetch } from '../hooks/useFetch';
import { fetchDashboardSummary, fetchSales } from '../api/client';
import { useDataset } from '../context/DatasetContext';
import { fmtINR_SI, fmtNum, fmtUnits, fmtYearMonth } from '../utils/format';

const MEASURES = {
  revenue:      { label: 'Revenue',      key: 'revenue',      fmt: fmtINR_SI },
  units:        { label: 'Units',        key: 'units',        fmt: fmtUnits },
  transactions: { label: 'Transactions', key: 'transactions', fmt: fmtNum },
};

const tooltipStyle = { backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: '0.78rem', color: '#0f172a' };

export default function Overview() {
  const { caps } = useDataset();
  const summary = useFetch(fetchDashboardSummary);
  const sales = useFetch(fetchSales);
  const s = summary.data?.data;

  const [measure, setMeasure] = useState('revenue');
  const [view, setView] = useState('time');      // 'time' | 'category'
  const [chartType, setChartType] = useState('area');
  const m = MEASURES[measure];

  const chartData = useMemo(() => {
    const d = sales.data?.data;
    if (view === 'category') {
      return (d?.category_performance ?? [])
        .map((r) => ({ label: r.category_name, value: r[m.key] }))
        .sort((x, y) => y.value - x.value);
    }
    return (d?.monthly_trend ?? []).map((r) => ({ label: fmtYearMonth(r), value: r[m.key] }));
  }, [sales.data, view, m]);

  // Category names are long: use bars (area/line make no sense across categories)
  const type = view === 'category' ? 'bar' : chartType;

  const toggle = (value, current, set, options) => (
    <div className="btn-toggle-group">
      {options.map(([v, l]) => (
        <button key={v} type="button" className={`btn-toggle ${current === v ? 'active' : ''}`} onClick={() => set(v)}>{l}</button>
      ))}
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div className="hero">
        <h1>Know what sells, and what you’ll need next.</h1>
        <p>
          MedStock turns raw pharmacy sales into a data warehouse you can explore, and uses machine learning
          to forecast how much of each medicine every branch will sell in the coming weeks.
        </p>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Total revenue" value={fmtINR_SI(s?.total_revenue)} accent="green" loading={summary.loading} />
        <KpiCard label="Units sold" value={fmtUnits(s?.total_units_sold)} accent="blue" loading={summary.loading} />
        <KpiCard label="Transactions" value={fmtNum(s?.total_transactions)} accent="purple" loading={summary.loading} />
        <KpiCard label="Avg. bill value" value={fmtINR_SI(s?.average_transaction_value)} accent="amber" loading={summary.loading} />
      </div>

      <ChartCard
        title={`${m.label} ${view === 'category' ? 'by category' : 'over time'}`}
        subtitle={view === 'category' ? 'Which medicine categories drive sales' : 'How sales have moved over time'}
        loading={sales.loading} error={sales.error ? 'Unable to load sales trend.' : null} onRetry={sales.refetch}
        isEmpty={!chartData.length} height={260}
        headerRight={
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {toggle(measure, measure, setMeasure, [['revenue', 'Revenue'], ['units', 'Units'], ['transactions', 'Orders']])}
            {toggle(view, view, setView, [['time', 'Over time'], ['category', 'By category']])}
            {view === 'time' && toggle(chartType, chartType, setChartType, [['area', 'Area'], ['line', 'Line'], ['bar', 'Bars']])}
          </div>
        }
      >
        <ResponsiveContainer width="100%" height={260}>
          {type === 'bar' ? (
            <BarChart data={chartData} margin={{ top: 10, right: 15, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={{ stroke: '#e2e8f0' }} interval={chartData.length > 12 ? 1 : 0} />
              <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} width={60} tickFormatter={m.fmt} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(13,148,136,0.08)' }} formatter={(v) => [m.fmt(v), m.label]} />
              <Bar dataKey="value" fill="#0d9488" radius={[4, 4, 0, 0]} maxBarSize={48} />
            </BarChart>
          ) : type === 'line' ? (
            <LineChart data={chartData} margin={{ top: 10, right: 15, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={{ stroke: '#e2e8f0' }} interval={chartData.length > 12 ? 1 : 0} />
              <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} width={60} tickFormatter={m.fmt} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [m.fmt(v), m.label]} />
              <Line type="monotone" dataKey="value" stroke="#0d9488" strokeWidth={2.5} dot={chartData.length <= 12} />
            </LineChart>
          ) : (
            <AreaChart data={chartData} margin={{ top: 10, right: 15, left: 0, bottom: 5 }}>
              <defs>
                <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#0d9488" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#0d9488" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={{ stroke: '#e2e8f0' }} interval={chartData.length > 12 ? 1 : 0} />
              <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} width={60} tickFormatter={m.fmt} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [m.fmt(v), m.label]} />
              <Area type="monotone" dataKey="value" stroke="#0d9488" strokeWidth={2.5} fill="url(#rev)" />
            </AreaChart>
          )}
        </ResponsiveContainer>
      </ChartCard>

      <div className="tile-grid">
        <Link to="/olap" className="tile">
          <span className="tile-title">Sales Explorer</span>
          <span className="tile-text">Slice your sales by time, branch and medicine in four easy steps.</span>
          <span className="tile-go">Open explorer →</span>
        </Link>
        {caps.forecasting !== false && (
          <Link to="/forecast" className="tile">
            <span className="tile-title">Demand Forecast</span>
            <span className="tile-text">See how many units each branch is expected to sell over 7, 14 and 30 days.</span>
            <span className="tile-go">View forecast →</span>
          </Link>
        )}
        <Link to="/upload" className="tile">
          <span className="tile-title">Use your own data</span>
          <span className="tile-text">Upload a sales file and get the same views for your pharmacy.</span>
          <span className="tile-go">Upload data →</span>
        </Link>
      </div>
    </div>
  );
}
