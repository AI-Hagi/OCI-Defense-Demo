// UC4 — Maritime AIS layer (Pattern B: WebSocket multiplexer).
//
// Connects to the sovereign `ais-multiplexer` proxy at
// `VITE_MARITIME_WS_URL` (default `ws://localhost:8001/ws/maritime`),
// receives `ais_frame` JSON messages, renders one Cesium Billboard per
// MMSI with a ship icon, and exposes click metadata via the `_wv*`
// convention so LagebildView's intel panel can render it.
//
// Backend reality: the multiplexer holds the upstream aisstream.io
// connection (Vault-only API key) and fans out to N browsers. This
// frontend module never touches a public API.

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
  bboxQuery,
  getViewport,
  subscribe as subscribeViewport,
  type Viewport,
} from '../state/viewport';
import type {
  CesiumLayer,
  ClassificationLabel,
  ClickInspectMetaItem,
  WvProps,
} from './types';

// ---------------------------------------------------------------------------
// Wire format (from services/ais-multiplexer).
// ---------------------------------------------------------------------------

interface AisFrame {
  type: 'ais_frame';
  mmsi: string | number;
  lat: number;
  lon: number;
  heading_deg?: number | null;
  speed_kn?: number | null;
  vessel_name?: string | null;
  classification?: ClassificationLabel;
  ts?: string;
}

function isAisFrame(x: unknown): x is AisFrame {
  if (typeof x !== 'object' || x === null) return false;
  const f = x as Record<string, unknown>;
  return (
    f.type === 'ais_frame' &&
    (typeof f.mmsi === 'string' || typeof f.mmsi === 'number') &&
    typeof f.lat === 'number' &&
    typeof f.lon === 'number'
  );
}

// ---------------------------------------------------------------------------
// Module state — scoped to one enable/disable cycle.
// ---------------------------------------------------------------------------

// Resolve the multiplexer WebSocket URL.
//
// Accepted forms for `VITE_MARITIME_WS_URL`:
//   • absolute (`ws://`/`wss://`) — used verbatim. Useful for local dev
//     when frontend and backend run on different ports.
//   • origin-relative (`/ws/...`) — resolved against `window.location` at
//     runtime. Ship the same image in dev and prod; the Ingress (prod) or
//     Vite dev-server proxy (local) routes the path to the multiplexer.
//
// Default is origin-relative so the Docker image works in any environment
// without rebuilding. Local dev relies on the `/ws/` proxy in vite.config.ts.
function resolveWsUrl(raw: string): string {
  if (raw.startsWith('ws://') || raw.startsWith('wss://')) return raw;
  if (typeof window === 'undefined') return raw;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const path = raw.startsWith('/') ? raw : `/${raw}`;
  return `${proto}//${window.location.host}${path}`;
}

const WS_URL = resolveWsUrl(
  (import.meta.env.VITE_MARITIME_WS_URL as string | undefined) ?? '/ws/maritime',
);

const SHIP_ICON_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <path d="M12 2 L20 18 L12 16 L4 18 Z"
        fill="#1e88e5" stroke="#0d47a1" stroke-width="1.5" stroke-linejoin="round"/>
