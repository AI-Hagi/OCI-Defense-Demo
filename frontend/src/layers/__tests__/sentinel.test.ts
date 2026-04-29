// Smoke tests for the UC4 Sentinel-2 layer modules (Pattern C, ADR-0001).
//
// Each Sentinel sub-layer registers as its own LayerRegistry entry so the
// LagebildView shows one toggle per visualization (True Color, NDVI, …).

import { describe, expect, it, vi } from 'vitest';

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

describe('sentinel layer modules', () => {
  it('registers one entry per configured Sentinel sub-layer', () => {
    const trueColor = LayerRegistry.get('sentinel-true-color-hi');
    const ndvi = LayerRegistry.get('sentinel-ndvi');
    expect(trueColor).toBeDefined();
    expect(ndvi).toBeDefined();
  });

  it('every sentinel entry exposes the contract metadata', () => {
    for (const name of ['sentinel-true-color-hi', 'sentinel-ndvi']) {
      const layer = LayerRegistry.get(name)!;
      expect(layer.domain).toBe('imagery');
      expect(layer.pattern).toBe('C');
      expect(layer.defaultClassification).toBe(100);
      expect(typeof layer.enable).toBe('function');
      expect(typeof layer.disable).toBe('function');
      expect(typeof layer.getCount).toBe('function');
      expect(layer.label.toLowerCase()).toContain('sentinel');
    }
  });

  it('per-layer state is independent (enabling one does not affect the other)', async () => {
    const a = LayerRegistry.get('sentinel-true-color-hi')!;
    const b = LayerRegistry.get('sentinel-ndvi')!;
    const fakeViewer: any = {
      imageryLayers: {
        addImageryProvider: vi.fn(() => ({})),
        remove: vi.fn(),
      },
      scene: { requestRender: vi.fn() },
    };
    expect(a.getCount()).toBe(0);
    expect(b.getCount()).toBe(0);
    await a.enable(fakeViewer);
    expect(a.getCount()).toBe(1);
    expect(b.getCount()).toBe(0);
    await b.enable(fakeViewer);
    expect(a.getCount()).toBe(1);
    expect(b.getCount()).toBe(1);
    a.disable(fakeViewer);
    expect(a.getCount()).toBe(0);
    expect(b.getCount()).toBe(1);
    b.disable(fakeViewer);
    expect(a.getCount()).toBe(0);
    expect(b.getCount()).toBe(0);
  });

  it('registers more than one entry overall in the imagery domain', () => {
    const imagery = LayerRegistry.list().filter((l) => l.domain === 'imagery');
    expect(imagery.length).toBeGreaterThanOrEqual(2);
  });
});
