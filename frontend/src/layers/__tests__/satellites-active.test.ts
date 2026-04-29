// Smoke tests for the UC4 Satellites: Active sub-layer
// (PointPrimitiveCollection variant — limited test scope by design,
// no individual click handler to verify).

import { describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  return {
    Cartesian3: { fromDegrees: () => ({ x: 0, y: 0, z: 0 }) },
    Color: new Proxy(
      { fromCssColorString: () => 'mock-css', CYAN: { withAlpha: () => 'mock-cyan' } },
      { get: (target, prop) => (prop in target ? (target as never)[prop] : 'mock-color') },
    ),
    JulianDate: { now: () => ({}), toDate: () => new Date() },
    PointPrimitiveCollection: class {
      add() { return { position: null }; }
      remove() {}
      isDestroyed() { return false; }
    },
  };
});

import { LayerRegistry } from '../registry';
import '../satellites-active';

describe('satellites-active layer module', () => {
  it('registers itself in LayerRegistry on import', () => {
    const layer = LayerRegistry.get('satellites-active');
    expect(layer).toBeDefined();
    expect(layer?.name).toBe('satellites-active');
  });

  it('exposes the contract metadata (Pattern A, OPEN, air domain)', () => {
    const layer = LayerRegistry.get('satellites-active')!;
    expect(layer.domain).toBe('air');
    expect(layer.pattern).toBe('A');
    expect(layer.defaultClassification).toBe(100);
  });

  it('label is human-readable and references active', () => {
    const layer = LayerRegistry.get('satellites-active')!;
    expect(layer.label.toLowerCase()).toContain('active');
  });
});
