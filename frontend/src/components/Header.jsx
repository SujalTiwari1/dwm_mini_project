import { useDataset } from '../context/DatasetContext';

/**
 * Top application header bar.
 * dataBadge — string shown in the top-right badge (e.g. "Data through: 31 Dec 2026")
 * The dataset selector switches every page between the demo dataset and the user's uploads.
 */
export default function Header({ dataBadge }) {
  const { datasets, activeId, select } = useDataset();
  return (
    <header className="app-header">
      <div className="app-header-brand">
        <span className="brand-name">MedStock</span>
        <span className="brand-sub">Pharmacy Inventory Intelligence</span>
      </div>
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
    </header>
  );
}
