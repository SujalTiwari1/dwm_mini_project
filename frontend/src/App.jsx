import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link } from 'react-router-dom';

import Header   from './components/Header';
import Sidebar  from './components/Sidebar';
import Gate from './components/Gate';
import Overview from './pages/Overview';
import Olap from './pages/Olap';
import Forecast from './pages/Forecast';
import Mining from './pages/Mining';
import Upload from './pages/Upload';
import Models from './pages/Models';
import Login from './pages/Login';
import { AuthProvider, useAuth } from './context/AuthContext';
import { DatasetProvider, useDataset } from './context/DatasetContext';
import { fetchDashboardSummary } from './api/client';
import { fmtDate } from './utils/format';

/** Shown on every page while an uploaded dataset is selected. */
function DatasetNotice() {
  const { active } = useDataset();
  if (active.built_in) return null;
  const running = active.status === 'queued' || active.status === 'running';
  return (
    <div style={{
      background: 'rgba(2, 132, 199, 0.07)', border: '1px solid rgba(2, 132, 199, 0.25)', borderRadius: 'var(--radius)',
      padding: '0.55rem 1rem', fontSize: '0.75rem', color: '#075985', marginBottom: '1rem',
    }}>
      Viewing your uploaded dataset <strong>{active.name}</strong>.{' '}
      {running ? 'Analysis is still running — some pages may be incomplete. '
        : ''}
      <Link to="/upload" style={{ color: '#075985', textDecoration: 'underline' }}>Manage datasets</Link>
    </div>
  );
}

/**
 * Top-level app shell.
 * Pages re-mount (key) whenever the selected dataset changes, so every page refetches for the new dataset.
 */
function Shell() {
  const { activeId, active } = useDataset();
  const { isAdmin } = useAuth();
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
          <Route path="/"          element={<Navigate to="/overview" replace />} />
          <Route path="/overview"  element={<Overview />} />
          <Route path="/olap"      element={<Olap />} />
          <Route path="/forecast"  element={<Gate need="forecasting" title="Demand Forecast" requirement="Forecasting needs at least 180 days of sales history. Upload a longer sales extract."><Forecast /></Gate>} />
          <Route path="/mining"    element={isAdmin ? <Mining /> : <Navigate to="/overview" replace />} />
          <Route path="/models"    element={isAdmin ? <Models /> : <Navigate to="/overview" replace />} />
          <Route path="/upload"   element={<Upload />} />
          <Route path="*"          element={<Navigate to="/overview" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function AuthGate() {
  const { role } = useAuth();
  if (!role) return <Login />;
  return (
    <DatasetProvider>
      <Shell />
    </DatasetProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AuthGate />
      </AuthProvider>
    </BrowserRouter>
  );
}
