/**
 * MedStock API client.
 * All endpoints are read-only GET requests against the local FastAPI backend.
 * Base URL is controlled by VITE_API_URL in the .env file — never hardcoded here.
 */

const BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

/**
 * Core fetch wrapper. Throws an Error with a readable message on non-2xx responses.
 */
async function get(path, params = {}) {
  const url = new URL(BASE + path);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
  });
  const res = await fetch(url.toString());
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

// ── Dashboard ────────────────────────────────────────────
export const fetchDashboardSummary = () => get('/api/dashboard/summary');

// ── Analytics ────────────────────────────────────────────
export const fetchSales = (params = {}) => get('/api/analytics/sales', params);
export const fetchInventory = (params = {}) => get('/api/analytics/inventory', params);
export const fetchBranches = (params = {}) => get('/api/analytics/branches', params);
export const fetchMedicines = (params = {}) => get('/api/analytics/medicines', params);

// ── Decisions ────────────────────────────────────────────
export const fetchActionQueue = (params = {}) => get('/api/decisions/action-queue', params);
export const fetchStockoutRisk = (params = {}) => get('/api/decisions/stockout-risk', params);
export const fetchReorder = (params = {}) => get('/api/decisions/reorder', params);
export const fetchOverstock = (params = {}) => get('/api/decisions/overstock', params);
export const fetchExpiry = (params = {}) => get('/api/decisions/expiry', params);

// ── Mining ───────────────────────────────────────────────
export const fetchAssociationRules = (params = {}) => get('/api/mining/association-rules', params);
export const fetchClusters = (params = {}) => get('/api/mining/clusters', params);
export const fetchAnomalies = (params = {}) => get('/api/mining/anomalies', params);

// ── Forecasts ────────────────────────────────────────────
export const fetchForecasts = (params = {}) => get('/api/forecasts', params);
