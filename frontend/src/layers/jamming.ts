// UC4 — GPS Jamming layer (Pattern A: REST poll with H3 hex polygons).
//
// The Sovereign Proxy `services/jamming-poller` pulls the daily CSV from
// gpsjam.org, transforms H3 cells into GeoJSON polygons, classifies each
// cell as green/amber/red by the low-NACp ratio, and persists the result
// in `osint_cache`. This frontend module does NOT talk to gpsjam.org —
// it consumes `/api/osint/jamming/current` (GeoJSON FeatureCollection)
// from the same-origin reverse proxy.

import {
  Cartesian3,
  Color,
  PolygonHierarchy,
  type Entity,
  type Viewer,
} from 'cesium';
import { LayerRegistry } from './registry';
import {
  getViewport,
  subscribe as subscribeViewport,
  viewportQuery,
  type Viewport,
} from '../state/viewport';
import type {
  CesiumLayer,
  ClassificationLabel,
  ClickInspectMetaItem,
  WvProps,
} from './types';

// ---------------------------------------------------------------------------
// Wire format from /api/osint/jamming/current.
// ---------------------------------------------------------------------------

// Numeric fields may arrive as JS numbers OR numeric strings — Oracle's
// JSON column read-back via oracledb thin mode renders numbers as strings.
type Num = number | string | null;

interface JammingFeature {
  type: 'Feature';
  geometry: { type: 'Polygon'; coordinates: number[][][] };
  properties: {
    h3_index: string;
    aircraft_total: Num;
    aircraft_low_nacp: Num;
    low_nacp_ratio: Num;
    classification_color: 'green' | 'amber' | 'red';
    centroid_lat: Num;
    centroid_lon: Num;
  };
}

