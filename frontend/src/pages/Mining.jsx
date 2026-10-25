import { useState, useMemo } from 'react';
import { Navigate } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import { useFetch } from '../hooks/useFetch';
import { useAuth } from '../context/AuthContext';
import { fetchAssociationRules, fetchClusters, fetchMiningModels } from '../api/client';
import { fmtNum, fmtPct, fmtINR } from '../utils/format';

/* ── colour palette ────────────────────────────────────── */
const LIFT_COLORS = [
  '#115e59', '#0f766e', '#0d9488', '#14b8a6',
  '#0e7490', '#0369a1', '#4f46e5', '#7c3aed',
];
const CLUSTER_COLORS = ['#0d9488', '#6366f1', '#f59e0b', '#ef4444'];
const tooltipStyle = {
  backgroundColor: '#fff', border: '1px solid #e2e8f0',
  borderRadius: 8, fontSize: '0.78rem', color: '#0f172a',
};

/* ── helpers ────────────────────────────────────────────── */
/** Strip "[MED020]" from medicine name */
function shortMed(name) {
  if (!name) return '';
  return name.replace(/\s*\[MED\d+\]/, '');
}

/** Extract the MED code like [MED020] */
function medCode(name) {
  return name?.match(/\[MED\d+\]/)?.[0] ?? '';
}

/** Clean, punchy cluster title */
function clusterTitle(c) {
  if (c.cluster_id === 0) return 'High Demand & Volume';
  if (c.cluster_id === 1) return 'High-Price Tier';
  if (c.cluster_id === 2) return 'Budget & Steady';
  if (c.cluster_id === 3) return 'Low-Volume & Expiry Risk';
  if (!c.label) return `Cluster ${c.cluster_id}`;
  return c.label.split(',')[0].trim().replace(/\b\w/g, (l) => l.toUpperCase());
}


/* ================================================================
   1 — ASSOCIATION RULES  (Apriori)
   ================================================================ */
