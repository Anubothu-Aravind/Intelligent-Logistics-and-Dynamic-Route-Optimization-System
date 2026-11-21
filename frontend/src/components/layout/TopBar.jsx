import { useCallback, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowRight, Ban, BarChart3, Check, ChevronDown, Gauge, PackagePlus, Pause, Play, RotateCcw, Sparkles, Square,
  TrafficCone, Wand2, Zap,
} from 'lucide-react';
import { api } from '../../api/client';
import { useLive } from '../../hooks/live';
import { useToast } from '../../hooks/toast';
import { useConfirm } from '../../hooks/confirm';
import { useAction, useDismiss } from '../../hooks/useApi';
import { Button, Toggle } from '../ui';
import { pop, spring } from '../motion';

const STEPS = [
  { key: 'orders', label: 'Orders', to: '/orders' },
  { key: 'plan', label: 'Plan', to: '/dispatch' },
  { key: 'dispatch', label: 'Dispatch', to: '/dispatch' },
  { key: 'live', label: 'Live', to: '/' },
  { key: 'review', label: 'Review', to: '/analytics' },
];
const SPEEDS = [0.5, 1, 2, 5, 10];

/** Where the user is in the day: derived from real engine state, never stored separately. */
export function flowStep(s) {
  if (!s) return 0;
  const k = s.kpis;
  if (!k.total_orders) return 0;
  if (!s.plan && !s.dispatched) return 1;
  if (!s.dispatched) return 2;
  const finished = !s.running && k.delivered > 0 && k.pending === 0 && k.in_transit === 0;
  return finished ? 4 : 3;
}

