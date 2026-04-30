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
import type { ScNode } from '../types';

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
    </section>
  );
}

export default SupplyChainView;
