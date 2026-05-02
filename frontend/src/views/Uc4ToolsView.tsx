/**
 * UC4 Tools View — direct ORDS-tool consumer (Tag 8).
 *
 * Demonstrates the live OLS-cap propagation by switching X-OLS-Label-Max
 * across three personas and watching the visible row counts change. Two
 * panels:
 *
 *   1. Multi-correlation entities (graph_query / multi_source_entity).
 *      The Shadow-Fleet network from the demo seed surfaces here.
 *   2. Spatial heatmap (spatial_aggregate).  H3-bucket centroids drawn as
 *      Leaflet circle markers, sized by event_count.
 *
 * The agent (Tag 7) and vector_hybrid_search (BLOCKED on embeddings) get
 * a small status card explaining why they're not wired here today.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
} from 'react-leaflet';
import type { LatLngBoundsExpression } from 'leaflet';
import { AlertTriangle, Database, Map as MapIcon, Network, Shield } from 'lucide-react';
import {
  graphQuery,
  spatialAggregate,
  ToolError,
  type GraphQueryData,
  type H3BucketFeature,
  type MultiSourceEntity,
  type OlsLabel,
  type SpatialAggregateData,
  type ToolResponse,
} from '../services/uc4Tools';

// Default Leaflet view — Mitteleuropa, matches GeointView convention so
// operators don't get tossed onto a Russland-zoomed default.
const DEFAULT_CENTER: [number, number] = [55.0, 18.0];
const DEFAULT_ZOOM = 5;

const PERSONAS: { value: OlsLabel; label: string; rowsHint: string }[] = [
  { value: 'OFFEN',  label: 'OFFEN (10)',  rowsHint: 'public OSINT' },
  { value: 'INTERN', label: 'INTERN (30)', rowsHint: 'Reserve-Force' },
  { value: 'NFD',    label: 'NFD (50)',    rowsHint: 'Active-Force' },
];

// -----------------------------------------------------------------------------
// Map viewport reset — re-fits to bucket bounds when the heatmap changes.
// -----------------------------------------------------------------------------
function MapBoundsController({ buckets }: { buckets: H3BucketFeature[] }) {
  const map = useMap();
  if (buckets.length > 0) {
    let minLat = +Infinity, minLon = +Infinity, maxLat = -Infinity, maxLon = -Infinity;
    for (const b of buckets) {
      const [lon, lat] = b.geometry.coordinates;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
    }
    if (Number.isFinite(minLat) && Number.isFinite(minLon)) {
      const bounds: LatLngBoundsExpression = [
        [minLat, minLon],
        [maxLat, maxLon],
      ];
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 });
    }
  } else {
    map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  }
  return null;
}

// -----------------------------------------------------------------------------
// Bucket marker — radius scales with event_count
// -----------------------------------------------------------------------------
function BucketMarker({ feature }: { feature: H3BucketFeature }) {
  const { properties: p, geometry } = feature;
  const [lon, lat] = geometry.coordinates;
  const radius = Math.min(28, 8 + Math.sqrt(p.event_count) * 4);
  return (
    <CircleMarker
      center={[lat, lon]}
      radius={radius}
      pathOptions={{
        color: '#C74634',
        weight: 2,
        fillColor: '#C74634',
        fillOpacity: 0.25,
      }}
    >
      <Popup>
        <div className="space-y-1 text-xs">
          <div className="font-mono font-semibold">{p.h3_cell}</div>
          <div>Ereignisse: <strong>{p.event_count}</strong></div>
          <div>Quellen-Typen: {p.variety}</div>
          <div className="text-slate-500">
            {lat.toFixed(3)}°N, {lon.toFixed(3)}°E
          </div>
        </div>
      </Popup>
    </CircleMarker>
  );
}

// -----------------------------------------------------------------------------
// Persona pill row
// -----------------------------------------------------------------------------
function PersonaPills({
  value,
  onChange,
}: {
  value: OlsLabel;
  onChange: (v: OlsLabel) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="OLS-Cap"
      className="flex items-center gap-2"
    >
      <span className="text-xs uppercase tracking-wider text-slate-500">
        X-OLS-Label-Max
      </span>
      {PERSONAS.map((p) => (
        <button
          key={p.value}
          role="radio"
          aria-checked={value === p.value}
          onClick={() => onChange(p.value)}
          className={[
            'rounded-full px-3 py-1 text-xs font-medium transition-colors',
            value === p.value
              ? 'bg-[#C74634] text-white'
              : 'bg-slate-100 text-slate-700 hover:bg-slate-200',
          ].join(' ')}
        >
          {p.label}
          <span className="ml-1.5 opacity-70">{p.rowsHint}</span>
        </button>
      ))}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Section: multi-correlation entities
// -----------------------------------------------------------------------------
function MultiCorrelationPanel({ cap }: { cap: OlsLabel }) {
  const q = useQuery<ToolResponse<GraphQueryData>, Error>({
    queryKey: ['uc4.graph_query.multi_source_entity', cap],
    queryFn: () =>
      graphQuery(
        {
          pattern: 'multi_source_entity',
          args: { hours: 72, min_correlations: 2 },
        },
        cap,
      ),
  });

  const entities: MultiSourceEntity[] = useMemo(() => {
    const data = q.data?.data;
    if (!data || !('entities' in data) || data.entities == null) return [];
    return data.entities;
  }, [q.data]);

  return (
    <section
      data-testid="uc4-multi-corr"
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Network size={16} className="text-[#C74634]" />
          <h3 className="text-sm font-semibold text-slate-900">
            Multi-Korrelations-Entities
          </h3>
        </div>
        <span className="text-xs text-slate-500">
          letzte 72h · ≥2 Korrelationen
        </span>
      </header>

      {q.isLoading && (
        <div className="mt-4 text-xs text-slate-500">Lade graph_query…</div>
      )}
      {q.isError && (
        <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
          Fehler: {(q.error as ToolError | Error).message}
        </div>
      )}
      {q.isSuccess && entities.length === 0 && (
        <div className="mt-4 text-xs text-slate-500">
          Keine Entities mit ≥2 Korrelationen sichtbar bei Cap {cap}.
        </div>
      )}
      {q.isSuccess && entities.length > 0 && (
        <table className="mt-3 w-full text-left text-xs" role="table">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1.5 pr-2">Typ</th>
              <th className="py-1.5 pr-2">Bezeichnung</th>
              <th className="py-1.5 pr-2 font-mono">Canonical ID</th>
              <th className="py-1.5 text-right">Korrelationen</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-slate-800">
            {entities.map((e) => (
              <tr key={e.entity_id} data-testid="uc4-multi-corr-row">
                <td className="py-1.5 pr-2">
                  <EntityKindBadge kind={e.entity_kind} />
                </td>
                <td className="py-1.5 pr-2 font-medium">{e.display_name}</td>
                <td className="py-1.5 pr-2 font-mono text-slate-500">
                  {e.canonical_id}
                </td>
                <td className="py-1.5 text-right tabular-nums font-semibold text-[#C74634]">
                  {e.corr_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {q.data && (
        <footer className="mt-3 flex items-center justify-between text-[11px] text-slate-400">
          <span>
            request {q.data.request_id.slice(0, 8)} ·{' '}
            {q.data.duration_ms.toFixed(0)} ms
          </span>
          <span>
            cap applied: <strong>{q.data.ols_cap_label}</strong>
          </span>
        </footer>
      )}
    </section>
  );
}

function EntityKindBadge({ kind }: { kind: string }) {
  const palette: Record<string, string> = {
    vessel: 'bg-blue-100 text-blue-800',
    aircraft: 'bg-sky-100 text-sky-800',
    actor: 'bg-amber-100 text-amber-800',
    location: 'bg-emerald-100 text-emerald-800',
    satellite: 'bg-purple-100 text-purple-800',
    emitter: 'bg-rose-100 text-rose-800',
  };
  const cls = palette[kind] ?? 'bg-slate-100 text-slate-700';
  return (
    <span
      className={['rounded px-1.5 py-0.5 text-[10px] font-bold uppercase', cls].join(' ')}
    >
      {kind}
    </span>
  );
}

// -----------------------------------------------------------------------------
// Section: spatial heatmap
// -----------------------------------------------------------------------------
function SpatialHeatmapPanel({ cap }: { cap: OlsLabel }) {
  const q = useQuery<ToolResponse<SpatialAggregateData>, Error>({
    queryKey: ['uc4.spatial_aggregate', cap],
    queryFn: () =>
      spatialAggregate(
        {
          h3_resolution: 5,
          hours: 72,
          min_events: 2,
          bbox: { min_lat: 53, max_lat: 58, min_lon: 13, max_lon: 23 },
        },
        cap,
      ),
  });

  const features: H3BucketFeature[] = useMemo(() => {
    const data = q.data?.data;
    if (!data || data.features == null) return [];
    return data.features;
  }, [q.data]);

  return (
    <section
      data-testid="uc4-spatial-heatmap"
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MapIcon size={16} className="text-[#C74634]" />
          <h3 className="text-sm font-semibold text-slate-900">
            H3-Bucket-Heatmap
          </h3>
        </div>
        <span className="text-xs text-slate-500">
          Ostsee · 72h · min 2 Events
        </span>
      </header>

      <div className="relative mt-3 h-[360px] overflow-hidden rounded-lg border border-slate-200">
        <MapContainer
          center={DEFAULT_CENTER}
          zoom={DEFAULT_ZOOM}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap"
          />
          <MapBoundsController buckets={features} />
          {features.map((f) => (
            <BucketMarker key={f.properties.h3_cell} feature={f} />
          ))}
        </MapContainer>
      </div>

      {q.data && (
        <footer className="mt-3 flex items-center justify-between text-[11px] text-slate-400">
          <span>
            {features.length} buckets · {q.data.duration_ms.toFixed(0)} ms
          </span>
          <span>
            cap applied: <strong>{q.data.ols_cap_label}</strong>
          </span>
        </footer>
      )}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Section: agent + vector status (deferred)
// -----------------------------------------------------------------------------
function StatusPanel() {
  return (
    <section
      data-testid="uc4-status-panel"
      className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900"
    >
      <header className="flex items-center gap-2">
        <AlertTriangle size={14} />
        <h3 className="text-sm font-semibold">Aktueller Reife-Stand</h3>
      </header>
      <ul className="mt-2 space-y-1.5">
        <li className="flex items-start gap-2">
          <Database size={12} className="mt-0.5 shrink-0" />
          <span>
            <strong>graph_query</strong>, <strong>spatial_aggregate</strong>,
            <strong> persist_briefing</strong> live über ORDS — siehe Tabellen
            oben.
          </span>
        </li>
        <li className="flex items-start gap-2">
          <Shield size={12} className="mt-0.5 shrink-0" />
          <span>
            <strong>vector_hybrid_search</strong> antwortet 503 bis Embeddings
            befüllt sind (siehe <code>02_compute_embeddings.sql</code>).
          </span>
        </li>
        <li className="flex items-start gap-2">
          <Shield size={12} className="mt-0.5 shrink-0" />
          <span>
            <strong>Threat-Fusion-Agent</strong> deploy-blocked auf Cohere
            Cluster + ORDS-OAuth. Korrelations-Detektor + TxEventQ-Trigger
            laufen, Queue ist gefüllt mit Tag 7c-Patterns.
          </span>
        </li>
      </ul>
    </section>
  );
}

// -----------------------------------------------------------------------------
// Top-level view
// -----------------------------------------------------------------------------
export function Uc4ToolsView() {
  const [cap, setCap] = useState<OlsLabel>('NFD');

  return (
    <section className="space-y-4">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            UC4 OSINT — Tools-Konsole
          </h2>
          <p className="text-sm text-slate-600">
            Direkter Zugriff auf die vier ORDS-Tools (Tag 6).
            Persona-Auswahl steuert den App-Layer-OLS-Cap (Tag 3b).
          </p>
        </div>
        <PersonaPills value={cap} onChange={setCap} />
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <MultiCorrelationPanel cap={cap} />
        <SpatialHeatmapPanel cap={cap} />
      </div>

      <StatusPanel />
    </section>
  );
}

export default Uc4ToolsView;
