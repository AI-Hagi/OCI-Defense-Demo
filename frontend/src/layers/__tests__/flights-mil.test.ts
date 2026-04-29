// Smoke tests for the UC4 Flights (Mil) layer module (Pattern A, ADR-0001).
//
// Verifies the LayerRegistry contract — that importing the module registers
// it with the right metadata. Cesium runtime + fetch lifecycle are covered
// by the manual smoke test in scripts/smoke-test-flights.sh.

import { describe, expect, it, vi } from 'vitest';

// --- Mock cesium with explicit named exports -------------------------------

vi.mock('cesium', () => {
  class Prop {
    constructor(public v: unknown) {}
  }
  return {
    Cartesian3: { fromDegrees: () => ({ x: 0, y: 0, z: 0 }) },
    Color: new Proxy(
      { fromCssColorString: () => 'mock-css' },
      { get: (target, prop) => (prop in target ? (target as never)[prop] : 'mock-color') },
    ),
    ConstantProperty: Prop,
    ConstantPositionProperty: Prop,
    HeightReference: { CLAMP_TO_GROUND: 1, NONE: 0 },
    HorizontalOrigin: { CENTER: 0 },
    VerticalOrigin: { CENTER: 0 },
  };
});

// Static imports — vitest resolves the mock cleanly.
import { LayerRegistry } from '../registry';
import '../flights-mil';

describe('flights-mil layer module', () => {
  it('registers itself in LayerRegistry on import', () => {
    const layer = LayerRegistry.get('flights-mil');
    expect(layer).toBeDefined();
    expect(layer?.name).toBe('flights-mil');
  });

  it('exposes the contract metadata', () => {
    const layer = LayerRegistry.get('flights-mil')!;
    expect(layer.domain).toBe('air');
    expect(layer.pattern).toBe('A');
    expect(layer.defaultClassification).toBe(100); // OPEN
    expect(typeof layer.enable).toBe('function');
    expect(typeof layer.disable).toBe('function');
    expect(typeof layer.getCount).toBe('function');
  });

  it('getCount starts at zero before enable is called', () => {
    const layer = LayerRegistry.get('flights-mil')!;
    expect(layer.getCount()).toBe(0);
  });

  it('label is human-readable and references mil', () => {
    const layer = LayerRegistry.get('flights-mil')!;
    expect(layer.label).toBeTruthy();
    expect(layer.label.toLowerCase()).toContain('mil');
  });
});
