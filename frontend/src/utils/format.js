/**
 * Number and currency formatting utilities for MedStock (INR, Indian system).
 */

/**
 * Format a number with Indian abbreviations: ₹159.2M, ₹3.64M, ₹211.8K, etc.
 * Used for KPI cards where compactness matters.
 */
export function fmtINR(val) {
  if (val == null || isNaN(val)) return '—';
  const n = Number(val);
  if (n >= 1_00_00_00_000) return `₹${(n / 1_00_00_00_000).toFixed(1)}B`;
  if (n >= 1_00_00_000)   return `₹${(n / 1_00_00_000).toFixed(1)}Cr`;
  if (n >= 1_00_000)       return `₹${(n / 1_00_000).toFixed(2)}L`;
  if (n >= 1_000)          return `₹${(n / 1_000).toFixed(1)}K`;
  return `₹${n.toFixed(2)}`;
}

/**
 * Format using the SI scale (M/K) as per the spec examples.
 * ₹159.2M  ₹3.64M  ₹211.8K
 */
export function fmtINR_SI(val) {
  if (val == null || isNaN(val)) return '—';
  const n = Number(val);
  if (n >= 1_000_000_000) return `₹${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `₹${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `₹${(n / 1_000).toFixed(1)}K`;
  return `₹${n.toFixed(0)}`;
}

/**
 * Format a plain integer/float with Indian comma grouping (no currency symbol).
 */
export function fmtNum(val) {
  if (val == null || isNaN(val)) return '—';
  return Number(val).toLocaleString('en-IN');
}

/**
 * Format a large unit count with abbreviations (no ₹).
 */
export function fmtUnits(val) {
  if (val == null || isNaN(val)) return '—';
  const n = Number(val);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString('en-IN');
}

/**
 * Format a percentage: 12.34 → "12.3%"
 */
export function fmtPct(val, decimals = 1) {
  if (val == null || isNaN(val)) return '—';
  return `${Number(val).toFixed(decimals)}%`;
}

/**
 * Format a date string (YYYY-MM-DD) to "31 Dec 2026".
 */
export function fmtDate(val) {
  if (!val) return '—';
  const d = new Date(val + (val.length === 10 ? 'T00:00:00' : ''));
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

/**
 * Format "2026-01" or {year, month, month_name} → "Jan 2026"
 */
export function fmtYearMonth(item) {
  if (!item) return '';
  if (typeof item === 'string') {
    const [y, m] = item.split('-');
    const d = new Date(Number(y), Number(m) - 1, 1);
    return d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
  }
  const { year, month } = item;
  const d = new Date(Number(year), Number(month) - 1, 1);
  return d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
}
