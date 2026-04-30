// Smoke tests for the UC4 GPS Jamming layer module (Pattern A, ADR-0001).
//
// Verifies the LayerRegistry contract: importing the module registers it
// with the right metadata. Cesium runtime + fetch lifecycle are covered
// by the manual smoke test in scripts/smoke-test-jamming.sh.

import { describe, expect, it, vi } from 'vitest';

// --- Mock cesium with explicit named exports -------------------------------

vi.mock('cesium', () => {
  class Prop {
    constructor(public v: unknown) {}
  }
  class FakePolygonHierarchy {
    constructor(public positions: unknown) {}
  }
  return {
    Cartesian3: { fromDegrees: () => ({ x: 0, y: 0, z: 0 }) },
    Color: new Proxy(
      { fromCssColorString: () => ({ withAlpha: () => 'mock-color' }) },
      {
        get(target, prop) {
          if (prop in target) return (target as never)[prop];
          if (prop === 'WHITE') return { withAlpha: () => 'mock-white' };
          return 'mock-color';
        },
      },
    ),
    ConstantProperty: Prop,
    ConstantPositionProperty: Prop,
    HeightReference: { CLAMP_TO_GROUND: 1, NONE: 0 },
    HorizontalOrigin: { CENTER: 0 },
    VerticalOrigin: { CENTER: 0 },
    PolygonHierarchy: FakePolygonHierarchy,
  };
});

// Static imports — vitest resolves the mock cleanly.
import { LayerRegistry } from '../registry';
import '../jamming';

describe('jamming layer module', () => {
  it('registers itself in LayerRegistry on import', () => {
    const layer = LayerRegistry.get('jamming');
    expect(layer).toBeDefined();
    expect(layer?.name).toBe('jamming');
  });

  it('exposes the contract metadata', () => {
    const layer = LayerRegistry.get('jamming')!;
    expect(layer.domain).toBe('ew');
    expect(layer.pattern).toBe('A');
    expect(layer.defaultClassification).toBe(100);
    expect(typeof layer.enable).toBe('function');
    expect(typeof layer.disable).toBe('function');
    expect(typeof layer.getCount).toBe('function');
  });

  it('getCount starts at zero before enable is called', () => {
    const layer = LayerRegistry.get('jamming')!;
    expect(layer.getCount()).toBe(0);
  });

  it('label is set and human-readable', () => {
    const layer = LayerRegistry.get('jamming')!;
    expect(layer.label).toBeTruthy();
    expect(layer.label.toLowerCase()).toContain('jamming');
  });
});
