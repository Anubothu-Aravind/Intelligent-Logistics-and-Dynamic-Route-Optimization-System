import { NavLink } from 'react-router-dom';
import clsx from 'clsx';
import { BarChart3, Boxes, FileCode2, FlaskConical, Map, Route, Truck } from 'lucide-react';
import { useLive } from '../../hooks/live';

export const NAV = [
  { to: '/', icon: Map, label: 'Live map' },
  { to: '/dispatch', icon: Route, label: 'Route & dispatch' },
  { to: '/orders', icon: Boxes, label: 'Orders' },
  { to: '/fleet', icon: Truck, label: 'Fleet & depots' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/lab', icon: FlaskConical, label: 'Algorithm lab' },
];

export default function Sidebar() {
  const { connected } = useLive();
  return (
    <nav aria-label="Main" className="flex w-[72px] shrink-0 flex-col items-center gap-2 border-r border-surface-line bg-surface py-5">
      <div className="mb-5 grid h-10 w-10 place-items-center rounded-xl bg-brand text-white shadow-float" title="Intelligent Logistics">
        <Route className="h-5 w-5" strokeWidth={2.4} />
      </div>
      {NAV.map(({ to, icon: Icon, label }) => (
        <NavLink key={to} to={to} end={to === '/'} title={label} aria-label={label}
          className={({ isActive }) => clsx('grid h-11 w-11 place-items-center rounded-xl transition-colors',
            isActive ? 'bg-brand-soft text-brand' : 'text-ink-muted hover:bg-surface-sunken hover:text-ink')}>
          <Icon className="h-5 w-5" />
        </NavLink>
      ))}
      <div className="mt-auto flex flex-col items-center gap-3">
        <a href="/docs" target="_blank" rel="noreferrer" title="API documentation (opens Swagger in a new tab)" aria-label="API documentation"
          className="grid h-11 w-11 place-items-center rounded-xl text-ink-muted hover:bg-surface-sunken">
          <FileCode2 className="h-5 w-5" />
        </a>
        <span title={connected ? 'Live connection' : 'Reconnecting…'}
          className={clsx('h-2.5 w-2.5 rounded-full', connected ? 'bg-ok' : 'bg-warn')} />
      </div>
    </nav>
  );
}
