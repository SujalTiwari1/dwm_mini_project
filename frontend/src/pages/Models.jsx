import { useMemo, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import { useFetch } from '../hooks/useFetch';
import { fetchModelComparison, fetchMiningModels, fetchDecisionSummary } from '../api/client';
import { fmtNum } from '../utils/format';

const tooltipStyle = { backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: '0.78rem', color: '#0f172a' };
const HORIZON_COLORS = { 7: '#0d9488', 14: '#3b82f6', 30: '#8b5cf6' };

const MODEL_INFO = {
  naive: ['Naive', 'Repeats the last observed value.'],
  moving_average_7: ['Moving average (7d)', 'Mean of the last 7 days.'],
  moving_average_28: ['Moving average (28d)', 'Mean of the last 28 days.'],
  seasonal_naive_weekly: ['Seasonal naive (weekly)', 'Repeats the value from the same weekday last week.'],
  seasonal_naive_yearly: ['Seasonal naive (yearly)', 'Repeats the value from the same day last year.'],
  ml_selected: ['Gradient boosting (ML)', 'HistGradientBoostingRegressor trained on lag, rolling, stock and calendar features.'],
};
const modelName = (m) => MODEL_INFO[m]?.[0] ?? m;
const pct = (v) => (v == null ? '–' : `${(v * 100).toFixed(1)}%`);
const num = (v, d = 2) => (v == null ? '–' : Number(v).toFixed(d));
const axis = { stroke: '#94a3b8', fontSize: 11, tickLine: false };

// A 404 means the report was never generated for the selected (uploaded) dataset: not a failure, so no retry.
const unavailable = (err, fallback, why) => (err ? (err.status === 404 ? `Not available for the selected dataset${why ? ` — ${why}` : ''}. Switch to the demo dataset to see it.` : fallback) : null);
const retryable = (err, retry) => (err && err.status !== 404 ? retry : undefined);

function Section({ title, children }) {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <h2 style={{ fontSize: '1.05rem', fontWeight: 700, margin: 0 }}>{title}</h2>
      {children}
    </section>
  );
}

function Note({ children }) {
  return <p style={{ fontSize: '0.78rem', color: 'var(--color-muted)', margin: 0 }}>{children}</p>;
}

