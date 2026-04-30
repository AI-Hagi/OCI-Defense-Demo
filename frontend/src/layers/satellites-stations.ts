// UC4 — Satellites: Stations sub-layer (Pattern A REST poll +
// client-side SGP4 propagation).
//
// Source: tle-proxy backend keeps a 6 h cache of CelesTrak's `stations`
// catalog (ISS, Tiangong, etc., ~6 records). Browser fetches the raw
// TLE blob once on enable, then uses satellite.js SGP4 every 1 s to
// recompute geodetic lat/lon/alt for each record. Cesium Entities with
// `CallbackProperty` positions update without re-creating primitives.
//
// Click-to-Inspect: each station Entity carries `_wv*` so the LagebildView
// intel panel renders name, NORAD ID, orbit class, period, current alt.

import {
  Cartesian3,
  Cartesian2,
  CallbackProperty,
  Color,
  HeightReference,
  HorizontalOrigin,
  JulianDate,
  VerticalOrigin,
  type Entity,
  type Viewer,
} from 'cesium';
import { LayerRegistry } from './registry';
import {
  orbitClass,
  parseTleCollection,
  propagatePosition,
  type OrbitClass,
  type SatPosition,
  type SatelliteRecord,
  type TleCollection,
} from './satellites-shared';
import type {
  CesiumLayer,
  ClickInspectMetaItem,
  WvProps,
} from './types';

// ---------------------------------------------------------------------------
// URL helper — origin-relative by default.
// ---------------------------------------------------------------------------

function resolveUrl(raw: string): string {
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw;
  if (typeof window === 'undefined') return raw;
  const proto = window.location.protocol === 'https:' ? 'https:' : 'http:';
  const path = raw.startsWith('/') ? raw : `/${raw}`;
  return `${proto}//${window.location.host}${path}`;
}

const API_URL = resolveUrl(
  (import.meta.env.VITE_SATELLITES_STATIONS_URL as string | undefined) ??
    '/api/osint/satellites/stations/current',
);

const TLE_REFRESH_MS = 6 * 60 * 60 * 1000; // 6 h — backend already caches this long
const PROP_REFRESH_MS = 1000;              // 1 Hz orbit step

// ---------------------------------------------------------------------------
// Module state — scoped to one enable/disable cycle.
// ---------------------------------------------------------------------------

interface StationState {
  record: SatelliteRecord;
  entity: Entity;
  // Cached every propagation tick — drives the CallbackProperty + the
  // intel panel meta (lat/lon/alt update live without re-rendering Entities).
  lastPosition: SatPosition | null;
}

const stationsByNorad: Map<string, StationState> = new Map();
let tleRefreshTimer: ReturnType<typeof setInterval> | null = null;
let propRefreshTimer: ReturnType<typeof setInterval> | null = null;
let activeViewer: Viewer | null = null;
const countListeners: Set<(n: number) => void> = new Set();

// ---------------------------------------------------------------------------
// Icon — small white dot with a halo, station-like "look at me" feel.
// ---------------------------------------------------------------------------

const STATION_ICON_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20">
  <circle cx="12" cy="12" r="9" fill="none" stroke="#a78bfa" stroke-width="1.2" opacity="0.6"/>
  <circle cx="12" cy="12" r="4" fill="#a78bfa" stroke="#312e81" stroke-width="1"/>
