// Smoke tests for the UC4 maritime layer module (Pattern B, ADR-0001).
//
// Verifies the LayerRegistry contract — that importing the module registers
// it with the right metadata. Cesium runtime + WebSocket lifecycle are
// covered by the manual smoke test in scripts/smoke-test-maritime.sh.

import { describe, expect, it, vi } from 'vitest';

// --- Mock cesium with explicit named exports --------------------------------

vi.mock('cesium', () => {
  class Prop {
    constructor(public v: unknown) {}
  }
  return {
    Cartesian3: { fromDegrees: () => ({ x: 0, y: 0, z: 0 }) },
    Color: new Proxy({}, { get: () => 'mock-color' }),
    ConstantProperty: Prop,
    ConstantPositionProperty: Prop,
    HeightReference: { CLAMP_TO_GROUND: 1, NONE: 0 },
    HorizontalOrigin: { CENTER: 0 },
    VerticalOrigin: { CENTER: 0 },
  };
});

// Static (non-dynamic) imports so vitest resolves the mock cleanly.
import { LayerRegistry } from '../registry';
import '../maritime';

describe('maritime layer module', () => {
  it('registers itself in LayerRegistry on import', () => {
    const layer = LayerRegistry.get('maritime');
    expect(layer).toBeDefined();
    expect(layer?.name).toBe('maritime');
  });

  it('exposes the contract metadata', () => {
    const layer = LayerRegistry.get('maritime')!;
    expect(layer.domain).toBe('maritime');
    expect(layer.pattern).toBe('B');
    expect(layer.defaultClassification).toBe(100); // OPEN
    expect(typeof layer.enable).toBe('function');
    expect(typeof layer.disable).toBe('function');
    expect(typeof layer.getCount).toBe('function');
  });

  it('getCount starts at zero before enable is called', () => {
    const layer = LayerRegistry.get('maritime')!;
    expect(layer.getCount()).toBe(0);
  });

  it('label is set and non-trivial', () => {
    const layer = LayerRegistry.get('maritime')!;
    expect(layer.label).toBeTruthy();
    expect(layer.label.length).toBeGreaterThan(2);
  });
});
