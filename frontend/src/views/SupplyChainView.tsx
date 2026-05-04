import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { LatLngTuple } from 'leaflet';
import { sc } from '../services/api';
import type { ScEdge, ScEdgeType, ScNode, ScNodeType, ScRiskPoint } from '../types';

// Interpolate a red->amber->green colour based on a 0-100 risk score.
function riskColour(score: number | null | undefined): string {
  if (score == null) return '#94a3b8';
  const clamped = Math.max(0, Math.min(100, score));
  // 0 (low risk) = green, 100 (high risk) = red.
  if (clamped < 33) return '#10b981';
  if (clamped < 66) return '#f59e0b';
  return '#dc2626';
}

function markerRadius(criticality: number): number {
  // 6..18 px depending on criticality (0..100).
  return 6 + (criticality / 100) * 12;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('de-DE', {
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return iso;
  }
}

export function SupplyChainView() {
  const [selectedNode, setSelectedNode] = useState<ScNode | null>(null);

  const nodesQuery = useQuery({
    queryKey: ['sc.nodes'],
    queryFn: () => sc.nodes(),
  });

  // Pull all edges once — the narrative panel summarises edge-types and the
  // detail panel uses them to render in/out neighbours of the selected node.
  const edgesQuery = useQuery({
    queryKey: ['sc.edges'],
    queryFn: () => sc.edges(),
  });

  const riskQuery = useQuery({
    queryKey: ['sc.risk', selectedNode?.node_id],
    queryFn: () =>
      selectedNode ? sc.risk(selectedNode.node_id) : Promise.resolve([]),
    enabled: !!selectedNode,
  });

  const riskSeries = useMemo(() => {
    const rows = riskQuery.data ?? [];
    return rows
      .slice(-30)
      .map((p) => ({ date: formatDate(p.as_of), score: p.risk_score }));
  }, [riskQuery.data]);

  const nodes = nodesQuery.data ?? [];
  const edges = edgesQuery.data ?? [];
  const riskRows = riskQuery.data ?? [];

  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold text-slate-900">
          Lieferketten-Graph
        </h2>
        <p className="text-sm text-slate-600">
          Kritikalität als Markergröße, Risikoscore als Farbverlauf (grün →
          rot).
        </p>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Left: map */}
        <div className="relative h-[70vh] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <MapContainer
            center={[50, 10] as LatLngTuple}
            zoom={3}
            style={{ height: '100%', width: '100%' }}
            scrollWheelZoom
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution="&copy; OpenStreetMap"
            />
            {nodes
              .filter((n) => n.latitude != null && n.longitude != null)
              .map((n) => (
                <CircleMarker
                  key={n.node_id}
                  center={[n.latitude as number, n.longitude as number]}
                  radius={markerRadius(n.criticality)}
                  pathOptions={{
                    color: riskColour(n.latest_risk_score),
                    fillColor: riskColour(n.latest_risk_score),
                    fillOpacity: selectedNode?.node_id === n.node_id ? 0.85 : 0.55,
                    weight: selectedNode?.node_id === n.node_id ? 3 : 1.5,
                  }}
                  eventHandlers={{ click: () => setSelectedNode(n) }}
                >
                  <Popup>
                    <div className="text-xs">
                      <div className="font-semibold">{n.display_name}</div>
                      <div>
                        {n.node_type} · {n.country_iso3}
                      </div>
                      <div>Kritikalität: {n.criticality}</div>
                      {n.latest_risk_score != null && (
                        <div>Risiko: {n.latest_risk_score.toFixed(1)}</div>
                      )}
                    </div>
                  </Popup>
                </CircleMarker>
              ))}
          </MapContainer>
          {nodesQuery.isLoading && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-slate-100/60 text-sm text-slate-600">
              Lade Knoten...
            </div>
          )}
          {nodesQuery.isError && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-slate-100/60 text-sm text-rose-700">
              Fehler beim Laden der Knoten.
            </div>
          )}
        </div>

        {/* Right: chart */}
        <div className="flex h-[70vh] flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold text-slate-900">
              Risikoverlauf (30 Tage)
            </h3>
            <div className="text-xs text-slate-500">
              {selectedNode
                ? `${selectedNode.display_name} · ${selectedNode.country_iso3}`
                : 'Kein Knoten gewählt'}
            </div>
          </div>

          <div className="mt-4 flex-1">
            {!selectedNode ? (
              <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500">
                Knoten auf der Karte auswählen.
              </div>
            ) : riskQuery.isLoading ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                Lade Risikodaten...
              </div>
            ) : riskQuery.isError ? (
              <div className="flex h-full items-center justify-center text-sm text-rose-700">
                Fehler beim Laden der Risikodaten.
              </div>
            ) : riskSeries.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                Keine Risikohistorie verfügbar.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={riskSeries}
                  margin={{ top: 10, right: 20, bottom: 10, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis
                    dataKey="date"
                    stroke="#64748b"
                    fontSize={11}
                    tickMargin={6}
                  />
                  <YAxis
                    domain={[0, 100]}
                    stroke="#64748b"
                    fontSize={11}
                    tickMargin={6}
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 8,
                      borderColor: '#e2e8f0',
                      fontSize: 12,
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#C74634"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      <SupplyChainNarrativePanel
        nodes={nodes}
        edges={edges}
        loading={nodesQuery.isLoading || edgesQuery.isLoading}
        error={nodesQuery.isError || edgesQuery.isError}
      />

      <SupplyChainDetailPanel
        node={selectedNode}
        nodes={nodes}
        edges={edges}
        riskRows={riskRows}
        riskLoading={riskQuery.isLoading}
        riskError={riskQuery.isError}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helper labels — the SC schema is English; UI is German per project rules.
// ---------------------------------------------------------------------------
const NODE_TYPE_LABEL: Record<ScNodeType, string> = {
  supplier: 'Zulieferer',
  hub: 'Logistik-Hub',
  mine: 'Rohstoff-Mine',
  port: 'Hafen',
  factory: 'Werk',
};

const EDGE_TYPE_LABEL: Record<ScEdgeType, string> = {
  ships_to: 'liefert an',
  supplies: 'beliefert mit',
  transports: 'transportiert',
  depends_on: 'abhängig von',
  owned_by: 'gehört zu',
};

const NODE_TYPE_COLOR: Record<ScNodeType, string> = {
  supplier: '#1f7a8c',
  hub: '#0f4c81',
  mine: '#b08968',
  port: '#264653',
  factory: '#C74634',
};

function riskBucket(score: number | null | undefined): 'niedrig' | 'mittel' | 'hoch' | 'unbekannt' {
  if (score == null) return 'unbekannt';
  if (score < 33) return 'niedrig';
  if (score < 66) return 'mittel';
  return 'hoch';
}

// ---------------------------------------------------------------------------
// SupplyChainNarrativePanel — sits under the map+chart grid and explains what
// the operator is currently looking at: counts per node-type + country + risk
// bucket, edge-type breakdown, and a short narrative on the chain semantics.
// ---------------------------------------------------------------------------
interface NarrativePanelProps {
  nodes: ScNode[];
  edges: ScEdge[];
  loading: boolean;
  error: boolean;
}

function SupplyChainNarrativePanel({ nodes, edges, loading, error }: NarrativePanelProps) {
  const typeCounts = useMemo(() => {
    const counts: Partial<Record<ScNodeType, number>> = {};
    for (const n of nodes) counts[n.node_type] = (counts[n.node_type] ?? 0) + 1;
    return Object.entries(counts).sort((a, b) => b[1]! - a[1]!) as [ScNodeType, number][];
  }, [nodes]);

  const countryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of nodes) {
      const c = n.country_iso3 || '???';
      counts[c] = (counts[c] ?? 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [nodes]);

  const riskBuckets = useMemo(() => {
    const buckets = { niedrig: 0, mittel: 0, hoch: 0, unbekannt: 0 };
    for (const n of nodes) buckets[riskBucket(n.latest_risk_score)] += 1;
    return buckets;
  }, [nodes]);

  const edgeTypeCounts = useMemo(() => {
    const counts: Partial<Record<ScEdgeType, number>> = {};
    for (const e of edges) counts[e.edge_type] = (counts[e.edge_type] ?? 0) + 1;
    return Object.entries(counts).sort((a, b) => b[1]! - a[1]!) as [ScEdgeType, number][];
  }, [edges]);

  return (
    <section
      data-testid="sc-narrative"
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">
          Lagebild-Beschreibung — was wird hier gezeigt?
        </h3>
        <span className="text-[11px] text-slate-500">
          {nodes.length} Knoten · {edges.length} Kanten
        </span>
      </header>

      {loading && <p className="mt-3 text-xs text-slate-500">Lade Beschreibung…</p>}
      {error && (
        <p className="mt-3 text-xs text-rose-700">
          Beschreibung kann nicht geladen werden — /sc/nodes oder /sc/edges nicht erreichbar.
        </p>
      )}

      {!loading && !error && (
        <div className="mt-4 grid gap-5 lg:grid-cols-3">
          <div className="space-y-3">
            <div className="text-xs uppercase tracking-wider text-slate-500">
              Knoten nach Typ
            </div>
            <ul className="space-y-1.5">
              {typeCounts.map(([t, n]) => (
                <li key={t} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: NODE_TYPE_COLOR[t] }}
                    />
                    <span className="font-medium text-slate-800">{NODE_TYPE_LABEL[t] ?? t}</span>
                  </span>
                  <span className="font-mono text-slate-600">{n}</span>
                </li>
              ))}
            </ul>

            <div className="mt-4 text-xs uppercase tracking-wider text-slate-500">
              Risiko-Verteilung
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(['hoch', 'mittel', 'niedrig', 'unbekannt'] as const).map((bk) => (
                <span
                  key={bk}
                  className={[
                    'rounded-md px-2 py-0.5 text-[10px] font-mono',
                    bk === 'hoch'
                      ? 'bg-rose-100 text-rose-800'
                      : bk === 'mittel'
                      ? 'bg-amber-100 text-amber-800'
                      : bk === 'niedrig'
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-slate-100 text-slate-600',
                  ].join(' ')}
                >
                  {bk} ×{riskBuckets[bk]}
                </span>
              ))}
            </div>

            <div className="mt-4 text-xs uppercase tracking-wider text-slate-500">
              Top-Länder
            </div>
            <div className="flex flex-wrap gap-1.5">
              {countryCounts.map(([c, n]) => (
                <span
                  key={c}
                  className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-700"
                >
                  {c} ×{n}
                </span>
              ))}
            </div>
          </div>

          <div className="space-y-2 text-xs leading-relaxed text-slate-700 lg:col-span-2">
            <div className="text-xs uppercase tracking-wider text-slate-500">
              Worum geht es?
            </div>
            <p>
              Der Knowledge-Graph in <span className="font-mono">UC5_supply_chain</span>{' '}
              auf Oracle 26ai modelliert die Rüstungs-Lieferkette als gerichtetes
              Netz. <strong>Knoten</strong> sind physische Standorte (Werke,
              Häfen, Hubs, Minen, Zulieferer); ihre Markergröße auf der Karte
              skaliert mit <em>Kritikalität</em> (0–100), die Farbe codiert den
              aggregierten <em>Risk-Score</em>{' '}
              (<span className="text-emerald-700">grün &lt; 33</span> ·{' '}
              <span className="text-amber-700">gelb 33–65</span> ·{' '}
              <span className="text-rose-700">rot ≥ 66</span>).
            </p>
            <p>
              <strong>Kanten</strong> sind nachvollziehbare Material-/Eigentums-
              beziehungen — ihre Aggregation pro Typ:
            </p>
            <div className="flex flex-wrap gap-1.5">
              {edgeTypeCounts.length === 0 ? (
                <span className="text-slate-400">keine Kanten geladen</span>
              ) : (
                edgeTypeCounts.map(([t, n]) => (
                  <span
                    key={t}
                    className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-700"
                  >
                    {EDGE_TYPE_LABEL[t] ?? t} <span className="opacity-70">×{n}</span>
                  </span>
                ))
              )}
            </div>
            <p>
              Der <strong>Risk-Score</strong> wird täglich neu berechnet aus
              vier Buckets — <span className="font-mono">geopolitical</span>,{' '}
              <span className="font-mono">sanctions</span>,{' '}
              <span className="font-mono">weather</span>,{' '}
              <span className="font-mono">cyber</span> — und über eine
              gewichtete Funktion zum Aggregat verdichtet. Klick auf einen
              Knoten lädt 30 Tage Risk-Verlauf und die letzte Bucket-
              Aufschlüsselung.
            </p>
            <div className="mt-3 grid grid-cols-1 gap-2 rounded-md bg-slate-50 p-3 text-[11px] text-slate-600 sm:grid-cols-3">
              <span>
                <strong className="text-slate-800">Markergröße</strong> →
                Kritikalität (0–100)
              </span>
              <span>
                <strong className="text-slate-800">Markerfarbe</strong> →
                aktueller Risk-Score-Bucket
              </span>
              <span>
                <strong className="text-slate-800">Klick</strong> → Detail-
                Karte + 30-Tage-Risk-Chart
              </span>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// SupplyChainDetailPanel — only renders when a node is selected. Surfaces
// the node's static metadata (type, country, criticality, risk bucket), the
// most recent risk-bucket breakdown, and the in/out edges so the operator
// sees the dependency neighbourhood at a glance.
// ---------------------------------------------------------------------------
interface DetailPanelProps {
  node: ScNode | null;
  nodes: ScNode[];
  edges: ScEdge[];
  riskRows: ScRiskPoint[];
  riskLoading: boolean;
  riskError: boolean;
}

function SupplyChainDetailPanel({
  node,
  nodes,
  edges,
  riskRows,
  riskLoading,
  riskError,
}: DetailPanelProps) {
  const nodeById = useMemo(() => {
    const m = new Map<string, ScNode>();
    for (const n of nodes) m.set(n.node_id, n);
    return m;
  }, [nodes]);

  const incoming = useMemo(
    () => (node ? edges.filter((e) => e.dst_node === node.node_id) : []),
    [edges, node],
  );
  const outgoing = useMemo(
    () => (node ? edges.filter((e) => e.src_node === node.node_id) : []),
    [edges, node],
  );

  const latestRisk = useMemo(() => {
    if (!riskRows.length) return null;
    return [...riskRows].sort(
      (a, b) => new Date(b.as_of).getTime() - new Date(a.as_of).getTime(),
    )[0];
  }, [riskRows]);

  if (!node) {
    return (
      <section
        data-testid="sc-detail-empty"
        className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-xs text-slate-500"
      >
        <strong className="text-slate-700">Detail-Karte:</strong> Klicken Sie
        einen Knoten auf der Karte an, um Stammdaten, Risk-Bucket-
        Aufschlüsselung und ein-/ausgehende Lieferketten-Beziehungen zu sehen.
      </section>
    );
  }

  const bucket = riskBucket(node.latest_risk_score);

  return (
    <section
      data-testid="sc-detail"
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500">
            Detail-Karte
          </div>
          <h3 className="text-base font-semibold text-slate-900">
            {node.display_name}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="rounded-md px-2 py-0.5 text-[10px] font-mono"
            style={{
              backgroundColor: `${NODE_TYPE_COLOR[node.node_type]}22`,
              color: NODE_TYPE_COLOR[node.node_type],
            }}
          >
            {NODE_TYPE_LABEL[node.node_type] ?? node.node_type}
          </span>
          <span
            className={[
              'rounded-md px-2 py-0.5 text-[10px] font-mono',
              bucket === 'hoch'
                ? 'bg-rose-100 text-rose-800'
                : bucket === 'mittel'
                ? 'bg-amber-100 text-amber-800'
                : bucket === 'niedrig'
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-slate-100 text-slate-600',
            ].join(' ')}
          >
            Risiko: {bucket}
            {node.latest_risk_score != null && ` · ${node.latest_risk_score.toFixed(1)}`}
          </span>
        </div>
      </header>

      <div className="mt-4 grid gap-5 lg:grid-cols-3">
        <div className="space-y-2 text-xs">
          <div className="text-xs uppercase tracking-wider text-slate-500">Stammdaten</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-slate-700">
            <dt className="text-slate-500">Land</dt>
            <dd className="font-mono">{node.country_iso3}</dd>
            <dt className="text-slate-500">Kritikalität</dt>
            <dd className="font-mono">{node.criticality}/100</dd>
            <dt className="text-slate-500">Position</dt>
            <dd className="font-mono">
              {node.latitude != null && node.longitude != null
                ? `${node.latitude.toFixed(2)}°N / ${node.longitude.toFixed(2)}°E`
                : '—'}
            </dd>
            <dt className="text-slate-500">OLS-Label</dt>
            <dd className="font-mono">{node.ols_label ?? '—'}</dd>
            <dt className="text-slate-500">Node-ID</dt>
            <dd className="font-mono text-[10px] text-slate-500">
              {node.node_id.slice(0, 12)}…
            </dd>
          </dl>
        </div>

        <div className="space-y-2 text-xs">
          <div className="text-xs uppercase tracking-wider text-slate-500">
            Letzter Risk-Bucket
          </div>
          {riskLoading ? (
            <p className="text-slate-500">Lade Risikodaten…</p>
          ) : riskError ? (
            <p className="text-rose-700">Risikodaten nicht verfügbar.</p>
          ) : !latestRisk ? (
            <p className="text-slate-500">Keine Risikohistorie verfügbar.</p>
          ) : (
            <>
              <p className="text-[11px] text-slate-500">
                Stand{' '}
                <span className="font-mono">
                  {new Date(latestRisk.as_of).toLocaleDateString('de-DE')}
                </span>{' '}
                · Aggregat{' '}
                <span className="font-semibold text-slate-700">
                  {latestRisk.risk_score?.toFixed(1) ?? '—'}
                </span>
              </p>
              <ul className="mt-1 space-y-1.5">
                {Object.entries(latestRisk.risk_breakdown ?? {}).map(([bk, val]) => {
                  const num = typeof val === 'string' ? Number(val) : (val as number);
                  return (
                    <li key={bk} className="flex items-center gap-2 text-[11px]">
                      <span className="w-20 capitalize text-slate-600">{bk}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full bg-[#C74634]"
                          style={{ width: `${Math.min(100, Math.max(0, num))}%` }}
                        />
                      </div>
                      <span className="w-10 text-right font-mono text-slate-700">
                        {Number.isFinite(num) ? num.toFixed(0) : '—'}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>

        <div className="space-y-2 text-xs">
          <div className="text-xs uppercase tracking-wider text-slate-500">
            Lieferketten-Nachbarn
          </div>
          {incoming.length === 0 && outgoing.length === 0 ? (
            <p className="text-slate-500">Keine direkten Kanten — der Knoten ist isoliert.</p>
          ) : (
            <>
              {incoming.length > 0 && (
                <div>
                  <div className="text-[11px] font-semibold text-slate-600">
                    eingehend ({incoming.length})
                  </div>
                  <ul className="mt-1 space-y-1">
                    {incoming.slice(0, 8).map((e) => {
                      const src = nodeById.get(e.src_node);
                      return (
                        <li
                          key={e.edge_id}
                          className="flex items-center justify-between gap-2 truncate"
                        >
                          <span className="truncate text-slate-700">
                            {src?.display_name ?? e.src_node.slice(0, 8) + '…'}
                          </span>
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-600">
                            {EDGE_TYPE_LABEL[e.edge_type] ?? e.edge_type}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
              {outgoing.length > 0 && (
                <div className="mt-3">
                  <div className="text-[11px] font-semibold text-slate-600">
                    ausgehend ({outgoing.length})
                  </div>
                  <ul className="mt-1 space-y-1">
                    {outgoing.slice(0, 8).map((e) => {
                      const dst = nodeById.get(e.dst_node);
                      return (
                        <li
                          key={e.edge_id}
                          className="flex items-center justify-between gap-2 truncate"
                        >
                          <span className="truncate text-slate-700">
                            {dst?.display_name ?? e.dst_node.slice(0, 8) + '…'}
                          </span>
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-600">
                            {EDGE_TYPE_LABEL[e.edge_type] ?? e.edge_type}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

export default SupplyChainView;
