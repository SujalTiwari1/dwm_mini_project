/**
 * PlaceholderPage — used for pages not yet implemented.
 * Shows the page name and a "coming next" note.
 */
export default function PlaceholderPage({ title, description }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div className="page-header">
        <div className="page-title">{title}</div>
        <div className="page-subtitle">{description ?? 'This section will be implemented in the next phase.'}</div>
      </div>
      <div className="card">
        <div className="card-body" style={{ padding: '3rem', textAlign: 'center' }}>
          <div style={{ fontSize: '2rem', marginBottom: '0.75rem', color: 'var(--color-border)' }}>◈</div>
          <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-text)', marginBottom: '0.4rem' }}>
            Coming next
          </div>
          <div style={{ fontSize: '0.8rem', color: 'var(--color-muted)', maxWidth: '360px', margin: '0 auto' }}>
            Navigate to <strong style={{ color: 'var(--color-accent-light)' }}>Dashboard</strong> to explore the fully implemented
            analytics overview.
          </div>
        </div>
      </div>
    </div>
  );
}
