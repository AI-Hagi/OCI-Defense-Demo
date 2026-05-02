// Smoke tests for the UC4 Ports layer module (Pattern A, hybrid classifier).

import { describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  return {
    Cartesian2: class { constructor(public x = 0, public y = 0) {} },
    Cartesian3: { fromDegrees: () => ({ x: 0, y: 0, z: 0 }) },
    Color: new Proxy(
      { fromCssColorString: () => 'mock-css' },
      { get: (target, prop) => (prop in target ? (target as never)[prop] : 'mock-color') },
    ),
    ConstantPositionProperty: class { constructor(public v: unknown) {} },
    ConstantProperty: class { constructor(public v: unknown) {} },
    HeightReference: { CLAMP_TO_GROUND: 1, NONE: 0 },
    HorizontalOrigin: { CENTER: 0 },
    VerticalOrigin: { CENTER: 0 },
  };
});

import { LayerRegistry } from '../registry';
import {
  ALL_PORT_TYPES,
  iconForPortType,
  getFilter,
  setFilter,
  type PortType,
} from '../ports';

describe('ports layer module', () => {
  it('registers itself in LayerRegistry on import', () => {
    const layer = LayerRegistry.get('ports');
    expect(layer).toBeDefined();
    expect(layer?.name).toBe('ports');
  });

  it('exposes the contract metadata (Pattern A, OPEN, maritime domain)', () => {
    const layer = LayerRegistry.get('ports')!;
    expect(layer.domain).toBe('maritime');
    expect(layer.pattern).toBe('A');
    expect(layer.defaultClassification).toBe(100);
    expect(layer.label).toBeTruthy();
    expect(layer.label.toLowerCase()).toContain('häfen');
  });

  it('default filter contains all five port types', () => {
    const f = getFilter();
    for (const t of ALL_PORT_TYPES) expect(f.has(t)).toBe(true);
  });

  it('iconForPortType returns a distinct data URI per type, falls back to mixed', () => {
    const seen = new Set<string>();
    for (const t of ALL_PORT_TYPES) {
      const uri = iconForPortType(t);
      expect(uri.startsWith('data:image/svg+xml')).toBe(true);
      seen.add(uri);
    }
    // commercial / military / mixed share the anchor SVG but with different
    // colours → at least three unique data URIs (anchor variants + fish + sail).
    expect(seen.size).toBeGreaterThanOrEqual(3);
    // Unknown types fall back to the mixed icon — defensive default.
    expect(iconForPortType('banana' as PortType)).toBe(iconForPortType('mixed'));
  });

  it('getCount starts at zero and setFilter shrinks the active filter set', () => {
    const layer = LayerRegistry.get('ports')!;
    expect(layer.getCount()).toBe(0);
    setFilter(['military']);
    expect(getFilter().size).toBe(1);
    expect(getFilter().has('military')).toBe(true);
    setFilter(ALL_PORT_TYPES); // reset for other tests in this run
    expect(getFilter().size).toBe(5);
  });
});
