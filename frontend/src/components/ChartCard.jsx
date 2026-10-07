/**
 * ChartCard — a card wrapper for Recharts charts.
 * Handles loading skeleton, error state, and empty state.
 *
 * Props:
 *   title       - card heading
 *   subtitle    - optional subheading
 *   loading     - show skeleton
 *   error       - error message string
 *   onRetry     - retry callback
 *   isEmpty     - show empty state
 *   height      - chart container height (default 280)
 *   children    - the actual chart element
 *   headerRight - optional right-aligned header element
 */
export default function ChartCard({
  title,
  subtitle,
  loading = false,
  error = null,
  onRetry,
  isEmpty = false,
  height = 280,
  children,
  headerRight,
}) {
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">{title}</div>
          {subtitle && <div className="card-subtitle">{subtitle}</div>}
        </div>
        {headerRight && <div>{headerRight}</div>}
      </div>
      <div className="card-body" style={{ padding: '1rem 1.25rem' }}>
        {loading ? (
          <div className="skeleton" style={{ height: `${height}px`, width: '100%', borderRadius: '6px' }} />
        ) : error ? (
          <div className="error-state" style={{ minHeight: `${height}px` }}>
            <span className="error-icon">⚠</span>
            <span className="error-msg">{error}</span>
            {onRetry && <button className="retry-btn" onClick={onRetry}>Retry</button>}
          </div>
        ) : isEmpty ? (
          <div className="empty-state" style={{ minHeight: `${height}px` }}>
            No data available for this view.
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
