/**
 * Tests for LayerRegistry — register, get, list, byDomain, names,
 * duplicate registration guard.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { CesiumLayer } from '../types';

// ── helpers ──────────────────────────────────────────────────────────────────

function makeLayer(overrides: Partial<CesiumLayer> = {}): CesiumLayer {
  return {
    name: 'test-layer',
    domain: 'maritime',
    pattern: 'A',
    enable: vi.fn().mockResolvedValue(undefined),
    disable: vi.fn(),
    ...overrides,
  };
}

// Re-import the registry module fresh before each test so `layers` map is empty.
// Vitest's module isolation resets ESM module state when vi.resetModules() is called.
let LayerRegistry: (typeof import('../registry'))['LayerRegistry'];

beforeEach(async () => {
  vi.resetModules();
  // Suppress the HMR DEV branch by forcing PROD mode in the test environment
  vi.stubEnv('DEV', false);
  const mod = await import('../registry');
  LayerRegistry = mod.LayerRegistry;
});

// ── register + get ────────────────────────────────────────────────────────────

describe('LayerRegistry.register', () => {
  it('registers a layer and makes it retrievable via get()', () => {
    const layer = makeLayer({ name: 'maritime' });
    LayerRegistry.register(layer);
    expect(LayerRegistry.get('maritime')).toBe(layer);
  });

  it('returns undefined for an unregistered name', () => {
    expect(LayerRegistry.get('nonexistent')).toBeUndefined();
  });

  it('throws when the same name is registered twice in production', () => {
    const layer = makeLayer({ name: 'dup-layer' });
    LayerRegistry.register(layer);
    expect(() => LayerRegistry.register(makeLayer({ name: 'dup-layer' }))).toThrow(
      'Layer already registered: dup-layer',
    );
  });
});

// ── list ─────────────────────────────────────────────────────────────────────

describe('LayerRegistry.list', () => {
  it('returns an empty array when nothing is registered', () => {
    expect(LayerRegistry.list()).toEqual([]);
  });

  it('returns all registered layers', () => {
    const a = makeLayer({ name: 'a' });
    const b = makeLayer({ name: 'b' });
    LayerRegistry.register(a);
    LayerRegistry.register(b);
    expect(LayerRegistry.list()).toHaveLength(2);
    expect(LayerRegistry.list()).toContain(a);
    expect(LayerRegistry.list()).toContain(b);
  });
});

// ── byDomain ─────────────────────────────────────────────────────────────────

describe('LayerRegistry.byDomain', () => {
  it('returns only layers matching the given domain', () => {
    LayerRegistry.register(makeLayer({ name: 'ais', domain: 'maritime' }));
    LayerRegistry.register(makeLayer({ name: 'jamming', domain: 'ew' }));
    LayerRegistry.register(makeLayer({ name: 'ports', domain: 'maritime' }));

    const maritime = LayerRegistry.byDomain('maritime');
    expect(maritime.map((l) => l.name).sort()).toEqual(['ais', 'ports']);
  });

  it('returns an empty array for a domain with no registered layers', () => {
    LayerRegistry.register(makeLayer({ name: 'ais', domain: 'maritime' }));
    expect(LayerRegistry.byDomain('air')).toEqual([]);
  });
});

// ── names ─────────────────────────────────────────────────────────────────────

describe('LayerRegistry.names', () => {
  it('returns the registration-order names', () => {
    LayerRegistry.register(makeLayer({ name: 'first' }));
    LayerRegistry.register(makeLayer({ name: 'second' }));
    expect(LayerRegistry.names()).toEqual(['first', 'second']);
  });

  it('returns an empty array when empty', () => {
    expect(LayerRegistry.names()).toEqual([]);
  });
});
