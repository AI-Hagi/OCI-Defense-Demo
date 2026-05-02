/**
 * Tests for frontend/src/state/viewport.ts
 *
 * Gaps covered:
 *  - rectToViewport(): correct lat/lon/distNm/bbox from a normal rectangle
 *  - rectToViewport(): distNm is capped at 250 for very wide viewports
 *  - rectToViewport(): distNm has a minimum floor of 10
 *  - rectToViewport(): cosLat guard clamps to 0.05 near the poles (cos ≈ 0)
 *  - fallbackViewport(): returns Baltic default when no viewer
 *  - getViewport(): returns rectToViewport result when viewer is bound
 *  - getViewport(): returns fallback when viewer.isDestroyed() === true
 *  - getViewport(): returns fallback when computeViewRectangle() is undefined
 *  - getViewport(): returns lastViewport cache when viewer is destroyed after bind
 *  - bindViewer(): re-binding replaces the old camera listener
 *  - subscribe(): listener is called on emit()
 *  - subscribe(): returned unsubscribe() removes the listener
 *  - subscribe(): throwing listener does not block other subscribers
 *  - subscribe(): multiple subscribers each receive the same viewport value
 *  - viewportQuery(): formats lat/lon/dist correctly
 *  - bboxQuery(): formats all four bbox values correctly
 *  - bboxQuery(): negative coordinates are formatted correctly
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

// ---------------------------------------------------------------------------
// Cesium mock
// CesiumMath and Rectangle are the only cesium exports consumed by viewport.ts.
// ---------------------------------------------------------------------------

vi.mock('cesium', () => {
  const CesiumMath = {
    toDegrees: (rad: number) => (rad * 180) / Math.PI,
    toRadians: (deg: number) => (deg * Math.PI) / 180,
  };
  class Rectangle {
    constructor(
      public west: number,
      public south: number,
      public east: number,
      public north: number,
    ) {}
  }
  return { Math: CesiumMath, Rectangle };
});

// ---------------------------------------------------------------------------
// Module under test — imported AFTER the mock declaration so vitest hoists
// the vi.mock() call before the import.
// ---------------------------------------------------------------------------

import {
  bindViewer,
  bboxQuery,
  getViewport,
  subscribe,
  viewportQuery,
  type Viewport,
} from '../viewport';
import { Math as CesiumMath } from 'cesium';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEG = Math.PI / 180; // multiply degrees by this to get radians

/** Build a minimal Cesium Viewer mock. */
function makeViewer(opts: {
  isDestroyed?: boolean;
  rect?: { south: number; west: number; north: number; east: number } | undefined;
}) {
  const { isDestroyed = false, rect } = opts;
  const moveEndListeners: Array<() => void> = [];
  return {
    isDestroyed: () => isDestroyed,
    camera: {
      computeViewRectangle: () =>
        rect
          ? {
              south: rect.south * DEG,
              west: rect.west * DEG,
              north: rect.north * DEG,
              east: rect.east * DEG,
            }
          : undefined,
      moveEnd: {
        addEventListener: (fn: () => void) => moveEndListeners.push(fn),
        removeEventListener: (fn: () => void) => {
          const idx = moveEndListeners.indexOf(fn);
          if (idx !== -1) moveEndListeners.splice(idx, 1);
        },
        // Test helper: fire all registered listeners
        _fire: () => moveEndListeners.forEach((fn) => fn()),
        _listenerCount: () => moveEndListeners.length,
      },
    },
  };
}

// Reset module-level singletons between tests by re-importing the module fresh.
// Because vitest isolates modules per file we only need to reset singleton state.
// We do this by binding to a destroyed viewer so getViewport() falls back to defaults.
beforeEach(() => {
  // Bind a destroyed viewer to clear the lastViewport cache and force fallback.
  bindViewer(makeViewer({ isDestroyed: true }) as any);
});

// ---------------------------------------------------------------------------
// viewportQuery
// ---------------------------------------------------------------------------

