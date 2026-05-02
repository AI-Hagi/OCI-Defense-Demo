// UC4 — singleton LayerRegistry (ADR-0001).
//
// Layer modules call `LayerRegistry.register(<layer>)` as a top-level side
// effect when imported. Consumers (LagebildView, chat-service map_action
// dispatcher) read via `list()` / `byDomain()` / `get()`.

import type { CesiumLayer, LayerDomain } from './types';

const layers = new Map<string, CesiumLayer>();

export const LayerRegistry = {
  register(layer: CesiumLayer): void {
    if (layers.has(layer.name)) {
      // Side-effect imports may run twice in HMR — keep the existing
      // registration rather than throwing in dev.
      if (import.meta.env.DEV) return;
      throw new Error(`Layer already registered: ${layer.name}`);
    }
    layers.set(layer.name, layer);
  },

  get(name: string): CesiumLayer | undefined {
    return layers.get(name);
  },

  list(): CesiumLayer[] {
    return Array.from(layers.values());
  },

  byDomain(domain: LayerDomain): CesiumLayer[] {
    return this.list().filter((l) => l.domain === domain);
  },

  /** Names of all registered layers — useful for tests and debugging. */
  names(): string[] {
    return Array.from(layers.keys());
  },
};
