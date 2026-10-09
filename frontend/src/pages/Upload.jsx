import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

import { useDataset } from '../context/DatasetContext';
import {
  previewFile, createDataset, fetchDataset, deleteDataset, TEMPLATE_URL, PURCHASES_TEMPLATE_URL,
} from '../api/client';
import { fmtNum, fmtINR, fmtDate } from '../utils/format';

const C_DANGER = '#ef4444';

const FIELD_INFO = {
  transaction_date:   { label: 'Date',                required: true,  hint: 'Sale date, e.g. 2025-03-31' },
  medicine_id:        { label: 'Medicine / product ID', required: true,  hint: 'Code that identifies the item' },
  quantity:           { label: 'Quantity',            required: true,  hint: 'Units sold' },
  unit_selling_price: { label: 'Unit price',          required: true,  hint: 'Selling price per unit (INR)' },
  transaction_id:     { label: 'Bill / transaction ID', required: false, hint: 'Enables “bought together” association rules' },
  branch_id:          { label: 'Branch / store',      required: false, hint: 'Without it all sales are one location' },
  medicine_name:      { label: 'Medicine name',       required: false, hint: 'Display name' },
  category:           { label: 'Category',            required: false, hint: 'Medicine category' },
  discount:           { label: 'Discount',            required: false, hint: 'Discount per line (INR)' },
  total_amount:       { label: 'Line total',          required: false, hint: 'Calculated if missing' },
};
const FIELD_ORDER = Object.keys(FIELD_INFO);

const PURCHASE_INFO = {
  purchase_date:       { label: 'Receipt date',          required: true,  hint: 'Date the stock was received' },
  medicine_id:         { label: 'Medicine / product ID', required: true,  hint: 'Same codes as in the sales file' },
  quantity:            { label: 'Quantity received',     required: true,  hint: 'Units received' },
  unit_purchase_price: { label: 'Unit cost',             required: true,  hint: 'Purchase cost per unit (INR)' },
  expiry_date:         { label: 'Expiry date',           required: false, hint: 'Enables expiry-risk analysis' },
  batch_id:            { label: 'Batch / lot number',    required: false, hint: 'Without it each receipt is its own lot' },
  branch_id:           { label: 'Branch / store',        required: false, hint: 'Required when sales have several branches' },
  supplier:            { label: 'Supplier',              required: false, hint: 'Supplier name' },
};

