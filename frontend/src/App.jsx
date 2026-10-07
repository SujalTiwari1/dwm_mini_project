import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import Header   from './components/Header';
import Sidebar  from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Sales from './pages/Sales';
import Inventory from './pages/Inventory';
import PlaceholderPage from './pages/PlaceholderPage';
import { fetchDashboardSummary } from './api/client';
import { fmtDate } from './utils/format';

/**
 * Top-level app shell.
 * Fetches the dashboard summary once at mount to derive the "Data through" badge date.
 * Each page is responsible for its own data fetching.
 */
export default function App() {
  const [badgeDate, setBadgeDate] = useState(null);

  // Fetch once to get the snapshot date for the header badge.
  // The Dashboard page fetches its own copy independently.
  useEffect(() => {
    fetchDashboardSummary()
      .then((res) => {
        const d = res?.data?.inventory_snapshot_date ?? res?.data?.decision_date;
        if (d) setBadgeDate(fmtDate(d));
      })
      .catch(() => {/* ignore — badge is optional */});
  }, []);

  const dataBadge = badgeDate ? `Data through: ${badgeDate}` : null;

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Header dataBadge={dataBadge} />
        <Sidebar />
        <main className="app-main">
          <Routes>
            <Route path="/"           element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard"  element={<Dashboard />} />
            <Route path="/sales"      element={<Sales />} />
            <Route path="/inventory"  element={<Inventory />} />
            <Route path="/forecast"   element={<PlaceholderPage title="Demand & Forecast"  description="ML demand forecasts (7/14/30-day horizons) for each branch and medicine." />} />
            <Route path="/risk"       element={<PlaceholderPage title="Risk & Expiry"      description="Batch-level expiry risk, near-dated stock, prioritize-sale actions." />} />
            <Route path="/insights"   element={<PlaceholderPage title="Insights"           description="Association rules, medicine clusters and anomaly detection results." />} />
            <Route path="/decisions"  element={<PlaceholderPage title="Decisions"          description="Full decision support action queue — reorder, overstock, expiry and stockout risk." />} />
            <Route path="*"           element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