export default function TopBar() {
  const { state, setState } = useLive();
  const toast = useToast();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const location = useLocation();
  const { busy, done, run } = useAction(toast);
  const step = flowStep(state);
  const k = state?.kpis;

  const post = (key, path, body, msg) => run(key, async () => {
    const res = await api.post(path, body);
    if (res?.vehicles) setState(res);
    return res;
  }, msg);

  const next = (() => {
    if (!state) return null;
    if (step === 0) return { label: 'Add orders', icon: PackagePlus, onClick: () => navigate('/orders') };
    if (step === 1) {
      return { label: 'Optimise plan', icon: Wand2, key: 'opt',
        onClick: () => post('opt', '/optimization/run', {}, (r) => `Plan ready · ${r.metrics.vehicles_used} vehicles · ${r.metrics.late_count} late`).then(() => navigate('/dispatch')) };
    }
    if (step === 2) {
      return { label: k.unassigned ? `Dispatch (+${k.unassigned} new)` : 'Dispatch fleet', icon: Play, key: 'go', tone: 'brand',
        onClick: () => post('go', '/simulation/start', {}, 'Fleet dispatched').then(() => navigate('/')) };
    }
    if (step === 3 && !state.running) return { label: 'Resume', icon: Play, key: 'go', onClick: () => post('go', '/simulation/start', {}, 'Resumed') };
    if (step === 3 && location.pathname !== '/') return { label: 'Watch live', icon: ArrowRight, onClick: () => navigate('/') };
    if (step === 4) return { label: 'Review results', icon: BarChart3, onClick: () => navigate('/analytics') };
    return null;
  })();

  const stop = async () => {
    const ok = await confirm({
      title: 'Stop the run?', confirmLabel: 'Stop run',
      body: 'Vehicles go back to their hubs and the clock returns to the start of the shift. Deliveries made in this run are undone. All orders and the optimised plan are kept, so you can dispatch again.',
    });
    if (ok) post('stop', '/simulation/stop', {}, 'Run stopped – back to planning');
  };
  const reset = async () => {
    const ok = await confirm({
      title: 'Reset everything to the start?', tone: 'danger', confirmLabel: 'Reset',
      body: 'Clears the plan, traffic events and orders created by the simulation, and returns every vehicle to its hub. Your own orders, vehicles and hubs are kept.',
    });
    if (ok) post('reset', '/simulation/reset', { keep_plan: false }, 'Reset – start again by optimising a plan');
  };

  return (
    <header className="relative z-[1500] flex h-16 shrink-0 items-center gap-4 border-b border-surface-line bg-surface px-5">
      {/* flow */}
      <nav aria-label="Workflow" className="flex items-center gap-1">
        {STEPS.map((s, i) => {
          const state_ = i < step ? 'done' : i === step ? 'current' : 'todo';
          return (
            <div key={s.key} className="flex items-center">
              <button type="button" onClick={() => navigate(s.to)} aria-current={state_ === 'current' ? 'step' : undefined}
                className={clsx('relative flex h-9 items-center gap-2 rounded-full px-3 text-sm font-medium transition-colors',
                  state_ === 'current' ? 'text-brand-strong' : state_ === 'done' ? 'text-ink' : 'text-ink-muted hover:text-ink')}>
                {state_ === 'current' && <motion.span layoutId="flow-pill" transition={spring} className="absolute inset-0 rounded-full bg-brand-soft" />}
                <span className={clsx('relative grid h-5 w-5 place-items-center rounded-full text-[11px] font-semibold transition-colors',
                  state_ === 'done' ? 'bg-ink text-white' : state_ === 'current' ? 'bg-brand text-white' : 'bg-surface-sunken text-ink-muted')}>
                  {state_ === 'done' ? <Check className="h-3 w-3" strokeWidth={3} /> : i + 1}
                </span>
                <span className="relative hidden lg:inline">{s.label}</span>
              </button>
              {i < STEPS.length - 1 && <span className={clsx('mx-0.5 h-px w-4 transition-colors', i < step ? 'bg-ink' : 'bg-surface-line')} />}
            </div>
          );
        })}
      </nav>

      <AnimatePresence mode="popLayout" initial={false}>
        {next && (
          <motion.div key={next.label} {...pop} data-flow-cta>
            <Button variant={next.tone === 'brand' ? 'brand' : 'dark'} icon={next.icon} busy={busy === next.key} done={done === next.key}
              disabled={!!busy || state?.optimizing} onClick={next.onClick}>{next.label}</Button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* simulation controls */}
      <div className="ml-auto flex items-center gap-2">
        {state && (
          <>
            <div className="flex items-center rounded-xl border border-surface-line p-0.5">
              <CtrlButton icon={state.running ? Pause : Play} label={state.running ? 'Pause' : state.dispatched ? 'Resume' : 'Start (optimise if needed, then dispatch)'}
                busy={busy === 'play'} disabled={!k.total_orders && !state.dispatched}
                onClick={() => post('play', state.running ? '/simulation/pause' : '/simulation/start', {}, state.running ? 'Paused' : 'Running')} />
              <CtrlButton icon={Square} label="Stop – back to planning" busy={busy === 'stop'} disabled={!state.dispatched} onClick={stop} />
              <CtrlButton icon={RotateCcw} label="Reset" busy={busy === 'reset'} onClick={reset} />
            </div>
            <SpeedMenu value={state.minutes_per_tick} onChange={(v) => post('speed', '/simulation/speed', { minutes_per_tick: v })} />
            <EventsMenu state={state} post={post} busy={busy} />
            <div className="flex h-9 items-center gap-2 rounded-xl bg-surface-subtle px-3">
              <motion.span className={clsx('h-2 w-2 rounded-full', state.running ? 'bg-ok' : 'bg-idle')}
                animate={state.running ? { opacity: [1, 0.35, 1] } : { opacity: 1 }} transition={state.running ? { repeat: Infinity, duration: 1.6 } : {}} />
              <span className="tabular font-mono text-sm">{state.clock_hhmm}</span>
            </div>
          </>
        )}
      </div>
    </header>
  );
}

function CtrlButton({ icon: Icon, label, onClick, disabled, busy }) {
  return (
    <motion.button type="button" title={label} aria-label={label} onClick={onClick} disabled={disabled || busy}
      whileTap={{ scale: 0.9 }} className="grid h-8 w-9 place-items-center rounded-lg text-ink-soft transition-colors hover:bg-surface-sunken hover:text-ink disabled:opacity-35">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span key={label} initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.6 }}>
          <Icon className="h-4 w-4" />
        </motion.span>
      </AnimatePresence>
    </motion.button>
  );
}

