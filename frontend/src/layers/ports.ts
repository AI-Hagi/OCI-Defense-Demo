// UC4 — Ports layer (Pattern A: REST poll, hybrid OSM + curated classifier).
//
// Single layer with five port types selectable via a frontend filter
// (commercial / military / fishing / marina / mixed). Backend
// (`services/ports-proxy`) does a one-shot Overpass + curated NN
// classification and persists the result in osint_cache(layer='ports').
// Browser fetches once on enable; ports are static so no refresh loop.
//
// Click-to-Inspect: each port Entity carries `_wv*` so the LagebildView
// intel panel renders name, country, port_type, source ('curated' /
// 'osm'), and curated-only flags (NATO member, Bundeswehr facility).

import {
  Cartesian2,
  Cartesian3,
  Color,
  ConstantPositionProperty,
  ConstantProperty,
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
// Wire format from /api/osint/ports/current.
// ---------------------------------------------------------------------------

export type PortType = 'commercial' | 'military' | 'fishing' | 'marina' | 'mixed';

interface PortProperties {
  osm_id: string;
  osm_type: string;
  name: string;
  country: string | null;
  port_type: PortType;
  source: 'curated' | 'osm';
  curated_id: number | null;
  nato_member: boolean;
  bundeswehr_facility: boolean;
  osm_tags: Record<string, string>;
}

interface PortFeature {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number | string, number | string] };
  properties: PortProperties;
}

interface PortFeatureCollection {
  type: 'FeatureCollection';
  features: PortFeature[];
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
  (import.meta.env.VITE_PORTS_API_URL as string | undefined) ??
    '/api/osint/ports/current',
);

