import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';
import { Marker, Polyline, Tooltip } from 'react-leaflet';
import {
  Activity, AlertTriangle, Ban, CarFront, Check, ListFilter, PackagePlus, Play,
  Search, Split, Sparkles, TrafficCone, Wand2, X, Zap,
} from 'lucide-react';
import CityMap, { MapControls } from '../components/map/CityMap';
import { AnimatedNumber, slideRight } from '../components/motion';
import AnimatedVehicles from '../components/map/AnimatedVehicles';
import { DepotLayer, TrafficLayer } from '../components/map/layers';
import { pinIcon, stopIcon } from '../components/map/markers';
import { Avatar, Badge, Bar, Button, Chip, Empty, IconButton, Panel, Segments, Skeleton, StatTile } from '../components/ui';
import { api } from '../api/client';
import { useLive } from '../hooks/live';
import { useToast } from '../hooks/toast';
import { useAction, useApi } from '../hooks/useApi';
import { displayStatus, fmt } from '../lib/format';
import { colors, routePalette, statusColor } from '../theme/tokens';

const FILTERS = ['all', 'moving', 'delayed', 'idle'];

export default function LiveMapPage() {
  const { state, setState, simNow } = useLive();
  const toast = useToast();
  const { busy, done, run } = useAction(toast);
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [alternatives, setAlternatives] = useState(null);
  const [showAll, setShowAll] = useState(false);

  const vehicles = state?.vehicles || [];
  const selected = vehicles.find((v) => v.id === selectedId);
  const colorIndex = useMemo(() => Object.fromEntries(vehicles.map((v, i) => [v.id, routePalette[i % routePalette.length]])), [vehicles]);
  const counts = useMemo(() => {
    const c = { all: vehicles.length, moving: 0, delayed: 0, idle: 0 };
    vehicles.forEach((v) => { const s = displayStatus(v); c[s in c ? s : 'idle'] += 1; });
    return c;
  }, [vehicles]);
  const visible = vehicles.filter((v) => {
    const s = displayStatus(v);
    const okFilter = filter === 'all' || s === filter || (filter === 'idle' && !['moving', 'delayed'].includes(s));
    const q = query.trim().toLowerCase();
    return okFilter && (!q || v.code.toLowerCase().includes(q) || v.driver_name.toLowerCase().includes(q)
      || v.next_stop?.customer?.toLowerCase().includes(q) || v.next_stop?.code?.toLowerCase().includes(q));
  });

  // route geometry + stop list: only for the selected vehicle; refreshed when its route changes
  // (and every few seconds for fresh ETAs) – the per-second broadcast stays small
  const [etaTick, setEtaTick] = useState(0);
  useEffect(() => {
    if (!selected) return undefined;
    const t = setInterval(() => setEtaTick((x) => x + 1), 5000);
    return () => clearInterval(t);
  }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const route = useApi(selected ? `/vehicles/${selected.id}/route` : null, [selected?.route_version, selected?.stops_done, etaTick]);
  const detail = route.data?.vehicle_id === selected?.id ? route.data : null;
  const allKey = showAll ? vehicles.map((v) => v.route_version).join('|') : '';
  const allRoutes = useApi(showAll ? '/routes' : null, [allKey]);

  const colorOf = useCallback((v) => statusColor[displayStatus(v)] || colors.idle.DEFAULT, []);
  const select = useCallback((id) => { setSelectedId((cur) => (cur === id ? cur : id)); setAlternatives(null); }, []);

  const sim = (key, path, body, msg) => run(key, async () => {
    const res = await api.post(path, body);
    if (res?.vehicles) setState(res);
    return res;
  }, msg);

  const loadAlternatives = async () => {
    if (alternatives?.vehicleId === selected.id) { setAlternatives(null); return; }
    const res = await run('alt', () => api.get(`/vehicles/${selected.id}/alternatives`));
    if (res) setAlternatives({ vehicleId: selected.id, ...res });
    if (res && !res.paths?.length) toast.push(`${selected.code} has no next stop to compare roads for`, 'bad');
  };

  if (!state) {
    return (
      <div className="relative h-full p-6">
        <Skeleton className="absolute inset-0 !rounded-none" />
        <div className="relative z-10 text-sm text-ink-muted">Connecting to the optimisation engine…</div>
      </div>
    );
  }
  const k = state.kpis;

  return (
    <div className="relative h-full">
      <CityMap className="absolute inset-0 h-full w-full" padding={{ tl: [400, 100], br: [380, 80] }}>
        <MapControls right={380} bottom={90} />
        <TrafficLayer traffic={state.traffic} jamFactor={state.jam_factor} />
        {showAll && allRoutes.data?.routes.filter((r) => r.vehicle_id !== selectedId).map((r) => (
          <Polyline key={`r${r.vehicle_id}`} positions={r.paths}
            pathOptions={{ color: colorIndex[r.vehicle_id], weight: 3, opacity: 0.6 }} />
        ))}
        {selected && <SelectedRoute route={detail}
          alternatives={alternatives?.vehicleId === selected.id ? alternatives : null} />}
        <DepotLayer depots={state.depots} />
        <AnimatedVehicles vehicles={vehicles} simNow={simNow} selectedId={selectedId} colorOf={colorOf} onSelect={select} />
      </CityMap>

      {/* ---------- top bar ---------- */}
      <div className="pointer-events-none absolute inset-x-6 top-6 z-[1000] flex items-start gap-4">
        <label className="pointer-events-auto flex h-14 w-[364px] items-center gap-3 rounded-full bg-surface px-5 shadow-panel">
          <Search className="h-[18px] w-[18px] text-ink-muted" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search vans, drivers, stops"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-muted" aria-label="Search fleet" />
          {query && <button type="button" aria-label="Clear search" onClick={() => setQuery('')}><X className="h-4 w-4 text-ink-muted" /></button>}
        </label>
        <div className="pointer-events-auto hidden h-14 items-center gap-6 rounded-full bg-surface px-6 text-sm shadow-panel xl:flex">
          <span className="text-ink-muted">On time <b className="tabular ml-1 text-ok">{k.on_time_pct === null ? '–' : fmt.pct(k.on_time_pct)}</b></span>
          <span className="h-6 w-px bg-surface-line" />
          <span className="text-ink-muted">Delivered <b className="tabular ml-1 text-ink"><AnimatedNumber value={k.delivered} /> / <AnimatedNumber value={k.total_orders} /></b></span>
          <span className="h-6 w-px bg-surface-line" />
          <span className="text-ink-muted">Avg. delay <b className="tabular ml-1 text-warn">{fmt.num(k.avg_delay_min)} min</b></span>
        </div>
      </div>

      {/* ---------- fleet panel ---------- */}
      <Panel className="absolute bottom-24 left-6 top-[104px] z-[1000] flex w-[364px] flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 pb-3 pt-5">
          <h2 className="text-xl font-bold">Fleet <span className="ml-1 text-sm font-normal text-ink-muted">{vehicles.length} vehicles</span></h2>
          <IconButton icon={ListFilter} label={showAll ? 'Hide all routes' : 'Show every vehicle’s route'} active={showAll}
            className="h-9 w-9 rounded-xl" onClick={() => setShowAll((x) => !x)} />
        </div>
        <div className="flex flex-wrap gap-1.5 px-5 pb-3">
          {FILTERS.map((f) => <Chip key={f} active={filter === f} count={counts[f]} onClick={() => setFilter(f)}>{fmt.label(f)}</Chip>)}
        </div>
        <ul className="scroll-thin flex-1 space-y-1 overflow-y-auto px-3 pb-3">
          <AnimatePresence initial={false}>
            {visible.map((v) => (
              <FleetRow key={v.id} v={v} color={colorIndex[v.id]} selected={v.id === selectedId}
                onSelect={() => { setSelectedId(v.id === selectedId ? null : v.id); setAlternatives(null); }} />
            ))}
          </AnimatePresence>
          {!visible.length && <Empty icon={CarFront} title="No vehicles match">Try another filter or search.</Empty>}
        </ul>
      </Panel>

      {/* ---------- right panel ---------- */}
      <AnimatePresence mode="wait" initial={false}>
        <motion.section key={selected ? `v${selected.id}` : 'ops'} {...slideRight}
          className="panel absolute bottom-6 right-6 top-[104px] z-[1000] flex w-[340px] flex-col overflow-hidden">
          {selected
            ? <VehicleDetail v={selected} stops={detail?.stops} onClose={() => { setSelectedId(null); setAlternatives(null); }}
                alternatives={alternatives?.vehicleId === selected.id ? alternatives : null}
                onAlternatives={loadAlternatives} busy={busy} done={done}
                onReplan={() => sim('replan', '/optimization/reoptimize', { strategy: 'insertion_plus_local_search' },
                  (r) => ((r?.saving?.objective?.pct ?? 0) > 0.05
                    ? `Routes re-planned from live positions · ${r.saving.objective.pct}% better than keeping the old plan`
                    : 'Re-planned from live positions – the current routes are already the best found, nothing changed'))} />
            : <ActivityPanel state={state} sim={sim} busy={busy} />}
        </motion.section>
      </AnimatePresence>

      {state.persistence_error && (
        <div role="alert" className="absolute bottom-[76px] left-1/2 z-[1000] w-[min(560px,calc(100%-820px))] -translate-x-1/2 rounded-card bg-bad-soft px-3 py-2 text-xs text-bad shadow-float">
          <b>Database write failed – changes are kept in memory and retried.</b> {state.persistence_error}
        </div>
      )}
      <div className="absolute bottom-6 left-1/2 z-[1000] flex h-11 -translate-x-1/2 items-center gap-5 rounded-full bg-surface px-5 text-sm text-ink-soft shadow-panel">
        {[['Moving', statusColor.moving], ['Delayed', statusColor.delayed], ['Idle', statusColor.idle]].map(([l, c]) => (
          <span key={l} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />{l}</span>
        ))}
        <span className="flex items-center gap-2"><span className="h-1 w-4 rounded-full bg-warn" />Slow traffic</span>
        <span className="flex items-center gap-2"><span className="h-1 w-4 rounded-full bg-bad" />Jam / closed</span>
      </div>
    </div>
  );
}

const FleetRow = memo(function FleetRow({ v, color, selected, onSelect }) {
  const s = displayStatus(v);
  const progress = v.stops_total ? v.stops_done / v.stops_total : 0;
  const barColor = s === 'delayed' ? colors.warn.DEFAULT : selected ? colors.brand.DEFAULT : colors.ink.DEFAULT;
  const label = v.status === 'scheduled' ? `Departs ${v.departs_at}` : s === 'delayed' && v.next_stop?.late ? 'Late risk' : fmt.label(v.status);
  return (
    <motion.li layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 420, damping: 34 }}>
      <motion.button type="button" onClick={onSelect} aria-pressed={selected} whileTap={{ scale: 0.985 }}
        className={clsx('relative flex w-full items-center gap-3 rounded-card px-3 py-3 text-left transition-colors duration-150',
          selected ? 'bg-brand-soft' : 'hover:bg-surface-subtle')}>
        {selected && <span className="anim-fade absolute -left-3 bottom-3 top-3 w-1 rounded-r bg-brand" />}
        <Avatar name={v.driver_name} color={color} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-sm font-medium">{v.code}</span>
            <span className="tabular font-mono text-sm font-medium">{v.next_stop?.time || v.eta_end || '–'}</span>
          </div>
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-xs text-ink-muted">{v.driver_name}</span>
            <span key={label} className={clsx('anim-fade whitespace-nowrap text-xs', {
              'text-ok': s === 'moving' && v.status !== 'scheduled', 'text-warn': s === 'delayed',
              'text-brand': v.status === 'scheduled', 'text-ink-muted': !['moving', 'delayed'].includes(s) })}>{label}</span>
          </div>
          <div className="mt-1.5 flex items-center gap-3">
            <Bar value={progress} color={barColor} className="flex-1" />
            <span className="tabular font-mono text-2xs text-ink-muted">{v.stops_done}/{v.stops_total}</span>
          </div>
        </div>
      </motion.button>
    </motion.li>
  );
});