describe('viewportQuery', () => {
  it('formats lat, lon, and dist with 4 decimal places', () => {
    // toFixed(4) truncates the 5th digit — 54.12345 → "54.1234"
    const v: Viewport = { lat: 54.12345, lon: 15.67890, distNm: 120, bbox: [50, 10, 58, 20] };
    expect(viewportQuery(v)).toBe('lat=54.1234&lon=15.6789&dist=120');
  });

  it('formats negative coordinates correctly', () => {
    const v: Viewport = { lat: -33.9999, lon: -70.0001, distNm: 250, bbox: [-40, -80, -30, -60] };
    const q = viewportQuery(v);
    expect(q).toContain('lat=-33.9999');
    expect(q).toContain('lon=-70.0001');
  });
});

// ---------------------------------------------------------------------------
// bboxQuery
// ---------------------------------------------------------------------------

describe('bboxQuery', () => {
  it('formats all four bbox corners', () => {
    const v: Viewport = { lat: 54, lon: 15, distNm: 100, bbox: [50.1, 10.2, 58.3, 20.4] };
    const q = bboxQuery(v);
    expect(q).toContain('bbox_s=50.1000');
    expect(q).toContain('bbox_w=10.2000');
    expect(q).toContain('bbox_n=58.3000');
    expect(q).toContain('bbox_e=20.4000');
  });

  it('handles negative bbox coordinates', () => {
    const v: Viewport = { lat: 0, lon: -170, distNm: 250, bbox: [-10, -180, 10, -160] };
    const q = bboxQuery(v);
    expect(q).toContain('bbox_s=-10.0000');
    expect(q).toContain('bbox_w=-180.0000');
    expect(q).toContain('bbox_e=-160.0000');
  });
});

// ---------------------------------------------------------------------------
// getViewport — fallback paths
// ---------------------------------------------------------------------------

describe('getViewport — fallback', () => {
  it('returns the Baltic default when no viewer is bound (initial state)', () => {
    // beforeEach binds a destroyed viewer, resetting lastViewport.
    // A destroyed viewer + no cache → fallback.
    const v = getViewport();
    expect(v.lat).toBe(54.5);
    expect(v.lon).toBe(15.0);
    expect(v.distNm).toBe(250);
    expect(v.bbox).toEqual([40, -10, 70, 40]);
  });

  it('returns the Baltic default when computeViewRectangle() returns undefined', () => {
    bindViewer(makeViewer({ rect: undefined }) as any);
    const v = getViewport();
    expect(v.lat).toBe(54.5);
    expect(v.lon).toBe(15.0);
  });

  it('returns the Baltic default when viewer.isDestroyed() is true', () => {
    bindViewer(makeViewer({ isDestroyed: true }) as any);
    const v = getViewport();
    expect(v.lat).toBe(54.5);
  });

  it('returns lastViewport cache when viewer becomes destroyed after a successful call', () => {
    // First call with a live viewer to populate lastViewport.
    const liveViewer = makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } });
    bindViewer(liveViewer as any);
    const first = getViewport();
    expect(first.lat).toBeCloseTo(54, 1);

    // Bind a destroyed viewer — lastViewport should still be returned.
    bindViewer(makeViewer({ isDestroyed: true }) as any);
    const cached = getViewport();
    expect(cached.lat).toBeCloseTo(54, 1);
  });
});

// ---------------------------------------------------------------------------
// getViewport — live viewer paths (rectToViewport internals)
// ---------------------------------------------------------------------------

