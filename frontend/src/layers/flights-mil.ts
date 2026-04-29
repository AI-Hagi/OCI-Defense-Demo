// UC4 — Flights (Military) layer (Pattern A: REST poll).
//
// Reads `/api/osint/flights/mil/current` — the same FastAPI service
// (`services/flights-proxy`) writes both civil and mil cache rows in
// one tick. An aircraft lands in the mil sub-layer iff the hybrid
// classifier matched it against `mil_aircraft_curated` (sovereign) or
// `mil_aircraft_mictronics` (community DB). The frontend never talks
// to adsb.lol or the upstream Mictronics repo directly.

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
import type {
  CesiumLayer,
  ClickInspectMetaItem,
  WvProps,
} from './types';

// ---------------------------------------------------------------------------
// Wire format from /api/osint/flights/mil/current.
// ---------------------------------------------------------------------------

// Same Oracle JSON read-back caveat as flights-civil: numeric fields may
// be JS numbers or numeric strings; `altitude_ft = "ground"` is a sentinel.
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
  (import.meta.env.VITE_FLIGHTS_MIL_API_URL as string | undefined) ??
    '/api/osint/flights/mil/current',
);

// Mil-aircraft icon — red plane silhouette, larger to stand out from civil.
const MIL_ICON_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="26" height="26">
  <path d="M12 2 L13.6 9 L22 11 L13.6 13 L13 22 L11 22 L10.4 13 L2 11 L10.4 9 Z"
        fill="#dc2626" stroke="#7f1d1d" stroke-width="1.4" stroke-linejoin="round"/>
</svg>`.trim();
const MIL_ICON_DATA_URI = `data:image/svg+xml;utf8,${encodeURIComponent(MIL_ICON_SVG)}`;

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
    try { cb(n); } catch { /* swallow listener errors */ }
  });
}

function asNum(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v !== '' && v !== 'ground') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function sourcesFor(p: FlightProperties): string[] {
  // Always include the upstream feed; append the matching DB so the
  // intel panel makes the provenance hop visible.
  const out = ['adsb.lol via ADS-B Exchange community feeders'];
  if (p.mil_source === 'curated') {
    out.push('Bundeswehr-Stammdaten (mil_aircraft_curated)');
  } else if (p.mil_source === 'mictronics') {
    out.push('Mictronics community DB (mil_aircraft_mictronics)');
  } else if (p.mil_source === 'dbflags') {
    out.push('adsb.lol dbFlags (mil-bit set)');
  }
  return out;
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
  if (p.mil_label) items.push({ key: 'Operator', val: p.mil_label });
  if (p.mil_source) items.push({ key: 'Mil Source', val: p.mil_source });
  return items;
}

function applyWvProps(entity: Entity, feat: FlightFeature): void {
  const props: WvProps = {
    _wvType: 'aircraft',
    _wvMeta: buildMeta(feat.properties),
    _wvLat: asNum(feat.geometry.coordinates[1]) ?? 0,
    _wvLon: asNum(feat.geometry.coordinates[0]) ?? 0,
    _wvClassification: 100,
    _wvSources: sourcesFor(feat.properties),
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
    id: `flights-mil:${hex}`,
    position,
    billboard: {
      image: MIL_ICON_DATA_URI,
      width: 26,
      height: 26,
      rotation: trackNum !== null ? -((trackNum * Math.PI) / 180) : 0,
      horizontalOrigin: HorizontalOrigin.CENTER,
      verticalOrigin: VerticalOrigin.CENTER,
      heightReference: HeightReference.NONE,
    },
    label: {
      text: label,
      font: 'bold 11px sans-serif',
      fillColor: Color.WHITE,
      outlineColor: Color.fromCssColorString('#7f1d1d'),
      outlineWidth: 2,
      showBackground: true,
      backgroundColor: new Color(0.5, 0, 0, 0.65),
      pixelOffset: new Cartesian3(0, -22, 0),
    },
  });
  applyWvProps(entity, feat);
  entitiesByHex.set(hex, entity);
}

async function fetchAndApply(viewer: Viewer): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(API_URL, { headers: { Accept: 'application/json' } });
  } catch {
    return;
  }
  if (!resp.ok) return;
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

export const flightsMilLayer: CesiumLayer = {
  name: 'flights-mil',
  label: 'Flüge: Mil',
  domain: 'air',
  pattern: 'A',
  defaultClassification: 100,

  async enable(viewer: Viewer): Promise<void> {
    activeViewer = viewer;
    await fetchAndApply(viewer);
    refreshTimer = setInterval(() => {
      if (activeViewer === viewer) void fetchAndApply(viewer);
    }, REFRESH_MS);
  },

  disable(viewer: Viewer): void {
    activeViewer = null;
    if (refreshTimer !== null) {
      clearInterval(refreshTimer);
      refreshTimer = null;
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

LayerRegistry.register(flightsMilLayer);

export default flightsMilLayer;
