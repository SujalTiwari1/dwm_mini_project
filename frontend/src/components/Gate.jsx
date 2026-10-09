import { Link } from 'react-router-dom';
import { useDataset } from '../context/DatasetContext';

/**
 * Renders its children only when the selected dataset supports the page; otherwise explains what is missing.
 * need — a key of the dataset's `capabilities` (e.g. "inventory_expiry_decisions", "forecasting").
 */
export default function Gate({ need, title, requirement, children }) {
  const { active, caps, loading } = useDataset();
  if (loading) return null;
  if (caps[need] !== false && caps[need] !== undefined) return children;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div className="page-header">
        <h1 className="page-title">{title}</h1>
      </div>
      <div className="card">
        <div className="card-body" style={{ padding: '2.5rem', textAlign: 'center' }}>
          <div style={{ fontSize: '2rem', color: 'var(--color-border)', marginBottom: '0.6rem' }}>◈</div>
          <div style={{ fontWeight: 600, marginBottom: '0.4rem' }}>Not available for “{active.name}”</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--color-muted)', maxWidth: '460px', margin: '0 auto 1rem' }}>{requirement}</div>
          <Link to="/upload" className="pagination-btn" style={{ textDecoration: 'none', display: 'inline-block' }}>Manage datasets</Link>
        </div>
      </div>
    </div>
  );
}
