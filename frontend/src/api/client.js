const BASE = import.meta.env.VITE_API_URL || '';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const inflight = new Map();   // identical concurrent GETs share one request
const cache = new Map();      // short-lived GET cache for static data (opt-in per call)

async function request(method, path, body, { signal } = {}) {
  let res;
  try {
    res = await fetch(`${BASE}/api${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError('Cannot reach the server – is the backend running?', 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(', ') : data.detail;
    throw new ApiError(detail || `${res.status} ${res.statusText}`, res.status);
  }
  return data;
}

function get(path, { ttl = 0, signal } = {}) {
  const hit = cache.get(path);
  if (ttl && hit && Date.now() - hit.t < ttl) return Promise.resolve(hit.data);
  if (!signal && inflight.has(path)) return inflight.get(path);
  const p = request('GET', path, null, { signal })
    .then((data) => { if (ttl) cache.set(path, { t: Date.now(), data }); return data; })
    .finally(() => { if (inflight.get(path) === p) inflight.delete(path); });
  if (!signal) inflight.set(path, p);
  return p;
}

export const api = {
  get,
  post: (p, b = {}) => request('POST', p, b),
  patch: (p, b = {}) => request('PATCH', p, b),
  del: (p) => request('DELETE', p),
  invalidate: (prefix = '') => { [...cache.keys()].filter((k) => k.startsWith(prefix)).forEach((k) => cache.delete(k)); },
};

export function qs(params) {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') s.set(k, v); });
  const str = s.toString();
  return str ? `?${str}` : '';
}

export function wsUrl() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  const base = BASE || window.location.origin;
  return `${base.replace(/^http/, 'ws')}/ws`;
}
