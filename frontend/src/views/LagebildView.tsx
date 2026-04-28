// UC4 — Cesium 3D-Lagebild host view.
//
// Hosts a single Cesium.Viewer, renders domain-grouped layer toggles from
// the LayerRegistry, and shows a click-to-inspect intel panel for the
// last-picked Entity (`_wv*` convention from layers/types.ts).

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Credit,
  Rectangle,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  UrlTemplateImageryProvider,
  Viewer,
  type Cartesian2,
} from 'cesium';
import 'cesium/Source/Widgets/widgets.css';
import { Globe } from 'lucide-react';

// Side-effect import — registers all layer modules in the singleton
// LayerRegistry. Must run before we read `LayerRegistry.list()`.
import { LayerRegistry } from '../layers';
import type {
  CesiumLayer,
  ClassificationLabel,
  ClickInspectMeta,
  ClickInspectMetaItem,
  LayerDomain,
  WvProps,
} from '../layers/types';
import { labelColor, numericToLabel } from '../types/classification';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

// Camera default — Cesium flies here on mount. This is NOT the AIS
// subscription filter; that lives server-side in
// services/ais-multiplexer/app/settings.py:AIS_BBOX_DEFAULT and may be
// tighter or wider. Treat them as independent concerns: this controls
// the operator's initial framing, the server controls which frames are
// forwarded.
const CAMERA_DEFAULT_BBOX = Rectangle.fromDegrees(8.0, 53.0, 22.0, 56.0);

const DOMAIN_LABELS: Record<LayerDomain, string> = {
  air: 'Luft',
  maritime: 'Maritim',
  ew: 'Elektromagnetik / EW',
  surface: 'Oberfläche',
  environment: 'Umwelt',
  imagery: 'Bildgebung',
  'sovereign-fusion': 'Sovereign Fusion',
};

const DOMAIN_ORDER: LayerDomain[] = [
  'air',
  'maritime',
  'ew',
  'surface',
  'environment',
  'imagery',
  'sovereign-fusion',
];

// ---------------------------------------------------------------------------
// Types local to the view.
// ---------------------------------------------------------------------------

// Read-only view onto the WvProps that get attached to picked Entities.
type WvPickable = Partial<WvProps>;

function readWvProps(picked: unknown): ClickInspectMeta | null {
  if (typeof picked !== 'object' || picked === null) return null;
  // Cesium returns either an Entity or a primitive descriptor with `.id`
  // pointing at the Entity. Normalise both forms here.
  const candidate =
    'id' in picked && picked.id && typeof picked.id === 'object'
      ? (picked.id as WvPickable)
      : (picked as WvPickable);

  if (!candidate._wvType) return null;

  return {
    type: candidate._wvType,
    meta: candidate._wvMeta ?? [],
    lat: candidate._wvLat ?? 0,
    lon: candidate._wvLon ?? 0,
    classification: (candidate._wvClassification ?? 100) as ClassificationLabel,
    sources: candidate._wvSources ?? [],
  };
}

// ---------------------------------------------------------------------------
// Component.
// ---------------------------------------------------------------------------

