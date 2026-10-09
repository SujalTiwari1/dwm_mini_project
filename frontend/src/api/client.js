/**
 * MedStock API client.
 * All endpoints are read-only GET requests against the local FastAPI backend.
 * Base URL is controlled by VITE_API_URL in the .env file — never hardcoded here.
 */

const BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

// ── Active dataset ───────────────────────────────────────
// Every data request carries the selected dataset in an X-Dataset-Id header (the built-in demo dataset needs none).
export const DEMO_DATASET = 'demo';
const STORAGE_KEY = 'medstock.dataset';
let activeDataset = DEMO_DATASET;
try { activeDataset = localStorage.getItem(STORAGE_KEY) || DEMO_DATASET; } catch { /* storage unavailable */ }

export const getActiveDataset = () => activeDataset;
export function setActiveDataset(id) {
  activeDataset = id || DEMO_DATASET;
  try { localStorage.setItem(STORAGE_KEY, activeDataset); } catch { /* ignore */ }
}

/**
 * Core fetch wrapper. Throws an Error with a readable message on non-2xx responses.
 * `scoped: false` is used by the dataset-management calls, which must not depend on the selected dataset.
 * Validation failures (422) expose the list of user-facing problems as `error.messages`.
 */
async function request(path, { params = {}, method = 'GET', body, scoped = true } = {}) {
  const url = new URL(BASE + path);
  Object.entries(params).forEach(([k, v]) => {
    if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, x));
    else if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
  });
  const headers = scoped && activeDataset !== DEMO_DATASET ? { 'X-Dataset-Id': activeDataset } : {};
  const res = await fetch(url.toString(), { method, headers, body });
  if (!res.ok) {
    let detail = res.statusText;
    let messages = null;
    try {
      const d = (await res.json()).detail;
      if (d?.messages) { messages = d.messages; detail = d.messages.join(' '); } else if (d) detail = d;
    } catch { /* ignore */ }
    const err = new Error(`${res.status}: ${detail}`);
    err.status = res.status;
    err.messages = messages;
    throw err;
  }
  return res.json();
}

const get = (path, params = {}) => request(path, { params });

// ── Datasets (upload) ────────────────────────────────────
export const TEMPLATE_URL = `${BASE}/api/datasets/template/sales`;
export const PURCHASES_TEMPLATE_URL = `${BASE}/api/datasets/template/purchases`;
export const fetchDatasets = () => request('/api/datasets', { scoped: false });
export const fetchDataset = (id) => request(`/api/datasets/${id}`, { scoped: false });
export const deleteDataset = (id) => request(`/api/datasets/${id}`, { method: 'DELETE', scoped: false });
export function previewFile(file, kind = 'sales') {
  const fd = new FormData();
  fd.append('file', file);
  return request('/api/datasets/preview', { method: 'POST', body: fd, params: { kind }, scoped: false });
}
export function createDataset({ file, name, mapping, purchases, purchasesMapping }) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('name', name ?? '');
  fd.append('mapping', JSON.stringify(mapping ?? {}));
  if (purchases) {
    fd.append('purchases', purchases);
    fd.append('purchases_mapping', JSON.stringify(purchasesMapping ?? {}));
  }
  return request('/api/datasets', { method: 'POST', body: fd, scoped: false });
}

// ── Dashboard ────────────────────────────────────────────
export const fetchDashboardSummary = () => get('/api/dashboard/summary');

// ── Analytics ────────────────────────────────────────────
export const fetchSales = (params = {}) => get('/api/analytics/sales', params);
export const fetchOlap = (params = {}) => get('/api/analytics/olap', params);
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
