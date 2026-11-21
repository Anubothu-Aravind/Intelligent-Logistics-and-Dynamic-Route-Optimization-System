// Single source of design tokens – consumed by tailwind.config.js AND by
// JavaScript that needs raw colour strings (Leaflet layers, Recharts series).
export const colors = {
  brand: { DEFAULT: '#F25C1F', soft: '#FDEBE2', strong: '#D9480F', glow: 'rgba(242,92,31,0.18)' },
  ink: { DEFAULT: '#14161A', soft: '#3B3F46', muted: '#7B808A', faint: '#A9ADB5' },
  surface: { DEFAULT: '#FFFFFF', subtle: '#F6F5F3', sunken: '#EFEEEB', line: '#E6E4E0' },
  canvas: { DEFAULT: '#ECE9E4', block: '#E4E0DA', road: '#FFFFFF', arterial: '#FFFFFF', park: '#DCE8D5', water: '#CFE0EC' },
  ok: { DEFAULT: '#1F9D55', soft: '#E3F5EA' },
  warn: { DEFAULT: '#E6A100', soft: '#FDF3D8' },
  bad: { DEFAULT: '#E5484D', soft: '#FDE7E8' },
  idle: { DEFAULT: '#9AA0A8', soft: '#EEEFF1' },
};

// categorical palette for per-vehicle routes (image 2 – coral, blue, purple …)
export const routePalette = [
  '#F2775B', '#5FA8C7', '#7C5BA6', '#3FA27A', '#E0A33B', '#D05C8C', '#4F79C9', '#8E9B3A', '#C8693E', '#3E9DA8',
  '#B05CC8', '#6E8B5E',
];

export const statusColor = {
  moving: colors.ok.DEFAULT,
  delayed: colors.warn.DEFAULT,
  idle: colors.idle.DEFAULT,
  done: colors.idle.DEFAULT,
  servicing: colors.brand.DEFAULT,
  reloading: colors.ink.soft,
  blocked: colors.bad.DEFAULT,
  inactive: colors.ink.faint,
};

export const chart = {
  grid: colors.surface.line,
  axis: colors.ink.muted,
  outcomes: { early: colors.warn.DEFAULT, on_time: colors.ok.DEFAULT, late: colors.bad.DEFAULT },
  priorities: { high: colors.bad.DEFAULT, medium: colors.warn.DEFAULT, low: colors.idle.DEFAULT },
  before: colors.ink.faint,
  after: colors.brand.DEFAULT,
};

export const fonts = {
  sans: ['Inter', 'system-ui', 'sans-serif'],
  mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
};