function Popover({ button, children, width = 280 }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  return (
    <div ref={ref} className="relative">
      {button(open, () => setOpen((o) => !o))}
      <AnimatePresence>
        {open && (
          <motion.div {...pop} role="menu" style={{ width, transformOrigin: 'top right' }}
            className="absolute right-0 top-11 rounded-card bg-surface p-2 shadow-panel">
            {children(close)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function SpeedMenu({ value, onChange }) {
  return (
    <Popover width={200} button={(open, toggle) => (
      <button type="button" onClick={toggle} aria-expanded={open} title="Simulation speed"
        className="flex h-9 items-center gap-1.5 rounded-xl border border-surface-line px-2.5 text-sm hover:bg-surface-subtle">
        <Gauge className="h-4 w-4 text-ink-muted" /><span className="tabular">{value}×</span><ChevronDown className="h-3.5 w-3.5 text-ink-muted" />
      </button>
    )}>
      {(close) => (
        <>
          <div className="px-2 pb-1 pt-1 text-xs text-ink-muted">Simulated minutes per second</div>
          {SPEEDS.map((s) => (
            <button key={s} type="button" role="menuitemradio" aria-checked={value === s} onClick={() => { onChange(s); close(); }}
              className={clsx('flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-sm hover:bg-surface-subtle', value === s && 'font-semibold')}>
              {s}× {value === s && <Check className="h-4 w-4 text-brand" />}
            </button>
          ))}
        </>
      )}
    </Popover>
  );
}

function EventsMenu({ state, post, busy }) {
  const decided = (r) => r.decisions?.find((d) => d.order_id === r.order.id)?.chosen_vehicle;
  const actions = [
    { key: 'ev-order', path: '/simulation/events/new-order', icon: PackagePlus, label: 'New customer order', body: {},
      msg: (r) => `${r.order.code} → ${decided(r) || 'waiting for a vehicle'}` },
    { key: 'ev-urgent', path: '/simulation/events/new-order', icon: Zap, label: 'Urgent order (due in 45 min)', body: { priority: 'high', deadline_in_min: 45 },
      msg: (r) => `Urgent ${r.order.code} → ${decided(r) || 'waiting for a vehicle'}` },
    { key: 'ev-jam', path: '/simulation/events/congestion', icon: TrafficCone, label: 'Traffic jam on a route', body: {},
      msg: (r) => `Traffic ×${r.congestion.factor} until ${r.congestion.until_hhmm} – routes re-planned` },
    { key: 'ev-close', path: '/simulation/events/closure', icon: Ban, label: 'Close a road', body: {}, msg: (r) => `${r.closure.street} closed – vehicles rerouted` },
    { key: 'ev-clear', path: '/simulation/events/clear-traffic', icon: Check, label: 'Clear traffic', body: {}, msg: 'All roads open' },
  ];
  return (
    <Popover width={290} button={(open, toggle) => (
      <Button variant="brand" size="sm" className="h-9" icon={Sparkles} busy={busy?.startsWith?.('ev-')} onClick={toggle} aria-expanded={open}>Events</Button>
    )}>
      {(close) => (
        <>
          <div className="px-2.5 pb-1 pt-1 text-xs text-ink-muted">Something happens – the engine re-plans</div>
          {actions.map((a, i) => (
            <motion.button key={a.key} type="button" role="menuitem" disabled={!!busy}
              initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0, transition: { delay: i * 0.03 } }}
              onClick={() => { close(); post(a.key, a.path, a.body, a.msg); }}
              className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-sm transition-colors hover:bg-surface-subtle disabled:opacity-50">
              <a.icon className="h-4 w-4 text-ink-soft" />{a.label}
            </motion.button>
          ))}
          <div className="my-2 h-px bg-surface-line" />
          <div className="px-2.5 pb-1.5">
            <Toggle checked={state.random_events} label="Random events while running"
              onChange={(v) => post('rand', '/simulation/random-events', { enabled: v }, v ? 'Random events on' : 'Random events off')} />
          </div>
        </>
      )}
    </Popover>
  );
}