function SelectedRoute({ route, alternatives }) {
  const stops = (route?.stops || []).filter((s) => s.lat !== undefined);
  return (
    <>
      {route?.trail?.length > 1 && (
        <Polyline positions={route.trail} pathOptions={{ color: colors.ink.muted, weight: 3.5, dashArray: '2 7', lineCap: 'round' }} />
      )}
      {route?.future?.filter((p) => p.length > 1).map((p, i) => (
        <Polyline key={`f${i}`} positions={p} pathOptions={{ color: colors.brand.DEFAULT, weight: 4, opacity: 0.7 }} />
      ))}
      {route?.current?.length > 1 && (
        <Polyline positions={route.current} pathOptions={{ color: colors.brand.DEFAULT, weight: 5.5 }} />
      )}
      {alternatives?.paths?.slice(1).map((p) => (
        <Polyline key={`alt${p.rank}`} positions={p.coords}
          pathOptions={{ color: colors.ink.soft, weight: 4, dashArray: '8 8', opacity: 0.75 }}>
          <Tooltip sticky className="chip-tooltip">Alternative #{p.rank} · {fmt.num(p.time_min, 1)} min · {fmt.km(p.distance_m / 1000)}</Tooltip>
        </Polyline>
      ))}
      {stops.map((s, i) => {
        const done = s.status === 'done';
        const next = s.status === 'next' || s.status === 'servicing';
        const label = s.order_id ? i + 1 : 'D';
        return (
          <Marker key={`${s.code}${i}`} position={[s.lat, s.lon]} zIndexOffset={next ? 900 : 400}
            icon={next ? pinIcon(label, colors.brand.DEFAULT) : stopIcon(label, { color: colors.ink.DEFAULT, filled: done })}>
            <Tooltip direction="top" offset={[0, -12]} className="chip-tooltip">{s.code} · {s.customer} · {s.time}</Tooltip>
          </Marker>
        );
      })}
    </>
  );
}

