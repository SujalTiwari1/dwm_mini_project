import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link } from 'react-router-dom';

import Header   from './components/Header';
import Sidebar  from './components/Sidebar';
import Gate from './components/Gate';
import Dashboard from './pages/Dashboard';
import Sales from './pages/Sales';
import Inventory from './pages/Inventory';
import Risk from './pages/Risk';
import Insights from './pages/Insights';
import Decisions from './pages/Decisions';
import Forecast from './pages/Forecast';
import Upload from './pages/Upload';
import { DatasetProvider, useDataset } from './context/DatasetContext';
import { fetchDashboardSummary } from './api/client';
import { fmtDate } from './utils/format';

const NEEDS_INVENTORY = 'Upload purchase and batch (expiry) data together with your sales to unlock inventory, expiry-risk and decision-support views. The demo dataset includes them.';

const NEEDS_DECISIONS = 'Decision support and risk views need a purchases file with your sales and at least 180 days of sales history (they use the demand forecast). The demo dataset includes both.';

/** Shown on every page while an uploaded dataset is selected. */
function DatasetNotice() {
  const { active } = useDataset();
  if (active.built_in) return null;
  const running = active.status === 'queued' || active.status === 'running';
  return (
    <div style={{
      background: 'rgba(56, 189, 248, 0.08)', border: '1px solid rgba(56, 189, 248, 0.25)', borderRadius: 'var(--radius)',
      padding: '0.55rem 1rem', fontSize: '0.75rem', color: '#bae6fd', marginBottom: '1rem',
    }}>
      Viewing your uploaded dataset <strong>{active.name}</strong>.{' '}
      {running ? 'Analysis is still running — some pages may be incomplete. '
        : !active.capabilities?.inventory_expiry_decisions ? 'Sections that need stock, purchase or expiry data are unavailable (add a purchases file to unlock them). '
        : active.capabilities?.expiry_risk === false ? 'No expiry dates were provided, so expiry-risk results are unavailable. '
        : 'Stock levels are rebuilt from your purchases and sales. '}
      <Link to="/upload" style={{ color: '#e0f2fe', textDecoration: 'underline' }}>Manage datasets</Link>
    </div>
  );
}

/**
 * Top-level app shell.
 * Pages re-mount (key) whenever the selected dataset changes, so every page refetches for the new dataset.
 */
function Shell() {
  const { activeId, active } = useDataset();
  const [badgeDate, setBadgeDate] = useState(null);

  useEffect(() => {
    setBadgeDate(null);
    if (!active.built_in) return;
    fetchDashboardSummary()
      .then((res) => {
        const d = res?.data?.inventory_snapshot_date ?? res?.data?.decision_date;
        if (d) setBadgeDate(fmtDate(d));
      })
      .catch(() => {/* ignore — badge is optional */});
  }, [activeId, active.built_in]);

  const upload = active.validation;
  const dataBadge = active.built_in
    ? (badgeDate ? `Data through: ${badgeDate}` : null)
    : (upload?.date_to ? `Sales through: ${fmtDate(upload.date_to)}` : null);

  return (
    <div className="app-shell">
      <Header dataBadge={dataBadge} />
      <Sidebar />
      <main className="app-main" key={activeId}>
        <DatasetNotice />
        <Routes>
          <Route path="/"           element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard"  element={<Dashboard />} />
          <Route path="/sales"      element={<Sales />} />
          <Route path="/inventory"  element={<Gate need="inventory_expiry_decisions" title="Inventory" requirement={NEEDS_INVENTORY}><Inventory /></Gate>} />
          <Route path="/forecast"   element={<Gate need="forecasting" title="Demand & Forecast" requirement="Forecasting needs at least 180 days of sales history. Upload a longer sales extract."><Forecast /></Gate>} />
          <Route path="/risk"       element={<Gate need="decision_support" title="Risk & Expiry" requirement={NEEDS_DECISIONS}><Risk /></Gate>} />
          <Route path="/insights"   element={<Insights />} />
          <Route path="/decisions"  element={<Gate need="decision_support" title="Decision Support" requirement={NEEDS_DECISIONS}><Decisions /></Gate>} />
          <Route path="/upload"     element={<Upload />} />
          <Route path="*"           element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <DatasetProvider>
        <Shell />
      </DatasetProvider>
    </BrowserRouter>
  );
}
