import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { Marker, Polyline, Tooltip } from 'react-leaflet';
import { Bar as RBar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from 'recharts';
import { Eye, EyeOff, GitCompareArrows, Info, Play, Route, Wand2 } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import CityMap, { MapControls } from '../components/map/CityMap';
import { DepotLayer, OrderDots } from '../components/map/layers';
import { stopIcon } from '../components/map/markers';
import { Badge, Bar, Button, Chip, Empty, ErrorState, Field, KpiChip, Panel, SectionTitle, Select, Spinner } from '../components/ui';
import { api } from '../api/client';
import { useLive } from '../hooks/live';
import { useToast } from '../hooks/toast';
import { useAction, useApi } from '../hooks/useApi';
import { fmt } from '../lib/format';
import { chart, colors, routePalette } from '../theme/tokens';

const WEIGHT_KEYS = [
  ['alpha_distance_per_km', 'α distance (per km)'],
  ['beta_time_per_min', 'β time (per min)'],
  ['gamma_lateness_per_min', 'γ lateness (per min)'],
  ['delta_vehicle_fixed', 'δ per vehicle'],
  ['epsilon_waiting_per_min', 'ε customer wait (per min)'],
  ['zeta_balance_per_h2', 'ζ workload balance (per h²)'],
  ['max_route_duration_min', 'Max route length (min)'],
  ['route_overtime_penalty_per_min', 'Penalty past max (per min)'],
];

export default function DispatchPage() {
  const toast = useToast();
  const { state, setState } = useLive();
  const { busy, done, run } = useAction(toast);
  const algos = useApi('/optimization/algorithms', [], { ttl: 60000 });
  const runId = state?.plan?.run_id;
  const planReq = useApi('/optimization/plan', [runId]);
  const markers = useApi('/orders/markers?status=pending', [runId, state?.kpis?.unassigned, state?.kpis?.total_orders]);
  const [hidden, setHidden] = useState(new Set());
  const [form, setForm] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [advanced, setAdvanced] = useState(false);

  useEffect(() => {
    if (!algos.data || form) return;
    const d = algos.data.defaults;
    const a = algos.data.active || {};
    setForm({
      algorithm: a.algorithm || d.algorithm, shortest_path: a.shortest_path || d.shortest_path,
      operators: a.operators || d.operators,
      weights: Object.fromEntries(WEIGHT_KEYS.map(([k]) => [k, (a.weights || {})[k] ?? d.weights[k]])),
      ga: { population_size: d.ga.population_size, generations: d.ga.generations, mutation_rate: d.ga.mutation_rate, time_limit_s: d.ga.time_limit_s },
    });
  }, [algos.data, form]);

  const plan = planReq.data?.plan;
  const meta = planReq.data?.meta;
  const m = meta?.metrics;
  const imp = meta?.explanation?.improvement_vs_baseline || meta?.explanation?.saving;
  const vehicles = state?.vehicles || [];
  const colorOf = useMemo(() => Object.fromEntries(vehicles.map((v, i) => [v.id, routePalette[i % routePalette.length]])), [vehicles]);
  const unassignedOrders = (markers.data?.markers || []).map(([id, code, lat, lon, st, pr]) => ({ id, code, lat, lon, status: st, priority: pr, weight_kg: '' }));
  const working = busy === 'opt' || busy === 'cmp' || state?.optimizing;

  const optimise = () => run('opt', async () => {
    const res = await api.post('/optimization/run', {
      algorithm: form.algorithm, shortest_path: form.shortest_path, operators: form.operators,
      weights: Object.fromEntries(Object.entries(form.weights).map(([k, v]) => [k, Number(v)])),
      ga: form.algorithm === 'genetic' ? Object.fromEntries(Object.entries(form.ga).map(([k, v]) => [k, Number(v)])) : undefined,
    });
    await planReq.reload();
    return res;
  }, (r) => (state?.dispatched ? `Open orders re-planned from live positions · Z ${fmt.num(r.reoptimized?.objective, 1)}`
    : `Plan ready · Z ${fmt.num(r.metrics?.objective, 1)} · ${r.metrics?.vehicles_used} vehicles · ${r.metrics?.late_count} late`));

  const dispatch = () => run('dispatch', async () => {
    const res = await api.post('/simulation/start');
    setState(res);
    return res;
  }, 'Fleet dispatched – follow it on the Live map');

  const compare = () => run('cmp', async () => {
    const res = await api.post('/optimization/compare', { algorithms: algos.data.routing.filter((a) => a.available).map((a) => a.id) });
    setComparison(res.results);
    return res;
  }, 'Comparison finished');

  const toggle = (id) => setHidden((h) => { const n = new Set(h); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <div className="h-full overflow-y-auto bg-surface-subtle p-6">
      <Panel className="p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[32px] font-extrabold tracking-tight">Route &amp; Dispatch</h1>
            <p className="mt-1 text-sm text-ink-muted">
              {meta?.explanation?.algorithm_label || (meta ? `Dynamic re-optimisation (${fmt.label(meta.explanation?.strategy)})` : 'No plan yet – choose an algorithm and optimise.')}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {state?.dispatched
              ? <Badge tone="warn">Fleet on the road – optimising re-plans open orders from live positions</Badge>
              : <Button variant="brand" icon={Play} busy={busy === 'dispatch'} disabled={!plan || working} onClick={dispatch}
                  title={plan ? 'Load the vehicles and start the simulation' : 'Optimise first'}>Dispatch fleet</Button>}
          </div>
        </div>
        <div className="mt-5 flex flex-wrap gap-3 border-y border-surface-line py-4">
          <KpiChip label="Assigned" value={`${(state?.kpis.total_orders ?? 0) - (state?.kpis.unassigned ?? 0)}/${state?.kpis.total_orders ?? 0}`} />
          <KpiChip label="Orders / Stops" value={`${state?.kpis.total_orders ?? 0}/${plan ? plan.routes.reduce((s, r) => s + r.stops.length, 0) : 0}`} />
          <KpiChip label="Vehicles" value={`${m?.vehicles_used ?? 0}/${state?.kpis.fleet_size ?? 0}`} />
          <KpiChip label="Duration" value={fmt.duration(m?.duration_min)} />
          <KpiChip label="Distance" value={fmt.km(m?.distance_km)} />
          <KpiChip label="Objective Z" value={fmt.num(m?.objective, 0)} highlight delta={imp?.objective ? `${imp.objective.pct}%` : null} positive={(imp?.objective?.pct ?? 0) >= 0} />
          <KpiChip label="Late stops" value={m?.late_count ?? '–'} highlight delta={imp?.late_count ? `${imp.late_count.delta}` : null} positive={(imp?.late_count?.delta ?? 0) >= 0} />
          <KpiChip label="CO₂" value={m ? `${fmt.num(m.co2_kg)} kg` : '–'} highlight delta={imp?.co2_kg ? `${imp.co2_kg.pct}%` : null} positive={(imp?.co2_kg?.pct ?? 0) >= 0} />
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)_340px]">
          {/* vehicle route cards */}
          <div className="scroll-thin space-y-3 overflow-y-auto xl:max-h-[640px]">
            {plan?.routes.filter((r) => r.stops.length).map((r) => (
              <div key={r.vehicle_id} className="flex overflow-hidden rounded-card border border-surface-line bg-surface">
                <span className="w-2 shrink-0" style={{ background: colorOf[r.vehicle_id] }} />
                <div className="min-w-0 flex-1 p-3">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-2 font-medium">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: colorOf[r.vehicle_id] }} />
                      <span className="font-mono">{r.vehicle_code}</span>
                    </span>
                    <button type="button" aria-label={hidden.has(r.vehicle_id) ? 'Show route' : 'Hide route'} onClick={() => toggle(r.vehicle_id)}
                      className="rounded-lg p-1 text-ink-muted hover:bg-surface-sunken">
                      {hidden.has(r.vehicle_id) ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <div className="mt-1 truncate text-xs text-ink-muted">{vehicles.find((v) => v.id === r.vehicle_id)?.driver_name}</div>
                  <div className="mt-2 grid grid-cols-3 gap-1 text-xs">
                    <span><b className="tabular">{r.stops.filter((s) => s.type === 'order').length}</b> stops</span>
                    <span><b className="tabular">{fmt.num(r.distance_km, 1)}</b> km</span>
                    <span className={clsx(r.late_count && 'text-bad')}><b className="tabular">{r.late_count}</b> late</span>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <Bar value={r.load_kg / r.capacity_kg} color={colorOf[r.vehicle_id]} className="flex-1" />
                    <span className="tabular text-2xs text-ink-muted">{fmt.num(r.load_kg)}/{fmt.num(r.capacity_kg)} kg</span>
                  </div>
                  <div className="mt-1 text-2xs text-ink-muted">Back at depot {r.end_hhmm || '–'}</div>
                </div>
              </div>
            ))}
            {plan && !plan.routes.some((r) => r.stops.length) && <Empty icon={Route} title="All routes completed" />}
            {!plan && !planReq.loading && <Empty icon={Route} title="No routes yet">Run an optimisation to assign orders to vehicles.</Empty>}
          </div>

          {/* map */}
          <div className="relative h-[640px] overflow-hidden rounded-[18px] border border-surface-line">
            <CityMap className="h-full w-full" padding={[30, 30]}>
              <MapControls bottom={20} />
              <DepotLayer depots={state?.depots} />
              <OrderDots orders={unassignedOrders} color={colors.ink.muted} radius={5} />
              {plan?.routes.filter((r) => !hidden.has(r.vehicle_id)).map((r) => (
                <RouteOverlay key={r.vehicle_id} route={r} color={colorOf[r.vehicle_id]} />
              ))}
            </CityMap>
            {unassignedOrders.length > 0 && (
              <div className="absolute bottom-4 left-4 z-[1000] rounded-full bg-surface px-4 py-2 text-xs shadow-float">
                <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full bg-ink-muted" />{unassignedOrders.length} unassigned orders
              </div>
            )}
          </div>

          {/* controls */}
          <div className="space-y-4">
            <div className="rounded-card border border-surface-line p-4">
              <SectionTitle aside="Python engine">Optimiser</SectionTitle>
              {algos.error && !algos.data ? <ErrorState message={algos.error} onRetry={algos.reload} /> : !form ? <Spinner /> : (
                <div className="space-y-3">
                  <Field label="Vehicle routing algorithm">
                    <Select value={form.algorithm} onChange={(v) => setForm({ ...form, algorithm: v })}
                      options={algos.data.routing.map((a) => ({ value: a.id, label: a.label, disabled: !a.available }))} />
                  </Field>
                  <button type="button" onClick={() => setAdvanced((a) => !a)} aria-expanded={advanced}
                    className="flex w-full items-center justify-between rounded-lg py-1 text-sm font-medium text-ink-soft hover:text-ink">
                    Advanced settings
                    <motion.span animate={{ rotate: advanced ? 180 : 0 }}>▾</motion.span>
                  </button>
                  <AnimatePresence initial={false}>
                  {advanced && (
                  <motion.div key="adv" className="space-y-3 overflow-hidden" initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.22 }}>
                  <Field label="Shortest-path algorithm (road legs)">
                    <Select value={form.shortest_path} onChange={(v) => setForm({ ...form, shortest_path: v })}
                      options={algos.data.shortest_path.map((a) => ({ value: a, label: fmt.label(a).replace('Astar', 'A* search') }))} />
                  </Field>
                  <div>
                    <div className="label mb-1.5">Local-search operators</div>
                    <div className="flex flex-wrap gap-1.5">
                      {algos.data.operators.map((op) => (
                        <Chip key={op} active={form.operators.includes(op)}
                          onClick={() => setForm({ ...form, operators: form.operators.includes(op) ? form.operators.filter((x) => x !== op) : [...form.operators, op] })}>
                          {fmt.label(op).replace('Two Opt', '2-opt').replace('Or Opt', 'Or-opt')}
                        </Chip>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-sm font-medium text-ink-soft">Objective weights  Z = αD + βT + γL + δV + εW + ζB</div>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {WEIGHT_KEYS.map(([key, label]) => (
                        <Field key={key} label={label}>
                          <input type="number" min="0" step="0.1" className="input" value={form.weights[key]}
                            onChange={(e) => setForm({ ...form, weights: { ...form.weights, [key]: e.target.value } })} />
                        </Field>
                      ))}
                    </div>
                  </div>
                  </motion.div>
                  )}
                  </AnimatePresence>
                  {form.algorithm === 'genetic' && (
                    <div className="grid grid-cols-2 gap-2">
                      {Object.keys(form.ga).map((key) => (
                        <Field key={key} label={fmt.label(key)}>
                          <input type="number" min="0" step="any" className="input" value={form.ga[key]}
                            onChange={(e) => setForm({ ...form, ga: { ...form.ga, [key]: e.target.value } })} />
                        </Field>
                      ))}
                    </div>
                  )}
                  <div className="flex gap-2 pt-1">
                    <Button variant="dark" className="flex-1" icon={Wand2} busy={busy === 'opt'} done={done === 'opt'} disabled={working}
                      onClick={optimise} title={state?.dispatched ? 'Re-assign all open orders from the vehicles’ live positions' : 'Build a new plan for all open orders'}>
                      {state?.dispatched ? 'Re-plan open orders' : 'Optimise plan'}
                    </Button>
                    <Button icon={GitCompareArrows} busy={busy === 'cmp'} disabled={working} onClick={compare}
                      title="Run every algorithm on the same open orders without changing the plan">Compare all</Button>
                  </div>
                  {busy === 'cmp' && <p className="text-xs text-ink-muted">Running every algorithm on the same orders – the GA and OR-Tools take up to their time limits. The simulation keeps running.</p>}
                </div>
              )}
            </div>
            <Explanation meta={meta} plan={plan} />
          </div>
        </div>
      </Panel>
      {comparison && <ComparisonPanel rows={comparison} />}
    </div>
  );
}

