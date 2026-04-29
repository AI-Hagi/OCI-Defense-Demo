// UC4 — Sentinel-2 imagery layers (Pattern C: WMS reverse-proxy + OAuth2).
//
// One LayerRegistry entry per Sentinel-Hub sub-layer that has a Style
// configured upstream. Each entry has its own ImageryLayer reference;
// enabling one and disabling another switches the displayed visualization.
// Multiple can be enabled at once — Cesium stacks ImageryLayers, so the
// last-enabled wins on overlap.
//
// To add a new Sentinel sub-layer:
//   1. Add a Style for it in the Sentinel Hub Configuration UI.
//   2. Append a row to SENTINEL_LAYERS below.
//   3. (No frontend rebuild needed for backend tile fetch — the new entry
//       just hits /api/osint/sentinel/tiles/{name}/...)

import {
  Credit,
  ImageryLayer,
  UrlTemplateImageryProvider,
  type Viewer,
} from 'cesium';
import { LayerRegistry } from './registry';
import type { CesiumLayer } from './types';

interface SentinelSubLayer {
  /** LayerRegistry name — kebab-case, prefixed `sentinel-`. */
  name: string;
  /** Sidebar label shown to the operator. */
  label: string;
  /** Sentinel-Hub layer name as configured in the Configuration UI. */
  sentinelLayer: string;
  /** Maximum tile zoom — Sentinel-2 is most useful at 8-14. */
  maximumLevel: number;
}

// Layers verified to have a Style configured upstream as of 2026-04-29.
// TRUE-COLOR / FALSE-COLOR / NDMI / NDWI return WMS 400 "No style defined"
// today; add them here once the Sentinel Hub Configuration is fixed.
const SENTINEL_LAYERS: ReadonlyArray<SentinelSubLayer> = [
  {
    name: 'sentinel-true-color-hi',
    label: 'Sentinel-2: True Color (HL)',
    sentinelLayer: 'TRUE-COLOR-HIGHLIGHT-OPTIMIZED',
    maximumLevel: 14,
  },
  {
    name: 'sentinel-ndvi',
    label: 'Sentinel-2: NDVI',
    sentinelLayer: 'NDVI',
    maximumLevel: 14,
  },
];

function urlTemplateFor(sentinelLayer: string): string {
  // Allow per-layer override via env (rarely used; defaults are origin-relative
  // so the same image works in dev + prod).
  const envKey = `VITE_SENTINEL_TILE_URL_${sentinelLayer.replace(/-/g, '_')}`;
  const override = (import.meta.env as Record<string, string | undefined>)[envKey];
  if (override) return override;
  return `/api/osint/sentinel/tiles/${sentinelLayer}/{z}/{x}/{y}.png`;
}

function makeSentinelLayer(spec: SentinelSubLayer): CesiumLayer {
  // Per-instance state — closes over `imageryLayer`, never globalised.
  let imageryLayer: ImageryLayer | null = null;

  return {
    name: spec.name,
    label: spec.label,
    domain: 'imagery',
    pattern: 'C',
    defaultClassification: 100,

    async enable(viewer: Viewer): Promise<void> {
      if (imageryLayer !== null) return;
      const provider = new UrlTemplateImageryProvider({
        url: urlTemplateFor(spec.sentinelLayer),
        maximumLevel: spec.maximumLevel,
        credit: new Credit(
          '© Copernicus Dataspace / Sentinel-2 L2A (via sentinel-proxy)',
        ),
      });
      imageryLayer = viewer.imageryLayers.addImageryProvider(provider);
      viewer.scene.requestRender();
    },

    disable(viewer: Viewer): void {
      if (imageryLayer === null) return;
      viewer.imageryLayers.remove(imageryLayer, true);
      imageryLayer = null;
      viewer.scene.requestRender();
    },

    getCount(): number {
      return imageryLayer === null ? 0 : 1;
    },
  };
}

for (const spec of SENTINEL_LAYERS) {
  LayerRegistry.register(makeSentinelLayer(spec));
}

// Default export kept for backward compatibility with code that imports
// the module as a single value — points at the first registered layer.
export default LayerRegistry.get(SENTINEL_LAYERS[0]!.name)!;