function ForecastSection() {
  const cmp = useFetch(fetchModelComparison);
  const [horizon, setHorizon] = useState(7);
  const d = cmp.data;

  const rows = useMemo(() => (d?.models ?? [])
    .filter((r) => r.horizon === horizon)
    .sort((a, b) => a.WAPE - b.WAPE), [d, horizon]);
  const chart = useMemo(() => {
    const byModel = {};
    (d?.models ?? []).forEach((r) => {
      byModel[r.model] ??= { name: modelName(r.model) };
      byModel[r.model][`h${r.horizon}`] = +(r.WAPE * 100).toFixed(1);
    });
    return Object.values(byModel);
  }, [d]);
  const best = rows[0];
  const cfg = d?.selected_model_config;

  return (
    <Section title="1 · Demand forecasting models">
      <Note>
        Six forecasting models compared on the held-out test period (chronological split, no random splitting).
        Lower WAPE / MAE / RMSE / MASE is better; MASE below 1 beats a naive forecast.
      </Note>
      <div className="kpi-grid">
        <KpiCard label="Models compared" value={fmtNum(Object.keys(MODEL_INFO).length)} accent="blue" loading={cmp.loading} />
        <KpiCard label={`Best at ${horizon}-day`} value={best ? modelName(best.model) : '–'} accent="green" loading={cmp.loading} />
        <KpiCard label="Best WAPE" value={best ? pct(best.WAPE) : '–'} accent="purple" loading={cmp.loading} />
        <KpiCard label="Selected model" value={d?.selected_model ? 'Gradient boosting' : '–'} accent="amber" loading={cmp.loading} />
      </div>

      <ChartCard title="Forecast error by model (WAPE %)" subtitle="Lower is better" loading={cmp.loading}
        error={unavailable(cmp.error, 'Unable to load model comparison.')} onRetry={retryable(cmp.error, cmp.refetch)} isEmpty={!chart.length} height={300}>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chart} margin={{ top: 10, right: 15, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="name" {...axis} axisLine={{ stroke: '#e2e8f0' }} interval={0} />
            <YAxis {...axis} axisLine={false} width={45} tickFormatter={(v) => `${v}%`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [`${v}%`, n]} />
            <Legend />
            {[7, 14, 30].map((h) => <Bar key={h} dataKey={`h${h}`} name={`${h}-day`} fill={HORIZON_COLORS[h]} radius={[3, 3, 0, 0]} maxBarSize={22} />)}
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="Leaderboard" subtitle="Test period, all samples" loading={cmp.loading} error={unavailable(cmp.error, 'Unable to load.')}
        isEmpty={!rows.length} height={260}
        headerRight={
          <div className="btn-toggle-group">
            {[7, 14, 30].map((h) => (
              <button key={h} type="button" className={`btn-toggle ${horizon === h ? 'active' : ''}`} onClick={() => setHorizon(h)}>{h}-day</button>
            ))}
          </div>
        }>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead><tr><th>#</th><th>Model</th><th>How it works</th><th>WAPE</th><th>MAE</th><th>RMSE</th><th>MASE</th><th>Bias</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.model} style={r.model === 'ml_selected' ? { fontWeight: 600 } : undefined}>
                  <td>{i + 1}</td>
                  <td>{modelName(r.model)}{r.model === 'ml_selected' && <span className="badge badge-low" style={{ marginLeft: 6 }}>ML</span>}</td>
                  <td style={{ color: 'var(--color-muted)', fontWeight: 400 }}>{MODEL_INFO[r.model]?.[1]}</td>
                  <td>{pct(r.WAPE)}</td><td>{num(r.MAE)}</td><td>{num(r.RMSE)}</td><td>{num(r.MASE)}</td><td>{num(r.bias_pct, 1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartCard>

      <div className="tile-grid">
        <ChartCard title="What drives the ML forecast" subtitle="Top features by importance" loading={cmp.loading}
          isEmpty={!d?.feature_importance?.length} height={280}>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={d?.feature_importance ?? []} layout="vertical" margin={{ top: 5, right: 15, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis type="number" {...axis} axisLine={{ stroke: '#e2e8f0' }} />
              <YAxis type="category" dataKey="feature" {...axis} axisLine={false} width={150} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="importance" fill="#0d9488" radius={[0, 3, 3, 0]} maxBarSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Selected model configuration" loading={cmp.loading} isEmpty={!cfg} height={200}>
          <table className="data-table">
            <tbody>
              <tr><td>Algorithm</td><td>{d?.selected_model}</td></tr>
              <tr><td>Loss</td><td>{cfg?.loss}</td></tr>
              <tr><td>Target transform</td><td>{cfg?.target_transform}</td></tr>
              {Object.entries(cfg?.params ?? {}).map(([k, v]) => <tr key={k}><td>{k}</td><td>{String(v)}</td></tr>)}
              <tr><td>Train period</td><td>{d?.split_dates?.train?.join(' → ')}</td></tr>
              <tr><td>Test period</td><td>{d?.split_dates?.test?.join(' → ')}</td></tr>
            </tbody>
          </table>
        </ChartCard>
      </div>
    </Section>
  );
}

function MiningSection() {
  const mining = useFetch(fetchMiningModels);
  const m = mining.data;
  const evaluation = m?.clustering?.evaluation ?? [];
  const chosen = evaluation.find((r) => r.selected);
  const detectors = Object.entries(m?.anomaly?.detectors ?? {});
  const a = m?.association;
  const DET = { statistical: 'Statistical (robust z-score)', isolation_forest: 'Isolation Forest', combined_both_methods: 'Both methods agree', either_method: 'Either method' };

  return (
    <Section title="2 · Data mining models">
      <Note>Three unsupervised techniques run on the warehouse. Figures come from the stored mining reports.</Note>

      <ChartCard title="K-Means clustering of medicines" loading={mining.loading} error={unavailable(mining.error, 'Unable to load mining summary.', 'needs transaction IDs in the upload')}
        onRetry={retryable(mining.error, mining.refetch)} isEmpty={!evaluation.length} height={240}
        subtitle={chosen ? `k = ${chosen.k} chosen (silhouette ${num(chosen.silhouette, 3)}, Davies–Bouldin ${num(chosen.davies_bouldin, 3)})` : undefined}>
        <div className="tile-grid">
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead><tr><th>k</th><th>Inertia</th><th>Silhouette</th><th>Calinski–H.</th><th>Davies–B.</th></tr></thead>
              <tbody>
                {evaluation.map((r) => (
                  <tr key={r.k} style={r.selected ? { fontWeight: 600, background: 'var(--color-surface-2)' } : undefined}>
                    <td>{r.k}{r.selected && ' ✓'}</td><td>{fmtNum(Math.round(r.inertia))}</td><td>{num(r.silhouette, 3)}</td>
                    <td>{num(r.calinski_harabasz, 1)}</td><td>{num(r.davies_bouldin, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <table className="data-table">
            <thead><tr><th>Cluster</th><th>Medicines</th><th>Profile</th><th>Units share</th></tr></thead>
            <tbody>
              {(m?.clustering?.clusters ?? []).map((c) => (
                <tr key={c.cluster_id}><td>{c.cluster_id}</td><td>{c.medicine_count}</td><td>{c.label}</td><td>{num(c.share_of_units_pct, 1)}%</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartCard>

      <div className="kpi-grid">
        <KpiCard label="Apriori · transactions" value={fmtNum(a?.transactions)} accent="blue" loading={mining.loading} />
        <KpiCard label="Frequent itemsets" value={fmtNum(a?.frequent_itemsets)} accent="green" loading={mining.loading} />
        <KpiCard label="Association rules" value={fmtNum(a?.useful_rules_after_filter)} accent="purple" loading={mining.loading} />
        <KpiCard label="Min support / conf." value={a ? `${+(a.min_support * 100).toFixed(2)}% / ${+(a.min_confidence * 100).toFixed(0)}%` : '–'} accent="amber" loading={mining.loading} />
      </div>

      <ChartCard title="Anomaly detection" loading={mining.loading} isEmpty={!detectors.length} height={200}
        subtitle={`Checked after the fact against ${m?.anomaly?.ground_truth_events ?? '–'} injected synthetic events (not used as model input)`}>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead><tr><th>Detector</th><th>Rows flagged</th><th>Events found</th><th>Recall</th><th>Precision</th><th>F1</th></tr></thead>
            <tbody>
              {detectors.map(([k, v]) => (
                <tr key={k}><td>{DET[k] ?? k}</td><td>{fmtNum(v.flagged_rows)}</td><td>{v.events_detected_strict} / {v.events_total}</td>
                  <td>{pct(v.recall_event_level_strict)}</td><td>{pct(v.precision_episode_level)}</td><td>{num(v.f1, 3)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartCard>
    </Section>
  );
}

function DecisionSection() {
  const dec = useFetch(fetchDecisionSummary);
  const s = dec.data;
  const asm = s?.configuration?.planning_assumptions_not_in_dataset;
  return (
    <Section title="3 · Decision-support rules">
      <Note>Rule-based scoring on top of the forecasts, not a trained model. It turns forecast demand and current stock into priorities.</Note>
      <div className="kpi-grid">
        <KpiCard label="Critical priority" value={fmtNum(s?.critical_count)} accent="red" loading={dec.loading} />
        <KpiCard label="High priority" value={fmtNum(s?.high_count)} accent="amber" loading={dec.loading} />
        <KpiCard label="Order now" value={fmtNum(s?.order_now_count)} accent="blue" loading={dec.loading} />
        <KpiCard label="Overstocked pairs" value={fmtNum(s?.overstock_count)} accent="purple" loading={dec.loading} />
      </div>
      <ChartCard title="Planning assumptions" subtitle={s ? `${fmtNum(s.total_branch_medicine_pairs)} branch–medicine pairs assessed on ${s.decision_date}` : undefined}
        loading={dec.loading} error={unavailable(dec.error, 'Unable to load decision summary.', 'needs inventory and expiry data')} onRetry={retryable(dec.error, dec.refetch)} isEmpty={!asm} height={160}>
        <table className="data-table">
          <tbody>{Object.entries(asm ?? {}).map(([k, v]) => <tr key={k}><td>{k.replace(/_/g, ' ')}</td><td>{String(v)}</td></tr>)}</tbody>
        </table>
      </ChartCard>
    </Section>
  );
}

export default function Models() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      <div className="page-header">
        <h1 className="page-title">Models</h1>
        <p style={{ margin: 0, color: 'var(--color-muted)', fontSize: '0.85rem' }}>Every model and algorithm used in this project, and how well each performs.</p>
      </div>
      <ForecastSection />
      <MiningSection />
      <DecisionSection />
    </div>
  );
}