</svg>`.trim();
const STATION_ICON_DATA_URI = `data:image/svg+xml;utf8,${encodeURIComponent(STATION_ICON_SVG)}`;

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

function emitCount(): void {
  const n = stationsByNorad.size;
  countListeners.forEach((cb) => {
    try { cb(n); } catch { /* swallow listener errors */ }
  });
}

function buildMeta(state: StationState): ClickInspectMetaItem[] {
  const { record, lastPosition } = state;
  const alt = lastPosition?.altKm ?? 0;
  const klass: OrbitClass = orbitClass(alt, record.periodMinutes);
  const items: ClickInspectMetaItem[] = [
    { key: 'Name', val: record.name },
    { key: 'NORAD-ID', val: record.noradId },
    { key: 'Orbit-Klasse', val: klass },
  ];
  if (Number.isFinite(record.periodMinutes) && record.periodMinutes > 0) {
    items.push({ key: 'Periode', val: `${record.periodMinutes.toFixed(1)} min` });
  }
  if (lastPosition) {
    items.push({ key: 'Höhe (aktuell)', val: `${lastPosition.altKm.toFixed(1)} km` });
    items.push({ key: 'Position (aktuell)', val: `${lastPosition.lat.toFixed(2)}, ${lastPosition.lon.toFixed(2)}` });
  }
  items.push({ key: 'Quelle', val: 'CelesTrak NORAD GP — stations' });
  return items;
}

function applyWvProps(state: StationState): void {
  const { lastPosition, entity } = state;
  const props: WvProps = {
    _wvType: 'satellite',
    _wvMeta: buildMeta(state),
    _wvLat: lastPosition?.lat ?? 0,
    _wvLon: lastPosition?.lon ?? 0,
    _wvClassification: 100,
    _wvSources: ['CelesTrak NORAD TLE catalog'],
  };
  Object.assign(entity, props);
}

function createEntity(viewer: Viewer, record: SatelliteRecord): Entity {
  // Position is a CallbackProperty so we can update lastPosition every
  // 1 s without recreating the Entity. The closure captures the state
  // entry which we mutate in-place.
  const state: StationState = { record, entity: undefined as unknown as Entity, lastPosition: null };
  const positionProperty = new CallbackProperty(() => {
    if (!state.lastPosition) return Cartesian3.fromDegrees(0, 0);
    return Cartesian3.fromDegrees(
      state.lastPosition.lon,
      state.lastPosition.lat,
      state.lastPosition.altKm * 1000,
    );
  }, false) as unknown as never;

  const entity = viewer.entities.add({
    id: `satellites-stations:${record.noradId}`,
    position: positionProperty,
    billboard: {
      image: STATION_ICON_DATA_URI,
      width: 20,
      height: 20,
      horizontalOrigin: HorizontalOrigin.CENTER,
      verticalOrigin: VerticalOrigin.CENTER,
      heightReference: HeightReference.NONE,
    },
    label: {
      text: record.name,
      font: '11px sans-serif',
      fillColor: Color.WHITE,
      outlineColor: Color.fromCssColorString('#312e81'),
      outlineWidth: 2,
      showBackground: true,
      backgroundColor: new Color(0.18, 0.16, 0.55, 0.6),
      pixelOffset: new Cartesian2(0, -16),
    },
  });
  state.entity = entity;
  stationsByNorad.set(record.noradId, state);
  return entity;
}

// ---------------------------------------------------------------------------
// TLE fetch + propagation loop.
// ---------------------------------------------------------------------------

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
  const incomingNorads = new Set<string>();

  for (const record of records) {
    incomingNorads.add(record.noradId);
    if (!stationsByNorad.has(record.noradId)) {
      createEntity(viewer, record);
    } else {
      // Same NORAD-ID, refreshed TLE — replace the SatRec in place. The
      // CallbackProperty closure captures the state entry, so swapping
      // its `record` field is enough.
      const state = stationsByNorad.get(record.noradId)!;
      state.record = record;
    }
  }

  // Drop entities that disappeared from the latest catalog (rare for
  // stations but harmless).
  for (const [norad, state] of Array.from(stationsByNorad.entries())) {
    if (!incomingNorads.has(norad)) {
      viewer.entities.remove(state.entity);
      stationsByNorad.delete(norad);
    }
  }

  // Run a propagation tick immediately so the entities have a real
  // position before the user sees them.
  propagateOnce(viewer);
  emitCount();
}

function propagateOnce(viewer: Viewer): void {
  const now = JulianDate.toDate(JulianDate.now());
  for (const state of stationsByNorad.values()) {
    state.lastPosition = propagatePosition(state.record.satrec, now);
    applyWvProps(state);
  }
  viewer.scene.requestRender();
}

// ---------------------------------------------------------------------------
// CesiumLayer contract.
// ---------------------------------------------------------------------------

export const satellitesStationsLayer: CesiumLayer = {
  name: 'satellites-stations',
  label: 'Satelliten: Stationen',
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
    for (const state of stationsByNorad.values()) {
      viewer.entities.remove(state.entity);
    }
    stationsByNorad.clear();
    viewer.scene.requestRender();
    emitCount();
  },

  getCount(): number {
    return stationsByNorad.size;
  },

  onCountChange(cb) {
    countListeners.add(cb);
    return () => { countListeners.delete(cb); };
  },
};

LayerRegistry.register(satellitesStationsLayer);

export default satellitesStationsLayer;
