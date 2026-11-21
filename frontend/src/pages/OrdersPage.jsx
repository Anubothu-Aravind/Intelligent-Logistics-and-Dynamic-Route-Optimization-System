import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { Marker } from 'react-leaflet';
import { ArrowDown, ArrowUp, Ban, Boxes, MapPin, PackagePlus, Search, Trash2, Wand2, X } from 'lucide-react';
import CityMap from '../components/map/CityMap';
import { DepotLayer, OrderDots } from '../components/map/layers';
import { pinIcon } from '../components/map/markers';
import {
  Button, Checkbox, Chip, Empty, ErrorState, Field, PageHeader, Panel, SectionTitle, Select, SkeletonRows, StatusBadge, Td, Th,
} from '../components/ui';
import { api, qs } from '../api/client';
import { useLive } from '../hooks/live';
import { useToast } from '../hooks/toast';
import { useConfirm } from '../hooks/confirm';
import { useAction, useApi, useDebounced } from '../hooks/useApi';
import { fmt } from '../lib/format';
import { chart, colors } from '../theme/tokens';

const STATUSES = ['all', 'pending', 'assigned', 'in_transit', 'delivered', 'cancelled'];
const PAGE_SIZES = [25, 50, 100];
const EMPTY_FORM = { customer_name: '', weight_kg: '', priority: '', deadline: '', lat: null, lon: null };

