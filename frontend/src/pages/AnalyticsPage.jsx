import { useMemo, useState } from 'react';
import clsx from 'clsx';
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { BarChart3, CalendarClock } from 'lucide-react';
import {
  Button, Empty, ErrorState, Panel, SectionTitle, Segmented, Select, Skeleton, SkeletonRows, StatusBadge, Td, Th,
} from '../components/ui';
import { qs } from '../api/client';
import { useLive } from '../hooks/live';
import { useApi } from '../hooks/useApi';
import { fmt } from '../lib/format';
import { chart, colors, routePalette } from '../theme/tokens';

const axis = { tick: { fontSize: 11, fill: chart.axis }, axisLine: false, tickLine: false };
const tooltipStyle = {
  contentStyle: { borderRadius: 12, border: `1px solid ${colors.surface.line}`, boxShadow: '0 4px 16px rgba(20,22,26,.08)', fontSize: 12 },
  labelStyle: { fontWeight: 600, color: colors.ink.DEFAULT },
};
const toMin = (hhmm) => { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m; };
const PAGE = 10;

export default function AnalyticsPage() {
  const { state } = useLive();
  const [win, setWin] = useState('shift');
  const [custom, setCustom] = useState({ from: '', to: '' });
  const [runsDays, setRunsDays] = useState('');
  const shift = state ? { start: toMin(state.shift.start), end: toMin(state.shift.end), now: state.clock } : null;
  const range = useMemo(() => {
    if (!shift) return {};
    const noon = 12 * 60;
    switch (win) {
      case 'morning': return { from_min: shift.start, to_min: noon };
      case 'afternoon': return { from_min: noon, to_min: Math.max(shift.end, noon) };
      case 'now': return { from_min: shift.start, to_min: Math.floor(shift.now) };
      case 'custom': return custom.from && custom.to ? { from_min: toMin(custom.from), to_min: toMin(custom.to) } : {};
      default: return {};
    }
  }, [win, custom, shift?.start, shift?.end, win === 'now' ? Math.floor((shift?.now || 0) / 15) : 0]); // eslint-disable-line react-hooks/exhaustive-deps
  const k0 = state?.kpis;
  const liveKey = k0 ? `${Math.floor(k0.delivered / 3)}|${k0.total_orders}|${state.plan?.run_id}` : '';
  const { data, error, loading, reload } = useApi(`/analytics/summary${qs({ ...range, runs_since_days: runsDays })}`, [liveKey]);
  const [mode, setMode] = useState('vehicle');

  const header = (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[28px] font-extrabold tracking-tight">Analytics</h1>
        <p className="mt-1 text-sm text-ink-muted">Measured from the database and the running simulation – nothing on this page is sample data.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <CalendarClock className="h-4 w-4 text-ink-muted" />
        <Segmented value={win} onChange={setWin} size="sm" options={[
          { value: 'shift', label: 'Whole shift' }, { value: 'morning', label: 'Morning' }, { value: 'afternoon', label: 'Afternoon' },
          { value: 'now', label: 'Up to now' }, { value: 'custom', label: 'Custom' }]} />
        {win === 'custom' && (
          <span className="anim-fade flex items-center gap-1 text-sm">
            <input type="time" className="input h-8 w-28" value={custom.from} onChange={(e) => setCustom({ ...custom, from: e.target.value })} aria-label="From" />
            –<input type="time" className="input h-8 w-28" value={custom.to} onChange={(e) => setCustom({ ...custom, to: e.target.value })} aria-label="To" />
          </span>
        )}
        <Select className="h-8 w-44" value={runsDays} onChange={setRunsDays} options={[
          { value: '', label: 'Run history: all' }, { value: '1', label: 'Run history: 24 h' }, { value: '7', label: 'Run history: 7 days' }]} />
      </div>
    </header>
  );

  if (error && !data) return <div className="h-full overflow-y-auto p-6">{header}<Panel><ErrorState message={error} onRetry={reload} /></Panel></div>;
  if (!data) {
    return (
      <div className="h-full overflow-y-auto p-6">{header}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[76px]" />)}</div>
        <div className="mt-6 grid gap-5 xl:grid-cols-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-[320px]" />)}</div>
      </div>
    );
  }
  const k = data.kpis;
  const wk = data.window_kpis;
  const filtered = range.from_min !== undefined;
  const imp = data.before_after.improvement;
  const kpis = [
    { label: 'Total orders', value: fmt.num(k.total_orders) },
    { label: filtered ? 'Delivered (window)' : 'Delivered', value: fmt.num(filtered ? wk.delivered : k.delivered) },
    { label: 'Pending / in transit', value: `${fmt.num(k.pending)} / ${fmt.num(k.in_transit)}` },
    { label: 'Active vehicles', value: `${k.active_vehicles}/${k.fleet_size}` },
    { label: filtered ? 'On time (window)' : 'On time', value: fmt.pct(filtered ? wk.on_time_pct : k.on_time_pct, 1), tone: 'ok' },
    { label: 'Avg. delay of late', value: `${fmt.num(filtered ? wk.avg_delay_min : k.avg_delay_min, 1)} min`, tone: (filtered ? wk.late : k.late) ? 'warn' : undefined },
    { label: 'Distance driven', value: fmt.km(k.distance_km) },
    { label: 'Improvement vs FIFO', value: imp?.objective ? `${imp.objective.pct}%` : '–', tone: 'ok', hint: imp?.objective ? 'objective Z of the last plan' : 'optimise to measure' },
  ];
  const hourly = mode === 'vehicle'
    ? (data.deliveries_by_hour.actual.length ? data.deliveries_by_hour.actual : data.deliveries_by_hour.planned)
    : data.actual_vs_planned;
  const showingPlanned = mode === 'vehicle' && !data.deliveries_by_hour.actual.length;

  return (
    <div className={clsx('h-full overflow-y-auto p-6 transition-opacity', loading && 'opacity-80')}>
      {header}

      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-muted">Overview</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {kpis.map((c) => (
          <div key={c.label} className="rounded-card border border-surface-line bg-surface px-4 py-3" title={c.hint}>
            <div className="text-xs text-ink-muted">{c.label}</div>
            <div className={clsx('tabular mt-1 text-[22px] font-semibold', c.tone === 'ok' && 'text-ok', c.tone === 'warn' && 'text-warn')}>{c.value}</div>
          </div>
        ))}
      </div>

      <h2 className="mb-3 mt-8 text-xs font-semibold uppercase tracking-wider text-ink-muted">Performance</h2>
      <div className="grid gap-5 xl:grid-cols-3">
        <Panel className="p-5">
          <SectionTitle aside={<Segmented size="sm" value={mode} onChange={setMode} options={[{ value: 'vehicle', label: 'By vehicle' }, { value: 'avp', label: 'Actual vs planned' }]} />}>
            Deliveries per hour
          </SectionTitle>
          {hourly.length ? (
            <>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={hourly} barGap={2}>
                  <CartesianGrid vertical={false} stroke={chart.grid} />
                  <XAxis dataKey="hour" {...axis} /><YAxis allowDecimals={false} {...axis} width={28} />
                  <Tooltip {...tooltipStyle} cursor={{ fill: colors.surface.subtle }} />
                  {mode === 'vehicle'
                    ? data.deliveries_by_hour.vehicles.map((v, i) => <Bar key={v} dataKey={v} stackId="a" fill={routePalette[i % routePalette.length]} />)
                    : [<Bar key="p" dataKey="planned" name="Planned (current plan)" fill={chart.before} radius={[4, 4, 0, 0]} />,
                      <Bar key="a" dataKey="actual" name="Delivered" fill={chart.after} radius={[4, 4, 0, 0]} />]}
                  {mode === 'avp' && <Legend wrapperStyle={{ fontSize: 11 }} />}
                </BarChart>
              </ResponsiveContainer>
              {showingPlanned && <p className="mt-1 text-2xs text-ink-muted">No deliveries yet – showing planned arrivals of the current plan.</p>}
            </>
          ) : <Empty icon={BarChart3} title="No deliveries in this window">Optimise and run the simulation, or widen the time window.</Empty>}
        </Panel>

        <Panel className="p-5">
          <SectionTitle aside={data.before_after.algorithm ? `FIFO → ${fmt.label(data.before_after.algorithm)}` : ''}>FIFO vs optimised plan</SectionTitle>
          {imp ? (
            <div className="space-y-3.5">
              {[['distance_km', 'Total distance', 'km'], ['duration_min', 'Route time', 'min'], ['fuel_l', 'Fuel', 'L'], ['co2_kg', 'CO₂', 'kg'],
                ['late_count', 'Late deliveries', ''], ['vehicles_used', 'Vehicles used', '']].map(([key, label, unit]) => {
                const row = imp[key];
                if (!row) return null;
                const max = Math.max(row.before, row.after, 1e-9);
                const better = row.delta >= 0;
                return (
                  <div key={key}>
                    <div className="mb-1 flex justify-between text-xs"><span className="font-medium">{label}</span>
                      <span className={clsx('tabular font-semibold', row.delta === 0 ? 'text-ink-muted' : better ? 'text-ok' : 'text-bad')}>
                        {row.delta === 0 ? 'no change' : `${better ? '−' : '+'}${fmt.num(Math.abs(row.pct), 1)}%`}</span></div>
                    {[['before', chart.before], ['after', chart.after]].map(([w, c]) => (
                      <div key={w} className="mb-0.5 flex items-center gap-2">
                        <div className="h-2 flex-1 rounded-full bg-surface-sunken"><div className="h-2 rounded-full transition-[width] duration-700" style={{ width: `${(row[w] / max) * 100}%`, background: c }} /></div>
                        <span className="tabular w-24 text-right font-mono text-2xs text-ink-muted">{fmt.num(row[w], 1)} {unit}</span>
                      </div>
                    ))}
                  </div>
                );
              })}
              <div className="flex gap-4 pt-1 text-2xs text-ink-muted">
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: chart.before }} />FIFO (orders in arrival order)</span>
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: chart.after }} />Optimised</span>
              </div>
            </div>
          ) : <Empty title="No optimisation yet">Run <b>Optimise plan</b> on Route &amp; dispatch to compare against the FIFO baseline.</Empty>}
        </Panel>

        <Panel className="p-5">
          <SectionTitle aside={`${data.events.length} event(s)`}>Dynamic event impact</SectionTitle>
          {data.events.length ? (
            <>
              <ResponsiveContainer width="100%" height={210}>
                <ComposedChart data={[...data.events].reverse().map((e) => ({ ...e, label: `${e.time} · ${fmt.label(e.type)}` }))}>
                  <CartesianGrid vertical={false} stroke={chart.grid} />
                  <XAxis dataKey="time" {...axis} /><YAxis yAxisId="z" {...axis} width={44} />
                  <YAxis yAxisId="p" orientation="right" {...axis} width={36} unit="%" />
                  <Tooltip {...tooltipStyle} labelFormatter={(_, p) => p?.[0]?.payload?.label} formatter={(v) => fmt.num(v, 1)} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar yAxisId="z" dataKey="static_objective" name="Keep old plan (Z)" fill={chart.before} radius={[4, 4, 0, 0]} />
                  <Bar yAxisId="z" dataKey="reoptimized_objective" name="Re-optimised (Z)" fill={chart.after} radius={[4, 4, 0, 0]} />
                  <Line yAxisId="p" dataKey="saving_pct" name="Saving %" stroke={colors.ok.DEFAULT} strokeWidth={2} dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
              <ul className="mt-3 max-h-24 space-y-1 overflow-y-auto text-xs">
                {data.events.slice(0, 6).map((e) => (
                  <li key={e.id} className="flex justify-between gap-2">
                    <span className="truncate"><span className="font-mono text-ink-muted">{e.time}</span> {fmt.label(e.type)}
                      {e.decisions?.[0]?.order_code && ` · ${e.decisions[0].order_code} → ${e.decisions[0].chosen_vehicle}`}</span>
                    <span className={clsx('tabular font-medium', (e.saving_pct ?? 0) > 0 ? 'text-ok' : 'text-ink-muted')}>{e.saving_pct === null || e.saving_pct === undefined ? '–' : `${e.saving_pct}%`}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : <Empty title="No dynamic events in this window">Use <b>Simulate</b> on the live map to add orders, congestion or closures.</Empty>}
        </Panel>
      </div>

      <h2 className="mb-3 mt-8 text-xs font-semibold uppercase tracking-wider text-ink-muted">Operations</h2>
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        <Donut title="Delivery punctuality" data={data.outcomes.actual} fallback={data.outcomes.planned} colorsMap={chart.outcomes} />
        <Donut title="Orders by priority" colorsMap={chart.priorities}
          data={Object.fromEntries(Object.entries(data.priorities).map(([p, s]) => [p, Object.values(s).reduce((a, b) => a + b, 0)]))} />
        <Panel className="p-5">
          <SectionTitle aside="current plan">Stops &amp; distance per vehicle</SectionTitle>
          {data.per_vehicle.some((v) => v.stops) ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.per_vehicle.filter((v) => v.stops)} barGap={2}>
                <CartesianGrid vertical={false} stroke={chart.grid} />
                <XAxis dataKey="vehicle" {...axis} interval={0} angle={-30} textAnchor="end" height={44} />
                <YAxis {...axis} width={28} />
                <Tooltip {...tooltipStyle} cursor={{ fill: colors.surface.subtle }} /><Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="stops" name="Stops" fill={colors.ink.DEFAULT} radius={[4, 4, 0, 0]} />
                <Bar dataKey="distance_km" name="km" fill={colors.brand.DEFAULT} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <Empty title="No routes in the current plan" />}
        </Panel>
        <Panel className="p-5">
          <SectionTitle aside="load ÷ capacity">Vehicle utilisation</SectionTitle>
          {data.per_vehicle.some((v) => v.stops) ? <Gauge value={data.utilization} /> : <Empty title="No vehicles in use" />}
          <p className="mt-1 text-center text-2xs text-ink-muted">Across vehicles used by the current plan</p>
        </Panel>
      </div>

      <Panel className="mt-5 overflow-hidden">
        <div className="p-5 pb-2"><SectionTitle aside="most recent first">Delivery history</SectionTitle></div>
        <DeliveryHistory liveKey={liveKey} />
      </Panel>

      {data.runs.length > 0 && (
        <Panel className="mt-5 overflow-hidden">
          <div className="p-5 pb-2"><SectionTitle aside={runsDays ? `last ${runsDays === '1' ? '24 h' : `${runsDays} days`}` : 'all'}>Optimisation runs</SectionTitle></div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead><tr className="border-y border-surface-line"><Th>Run</Th><Th>Sim time</Th><Th>Kind</Th><Th>Algorithm / strategy</Th><Th>Objective Z</Th><Th>Distance</Th><Th>Late</Th><Th>Runtime</Th></tr></thead>
              <tbody>{data.runs.map((r) => (
                <tr key={r.id} className="border-b border-surface-line last:border-0">
                  <Td className="font-mono">#{r.id}</Td><Td className="font-mono text-xs">{r.time}</Td><Td>{fmt.label(r.kind)}</Td><Td>{fmt.label(r.algorithm)}</Td>
                  <Td className="tabular">{fmt.num(r.objective, 1)}</Td><Td className="tabular">{fmt.km(r.distance_km)}</Td><Td className="tabular">{r.late_count ?? '–'}</Td>
                  <Td className="tabular">{r.runtime_ms ? `${fmt.num(r.runtime_ms)} ms` : '–'}</Td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

function Donut({ title, data, fallback, colorsMap }) {
  const useFallback = fallback && !Object.values(data).some(Boolean);
  const src = useFallback ? fallback : data;
  const rows = Object.entries(src).map(([name, value]) => ({ name, value }));
  const total = rows.reduce((a, b) => a + b.value, 0);
  return (
    <Panel className="p-5">
      <SectionTitle aside={useFallback ? 'predicted from plan' : ''}>{title}</SectionTitle>
      {total ? (
        <div className="flex items-center gap-4">
          <ul className="space-y-1.5 text-sm">
            {rows.map((r) => (
              <li key={r.name} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: colorsMap[r.name] }} />
                {fmt.label(r.name)} <span className="tabular text-ink-muted">{r.value}</span></li>
            ))}
          </ul>
          <div className="relative h-[170px] flex-1">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={rows} dataKey="value" innerRadius="64%" outerRadius="95%" startAngle={90} endAngle={-270} stroke="none" animationDuration={600}>
                  {rows.map((r) => <Cell key={r.name} fill={colorsMap[r.name]} />)}
                </Pie>
                <Tooltip {...tooltipStyle} formatter={(v, n) => [v, fmt.label(n)]} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
              <div><div className="tabular text-2xl font-semibold">{fmt.num(total)}</div><div className="text-2xs text-ink-muted">TOTAL</div></div>
            </div>
          </div>
        </div>
      ) : <Empty title="No data in this window" />}
    </Panel>
  );
}

function Gauge({ value }) {
  const v = Math.max(0, Math.min(1.2, value || 0));
  const angle = Math.PI * (1 - v / 1.2);
  const arc = (from, to) => {
    const a0 = Math.PI * (1 - from / 1.2);
    const a1 = Math.PI * (1 - to / 1.2);
    return `M ${100 + 80 * Math.cos(a0)} ${100 - 80 * Math.sin(a0)} A 80 80 0 0 1 ${100 + 80 * Math.cos(a1)} ${100 - 80 * Math.sin(a1)}`;
  };
  return (
    <svg viewBox="0 0 200 120" className="mx-auto w-full max-w-[240px]" role="img" aria-label={`Utilisation ${fmt.pct(value)}`}>
      <path d={arc(0, 0.5)} stroke={colors.bad.DEFAULT} strokeWidth="18" fill="none" />
      <path d={arc(0.5, 0.75)} stroke={colors.warn.DEFAULT} strokeWidth="18" fill="none" />
      <path d={arc(0.75, 1)} stroke={colors.ok.DEFAULT} strokeWidth="18" fill="none" />
      <path d={arc(1, 1.2)} stroke={colors.bad.DEFAULT} strokeWidth="18" fill="none" />
      <line x1="100" y1="100" x2={100 + 58 * Math.cos(angle)} y2={100 - 58 * Math.sin(angle)} stroke={colors.ink.soft} strokeWidth="4" strokeLinecap="round" />
      <circle cx="100" cy="100" r="6" fill={colors.ink.soft} />
      <text x="100" y="78" textAnchor="middle" fontSize="24" fontWeight="600" fill={colors.ink.DEFAULT}>{fmt.pct(value)}</text>
      <text x="14" y="116" fontSize="8" fill={chart.axis}>0%</text>
      <text x="170" y="116" fontSize="8" fill={chart.axis}>120%</text>
    </svg>
  );
}

function DeliveryHistory({ liveKey }) {
  const [page, setPage] = useState(1);
  const { data, error, reload } = useApi(`/orders${qs({ status: 'delivered', sort: 'delivered', direction: 'desc', page, page_size: PAGE })}`, [liveKey]);
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead><tr className="border-y border-surface-line">
            <Th>Order</Th><Th>Customer</Th><Th>Vehicle</Th><Th>Priority</Th><Th>Window</Th><Th>Arrived</Th><Th>Punctuality</Th><Th>Weight</Th><Th>Source</Th>
          </tr></thead>
          <tbody>
            {!data && <SkeletonRows rows={5} cols={9} />}
            {data?.items.map((o) => (
              <tr key={o.id} className="border-b border-surface-line last:border-0">
                <Td className="font-mono">{o.code}</Td><Td className="max-w-[220px] truncate">{o.customer_name}</Td>
                <Td className="font-mono">{o.vehicle_code || '–'}</Td><Td>{fmt.label(o.priority)}</Td>
                <Td className="tabular font-mono text-xs">{o.ready}–{o.deadline}</Td><Td className="tabular font-mono text-xs">{o.delivered || '–'}</Td>
                <Td>{o.delivery_note ? <StatusBadge status={o.delivery_note} /> : '–'}</Td>
                <Td className="tabular">{o.weight_kg} kg</Td><Td className="text-xs text-ink-muted">{fmt.label(o.source)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && !data.items.length && <Empty title="Nothing delivered yet">Deliveries appear here as the simulation runs.</Empty>}
      </div>
      {data?.total > 0 && (
        <div className="flex items-center justify-end gap-3 px-5 py-3 text-xs text-ink-muted">
          Rows {(page - 1) * PAGE + 1}–{Math.min(data.total, page * PAGE)} of {data.total}
          <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Previous page">‹</Button>
          <Button size="sm" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)} aria-label="Next page">›</Button>
        </div>
      )}
    </>
  );
}
