import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { useMap } from 'react-leaflet';
import { colors } from '../../theme/tokens';
import { fmt } from '../../lib/format';

/** Position on a timed polyline [[lat, lon, t], …] at simulation time t. */
function positionAt(motion, t) {
  if (!motion?.length) return null;
  if (t <= motion[0][2]) return { lat: motion[0][0], lon: motion[0][1], heading: heading(motion[0], motion[1]) };
  for (let i = 0; i < motion.length - 1; i += 1) {
    const a = motion[i];
    const b = motion[i + 1];
    if (t <= b[2]) {
      const f = b[2] > a[2] ? (t - a[2]) / (b[2] - a[2]) : 1;
      return { lat: a[0] + (b[0] - a[0]) * f, lon: a[1] + (b[1] - a[1]) * f, heading: heading(a, b) };
    }
  }
  const z = motion[motion.length - 1];
  return { lat: z[0], lon: z[1], heading: heading(motion[motion.length - 2], z) };
}

function heading(a, b) {
  if (!a || !b) return null;
  const dx = (b[1] - a[1]) * Math.cos((a[0] * Math.PI) / 180);
  const dy = b[0] - a[0];
  if (Math.abs(dx) + Math.abs(dy) < 1e-12) return null;
  return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
}

function iconFor(color, selected) {
  const size = selected ? 40 : 26;
  const halo = selected
    ? `<span class="pulse-ring" style="position:absolute;inset:-34px;border-radius:9999px;background:${colors.brand.glow}"></span>
       <span style="position:absolute;inset:-30px;border-radius:9999px;background:${colors.brand.glow}"></span>`
    : '';
  return L.divIcon({
    className: 'vehicle-marker',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="position:relative;width:${size}px;height:${size}px">${halo}
      <div style="position:relative;width:${size}px;height:${size}px;border-radius:9999px;background:${color};
        border:${selected ? 4 : 3}px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.25);display:grid;place-items:center;
        transition:background-color .4s">
        <svg data-arrow width="14" height="14" viewBox="0 0 24 24"><path d="M12 3l7 17-7-4-7 4z" fill="#fff"/></svg></div></div>`,
  });
}

/** Imperative Leaflet layer: markers are created once and moved every animation
 *  frame (no React re-render per frame, no icon rebuild unless colour/selection changes). */
export default function AnimatedVehicles({ vehicles, simNow, selectedId, colorOf, onSelect }) {
  const map = useMap();
  const items = useRef(new Map());
  const latest = useRef({ vehicles, selectedId });
  latest.current = { vehicles, selectedId };

  useEffect(() => {
    const seen = new Set();
    vehicles.forEach((v) => {
      if (v.status === 'inactive') return;
      seen.add(v.id);
      const selected = v.id === selectedId;
      const color = selected ? colors.brand.DEFAULT : colorOf(v);
      let it = items.current.get(v.id);
      if (!it) {
        const marker = L.marker([v.lat, v.lon], { icon: iconFor(color, selected), keyboard: true, title: v.code })
          .on('click', () => onSelect(v.id))
          .addTo(map);
        it = { marker, color, selected, heading: null };
        items.current.set(v.id, it);
      } else if (it.color !== color || it.selected !== selected) {
        it.marker.setIcon(iconFor(color, selected));
        it.color = color;
        it.selected = selected;
        it.heading = null;
      }
      it.v = v;
      it.marker.setZIndexOffset(selected ? 1000 : 100);
      const label = `<span style="display:inline-block;width:8px;height:8px;border-radius:9999px;background:${colorOf(v)};margin-right:6px"></span>${v.code} <span style="opacity:.6">${fmt.num(v.speed_kmh)} km/h</span>`;
      if (selected) {
        if (!it.marker.getTooltip()) it.marker.bindTooltip(label, { permanent: true, direction: 'left', offset: [-22, 0], className: 'chip-tooltip' });
        else it.marker.setTooltipContent(label);
      } else if (it.marker.getTooltip()) {
        it.marker.unbindTooltip();
      }
    });
    items.current.forEach((it, id) => {
      if (!seen.has(id)) { it.marker.remove(); items.current.delete(id); }
    });
  }, [vehicles, selectedId, colorOf, onSelect, map]);

  useEffect(() => {
    let raf;
    const frame = () => {
      const t = simNow();
      items.current.forEach((it) => {
        const v = it.v;
        if (!v) return;
        const p = (v.status === 'moving' || v.status === 'scheduled') && v.motion ? positionAt(v.motion, t) : null;
        const lat = p ? p.lat : v.lat;
        const lon = p ? p.lon : v.lon;
        const ll = it.marker.getLatLng();
        if (Math.abs(ll.lat - lat) > 1e-9 || Math.abs(ll.lng - lon) > 1e-9) it.marker.setLatLng([lat, lon]);
        const h = p?.heading ?? v.heading;
        if (h !== null && h !== undefined && Math.abs((it.heading ?? -999) - h) > 0.5) {
          const arrow = it.marker.getElement()?.querySelector('[data-arrow]');
          if (arrow) { arrow.style.transform = `rotate(${h}deg)`; it.heading = h; }
        }
      });
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [simNow]);

  useEffect(() => () => { items.current.forEach((it) => it.marker.remove()); items.current.clear(); }, []);
  return null;
}
