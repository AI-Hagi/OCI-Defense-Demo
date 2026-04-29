// Smoke tests for the UC4 Sentinel-2 layer module (Pattern C, ADR-0001).
//
// Verifies the LayerRegistry contract — registration with the right
// metadata. Cesium imagery rendering is exercised by the manual smoke
// test in scripts/smoke-test-sentinel.sh.

import { describe, expect, it, vi } from 'vitest';

// --- Mock cesium with explicit named exports ------------------------------

vi.mock('cesium', () => {
  class FakeImageryLayer {}
  class FakeImageryLayers {
    addImageryProvider = vi.fn(() => new FakeImageryLayer());
    remove = vi.fn();
  }
  class FakeViewer {
    imageryLayers = new FakeImageryLayers();
    scene = { requestRender: vi.fn() };
  }
  return {
    Cartesian3: { fromDegrees: () => ({ x: 0, y: 0, z: 0 }) },
    Color: new Proxy(
      { fromCssColorString: () => ({ withAlpha: () => 'mock' }) },
      { get: (t, p) => (p in t ? (t as never)[p] : 'mock') },
    ),
    ConstantProperty: class {
      constructor(public v: unknown) {}
    },
    ConstantPositionProperty: class {
      constructor(public v: unknown) {}
    },
    Credit: class {
      constructor(public html: string) {}
    },
    HeightReference: { CLAMP_TO_GROUND: 1, NONE: 0 },
    HorizontalOrigin: { CENTER: 0 },
    VerticalOrigin: { CENTER: 0 },
    PolygonHierarchy: class {
      constructor(public positions: unknown) {}
    },
    UrlTemplateImageryProvider: class {
      constructor(public opts: unknown) {}
    },
    ImageryLayer: FakeImageryLayer,
    Viewer: FakeViewer,
  };
});

import { LayerRegistry } from '../registry';
import '../sentinel';

describe('sentinel layer module', () => {
  it('registers itself in LayerRegistry on import', () => {
    const layer = LayerRegistry.get('sentinel');
    expect(layer).toBeDefined();
    expect(layer?.name).toBe('sentinel');
  });

  it('exposes the contract metadata', () => {
    const layer = LayerRegistry.get('sentinel')!;
    expect(layer.domain).toBe('imagery');
    expect(layer.pattern).toBe('C');
    expect(layer.defaultClassification).toBe(100);
    expect(typeof layer.enable).toBe('function');
    expect(typeof layer.disable).toBe('function');
    expect(typeof layer.getCount).toBe('function');
  });

  it('label is human-readable', () => {
    const layer = LayerRegistry.get('sentinel')!;
    expect(layer.label).toBeTruthy();
    expect(layer.label.toLowerCase()).toContain('sentinel');
  });

  it('getCount toggles 0 → 1 → 0 across enable/disable', async () => {
    const layer = LayerRegistry.get('sentinel')!;
    // Build a fake viewer that satisfies the imagery interface.
    const fakeViewer: any = {
      imageryLayers: {
        addImageryProvider: vi.fn(() => ({})),
        remove: vi.fn(),
      },
      scene: { requestRender: vi.fn() },
    };
    expect(layer.getCount()).toBe(0);
    await layer.enable(fakeViewer);
    expect(layer.getCount()).toBe(1);
    layer.disable(fakeViewer);
    expect(layer.getCount()).toBe(0);
  });
});
