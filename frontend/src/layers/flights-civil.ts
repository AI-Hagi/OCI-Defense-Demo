// UC4 — Flights (Civil) layer (Pattern A: REST poll).
//
// The Sovereign Proxy `services/flights-proxy` polls adsb.lol every
// REFRESH_MINUTES, runs each aircraft through the hybrid classifier
// (curated → Mictronics → civil) and persists two cache rows in
// `osint_cache` (layer='flights-civil' and layer='flights-mil').
//
// This module reads `/api/osint/flights/civil/current` (GeoJSON
// FeatureCollection of Point Features). Civil aircraft only; the mil
// sub-layer lives in `flights-mil.ts`. Frontend never talks to
// adsb.lol directly.

import {
  Cartesian3,
  Color,
  ConstantProperty,
  ConstantPositionProperty,
  HeightReference,
  HorizontalOrigin,
  VerticalOrigin,
  type Entity,
  type Viewer,
} from 'cesium';
import { LayerRegistry } from './registry';
import {
  bboxQuery as _unusedBboxQuery,  // eslint-disable-line @typescript-eslint/no-unused-vars
  getViewport,
  subscribe as subscribeViewport,
  viewportQuery,
  type Viewport,
} from '../state/viewport';
import type {
  CesiumLayer,
  ClickInspectMetaItem,
  WvProps,
} from './types';

// ---------------------------------------------------------------------------
// Wire format from /api/osint/flights/civil/current.
// ---------------------------------------------------------------------------

// Numeric fields may arrive as JS numbers OR numeric strings — Oracle's
// JSON column read-back via oracledb thin mode renders numbers as strings.
// `altitude_ft` may also be the literal "ground" sentinel for grounded
// aircraft. asNum() coerces all valid forms to a number.
type Num = number | string | null;

interface FlightProperties {
  hex24: string;
  callsign: string | null;
  icao_type: string | null;
  registration: string | null;
  altitude_ft: Num | 'ground';
  ground_speed_kn: Num;
  track_deg: Num;
  squawk: string | null;
  nac_p: Num;
  mil_source: 'curated' | 'mictronics' | 'dbflags' | null;
  mil_label: string | null;
}

interface FlightFeature {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number | string, number | string] };
  properties: FlightProperties;
}

interface FlightFeatureCollection {
  type: 'FeatureCollection';
  features: FlightFeature[];
  fetched_at?: string;
  source?: string;
  error?: string;
}

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
  (import.meta.env.VITE_FLIGHTS_CIVIL_API_URL as string | undefined) ??
    '/api/osint/flights/civil/current',
);

// Civil-aircraft icon — neutral blue plane silhouette, top-down view.
const CIVIL_ICON_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">
  <path d="M12 2 L13.4 10 L22 12 L13.4 14 L13 21 L11 21 L10.6 14 L2 12 L10.6 10 Z"
        fill="#2563eb" stroke="#0b3d91" stroke-width="1.2" stroke-linejoin="round"/>