// Numeric coercion — same Oracle JSON read-back caveat as the other layers.
function asNum(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Icons — one SVG per port_type.
// ---------------------------------------------------------------------------

function anchorSvg(fill: string, stroke: string): string {
  // Anchor silhouette — used for commercial / military / mixed (color differs).
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">
  <circle cx="12" cy="6" r="2" fill="none" stroke="${stroke}" stroke-width="1.4"/>
  <path d="M12 8 L12 19 M7 19 Q12 22 17 19 M5 14 L7 14 M19 14 L17 14"
        stroke="${stroke}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  <path d="M9 19 L12 22 L15 19 Z" fill="${fill}" stroke="${stroke}" stroke-width="0.8"/>
</svg>`.trim();
}

function fishHookSvg(): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">
  <path d="M14 4 V13 A4 4 0 0 1 6 13" stroke="#15803d" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  <circle cx="14" cy="4" r="1.2" fill="#15803d"/>
  <path d="M6 13 L4 11 M6 13 L8 11" stroke="#15803d" stroke-width="1.4" stroke-linecap="round"/>
</svg>`.trim();
}

function sailboatSvg(): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">
  <path d="M12 3 L12 16 L4 16 Z" fill="#0d9488" stroke="#134e4a" stroke-width="1"/>
  <path d="M2 18 Q12 22 22 18" stroke="#134e4a" stroke-width="1.4" fill="none"/>
</svg>`.trim();
}

const ICON_BY_TYPE: Record<PortType, string> = {
  commercial: `data:image/svg+xml;utf8,${encodeURIComponent(anchorSvg('#1d4ed8', '#1e3a8a'))}`,
  military:   `data:image/svg+xml;utf8,${encodeURIComponent(anchorSvg('#dc2626', '#7f1d1d'))}`,
  fishing:    `data:image/svg+xml;utf8,${encodeURIComponent(fishHookSvg())}`,
  marina:     `data:image/svg+xml;utf8,${encodeURIComponent(sailboatSvg())}`,
  mixed:      `data:image/svg+xml;utf8,${encodeURIComponent(anchorSvg('#6b7280', '#1f2937'))}`,
};

export function iconForPortType(t: PortType): string {
  return ICON_BY_TYPE[t] ?? ICON_BY_TYPE.mixed;
}

// ---------------------------------------------------------------------------
// Filter state — Set of enabled port types. UI mutates via setFilter().
// ---------------------------------------------------------------------------

export const ALL_PORT_TYPES: ReadonlyArray<PortType> = [
  'commercial', 'military', 'fishing', 'marina', 'mixed',
];

const DEFAULT_FILTER: ReadonlySet<PortType> = new Set(ALL_PORT_TYPES);
let activeFilter: Set<PortType> = new Set(DEFAULT_FILTER);
const filterListeners: Set<(f: ReadonlySet<PortType>) => void> = new Set();

export function getFilter(): ReadonlySet<PortType> {
  return activeFilter;
}

export function setFilter(next: Iterable<PortType>): void {
  activeFilter = new Set(next);
  // Re-apply visibility against the cached features.
  if (activeViewer && lastFeatures.length > 0) {
    rebuildEntities(activeViewer);
  }
  filterListeners.forEach((cb) => {
    try { cb(activeFilter); } catch { /* swallow */ }
  });
}

export function onFilterChange(cb: (f: ReadonlySet<PortType>) => void): () => void {
  filterListeners.add(cb);
  return () => { filterListeners.delete(cb); };
}

// ---------------------------------------------------------------------------
// Module state — scoped to one enable/disable cycle.
// ---------------------------------------------------------------------------

const entitiesByOsmId: Map<string, Entity> = new Map();
let lastFeatures: PortFeature[] = [];
let activeViewer: Viewer | null = null;
const countListeners: Set<(n: number) => void> = new Set();

function emitCount(): void {
  const n = entitiesByOsmId.size;
  countListeners.forEach((cb) => {
    try { cb(n); } catch { /* swallow */ }
  });
}

function buildMeta(p: PortProperties): ClickInspectMetaItem[] {
  const items: ClickInspectMetaItem[] = [
    { key: 'Name', val: p.name || `OSM ${p.osm_id}` },
    { key: 'Typ', val: p.port_type },
    { key: 'Quelle', val: p.source === 'curated' ? 'Bundeswehr/NATO Stammdaten' : 'OpenStreetMap' },
  ];
  if (p.country) items.push({ key: 'Land', val: p.country });
  if (p.osm_id) items.push({ key: 'OSM-ID', val: `${p.osm_type}/${p.osm_id}` });
  if (p.source === 'curated') {
    items.push({ key: 'NATO-Mitglied', val: p.nato_member ? 'ja' : 'nein' });
    items.push({ key: 'Bundeswehr-Anlage', val: p.bundeswehr_facility ? 'ja' : 'nein' });
  }
  return items;
}

function applyWvProps(entity: Entity, feat: PortFeature): void {
  const lon = asNum(feat.geometry.coordinates[0]) ?? 0;
  const lat = asNum(feat.geometry.coordinates[1]) ?? 0;
  const sources = feat.properties.source === 'curated'
    ? ['Bundeswehr-Stammdaten (ports_curated)']
    : ['OpenStreetMap Overpass API'];
  const props: WvProps = {
    _wvType: 'port',
    _wvMeta: buildMeta(feat.properties),
    _wvLat: lat,
    _wvLon: lon,
    _wvClassification: 100,
    _wvSources: sources,
  };
  Object.assign(entity, props);
}

function upsertPort(viewer: Viewer, feat: PortFeature): void {
  const osmId = feat.properties.osm_id || `${feat.properties.osm_type}-${Math.random()}`;
  const lon = asNum(feat.geometry.coordinates[0]);
  const lat = asNum(feat.geometry.coordinates[1]);
  if (lon === null || lat === null) return;
  const position = Cartesian3.fromDegrees(lon, lat);
  const label = feat.properties.name || `OSM ${osmId}`;
  const portType = feat.properties.port_type ?? 'mixed';

  const existing = entitiesByOsmId.get(osmId);
  if (existing) {
    existing.position = new ConstantPositionProperty(position);
    if (existing.label) {
      existing.label.text = new ConstantProperty(label);
    }
    applyWvProps(existing, feat);
    return;
  }

  const entity = viewer.entities.add({
    id: `ports:${osmId}`,
    position,
    billboard: {
      image: iconForPortType(portType),
      width: 22,
      height: 22,
      horizontalOrigin: HorizontalOrigin.CENTER,
      verticalOrigin: VerticalOrigin.CENTER,
      heightReference: HeightReference.CLAMP_TO_GROUND,
    },
    label: {
      text: label,
      font: '11px sans-serif',
      fillColor: Color.WHITE,
      outlineColor: Color.BLACK,
      outlineWidth: 2,
      showBackground: true,
      backgroundColor: new Color(0, 0, 0, 0.55),
      pixelOffset: new Cartesian2(0, -18),
    },
  });
  applyWvProps(entity, feat);
  entitiesByOsmId.set(osmId, entity);
}

function rebuildEntities(viewer: Viewer): void {
  // Drop everything that no longer matches the filter, add back any
  // that came back into scope. Simple O(N) — port count is small enough.
  const wanted = new Set<string>();
  for (const feat of lastFeatures) {
    const t = feat.properties.port_type ?? 'mixed';
    if (!activeFilter.has(t)) continue;
    const id = feat.properties.osm_id;
    if (!id) continue;
    wanted.add(id);
    upsertPort(viewer, feat);
  }
  for (const [id, ent] of Array.from(entitiesByOsmId.entries())) {
    if (!wanted.has(id)) {
      viewer.entities.remove(ent);
      entitiesByOsmId.delete(id);
    }
  }
  viewer.scene.requestRender();
  emitCount();
}

async function fetchAndApply(viewer: Viewer): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(API_URL, { headers: { Accept: 'application/json' } });
  } catch {
    return;
  }
  if (!resp.ok) return;
  let payload: PortFeatureCollection;
  try {
    payload = (await resp.json()) as PortFeatureCollection;
  } catch {
    return;
  }
  if (payload.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
    return;
  }
  lastFeatures = payload.features;
  rebuildEntities(viewer);
}

// ---------------------------------------------------------------------------
// CesiumLayer contract.
// ---------------------------------------------------------------------------

export const portsLayer: CesiumLayer = {
  name: 'ports',
  label: 'Häfen',
  domain: 'maritime',
  pattern: 'A',
  defaultClassification: 100,

  async enable(viewer: Viewer): Promise<void> {
    activeViewer = viewer;
    await fetchAndApply(viewer);
    // No refresh interval — ports are static. Operator can hit
    // /api/osint/ports/refresh server-side and re-enable the layer
    // (or refresh the page) to reload.
  },

  disable(viewer: Viewer): void {
    activeViewer = null;
    for (const ent of entitiesByOsmId.values()) {
      viewer.entities.remove(ent);
    }
    entitiesByOsmId.clear();
    lastFeatures = [];
    viewer.scene.requestRender();
    emitCount();
  },

  getCount(): number {
    return entitiesByOsmId.size;
  },

  onCountChange(cb) {
    countListeners.add(cb);
    return () => { countListeners.delete(cb); };
  },
};

LayerRegistry.register(portsLayer);

export default portsLayer;
