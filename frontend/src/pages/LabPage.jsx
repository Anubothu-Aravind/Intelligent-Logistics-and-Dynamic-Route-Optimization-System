import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import clsx from 'clsx';
import { Marker, Polyline, Tooltip as LTooltip } from 'react-leaflet';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  BookOpen, ChevronFirst, ChevronLast, FlaskConical, Pause, Play, RotateCcw, Route, Square, StepBack, StepForward,
} from 'lucide-react';
import CityMap, { MapControls } from '../components/map/CityMap';
import ExploreLayer from '../components/lab/ExploreLayer';
import { pinIcon } from '../components/map/markers';
import {
  Bar as Progress, Badge, Button, Chip, Empty, ErrorState, Field, PageHeader, Panel, SectionTitle, Segmented, Spinner, Td, Th, Toggle,
} from '../components/ui';
import { api } from '../api/client';
import { useToast } from '../hooks/toast';
import { useConfirm } from '../hooks/confirm';
import { useAction, useApi } from '../hooks/useApi';
import { fmt } from '../lib/format';
import { chart, colors, routePalette } from '../theme/tokens';

const axis = { tick: { fontSize: 11, fill: chart.axis }, axisLine: false, tickLine: false };
const tooltipStyle = { contentStyle: { borderRadius: 12, border: `1px solid ${colors.surface.line}`, fontSize: 12 } };
const SP = { dijkstra: 'Dijkstra', astar: 'A*', bidirectional_dijkstra: 'Bidirectional Dijkstra' };

export default function LabPage() {
  const [tab, setTab] = useState('visualizer');
  return (
    <div className="h-full overflow-y-auto p-6">
      <PageHeader title="Algorithm lab" subtitle="See how the routing algorithms work, measure them on identical inputs, and read what each one does in this system."
        actions={<Segmented value={tab} onChange={setTab} options={[
          { value: 'visualizer', label: 'Path visualizer' }, { value: 'bench', label: 'Benchmarks' }, { value: 'docs', label: 'Algorithm reference' }]} />} />
      <div key={tab} className="anim-page">
        {tab === 'visualizer' && <Visualizer />}
        {tab === 'bench' && <Benchmarks />}
        {tab === 'docs' && <Reference />}
      </div>
    </div>
  );
}

