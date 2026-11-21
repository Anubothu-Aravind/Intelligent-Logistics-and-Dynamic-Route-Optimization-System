import { useState } from 'react';
import clsx from 'clsx';
import { Marker } from 'react-leaflet';
import { AlertTriangle, Plus, Truck, Warehouse } from 'lucide-react';
import CityMap from '../components/map/CityMap';
import { DepotLayer } from '../components/map/layers';
import { pinIcon } from '../components/map/markers';
import {
  Avatar, Bar, Button, ErrorState, Field, PageHeader, Panel, SectionTitle, Select, SkeletonRows, StatusBadge, Td, Th, Toggle,
} from '../components/ui';
import { api } from '../api/client';
import { useLive } from '../hooks/live';
import { useToast } from '../hooks/toast';
import { useConfirm } from '../hooks/confirm';
import { useAction, useApi } from '../hooks/useApi';
import { displayStatus, fmt } from '../lib/format';
import { colors, routePalette } from '../theme/tokens';

export default function FleetPage() {
  const { state } = useLive();
  const toast = useToast();
  const confirm = useConfirm();
  const { busy, done, run } = useAction(toast);
  const liveKey = `${state?.vehicles?.length}|${state?.vehicles?.map((v) => `${v.depot_id}${v.active}`).join('')}`;
  const fleet = useApi('/vehicles', [liveKey]);
  const depotsReq = useApi('/depots', [liveKey, state?.depots?.length, state?.kpis?.total_orders]);
  const [vForm, setVForm] = useState({ model: '', capacity_kg: '', driver_name: '', depot_id: '' });
  const [dForm, setDForm] = useState({ name: '', lat: null, lon: null, move_vehicles: 0 });
  const [editing, setEditing] = useState({});
  const [optimistic, setOptimistic] = useState({});
  const live = Object.fromEntries((state?.vehicles || []).map((v) => [v.id, v]));
  const types = fleet.data?.types || [];
  const depots = depotsReq.data?.depots || state?.depots || [];
  const parked = (state?.vehicles || []).filter((v) => ['idle', 'done'].includes(v.status)).length;

  const patch = (v, body, msg) => run(`v${v.id}${Object.keys(body)[0]}`, async () => {
    const r = await api.patch(`/vehicles/${v.id}`, body);
    await Promise.all([fleet.reload(), depotsReq.reload()]);
    return r;
  }, msg);

  const toggleActive = async (v, val) => {
    const lv = live[v.id];
    if (!val && lv?.stops?.some((s) => s.status !== 'done')) {
      const ok = await confirm({
        title: `Deactivate ${v.code}?`, confirmLabel: 'Deactivate',
        body: 'Its planned (not yet loaded) orders go back to the pool. Re-optimise afterwards to give them to other vehicles.',
      });
      if (!ok) return;
    }
    setOptimistic((o) => ({ ...o, [v.id]: val }));          // optimistic, rolled back on error
    const res = await patch(v, { active: val }, `${v.code} ${val ? 'activated' : 'deactivated'}`);
    setOptimistic((o) => { const n = { ...o }; delete n[v.id]; return n; });
    return res;
  };

  const moveVehicle = (v, depotId) => patch(v, { depot_id: Number(depotId) },
    `${v.code} moved to ${depots.find((d) => d.id === Number(depotId))?.name} – re-optimise to use it`);

  const saveCapacity = (v) => {
    const cap = Number(editing[v.id]);
    if (!(cap > 0 && cap <= 100000)) { toast.push('Capacity must be between 1 and 100 000 kg', 'bad'); return; }
    patch(v, { capacity_kg: cap }, `${v.code} capacity set to ${cap} kg`).then((r) => r && setEditing((e) => ({ ...e, [v.id]: undefined })));
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <PageHeader title="Fleet & depots" subtitle="Vehicles, capacities and the hubs they start from. Orders are planned from the nearest hub that has active vehicles." />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel className="overflow-hidden">
          {fleet.error && !fleet.data ? <ErrorState message={fleet.error} onRetry={fleet.reload} /> : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead><tr className="border-b border-surface-line">
                  <Th>Vehicle</Th><Th>Driver</Th><Th>Hub</Th><Th>Capacity</Th><Th>Load</Th><Th>Fuel</Th><Th>Distance</Th><Th>Stops</Th><Th>Status</Th><Th>Active</Th>
                </tr></thead>
                <tbody>
                  {!fleet.data && <SkeletonRows rows={8} cols={10} />}
                  {fleet.data?.vehicles.map((v, i) => {
                    const lv = live[v.id] || v;
                    const active = optimistic[v.id] ?? v.active;
                    const canMove = ['idle', 'done', 'inactive'].includes(lv.status) && !lv.load_kg;
                    return (
                      <tr key={v.id} className={clsx('border-b border-surface-line transition-opacity last:border-0', !active && 'opacity-60')}>
                        <Td><div className="font-mono font-medium">{v.code}</div><div className="text-xs text-ink-muted">{v.model}</div></Td>
                        <Td><div className="flex items-center gap-2"><Avatar name={v.driver_name} color={routePalette[i % routePalette.length]} size={30} />{v.driver_name}</div></Td>
                        <Td>
                          <Select className="h-8 w-40" value={v.depot_id} onChange={(d) => moveVehicle(v, d)}
                            options={depots.map((d) => ({ value: d.id, label: d.name, disabled: !canMove && d.id !== v.depot_id }))} />
                          {!canMove && <div className="mt-0.5 text-2xs text-ink-muted">on the road – movable when parked</div>}
                        </Td>
                        <Td>
                          <div className="flex items-center gap-1">
                            <input type="number" min="1" max="100000" className="input h-8 w-24" value={editing[v.id] ?? v.capacity_kg}
                              onChange={(e) => setEditing({ ...editing, [v.id]: e.target.value })}
                              onKeyDown={(e) => e.key === 'Enter' && saveCapacity(v)} aria-label={`Capacity of ${v.code} in kg`} />
                            {editing[v.id] !== undefined && Number(editing[v.id]) !== v.capacity_kg && (
                              <Button size="sm" variant="dark" busy={busy === `v${v.id}capacity_kg`} onClick={() => saveCapacity(v)}>Save</Button>
                            )}
                          </div>
                        </Td>
                        <Td className="w-28"><Bar value={lv.load_pct} color={colors.ink.DEFAULT} /><span className="tabular text-xs text-ink-muted">{fmt.pct(lv.load_pct)}</span></Td>
                        <Td className="w-28"><Bar value={lv.fuel_pct} color={lv.fuel_pct < 0.2 ? colors.bad.DEFAULT : colors.ok.DEFAULT} /><span className="tabular text-xs text-ink-muted">{fmt.pct(lv.fuel_pct)} of {v.fuel_tank_l} L</span></Td>
                        <Td className="tabular">{fmt.km(lv.distance_km)}</Td>
                        <Td className="tabular">{lv.stops_done}/{lv.stops_total}</Td>
                        <Td><StatusBadge status={displayStatus(lv) === 'delayed' ? 'delayed' : lv.status} /></Td>
                        <Td><Toggle checked={active} onChange={(val) => toggleActive(v, val)} label={<span className="sr-only">{v.code} active</span>} /></Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <div className="space-y-6">
          <Panel className="p-5">
            <SectionTitle aside={`${depots.length} hub(s)`}><span className="flex items-center gap-2"><Warehouse className="h-4 w-4" />Hubs</span></SectionTitle>
            <ul className="mb-4 space-y-2">
              {depots.map((d) => (
                <li key={d.id} className={clsx('rounded-card border p-3 text-sm', d.in_use === false ? 'border-warn/40 bg-warn-soft/50' : 'border-surface-line')}>
                  <div className="flex items-center justify-between gap-2"><span className="font-medium">{d.name}</span>
                    <span className="tabular text-xs text-ink-muted">{d.vehicles ?? '–'} vehicle(s) · {d.open_orders ?? '–'} open order(s)</span></div>
                  <div className="text-xs text-ink-muted">{d.address}</div>
                  {d.in_use === false && (
                    <div className="mt-1.5 flex items-center gap-1.5 text-xs text-ink-soft"><AlertTriangle className="h-3.5 w-3.5 text-warn" />
                      No active vehicles – not used for planning. Assign vehicles with the Hub selector.</div>
                  )}
                </li>
              ))}
            </ul>
            <div className="h-48 overflow-hidden rounded-card border border-surface-line">
              <CityMap className="h-full w-full" onClick={(ll) => setDForm({ ...dForm, lat: ll.lat, lon: ll.lng })}>
                <DepotLayer depots={depots} />
                {dForm.lat && <Marker position={[dForm.lat, dForm.lon]} icon={pinIcon('+', colors.brand.DEFAULT)} />}
              </CityMap>
            </div>
            <p className={clsx('mt-2 text-xs', dForm.lat ? 'text-ink-soft' : 'text-ink-muted')}>{dForm.lat ? 'Location selected – it snaps to the nearest intersection' : 'Click the map to place a new hub'}</p>
            <div className="mt-3 space-y-3">
              <input className="input" maxLength={120} placeholder="Hub name (generated if empty)" value={dForm.name} onChange={(e) => setDForm({ ...dForm, name: e.target.value })} />
              <Field label={`Move parked vehicles to the new hub (${parked} parked now)`}>
                <input type="number" min="0" max={parked} className="input" value={dForm.move_vehicles}
                  onChange={(e) => setDForm({ ...dForm, move_vehicles: Math.max(0, Math.min(parked, Number(e.target.value) || 0)) })} />
              </Field>
              <Button variant="dark" className="w-full" icon={Plus} disabled={!dForm.lat} busy={busy === 'addd'} done={done === 'addd'}
                onClick={() => run('addd', async () => {
                  const r = await api.post('/depots', { lat: dForm.lat, lon: dForm.lon, name: dForm.name || undefined, move_vehicles: dForm.move_vehicles });
                  setDForm({ name: '', lat: null, lon: null, move_vehicles: 0 });
                  await Promise.all([fleet.reload(), depotsReq.reload()]);
                  return r;
                }, (r) => (r.moved_vehicles.length ? `${r.name} added with ${r.moved_vehicles.join(', ')} – re-optimise to use it`
                  : `${r.name} added – assign vehicles to it so it is used`))}>Add hub</Button>
            </div>
          </Panel>
          <Panel className="p-5">
            <SectionTitle aside="types from settings.yaml"><span className="flex items-center gap-2"><Truck className="h-4 w-4" />Register vehicle</span></SectionTitle>
            <div className="space-y-3">
              <Field label="Vehicle type">
                <Select value={vForm.model} onChange={(m) => setVForm({ ...vForm, model: m, capacity_kg: types.find((t) => t.model === m)?.capacity_kg ?? '' })}
                  options={[{ value: '', label: 'Random (weighted mix)' }, ...types.map((t) => ({ value: t.model, label: `${t.model} · ${t.capacity_kg} kg` }))]} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Capacity (kg)"><input type="number" min="1" max="100000" className="input" value={vForm.capacity_kg} onChange={(e) => setVForm({ ...vForm, capacity_kg: e.target.value })} /></Field>
                <Field label="Hub">
                  <Select value={vForm.depot_id} onChange={(d) => setVForm({ ...vForm, depot_id: d })}
                    options={[{ value: '', label: 'First hub' }, ...depots.map((d) => ({ value: d.id, label: d.name }))]} />
                </Field>
              </div>
              <Field label="Driver name" hint="Generated if empty"><input className="input" maxLength={120} value={vForm.driver_name} onChange={(e) => setVForm({ ...vForm, driver_name: e.target.value })} /></Field>
              <Button variant="dark" className="w-full" icon={Plus} busy={busy === 'addv'} done={done === 'addv'}
                onClick={() => run('addv', async () => {
                  const body = Object.fromEntries(Object.entries(vForm).filter(([, v]) => v !== ''));
                  if (body.capacity_kg !== undefined) {
                    body.capacity_kg = Number(body.capacity_kg);
                    if (!(body.capacity_kg > 0)) throw new Error('Capacity must be a positive number');
                  }
                  if (body.depot_id) body.depot_id = Number(body.depot_id);
                  const r = await api.post('/vehicles', body);
                  setVForm({ model: '', capacity_kg: '', driver_name: '', depot_id: '' });
                  await Promise.all([fleet.reload(), depotsReq.reload()]);
                  return r;
                }, (r) => `${r.code} registered – it is used from the next optimisation`)}>Add vehicle</Button>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
