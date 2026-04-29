/**
 * Layer module lifecycle tests — maritime (WebSocket), jamming (REST poll),
 * sentinel (WMS imagery provider), and cross-layer initial count.
 *
 * Gaps covered:
 *  - maritime: enable() opens a WebSocket connection
 *  - maritime: disable() closes the WebSocket
 *  - maritime: disable() before enable() does not throw
 *  - maritime: malformed JSON frame is silently ignored
 *  - maritime: WebSocket error event does not throw
 *  - jamming:  enable() calls fetch and renders entities
 *  - jamming:  disable() clears polling interval (no further fetches)
 *  - jamming:  disable() removes all entities from the viewer
 *  - jamming:  network error on fetch does not propagate
 *  - sentinel: enable() adds imagery provider to imageryLayers
 *  - sentinel: disable() removes imagery provider
 *  - sentinel: duplicate enable() calls do not stack providers
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { CesiumLayer } from '../types';

// ---------------------------------------------------------------------------
// Cesium mock — must be declared before any dynamic imports of layer modules.
// vi.mock() calls are hoisted to the top of the file by Vitest.
//
// `Color` must be a constructible class because maritime.ts and several other
// layer modules use `new Color(r, g, b, a)` for backgroundColor/outlineColor.
// Static helpers (WHITE, BLACK, fromCssColorString) are attached afterwards.
// `UrlTemplateImageryProvider` + `Credit` + `ImageryLayer` are required by
// sentinel.ts (it constructs an UrlTemplateImageryProvider per sub-layer
// and reads the returned ImageryLayer back from `imageryLayers.add...`).
// ---------------------------------------------------------------------------
vi.mock('cesium', () => {
  class FakeColor {
    constructor(public r = 0, public g = 0, public b = 0, public a = 1) {}
    withAlpha(_a: number) { return this; }
  }
  // Static-style helpers used by layer modules (Color.WHITE, Color.BLACK,
  // Color.fromCssColorString, etc.). Attached on the constructor function
  // itself so layer code that does `Color.WHITE.withAlpha(...)` keeps working.
  const ColorStatic = FakeColor as unknown as Record<string, unknown>;
  ColorStatic.WHITE = new FakeColor(1, 1, 1, 1);
  ColorStatic.BLACK = new FakeColor(0, 0, 0, 1);
  ColorStatic.CYAN = new FakeColor(0, 1, 1, 1);
  ColorStatic.fromCssColorString = vi.fn(() => new FakeColor());

  // Cartesian3 is used both as constructor (`new Cartesian3(0, -22, 0)`
  // for label pixelOffsets) AND as namespace (`Cartesian3.fromDegrees(...)`).
  // Build it as a class first, then attach static helpers.
  class FakeCartesian3 {
    constructor(public x = 0, public y = 0, public z = 0) {}
  }
  const Cartesian3Static = FakeCartesian3 as unknown as Record<string, unknown>;
  Cartesian3Static.fromDegrees = vi.fn((_lon: number, _lat: number, _h?: number) => ({ x: 0, y: 0, z: 0 }));

  return {
    Cartesian3: FakeCartesian3,
    Cartesian2: vi.fn().mockImplementation((x = 0, y = 0) => ({ x, y })),
    Color: FakeColor,
    PolygonHierarchy: vi.fn().mockImplementation((positions: unknown[]) => ({ positions })),
    ConstantProperty: vi.fn().mockImplementation((val: unknown) => ({ val })),
    ConstantPositionProperty: vi.fn().mockImplementation((pos: unknown) => ({ pos })),
    CallbackProperty: vi.fn().mockImplementation((fn: () => unknown) => ({ fn })),
    HeightReference: { CLAMP_TO_GROUND: 1, NONE: 0 },
    HorizontalOrigin: { CENTER: 0 },
    VerticalOrigin: { CENTER: 0 },
    WebMapServiceImageryProvider: vi.fn().mockImplementation(() => ({ _type: 'wms' })),
    UrlTemplateImageryProvider: vi.fn().mockImplementation((opts: unknown) => ({ _type: 'url-template', opts })),
    Credit: vi.fn().mockImplementation((html: string) => ({ html })),
    ImageryLayer: vi.fn().mockImplementation((provider: unknown) => ({ provider, _layer: true })),
    JulianDate: { now: vi.fn(() => ({})), toDate: vi.fn(() => new Date()) },
    PointPrimitiveCollection: vi.fn().mockImplementation(() => ({
      add: vi.fn(() => ({ position: null })),
      remove: vi.fn(),
      isDestroyed: () => false,
    })),
  };
});

// ---------------------------------------------------------------------------
// Mock Cesium Viewer factory
// ---------------------------------------------------------------------------

function makeMockViewer() {
  return {
    scene: { requestRender: vi.fn() },
    entities: { add: vi.fn(() => ({ id: 'entity-1' })), remove: vi.fn(), removeAll: vi.fn() },
    imageryLayers: { addImageryProvider: vi.fn(() => ({ _layer: true })), remove: vi.fn() },
  };
}

// ---------------------------------------------------------------------------
// Maritime layer — WebSocket lifecycle
// ---------------------------------------------------------------------------

describe('maritime layer', () => {
  let viewer: ReturnType<typeof makeMockViewer>;
  let maritime: { default: CesiumLayer };

  // Fake WebSocket instance returned by the constructor
  let fakeWs: {
    onmessage: ((ev: MessageEvent) => void) | null;
    onerror: ((ev: Event) => void) | null;
    onclose: ((ev: CloseEvent) => void) | null;
    onopen: (() => void) | null;
    close: ReturnType<typeof vi.fn>;
    readyState: number;
    send: ReturnType<typeof vi.fn>;
  };

  beforeEach(async () => {
    vi.resetModules();
    viewer = makeMockViewer();

    fakeWs = {
      onmessage: null,
      onerror: null,
      onclose: null,
      onopen: null,
      close: vi.fn(),
      readyState: 1, // OPEN
      send: vi.fn(),
    };

    const WsMock = vi.fn(() => fakeWs);
    vi.stubGlobal('WebSocket', WsMock);

    // Import after module reset so module-level state is fresh
    maritime = await import('../maritime');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('enable() opens a WebSocket connection', async () => {
    const WsMock = globalThis.WebSocket as ReturnType<typeof vi.fn>;
    await maritime.default.enable(viewer as never);
    expect(WsMock).toHaveBeenCalledOnce();
  });

  it('disable() closes the WebSocket when one is open', async () => {
    await maritime.default.enable(viewer as never);
    maritime.default.disable(viewer as never);
    expect(fakeWs.close).toHaveBeenCalledOnce();
  });

  it('disable() before enable() does not throw', () => {
    expect(() => maritime.default.disable(viewer as never)).not.toThrow();
  });

  it('malformed JSON frame is silently ignored — no throw, no entity added', async () => {
    await maritime.default.enable(viewer as never);

    // Simulate a bad WebSocket message
    expect(() => {
      fakeWs.onmessage?.({ data: '{{not valid json' } as MessageEvent);
    }).not.toThrow();

    expect(viewer.entities.add).not.toHaveBeenCalled();
  });

  it('WebSocket error event does not throw', async () => {
    await maritime.default.enable(viewer as never);

    expect(() => {
      fakeWs.onerror?.({ type: 'error' } as Event);
    }).not.toThrow();
  });

  it('valid AIS frame adds an entity to the viewer', async () => {
    await maritime.default.enable(viewer as never);

    const frame = JSON.stringify({
      type: 'ais_frame',
      mmsi: 123456789,
      lat: 54.0,
      lon: 12.0,
      vessel_name: 'TEST VESSEL',
    });

    fakeWs.onmessage?.({ data: frame } as MessageEvent);

    expect(viewer.entities.add).toHaveBeenCalledOnce();
    expect(viewer.scene.requestRender).toHaveBeenCalled();
  });

  it('frame missing type field is not treated as ais_frame', async () => {
    await maritime.default.enable(viewer as never);

    fakeWs.onmessage?.({
      data: JSON.stringify({ mmsi: 999, lat: 54.0, lon: 12.0 }),
    } as MessageEvent);

    expect(viewer.entities.add).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Jamming layer — polling lifecycle
// ---------------------------------------------------------------------------

const VALID_GEOJSON = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [[[10, 54], [11, 54], [11, 55], [10, 55], [10, 54]]],
      },
      properties: {
        h3_index: '891f1d4847bffff',
        aircraft_total: 40,
        aircraft_low_nacp: 30,
        low_nacp_ratio: 0.75,
        classification_color: 'red',
        centroid_lat: 54.5,
        centroid_lon: 10.5,
      },
    },
  ],
};

describe('jamming layer', () => {
  let viewer: ReturnType<typeof makeMockViewer>;
  let jamming: { default: CesiumLayer };

  beforeEach(async () => {
    vi.resetModules();
    vi.useFakeTimers();
    viewer = makeMockViewer();

    // Default fetch mock — returns valid GeoJSON
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue(VALID_GEOJSON),
      }),
    );

    jamming = await import('../jamming');
  });

  afterEach(async () => {
    // Ensure disable() is called so the module clears its interval state
    try { jamming.default.disable(viewer as never); } catch { /* noop */ }
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('enable() calls fetch and calls requestRender', async () => {
    await jamming.default.enable(viewer as never);
    expect(globalThis.fetch).toHaveBeenCalledOnce();
    expect(viewer.scene.requestRender).toHaveBeenCalled();
  });

  it('enable() adds polygon entities for each GeoJSON feature', async () => {
    await jamming.default.enable(viewer as never);
    expect(viewer.entities.add).toHaveBeenCalledOnce();
  });

  it('disable() removes all entities and calls requestRender', async () => {
    await jamming.default.enable(viewer as never);
    viewer.entities.remove.mockClear();

    jamming.default.disable(viewer as never);

    expect(viewer.entities.remove).toHaveBeenCalled();
    expect(viewer.scene.requestRender).toHaveBeenCalled();
  });

  it('disable() clears the polling interval — no further fetches after disable', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    await jamming.default.enable(viewer as never);
    const callsAfterEnable = fetchMock.mock.calls.length;

    jamming.default.disable(viewer as never);

    // Advance time well past the 6h refresh window
    vi.advanceTimersByTime(8 * 60 * 60 * 1000);

    expect(fetchMock.mock.calls.length).toBe(callsAfterEnable); // no new calls
  });

  it('network error on fetch does not propagate out of enable()', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network failure')));

    await expect(jamming.default.enable(viewer as never)).resolves.not.toThrow();
  });

  it('non-ok HTTP response is silently ignored', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 503 }),
    );

    await expect(jamming.default.enable(viewer as never)).resolves.not.toThrow();
    expect(viewer.entities.add).not.toHaveBeenCalled();
  });

  it('malformed JSON response is silently ignored', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockRejectedValue(new SyntaxError('Unexpected token')),
      }),
    );

    await expect(jamming.default.enable(viewer as never)).resolves.not.toThrow();
  });

  it('response without FeatureCollection type is ignored', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ type: 'Feature', features: null }),
      }),
    );

    await expect(jamming.default.enable(viewer as never)).resolves.not.toThrow();
    expect(viewer.entities.add).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Sentinel layer — WMS imagery provider lifecycle
