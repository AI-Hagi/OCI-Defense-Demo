import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MapContainer, Polygon, Popup, TileLayer, useMap } from 'react-leaflet';
import { Info, MapPin, Plane, Satellite as SatelliteIcon, Upload, X } from 'lucide-react';
import type { LatLngBoundsExpression, LatLngTuple } from 'leaflet';
import { geoint, type UploadSceneResult } from '../services/api';
import type { PlatformKind, SatelliteScene } from '../types';

// Banner dismissal persists for the browser session only — a fresh tab
// re-shows the hint, but the operator doesn't have to dismiss it on every
// re-render within a working session.
const BANNER_DISMISS_KEY = 'sov:geoint:footprint-hint-dismissed';

// Mitteleuropa-Default — wird genutzt, solange keine Szene mit Footprint
// geladen ist. Verhindert den unbeabsichtigten Russland-Zoom, der bei
// `[52, 10]` + `zoom=4` und ohne Bounds-Fitting durch die Leaflet-CRS-
// Mathematik zustande gekommen ist.
const DEFAULT_CENTER: LatLngTuple = [51.0, 10.0];
const DEFAULT_ZOOM = 5;

// Convert a GeoJSON Polygon (lon/lat) into Leaflet LatLngTuple[] (lat/lon) rings.
function polygonToLatLngs(scene: SatelliteScene): LatLngTuple[][] | null {
  const poly = scene.footprint;
  if (!poly || poly.type !== 'Polygon') return null;
  return poly.coordinates.map((ring) =>
    ring.map(([lon, lat]) => [lat, lon] as LatLngTuple),
  );
}

// Reduce a list of scenes to a [[minLat, minLon], [maxLat, maxLon]] bounding
// box across every polygon ring. Returns null when no scene carries a
// footprint — the caller falls back to the default centre/zoom.
function boundsFromScenes(list: SatelliteScene[]): LatLngBoundsExpression | null {
  let minLat = +Infinity, minLon = +Infinity;
  let maxLat = -Infinity, maxLon = -Infinity;
  let any = false;
  for (const scene of list) {
    const rings = polygonToLatLngs(scene);
    if (!rings) continue;
    for (const ring of rings) {
      for (const [lat, lon] of ring) {
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
          minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
          minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
          any = true;
        }
      }
    }
  }
  if (!any) return null;
  return [[minLat, minLon], [maxLat, maxLon]];
}

/**
 * Embedded map controller: re-fits the Leaflet view to the polygon bounds
 * whenever the scene list changes. When there are no footprints, resets to
 * the default Mitteleuropa view so a previous fit doesn't leave the user
 * stranded over an empty region of map.
 */
function MapBoundsController({ scenes }: { scenes: SatelliteScene[] }) {
  const map = useMap();
  useEffect(() => {
    const bounds = boundsFromScenes(scenes);
    if (bounds) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 9 });
    } else {
      map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    }
  }, [scenes, map]);
  return null;
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

// UC1 multi-source — view filter for satellite-only / UAV-only / both.
type PlatformFilter = 'all' | PlatformKind;