interface JammingFeatureCollection {
  type: 'FeatureCollection';
  features: JammingFeature[];
  fetched_at?: string;
  source?: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// URL helper — origin-relative by default (works behind frontend nginx
// reverse proxy in prod and behind the Vite dev-server proxy in local dev).
// ---------------------------------------------------------------------------

function resolveUrl(raw: string): string {
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw;
  if (typeof window === 'undefined') return raw;
  const proto = window.location.protocol === 'https:' ? 'https:' : 'http:';
  const path = raw.startsWith('/') ? raw : `/${raw}`;
  return `${proto}//${window.location.host}${path}`;
}

const API_URL = resolveUrl(
  (import.meta.env.VITE_JAMMING_API_URL as string | undefined) ??
    '/api/osint/jamming/current',
);

// ---------------------------------------------------------------------------
// Module state — scoped to one enable/disable cycle.
// ---------------------------------------------------------------------------

let entitiesByHex: Map<string, Entity> = new Map();
let refreshTimer: ReturnType<typeof setInterval> | null = null;
const REFRESH_MS = 6 * 60 * 60 * 1000; // 6 h, matches server-side schedule.

function colorFor(cls: 'green' | 'amber' | 'red'): Color {
  switch (cls) {
    case 'red':
      return Color.fromCssColorString('#dc2626').withAlpha(0.45);
    case 'amber':
      return Color.fromCssColorString('#d97706').withAlpha(0.4);
    case 'green':
    default:
      return Color.fromCssColorString('#16a34a').withAlpha(0.25);
  }
}

function asNum(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

// Operator-facing German label + traffic-light meaning for the
// per-cell low-NACp ratio. Thresholds match the backend
// classifier in services/jamming-poller (green ≤2%, amber ≤8%,
// red >8%) — keep these two in sync.
function classificationLabel(c: 'green' | 'amber' | 'red'): string {
  switch (c) {
    case 'red':   return 'Hoch (>8% Low-NACp)';
    case 'amber': return 'Mittel (2–8% Low-NACp)';
    case 'green':
    default:      return 'Niedrig (≤2% Low-NACp)';
  }
}

function buildMeta(props: JammingFeature['properties']): ClickInspectMetaItem[] {
  const items: ClickInspectMetaItem[] = [
    { key: 'H3-Zelle', val: props.h3_index },
  ];
  const total = asNum(props.aircraft_total);
  if (total !== null) items.push({ key: 'Flugzeuge gesamt', val: total });
  const lowN = asNum(props.aircraft_low_nacp);
  if (lowN !== null) items.push({ key: 'Flugzeuge mit Low-NACp', val: lowN });
  const ratio = asNum(props.low_nacp_ratio);
  if (ratio !== null) {
    items.push({ key: 'Low-NACp Anteil', val: `${(ratio * 100).toFixed(1)} %` });
  }
  items.push({ key: 'Stör-Stufe', val: classificationLabel(props.classification_color) });
  items.push({ key: 'Farbe (Layer)', val: props.classification_color });
  // Inline legend so the operator never has to recall the ratio thresholds.
  items.push({ key: 'Legende', val: 'grün ≤2% · gelb 2–8% · rot >8%' });
  // What the metric measures, in one line. NACp = Navigation Accuracy
  // Category for Position; ADS-B emitters drop their NACp below 8 when
  // GPS solutions degrade, which is the signature we use as a proxy for
  // GPS-Jamming oder Spoofing in der Zelle.
  items.push({ key: 'Indikator', val: 'NACp <8 = GPS-Position unsicher (Stör-Indiz)' });
  const lat = asNum(props.centroid_lat);
  const lon = asNum(props.centroid_lon);
  if (lat !== null && lon !== null) {
    items.push({ key: 'Zentroid', val: `${lat.toFixed(3)}, ${lon.toFixed(3)}` });
  }
  return items;
}

function applyWvProps(entity: Entity, feat: JammingFeature, classification: ClassificationLabel): void {
  const props: WvProps = {
    _wvType: 'jamming_zone',
    _wvMeta: buildMeta(feat.properties),
    _wvLat: asNum(feat.properties.centroid_lat) ?? 0,
    _wvLon: asNum(feat.properties.centroid_lon) ?? 0,
    _wvClassification: classification,
    _wvSources: ['adsb.lol via ADS-B Exchange community feeders'],
  };
  Object.assign(entity, props);
}

function ringToCartesian(ring: number[][]): Cartesian3[] {
  // GeoJSON ring is [[lon, lat], ...]. Drop the closing duplicate vertex —
  // Cesium PolygonHierarchy doesn't want it.
  const open = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0]
    ? ring.slice(0, -1)
    : ring;
  return open.map(([lon, lat]) => Cartesian3.fromDegrees(lon, lat));
}

function upsertHex(viewer: Viewer, feat: JammingFeature): void {
  const hex = feat.properties.h3_index;
  const positions = ringToCartesian(feat.geometry.coordinates[0] ?? []);
  if (positions.length < 3) return;

  const existing = entitiesByHex.get(hex);
  if (existing) {
    if (existing.polygon) {
      existing.polygon.hierarchy = new PolygonHierarchy(positions) as never;
      existing.polygon.material = colorFor(feat.properties.classification_color) as never;
    }
    applyWvProps(existing, feat, 100);
    return;
  }

  const entity = viewer.entities.add({
    id: `jamming:${hex}`,
    polygon: {
      hierarchy: new PolygonHierarchy(positions),
      material: colorFor(feat.properties.classification_color),
      outline: true,
      outlineColor: Color.WHITE.withAlpha(0.4),
    },
  });
  applyWvProps(entity, feat, 100);
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
    // Network error — keep previous state, try again next tick.
    return;
  }
  if (!resp.ok) {
    // 503 cold-cache or 5xx — preserve current state.
    return;
  }
  let payload: JammingFeatureCollection;
  try {
    payload = (await resp.json()) as JammingFeatureCollection;
  } catch {
    return;
  }
  if (payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    return;
  }

  // Upsert every received feature.
  const seenHex = new Set<string>();
  for (const feat of payload.features) {
    if (!feat?.properties?.h3_index) continue;
    seenHex.add(feat.properties.h3_index);
    upsertHex(viewer, feat);
  }
  // Drop entities that disappeared from the latest payload.
  for (const [hex, ent] of Array.from(entitiesByHex.entries())) {
    if (!seenHex.has(hex)) {
      viewer.entities.remove(ent);
      entitiesByHex.delete(hex);
    }
  }
  viewer.scene.requestRender();
}

// ---------------------------------------------------------------------------
// CesiumLayer contract.
// ---------------------------------------------------------------------------

let viewportUnsub: (() => void) | null = null;

const jammingLayer: CesiumLayer = {
  name: 'jamming',
  label: 'GPS Jamming',
  domain: 'ew',
  pattern: 'A',
  defaultClassification: 100,

  async enable(viewer: Viewer): Promise<void> {
    await fetchAndApply(viewer, getViewport());
    refreshTimer = setInterval(() => {
      void fetchAndApply(viewer, getViewport());
    }, REFRESH_MS);
    viewportUnsub = subscribeViewport((v) => {
      void fetchAndApply(viewer, v);
    });
  },

  disable(viewer: Viewer): void {
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
  },

  getCount(): number {
    return entitiesByHex.size;
  },
};

LayerRegistry.register(jammingLayer);

export default jammingLayer;
