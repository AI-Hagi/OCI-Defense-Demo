// UC4 — Satellites: Active sub-layer.
//
// CelesTrak's `active` GROUP is the full operational catalog (~10–15 k
// satellites at the time of writing). Rendering 15 k Cesium Entities
// would tank the frame rate even on dev hardware, so this layer uses
// `PointPrimitiveCollection` with one PointPrimitive per satellite.
// Positions are rewritten in-place every 1 s by re-assigning each
// PointPrimitive.position from the latest SGP4 propagation step.
//
// Trade-off: PointPrimitives are rendered as fast as Cesium can manage
// (no individual labels, no Entity-API CallbackProperty machinery), but
// they don't carry the `_wv*` Click-to-Inspect convention. Clicking on
// an active-catalog dot is intentionally a no-op — the operator picks
// the smaller stations / resource sub-layers when they want details.

import {
  Cartesian3,
  Color,
  JulianDate,
  PointPrimitiveCollection,
  type PointPrimitive,
  type Viewer,
} from 'cesium';
import { LayerRegistry } from './registry';
import {
  parseTleCollection,
  propagatePosition,
  type SatelliteRecord,
  type TleCollection,
} from './satellites-shared';
import type { CesiumLayer } from './types';

function resolveUrl(raw: string): string {
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw;
  if (typeof window === 'undefined') return raw;
  const proto = window.location.protocol === 'https:' ? 'https:' : 'http:';
  const path = raw.startsWith('/') ? raw : `/${raw}`;
  return `${proto}//${window.location.host}${path}`;
}

const API_URL = resolveUrl(
  (import.meta.env.VITE_SATELLITES_ACTIVE_URL as string | undefined) ??
    '/api/osint/satellites/active/current',
);

const TLE_REFRESH_MS = 6 * 60 * 60 * 1000;
const PROP_REFRESH_MS = 1000;

// PointPrimitive styling — built lazily inside enable() so that the
// Cesium `Color` constants are real values (not mocks) at module load
// time. Module-level initialisation interacted badly with the
// LagebildView vitest harness which only mocks a subset of Color.
let POINT_COLOR: Color | null = null;
let POINT_OUTLINE: Color | null = null;

function ensurePointStyle(): { fill: Color; outline: Color } {
  if (!POINT_COLOR) POINT_COLOR = Color.CYAN.withAlpha(0.85);
  if (!POINT_OUTLINE) POINT_OUTLINE = Color.fromCssColorString('#0e7490');
  return { fill: POINT_COLOR, outline: POINT_OUTLINE };
}

interface ActiveSatState {
  record: SatelliteRecord;
  point: PointPrimitive;
}

const satsByNorad: Map<string, ActiveSatState> = new Map();
let collection: PointPrimitiveCollection | null = null;
let tleRefreshTimer: ReturnType<typeof setInterval> | null = null;
let propRefreshTimer: ReturnType<typeof setInterval> | null = null;
let activeViewer: Viewer | null = null;
const countListeners: Set<(n: number) => void> = new Set();

function emitCount(): void {
  const n = satsByNorad.size;
  countListeners.forEach((cb) => {
    try { cb(n); } catch { /* swallow listener errors */ }
  });
}

function ensureCollection(viewer: Viewer): PointPrimitiveCollection {
  if (collection && !collection.isDestroyed()) return collection;
  collection = viewer.scene.primitives.add(new PointPrimitiveCollection()) as PointPrimitiveCollection;
  return collection;
}

async function fetchAndApply(viewer: Viewer): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(API_URL, { headers: { Accept: 'application/json' } });
  } catch {
    return;
  }
  if (!resp.ok) return;
  let payload: TleCollection;
  try {
    payload = (await resp.json()) as TleCollection;
  } catch {
    return;
  }
  if (payload.type !== 'TleCollection' || !Array.isArray(payload.tle)) return;

  const records = parseTleCollection(payload);
  const incoming = new Set<string>();
  const coll = ensureCollection(viewer);

  for (const record of records) {
    incoming.add(record.noradId);
    const existing = satsByNorad.get(record.noradId);
    if (existing) {
      // TLE refresh — same NORAD, swap the SatRec.
      existing.record = record;
      continue;
    }
    const style = ensurePointStyle();
    const point = coll.add({
      position: Cartesian3.fromDegrees(0, 0, 0),
      color: style.fill,
      outlineColor: style.outline,
      outlineWidth: 0.5,
      pixelSize: 2,
    }) as PointPrimitive;
    satsByNorad.set(record.noradId, { record, point });
  }

  for (const [norad, state] of Array.from(satsByNorad.entries())) {
    if (!incoming.has(norad)) {
      coll.remove(state.point);
      satsByNorad.delete(norad);
    }
  }

  propagateOnce(viewer);
  emitCount();
}

function propagateOnce(viewer: Viewer): void {
  const now = JulianDate.toDate(JulianDate.now());
  for (const state of satsByNorad.values()) {
    const pos = propagatePosition(state.record.satrec, now);
    if (pos) {
      state.point.position = Cartesian3.fromDegrees(pos.lon, pos.lat, pos.altKm * 1000);
    }
  }
  viewer.scene.requestRender();
}

export const satellitesActiveLayer: CesiumLayer = {
  name: 'satellites-active',
  label: 'Satelliten: Active',
  domain: 'air',
  pattern: 'A',
  defaultClassification: 100,

  async enable(viewer: Viewer): Promise<void> {
    activeViewer = viewer;
    await fetchAndApply(viewer);
    tleRefreshTimer = setInterval(() => {
      if (activeViewer === viewer) void fetchAndApply(viewer);
    }, TLE_REFRESH_MS);
    propRefreshTimer = setInterval(() => {
      if (activeViewer === viewer) propagateOnce(viewer);
    }, PROP_REFRESH_MS);
  },

  disable(viewer: Viewer): void {
    activeViewer = null;
    if (tleRefreshTimer !== null) {
      clearInterval(tleRefreshTimer);
      tleRefreshTimer = null;
    }
    if (propRefreshTimer !== null) {
      clearInterval(propRefreshTimer);
      propRefreshTimer = null;
    }
    if (collection && !collection.isDestroyed()) {
      try {
        viewer.scene.primitives.remove(collection);
      } catch {
        // Already removed elsewhere — safe to ignore.
      }
    }
    collection = null;
    satsByNorad.clear();
    viewer.scene.requestRender();
    emitCount();
  },

  getCount(): number {
    return satsByNorad.size;
  },

  onCountChange(cb) {
    countListeners.add(cb);
    return () => { countListeners.delete(cb); };
  },
};

LayerRegistry.register(satellitesActiveLayer);

export default satellitesActiveLayer;
