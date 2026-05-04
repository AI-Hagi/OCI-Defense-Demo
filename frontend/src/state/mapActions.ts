/**
 * mapActions — typed pub/sub for chat-driven map control.
 *
 * Producers: ChatPanel, when the uc4-chat WebSocket emits a `map_action`
 * event. Consumers: LagebildView (and future Cesium hosts) subscribe and
 * execute the action locally. The store does not own the Cesium viewer —
 * it just relays validated intents.
 *
 * Action shapes mirror the backend (services/uc4-chat/app/tools/map_action.py).
 * Anything else is dropped at the type boundary.
 */
export interface FlytoAction {
  action: 'flyto';
  lat: number;
  lon: number;
  zoom_km?: number;
}
export interface EnableLayerAction {
  action: 'enable_layer';
  layer: string;
}
export interface DisableLayerAction {
  action: 'disable_layer';
  layer: string;
}
export interface HighlightEntitiesAction {
  action: 'highlight_entities';
  entity_ids: string[];
}

export type MapAction =
  | FlytoAction
  | EnableLayerAction
  | DisableLayerAction
  | HighlightEntitiesAction;

type Listener = (action: MapAction) => void;

const listeners = new Set<Listener>();

export function dispatchMapAction(action: MapAction): void {
  listeners.forEach((cb) => {
    try {
      cb(action);
    } catch {
      // listener errors must not block other subscribers
    }
  });
}

export function subscribeMapAction(cb: Listener): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/**
 * Validate an event payload coming over the wire and return a typed
 * MapAction, or null if it doesn't match a known shape. Used by ChatPanel
 * before publishing — defence-in-depth against backend regressions.
 */
export function parseMapActionEvent(raw: Record<string, unknown>): MapAction | null {
  const action = typeof raw.action === 'string' ? raw.action : null;
  switch (action) {
    case 'flyto':
      if (typeof raw.lat !== 'number' || typeof raw.lon !== 'number') return null;
      if (raw.lat < -90 || raw.lat > 90 || raw.lon < -180 || raw.lon > 180) return null;
      return {
        action: 'flyto',
        lat: raw.lat,
        lon: raw.lon,
        ...(typeof raw.zoom_km === 'number' ? { zoom_km: raw.zoom_km } : {}),
      };
    case 'enable_layer':
    case 'disable_layer':
      if (typeof raw.layer !== 'string' || !raw.layer) return null;
      return { action, layer: raw.layer };
    case 'highlight_entities':
      if (!Array.isArray(raw.entity_ids)) return null;
      return {
        action: 'highlight_entities',
        entity_ids: raw.entity_ids.filter((x): x is string => typeof x === 'string'),
      };
    default:
      return null;
  }
}

// Test-only — clears listeners between unit tests so previous subscribers
// don't leak across cases.
export function _resetMapActionsForTest(): void {
  listeners.clear();
}