function AssociationSection({ rules, loading, error, refetch }) {
  const [metric, setMetric] = useState('lift');
  const [search, setSearch] = useState('');
  const [sortDir, setSortDir] = useState('desc');

  /* filter + sort for the table */
  const filtered = useMemo(() => {
    if (!rules) return [];
    let list = [...rules];
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (r) => r.antecedent.toLowerCase().includes(q) || r.consequent.toLowerCase().includes(q),
      );
    }
    list.sort((a, b) => sortDir === 'desc' ? b[metric] - a[metric] : a[metric] - b[metric]);
    return list;
  }, [rules, search, metric, sortDir]);

  /* bar chart: one bar per unique medicine pair (de-duplicated, top 8) */
  const barData = useMemo(() => {
    if (!rules) return [];
    const seen = new Set();
    return rules
      .slice()
      .sort((a, b) => b.lift - a.lift)
      .filter((r) => {
        const key = [r.antecedent, r.consequent].sort().join('|');
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 8)
      .map((r) => ({
        name: `${shortMed(r.antecedent)}  ↔  ${shortMed(r.consequent)}`,
        lift: +r.lift.toFixed(1),
        confidence: +(r.confidence * 100).toFixed(1),
      }))
      .reverse();
  }, [rules]);

  return (
    <section id="mining-association" className="mining-section">
      {/* section heading */}
      <div className="mining-section-head">
        <div className="mining-section-icon" style={{ background: 'linear-gradient(135deg, #0d9488, #06b6d4)' }}>⛓</div>
        <div>
          <h2 className="mining-section-title">Association Rules <span className="mining-tag">Apriori</span></h2>
          <p className="mining-section-sub">
            Medicines frequently purchased together in customer baskets.
          </p>
        </div>
      </div>

      {/* ── horizontal bar chart ─────────────────────────── */}
      <ChartCard
        title="Top Co-Purchase Pairs"
        subtitle="Ranked by co-occurrence strength vs. random chance"
        loading={loading} error={error ? 'Unable to load association rules.' : null} onRetry={refetch}
        isEmpty={!barData.length} height={320}
        headerRight={
          <div className="btn-toggle-group">
            <button type="button" className={`btn-toggle ${metric === 'lift' ? 'active' : ''}`} onClick={() => setMetric('lift')}>Lift</button>
            <button type="button" className={`btn-toggle ${metric === 'confidence' ? 'active' : ''}`} onClick={() => setMetric('confidence')}>Confidence</button>
          </div>
        }
      >
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={barData} layout="vertical" margin={{ top: 8, right: 30, left: 10, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
            <XAxis type="number" stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false}
              tickFormatter={(v) => metric === 'lift' ? `${v}×` : `${v}%`}
            />
            <YAxis type="category" dataKey="name" stroke="#94a3b8" fontSize={10} tickLine={false} axisLine={false} width={230} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(13,148,136,0.06)' }}
              formatter={(v) => [metric === 'lift' ? `${v}×` : `${v}%`, metric === 'lift' ? 'Lift multiplier' : 'Confidence']}
            />
            <Bar dataKey={metric} radius={[0, 6, 6, 0]} maxBarSize={28} animationDuration={800}>
              {barData.map((_, i) => (
                <Cell key={i} fill={LIFT_COLORS[i % LIFT_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      {/* ── detail table ─────────────────────────────────── */}
      <div className="card" style={{ marginTop: '1.5rem' }}>
        {/* table header controls */}
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '0.75rem', padding: '1.25rem 1.5rem' }}>
          <div>
            <div className="card-title">All {filtered.length} Discovered Rules</div>
            <div className="card-subtitle">Ranked by {metric === 'lift' ? 'lift multiplier' : 'confidence percentage'}</div>
          </div>
          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              className="filter-input" placeholder="Search medicine…" value={search}
              onChange={(e) => setSearch(e.target.value)} style={{ minWidth: '180px' }}
            />
            <div className="btn-toggle-group">
              <button type="button" className={`btn-toggle ${metric === 'lift' ? 'active' : ''}`} onClick={() => setMetric('lift')}>Lift</button>
              <button type="button" className={`btn-toggle ${metric === 'confidence' ? 'active' : ''}`} onClick={() => setMetric('confidence')}>Confidence</button>
            </div>
            <button type="button" className="btn" onClick={() => setSortDir((d) => d === 'desc' ? 'asc' : 'desc')}>
              {sortDir === 'desc' ? '↓ Highest' : '↑ Lowest'}
            </button>
          </div>
        </div>

        {/* table body */}
        <div style={{ overflowX: 'auto', padding: '0.5rem 0.75rem' }}>
          {loading ? (
            <div style={{ padding: '2rem' }}>
              <div className="skeleton" style={{ height: '200px', width: '100%', borderRadius: '6px' }} />
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ padding: '0.9rem 1rem' }}>Purchased Medicine</th>
                  <th style={{ padding: '0.9rem 1rem' }}>Co-Purchased</th>
                  <th style={{ textAlign: 'right', padding: '0.9rem 1rem' }}>Support</th>
                  <th style={{ textAlign: 'right', padding: '0.9rem 1rem' }}>Confidence</th>
                  <th style={{ textAlign: 'right', padding: '0.9rem 1rem' }}>Lift</th>
                  <th style={{ textAlign: 'center', padding: '0.9rem 1rem' }}>Affinity</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => (
                  <tr key={i}>
                    <td style={{ padding: '0.85rem 1rem' }}>
                      <span className="med-name">{shortMed(r.antecedent)}</span>
                      <span className="med-code">{medCode(r.antecedent)}</span>
                    </td>
                    <td style={{ padding: '0.85rem 1rem' }}>
                      <span className="med-name">{shortMed(r.consequent)}</span>
                      <span className="med-code">{medCode(r.consequent)}</span>
                    </td>
                    <td style={{ textAlign: 'right', padding: '0.85rem 1rem' }}>
                      <span style={{ fontWeight: 600 }}>{fmtPct(r.support * 100, 2)}</span>
                      <br />
                      <span className="med-code">{fmtNum(r.support_count)} txs</span>
                    </td>
                    <td style={{ textAlign: 'right', padding: '0.85rem 1rem' }}>
                      <span style={{ fontWeight: 600 }}>{fmtPct(r.confidence * 100, 1)}</span>
                    </td>
                    <td style={{ textAlign: 'right', padding: '0.85rem 1rem' }}>
                      <span className="lift-badge">{r.lift.toFixed(2)}×</span>
                    </td>
                    <td style={{ textAlign: 'center', padding: '0.85rem 1rem' }}>
                      {r.reverse_rule_present
                        ? <span className="badge badge-medium">↔ Both ways</span>
                        : <span className="badge badge-low">→ One-way</span>}
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr><td colSpan={6} style={{ textAlign: 'center', padding: '2rem', color: 'var(--color-muted)' }}>No rules match your search.</td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* glossary */}
        <div className="mining-glossary" style={{ margin: '1rem 1.25rem 1.25rem' }}>
          <div className="mining-glossary-title">Rule Metrics Explained</div>
          <div className="mining-glossary-grid">
            <div className="mining-glossary-item">
              <strong>Support</strong>
              <span>Frequency of the pair across all {fmtNum(613027)} transactions.</span>
            </div>
            <div className="mining-glossary-item">
              <strong>Confidence</strong>
              <span>Probability of buying the second medicine given the first.</span>
            </div>
            <div className="mining-glossary-item">
              <strong>Lift</strong>
              <span>Multiplier above random chance (&gt;1× indicates positive affinity).</span>
            </div>
            <div className="mining-glossary-item">
              <strong>Affinity</strong>
              <span>"Both ways" indicates bidirectional purchase affinity.</span>
            </div>
          </div>
          <p className="mining-disclaimer">
            ⚕ Statistical purchase patterns only; does not imply medical substitution or prescription advice.
          </p>
        </div>
      </div>
    </section>
  );
}


/* ================================================================
   2 — MEDICINE CLUSTERS  (K-Means)
   ================================================================ */
function ClustersSection({ clustersData, loading, evaluation }) {
  const summary = clustersData?.summary ?? [];

  /* silhouette chart for k selection */
  const silhouetteData = useMemo(() => {
    if (!evaluation) return [];
    return evaluation.map((e) => ({
      k: `k = ${e.k}`,
      silhouette: +e.silhouette.toFixed(4),
      selected: e.selected,
    }));
  }, [evaluation]);

  return (
    <section id="mining-clusters" className="mining-section">
      <div className="mining-section-head">
        <div className="mining-section-icon" style={{ background: 'linear-gradient(135deg, #6366f1, #a855f7)' }}>◎</div>
        <div>
          <h2 className="mining-section-title">Medicine Segments <span className="mining-tag">K-Means</span></h2>
          <p className="mining-section-sub">
            Medicines grouped into 4 behavioural segments by volume, price, and demand stability.
          </p>
        </div>
      </div>

      {/* ── cluster summary cards ────────────────────────── */}
      <div className="mining-cluster-grid">
        {loading ? (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="mining-cluster-card">
              <div className="skeleton" style={{ height: '140px', borderRadius: '8px' }} />
            </div>
          ))
        ) : summary.map((c, i) => (
          <div key={c.cluster_id} className="mining-cluster-card">
            <div>
              <div className="cluster-card-header">
                <span className="cluster-dot" style={{ background: CLUSTER_COLORS[i % CLUSTER_COLORS.length] }} />
                <span className="cluster-id">Cluster {c.cluster_id}</span>
                <span className="cluster-count">{c.medicine_count} medicines</span>
              </div>
              <div className="cluster-label">{clusterTitle(c)}</div>
              <div className="cluster-stats-row">
                <div className="cluster-stat-pill">
                  <span className="cluster-stat-val">{fmtPct(c.share_of_units_pct)}</span>
                  <span className="cluster-stat-lbl">of total units</span>
                </div>
                <div className="cluster-stat-pill" style={{ marginLeft: 'auto' }}>
                  <span className="cluster-stat-val">{Math.round(c.avg_days_of_inventory ?? 0)}d</span>
                  <span className="cluster-stat-lbl">supply</span>
                </div>
              </div>
            </div>
            <div className="cluster-categories">
              {(c.top_categories ?? '').split(';').slice(0, 3).map((cat, ci) => (
                <span key={ci} className="cluster-cat-chip">{cat.trim()}</span>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* ── charts row ───────────────────────────────────── */}
      <div className="chart-grid">
        {/* choosing K */}
        <ChartCard
          title="How K Was Chosen"
          subtitle="Silhouette score across cluster counts (optimal k = 4)"
          loading={!evaluation} isEmpty={!silhouetteData.length} height={250}
        >
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={silhouetteData} margin={{ top: 15, right: 15, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="k" stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={{ stroke: '#e2e8f0' }} />
              <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} width={45}
                label={{ value: 'Silhouette', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 10 }}
              />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [v.toFixed(4), 'Silhouette']} />
              <Bar dataKey="silhouette" radius={[4, 4, 0, 0]} maxBarSize={38} animationDuration={800}>
                {silhouetteData.map((d, i) => (
                  <Cell
                    key={i}
                    fill={d.selected ? '#6366f1' : 'rgba(99,102,241,0.18)'}
                    stroke={d.selected ? '#4f46e5' : 'transparent'}
                    strokeWidth={d.selected ? 2 : 0}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* segment comparison table */}
        <ChartCard
          title="Segment Comparison"
          subtitle="Operational benchmarks across the 4 clusters"
          loading={loading} isEmpty={!summary.length}
        >
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table" style={{ fontSize: '0.78rem' }}>
              <thead>
                <tr>
                  <th style={{ padding: '0.75rem 0.85rem' }}>Segment</th>
                  <th style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>Medicines</th>
                  <th style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>Vol. Share</th>
                  <th style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>Avg Price</th>
                  <th style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>Stockouts</th>
                  <th style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>Supply Days</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((c, i) => (
                  <tr key={c.cluster_id}>
                    <td style={{ padding: '0.75rem 0.85rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span className="cluster-dot" style={{ background: CLUSTER_COLORS[i % CLUSTER_COLORS.length] }} />
                        <span style={{ fontWeight: 600 }}>{clusterTitle(c)}</span>
                      </div>
                    </td>
                    <td style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>{c.medicine_count}</td>
                    <td style={{ textAlign: 'right', padding: '0.75rem 0.85rem', fontWeight: 600 }}>{fmtPct(c.share_of_units_pct)}</td>
                    <td style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>{fmtINR(c.avg_price)}</td>
                    <td style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>{fmtPct((c.avg_stockout_rate ?? 0) * 100, 1)}</td>
                    <td style={{ textAlign: 'right', padding: '0.75rem 0.85rem' }}>
                      <span className="med-code" style={{ fontWeight: 700, color: 'var(--color-text)' }}>
                        {Math.round(c.avg_days_of_inventory ?? 0)}d
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ChartCard>
      </div>

      {/* explanation footer */}
      <div className="mining-glossary">
        <div className="mining-glossary-title">Key Insights</div>
        <div className="mining-glossary-grid">
          <div className="mining-glossary-item">
            <strong>Optimal K = 4</strong>
            <span>Highest silhouette score confirms 4 distinct behavioural groups without overfitting.</span>
          </div>
          <div className="mining-glossary-item">
            <strong>Inventory Strategy</strong>
            <span>Enables tiered procurement: daily replenishment for Cluster 0 vs. conservative stocking for Cluster 3.</span>
          </div>
        </div>
      </div>
    </section>
  );
}


/* ================================================================
   MAIN PAGE
   ================================================================ */
export default function Mining() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return <Navigate to="/overview" replace />;
  }

  const rules = useFetch(fetchAssociationRules);
  const clusters = useFetch(() => fetchClusters({ limit: 1000 }));
  const models = useFetch(fetchMiningModels);

  const rulesData = rules.data?.data ?? [];
  const clustersPayload = clusters.data ?? {};
  const modelsData = models.data ?? {};

  const assocSummary = modelsData.association ?? {};
  const clusterEvaluation = modelsData.clustering?.evaluation ?? null;
  const clusterCount = modelsData.clustering?.clusters?.length ?? 0;

  return (
    <div className="mining-page">
      {/* ── Hero ────────────────────────────────────────── */}
      <div className="mining-hero">
        <div className="mining-hero-content">
          <h1>Data Mining Insights</h1>
          <p>Co-purchase patterns and medicine behavioural segmentation from 24-month transactions</p>
          <div className="mining-hero-engines">
            <span className="mining-engine-chip">⛓ Apriori Algorithm</span>
            <span className="mining-engine-chip">◎ K-Means Clustering</span>
          </div>
        </div>
        <div className="mining-hero-meta">
          <div className="mining-hero-stat">
            <span className="mining-hero-stat-val">{fmtNum(assocSummary.transactions ?? 613027)}</span>
            <span className="mining-hero-stat-lbl">Transactions Analysed</span>
          </div>
          <div className="mining-hero-stat">
            <span className="mining-hero-stat-val">{assocSummary.unique_medicines ?? 500}</span>
            <span className="mining-hero-stat-lbl">Medicines</span>
          </div>
          <div className="mining-hero-stat">
            <span className="mining-hero-stat-val">24 mo</span>
            <span className="mining-hero-stat-lbl">Data Span</span>
          </div>
        </div>
      </div>

      {/* ── KPI strip ───────────────────────────────────── */}
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <KpiCard
          label="Co-Purchase Rules"
          value={fmtNum(assocSummary.useful_rules_after_filter)}
          accent="green" loading={models.loading}
          note={`All with lift > ${assocSummary.min_lift ?? 1}×`}
        />
        <KpiCard
          label="Frequent Itemsets"
          value={fmtNum(assocSummary.frequent_itemsets)}
          accent="blue" loading={models.loading}
          note={`Min support ${fmtPct((assocSummary.min_support ?? 0.0005) * 100, 2)}`}
        />
        <KpiCard
          label="Medicine Clusters"
          value={clusterCount || '—'}
          accent="purple" loading={models.loading}
          note="Best K by silhouette score"
        />
      </div>

      {/* ── Section 1: Association Rules ──────────────────── */}
      <AssociationSection
        rules={rulesData}
        loading={rules.loading}
        error={rules.error}
        refetch={rules.refetch}
      />

      {/* ── Section 2: Medicine Clusters ─────────────────── */}
      <ClustersSection
        clustersData={clustersPayload}
        loading={clusters.loading}
        evaluation={clusterEvaluation}
      />
      </div>
  );
}
