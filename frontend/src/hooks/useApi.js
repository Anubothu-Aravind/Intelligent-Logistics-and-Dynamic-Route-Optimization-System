import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

/** GET with loading / error / retry. Keeps the previous data while refreshing
 *  (no flicker) and aborts stale requests when the path changes. */
export function useApi(path, deps = [], { ttl = 0 } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(!!path);
  const ctrl = useRef(null);
  const reload = useCallback(() => {
    if (!path) { setLoading(false); return Promise.resolve(); }
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setLoading(true);
    return api.get(path, { ttl, signal: ttl ? undefined : c.signal })
      .then((d) => { if (!c.signal.aborted) { setData(d); setError(null); } })
      .catch((e) => { if (e.name !== 'AbortError') setError(e.message); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
  }, [path, ttl]);
  useEffect(() => { reload(); return () => ctrl.current?.abort(); }, [reload, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, loading, reload, setData };
}

/** Async actions with per-key status: busy -> success (briefly) | error.
 *  Re-entrancy guard prevents duplicate submissions of the same action. */
export function useAction(toast) {
  const [busy, setBusy] = useState(null);
  const [done, setDone] = useState(null);
  const running = useRef(new Set());
  const run = useCallback(async (key, fn, success) => {
    if (running.current.has(key)) return null;
    running.current.add(key);
    setBusy(key);
    try {
      const res = await fn();
      if (success && toast) toast.push(typeof success === 'function' ? success(res) : success, 'ok');
      setDone(key);
      setTimeout(() => setDone((d) => (d === key ? null : d)), 1400);
      return res;
    } catch (e) {
      toast?.push(e.message, 'bad');
      return null;
    } finally {
      running.current.delete(key);
      setBusy((b) => (b === key ? null : b));
    }
  }, [toast]);
  return { busy, done, run };
}

export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Close a popover on outside click / Escape. */
export function useDismiss(open, onClose) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const click = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    const key = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', click);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('mousedown', click); document.removeEventListener('keydown', key); };
  }, [open, onClose]);
  return ref;
}