</svg>`.trim();
const CIVIL_ICON_DATA_URI = `data:image/svg+xml;utf8,${encodeURIComponent(CIVIL_ICON_SVG)}`;

const REFRESH_MS = 30_000; // 30 s — backend cache cushions.

// ---------------------------------------------------------------------------
// Module state — scoped to one enable/disable cycle.
// ---------------------------------------------------------------------------

const entitiesByHex: Map<string, Entity> = new Map();
let refreshTimer: ReturnType<typeof setInterval> | null = null;
let activeViewer: Viewer | null = null;
const countListeners: Set<(n: number) => void> = new Set();

function emitCount(): void {
  const n = entitiesByHex.size;
  countListeners.forEach((cb) => {
    try { cb(n); } catch { /* listener errors must not crash polling */ }
  });
}

// Oracle's JSON column read-back via oracledb thin mode returns
// numeric values as strings ("23025"). Coerce both forms here so
// the intel panel renders the field whether the upstream is a JS
// number or a numeric string. `altitude_ft = "ground"` (sentinel
// for grounded aircraft) is preserved verbatim.
function asNum(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v !== '' && v !== 'ground') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function buildMeta(p: FlightProperties): ClickInspectMetaItem[] {
  const items: ClickInspectMetaItem[] = [
    { key: 'Hex (ICAO24)', val: p.hex24 || 'unknown' },
    { key: 'Callsign', val: p.callsign ?? '—' },
  ];
  if (p.registration) items.push({ key: 'Registration', val: p.registration });
  if (p.icao_type) items.push({ key: 'Type', val: p.icao_type });
  const alt = asNum(p.altitude_ft);
  if (alt !== null) items.push({ key: 'Altitude', val: `${alt} ft` });
  else if (p.altitude_ft === 'ground') items.push({ key: 'Altitude', val: 'ground' });
  const gs = asNum(p.ground_speed_kn);
  if (gs !== null) items.push({ key: 'Speed', val: `${Math.round(gs)} kn` });
  const tr = asNum(p.track_deg);
  if (tr !== null) items.push({ key: 'Track', val: `${Math.round(tr)}°` });
  if (p.squawk) items.push({ key: 'Squawk', val: p.squawk });
  const nacp = asNum(p.nac_p);
  if (nacp !== null) items.push({ key: 'NACp', val: nacp });
  return items;
}

function applyWvProps(entity: Entity, feat: FlightFeature): void {
  const props: WvProps = {
    _wvType: 'aircraft',
    _wvMeta: buildMeta(feat.properties),
    _wvLat: asNum(feat.geometry.coordinates[1]) ?? 0,
    _wvLon: asNum(feat.geometry.coordinates[0]) ?? 0,
    _wvClassification: 100,
    _wvSources: ['adsb.lol via ADS-B Exchange community feeders'],
  };
  Object.assign(entity, props);
}

function upsertAircraft(viewer: Viewer, feat: FlightFeature): void {
  const hex = feat.properties.hex24;
  if (!hex) return;
  const lon = asNum(feat.geometry.coordinates[0]);
  const lat = asNum(feat.geometry.coordinates[1]);
  if (lon === null || lat === null) return;
  const position = Cartesian3.fromDegrees(lon, lat);
  const label = feat.properties.callsign || feat.properties.registration || hex;
  const trackNum = asNum(feat.properties.track_deg);

  const existing = entitiesByHex.get(hex);
  if (existing) {
    existing.position = new ConstantPositionProperty(position);
    if (existing.label) {
      existing.label.text = new ConstantProperty(label);
    }
    if (existing.billboard && trackNum !== null) {
      existing.billboard.rotation = new ConstantProperty(
        -((trackNum * Math.PI) / 180),
      );
    }
    applyWvProps(existing, feat);
    return;
  }

  const entity = viewer.entities.add({
    id: `flights-civil:${hex}`,
    position,
    billboard: {
      image: CIVIL_ICON_DATA_URI,
      width: 22,
      height: 22,
      rotation: trackNum !== null ? -((trackNum * Math.PI) / 180) : 0,
      horizontalOrigin: HorizontalOrigin.CENTER,
      verticalOrigin: VerticalOrigin.CENTER,
      heightReference: HeightReference.NONE,
    },
    label: {
      text: label,
      font: '11px sans-serif',
      fillColor: Color.WHITE,
      outlineColor: Color.BLACK,
      outlineWidth: 2,
      showBackground: true,
      backgroundColor: new Color(0, 0, 0, 0.55),
      pixelOffset: new Cartesian3(0, -18, 0),
    },
  });
  applyWvProps(entity, feat);
  entitiesByHex.set(hex, entity);
}

function buildUrl(viewport?: Viewport): string {
  if (!viewport) return API_URL;
  const sep = API_URL.includes('?') ? '&' : '?';
  return `${API_URL}${sep}${viewportQuery(viewport)}`;
}

async function fetchAndApply(viewer: Viewer, viewport?: Viewport): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(buildUrl(viewport), { headers: { Accept: 'application/json' } });
  } catch {
    return; // network blip — keep last good frame
  }
  if (!resp.ok) return; // 503 cold-cache or 5xx — preserve current state
  let payload: FlightFeatureCollection;
  try {
    payload = (await resp.json()) as FlightFeatureCollection;
  } catch {
    return;
  }
  if (payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    return;
  }

  const seenHex = new Set<string>();
  for (const feat of payload.features) {
    const hex = feat?.properties?.hex24;
    if (!hex) continue;
    seenHex.add(hex);
    upsertAircraft(viewer, feat);
  }
  for (const [hex, ent] of Array.from(entitiesByHex.entries())) {
    if (!seenHex.has(hex)) {
      viewer.entities.remove(ent);
      entitiesByHex.delete(hex);
    }
  }
  viewer.scene.requestRender();
  emitCount();
}

// ---------------------------------------------------------------------------
// CesiumLayer contract.
// ---------------------------------------------------------------------------

let viewportUnsub: (() => void) | null = null;

export const flightsCivilLayer: CesiumLayer = {
  name: 'flights-civil',
  label: 'Flüge: Civil',
  domain: 'air',
  pattern: 'A',
  defaultClassification: 100,

  async enable(viewer: Viewer): Promise<void> {
    activeViewer = viewer;
    // Initial fetch uses whatever viewport the camera is sitting on.
    await fetchAndApply(viewer, getViewport());
    // Periodic refresh — picks up new aircraft positions even when the
    // operator isn't moving the camera.
    refreshTimer = setInterval(() => {
      if (activeViewer === viewer) void fetchAndApply(viewer, getViewport());
    }, REFRESH_MS);
    // Camera-driven refresh — refetch immediately after a pan/zoom
    // settles. The viewport singleton debounces moveEnd internally.
    viewportUnsub = subscribeViewport((v) => {
      if (activeViewer === viewer) void fetchAndApply(viewer, v);
    });
  },

  disable(viewer: Viewer): void {
    activeViewer = null;
    if (refreshTimer !== null) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
    if (viewportUnsub) {
      viewportUnsub();
      viewportUnsub = null;
    }
    for (const ent of entitiesByHex.values()) {
      viewer.entities.remove(ent);
    }
    entitiesByHex.clear();
    viewer.scene.requestRender();
    emitCount();
  },

  getCount(): number {
    return entitiesByHex.size;
  },

  onCountChange(cb) {
    countListeners.add(cb);
    return () => { countListeners.delete(cb); };
  },
};

LayerRegistry.register(flightsCivilLayer);

export default flightsCivilLayer;