function VehicleDetail({ v, stops: stopsIn, onClose, alternatives, onAlternatives, onReplan, busy, done }) {
  const s = displayStatus(v);
  const nxt = v.next_stop;
  const stops = stopsIn || [];
  const currentIdx = stops.findIndex((x) => x.status === 'next' || x.status === 'servicing');
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between px-5 pt-5">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-mono text-2xl font-semibold">{v.code}</h2>
            <Badge key={v.status} className="anim-fade" tone={v.status === 'scheduled' ? 'brand' : s === 'delayed' ? 'warn' : s === 'moving' ? 'ok' : 'idle'}>
              {v.status === 'scheduled' ? `Departs ${v.departs_at}` : fmt.label(v.status)}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-ink-muted">{v.model} · {fmt.pct(v.load_pct)} full</p>
        </div>
        <IconButton icon={X} label="Close vehicle details" onClick={onClose} className="h-10 w-10 rounded-xl" />
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto px-5 pb-4">
        <div className="card mt-4 flex items-center gap-3 p-3">
          <Avatar name={v.driver_name} color={colors.ink.soft} size={40} />
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{v.driver_name}</div>
            <div className="text-xs text-ink-muted">Driver · since {v.driver_since}</div>
          </div>
        </div>
        {nxt ? (
          <div className="mt-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="label">{nxt.status === 'servicing' ? 'Delivering now' : 'Next stop'}</div>
                <div key={nxt.code} className="anim-fade mt-1 truncate text-lg font-semibold">{nxt.customer}</div>
                <div className="truncate text-xs text-ink-muted">{nxt.address}{nxt.weight_kg ? ` · ${nxt.weight_kg} kg` : ''}</div>
              </div>
              <div className="shrink-0 text-right">
                <div className={clsx('tabular text-2xl font-bold', nxt.late ? 'text-bad' : 'text-brand')}>{nxt.time}</div>
                <div className="font-mono text-2xs text-ink-muted">{nxt.deadline ? `DUE ${nxt.deadline}` : 'ARRIVAL'}</div>
              </div>
            </div>
            <div className="mt-3"><Segments total={v.stops_total} done={v.stops_done} current={v.stops_done} /></div>
          </div>
        ) : <p className="mt-5 text-sm text-ink-muted">No remaining stops{v.eta_end ? ` · back at depot ${v.eta_end}` : ''}.</p>}
        <div className="mt-4 grid grid-cols-3 gap-2">
          <StatTile label="Load" value={fmt.pct(v.load_pct)} />
          <StatTile label="Speed" value={`${fmt.num(v.speed_kmh)} km/h`} />
          <StatTile label="Fuel" value={fmt.pct(v.fuel_pct)} />
        </div>
        <div className="mt-5 flex items-center justify-between">
          <h3 className="text-[15px] font-semibold">Stops</h3>
          <span className="text-xs text-ink-muted">{v.stops_done} of {v.stops_total} done</span>
        </div>
        {!stopsIn && <div className="mt-3 space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>}
        {stopsIn && !stops.length && <p className="mt-2 text-xs text-ink-muted">No stops assigned. Optimise or re-plan to give this vehicle work.</p>}
        <ol className="mt-3">
          {stops.map((st, i) => {
            const isDone = st.status === 'done';
            const cur = i === currentIdx;
            return (
              <motion.li key={`${st.code}${i}`} className="relative flex gap-3 pb-4 last:pb-0"
                initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0, transition: { delay: Math.min(i, 8) * 0.025 } }}>
                {i < stops.length - 1 && <span className={clsx('absolute left-[9px] top-5 h-full w-0.5 transition-colors duration-500', isDone ? 'bg-ink' : 'bg-surface-line')} />}
                <span className={clsx('relative z-10 mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border-2 transition-colors duration-300',
                  isDone ? 'border-ink bg-ink text-white' : cur ? 'border-brand bg-surface' : 'border-surface-line bg-surface')}>
                  {isDone && <Check className="anim-fade h-3 w-3" strokeWidth={3} />}
                  {cur && <span className="h-2 w-2 rounded-full bg-brand" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex justify-between gap-2">
                    <span className={clsx('truncate text-sm font-medium', cur && 'text-brand-strong', !isDone && !cur && 'text-ink-soft')}>{st.customer}</span>
                    <span className={clsx('tabular font-mono text-xs', cur ? 'text-brand' : st.late ? 'text-bad' : 'text-ink-soft')}>{st.time}</span>
                  </div>
                  <div className="truncate text-xs text-ink-muted">
                    {isDone ? `Delivered · ${fmt.label(st.note)}` : st.order_id ? `${st.code} · ${st.weight_kg} kg · ${st.priority}` : 'Pick up new parcels'}
                  </div>
                </div>
              </motion.li>
            );
          })}
        </ol>
        {alternatives && (
          <div className="card anim-fade mt-5 p-3">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Split className="h-4 w-4" />Why this road?</div>
            <p className="mb-2 text-xs text-ink-muted">Yen's K-shortest paths to the next stop with current traffic. The vehicle drives path #1; the dashed lines on the map are the alternatives.</p>
            {alternatives.paths.map((p) => (
              <div key={p.rank} className="flex justify-between border-t border-surface-line py-1.5 text-xs first:border-0">
                <span className={p.chosen ? 'font-semibold text-brand' : 'text-ink-soft'}>#{p.rank} {p.chosen && '(chosen)'}</span>
                <span className="tabular font-mono">{fmt.num(p.time_min, 1)} min · {fmt.km(p.distance_m / 1000)}</span>
              </div>
            ))}
            <div className="mt-2 border-t border-surface-line pt-2 text-2xs text-ink-muted">
              {Object.values(alternatives.algorithms).map((a) => (
                <div key={a.algorithm} className="flex justify-between"><span>{fmt.label(a.algorithm).replace('Astar', 'A*')}</span>
                  <span className="tabular font-mono">{a.expanded} nodes · {fmt.num(a.runtime_ms, 2)} ms</span></div>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="flex gap-2 border-t border-surface-line p-4">
        <Button variant="dark" size="lg" className="flex-1" icon={Split} busy={busy === 'alt'} onClick={onAlternatives}
          disabled={!v.next_stop || v.next_stop.status !== 'next'} title="Compare alternative roads to the next stop">
          {alternatives ? 'Hide alternatives' : 'Alternative roads'}
        </Button>
        <Button size="lg" icon={Wand2} busy={busy === 'replan'} done={done === 'replan'} onClick={onReplan}
          title="Re-optimise all open orders from the vehicles' live positions">Re-plan</Button>
      </div>
    </div>
  );
}

function ActivityPanel({ state, sim, busy }) {
  const icons = { delivery: Check, new_order: PackagePlus, congestion: TrafficCone, closure: Ban, decision: Sparkles, optimize: Zap, alert: AlertTriangle };
  const m = state.plan?.metrics;
  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pt-5">
        <h2 className="text-xl font-bold">Operations</h2>
        <p className="mt-1 text-sm text-ink-muted">Select a vehicle on the map or in the fleet list to see its route, stops and alternatives.</p>
      </div>
      {m ? (
        <div className="mt-4 grid grid-cols-3 gap-2 px-5">
          <StatTile label="Plan km" value={fmt.num(m.distance_km)} />
          <StatTile label="Vehicles" value={m.vehicles_used} />
          <StatTile label="Late" value={m.late_count} />
        </div>
      ) : (
        <div className="mx-5 mt-4 rounded-card bg-brand-soft p-4 text-sm">
          No plan yet. <b>Optimise &amp; dispatch</b> plans with the default algorithm, or tune it first on <b>Route &amp; dispatch</b>.
        </div>
      )}
      <div className="mt-5 flex items-center justify-between px-5">
        <h3 className="flex items-center gap-2 text-[15px] font-semibold"><Activity className="h-4 w-4" />Live activity</h3>
        <span className="text-xs text-ink-muted">{state.kpis.in_transit} in transit</span>
      </div>
      <ul className="scroll-thin mt-2 flex-1 overflow-y-auto px-5 pb-4">
        <AnimatePresence initial={false}>
        {state.feed.map((f) => {
          const Icon = icons[f.type] || Activity;
          return (
            <motion.li key={f.id} layout initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              transition={{ type: 'spring', stiffness: 380, damping: 32 }} className="flex gap-3 border-b border-surface-line py-2.5 last:border-0">
              <span className={clsx('grid h-7 w-7 shrink-0 place-items-center rounded-full',
                f.type === 'decision' || f.type === 'optimize' ? 'bg-brand-soft text-brand'
                  : ['congestion', 'closure', 'alert'].includes(f.type) ? 'bg-bad-soft text-bad' : 'bg-surface-sunken text-ink-soft')}>
                <Icon className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1 text-sm">
                <div className="text-ink-soft">{f.message}</div>
                <div className="font-mono text-2xs text-ink-muted">{f.time}</div>
              </div>
            </motion.li>
          );
        })}
        </AnimatePresence>
        {!state.feed.length && <li className="py-6 text-center text-xs text-ink-muted">Nothing has happened yet.</li>}
      </ul>
    </div>
  );
}
