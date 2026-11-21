import { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../api/client';
import { useLive } from './live';

const NetworkContext = createContext(null);

/** Road network is static per scenario – fetched once, refetched if the scenario is regenerated. */
export function NetworkProvider({ children }) {
  const [network, setNetwork] = useState(null);
  const { state } = useLive();
  // fetched once per backend start (the server sends an ETag; re-fetch only when the source changes)
  const sourceKey = `${state?.network?.source}|${state?.network?.fallback_reason || ''}`;
  useEffect(() => {
    if (!state) return;
    api.get('/network').then(setNetwork).catch(() => {});
  }, [sourceKey]); // eslint-disable-line react-hooks/exhaustive-deps
  return <NetworkContext.Provider value={network}>{children}</NetworkContext.Provider>;
}

export const useNetwork = () => useContext(NetworkContext);
