// Smoke tests for the UC4 Satellites: Stations layer module.

import { describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  class Prop {
    constructor(public v: unknown) {}
  }
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
    JulianDate: {
      now: () => ({}),
      toDate: () => new Date('2024-01-02T00:00:00Z'),
    },
    PointPrimitiveCollection: class { add() { return {}; } remove() {} isDestroyed() { return false; } },
    VerticalOrigin: { CENTER: 0 },
    ConstantProperty: Prop,
    ConstantPositionProperty: Prop,
  };
});

import { LayerRegistry } from '../registry';
import '../satellites-stations';

describe('satellites-stations layer module', () => {
  it('registers itself in LayerRegistry on import', () => {
    const layer = LayerRegistry.get('satellites-stations');
    expect(layer).toBeDefined();
    expect(layer?.name).toBe('satellites-stations');
  });

  it('exposes the contract metadata', () => {
    const layer = LayerRegistry.get('satellites-stations')!;
    expect(layer.domain).toBe('air');
    expect(layer.pattern).toBe('A');
    expect(layer.defaultClassification).toBe(100);
    expect(typeof layer.enable).toBe('function');
    expect(typeof layer.disable).toBe('function');
    expect(typeof layer.getCount).toBe('function');
  });

  it('label is human-readable German and references "Stationen"', () => {
    const layer = LayerRegistry.get('satellites-stations')!;
    expect(layer.label).toBeTruthy();
    expect(layer.label.toLowerCase()).toContain('station');
  });

  it('getCount starts at zero before enable is called', () => {
    const layer = LayerRegistry.get('satellites-stations')!;
    expect(layer.getCount()).toBe(0);
  });
});
