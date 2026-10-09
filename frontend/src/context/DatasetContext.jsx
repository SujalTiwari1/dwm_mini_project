import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { DEMO_DATASET, fetchDatasets, getActiveDataset, setActiveDataset } from '../api/client';

const DEMO_ENTRY = {
  id: DEMO_DATASET, name: 'Demo dataset (synthetic pharmacy)', status: 'ready', built_in: true,
  capabilities: { sales_analytics: true, association_rules: true, multi_branch: true, forecasting: true, inventory_expiry_decisions: true, decision_support: true, expiry_risk: true },
};

const DatasetContext = createContext(null);

/**
 * Holds the list of datasets and the selected one. The selection is stored in api/client.js (sent as a header on
 * every request) and in localStorage; pages re-mount when it changes (see the key on <main> in App.jsx).
 */
export function DatasetProvider({ children }) {
  const [datasets, setDatasets] = useState([DEMO_ENTRY]);
  const [activeId, setActiveId] = useState(getActiveDataset());
  const [loading, setLoading] = useState(true);

  const select = useCallback((id) => {
    setActiveDataset(id);
    setActiveId(id);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const res = await fetchDatasets();
      const list = res?.data?.length ? res.data : [DEMO_ENTRY];
      setDatasets(list);
      if (!list.some((d) => d.id === getActiveDataset())) select(DEMO_DATASET);   // selected dataset was deleted
    } catch {
      /* keep the demo entry; the pages show their own errors */
    } finally {
      setLoading(false);
    }
  }, [select]);

  useEffect(() => { refresh(); }, [refresh]);

  const value = useMemo(() => {
    const active = datasets.find((d) => d.id === activeId) ?? DEMO_ENTRY;
    return { datasets, active, activeId: active.id, loading, select, refresh, caps: active.capabilities ?? {} };
  }, [datasets, activeId, loading, select, refresh]);

  return <DatasetContext.Provider value={value}>{children}</DatasetContext.Provider>;
}

export function useDataset() {
  const ctx = useContext(DatasetContext);
  if (!ctx) throw new Error('useDataset must be used inside <DatasetProvider>');
  return ctx;
}
