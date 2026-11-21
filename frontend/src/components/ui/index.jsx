import { forwardRef } from 'react';
import clsx from 'clsx';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, Check, Loader2, RotateCw } from 'lucide-react';
import { fmt } from '../../lib/format';

export function Panel({ className, children, ...rest }) {
  return <section className={clsx('panel', className)} {...rest}>{children}</section>;
}

const TONES = {
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  bad: 'bg-bad-soft text-bad',
  brand: 'bg-brand-soft text-brand-strong',
  idle: 'bg-idle-soft text-ink-muted',
  ink: 'bg-ink text-white',
};

export function Badge({ tone = 'idle', className, children }) {
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium', TONES[tone], className)}>
      {children}
    </span>
  );
}

export const STATUS_TONE = {
  moving: 'ok', delayed: 'warn', idle: 'idle', scheduled: 'brand', done: 'idle', servicing: 'brand', reloading: 'ink', blocked: 'bad',
  inactive: 'idle', pending: 'idle', assigned: 'brand', in_transit: 'ok', delivered: 'ink', cancelled: 'bad',
  high: 'bad', medium: 'warn', low: 'idle', on_time: 'ok', early: 'warn', late: 'bad',
};

/** key={status} remounts the badge so a status change visibly fades in. */
export function StatusBadge({ status }) {
  return <Badge key={status} className="anim-fade" tone={STATUS_TONE[status] || 'idle'}>{fmt.label(status)}</Badge>;
}

export function Chip({ active, onClick, children, count }) {
  return (
    <motion.button type="button" onClick={onClick} whileTap={{ scale: 0.94 }} aria-pressed={!!active}
      className={clsx('inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-sm font-medium transition-colors',
        active ? 'bg-ink text-white' : 'bg-surface-sunken text-ink-soft hover:bg-surface-line')}>
      {children}
      {count !== undefined && <span className={clsx('tabular', active ? 'text-white/60' : 'text-ink-muted')}>{count}</span>}
    </motion.button>
  );
}

/* One button system: dark = primary, brand = primary on maps/hero, outline = secondary,
   ghost = tertiary, danger / dangerSolid = destructive. */
const BTN = {
  dark: 'bg-ink text-white hover:bg-ink-soft',
  brand: 'bg-brand text-white hover:bg-brand-strong',
  outline: 'border border-surface-line bg-surface text-ink hover:bg-surface-subtle',
  ghost: 'text-ink-soft hover:bg-surface-sunken',
  danger: 'border border-bad/30 bg-surface text-bad hover:bg-bad-soft',
  dangerSolid: 'bg-bad text-white hover:brightness-95',
};

/** busy -> spinner + disabled (no double submit); done -> brief check mark (success feedback). */
export const Button = forwardRef(function Button(
  { variant = 'outline', size = 'md', busy, done, icon: Icon, className, children, disabled, ...rest }, ref,
) {
  return (
    <motion.button ref={ref} type="button" disabled={disabled || busy} aria-busy={busy || undefined}
      whileTap={disabled || busy ? undefined : { scale: 0.96 }} whileHover={disabled || busy ? undefined : { y: -1 }}
      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      className={clsx('inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl font-medium transition-[background-color,opacity,box-shadow] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 disabled:pointer-events-none disabled:opacity-50',
        size === 'lg' ? 'h-12 px-6 text-[15px]' : size === 'sm' ? 'h-8 px-3 text-xs' : 'h-10 px-4 text-sm', BTN[variant], className)}
      {...rest}>
      <AnimatePresence mode="popLayout" initial={false}>
        {busy ? (
          <motion.span key="busy" initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.6 }}>
            <Loader2 className="h-4 w-4 animate-spin" /></motion.span>
        ) : done ? (
          <motion.span key="done" initial={{ opacity: 0, scale: 0.4, rotate: -30 }} animate={{ opacity: 1, scale: 1, rotate: 0 }} exit={{ opacity: 0 }}>
            <Check className="h-4 w-4" /></motion.span>
        ) : Icon ? (
          <motion.span key="icon" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><Icon className="h-4 w-4" /></motion.span>
        ) : null}
      </AnimatePresence>
      {children}
    </motion.button>
  );
});

export function IconButton({ icon: Icon, label, className, active, ...rest }) {
  return (
    <button type="button" aria-label={label} title={label}
      className={clsx('grid h-10 w-10 place-items-center rounded-full border border-surface-line transition-colors',
        active ? 'bg-ink text-white' : 'bg-surface text-ink hover:bg-surface-subtle', className)} {...rest}>
      <Icon className="h-[18px] w-[18px]" />
    </button>
  );
}

export function Avatar({ name, color, size = 40, className }) {
  return (
    <span className={clsx('grid shrink-0 place-items-center rounded-full font-semibold text-white', className)}
      style={{ width: size, height: size, background: color, fontSize: size * 0.36 }}>
      {fmt.initials(name)}
    </span>
  );
}