function RouteOverlay({ route, color }) {
  let n = 0;
  return (
    <>
      {route.legs.map((leg, i) => (
        <Polyline key={i} positions={leg.coords} pathOptions={{ color, weight: 3.5, opacity: 0.95 }} />
      ))}
      {route.stops.map((s, i) => {
        if (s.type !== 'order') return null;
        n += 1;
        return (
          <Marker key={i} position={[s.lat, s.lon]} icon={stopIcon(n, { color, filled: true, size: 22 })}>
            <Tooltip direction="top" className="chip-tooltip">
              {route.vehicle_code} #{n} · {s.code} · ETA {s.eta_hhmm} (due {s.deadline_hhmm}){s.late ? ' · LATE' : ''}
            </Tooltip>
          </Marker>
        );
      })}
    </>
  );
}

function Explanation({ meta, plan }) {
  if (!meta) return null;
  const ex = meta.explanation || {};
  const cb = meta.metrics?.cost_breakdown;
  const total = cb ? Object.values(cb).reduce((a, b) => a + Math.max(0, b), 0) : 0;
  return (
    <div className="rounded-card border border-surface-line p-4">
      <SectionTitle aside={`run #${meta.run_id}`}><span className="flex items-center gap-2"><Info className="h-4 w-4" />Why this plan?</span></SectionTitle>
      {ex.stages && (
        <ol className="space-y-2">
          {ex.stages.map((s, i) => (
            <li key={i} className="text-xs">
              <div className="flex justify-between gap-2"><span className="font-medium">{i + 1}. {s.stage}</span>
                <span className="tabular font-mono">Z={fmt.num(s.cost, 1)}</span></div>
              <div className="text-ink-muted">{fmt.num(s.runtime_ms, 1)} ms
                {s.gains && ` · gains: ${Object.entries(s.gains).filter(([, g]) => g > 0).map(([k, g]) => `${fmt.label(k)} −${fmt.num(g, 1)}`).join(', ') || 'none'}`}
                {s.generations !== undefined && ` · ${s.generations} generations`}
              </div>
            </li>
          ))}
        </ol>
      )}
      {ex.decisions && (
        <div className="space-y-2 text-xs">
          <p className="text-ink-muted">Trigger: <b>{fmt.label(ex.trigger)}</b> · strategy {fmt.label(ex.strategy)}. Static plan Z={fmt.num(ex.static_policy?.objective, 1)} → re-optimised Z={fmt.num(ex.reoptimized?.objective, 1)}.</p>
          {ex.decisions.filter((d) => d.order_code).slice(0, 4).map((d) => (
            <div key={d.order_code} className="card p-2">
              <b>{d.order_code}</b> → {d.chosen_vehicle} (Δ {d.delta_cost}). Candidates: {d.candidates.map((c) => `${c.vehicle} ${c.delta_cost ?? '∞'}`).join(' · ')}
            </div>
          ))}
        </div>
      )}
      {cb && (
        <div className="mt-4">
          <div className="label mb-1.5">Cost breakdown of Z</div>
          <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-sunken">
            {Object.entries(cb).filter(([, v]) => v > 0).map(([k, v], i) => (
              <span key={k} title={`${k}: ${v}`} style={{ width: `${(v / total) * 100}%`, background: routePalette[i] }} />
            ))}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-2xs text-ink-muted">
            {Object.entries(cb).filter(([, v]) => v > 0).map(([k, v], i) => (
              <span key={k} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: routePalette[i] }} />{fmt.label(k)} {fmt.num(v)}</span>
            ))}
          </div>
        </div>
      )}
      {ex.convergence?.length > 2 && (
        <div className="mt-4">
          <div className="label mb-1">GA convergence (best Z per generation)</div>
          <ResponsiveContainer width="100%" height={90}>
            <LineChart data={ex.convergence.map((v, i) => ({ g: i, v }))}>
              <Line dataKey="v" stroke={colors.brand.DEFAULT} dot={false} strokeWidth={2} />
              <YAxis hide domain={['auto', 'auto']} /><XAxis dataKey="g" hide />
              <RTooltip formatter={(v) => fmt.num(v, 1)} labelFormatter={(g) => `generation ${g}`} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {plan?.shortest_path && (
        <p className="mt-3 text-2xs text-ink-muted">
          Travel-time matrix: {plan.matrix.dijkstra_runs} Dijkstra runs ({fmt.num(plan.matrix.runtime_ms)} ms).
          Road legs: {plan.shortest_path.legs} × {fmt.label(plan.shortest_path.algorithm)}, {fmt.num(plan.shortest_path.nodes_expanded)} nodes expanded.
        </p>
      )}
    </div>
  );
}

