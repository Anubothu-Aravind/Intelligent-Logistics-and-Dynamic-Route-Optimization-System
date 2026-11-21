import { useEffect, useMemo, useRef } from 'react';
import L from 'leaflet';
import { useMap } from 'react-leaflet';

/** Draws the first `step` explored nodes. Markers are added/removed incrementally on a
 *  dedicated canvas renderer, so stepping through thousands of nodes stays smooth. */
export default function ExploreLayer({ points, step, forward, backward, frontier }) {
  const map = useMap();
  const renderer = useMemo(() => L.canvas({ padding: 0.3 }), []);
  const group = useRef(null);
  const drawn = useRef([]);
  const head = useRef(null);

  useEffect(() => {
    group.current = L.layerGroup().addTo(map);
    return () => { group.current.remove(); drawn.current = []; };
  }, [map]);

  useEffect(() => {
    drawn.current.forEach((m) => m.remove());
    drawn.current = [];
  }, [points]);

  useEffect(() => {
    const g = group.current;
    if (!g || !points) return;
    while (drawn.current.length > step) drawn.current.pop().remove();
    for (let i = drawn.current.length; i < Math.min(step, points.length); i += 1) {
      const [lat, lon, side] = points[i];
      const c = side ? backward : forward;
      drawn.current.push(L.circleMarker([lat, lon], {
        renderer, radius: 3.2, weight: 0, fillColor: c, fillOpacity: 0.55, interactive: false,
      }).addTo(g));
    }
    head.current?.remove();
    if (step > 0 && step <= points.length) {
      const [lat, lon] = points[step - 1];
      head.current = L.circleMarker([lat, lon], { renderer, radius: 7, color: frontier, weight: 3, fillOpacity: 0, interactive: false }).addTo(g);
    }
  }, [points, step, forward, backward, frontier, renderer]);
  return null;
}