/** Column-mapping table: one row per MedStock field with a dropdown of the uploaded file's columns. */
function MappingTable({ info, preview, mapping, onChange }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead><tr><th>MedStock field</th><th>Your column</th><th>Notes</th></tr></thead>
        <tbody>
          {Object.keys(info).map((k) => (
            <tr key={k}>
              <td style={{ fontWeight: 600 }}>{info[k].label}{info[k].required && <span style={{ color: C_DANGER }}> *</span>}</td>
              <td>
                <select className="filter-select" value={mapping[k] ?? ''} onChange={(e) => onChange(k, e.target.value)}
                  style={{ borderColor: info[k].required && !mapping[k] ? C_DANGER : undefined }}>
                  <option value="">{info[k].required ? '— choose a column —' : '— not in my file —'}</option>
                  {preview.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </select>
              </td>
              <td style={{ color: '#8b90a8', fontSize: '0.74rem' }}>{info[k].hint}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const STATUS_STYLE = {
  ok:      { icon: '✔', color: '#86efac' },
  failed:  { icon: '✖', color: '#f87171' },
  running: { icon: '◔', color: '#7dd3fc' },
  pending: { icon: '○', color: '#8b90a8' },
  skipped: { icon: '–', color: '#8b90a8' },
};

function StatusBadge({ status }) {
  const cls = status === 'ready' ? 'badge-low' : status === 'ready_with_warnings' ? 'badge-high' : status === 'failed' ? 'badge-critical' : 'badge-medium';
  return <span className={`badge ${cls}`}>{String(status).replace(/_/g, ' ').toUpperCase()}</span>;
}

function Problems({ messages }) {
  if (!messages?.length) return null;
  return (
    <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 'var(--radius)', padding: '0.7rem 1rem', fontSize: '0.78rem', color: '#fca5a5' }}>
      <strong>This file cannot be used yet:</strong>
      <ul style={{ margin: '0.35rem 0 0', paddingLeft: '1.1rem' }}>{messages.map((m, i) => <li key={i}>{m}</li>)}</ul>
    </div>
  );
}

/** Progress and result of one dataset's background pipeline. Polls until the job finishes. */
function Progress({ datasetId, onFinished }) {
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);
  const finished = useRef(false);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const m = await fetchDataset(datasetId);
        if (stop) return;
        setMeta(m);
        if (['ready', 'ready_with_warnings', 'failed'].includes(m.status)) {
          if (!finished.current) { finished.current = true; onFinished?.(m); }
          return;
        }
      } catch (e) {
        if (!stop) setError(e.message);
      }
      if (!stop) setTimeout(tick, 3000);
    };
    tick();
    return () => { stop = true; };
  }, [datasetId, onFinished]);

  if (error && !meta) return <div className="error-state"><span className="error-icon">⚠</span><span className="error-msg">Unable to read progress: {error}</span></div>;
  if (!meta) return <div className="skeleton" style={{ height: '200px', borderRadius: 'var(--radius)' }} />;

  const v = meta.validation ?? {};
  const done = ['ready', 'ready_with_warnings', 'failed'].includes(meta.status);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <StatusBadge status={meta.status} />
        <strong>{meta.name}</strong>
        {!done && <span style={{ fontSize: '0.75rem', color: '#8b90a8' }}>Working… this page updates automatically.</span>}
      </div>
      {meta.error && <Problems messages={[meta.error]} />}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '0.6rem' }}>
        {[
          ['Rows used', `${fmtNum(v.rows_loaded)} of ${fmtNum(v.rows_uploaded)}`],
          ['Period', v.date_from ? `${fmtDate(v.date_from)} – ${fmtDate(v.date_to)}` : '—'],
          ['Medicines', fmtNum(v.medicines)], ['Branches', fmtNum(v.branches)],
          ['Transactions', fmtNum(v.transactions)], ['Revenue', fmtINR(v.total_revenue)],
        ].map(([k, val]) => (
          <div key={k} className="summary-stat-card">
            <span className="summary-stat-label">{k}</span>
            <span className="summary-stat-title" style={{ fontSize: '0.9rem' }}>{val}</span>
          </div>
        ))}
      </div>

      {v.warnings?.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.76rem', color: '#fbbf24' }}>{v.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}

      <div className="card" style={{ background: 'var(--color-surface-2)' }}>
        {Object.entries(meta.stages ?? {}).map(([key, s]) => {
          const st = STATUS_STYLE[s.status] ?? STATUS_STYLE.pending;
          return (
            <div key={key} style={{ display: 'flex', gap: '0.75rem', padding: '0.6rem 1rem', borderBottom: '1px solid var(--color-border)', alignItems: 'baseline' }}>
              <span style={{ color: st.color, width: '1rem', textAlign: 'center' }}>{st.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '0.82rem', fontWeight: 600 }}>{s.title}</div>
                {s.message && <div style={{ fontSize: '0.72rem', color: s.status === 'failed' ? '#f87171' : '#8b90a8' }}>{s.message}</div>}
              </div>
              <span style={{ fontSize: '0.72rem', color: '#8b90a8', textTransform: 'capitalize' }}>
                {s.status}{s.seconds != null ? ` · ${s.seconds}s` : ''}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function Upload() {
  const navigate = useNavigate();
  const { datasets, activeId, select, refresh } = useDataset();
  const fileInput = useRef(null);

  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [name, setName] = useState('');
  const [problems, setProblems] = useState(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [pFile, setPFile] = useState(null);
  const [pPreview, setPPreview] = useState(null);
  const [pMapping, setPMapping] = useState({});
  const purchasesInput = useRef(null);

  const reset = () => { setFile(null); setPreview(null); setMapping({}); setName(''); setProblems(null); setJobId(null); setPFile(null); setPPreview(null); setPMapping({}); };

  const choose = useCallback(async (f) => {
    if (!f) return;
    setProblems(null); setPreview(null); setBusy(true); setFile(f);
    setName(f.name.replace(/\.[^.]+$/, ''));
    try {
      const p = await previewFile(f, 'sales');
      setPreview(p);
      setMapping(p.suggested_mapping ?? {});
    } catch (e) {
      setProblems(e.messages ?? [e.message]);
      setFile(null);
    } finally {
      setBusy(false);
    }
  }, []);

  const choosePurchases = async (f) => {
    if (!f) return;
    setProblems(null); setBusy(true);
    try {
      const p = await previewFile(f, 'purchases');
      setPFile(f); setPPreview(p); setPMapping(p.suggested_mapping ?? {});
    } catch (e) {
      setProblems(e.messages ?? [e.message]);
    } finally {
      setBusy(false);
    }
  };
  const clearPurchases = () => { setPFile(null); setPPreview(null); setPMapping({}); };

  const missing = preview ? preview.required.filter((k) => !mapping[k]) : [];
  const pMissing = pPreview ? pPreview.required.filter((k) => !pMapping[k]) : [];
  const setField = (k, v) => setMapping((m) => ({ ...m, [k]: v || undefined }));
  const setPField = (k, v) => setPMapping((m) => ({ ...m, [k]: v || undefined }));

  const submit = async () => {
    setBusy(true); setProblems(null);
    try {
      const meta = await createDataset({ file, name, mapping, purchases: pFile, purchasesMapping: pMapping });
      await refresh();
      setJobId(meta.id);
    } catch (e) {
      setProblems(e.messages ?? [e.message]);
    } finally {
      setBusy(false);
    }
  };

  const finished = useCallback(() => { refresh(); }, [refresh]);

  const remove = async (d) => {
    if (!window.confirm(`Delete “${d.name}” and all its results? This cannot be undone.`)) return;
    try {
      await deleteDataset(d.id);
      if (jobId === d.id) reset();
      await refresh();
    } catch (e) {
      window.alert(`Could not delete: ${e.message}`);
    }
  };

  const open = (id) => { select(id); navigate('/dashboard'); };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div className="page-header">
        <h1 className="page-title">Upload Data</h1>
        <p className="page-subtitle">Upload your sales file and MedStock builds a warehouse, analytics, association rules and demand forecasts for it.</p>
      </div>

      {/* ── Upload wizard ───────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">{jobId ? 'Processing your data' : preview ? 'Check the column mapping' : 'Upload a sales file'}</div>
            <div className="card-subtitle">
              {jobId ? 'The analysis runs in the background.' : 'CSV with a header row · up to 250 MB / 3 million rows · a sales file is enough; purchases are optional'}
            </div>
          </div>
          <a href={TEMPLATE_URL} className="pagination-btn" style={{ textDecoration: 'none' }}>Download template</a>
        </div>
        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {jobId ? (
            <>
              <Progress datasetId={jobId} onFinished={finished} />
              <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
                <button className="filter-btn-apply" onClick={() => open(jobId)}>Open dashboard</button>
                <button className="pagination-btn" onClick={reset}>Upload another file</button>
              </div>
            </>
          ) : !preview ? (
            <>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files?.[0]); }}
                onClick={() => fileInput.current?.click()}
                style={{
                  border: `2px dashed ${dragging ? '#6366f1' : 'var(--color-border)'}`, borderRadius: 'var(--radius)', padding: '2.5rem 1rem',
                  textAlign: 'center', cursor: 'pointer', background: dragging ? 'rgba(99,102,241,0.08)' : 'transparent',
                }}
              >
                <div style={{ fontSize: '1.8rem', color: '#6366f1' }}>⇪</div>
                <div style={{ fontWeight: 600 }}>{busy ? 'Reading file…' : 'Drop your sales CSV here, or click to choose'}</div>
                <div style={{ fontSize: '0.74rem', color: '#8b90a8', marginTop: '0.3rem' }}>
                  Needs date, medicine ID, quantity and unit price. Bill ID and branch are optional.
                </div>
                <input ref={fileInput} type="file" accept=".csv,text/csv" hidden onChange={(e) => choose(e.target.files?.[0])} />
              </div>
              <Problems messages={problems} />
            </>
          ) : (
            <>
              <div style={{ fontSize: '0.78rem', color: '#a0a5bd' }}>
                File: <strong>{file?.name}</strong> — match your columns to MedStock fields. We guessed where we could.
              </div>
              <MappingTable info={FIELD_INFO} preview={preview} mapping={mapping} onChange={setField} />

              <div>
                <div className="summary-stat-label" style={{ marginBottom: '0.3rem' }}>First rows of your file</div>
                <div style={{ overflowX: 'auto', border: '1px solid var(--color-border)', borderRadius: 'var(--radius)' }}>
                  <table className="data-table">
                    <thead><tr>{preview.headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
                    <tbody>
                      {preview.sample_rows.slice(0, 5).map((r, i) => (
                        <tr key={i}>{preview.headers.map((h) => <td key={h}>{r[h]}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div style={{ border: '1px solid var(--color-border)', borderRadius: 'var(--radius)', padding: '0.9rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Purchases file <span style={{ color: '#8b90a8', fontWeight: 400 }}>(optional)</span></div>
                    <div style={{ fontSize: '0.74rem', color: '#8b90a8', maxWidth: '640px' }}>
                      Add your stock receipts (date, medicine, quantity, unit cost; batch and expiry if you have them) to unlock inventory, expiry risk,
                      reorder and overstock decisions. Stock is rebuilt from purchases minus sales, selling the earliest-expiring lots first.
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <a href={PURCHASES_TEMPLATE_URL} className="pagination-btn" style={{ textDecoration: 'none' }}>Template</a>
                    {pFile
                      ? <button className="pagination-btn" onClick={clearPurchases} disabled={busy}>Remove {pFile.name}</button>
                      : <button className="pagination-btn" onClick={() => purchasesInput.current?.click()} disabled={busy}>Choose purchases CSV</button>}
                    <input ref={purchasesInput} type="file" accept=".csv,text/csv" hidden onChange={(e) => { choosePurchases(e.target.files?.[0]); e.target.value = ''; }} />
                  </div>
                </div>
                {pPreview && <MappingTable info={PURCHASE_INFO} preview={pPreview} mapping={pMapping} onChange={setPField} />}
              </div>

              <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <input type="text" className="filter-input" value={name} onChange={(e) => setName(e.target.value)}
                  placeholder="Dataset name" style={{ width: '240px' }} maxLength={80} />
                <button className="filter-btn-apply" disabled={busy || missing.length > 0 || pMissing.length > 0} onClick={submit}>
                  {busy ? 'Uploading…' : 'Upload & analyze'}
                </button>
                <button className="pagination-btn" onClick={reset} disabled={busy}>Cancel</button>
                {(missing.length > 0 || pMissing.length > 0) && <span style={{ fontSize: '0.74rem', color: '#f87171' }}>Map: {[...missing.map((k) => FIELD_INFO[k].label), ...pMissing.map((k) => `${PURCHASE_INFO[k].label} (purchases)`)].join(', ')}</span>}
              </div>
              <Problems messages={problems} />
            </>
          )}
        </div>
      </div>

      {/* ── Existing datasets ───────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Your datasets</div>
            <div className="card-subtitle">Pick which dataset every page shows. The demo dataset is always available.</div>
          </div>
        </div>
        <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
          <table className="data-table">
            <thead><tr><th>Name</th><th>Status</th><th>Period</th><th>Rows</th><th>Created</th><th>Auto-delete</th><th /></tr></thead>
            <tbody>
              {datasets.map((d) => (
                <tr key={d.id} style={{ background: d.id === activeId ? 'rgba(99,102,241,0.12)' : undefined }}>
                  <td style={{ fontWeight: 600 }}>{d.name}{d.id === activeId && <span style={{ color: '#818cf8', fontSize: '0.7rem' }}> · selected</span>}</td>
                  <td><StatusBadge status={d.status} /></td>
                  <td>{d.validation?.date_from ? `${fmtDate(d.validation.date_from)} – ${fmtDate(d.validation.date_to)}` : '—'}</td>
                  <td>{d.validation ? fmtNum(d.validation.rows_loaded) : '—'}</td>
                  <td>{d.created_at ? fmtDate(d.created_at.slice(0, 10)) : '—'}</td>
                  <td style={{ color: '#8b90a8' }}>{d.expires_at ? fmtDate(d.expires_at.slice(0, 10)) : '—'}</td>
                  <td style={{ whiteSpace: 'nowrap', display: 'flex', gap: '0.4rem' }}>
                    <button className="pagination-btn" disabled={d.status === 'failed'} onClick={() => open(d.id)}>Use</button>
                    {!d.built_in && <button className="pagination-btn" onClick={() => remove(d)}>Delete</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