function ComparisonPanel({ rows }) {
  const best = Math.min(...rows.map((r) => r.objective));
  return (
    <Panel className="mt-6 p-6">
      <SectionTitle aside="same orders, same fleet, same objective">Algorithm comparison</SectionTitle>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr className="border-b border-surface-line">
              {['Algorithm', 'Objective Z', 'Distance', 'Duration', 'Late', 'Vehicles', 'Fuel', 'Runtime'].map((h) => <th key={h} className="px-3 py-2 text-left text-xs font-medium text-ink-muted">{h}</th>)}
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.algorithm} className={clsx('border-b border-surface-line last:border-0', r.objective === best && 'bg-ok-soft/50')}>
                  <td className="px-3 py-2 text-sm font-medium">{r.label}</td>
                  <td className="tabular px-3 py-2 text-sm">{fmt.num(r.objective, 1)}</td>
                  <td className="tabular px-3 py-2 text-sm">{fmt.km(r.distance_km)}</td>
                  <td className="tabular px-3 py-2 text-sm">{fmt.duration(r.duration_min)}</td>
                  <td className="tabular px-3 py-2 text-sm">{r.late_count}</td>
                  <td className="tabular px-3 py-2 text-sm">{r.vehicles_used}</td>
                  <td className="tabular px-3 py-2 text-sm">{fmt.num(r.fuel_l, 1)} L</td>
                  <td className="tabular px-3 py-2 text-sm">{fmt.num(r.runtime_ms)} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={rows.filter((r) => r.algorithm !== 'fifo')} layout="vertical" margin={{ left: 10 }}>
            <CartesianGrid horizontal={false} stroke={chart.grid} />
            <XAxis type="number" tick={{ fontSize: 11, fill: chart.axis }} />
            <YAxis type="category" dataKey="algorithm" width={120} tick={{ fontSize: 11, fill: chart.axis }} tickFormatter={fmt.label} />
            <RTooltip formatter={(v) => fmt.num(v, 1)} />
            <RBar dataKey="objective" name="Objective Z (FIFO omitted – off scale)" fill={colors.brand.DEFAULT} radius={[0, 6, 6, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}
