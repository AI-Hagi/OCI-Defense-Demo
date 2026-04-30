// UC4 — Camera viewport singleton.
//
// Each Pattern-A layer (flights-civil, flights-mil, jamming) and the
// Pattern-B maritime layer needs to ask the backend for data scoped to
// the operator's current Cesium camera viewport rather than the fixed
// Baltic poll. This module owns the Cesium Viewer reference, computes
// (centerLat, centerLon, distNm) + bbox on demand, and notifies
// subscribers (debounced) whenever the camera stops moving.
//
// LagebildView wires the Viewer in once via `bindViewer(viewer)`;
// layer modules call `subscribe(cb)` on enable and the returned
// `unsubscribe()` on disable. They use `getViewport()` to read the
// current value (e.g. on first fetch before the first move event).

import {
  Math as CesiumMath,
  Rectangle,
  type Viewer,
} from 'cesium';

export interface Viewport {
  /** Center lat in degrees. */
  lat: number;
  /** Center lon in degrees. */
  lon: number;
  /**
   * Half-diagonal in nautical miles, capped at 250 (adsb.lol free-tier
   * radius limit). We send this as the `dist` query param so the
   * backend's circle covers the visible map; the LB-side cache is
   * keyed on quantised lat/lon/dist so adjacent users share calls.
   */
  distNm: number;
  /** Bounding box in degrees, [south, west, north, east]. */
  bbox: [number, number, number, number];
}

const NM_PER_DEG_LAT = 60;             // 1° latitude ≈ 60 nm
const ADSB_MAX_DIST_NM = 250;
const DEBOUNCE_MS = 600;               // matches typical user "stopped panning" perception

let viewer: Viewer | null = null;
let listeners: Set<(v: Viewport) => void> = new Set();
let debounceTimer: ReturnType<typeof setTimeout> | null = null;
let lastViewport: Viewport | null = null;
let cesiumMoveEndUnsub: (() => void) | null = null;

function rectToViewport(rect: Rectangle): Viewport {
  const south = CesiumMath.toDegrees(rect.south);
  const west = CesiumMath.toDegrees(rect.west);
  const north = CesiumMath.toDegrees(rect.north);
  const east = CesiumMath.toDegrees(rect.east);
  const lat = (south + north) / 2;
  const lon = (west + east) / 2;

  // Half-diagonal in nm. Latitude span is ~60 nm/°; longitude span depends on cosine of the
  // mid-latitude. Take the larger of half-width / half-height — that's the radius the camera
  // viewport circumscribes — then cap at the adsb.lol 250 nm limit.
  const halfHeightNm = ((north - south) / 2) * NM_PER_DEG_LAT;
  const cosLat = Math.cos(CesiumMath.toRadians(lat));
  const halfWidthNm = ((east - west) / 2) * NM_PER_DEG_LAT * Math.max(cosLat, 0.05);
  const distNm = Math.min(
    ADSB_MAX_DIST_NM,
    Math.max(10, Math.ceil(Math.max(halfHeightNm, halfWidthNm) * 1.1)),
  );

  return { lat, lon, distNm, bbox: [south, west, north, east] };
}

function fallbackViewport(): Viewport {
  // Cesium returns undefined for `computeViewRectangle()` when the
  // camera is far enough out that the horizon is the ellipsoid limb
  // (the whole earth is visible). In that case we hand back a
  // capped-at-Baltic default so layers still resolve to something
  // and the user sees data after they zoom in.
  return {
    lat: 54.5,
    lon: 15.0,
    distNm: ADSB_MAX_DIST_NM,
    bbox: [40, -10, 70, 40],
  };
}

export function getViewport(): Viewport {
  if (viewer && !viewer.isDestroyed()) {
    const rect = viewer.camera.computeViewRectangle();
    if (rect) {
      lastViewport = rectToViewport(rect);
      return lastViewport;
    }
  }
  return lastViewport ?? fallbackViewport();
}

function emit(): void {
  const v = getViewport();
  listeners.forEach((cb) => {
    try {
      cb(v);
    } catch {
      // listener errors must not block other subscribers
    }
  });
}

export function bindViewer(v: Viewer): void {
  // Bind once; unbinding the old listener is safe to no-op when nothing
  // was registered.
  if (cesiumMoveEndUnsub) {
    cesiumMoveEndUnsub();
    cesiumMoveEndUnsub = null;
  }
  viewer = v;
  const handler = () => {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      emit();
    }, DEBOUNCE_MS);
  };
  v.camera.moveEnd.addEventListener(handler);
  cesiumMoveEndUnsub = () => v.camera.moveEnd.removeEventListener(handler);
}

export function subscribe(cb: (v: Viewport) => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/**
 * Build the `?lat=&lon=&dist=` query suffix consumed by the
 * Pattern-A flights/jamming endpoints.
 */
export function viewportQuery(v: Viewport): string {
  const lat = v.lat.toFixed(4);
  const lon = v.lon.toFixed(4);
  return `lat=${lat}&lon=${lon}&dist=${v.distNm}`;
}

/**
 * Build the `?bbox_s=&bbox_w=&bbox_n=&bbox_e=` suffix used by the
 * Maritime AIS multiplexer.
 */
export function bboxQuery(v: Viewport): string {
  const [s, w, n, e] = v.bbox;
  return `bbox_s=${s.toFixed(4)}&bbox_w=${w.toFixed(4)}&bbox_n=${n.toFixed(4)}&bbox_e=${e.toFixed(4)}`;
}
