import OlapExplorer from '../components/OlapExplorer';

export default function Olap() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div className="page-header">
        <h1 className="page-title">Sales Explorer (OLAP)</h1>
        <p className="page-subtitle">
          Answer questions about your sales in four short steps — choose a number, choose how to group it, narrow it down, read the result.
        </p>
      </div>
      <OlapExplorer />
    </div>
  );
}