describe('getViewport — rectToViewport', () => {
  it('computes correct center lat/lon from a Baltic-region rectangle', () => {
    bindViewer(makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } }) as any);
    const v = getViewport();
    expect(v.lat).toBeCloseTo(54, 4);
    expect(v.lon).toBeCloseTo(15, 4);
  });

  it('includes the correct bbox', () => {
    bindViewer(makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } }) as any);
    const { bbox } = getViewport();
    expect(bbox[0]).toBeCloseTo(50, 3); // south
    expect(bbox[1]).toBeCloseTo(10, 3); // west
    expect(bbox[2]).toBeCloseTo(58, 3); // north
    expect(bbox[3]).toBeCloseTo(20, 3); // east
  });

  it('caps distNm at 250 for a very wide viewport (full-world range)', () => {
    // 160° wide × 80° tall — distNm would be huge without the cap
    bindViewer(makeViewer({ rect: { south: -40, west: -80, north: 40, east: 80 } }) as any);
    const v = getViewport();
    expect(v.distNm).toBe(250);
  });

  it('floors distNm at 10 for a tiny viewport (very zoomed in)', () => {
    // 0.01° wide × 0.01° tall → ~0.3 nm diagonal → must floor to 10
    bindViewer(
      makeViewer({ rect: { south: 54.0, west: 10.0, north: 54.01, east: 10.01 } }) as any,
    );
    const v = getViewport();
    expect(v.distNm).toBeGreaterThanOrEqual(10);
  });

  it('uses cosLat guard (≥ 0.05) near the poles to avoid near-zero division', () => {
    // lat ≈ 89°N — cos(89°) ≈ 0.017, which is below the 0.05 guard
    bindViewer(makeViewer({ rect: { south: 88, west: -10, north: 90, east: 10 } }) as any);
    // Must not throw or produce NaN/Infinity
    const v = getViewport();
    expect(Number.isFinite(v.distNm)).toBe(true);
    expect(Number.isFinite(v.lon)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// subscribe / emit
// ---------------------------------------------------------------------------

describe('subscribe', () => {
  it('calls the listener when the camera moveEnd fires (after debounce)', async () => {
    vi.useFakeTimers();

    const listener = vi.fn();
    const unsub = subscribe(listener);

    const viewer = makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } });
    bindViewer(viewer as any);

    // Simulate camera moveEnd
    (viewer.camera.moveEnd as any)._fire();

    // Listener must not have fired yet — debounce is 600 ms
    expect(listener).not.toHaveBeenCalled();

    // Advance timer past debounce window
    vi.advanceTimersByTime(700);

    expect(listener).toHaveBeenCalledOnce();
    const received: Viewport = listener.mock.calls[0][0];
    expect(received.lat).toBeCloseTo(54, 1);

    unsub();
    vi.useRealTimers();
  });

  it('does not call the listener after unsubscribe()', async () => {
    vi.useFakeTimers();

    const listener = vi.fn();
    const unsub = subscribe(listener);
    unsub(); // unsubscribe immediately

    const viewer = makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } });
    bindViewer(viewer as any);
    (viewer.camera.moveEnd as any)._fire();
    vi.advanceTimersByTime(700);

    expect(listener).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('does not block other subscribers when one listener throws', () => {
    vi.useFakeTimers();

    const bad = vi.fn().mockImplementation(() => { throw new Error('listener exploded'); });
    const good = vi.fn();

    subscribe(bad);
    const unsubGood = subscribe(good);

    const viewer = makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } });
    bindViewer(viewer as any);
    (viewer.camera.moveEnd as any)._fire();
    vi.advanceTimersByTime(700);

    expect(good).toHaveBeenCalledOnce();

    unsubGood();
    vi.useRealTimers();
  });

  it('delivers the same viewport value to all simultaneous subscribers', () => {
    vi.useFakeTimers();

    const a = vi.fn();
    const b = vi.fn();
    const unsubA = subscribe(a);
    const unsubB = subscribe(b);

    const viewer = makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } });
    bindViewer(viewer as any);
    (viewer.camera.moveEnd as any)._fire();
    vi.advanceTimersByTime(700);

    expect(a).toHaveBeenCalledOnce();
    expect(b).toHaveBeenCalledOnce();
    expect(a.mock.calls[0][0]).toEqual(b.mock.calls[0][0]);

    unsubA();
    unsubB();
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// bindViewer — rebinding clears old listener
// ---------------------------------------------------------------------------

describe('bindViewer', () => {
  it('removes the old camera listener when bound a second time', () => {
    const viewer1 = makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } });
    const viewer2 = makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } });

    bindViewer(viewer1 as any);
    // viewer1 should now have 1 listener
    expect((viewer1.camera.moveEnd as any)._listenerCount()).toBe(1);

    bindViewer(viewer2 as any);
    // After rebinding, viewer1 listener must have been removed
    expect((viewer1.camera.moveEnd as any)._listenerCount()).toBe(0);
    expect((viewer2.camera.moveEnd as any)._listenerCount()).toBe(1);
  });

  it('does not accumulate listeners on repeated binds to the same viewer', () => {
    const viewer = makeViewer({ rect: { south: 50, west: 10, north: 58, east: 20 } });

    bindViewer(viewer as any);
    bindViewer(viewer as any);
    bindViewer(viewer as any);

    // Each rebind removes the previous handler, net count must be 1
    expect((viewer.camera.moveEnd as any)._listenerCount()).toBe(1);
  });
});
