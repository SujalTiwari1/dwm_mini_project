import { useDataset } from '../context/DatasetContext';
import { useAuth } from '../context/AuthContext';

/**
 * Top application header bar.
 * dataBadge — string shown in the top-right badge (e.g. "Data through: 31 Dec 2026")
 * The dataset selector switches every page between the demo dataset and the user's uploads.
 */
export default function Header({ dataBadge }) {
  const { datasets, activeId, select } = useDataset();
  const { role, logout } = useAuth();
  return (
    <header className="app-header">
      <img
        src="/MedStock%20Pharmacy%20Analytics%20Logo.png"
        alt="MedStock — Pharmacy sales & demand analytics"
        style={{ height: '48px', width: 'auto', display: 'block' }}
      />
      <div className="header-spacer" />
      <select
        className="filter-select"
        aria-label="Dataset"
        value={activeId}
        onChange={(e) => select(e.target.value)}
        style={{ maxWidth: '240px' }}
      >
        {datasets.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}{!d.built_in && d.status && d.status !== 'ready' ? ` (${d.status.replace(/_/g, ' ')})` : ''}
          </option>
        ))}
      </select>
      {dataBadge && (
        <span className="header-badge">{dataBadge}</span>
      )}
      <span className="header-badge" style={{ textTransform: 'capitalize' }}>{role}</span>
      <button className="filter-select" onClick={logout} style={{ cursor: 'pointer' }}>Logout</button>
    </header>
  );
}
