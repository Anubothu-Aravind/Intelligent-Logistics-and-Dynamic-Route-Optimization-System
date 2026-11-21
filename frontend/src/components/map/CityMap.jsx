import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { MapContainer, Pane, Polyline, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import { Layers, Map as MapIcon } from 'lucide-react';
import clsx from 'clsx';
import { colors } from '../../theme/tokens';
import { useNetwork } from '../../hooks/network';
import { useToast } from '../../hooks/toast';

const ROAD_STYLE = {
  local: { weight: 5, color: colors.canvas.road },
  arterial: { weight: 9, color: colors.canvas.arterial },
  diagonal: { weight: 10, color: colors.canvas.arterial },
};
let tileFailureReported = false;

const BasemapContext = createContext(null);
export const useBasemap = () => useContext(BasemapContext);

function FitBounds({ bounds, padding }) {
  const map = useMap();
  useEffect(() => {
    if (!bounds) return;
    // padding: [px, px] for all sides, or { tl: [left, top], br: [right, bottom] } to keep clear of floating panels
    const opts = padding && !Array.isArray(padding)
      ? { paddingTopLeft: padding.tl, paddingBottomRight: padding.br }
      : { padding: padding || [20, 20] };
    map.fitBounds(bounds, opts);
    map.setMinZoom(Math.max(3, map.getBoundsZoom(bounds) - 2));
    map.setMaxBounds(L.latLngBounds(bounds).pad(0.6));
  }, [bounds, map]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function ClickHandler({ onClick }) {
  useMapEvents({ click: (e) => onClick?.(e.latlng) });
  return null;
}

/** Tile layer that reports failure: if tiles keep failing and none load, fall back to
 *  the drawn road graph (once per session) instead of showing an empty grey map. */
function SafeTiles({ ui, onFail }) {
  const stats = useRef({ ok: 0, err: 0 });
  const toast = useToast();
  return (
    <TileLayer url={ui.map_tile_url} attribution={ui.map_tile_attribution}
      subdomains={ui.map_tile_subdomains || 'abc'} detectRetina crossOrigin
      eventHandlers={{
        tileload: () => { stats.current.ok += 1; },
        tileerror: () => {
          stats.current.err += 1;
          if (stats.current.err >= 6 && stats.current.ok === 0) {
            onFail();
            if (!tileFailureReported) {
              tileFailureReported = true;
              toast?.push('Map tiles could not be loaded (offline or blocked) – showing the road network instead', 'bad');
            }
          }
        },
      }} />
  );
}

/** Roads are drawn from the graph the algorithms actually use (with road shapes). */
export function RoadLayer({ network, mode }) {
  const renderer = useMemo(() => L.canvas({ padding: 0.5, pane: 'roads' }), []);
  const byClass = useMemo(() => {
    const groups = { local: [], arterial: [], diagonal: [] };
    network?.roads.forEach((r) => (groups[r.class] || groups.local).push(r.coords));
    return groups;
  }, [network]);
  if (!network) return null;
  return (
    <Pane name="roads" style={{ zIndex: 250 }}>
      {mode === 'tiles'
        ? null
        : ['local', 'arterial', 'diagonal'].map((cls) => (
          <Polyline key={cls} positions={byClass[cls]} renderer={renderer} interactive={false}
            pathOptions={{ ...ROAD_STYLE[cls], lineCap: 'round', lineJoin: 'round', opacity: 1 }} />
        ))}
    </Pane>
  );
}

export default function CityMap({ children, onClick, padding, className, initialBasemap }) {
  const network = useNetwork();
  const [mode, setMode] = useState(null);
  const tilesAllowed = !!network?.ui?.tiles_match_graph;
  const effective = mode || initialBasemap || network?.ui?.default_basemap || 'schematic';
  const basemap = effective === 'tiles' && tilesAllowed ? 'tiles' : 'schematic';
  const ctx = useMemo(() => ({ basemap, setBasemap: setMode, tilesAllowed, network }), [basemap, tilesAllowed, network]);
  if (!network) return <div className={clsx(className, 'skeleton !rounded-none')} />;
  return (
    <BasemapContext.Provider value={ctx}>
      <MapContainer bounds={network.bounds} zoomControl={false} attributionControl
        className={className} style={{ background: colors.canvas.block }} preferCanvas maxZoom={19} zoomSnap={0.25}
        wheelPxPerZoomLevel={90}>
        <FitBounds bounds={network.bounds} padding={padding} />
        {basemap === 'tiles' && <SafeTiles ui={network.ui} onFail={() => setMode('schematic')} />}
        <RoadLayer network={network} mode={basemap} />
        {onClick && <ClickHandler onClick={onClick} />}
        {children}
      </MapContainer>
    </BasemapContext.Provider>
  );
}

/** Zoom + basemap switch. Tiles are only offered when the graph is real OSM roads –
 *  under the generated city they would show streets the routes do not use. */
export function MapControls({ right = 16, bottom = 96 }) {
  const map = useMap();
  const { basemap, setBasemap, tilesAllowed } = useBasemap();
  const btn = 'grid h-11 w-11 place-items-center text-ink hover:bg-surface-subtle transition-colors';
  useEffect(() => {
    const el = document.querySelector('.leaflet-control-container');
    if (el) L.DomEvent.disableClickPropagation(el);
  }, []);
  return (
    <div className="leaflet-bottom leaflet-right" style={{ pointerEvents: 'auto' }}>
      <div className="flex flex-col gap-2" style={{ marginRight: right, marginBottom: bottom }}
        onDoubleClick={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
        <button type="button" onClick={() => setBasemap(basemap === 'tiles' ? 'schematic' : 'tiles')}
          disabled={!tilesAllowed}
          title={tilesAllowed ? (basemap === 'tiles' ? 'Show road network only' : 'Show OpenStreetMap tiles')
            : 'Tiles are available with real OSM roads (CITY_SOURCE=osm); the generated city has no real streets'}
          aria-label="Switch basemap"
          className={clsx('grid h-11 w-11 place-items-center rounded-xl bg-surface shadow-float transition-colors disabled:opacity-40',
            basemap === 'tiles' && 'text-brand')}>
          {basemap === 'tiles' ? <MapIcon className="h-[18px] w-[18px]" /> : <Layers className="h-[18px] w-[18px]" />}
        </button>
        <div className="flex flex-col overflow-hidden rounded-xl bg-surface shadow-float">
          <button type="button" aria-label="Zoom in" className={clsx(btn, 'text-xl')} onClick={() => map.zoomIn()}>+</button>
          <span className="mx-2 h-px bg-surface-line" />
          <button type="button" aria-label="Zoom out" className={clsx(btn, 'text-xl')} onClick={() => map.zoomOut()}>−</button>
        </div>
      </div>
    </div>
  );
}

/** Back-compat alias used by pages. */
export const ZoomControls = MapControls;

/** Tell the user when real roads were requested but the generated city is shown. */
export function NetworkNotice({ className }) {
  const network = useNetwork();
  const reason = network?.meta?.fallback_reason;
  if (!reason) return null;
  return (
    <div className={clsx('rounded-card bg-warn-soft px-3 py-2 text-xs text-ink-soft', className)} role="status">
      <b>Using the generated city.</b> Real OpenStreetMap roads could not be loaded: {reason.slice(0, 140)}
    </div>
  );
}