export function Bar({ value, color, className }) {
  return (
    <div className={clsx('h-1 w-full overflow-hidden rounded-full bg-surface-sunken', className)}>
      <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${Math.min(100, Math.max(0, value * 100))}%`, background: color }} />
    </div>
  );
}

/** Segmented progress (one segment per stop), like the next-stop indicator. */
export function Segments({ total, done, current, doneClass = 'bg-ink', currentClass = 'bg-brand' }) {
  return (
    <div className="flex gap-1.5">
      {Array.from({ length: Math.max(total, 1) }).map((_, i) => (
        <span key={i} className={clsx('h-1 flex-1 rounded-full', i < done ? doneClass : i === current ? currentClass : 'bg-surface-sunken')} />
      ))}
    </div>
  );
}

export function StatTile({ label, value, className }) {
  return (
    <div className={clsx('card px-3 py-2.5', className)}>
      <div className="label">{label}</div>
      <div className="tabular mt-1 text-[17px] font-semibold">{value}</div>
    </div>
  );
}

export function KpiChip({ label, value, delta, positive = true, highlight }) {
  return (
    <div className={clsx('min-w-[112px] rounded-card border px-4 py-2.5', highlight ? 'border-ok/20 bg-ok-soft/60' : 'border-surface-line bg-surface')}>
      <div className="text-xs text-ink-muted">{label}</div>
      <div className="tabular mt-0.5 flex items-baseline gap-2 text-xl font-semibold">
        {value}
        {delta !== undefined && delta !== null && (
          <span className={clsx('text-xs font-semibold', positive ? 'text-ok' : 'text-bad')}>{positive ? '↓' : '↑'} {delta}</span>
        )}
      </div>
    </div>
  );
}

export function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="label mb-1 block">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-2xs text-ink-faint">{hint}</span>}
    </label>
  );
}

export function Select({ value, onChange, options, className }) {
  return (
    <select className={clsx('input pr-8', className)} value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
      ))}
    </select>
  );
}

export function Toggle({ checked, onChange, label }) {
  return (
    <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2 text-sm text-ink-soft">
      <span className={clsx('relative h-5 w-9 shrink-0 rounded-full transition-colors', checked ? 'bg-brand' : 'bg-surface-line')}>
        <motion.span className="absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white shadow" initial={false}
          animate={{ x: checked ? 16 : 2 }} transition={{ type: 'spring', stiffness: 600, damping: 32 }} />
      </span>
      {label}
    </button>
  );
}

export function SectionTitle({ children, aside }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h3 className="text-[15px] font-semibold">{children}</h3>
      {aside && <span className="text-xs text-ink-muted">{aside}</span>}
    </div>
  );
}

export function Empty({ icon: Icon, title, children }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {Icon && <Icon className="h-6 w-6 text-ink-faint" />}
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="max-w-xs text-xs text-ink-muted">{children}</div>}
    </div>
  );
}

export function Skeleton({ className, style }) {
  return <span aria-hidden className={clsx('skeleton block', className)} style={style} />;
}

export function SkeletonRows({ rows = 6, cols = 6 }) {
  return Array.from({ length: rows }).map((_, r) => (
    <tr key={r} className="border-b border-surface-line">
      {Array.from({ length: cols }).map((__, c) => (
        <td key={c} className="px-3 py-3.5"><Skeleton className="h-3.5" style={{ width: `${50 + ((r * 7 + c * 13) % 45)}%` }} /></td>
      ))}
    </tr>
  ));
}

export function ErrorState({ message, onRetry }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      <AlertCircle className="h-6 w-6 text-bad" />
      <div className="text-sm font-medium">Could not load data</div>
      <div className="max-w-sm text-xs text-ink-muted">{message}</div>
      {onRetry && <Button size="sm" icon={RotateCw} onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Checkbox({ checked, indeterminate, onChange, label, className, disabled }) {
  return (
    <input type="checkbox" aria-label={label} checked={!!checked} disabled={disabled}
      ref={(el) => { if (el) el.indeterminate = !!indeterminate && !checked; }}
      onChange={(e) => onChange(e.target.checked)}
      className={clsx('h-4 w-4 cursor-pointer rounded accent-[theme(colors.ink.DEFAULT)] disabled:cursor-not-allowed disabled:opacity-40', className)} />
  );
}

/** Segmented control (single choice). */
export function Segmented({ value, onChange, options, size = 'md', className }) {
  return (
    <div role="radiogroup" className={clsx('inline-flex rounded-xl bg-surface-sunken p-1', className)}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} disabled={o.disabled}
          title={o.title} onClick={() => onChange(o.value)}
          className={clsx('relative rounded-lg font-medium transition-colors disabled:opacity-40',
            size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm',
            value === o.value ? 'text-ink' : 'text-ink-muted hover:text-ink')}>
          {value === o.value && <motion.span layoutId={`seg-${options.map((x) => x.value).join('')}`} transition={{ type: 'spring', stiffness: 500, damping: 38 }}
            className="absolute inset-0 rounded-lg bg-surface shadow-sm" />}
          <span className="relative">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

export function Spinner({ label }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-ink-muted">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[28px] font-extrabold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Th({ children, className }) {
  return <th className={clsx('whitespace-nowrap px-3 py-2.5 text-left text-xs font-medium text-ink-muted', className)}>{children}</th>;
}

export function Td({ children, className }) {
  return <td className={clsx('whitespace-nowrap px-3 py-2.5 text-sm', className)}>{children}</td>;
}
