export const fmt = {
  num: (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })),
  pct: (v, d = 0) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(d)}%`),
  km: (v) => (v === null || v === undefined ? '–' : `${Number(v).toFixed(1)} km`),
  duration: (min) => {
    if (min === null || min === undefined) return '–';
    const h = Math.floor(min / 60);
    const m = Math.round(min % 60);
    return h ? `${h} h ${m} m` : `${m} m`;
  },
  label: (s) => (s ? s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : ''),
  initials: (name = '') => name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase(),
};

/** A vehicle is "delayed" when a delivered stop was late or its next stop is predicted late. */
export function displayStatus(v) {
  if (!v) return 'idle';
  if (v.status === 'inactive') return 'inactive';
  if ((v.late_count > 0 || v.next_stop?.late) && ['moving', 'servicing', 'reloading'].includes(v.status)) return 'delayed';
  if (v.status === 'scheduled') return 'idle';          // parked until its planned departure
  if (['moving', 'servicing', 'reloading'].includes(v.status)) return 'moving';
  return v.status === 'blocked' ? 'blocked' : 'idle';
}
