import { CircleMarker, Marker, Polyline, Tooltip } from 'react-leaflet';
import { colors } from '../../theme/tokens';
import { closureIcon, depotIcon } from './markers';

export function DepotLayer({ depots }) {
  return depots?.map((d) => (
    <Marker key={d.id} position={[d.lat, d.lon]} icon={DEPOT_ICON} zIndexOffset={500}>
      <Tooltip direction="top" offset={[0, -14]} className="chip-tooltip">{d.name}{d.vehicles !== undefined ? ` · ${d.vehicles} vehicle(s)` : ''}</Tooltip>
    </Marker>
  ));
}

/** Congestion (slow traffic = amber, jam = red) and road closures. */
export function TrafficLayer({ traffic, jamFactor }) {
  if (!traffic) return null;
  return (
    <>
      {traffic.congestions.map((c) => (
        <Polyline key={`c${c.id}`} positions={c.segments} interactive
          pathOptions={{ color: c.factor >= jamFactor ? colors.bad.DEFAULT : colors.warn.DEFAULT, weight: 5, opacity: 0.85, lineCap: 'round' }}>
          <Tooltip sticky className="chip-tooltip">Traffic ×{c.factor} until {c.until_hhmm}</Tooltip>
        </Polyline>
      ))}
      {traffic.closures.map((c) => (
        <span key={`x${c.id}`}>
          <Polyline positions={c.coords} pathOptions={{ color: colors.bad.DEFAULT, weight: 6, dashArray: '6 6' }} />
          <Marker position={c.coords[Math.floor(c.coords.length / 2)]} icon={closureIcon()}>
            <Tooltip direction="top" className="chip-tooltip">Closed · {c.street}</Tooltip>
          </Marker>
        </span>
      ))}
    </>
  );
}

const DEPOT_ICON = depotIcon();

export function OrderDots({ orders, color = colors.ink.faint, radius = 4, onClick }) {
  return orders.map((o) => (
    <CircleMarker key={o.id} center={[o.lat, o.lon]} radius={radius}
      pathOptions={{ color: '#fff', weight: 1.5, fillColor: color, fillOpacity: 1 }}
      eventHandlers={onClick ? { click: () => onClick(o) } : undefined}>
      <Tooltip className="chip-tooltip">{o.code} · {o.weight_kg} kg · {o.priority}</Tooltip>
    </CircleMarker>
  ));
}
