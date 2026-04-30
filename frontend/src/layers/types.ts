// UC4 — Cesium Layer module contract (ADR-0001 LayerRegistry pattern).
//
// Each layer module in `frontend/src/layers/` exports a default `CesiumLayer`
// and registers itself in the singleton `LayerRegistry` as a top-level
// side effect. Click-to-Inspect convention: every picked Entity / Billboard
// carries `_wv*` properties so the LagebildView intel panel can render them
// without knowing the layer-specific data shape.

import type { Viewer } from 'cesium';

// ---------------------------------------------------------------------------
// Domain & pattern enums.
// ---------------------------------------------------------------------------

export type LayerDomain =
  | 'air'
  | 'maritime'
  | 'ew'
  | 'surface'
  | 'environment'
  | 'imagery'
  | 'sovereign-fusion';

// Backend Sovereign-Proxy pattern (see CLAUDE.md):
//   A — REST-Poll via ORDS handler
//   B — WebSocket Multiplexer (e.g. AIS)
//   C — WMS Tile Reverse Proxy
export type LayerPattern = 'A' | 'B' | 'C';

// 26ai Label Security numeric levels — see db/schema/01_users_and_security.sql.
//   100 = UNCLASSIFIED / OPEN
//   200 = RESTRICTED   / VS-NfD
//   300 = CONFIDENTIAL / VS-VERTRAULICH
//   400 = SECRET       / GEHEIM
export type ClassificationLabel = 100 | 200 | 300 | 400;

// ---------------------------------------------------------------------------
// Click-to-Inspect payload — attached to every pickable primitive as `_wv*`.
// ---------------------------------------------------------------------------

export interface ClickInspectMetaItem {
  key: string;
  val: string | number;
}

export interface ClickInspectMeta {
  type: string; // 'vessel' | 'aircraft' | 'satellite' | 'port' | 'jamming_zone' | …
  meta: ClickInspectMetaItem[];
  lat: number;
  lon: number;
  classification: ClassificationLabel;
  sources: string[]; // human-readable upstream provenance, e.g. ['aisstream.io via ais-multiplexer']
}

// `_wv*` properties as attached directly to a Cesium Entity. Modelled as a
// Partial bag so we can `Object.assign(entity, wvProps)` without fighting
// Cesium's own Entity type. Layer authors should use `WvProps` to build the
// object and then attach it.
export interface WvProps {
  _wvType: ClickInspectMeta['type'];
  _wvMeta: ClickInspectMetaItem[];
  _wvLat: number;
  _wvLon: number;
  _wvClassification: ClassificationLabel;
  _wvSources: string[];
}

// ---------------------------------------------------------------------------
// CesiumLayer contract.
// ---------------------------------------------------------------------------

export interface CesiumLayer {
  /** Lowercase kebab-case ASCII identifier. Unique across the registry. */
  name: string;
  /** Human-readable label for UI toggles (German). */
  label: string;
  /** Domain group used by the LagebildView sidebar. */
  domain: LayerDomain;
  /** Backend pattern. */
  pattern: LayerPattern;
  /** Default classification (numeric Label-Security level). */
  defaultClassification: ClassificationLabel;
  /** Attaches primitives, opens sockets, kicks off polling. */
  enable: (viewer: Viewer) => Promise<void>;
  /** MUST remove every primitive, listener, socket, timer it created. */
  disable: (viewer: Viewer) => void;
  /** Current count of live primitives — for badge UI. */
  getCount: () => number;
  /** Optional change subscription — returns an unsubscribe fn. */
  onCountChange?: (cb: (n: number) => void) => () => void;
}
