/**
 * KpiCard — a single KPI metric tile.
 * Props:
 *   label     - short uppercase label
 *   value     - formatted value string (e.g. "₹159.2M")
 *   note      - optional footnote
 *   accent    - "green" | "blue" | "purple" | "amber" | "red"
 *   loading   - show skeleton when true
 */
export default function KpiCard({ label, value, note, accent = 'blue', loading = false }) {
  return (
    <div className={`kpi-card kpi-accent-${accent}`}>
      <div className="kpi-label">{label}</div>
      {loading ? (
        <div className="skeleton" style={{ height: '2rem', width: '70%', borderRadius: '4px' }} />
      ) : (
        <div className="kpi-value">{value ?? '—'}</div>
      )}
      {note && <div className="kpi-note">{note}</div>}
    </div>
  );
}
