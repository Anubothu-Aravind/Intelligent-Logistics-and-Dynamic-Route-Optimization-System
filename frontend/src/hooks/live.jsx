import { createContext, startTransition, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api, wsUrl } from '../api/client';

const LiveContext = createContext(null);

/** Live simulation snapshot: WebSocket push, exponential-backoff reconnect, HTTP polling fallback.
 *  `simNow()` extrapolates the simulation clock between ticks so the map can animate smoothly. */
export function LiveProvider({ children }) {
  const [state, setStateRaw] = useState(null);
  const [connected, setConnected] = useState(false);
  const retry = useRef(0);
  const clock = useRef({ clock: 0, at: 0, rate: 0, maxAhead: 0 });

  const setState = useCallback((s) => {
    if (!s || s.vehicles === undefined) return;
    const rate = s.running ? s.minutes_per_tick / Math.max(0.05, s.tick_interval_s) : 0; // sim-min per real second
    clock.current = { clock: s.clock, at: performance.now(), rate, maxAhead: s.minutes_per_tick * 1.5 };
    // low-priority render: React can interrupt it, so the map keeps animating at 60 fps
    startTransition(() => setStateRaw(s));
  }, []);
  const simNow = useCallback(() => {
    const c = clock.current;
    return c.clock + Math.min(c.maxAhead, ((performance.now() - c.at) / 1000) * c.rate);
  }, []);
  const refresh = useCallback(() => api.get('/simulation/state').then(setState).catch(() => {}), [setState]);

  useEffect(() => {
    let socket;
    let timer;
    let poll;
    let closed = false;
    const connect = () => {
      socket = new WebSocket(wsUrl());
      socket.onopen = () => { retry.current = 0; setConnected(true); clearInterval(poll); };
      socket.onmessage = (e) => setState(JSON.parse(e.data));
      socket.onclose = () => {
        setConnected(false);
        if (closed) return;
        clearInterval(poll);
        poll = setInterval(refresh, 2000);
        timer = setTimeout(connect, Math.min(10000, 500 * 2 ** retry.current++));
      };
    };
    refresh();
    connect();
    return () => { closed = true; clearTimeout(timer); clearInterval(poll); socket?.close(); };
  }, [refresh, setState]);

  return <LiveContext.Provider value={{ state, connected, refresh, setState, simNow }}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);
