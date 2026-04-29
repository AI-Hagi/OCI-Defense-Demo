// Smoke tests for the UC4 Satellites: Resource (Earth-Observation) layer.

import { describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  return {
    Cartesian2: class { constructor(public x = 0, public y = 0) {} },
    Cartesian3: { fromDegrees: () => ({ x: 0, y: 0, z: 0 }) },
    CallbackProperty: class { constructor(public f: () => unknown) {} },
    Color: new Proxy(
      { fromCssColorString: () => 'mock-css' },
      { get: (target, prop) => (prop in target ? (target as never)[prop] : 'mock-color') },
    ),
    HeightReference: { CLAMP_TO_GROUND: 1, NONE: 0 },
    HorizontalOrigin: { CENTER: 0 },
    JulianDate: { now: () => ({}), toDate: () => new Date() },
    PointPrimitiveCollection: class {},
    VerticalOrigin: { CENTER: 0 },
  };
});

import { LayerRegistry } from '../registry';
import '../satellites-resource';

describe('satellites-resource layer module', () => {
  it('registers itself in LayerRegistry on import', () => {
    const layer = LayerRegistry.get('satellites-resource');
    expect(layer).toBeDefined();
    expect(layer?.name).toBe('satellites-resource');
  });

  it('exposes the contract metadata (Pattern A, OPEN, air domain)', () => {
    const layer = LayerRegistry.get('satellites-resource')!;
    expect(layer.domain).toBe('air');
    expect(layer.pattern).toBe('A');
    expect(layer.defaultClassification).toBe(100);
  });

  it('label references Earth-Observation', () => {
    const layer = LayerRegistry.get('satellites-resource')!;
    expect(layer.label.toLowerCase()).toContain('earth-observation');
  });

  it('getCount starts at zero before enable is called', () => {
    const layer = LayerRegistry.get('satellites-resource')!;
    expect(layer.getCount()).toBe(0);
  });
});
