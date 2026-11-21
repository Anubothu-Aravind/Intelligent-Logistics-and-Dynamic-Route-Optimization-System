import L from 'leaflet';
import { colors } from '../../theme/tokens';

const arrow = (rot) => `<svg width="14" height="14" viewBox="0 0 24 24" style="transform:rotate(${rot}deg)"><path d="M12 3l7 17-7-4-7 4z" fill="#fff"/></svg>`;

export function vehicleIcon(color, heading = 0, selected = false) {
  const size = selected ? 40 : 26;
  const halo = selected
    ? `<span class="pulse-ring" style="position:absolute;inset:-34px;border-radius:9999px;background:${colors.brand.glow}"></span>
       <span style="position:absolute;inset:-30px;border-radius:9999px;background:${colors.brand.glow}"></span>`
    : '';
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="position:relative;width:${size}px;height:${size}px">${halo}
      <div style="position:relative;width:${size}px;height:${size}px;border-radius:9999px;background:${color};
        border:${selected ? 4 : 3}px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.25);display:grid;place-items:center">
        ${arrow(heading)}</div></div>`,
  });
}

export function stopIcon(label, { color = colors.ink.DEFAULT, filled = false, size = 24 } = {}) {
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="width:${size}px;height:${size}px;border-radius:9999px;display:grid;place-items:center;
      font:600 ${size < 24 ? 10 : 11}px Inter,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.2);
      background:${filled ? color : '#fff'};color:${filled ? '#fff' : color};border:2px solid ${color}">${label}</div>`,
  });
}

export function depotIcon() {
  return L.divIcon({
    className: '',
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    html: `<div style="width:30px;height:30px;border-radius:8px;background:${colors.ink.DEFAULT};display:grid;place-items:center;
      box-shadow:0 2px 8px rgba(0,0,0,.25);border:2px solid #fff">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 21V9l9-6 9 6v12"/><path d="M9 21v-6h6v6"/></svg></div>`,
  });
}

export function closureIcon() {
  return L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<div style="width:22px;height:22px;border-radius:9999px;background:${colors.bad.DEFAULT};color:#fff;display:grid;place-items:center;
      font:700 13px Inter;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3)">×</div>`,
  });
}

export function pinIcon(label, color) {
  return L.divIcon({
    className: '',
    iconSize: [28, 28],
    iconAnchor: [14, 28],
    html: `<div style="width:28px;height:28px;border-radius:9999px 9999px 9999px 0;transform:rotate(-45deg);background:${color};
      border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3);display:grid;place-items:center">
      <span style="transform:rotate(45deg);color:#fff;font:700 11px Inter">${label}</span></div>`,
  });
}
