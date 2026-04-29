// UC4 — Layer barrel. Side-effect imports below trigger
// `LayerRegistry.register(...)` for each layer module exactly once.
//
// To add a new layer: drop a `frontend/src/layers/<name>.ts` module that
// calls `LayerRegistry.register(...)` at top level, then add an
// `import './<name>';` line here. No other wiring needed — LagebildView
// reads the registry at render time.

import './maritime';
import './jamming';
import './sentinel';

export { LayerRegistry } from './registry';
export type {
  CesiumLayer,
  ClassificationLabel,
  ClickInspectMeta,
  ClickInspectMetaItem,
  LayerDomain,
  LayerPattern,
  WvProps,
} from './types';
