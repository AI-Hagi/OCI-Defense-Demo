import { useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MapContainer, Polygon, Popup, TileLayer } from 'react-leaflet';
import { Upload, Satellite as SatelliteIcon } from 'lucide-react';
import type { LatLngTuple } from 'leaflet';
import { geoint } from '../services/api';
import type { SatelliteScene } from '../types';

// Convert a GeoJSON Polygon (lon/lat) into Leaflet LatLngTuple[] (lat/lon) rings.
function polygonToLatLngs(scene: SatelliteScene): LatLngTuple[][] | null {
  const poly = scene.footprint;
  if (!poly || poly.type !== 'Polygon') return null;
  return poly.coordinates.map((ring) =>
    ring.map(([lon, lat]) => [lat, lon] as LatLngTuple),
  );
}

function SkeletonCard() {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-slate-100/60 backdrop-blur-sm">
      <div className="rounded-xl border border-slate-200 bg-white px-6 py-4 text-sm text-slate-600 shadow-sm">
        Lade Satellitenszenen...
      </div>
    </div>
  );
}

function ErrorCard({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : 'Unbekannter Fehler';
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-slate-100/60">
      <div className="rounded-xl border border-rose-200 bg-white px-6 py-4 text-sm text-rose-700 shadow-sm">
        Fehler beim Laden der Szenen: {message}
      </div>
    </div>
  );
}

export function GeointView() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<File | null>(null);

  const scenesQuery = useQuery({
    queryKey: ['geoint.scenes'],
    queryFn: () => geoint.listScenes(),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => geoint.uploadScene(file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['geoint.scenes'] });
      setSelected(null);
      if (fileRef.current) fileRef.current.value = '';
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (selected) uploadMutation.mutate(selected);
  };

  const scenes = scenesQuery.data ?? [];

  return (
    <section className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            Satellitenszenen
          </h2>
          <p className="text-sm text-slate-600">
            YOLOv8-Detektionen mit WGS84-Footprint in Oracle 26ai Vector.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-600">
          <SatelliteIcon size={16} />
          {scenes.length} Szenen
        </div>
      </header>

      <div className="relative h-[70vh] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <MapContainer
          center={[52, 10] as LatLngTuple}
          zoom={4}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; OpenStreetMap'
          />
          {scenes.map((scene) => {
            const latlngs = polygonToLatLngs(scene);
            if (!latlngs) return null;
            return (
              <Polygon
                key={scene.scene_id}
                positions={latlngs}
                pathOptions={{
                  color: '#C74634',
                  weight: 2,
                  fillColor: '#C74634',
                  fillOpacity: 0.18,
                }}
              >
                <Popup>
                  <div className="space-y-1 text-xs">
                    <div className="font-semibold">{scene.sensor}</div>
                    <div>
                      {new Date(scene.captured_at).toLocaleString('de-DE')}
                    </div>
                    {scene.cloud_cover != null && (
                      <div>Wolkendecke: {scene.cloud_cover}%</div>
                    )}
                    {scene.yolo_detections?.length ? (
                      <div>
                        Detektionen: {scene.yolo_detections.length}
                      </div>
                    ) : null}
                  </div>
                </Popup>
              </Polygon>
            );
          })}
        </MapContainer>

        {/* Floating upload card */}
        <form
          onSubmit={handleSubmit}
          className="absolute right-4 top-4 z-[400] w-72 space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-lg"
        >
          <div>
            <div className="text-sm font-semibold text-slate-900">
              Szene hochladen
            </div>
            <div className="text-xs text-slate-500">TIFF oder JPEG</div>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/tiff,image/jpeg"
            onChange={(e) => setSelected(e.target.files?.[0] ?? null)}
            className="block w-full text-xs text-slate-700 file:mr-2 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white hover:file:bg-slate-800"
          />
          <button
            type="submit"
            disabled={!selected || uploadMutation.isPending}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-[#C74634] px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#A33A2C] disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            <Upload size={14} />
            {uploadMutation.isPending ? 'Hochladen...' : 'Hochladen'}
          </button>
          {uploadMutation.isError && (
            <div className="text-xs text-rose-700">
              Upload fehlgeschlagen.
            </div>
          )}
          {uploadMutation.isSuccess && (
            <div className="text-xs text-emerald-700">
              Szene erfolgreich ingestiert.
            </div>
          )}
        </form>

        {scenesQuery.isLoading && <SkeletonCard />}
        {scenesQuery.isError && <ErrorCard error={scenesQuery.error} />}
      </div>
    </section>
  );
}

export default GeointView;
