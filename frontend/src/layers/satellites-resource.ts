// UC4 — Satellites: Resource (Earth-Observation) sub-layer.
//
// CelesTrak's `resource` GROUP is the Earth-observation catalog:
// Sentinel-1/2/3, Landsat, RADARSAT, etc. About ~160 satellites. These
// are the upstream sources behind the UC4 Sentinel imagery layer, so
// the demo story is "welche Satelliten haben das aktuelle Bild
// aufgenommen, das du gerade siehst?"
//
// Architecture mirrors satellites-stations.ts: Cesium Entity-API with
// CallbackProperty position; full Click-to-Inspect.

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

function resolveUrl(raw: string): string {
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw;
  if (typeof window === 'undefined') return raw;
  const proto = window.location.protocol === 'https:' ? 'https:' : 'http:';
  const path = raw.startsWith('/') ? raw : `/${raw}`;
  return `${proto}//${window.location.host}${path}`;
}

const API_URL = resolveUrl(
  (import.meta.env.VITE_SATELLITES_RESOURCE_URL as string | undefined) ??
    '/api/osint/satellites/resource/current',
);

const TLE_REFRESH_MS = 6 * 60 * 60 * 1000;
const PROP_REFRESH_MS = 1000;

interface SatState {
  record: SatelliteRecord;
  entity: Entity;
  lastPosition: SatPosition | null;
}

const satsByNorad: Map<string, SatState> = new Map();
let tleRefreshTimer: ReturnType<typeof setInterval> | null = null;
let propRefreshTimer: ReturnType<typeof setInterval> | null = null;
let activeViewer: Viewer | null = null;
const countListeners: Set<(n: number) => void> = new Set();

// Earth-observation pin — green inner ring to imply imaging mission.
const RES_ICON_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16">
  <circle cx="12" cy="12" r="9" fill="none" stroke="#10b981" stroke-width="1" opacity="0.7"/>
  <circle cx="12" cy="12" r="3" fill="#10b981" stroke="#064e3b" stroke-width="0.8"/>
</svg>`.trim();
const RES_ICON_DATA_URI = `data:image/svg+xml;utf8,${encodeURIComponent(RES_ICON_SVG)}`;

function emitCount(): void {
  const n = satsByNorad.size;
  countListeners.forEach((cb) => {
    try { cb(n); } catch { /* swallow listener errors */ }
  });
}

function buildMeta(state: SatState): ClickInspectMetaItem[] {
  const { record, lastPosition } = state;
  const alt = lastPosition?.altKm ?? 0;
  const klass: OrbitClass = orbitClass(alt, record.periodMinutes);
  const items: ClickInspectMetaItem[] = [
    { key: 'Name', val: record.name },
    { key: 'NORAD-ID', val: record.noradId },
    { key: 'Orbit-Klasse', val: klass },
    { key: 'Mission', val: 'Earth-Observation (CelesTrak resource)' },
  ];
  if (Number.isFinite(record.periodMinutes) && record.periodMinutes > 0) {
    items.push({ key: 'Periode', val: `${record.periodMinutes.toFixed(1)} min` });
  }
  if (lastPosition) {
    items.push({ key: 'Höhe (aktuell)', val: `${lastPosition.altKm.toFixed(1)} km` });
    items.push({ key: 'Position (aktuell)', val: `${lastPosition.lat.toFixed(2)}, ${lastPosition.lon.toFixed(2)}` });
  }
  items.push({ key: 'Quelle', val: 'CelesTrak NORAD GP — resource' });
  return items;
}

function applyWvProps(state: SatState): void {
  const { lastPosition, entity } = state;
  const props: WvProps = {
    _wvType: 'satellite',
    _wvMeta: buildMeta(state),
    _wvLat: lastPosition?.lat ?? 0,
    _wvLon: lastPosition?.lon ?? 0,
    _wvClassification: 100,
    _wvSources: ['CelesTrak NORAD TLE catalog (resource)'],
  };
  Object.assign(entity, props);
}

function createEntity(viewer: Viewer, record: SatelliteRecord): Entity {
  const state: SatState = { record, entity: undefined as unknown as Entity, lastPosition: null };
  const positionProperty = new CallbackProperty(() => {
    if (!state.lastPosition) return Cartesian3.fromDegrees(0, 0);
    return Cartesian3.fromDegrees(
      state.lastPosition.lon,
      state.lastPosition.lat,
      state.lastPosition.altKm * 1000,
    );
  }, false) as unknown as never;

  const entity = viewer.entities.add({
    id: `satellites-resource:${record.noradId}`,
    position: positionProperty,
    billboard: {
      image: RES_ICON_DATA_URI,
      width: 16,
      height: 16,
      horizontalOrigin: HorizontalOrigin.CENTER,
      verticalOrigin: VerticalOrigin.CENTER,
      heightReference: HeightReference.NONE,
    },
    label: {
      text: record.name,
      font: '10px sans-serif',
      fillColor: Color.WHITE,
      outlineColor: Color.fromCssColorString('#064e3b'),
      outlineWidth: 1,
      showBackground: true,
      backgroundColor: new Color(0.024, 0.31, 0.18, 0.55),
      pixelOffset: new Cartesian2(0, -14),
    },
  });
  state.entity = entity;
  satsByNorad.set(record.noradId, state);
  return entity;
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
  const incomingNorads = new Set<string>();
  for (const record of records) {
    incomingNorads.add(record.noradId);
    if (!satsByNorad.has(record.noradId)) {
      createEntity(viewer, record);
    } else {
      satsByNorad.get(record.noradId)!.record = record;
    }
  }
  for (const [norad, state] of Array.from(satsByNorad.entries())) {
    if (!incomingNorads.has(norad)) {
      viewer.entities.remove(state.entity);
      satsByNorad.delete(norad);
    }
  }
  propagateOnce(viewer);
  emitCount();
}

function propagateOnce(viewer: Viewer): void {
  const now = JulianDate.toDate(JulianDate.now());
  for (const state of satsByNorad.values()) {
    state.lastPosition = propagatePosition(state.record.satrec, now);
    applyWvProps(state);
  }
  viewer.scene.requestRender();
}

export const satellitesResourceLayer: CesiumLayer = {
  name: 'satellites-resource',
  label: 'Satelliten: Earth-Observation',
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
    for (const state of satsByNorad.values()) {
      viewer.entities.remove(state.entity);
    }
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

LayerRegistry.register(satellitesResourceLayer);

export default satellitesResourceLayer;