/* ============================================================ visualizer */
function Visualizer() {
  const toast = useToast();
  const { busy, run } = useAction(toast);
  const [a, setA] = useState(null);
  const [b, setB] = useState(null);
  const [metric, setMetric] = useState('time');
  const [algo, setAlgo] = useState('astar');
  const [res, setRes] = useState(null);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [showAlts, setShowAlts] = useState(false);

  const pick = (ll) => {
    setPlaying(false);
    if (!a || (a && b)) { setA(ll); setB(null); setRes(null); setStep(0); } else setB(ll);
  };
  useEffect(() => {
    if (!a || !b) return;
    run('trace', () => api.post('/network/path/trace', {
      source_lat: a.lat, source_lon: a.lng, target_lat: b.lat, target_lon: b.lng, metric,
    })).then((r) => { if (r) { setRes(r); setStep(0); setPlaying(true); } });
  }, [a, b, metric, run]);

  const cur = res?.results?.[algo];
  const total = cur?.expanded_nodes?.length || 0;
  useEffect(() => { setStep(0); if (res) setPlaying(true); }, [algo]); // eslint-disable-line react-hooks/exhaustive-deps

  // play ≈ 6 s for a full run at 1×, independent of graph size
  const raf = useRef(null);
  useEffect(() => {
    if (!playing || !total) return undefined;
    let last = performance.now();
    const perMs = (total / 6000) * speed;
    let acc = 0;
    const tick = (now) => {
      acc += (now - last) * perMs;
      last = now;
      const inc = Math.floor(acc);
      if (inc > 0) {
        acc -= inc;
        setStep((s) => {
          const n = Math.min(total, s + inc);
          if (n >= total) setPlaying(false);
          return n;
        });
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [playing, total, speed]);

  const stepBy = (d) => { setPlaying(false); setStep((s) => Math.max(0, Math.min(total, s + d))); };
  const finished = total > 0 && step >= total;
  const dj = res?.results?.dijkstra;
  const insight = useMemo(() => {
    if (!res) return null;
    const r = res.results;
    const pct = (x) => Math.round((x.expanded / Math.max(1, r.dijkstra.expanded)) * 100);
    return [
      `All three algorithms return the same ${metric === 'time' ? 'travel time' : 'distance'} (${fmt.num(r.astar.cost, 2)} ${metric === 'time' ? 'min' : 'm'}) – they are exact.`,
      `Dijkstra grows a circle around A and settled ${r.dijkstra.expanded} of ${res.graph_nodes} intersections before reaching B.`,
      `A* settled only ${r.astar.expanded} (${pct(r.astar)} %): its heuristic (${res.heuristic}) never over-estimates, so it can safely prefer nodes that point towards B.`,
      `Bidirectional Dijkstra settled ${r.bidirectional_dijkstra.expanded} (${pct(r.bidirectional_dijkstra)} %): two half-size circles from A and B (orange and blue) cover less area than one big one.`,
      `Runtime also depends on work per node: A*'s heuristic adds a little cost per expansion, which is why fewer nodes does not always mean proportionally less time.`,
    ];
  }, [res, metric]);

  return (
    <Panel className="p-5">
      <SectionTitle aside={busy === 'trace' ? 'computing…' : !a ? 'click an origin on the map' : !b ? 'now click a destination' : 'click the map again to start over'}>
        <span className="flex items-center gap-2"><Route className="h-4 w-4" />Shortest-path visualizer</span>
      </SectionTitle>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div>
          <div className="relative h-[520px] overflow-hidden rounded-card border border-surface-line">
            <CityMap className="h-full w-full" onClick={pick}>
              <MapControls bottom={16} />
              {cur && <ExploreLayer points={cur.expanded_nodes} step={step} forward={colors.brand.DEFAULT} backward={routePalette[1]} frontier={colors.ink.DEFAULT} />}
              {showAlts && res?.alternatives.slice(1).map((p, i) => (
                <Polyline key={i} positions={p.coords} pathOptions={{ color: routePalette[(i + 2) % routePalette.length], weight: 4, dashArray: '8 8' }}>
                  <LTooltip sticky className="chip-tooltip">Alternative #{i + 2} · {fmt.num(p.time_min, 1)} min · {fmt.km(p.distance_m / 1000)}</LTooltip>
                </Polyline>
              ))}
              {cur && finished && <Polyline positions={cur.coords} pathOptions={{ color: colors.ink.DEFAULT, weight: 6 }} />}
              {a && <Marker position={res ? res.source_coords : a} icon={pinIcon('A', colors.ink.DEFAULT)} />}
              {b && <Marker position={res ? res.target_coords : b} icon={pinIcon('B', colors.brand.DEFAULT)} />}
            </CityMap>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" icon={ChevronFirst} disabled={!total} onClick={() => { setPlaying(false); setStep(0); }} aria-label="Reset to start" title="Reset" />
              <Button size="sm" variant="ghost" icon={StepBack} disabled={!total || step === 0} onClick={() => stepBy(-1)} aria-label="Previous step" title="Previous step" />
              <Button size="sm" variant="dark" icon={playing ? Pause : Play} disabled={!total}
                onClick={() => { if (finished) setStep(0); setPlaying((p) => !p); }}>{playing ? 'Pause' : finished ? 'Replay' : 'Play'}</Button>
              <Button size="sm" variant="ghost" icon={StepForward} disabled={!total || finished} onClick={() => stepBy(1)} aria-label="Next step" title="Next step" />
              <Button size="sm" variant="ghost" icon={ChevronLast} disabled={!total || finished} onClick={() => { setPlaying(false); setStep(total); }} aria-label="Jump to result" title="Jump to result" />
            </div>
            <Segmented size="sm" value={speed} onChange={setSpeed} options={[0.25, 1, 4].map((s) => ({ value: s, label: `${s}×` }))} />
            <input type="range" min="0" max={total} value={step} disabled={!total} aria-label="Exploration step"
              onChange={(e) => { setPlaying(false); setStep(Number(e.target.value)); }} className="min-w-[160px] flex-1 accent-[theme(colors.brand.DEFAULT)]" />
            <span className="tabular w-36 text-right font-mono text-xs text-ink-muted">{step} / {total} settled</span>
          </div>
        </div>
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Segmented value={algo} onChange={setAlgo} options={Object.entries(SP).map(([value, label]) => ({ value, label }))} size="sm" />
            <Segmented value={metric} onChange={setMetric} size="sm" options={[{ value: 'time', label: 'Fastest' }, { value: 'distance', label: 'Shortest' }]} />
          </div>
          {res ? (
            <>
              <table className="w-full">
                <thead><tr className="border-b border-surface-line"><Th>Algorithm</Th><Th>Cost</Th><Th>Settled</Th><Th>Time</Th></tr></thead>
                <tbody>{Object.entries(res.results).map(([k, r]) => (
                  <tr key={k} onClick={() => setAlgo(k)} className={clsx('cursor-pointer border-b border-surface-line transition-colors last:border-0', k === algo ? 'bg-brand-soft/60' : 'hover:bg-surface-subtle')}>
                    <Td className="font-medium">{SP[k]}</Td>
                    <Td className="tabular font-mono text-xs">{fmt.num(r.cost, 2)} {metric === 'time' ? 'min' : 'm'}</Td>
                    <Td className="tabular">{r.expanded}<span className="ml-1 text-2xs text-ink-muted">{Math.round((r.expanded / Math.max(1, dj.expanded)) * 100)}%</span></Td>
                    <Td className="tabular text-xs">{fmt.num(r.runtime_ms, 2)} ms</Td>
                  </tr>))}
                </tbody>
              </table>
              <div className="flex items-center gap-4 text-2xs text-ink-muted">
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: colors.brand.DEFAULT }} />settled (forward)</span>
                {algo === 'bidirectional_dijkstra' && <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: routePalette[1] }} />settled (backward)</span>}
                <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full border-2 border-ink" />current node</span>
              </div>
              <div className="card space-y-1.5 p-3 text-xs text-ink-soft">
                <div className="font-semibold text-ink">What you are seeing</div>
                {insight.map((t) => <p key={t}>{t}</p>)}
              </div>
              <div className="space-y-1 text-xs">
                <div className="flex items-center justify-between">
                  <span className="label">Yen's alternative routes</span>
                  <Toggle checked={showAlts} onChange={setShowAlts} label="show on map" />
                </div>
                {res.alternatives.map((p, i) => (
                  <div key={i} className="flex justify-between"><span>#{i + 1}{i === 0 && ' (optimal)'}</span>
                    <span className="tabular font-mono">{fmt.num(p.time_min, 1)} min · {fmt.km(p.distance_m / 1000)} · {p.hops} segments</span></div>
                ))}
              </div>
            </>
          ) : <Empty icon={Route} title="Pick an origin and a destination">Click two points on the map. Points snap to the nearest intersection of the road graph.</Empty>}
        </div>
      </div>
    </Panel>
  );
}