export default function OrdersPage() {
  const { state } = useLive();
  const toast = useToast();
  const confirm = useConfirm();
  const { busy, done, run } = useAction(toast);
  const [status, setStatus] = useState('all');
  const [priority, setPriority] = useState('');
  const [search, setSearch] = useState('');
  const q = useDebounced(search.trim(), 300);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sort, setSort] = useState({ key: 'id', dir: 'asc' });
  const [selected, setSelected] = useState(new Set());
  const [allMatching, setAllMatching] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [count, setCount] = useState(10);

  useEffect(() => { setPage(1); setSelected(new Set()); setAllMatching(false); }, [status, priority, q, pageSize]);

  const k = state?.kpis;
  const liveKey = k ? `${k.total_orders}|${k.delivered}|${k.in_transit}|${k.unassigned}|${state.plan?.run_id}` : '';
  const filter = { status: status === 'all' ? undefined : status, priority: priority || undefined, q: q || undefined };
  const list = useApi(`/orders${qs({ ...filter, page, page_size: pageSize, sort: sort.key, direction: sort.dir })}`, [liveKey]);
  const markers = useApi('/orders/markers', [liveKey]);
  const data = list.data;
  const rows = data?.items || [];
  const counts = useMemo(() => {
    const c = { ...(data?.counts || {}) };
    c.all = Object.values(c).reduce((a, b) => a + b, 0);
    return c;
  }, [data]);

  const pageIds = rows.map((o) => o.id);
  const pageAll = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const pageSome = pageIds.some((id) => selected.has(id));
  const selCount = allMatching ? data?.total || 0 : selected.size;
  const togglePage = (on) => setSelected((s) => { const n = new Set(s); pageIds.forEach((id) => (on ? n.add(id) : n.delete(id))); return n; });
  const toggleOne = (id, on) => { setAllMatching(false); setSelected((s) => { const n = new Set(s); if (on) n.add(id); else n.delete(id); return n; }); };
  const clearSel = () => { setSelected(new Set()); setAllMatching(false); };

  const refresh = () => { list.reload(); markers.reload(); };

  /** Confirm with exact numbers from the server (incl. history opt-in), then delete in one transaction. */
  const deleteFlow = async ({ key, selection, title, label }) => {
    const [without, withHistory] = await Promise.all([
      api.post('/orders/bulk-delete/preview', { ...selection, include_delivered: false }),
      api.post('/orders/bulk-delete/preview', { ...selection, include_delivered: true }),
    ]).catch((e) => { toast.push(e.message, 'bad'); return [null, null]; });
    if (!without) return;
    if (!withHistory.deletable) { toast.push('Nothing to delete – those orders are being delivered right now', 'bad'); return; }
    const delivered = withHistory.deletable - without.deletable;
    const ok = await confirm({
      title, tone: 'danger', confirmLabel: label,
      body: (checked) => {
        const n = checked ? withHistory.deletable : without.deletable;
        return (
          <div className="space-y-2">
            <p><b className="tabular">{n}</b> order(s) will be <b>permanently deleted</b> and removed from all routes and future planning. This cannot be undone.</p>
            {(checked ? withHistory : without).affects_routes > 0 && <p className="text-xs">Routes of affected vehicles are re-planned automatically.</p>}
            {without.skipped_in_service > 0 && <p className="text-xs text-ink-muted">{without.skipped_in_service} order(s) being handed over right now are kept.</p>}
            {!checked && delivered > 0 && <p className="text-xs text-ink-muted">{delivered} delivered order(s) are kept as history.</p>}
            <p className="text-xs text-ink-muted">To keep a record instead, use <b>Cancel</b> on the order.</p>
          </div>
        );
      },
      extra: delivered > 0 ? { label: `Also delete ${delivered} delivered order(s) – removes delivery history used by Analytics` } : null,
      disabled: (checked) => (checked ? withHistory.deletable : without.deletable) === 0,
    });
    if (!ok) return;
    const res = await run(key, () => api.post('/orders/bulk-delete', { ...selection, include_delivered: ok.checked }),
      (r) => `${r.deleted} order(s) deleted`);
    if (res) { clearSel(); refresh(); }
  };

  const deleteSelected = () => deleteFlow({
    key: 'bulk', title: `Delete ${selCount} selected order(s)?`, label: 'Delete orders',
    selection: allMatching ? { filter: { ...filter } } : { ids: [...selected] },
  });
  const clearAll = () => deleteFlow({ key: 'clear', title: 'Clear all orders?', label: 'Clear orders', selection: { filter: {} } });
  const deleteOne = (o) => deleteFlow({ key: `del${o.id}`, title: `Delete ${o.code}?`, label: 'Delete order', selection: { ids: [o.id] } });
  const cancelOne = async (o) => {
    const ok = await confirm({
      title: `Cancel ${o.code}?`, confirmLabel: 'Cancel order', cancelLabel: 'Keep order',
      body: 'The order is removed from its route and will not be delivered, but it stays in the list as “cancelled” for your records.',
    });
    if (ok && await run(`cancel${o.id}`, () => api.post(`/orders/${o.id}/cancel`), `${o.code} cancelled`)) refresh();
  };

  const create = () => run('create', async () => {
    const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v !== '' && v !== null));
    if (body.weight_kg !== undefined) {
      body.weight_kg = Number(body.weight_kg);
      if (!(body.weight_kg > 0)) throw new Error('Weight must be a positive number');
    }
    const res = await api.post('/orders', body);
    setForm(EMPTY_FORM);
    refresh();
    return res;
  }, (r) => `${r.order.code} created${r.decisions ? ` → ${r.decisions.find((d) => d.order_id === r.order.id)?.chosen_vehicle || 'waiting for a vehicle'}` : ' – optimise to assign it'}`);

  const generate = () => {
    const n = Number(count);
    if (!Number.isInteger(n) || n < 1 || n > 1000) { toast.push('Enter a whole number between 1 and 1000', 'bad'); return; }
    run('gen', async () => { const r = await api.post('/orders/generate', { count: n }); refresh(); return r; },
      (r) => `${r.orders.length} order(s) generated${state?.dispatched ? ' and inserted into live routes' : ''}`);
  };

  const sortBy = (key) => setSort((s) => ({ key, dir: s.key === key && s.dir === 'asc' ? 'desc' : 'asc' }));
  const SortTh = ({ k: key, children }) => (
    <Th>
      <button type="button" onClick={() => sortBy(key)} className="inline-flex items-center gap-1 hover:text-ink">
        {children}{sort.key === key && (sort.dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </Th>
  );
  const markerOrders = (markers.data?.markers || []).map(([id, code, lat, lon, st, pr]) => ({ id, code, lat, lon, status: st, priority: pr, weight_kg: '' }));

  return (
    <div className="h-full overflow-y-auto p-6">
      <PageHeader title="Orders"
        subtitle="Delivery requests with priorities and time windows. New orders during the simulation are inserted into live routes automatically."
        actions={<>
          <label className="flex items-center gap-2 text-sm text-ink-muted">Generate
            <input type="number" min="1" max="1000" className="input w-20" value={count} onChange={(e) => setCount(e.target.value)} aria-label="Number of orders to generate" />
          </label>
          <Button icon={Wand2} busy={busy === 'gen'} done={done === 'gen'} onClick={generate}>Generate random orders</Button>
          <Button variant="danger" icon={Trash2} busy={busy === 'clear'} disabled={!counts.all} onClick={clearAll}>Clear all…</Button>
        </>} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 border-b border-surface-line p-4">
            {STATUSES.map((s) => <Chip key={s} active={status === s} count={counts[s] || 0} onClick={() => setStatus(s)}>{fmt.label(s)}</Chip>)}
            <div className="ml-auto flex items-center gap-2">
              <Select className="h-9 w-36" value={priority} onChange={setPriority}
                options={[{ value: '', label: 'All priorities' }, ...(data?.priorities || []).map((p) => ({ value: p, label: fmt.label(p) }))]} />
              <label className="flex h-9 w-60 items-center gap-2 rounded-xl border border-surface-line px-3 focus-within:border-brand">
                <Search className="h-4 w-4 text-ink-muted" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Code, customer or address"
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none" aria-label="Search orders" />
                {search && <button type="button" aria-label="Clear search" onClick={() => setSearch('')}><X className="h-3.5 w-3.5 text-ink-muted" /></button>}
              </label>
            </div>
          </div>

          {(selCount > 0) && (
            <div className="anim-fade flex flex-wrap items-center gap-3 border-b border-surface-line bg-surface-subtle px-4 py-2.5 text-sm">
              <b className="tabular">{selCount}</b> selected
              {!allMatching && pageAll && data?.total > pageIds.length && (
                <button type="button" className="text-brand-strong underline-offset-2 hover:underline" onClick={() => setAllMatching(true)}>
                  Select all {data.total} matching orders
                </button>
              )}
              {allMatching && <span className="text-ink-muted">(every order matching the current filter)</span>}
              <div className="ml-auto flex gap-2">
                <Button size="sm" variant="ghost" onClick={clearSel}>Clear selection</Button>
                <Button size="sm" variant="dangerSolid" icon={Trash2} busy={busy === 'bulk'} onClick={deleteSelected}>Delete selected…</Button>
              </div>
            </div>
          )}

          {list.error && !data ? <ErrorState message={list.error} onRetry={list.reload} /> : (
            <div className="relative overflow-x-auto">
              {list.loading && data && <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden"><div className="skeleton h-full w-full !rounded-none" /></div>}
              <table className="w-full">
                <thead><tr className="border-b border-surface-line">
                  <Th className="w-10"><Checkbox checked={pageAll || allMatching} indeterminate={pageSome} label="Select all orders on this page" disabled={!pageIds.length}
                    onChange={(on) => { setAllMatching(false); togglePage(on); }} /></Th>
                  <SortTh k="code">Order</SortTh><Th>Customer</Th><SortTh k="weight">Weight</SortTh><SortTh k="priority">Priority</SortTh>
                  <SortTh k="deadline">Window</SortTh><Th>Vehicle</Th><SortTh k="status">Status</SortTh><SortTh k="delivered">Delivered</SortTh><Th className="text-right">Actions</Th>
                </tr></thead>
                <tbody>
                  {!data && <SkeletonRows rows={8} cols={10} />}
                  {rows.map((o) => {
                    const isSel = allMatching || selected.has(o.id);
                    return (
                      <tr key={o.id} className={clsx('border-b border-surface-line transition-colors last:border-0', isSel ? 'bg-brand-soft/40' : 'hover:bg-surface-subtle')}>
                        <Td><Checkbox checked={isSel} label={`Select ${o.code}`} onChange={(on) => toggleOne(o.id, on)} /></Td>
                        <Td className="font-mono">{o.code}</Td>
                        <Td><div className="max-w-[220px] truncate">{o.customer_name}</div><div className="max-w-[220px] truncate text-xs text-ink-muted">{o.address}</div></Td>
                        <Td className="tabular">{o.weight_kg} kg</Td>
                        <Td><StatusBadge status={o.priority} /></Td>
                        <Td className="tabular font-mono text-xs">{o.ready}–{o.deadline}</Td>
                        <Td className="font-mono">{o.vehicle_code || '–'}</Td>
                        <Td><StatusBadge status={o.status} /></Td>
                        <Td className="tabular font-mono text-xs">{o.delivered ? <span className="inline-flex items-center gap-1.5">{o.delivered}<StatusBadge status={o.delivery_note} /></span> : '–'}</Td>
                        <Td className="text-right">
                          <div className="inline-flex gap-1">
                            {['pending', 'assigned'].includes(o.status) && (
                              <Button size="sm" variant="ghost" icon={Ban} busy={busy === `cancel${o.id}`} onClick={() => cancelOne(o)}
                                title="Cancel: keep the record, remove it from routes">Cancel</Button>
                            )}
                            <Button size="sm" variant="ghost" icon={Trash2} className="text-bad hover:bg-bad-soft" busy={busy === `del${o.id}`}
                              onClick={() => deleteOne(o)} title="Delete permanently" aria-label={`Delete ${o.code}`} />
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {data && !rows.length && (
                <Empty icon={Boxes} title={counts.all ? 'No orders match these filters' : 'No orders yet'}>
                  {counts.all ? 'Change the status, priority or search.' : 'Create one on the right or generate random orders.'}
                </Empty>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-surface-line px-4 py-3 text-xs text-ink-muted">
            <label className="mr-auto flex items-center gap-2">Rows per page
              <Select className="h-8 w-20" value={pageSize} onChange={(v) => setPageSize(Number(v))} options={PAGE_SIZES.map((n) => ({ value: n, label: n }))} />
            </label>
            {data && <>Rows {data.total ? (page - 1) * pageSize + 1 : 0}–{Math.min(data.total, page * pageSize)} of {data.total}</>}
            <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Previous page">‹</Button>
            <span className="tabular">{page} / {data?.pages || 1}</span>
            <Button size="sm" disabled={!data || page >= data.pages} onClick={() => setPage((p) => p + 1)} aria-label="Next page">›</Button>
          </div>
        </Panel>

        <Panel className="h-fit p-5">
          <SectionTitle aside="empty fields are generated">New delivery order</SectionTitle>
          <div className="h-56 overflow-hidden rounded-card border border-surface-line">
            <CityMap className="h-full w-full" onClick={(ll) => setForm((f) => ({ ...f, lat: ll.lat, lon: ll.lng }))}>
              <DepotLayer depots={state?.depots} />
              <OrderDots orders={markerOrders} color={chart.priorities.low} radius={3} />
              {form.lat && <Marker position={[form.lat, form.lon]} icon={pinIcon('+', colors.brand.DEFAULT)} />}
            </CityMap>
          </div>
          <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-muted"><MapPin className="h-3.5 w-3.5" />
            {form.lat ? `Snaps to the nearest intersection of ${fmt.num(form.lat, 5)}, ${fmt.num(form.lon, 5)}` : 'Click the map to choose the destination (random if empty)'}
            {form.lat && <button type="button" className="ml-auto text-ink-soft underline" onClick={() => setForm((f) => ({ ...f, lat: null, lon: null }))}>clear</button>}</p>
          <div className="mt-3 space-y-3">
            <Field label="Customer"><input className="input" maxLength={160} value={form.customer_name} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Weight (kg)"><input type="number" min="0.1" step="0.1" className="input" value={form.weight_kg} onChange={(e) => setForm({ ...form, weight_kg: e.target.value })} /></Field>
              <Field label="Deadline (HH:MM)"><input type="time" className="input" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} /></Field>
            </div>
            <Field label="Priority">
              <Select value={form.priority} onChange={(v) => setForm({ ...form, priority: v })}
                options={[{ value: '', label: 'Random (by configured mix)' }, ...(data?.priorities || []).map((p) => ({ value: p, label: fmt.label(p) }))]} />
            </Field>
            <Button variant="dark" className="w-full" icon={PackagePlus} busy={busy === 'create'} done={done === 'create'} onClick={create}>
              {state?.dispatched ? 'Create & insert into live routes' : 'Create order'}
            </Button>
          </div>
        </Panel>
      </div>
    </div>
  );
}