</svg>`.trim();
const SHIP_ICON_DATA_URI = `data:image/svg+xml;utf8,${encodeURIComponent(SHIP_ICON_SVG)}`;

const RECONNECT_BASE_MS = 2_000;
const RECONNECT_MAX_MS = 30_000;

// MMSI → Entity. Lets us update existing ships in-place instead of
// orphaning Entities every frame.
const entitiesByMmsi = new Map<string, Entity>();
let socket: WebSocket | null = null;
let reconnectTimer: number | null = null;
let reconnectAttempt = 0;
let countListeners: Set<(n: number) => void> = new Set();
let activeViewer: Viewer | null = null;

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

function emitCount(): void {
  const n = entitiesByMmsi.size;
  countListeners.forEach((cb) => {
    try {
      cb(n);
    } catch {
      // listener errors must not crash the WS handler
    }
  });
}

function buildMeta(frame: AisFrame): ClickInspectMetaItem[] {
  const meta: ClickInspectMetaItem[] = [
    { key: 'MMSI', val: String(frame.mmsi) },
    { key: 'Name', val: frame.vessel_name ?? 'Unknown' },
  ];
  if (typeof frame.heading_deg === 'number') {
    meta.push({ key: 'Heading', val: `${Math.round(frame.heading_deg)}°` });
  }
  if (typeof frame.speed_kn === 'number') {
    meta.push({ key: 'Speed', val: `${frame.speed_kn.toFixed(1)} kn` });
  }
  if (frame.ts) {
    meta.push({ key: 'Timestamp', val: frame.ts });
  }
  return meta;
}

function applyWvProps(entity: Entity, frame: AisFrame): void {
  const props: WvProps = {
    _wvType: 'vessel',
    _wvMeta: buildMeta(frame),
    _wvLat: frame.lat,
    _wvLon: frame.lon,
    _wvClassification: frame.classification ?? 100,
    _wvSources: ['aisstream.io via ais-multiplexer'],
  };
  // Attach as plain properties on the Entity. Cesium tolerates extra fields,
  // and the LagebildView click handler reads them back via a typed cast.
  Object.assign(entity, props);
}

function upsertVessel(viewer: Viewer, frame: AisFrame): void {
  const mmsi = String(frame.mmsi);
  const position = Cartesian3.fromDegrees(frame.lon, frame.lat);
  const label = frame.vessel_name ?? mmsi;

  const existing = entitiesByMmsi.get(mmsi);
  if (existing) {
    existing.position = new ConstantPositionProperty(position);
    if (existing.label) {
      existing.label.text = new ConstantProperty(label);
    }
    applyWvProps(existing, frame);
  } else {
    const entity = viewer.entities.add({
      id: `maritime:${mmsi}`,
      position,
      billboard: {
        image: SHIP_ICON_DATA_URI,
        width: 24,
        height: 24,
        horizontalOrigin: HorizontalOrigin.CENTER,
        verticalOrigin: VerticalOrigin.CENTER,
        heightReference: HeightReference.CLAMP_TO_GROUND,
      },
      label: {
        text: label,
        font: '12px sans-serif',
        fillColor: Color.WHITE,
        outlineColor: Color.BLACK,
        outlineWidth: 2,
        showBackground: true,
        backgroundColor: new Color(0, 0, 0, 0.6),
        pixelOffset: new Cartesian3(0, -22, 0),
      },
    });
    applyWvProps(entity, frame);
    entitiesByMmsi.set(mmsi, entity);
  }
}

// ---------------------------------------------------------------------------
// WebSocket lifecycle.
// ---------------------------------------------------------------------------

function clearReconnectTimer(): void {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function scheduleReconnect(viewer: Viewer): void {
  clearReconnectTimer();
  const delay = Math.min(
    RECONNECT_MAX_MS,
    RECONNECT_BASE_MS * 2 ** reconnectAttempt,
  );
  reconnectAttempt += 1;
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    if (activeViewer === viewer) connect(viewer);
  }, delay);
}

function buildWsUrl(viewport?: Viewport): string {
  if (!viewport) return WS_URL;
  const sep = WS_URL.includes('?') ? '&' : '?';
  return `${WS_URL}${sep}${bboxQuery(viewport)}`;
}

function connect(viewer: Viewer, viewport?: Viewport): void {
  try {
    socket = new WebSocket(buildWsUrl(viewport));
  } catch (err) {
    console.warn('[maritime] WS construction failed:', err);
    scheduleReconnect(viewer);
    return;
  }

  socket.onopen = () => {
    reconnectAttempt = 0;
  };

  socket.onmessage = (ev) => {
    try {
      const parsed: unknown = JSON.parse(ev.data as string);
      if (!isAisFrame(parsed)) return;
      upsertVessel(viewer, parsed);
      viewer.scene.requestRender();
      emitCount();
    } catch (err) {
      console.warn('[maritime] frame parse failed:', err);
    }
  };

  socket.onerror = () => {
    // onclose will run after onerror; don't double-schedule reconnect here.
  };

  socket.onclose = () => {
    socket = null;
    if (activeViewer === viewer) scheduleReconnect(viewer);
  };
}

function reconnectForViewport(viewer: Viewer, viewport: Viewport): void {
  // The multiplexer subscribes upstream globally and applies a per-client
  // bbox filter (see services/ais-multiplexer/app/multiplexer.py). To
  // refresh that filter we have to re-handshake the WebSocket with the
  // new bbox query params. Drop entities first so stale vessels outside
  // the new bbox don't linger.
  if (socket) {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    try { socket.close(); } catch { /* already closing */ }
    socket = null;
  }
  entitiesByMmsi.forEach((entity) => viewer.entities.remove(entity));
  entitiesByMmsi.clear();
  viewer.scene.requestRender();
  emitCount();
  reconnectAttempt = 0;
  connect(viewer, viewport);
}

// ---------------------------------------------------------------------------
// CesiumLayer export — registered with LayerRegistry as a side effect.
// ---------------------------------------------------------------------------

let viewportUnsub: (() => void) | null = null;

export const maritimeLayer: CesiumLayer = {
  name: 'maritime',
  label: 'Maritime AIS',
  domain: 'maritime',
  pattern: 'B',
  defaultClassification: 100,

  async enable(viewer) {
    activeViewer = viewer;
    if (!socket) connect(viewer, getViewport());
    viewportUnsub = subscribeViewport((v) => {
      if (activeViewer === viewer) reconnectForViewport(viewer, v);
    });
  },

  disable(viewer) {
    activeViewer = null;
    clearReconnectTimer();
    reconnectAttempt = 0;
    if (viewportUnsub) {
      viewportUnsub();
      viewportUnsub = null;
    }
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      try {
        socket.close();
      } catch {
        // ignore — socket may already be closing
      }
      socket = null;
    }
    entitiesByMmsi.forEach((entity) => viewer.entities.remove(entity));
    entitiesByMmsi.clear();
    viewer.scene.requestRender();
    emitCount();
  },

  getCount() {
    return entitiesByMmsi.size;
  },

  onCountChange(cb) {
    countListeners.add(cb);
    return () => {
      countListeners.delete(cb);
    };
  },
};

// Top-level side effect: register on first import.
LayerRegistry.register(maritimeLayer);

export default maritimeLayer;