/* ============================================================ benchmarks */
function Benchmarks() {
  const toast = useToast();
  const confirm = useConfirm();
  const { busy, run } = useAction(toast);
  const defaults = useApi('/benchmarks/defaults', [], { ttl: 60000 });
  const history = useApi('/benchmarks/runs');
  const [form, setForm] = useState(null);
  const [status, setStatus] = useState(null);
  const [viewId, setViewId] = useState(null);
  const detail = useApi(viewId ? `/benchmarks/runs/${viewId}` : null, [viewId]);

  useEffect(() => {
    api.get('/benchmarks/status').then((s) => { if (s.running) setStatus(s); }).catch(() => {});
  }, []);
  useEffect(() => {
    if (!defaults.data || form) return;
    const d = defaults.data;
    setForm({
      graph: d.graph_sizes.map(([r, c]) => `${r}x${c}`), vrp: [...d.vrp_sizes], vehicles: d.vrp_vehicles, queries: d.path_queries,
      ga: d.ga_generations, timeout: d.experiment_timeout_s, spAlgos: [...d.shortest_path_algorithms],
      vrpAlgos: d.vrp_algorithms.filter((a) => a !== 'ortools' || d.ortools_available), ortools: d.ortools_available,
    });
  }, [defaults.data, form]);
  useEffect(() => {
    if (!history.data || viewId || status?.running) return;
    if (history.data.runs[0]) setViewId(history.data.runs[0].id);
  }, [history.data]); // eslint-disable-line react-hooks/exhaustive-deps

  // real progress: poll while a run is active
  useEffect(() => {
    if (!status?.running) return undefined;
    const t = setInterval(async () => {
      try {
        const s = await api.get('/benchmarks/status');
        setStatus(s);
        if (!s.running) {
          history.reload();
          setViewId(s.run_id);
          detail.reload();
          if (s.error) toast.push(`Benchmark failed: ${s.error}`, 'bad');
          else toast.push(`Benchmark ${s.message} – ${s.done}/${s.total} experiments`, s.message === 'finished' ? 'ok' : 'bad');
        }
      } catch { /* keep polling */ }
    }, 1000);
    return () => clearInterval(t);
  }, [status?.running]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (key, v) => setForm((f) => ({ ...f, [key]: f[key].includes(v) ? f[key].filter((x) => x !== v) : [...f[key], v] }));
  const start = () => {
    if (!form.vrp.length && !form.graph.length) { toast.push('Select at least one graph size or order count', 'bad'); return; }
    run('bench', async () => {
      const s = await api.post('/benchmarks', {
        graph_sizes: form.spAlgos.length ? form.graph.map((g) => g.split('x').map(Number)) : [],
        path_queries: Number(form.queries), vrp_sizes: form.vrpAlgos.length ? form.vrp.map(Number) : [],
        vrp_vehicles: Number(form.vehicles), ga_generations: Number(form.ga), timeout_s: Number(form.timeout),
        shortest_path_algorithms: form.spAlgos, vrp_algorithms: form.vrpAlgos, include_ortools: form.ortools,
      });
      setStatus(s);
      setViewId(null);
      return s;
    }, 'Benchmark started – every experiment runs in its own process');
  };
  const cancel = async () => {
    const ok = await confirm({ title: 'Stop the benchmark?', confirmLabel: 'Stop benchmark', tone: 'danger',
      body: 'The experiment that is running now is stopped. Results of finished experiments are kept.' });
    if (ok) run('cancel', () => api.post('/benchmarks/cancel'), 'Stopping…');
  };

  const running = status?.running;
  const results = running ? status.results : detail.data?.results;
  const d = defaults.data;
  if (defaults.error && !d) return <Panel><ErrorState message={defaults.error} onRetry={defaults.reload} /></Panel>;
  return (
    <div className="space-y-6">
      <Panel className="p-5">
        <SectionTitle aside="each experiment runs isolated, with a timeout"><span className="flex items-center gap-2"><FlaskConical className="h-4 w-4" />Configure experiments</span></SectionTitle>
        {!form ? <Spinner /> : (
          <div className="grid gap-5 lg:grid-cols-2">
            <div className="space-y-3">
              <div className="label">Shortest-path algorithms</div>
              <div className="flex flex-wrap gap-1.5">{d.shortest_path_algorithms.map((x) => <Chip key={x} active={form.spAlgos.includes(x)} onClick={() => toggle('spAlgos', x)}>{d.sp_labels[x]}</Chip>)}</div>
              <div className="label">Graphs (synthetic grids of controlled size, and the real map)</div>
              <div className="flex flex-wrap gap-1.5">{['10x10', '20x20', '35x35', '50x50', '0x0'].map((g) => (
                <Chip key={g} active={form.graph.includes(g)} onClick={() => toggle('graph', g)}>{g === '0x0' ? 'Vijayawada (real map)' : g}</Chip>))}</div>
              <Field label="Random path queries per graph"><input type="number" min="1" max="1000" className="input w-32" value={form.queries} onChange={(e) => setForm({ ...form, queries: e.target.value })} /></Field>
            </div>
            <div className="space-y-3">
              <div className="label">Routing algorithms</div>
              <div className="flex flex-wrap gap-1.5">{Object.keys(d.vrp_labels).map((x) => (
                <Chip key={x} active={form.vrpAlgos.includes(x)} onClick={() => (x !== 'ortools' || d.ortools_available) && toggle('vrpAlgos', x)}>
                  {d.vrp_labels[x]}{x === 'ortools' && !d.ortools_available ? ' (not installed)' : ''}</Chip>))}</div>
              <div className="label">Number of orders</div>
              <div className="flex flex-wrap items-center gap-1.5">
                {[...d.vrp_sizes, ...d.optional_vrp_sizes].map((n) => <Chip key={n} active={form.vrp.includes(n)} onClick={() => toggle('vrp', n)}>{n}</Chip>)}
                {form.vrp.some((n) => d.optional_vrp_sizes.includes(n)) && <span className="text-2xs text-warn">large – slow algorithms may hit the timeout</span>}
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Vehicles"><input type="number" min="1" max="200" className="input" value={form.vehicles} onChange={(e) => setForm({ ...form, vehicles: e.target.value })} /></Field>
                <Field label="GA generations"><input type="number" min="1" max="2000" className="input" value={form.ga} onChange={(e) => setForm({ ...form, ga: e.target.value })} /></Field>
                <Field label="Timeout / experiment (s)"><input type="number" min="5" max="3600" className="input" value={form.timeout} onChange={(e) => setForm({ ...form, timeout: e.target.value })} /></Field>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3 lg:col-span-2">
              <Button variant="dark" icon={Play} busy={busy === 'bench'} disabled={running} onClick={start}>Run experiments</Button>
              {running && <Button variant="danger" icon={Square} busy={busy === 'cancel'} onClick={cancel}>Stop</Button>}
              {running && (
                <div className="min-w-[240px] flex-1">
                  <Progress value={status.progress} color={colors.brand.DEFAULT} className="h-2" />
                  <div className="mt-1 text-xs text-ink-muted"><b className="tabular">{status.done}/{status.total}</b> experiments · {status.current || status.message}</div>
                </div>
              )}
            </div>
          </div>
        )}
      </Panel>

      <Panel className="p-5">
        <SectionTitle aside={history.data?.runs?.length ? (
          <select className="input h-8 w-64" value={running ? '' : viewId || ''} disabled={running} onChange={(e) => setViewId(Number(e.target.value))} aria-label="Benchmark run">
            {running && <option value="">Current run (live)</option>}
            {history.data.runs.map((r) => <option key={r.id} value={r.id}>#{r.id} · {new Date(r.created_at).toLocaleString()} · {r.status}</option>)}
          </select>) : null}>Results</SectionTitle>
        {results ? <BenchResults results={results} /> : running ? <Spinner label="Waiting for the first experiment…" />
          : <Empty icon={FlaskConical} title="No results yet">Configure and run the experiments above. Results are saved after every experiment.</Empty>}
      </Panel>
    </div>
  );
}

function pivot(rows, x, series, value) {
  const map = new Map();
  rows.filter((r) => r.status === 'ok' && r[value] !== undefined).forEach((r) => {
    if (!map.has(r[x])) map.set(r[x], { [x]: r[x] });
    map.get(r[x])[r.label || r[series]] = r[value];
  });
  return [...map.values()].sort((p, q) => p[x] - q[x]);
}

function BenchResults({ results }) {
  const sp = results.shortest_path || [];
  const vrp = results.vrp || [];
  const charts = [
    sp.length && { title: 'Shortest path · avg. time per query (ms, log)', data: pivot(sp, 'nodes', 'algorithm', 'avg_runtime_ms'), x: 'nodes', log: true },
    sp.length && { title: 'Shortest path · nodes explored per query', data: pivot(sp.filter((r) => r.algorithm !== 'floyd_warshall'), 'nodes', 'algorithm', 'avg_expanded'), x: 'nodes' },
    vrp.length && { title: 'Routing · objective Z (lower is better, log)', data: pivot(vrp, 'orders', 'algorithm', 'objective'), x: 'orders', bar: true, log: true },
    vrp.length && { title: 'Routing · improvement vs FIFO (%)', data: pivot(vrp.filter((r) => r.algorithm !== 'fifo'), 'orders', 'algorithm', 'improvement_vs_fifo_pct'), x: 'orders', bar: true },
    vrp.length && { title: 'Routing · runtime (ms, log)', data: pivot(vrp, 'orders', 'algorithm', 'runtime_ms'), x: 'orders', bar: true, log: true },
    vrp.length && { title: 'Routing · late deliveries', data: pivot(vrp, 'orders', 'algorithm', 'late_count'), x: 'orders', bar: true },
  ].filter(Boolean);
  return (
    <div className="space-y-6">
      {results.failures?.length > 0 && (
        <div className="rounded-card bg-warn-soft p-3 text-xs">
          <b>{results.failures.length} experiment(s) did not finish:</b>
          <ul className="mt-1 list-disc pl-5">{results.failures.map((f) => <li key={f.experiment}>{f.experiment} – {f.status} ({f.note})</li>)}</ul>
        </div>
      )}
      <div className="grid gap-5 xl:grid-cols-2">{charts.map((c) => <ChartCard key={c.title} {...c} />)}</div>
      {vrp.length > 0 && <ResultTable title="Routing experiments" rows={vrp} cols={['orders', 'label', 'status', 'objective', 'improvement_vs_fifo_pct', 'distance_km', 'late_count', 'vehicles_used', 'utilization', 'feasible', 'runtime_ms', 'cpu_ms', 'peak_kb']} />}
      {sp.length > 0 && <ResultTable title="Shortest-path experiments" rows={sp} cols={['graph', 'nodes', 'label', 'status', 'avg_runtime_ms', 'avg_expanded', 'avg_cost_min', 'peak_kb', 'precompute_ms']} />}
    </div>
  );
}

function ChartCard({ title, data, x, log, bar }) {
  const keys = [...new Set(data.flatMap((dd) => Object.keys(dd).filter((k) => k !== x)))];
  const Chart = bar ? BarChart : LineChart;
  if (!data.length) return null;
  return (
    <div className="rounded-card border border-surface-line p-4">
      <div className="mb-2 text-sm font-semibold">{title}</div>
      <ResponsiveContainer width="100%" height={250}>
        <Chart data={data}>
          <CartesianGrid vertical={false} stroke={chart.grid} />
          <XAxis dataKey={x} {...axis} />
          <YAxis {...axis} width={56} scale={log ? 'log' : 'auto'} domain={log ? ['auto', 'auto'] : ['auto', 'auto']} allowDataOverflow />
          <Tooltip {...tooltipStyle} formatter={(v) => fmt.num(v, 2)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {keys.map((k, i) => (bar
            ? <Bar key={k} dataKey={k} fill={routePalette[i % routePalette.length]} radius={[3, 3, 0, 0]} />
            : <Line key={k} dataKey={k} stroke={routePalette[i % routePalette.length]} strokeWidth={2} dot />))}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}

function ResultTable({ title, rows, cols }) {
  return (
    <div>
      <div className="mb-2 text-sm font-semibold">{title}</div>
      <div className="overflow-x-auto rounded-card border border-surface-line">
        <table className="w-full">
          <thead><tr className="border-b border-surface-line">{cols.map((c) => <Th key={c}>{fmt.label(c).replace('Pct', '%').replace('Kb', 'KB')}</Th>)}</tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={i} className="border-b border-surface-line last:border-0">
              {cols.map((c) => (
                <Td key={c} className={clsx(typeof r[c] === 'number' && 'tabular')}>
                  {c === 'status' ? <Badge tone={r.status === 'ok' ? 'ok' : r.status === 'skipped' ? 'idle' : 'bad'}>{r.status}</Badge>
                    : typeof r[c] === 'boolean' ? (r[c] ? 'yes' : 'no')
                      : c === 'utilization' && typeof r[c] === 'number' ? fmt.pct(r[c])
                        : typeof r[c] === 'number' ? fmt.num(r[c], 2) : (r[c] ?? (c === 'objective' && r.note ? r.note : '–'))}
                </Td>))}
            </tr>))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ============================================================ reference */
const DOCS = [
  { name: 'Dijkstra', group: 'Shortest paths', purpose: 'Exact shortest / fastest path between intersections.',
    how: 'Settles nodes in order of distance from the source using a binary-heap priority queue; the first time the target is settled its cost is optimal (all edge weights ≥ 0).',
    time: 'O((V + E) log V)', space: 'O(V)', pros: 'Exact, simple, robust to any non-negative weights.', cons: 'Explores in all directions – a circle around the source.',
    used: 'Builds the travel-time matrix between stops (one run per stop); fallback when A* finds no path; reference in benchmarks.', params: ['algorithms.default_shortest_path'] },
  { name: 'A* search', group: 'Shortest paths', purpose: 'Exact point-to-point routing for vehicles and plan legs (default).',
    how: 'Dijkstra ordered by g(n) + h(n); h = straight-line distance (÷ max speed limit for travel time). h never over-estimates, so the result stays optimal.',
    time: 'O((V + E) log V) worst case, far fewer expansions in practice', space: 'O(V)', pros: 'Same answer as Dijkstra while exploring a fraction of the graph.',
    cons: 'Needs coordinates and an admissible heuristic; heavy congestion makes the heuristic less informative.', used: 'Vehicle legs in the simulation, plan road legs, re-routing after congestion/closures.', params: ['algorithms.default_shortest_path'] },
  { name: 'Bidirectional Dijkstra', group: 'Shortest paths', purpose: 'Exact point-to-point search from both ends.',
    how: 'Runs a forward search from A and a backward search from B (on reversed edges) and stops when the best meeting cost cannot improve.',
    time: 'O((V + E) log V), roughly half the area of Dijkstra', space: 'O(V)', pros: 'No heuristic needed.', cons: 'Two queues, more bookkeeping; needs reverse adjacency.',
    used: 'Selectable for road legs on Route & dispatch; compared in the visualizer and alternatives panel.', params: [] },
  { name: 'Floyd–Warshall', group: 'Shortest paths', purpose: 'All-pairs reference on small graphs.',
    how: 'Dynamic programming: for every k, i, j relax d[i][j] with d[i][k] + d[k][j].',
    time: 'O(V³)', space: 'O(V²)', pros: 'Answers every pair at once.', cons: 'Cubic – only usable on small graphs.',
    used: 'Benchmarks and the path query endpoint when the graph has at most floyd_warshall_max_nodes nodes.', params: ['algorithms.floyd_warshall_max_nodes'] },
  { name: "Yen's K-shortest paths", group: 'Shortest paths', purpose: 'Loop-less alternative routes ("why this road?").',
    how: 'Takes the best path, then for every node on it computes a detour that avoids the edges already used by earlier paths with the same prefix.',
    time: 'O(K · V · (E + V log V))', space: 'O(K · V)', pros: 'Shows the operator real alternatives.', cons: 'Expensive for large K.',
    used: 'Vehicle detail “Alternative roads”, visualizer alternatives.', params: ['algorithms.k_alternative_paths'] },
  { name: 'FIFO baseline', group: 'Construction', purpose: 'The naive dispatcher every result is compared with.',
    how: 'Orders in arrival order, filling the largest vehicle first, visiting stops in arrival order.',
    time: 'O(n)', space: 'O(n)', pros: 'Trivial, predictable.', cons: 'Ignores geography and deadlines.', used: '“Before” numbers on Analytics and benchmarks.', params: [] },
  { name: 'Nearest Neighbour', group: 'Construction', purpose: 'Fast greedy routes.',
    how: 'Each vehicle repeatedly drives to the closest feasible customer (capacity-aware, nudged by deadlines) until full; leftovers go to Regret-2 insertion.',
    time: 'O(n²)', space: 'O(n)', pros: 'Very fast.', cons: 'Myopic – late customers end up far apart.', used: 'Routing option; seed for the GA.', params: [] },
  { name: 'Clarke–Wright Savings', group: 'Construction', purpose: 'Classic CVRP construction (default).',
    how: 'Start with one route per customer; merge route ends in decreasing order of saving s(i,j) = d(0,i) + d(0,j) − d(i,j) while capacity allows.',
    time: 'O(n² log n)', space: 'O(n²)', pros: 'Good distance quality quickly.', cons: 'Ignores time windows during merging.', used: 'Default routing algorithm; GA seed.', params: ['algorithms.default_construction'] },
  { name: 'Sweep', group: 'Construction', purpose: 'Geographic clustering.',
    how: 'Sort customers by polar angle around the depot, cut the sweep into capacity-feasible clusters, sequence each cluster with nearest neighbour.',
    time: 'O(n log n)', space: 'O(n)', pros: 'Compact, non-overlapping areas per vehicle.', cons: 'Poor with tight time windows.', used: 'Routing option; GA seed.', params: [] },
  { name: 'Regret-2 insertion', group: 'Construction / dynamic', purpose: 'Insert orders where postponing them would hurt most.',
    how: 'For each open order compute its best and second-best insertion over all vehicles; insert the one with the largest difference (regret) first. Cached per route – only the changed route is re-evaluated.',
    time: 'O(p · L) per insertion after O(p · m · L) setup', space: 'O(p · m)', pros: 'Good, explainable decisions (candidate costs are shown).',
    cons: 'Greedy.', used: 'Every dynamic event (new order, deletion), leftover orders of constructions.', params: ['simulation.reoptimize_strategy'] },
  { name: '2-opt', group: 'Local search', purpose: 'Remove crossings within a route.',
    how: 'Reverse a segment of the route whenever that lowers the route cost (first improvement, repeated until no gain).',
    time: 'O(L²) moves per pass', space: 'O(L)', pros: 'Removes obvious detours.', cons: 'Reversal can break time windows (the cost function decides).', used: 'Local search after construction and in re-planning.', params: ['algorithms.default_improvement', 'algorithms.local_search_max_iterations'] },
  { name: 'Or-opt', group: 'Local search', purpose: 'Move short chains inside a route.',
    how: 'Relocate segments of 1–3 consecutive stops to a better position in the same route.',
    time: 'O(L²) per pass', space: 'O(L)', pros: 'Keeps segment direction – friendly to time windows.', cons: 'Intra-route only.', used: 'Local search.', params: ['algorithms.default_improvement'] },
  { name: 'Relocate', group: 'Local search', purpose: 'Move one order to another vehicle.',
    how: 'Remove a customer and insert it at its best position in another route; granular neighbourhood: only next to its k nearest customers.',
    time: 'O(n · k) per pass', space: 'O(n · k)', pros: 'Balances work between vehicles.', cons: 'Loaded parcels cannot change vehicle (locked).', used: 'Local search; dynamic re-planning.', params: ['algorithms.granular_neighbours'] },
  { name: 'Swap', group: 'Local search', purpose: 'Exchange orders between vehicles.',
    how: 'Exchange two customers of different routes when the combined cost drops (granular candidates).',
    time: 'O(n · k) per pass', space: 'O(n)', pros: 'Escapes moves Relocate cannot.', cons: 'Can be blocked by capacity.', used: 'Local search.', params: ['algorithms.granular_neighbours'] },
  { name: 'Genetic algorithm (memetic)', group: 'Meta-heuristic', purpose: 'Search beyond local optima.',
    how: 'Chromosome = giant tour of all orders; Prins Split optimally cuts it into trips; tournament selection, OX crossover, swap/inversion mutation, elitism; best solution is polished with local search. Seeded with NN, CW and Sweep.',
    time: 'O(G · P · n · L)', space: 'O(P · n)', pros: 'Explores widely; convergence curve shown.', cons: 'Slower; a pure GA (no seeds/local search) scales poorly – see benchmarks.',
    used: 'Routing option “Genetic Algorithm”.', params: ['algorithms.genetic.population_size', 'algorithms.genetic.generations', 'algorithms.genetic.mutation_rate', 'algorithms.genetic.time_limit_s'] },
  { name: 'Google OR-Tools (reference)', group: 'Reference', purpose: 'External comparison only – never the main engine.',
    how: 'OR-Tools routing with capacity and time dimensions, soft deadlines and guided local search within a time limit.',
    time: 'time-limited', space: '–', pros: 'Strong industrial baseline.', cons: 'Black box, external dependency.', used: 'Compare all, benchmarks (when installed).', params: ['algorithms.ortools_time_limit_s'] },
];

function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), obj);
}

function Reference() {
  const cfg = useApi('/config', [], { ttl: 30000 });
  const [group, setGroup] = useState('all');
  const groups = ['all', ...new Set(DOCS.map((d) => d.group))];
  const objective = cfg.data?.objective;
  return (
    <div className="space-y-5">
      <Panel className="p-5">
        <SectionTitle aside="backend/app/algorithms"><span className="flex items-center gap-2"><BookOpen className="h-4 w-4" />Objective optimised by every routing algorithm</span></SectionTitle>
        <p className="font-mono text-sm">Z = α·D + β·T + γ·L + δ·V + ε·W (+ overtime, capacity and unassigned penalties)</p>
        {objective ? (
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            {[['α distance /km', objective.alpha_distance_per_km], ['β route time /min', objective.beta_time_per_min], ['γ lateness /min', objective.gamma_lateness_per_min],
              ['δ per vehicle (once a day)', objective.delta_vehicle_fixed], ['ε customer waiting /min', objective.epsilon_waiting_per_min],
              ['max route length', `${objective.max_route_duration_min} min`], ['overtime /min', objective.route_overtime_penalty_per_min], ['capacity penalty /kg', objective.capacity_violation_penalty]].map(([l, v]) => (
              <div key={l} className="card px-3 py-2"><div className="text-ink-muted">{l}</div><div className="tabular font-semibold">{v ?? '–'}</div></div>
            ))}
          </div>
        ) : cfg.error ? <ErrorState message={cfg.error} onRetry={cfg.reload} /> : <Spinner />}
      </Panel>
      <div className="flex flex-wrap gap-1.5">{groups.map((g) => <Chip key={g} active={group === g} onClick={() => setGroup(g)}>{g === 'all' ? 'All' : g}</Chip>)}</div>
      <div className="grid gap-4 lg:grid-cols-2">
        {DOCS.filter((d) => group === 'all' || d.group === group).map((d) => (
          <Panel key={d.name} className="p-5">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-base font-bold">{d.name}</h3><Badge>{d.group}</Badge>
            </div>
            <p className="mt-1 text-sm text-ink-soft">{d.purpose}</p>
            <p className="mt-2 text-sm">{d.how}</p>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
              <dt className="text-ink-muted">Time</dt><dd className="font-mono">{d.time}</dd>
              <dt className="text-ink-muted">Space</dt><dd className="font-mono">{d.space}</dd>
              <dt className="text-ink-muted">Strengths</dt><dd>{d.pros}</dd>
              <dt className="text-ink-muted">Limitations</dt><dd>{d.cons}</dd>
              <dt className="text-ink-muted">Used in this project</dt><dd>{d.used}</dd>
            </dl>
            {d.params.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {d.params.map((p) => {
                  const v = cfg.data ? getPath(cfg.data, p) : undefined;
                  return <span key={p} className="rounded-lg bg-surface-sunken px-2 py-1 font-mono text-2xs">{p} = {v === undefined ? '…' : JSON.stringify(v)}</span>;
                })}
              </div>
            )}
          </Panel>
        ))}
      </div>
    </div>
  );
}
