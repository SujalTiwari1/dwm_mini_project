import { fmtDate } from '../utils/format';

/**
 * Top application header bar.
 * dataBadge — string shown in the top-right badge (e.g. "Data through: 31 Dec 2026")
 */
export default function Header({ dataBadge }) {
  return (
    <header className="app-header">
      <div className="app-header-brand">
        <span className="brand-name">MedStock</span>
        <span className="brand-sub">Pharmacy Inventory Intelligence</span>
      </div>
      <div className="header-spacer" />
      {dataBadge && (
        <span className="header-badge">{dataBadge}</span>
      )}
    </header>
  );
}