export function GeointView() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<File | null>(null);
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>('all');
  const [uploadKind, setUploadKind] = useState<PlatformKind>('satellite');

  const scenesQuery = useQuery({
    queryKey: ['geoint.scenes'],
    queryFn: () => geoint.listScenes(),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => geoint.uploadScene(file, { platformKind: uploadKind }),
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

  const allScenes = scenesQuery.data ?? [];
  const scenes = useMemo(
    () => (platformFilter === 'all'
      ? allScenes
      : allScenes.filter((s) => s.platform_kind === platformFilter)),
    [allScenes, platformFilter],
  );
  const uavCount = allScenes.filter((s) => s.platform_kind === 'uav').length;
  const satCount = allScenes.length - uavCount;

  // Hint-Banner: zeige nur dann an, wenn Szenen geladen sind und KEINE
  // davon einen WGS84-Footprint mitbringt. Mit der Footprint-Persistenz
  // (commit a12b228) bekommen NEUE Uploads automatisch einen synthetischen
  // Mitteleuropa-Footprint, also wird der Banner nur noch für Bestand-
  // Szenen aus der Vor-Fix-Phase getriggert. Banner ist sitzungsweise
  // ausblendbar (X-Button, sessionStorage) — das Demo-Setup für BMVg /
  // Bundeswehr will die Karte mit klarem Default-View Mitteleuropa zeigen
  // und nicht durchgehend einen Hinweis-Block einblenden.
  const scenesMissingFootprint = useMemo(
    () => scenes.filter((s) => !s.footprint),
    [scenes],
  );
  const allScenesMissingFootprint =
    scenes.length > 0 && scenesMissingFootprint.length === scenes.length;
  const [bannerDismissed, setBannerDismissed] = useState<boolean>(() => {
    if (typeof sessionStorage === 'undefined') return false;
    return sessionStorage.getItem(BANNER_DISMISS_KEY) === '1';
  });
  const showFootprintHint = allScenesMissingFootprint && !bannerDismissed;
  const handleDismissBanner = () => {
    setBannerDismissed(true);
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem(BANNER_DISMISS_KEY, '1');
    }
  };

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
        <div className="flex items-center gap-3 text-sm text-slate-600">
          <PlatformFilterPills
            value={platformFilter}
            onChange={setPlatformFilter}
            satCount={satCount}
            uavCount={uavCount}
          />
          <span className="flex items-center gap-2">
            <SatelliteIcon size={16} />
            {scenes.length} Szenen
          </span>
        </div>
      </header>

      {showFootprintHint && (
        <div
          role="status"
          data-testid="geoint-footprint-hint"
          className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800"
        >
          <Info size={16} className="mt-0.5 shrink-0" />
          <span className="flex-1">
            Hochgeladene Szenen werden mit synthetischen Footprints
            versehen. Für präzise Lagebild-Korrelation:
            {' '}
            <span className="font-medium">&apos;Position wählen&apos;</span>
            -Feature nutzen (siehe Roadmap UC1.B).
          </span>
          <button
            type="button"
            onClick={handleDismissBanner}
            aria-label="Hinweis schließen"
            data-testid="geoint-footprint-hint-dismiss"
            className="shrink-0 rounded p-0.5 text-amber-700 hover:bg-amber-100 hover:text-amber-900"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div className="relative h-[70vh] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <MapContainer
          center={DEFAULT_CENTER}
          zoom={DEFAULT_ZOOM}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; OpenStreetMap'
          />
          <MapBoundsController scenes={scenes} />
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
                    <div className="flex items-center gap-1.5 font-semibold">
                      <PlatformBadge kind={scene.platform_kind} />
                      {scene.sensor}
                    </div>
                    <div>
                      {new Date(scene.captured_at).toLocaleString('de-DE')}
                    </div>
                    {scene.platform_kind === 'uav' && scene.altitude_m != null && (
                      <div>Höhe: {scene.altitude_m} m</div>
                    )}
                    {scene.platform_kind === 'uav' && scene.heading_deg != null && (
                      <div>Kurs: {scene.heading_deg}°</div>
                    )}
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
          <fieldset className="flex gap-2 text-xs">
            {(['satellite', 'uav'] as PlatformKind[]).map((k) => (
              <label
                key={k}
                className={[
                  'flex flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 font-medium',
                  uploadKind === k
                    ? 'border-[#C74634] bg-[#C74634] text-white'
                    : 'border-slate-200 text-slate-600 hover:bg-slate-50',
                ].join(' ')}
              >
                <input
                  type="radio"
                  name="upload-kind"
                  value={k}
                  checked={uploadKind === k}
                  onChange={() => setUploadKind(k)}
                  className="sr-only"
                />
                {k === 'satellite' ? <SatelliteIcon size={12} /> : <Plane size={12} />}
                {k === 'satellite' ? 'Satellit' : 'UAV'}
              </label>
            ))}
          </fieldset>
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
          {uploadMutation.isSuccess && uploadMutation.data && (
            <UploadResultCard result={uploadMutation.data} />
          )}
        </form>

        {scenesQuery.isLoading && <SkeletonCard />}
        {scenesQuery.isError && <ErrorCard error={scenesQuery.error} />}
      </div>
    </section>
  );
}

function PlatformBadge({ kind }: { kind: PlatformKind }) {
  if (kind === 'uav') {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-[#C74634] px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
        <Plane size={10} />
        UAV
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
      <SatelliteIcon size={10} />
      SAT
    </span>
  );
}

function PlatformFilterPills({
  value,
  onChange,
  satCount,
  uavCount,
}: {
  value: PlatformFilter;
  onChange: (v: PlatformFilter) => void;
  satCount: number;
  uavCount: number;
}) {
  const pill = (v: PlatformFilter, label: string, count: number) => (
    <button
      key={v}
      type="button"
      onClick={() => onChange(v)}
      aria-pressed={value === v}
      className={[
        'rounded-full px-2.5 py-1 text-xs font-medium transition-colors',
        value === v
          ? 'bg-slate-900 text-white'
          : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
      ].join(' ')}
    >
      {label} <span className="opacity-70">({count})</span>
    </button>
  );
  return (
    <div className="flex items-center gap-1">
      {pill('all', 'Alle', satCount + uavCount)}
      {pill('satellite', 'Satellit', satCount)}
      {pill('uav', 'UAV', uavCount)}
    </div>
  );
}

/**
 * Compact summary of the most-recent upload. Shows detection count and
 * the top-3 label histogram so the user immediately sees what YOLOv8
 * found without reopening the map popup. Distinguishes between an
 * EXIF-GPS-anchored footprint and the Mitteleuropa fallback so the
 * user understands why a generic JPEG just landed in central Germany.
 */
function UploadResultCard({ result }: { result: UploadSceneResult }) {
  // Build a small "3× truck, 2× car" histogram of the top labels.
  const histogram = useMemo(() => {
    const counts = new Map<string, number>();
    for (const det of result.detections) {
      counts.set(det.label, (counts.get(det.label) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([label, n]) => `${n}× ${label}`)
      .join(', ');
  }, [result.detections]);

  return (
    <div className="space-y-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
      <div className="font-semibold">
        Szene ingestiert · {result.count} Detektion{result.count === 1 ? '' : 'en'}
      </div>
      {histogram && (
        <div className="text-emerald-800">{histogram}</div>
      )}
      <div className="flex items-start gap-1 text-[11px] text-emerald-800">
        <MapPin size={11} className="mt-0.5 shrink-0" />
        <span>
          {result.is_synthetic_footprint ? (
            <>
              Keine EXIF-GPS-Daten — Default-Position Mitteleuropa
              ({result.footprint_lat.toFixed(3)}°N, {result.footprint_lon.toFixed(3)}°E).
            </>
          ) : (
            <>
              Position aus EXIF: {result.footprint_lat.toFixed(4)}°N,
              {' '}{result.footprint_lon.toFixed(4)}°E.
            </>
          )}
        </span>
      </div>
    </div>
  );
}

export default GeointView;