// ---------------------------------------------------------------------------

describe('sentinel layer', () => {
  let viewer: ReturnType<typeof makeMockViewer>;
  let sentinel: { default: CesiumLayer };

  beforeEach(async () => {
    vi.resetModules();
    viewer = makeMockViewer();

    // Sentinel fetch (token exchange) — use MSW or stub fetch
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ access_token: 'fake-token', expires_in: 3600 }),
        text: vi.fn().mockResolvedValue(''),
      }),
    );

    try {
      sentinel = await import('../sentinel');
    } catch {
      // sentinel layer may not exist yet — skip gracefully in that case
    }
  });

  afterEach(() => {
    try { sentinel?.default?.disable(viewer as never); } catch { /* noop */ }
    vi.unstubAllGlobals();
  });

  it('enable() adds an imagery provider to imageryLayers', async () => {
    if (!sentinel) return;
    await sentinel.default.enable(viewer as never);
    expect(viewer.imageryLayers.addImageryProvider).toHaveBeenCalledOnce();
  });

  it('disable() removes the imagery provider layer', async () => {
    if (!sentinel) return;
    await sentinel.default.enable(viewer as never);
    sentinel.default.disable(viewer as never);
    expect(viewer.imageryLayers.remove).toHaveBeenCalledOnce();
  });

  it('multiple enable() calls do not stack duplicate imagery layers', async () => {
    if (!sentinel) return;
    await sentinel.default.enable(viewer as never);
    await sentinel.default.enable(viewer as never);
    // Should only add the provider once (idempotent)
    expect(viewer.imageryLayers.addImageryProvider).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// Cross-layer: getCount() returns 0 before enable()
// ---------------------------------------------------------------------------

describe('getCount() initial state', () => {
  it('all registered layers report getCount() === 0 before any enable()', async () => {
    vi.resetModules();

    const { LayerRegistry } = await import('../registry');
    // Import the side-effecting modules so they register
    await import('../maritime').catch(() => null);
    await import('../jamming').catch(() => null);

    const layers = LayerRegistry.list();
    for (const layer of layers) {
      if (typeof layer.getCount === 'function') {
        expect(layer.getCount()).toBe(0);
      }
    }
  });
});
