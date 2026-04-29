// UC4 — Sentinel-2 imagery layer (Pattern C: WMS reverse-proxy + OAuth2).
//
// Calls the sovereign sentinel-proxy at
//   /api/osint/sentinel/tiles/{layer}/{z}/{x}/{y}.png
// which translates the XYZ tile request into a Sentinel Hub WMS GetMap call
// signed with an OAuth2 Bearer token. Browsers never see the OAuth
// credentials and never reach sh.dataspace.copernicus.eu directly.

import {
  ImageryLayer,
  UrlTemplateImageryProvider,
  Credit,
  type Viewer,
} from 'cesium';
import { LayerRegistry } from './registry';
import type { CesiumLayer } from './types';

// ---------------------------------------------------------------------------
// URL helper — origin-relative by default (matches the maritime + jamming
// convention; the frontend nginx + the prod ingress both proxy /api/osint/
// to the right backend in dev and prod respectively).
// ---------------------------------------------------------------------------

const SENTINEL_LAYER =
  (import.meta.env.VITE_SENTINEL_LAYER as string | undefined) ??
  'TRUE-COLOR-HIGHLIGHT-OPTIMIZED';

const TILE_URL_TEMPLATE =
  (import.meta.env.VITE_SENTINEL_TILE_URL as string | undefined) ??
  `/api/osint/sentinel/tiles/${SENTINEL_LAYER}/{z}/{x}/{y}.png`;

// ---------------------------------------------------------------------------
// Module state — scoped to one enable/disable cycle.
// ---------------------------------------------------------------------------

let imageryLayer: ImageryLayer | null = null;

const sentinelLayer: CesiumLayer = {
  name: 'sentinel',
  label: 'Sentinel-2 Imagery',
  domain: 'imagery',
  pattern: 'C',
  defaultClassification: 100,

  async enable(viewer: Viewer): Promise<void> {
    if (imageryLayer !== null) return;
    const provider = new UrlTemplateImageryProvider({
      url: TILE_URL_TEMPLATE,
      maximumLevel: 14,
      credit: new Credit('© Copernicus Dataspace / Sentinel-2 L2A (via sentinel-proxy)'),
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

LayerRegistry.register(sentinelLayer);

export default sentinelLayer;