export function LagebildView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const handlerRef = useRef<ScreenSpaceEventHandler | null>(null);

  const [enabledLayers, setEnabledLayers] = useState<Set<string>>(new Set());
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [intel, setIntel] = useState<ClickInspectMeta | null>(null);

  // The list is captured once on mount — registry is populated by the
  // side-effect imports in `../layers` and won't change at runtime.
  const layers: CesiumLayer[] = useMemo(() => LayerRegistry.list(), []);

  const layersByDomain = useMemo(() => {
    const grouped: Partial<Record<LayerDomain, CesiumLayer[]>> = {};
    for (const layer of layers) {
      const list = grouped[layer.domain] ?? [];
      list.push(layer);
      grouped[layer.domain] = list;
    }
    return grouped;
  }, [layers]);

  // -------------------------------------------------------------------------
  // Cesium viewer lifecycle.
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (!containerRef.current) return;

    // Tile provider: OpenStreetMap. No Cesium-Ion token needed.
    // Tiles are served by the OSM CDN; switch to a self-hosted/sovereign
    // tile cache (Pattern C — see docs) when classification > OPEN.
    const osmProvider = new UrlTemplateImageryProvider({
      url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      maximumLevel: 19,
      credit: new Credit('© OpenStreetMap contributors'),
    });

    const viewer = new Viewer(containerRef.current, {
      requestRenderMode: true,
      maximumRenderTimeChange: Infinity,
      animation: false,
      timeline: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      navigationHelpButton: false,
      sceneModePicker: false,
      fullscreenButton: false,
      selectionIndicator: false,
      infoBox: false,
    });
    // Replace the default Cesium-Ion Bing imagery with OSM tiles —
    // eliminates the Ion-token rate limit and removes the US service
    // dependency from the public demo path.
    viewer.imageryLayers.removeAll();
    viewer.imageryLayers.addImageryProvider(osmProvider);
    viewerRef.current = viewer;

    // Camera: zoom to Baltic by default.
    viewer.camera.flyTo({
      destination: CAMERA_DEFAULT_BBOX,
      duration: 0,
    });
    viewer.scene.requestRender();

    // Click handler for inspect panel.
    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((event: { position: Cartesian2 }) => {
      const picked = viewer.scene.pick(event.position);
      if (!picked) {
        setIntel(null);
        return;
      }
      const inspect = readWvProps(picked);
      if (inspect) setIntel(inspect);
    }, ScreenSpaceEventType.LEFT_CLICK);
    handlerRef.current = handler;

    return () => {
      handler.destroy();
      handlerRef.current = null;
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  // -------------------------------------------------------------------------
  // Toggle a layer.
  // -------------------------------------------------------------------------

  useEffect(() => {
    // Subscribe to count changes for every registered layer once.
    const unsubs: Array<() => void> = [];
    for (const layer of layers) {
      if (!layer.onCountChange) continue;
      const unsub = layer.onCountChange((n) => {
        setCounts((prev) => ({ ...prev, [layer.name]: n }));
      });
      unsubs.push(unsub);
    }
    return () => {
      unsubs.forEach((u) => u());
    };
  }, [layers]);

  function toggleLayer(layer: CesiumLayer): void {
    const viewer = viewerRef.current;
    if (!viewer) return;
    setEnabledLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layer.name)) {
        layer.disable(viewer);
        next.delete(layer.name);
        setCounts((c) => ({ ...c, [layer.name]: 0 }));
      } else {
        // enable() is async but we don't block the UI on it
        void layer.enable(viewer);
        next.add(layer.name);
      }
      return next;
    });
  }

  // -------------------------------------------------------------------------
  // Render.
  // -------------------------------------------------------------------------

  return (
    <div className="-m-6 flex h-[calc(100vh-4rem)] min-h-[600px] bg-[#0b1220] text-slate-100">
      {/* Layer toggles */}
      <aside className="flex w-72 flex-col border-r border-slate-800 bg-[#1A1816]">
        <div className="border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Globe size={16} />
            <span>Lagebild-Layer</span>
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            UC4 · Sovereign Proxy A/B/C
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-2 py-3">
          {DOMAIN_ORDER.map((domain) => {
            const group = layersByDomain[domain];
            if (!group || group.length === 0) return null;
            return (
              <div key={domain} className="mb-4">
                <div className="px-2 pb-1 text-[10px] uppercase tracking-wider text-slate-500">
                  {DOMAIN_LABELS[domain]}
                </div>
                {group.map((layer) => (
                  <LayerToggleRow
                    key={layer.name}
                    layer={layer}
                    enabled={enabledLayers.has(layer.name)}
                    count={counts[layer.name] ?? 0}
                    onToggle={() => toggleLayer(layer)}
                  />
                ))}
              </div>
            );
          })}
        </div>
      </aside>

      {/* Cesium canvas */}
      <div className="relative flex-1">
        <div ref={containerRef} className="absolute inset-0" />
      </div>

      {/* Intel panel */}
      <aside className="flex w-80 flex-col border-l border-slate-800 bg-[#1A1816]">
        <div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold text-white">
          Intel-Panel
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {intel ? (
            <IntelPanelBody intel={intel} />
          ) : (
            <div className="text-xs text-slate-500">
              Klicken Sie auf eine Entität in der Karte, um Detail-Metadaten
              anzuzeigen.
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components.
// ---------------------------------------------------------------------------

interface LayerToggleRowProps {
  layer: CesiumLayer;
  enabled: boolean;
  count: number;
  onToggle: () => void;
}

function LayerToggleRow({
  layer,
  enabled,
  count,
  onToggle,
}: LayerToggleRowProps) {
  const cls = labelColor(layer.defaultClassification);
  return (
    <button
      type="button"
      onClick={onToggle}
      className={[
        'mb-1 flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors',
        enabled
          ? 'bg-[#C74634] text-white'
          : 'text-slate-300 hover:bg-slate-800 hover:text-white',
      ].join(' ')}
    >
      <span className="flex flex-col">
        <span className="font-medium">{layer.label}</span>
        <span className="text-[10px] uppercase tracking-wider text-slate-400">
          Pattern {layer.pattern}
        </span>
      </span>
      <span className="flex items-center gap-2">
        {enabled && count > 0 && (
          <span className="rounded bg-black/30 px-1.5 py-0.5 text-[10px]">
            {count}
          </span>
        )}
        <span
          className={[
            'rounded border px-1.5 py-0.5 text-[10px] font-semibold',
            cls.bg,
            cls.fg,
            cls.border,
          ].join(' ')}
        >
          {numericToLabel(layer.defaultClassification)}
        </span>
      </span>
    </button>
  );
}

function IntelPanelBody({ intel }: { intel: ClickInspectMeta }) {
  const cls = labelColor(intel.classification);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-wider text-slate-500">
          {intel.type}
        </div>
        <span
          className={[
            'rounded border px-1.5 py-0.5 text-[10px] font-semibold',
            cls.bg,
            cls.fg,
            cls.border,
          ].join(' ')}
        >
          {numericToLabel(intel.classification)}
        </span>
      </div>
      <div className="rounded-md border border-slate-800 bg-slate-900/50 p-2 text-xs">
        <div className="text-slate-400">Position</div>
        <div className="font-mono text-slate-100">
          {intel.lat.toFixed(4)}°, {intel.lon.toFixed(4)}°
        </div>
      </div>
      <div className="rounded-md border border-slate-800 bg-slate-900/50">
        <div className="border-b border-slate-800 px-2 py-1 text-[10px] uppercase tracking-wider text-slate-500">
          Metadaten
        </div>
        <ul className="divide-y divide-slate-800">
          {intel.meta.map((item: ClickInspectMetaItem, i) => (
            <li key={i} className="flex justify-between px-2 py-1 text-xs">
              <span className="text-slate-400">{item.key}</span>
              <span className="text-slate-100">{String(item.val)}</span>
            </li>
          ))}
        </ul>
      </div>
      {intel.sources.length > 0 && (
        <div className="rounded-md border border-slate-800 bg-slate-900/50 p-2 text-[11px]">
          <div className="text-slate-400">Quellen</div>
          <ul className="mt-1 list-disc pl-4 text-slate-300">
            {intel.sources.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default LagebildView;
