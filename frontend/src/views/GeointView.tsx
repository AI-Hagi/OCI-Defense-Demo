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
  // UAV-only telemetry — backend accepts via X-Altitude-M / X-Heading-Deg
  // headers (services/geoint app/main.py:upload). Inputs hide for satellite.
  const [uavAltitude, setUavAltitude] = useState<string>('');
  const [uavHeading, setUavHeading] = useState<string>('');
  const [selectedScene, setSelectedScene] = useState<SatelliteScene | null>(null);

  const scenesQuery = useQuery({
    queryKey: ['geoint.scenes'],
    queryFn: () => geoint.listScenes(),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      geoint.uploadScene(file, {
        platformKind: uploadKind,
        altitudeM:
          uploadKind === 'uav' && uavAltitude !== '' && !Number.isNaN(Number(uavAltitude))
            ? Number(uavAltitude)
            : undefined,
        headingDeg:
          uploadKind === 'uav' && uavHeading !== '' && !Number.isNaN(Number(uavHeading))
            ? Number(uavHeading)
            : undefined,
      }),
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
            const isSelected = selectedScene?.scene_id === scene.scene_id;
            return (
              <Polygon
                key={scene.scene_id}
                positions={latlngs}
                pathOptions={{
                  color: '#C74634',
                  weight: isSelected ? 3 : 2,
                  fillColor: '#C74634',
                  fillOpacity: isSelected ? 0.35 : 0.18,
                }}
                eventHandlers={{ click: () => setSelectedScene(scene) }}
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
          {uploadKind === 'uav' && (
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <label className="space-y-1">
                <span className="block text-slate-600">Höhe [m]</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={0}
                  step={1}
                  value={uavAltitude}
                  onChange={(e) => setUavAltitude(e.target.value)}
                  placeholder="z.B. 120"
                  className="w-full rounded-md border border-slate-200 px-2 py-1 text-slate-800 focus:border-[#C74634] focus:outline-none"
                />
              </label>
              <label className="space-y-1">
                <span className="block text-slate-600">Kurs [°]</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={359}
                  step={1}
                  value={uavHeading}
                  onChange={(e) => setUavHeading(e.target.value)}
                  placeholder="0–359"
                  className="w-full rounded-md border border-slate-200 px-2 py-1 text-slate-800 focus:border-[#C74634] focus:outline-none"
                />
              </label>
            </div>
          )}
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

      <GeointNarrativePanel
        scenes={scenes}
        loading={scenesQuery.isLoading}
        error={scenesQuery.isError}
      />

      <GeointSceneDetailPanel
        scene={selectedScene}
        onClose={() => setSelectedScene(null)}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------
// GeointNarrativePanel — sits below the map and explains what the operator
// is currently looking at: counts per platform, sensor distribution,
// detection-class histogram, and a short narrative on the YOLOv8 + WGS84
// pipeline. Mirror of the OSINT/Lieferkette panels.
// ---------------------------------------------------------------------------
interface NarrativePanelProps {
  scenes: SatelliteScene[];
  loading: boolean;
  error: boolean;
}

function GeointNarrativePanel({ scenes, loading, error }: NarrativePanelProps) {
  const platformCounts = useMemo(() => {
    const c = { satellite: 0, uav: 0 };
    for (const s of scenes) c[s.platform_kind] = (c[s.platform_kind] ?? 0) + 1;
    return c;
  }, [scenes]);

  const detectionCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of scenes) {
      for (const d of s.yolo_detections ?? []) {
        counts[d.cls] = (counts[d.cls] ?? 0) + 1;
      }
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [scenes]);

  const sensorCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of scenes) {
      const family = (s.sensor || 'unknown').split('-')[0];
      counts[family] = (counts[family] ?? 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [scenes]);

  const totalDetections = useMemo(
    () => scenes.reduce((acc, s) => acc + (s.yolo_detections?.length ?? 0), 0),
    [scenes],
  );

  return (
    <section
      data-testid="geoint-narrative"
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">
          Lagebild-Beschreibung — was wird hier gezeigt?
        </h3>
        <span className="text-[11px] text-slate-500">
          {scenes.length} Szenen · {totalDetections} Detektionen
        </span>
      </header>

      {loading && <p className="mt-3 text-xs text-slate-500">Lade Beschreibung…</p>}
      {error && (
        <p className="mt-3 text-xs text-rose-700">
          Beschreibung kann nicht geladen werden — /api/geoint/scenes nicht erreichbar.
        </p>
      )}

      {!loading && !error && (
        <div className="mt-4 grid gap-5 lg:grid-cols-3">
          <div className="space-y-3">
            <div className="text-xs uppercase tracking-wider text-slate-500">
              Plattform-Verteilung
            </div>
            <ul className="space-y-1.5">
              <li className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2">
                  <SatelliteIcon size={12} className="text-slate-700" />
                  <span className="font-medium text-slate-800">Satellit</span>
                </span>
                <span className="font-mono text-slate-600">{platformCounts.satellite}</span>
              </li>
              <li className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2">
                  <Plane size={12} className="text-[#C74634]" />
                  <span className="font-medium text-slate-800">UAV</span>
                </span>
                <span className="font-mono text-slate-600">{platformCounts.uav}</span>
              </li>
            </ul>

            {sensorCounts.length > 0 && (
              <>
                <div className="mt-3 text-xs uppercase tracking-wider text-slate-500">
                  Sensoren
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {sensorCounts.map(([s, n]) => (
                    <span
                      key={s}
                      className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-700"
                    >
                      {s} <span className="opacity-70">×{n}</span>
                    </span>
                  ))}
                </div>
              </>
            )}

            {detectionCounts.length > 0 && (
              <>
                <div className="mt-3 text-xs uppercase tracking-wider text-slate-500">
                  Top-Detektions-Klassen
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {detectionCounts.map(([cls, n]) => (
                    <span
                      key={cls}
                      className="rounded-md bg-rose-50 px-2 py-0.5 font-mono text-[10px] text-rose-800"
                    >
                      {cls} ×{n}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="space-y-2 text-xs leading-relaxed text-slate-700 lg:col-span-2">
            <div className="text-xs uppercase tracking-wider text-slate-500">
              Worum geht es?
            </div>
            <p>
              Multi-Source-GEOINT-Fusion — der GEOINT-Service nimmt Aufnahmen
              aus zwei Plattformen entgegen: <strong>Satellit</strong> (z.B.
              Sentinel-2-Tiles) und <strong>UAV</strong> (Aufklärungsdrohnen
              mit Höhe + Kurs). Jedes hochgeladene Bild läuft durch einen
              YOLOv8-Inferenz-Pfad und wird mit WGS84-Footprint und
              Detektions-Liste in Oracle 26ai persistiert.
            </p>
            <p>
              Auf der Karte rendert jeder rote Polygon-Umriss den
              <strong> WGS84-Footprint</strong> einer Szene. Klick auf einen
              Polygon-Umriss öffnet die Detail-Karte unten mit kompletten
              Stammdaten, der Detection-Liste mit Confidence-Werten und —
              bei UAV-Aufnahmen — Höhe und Kurs. Der Upload-Block oben rechts
              schickt neue Aufnahmen an{' '}
              <span className="font-mono">/api/geoint/scenes/upload</span>;
              die Antwort enthält direkt <em>scene_id</em>,{' '}
              <em>image_uri</em> (Object Storage), und die YOLOv8-Detections
              inklusive Bounding-Boxes.
            </p>
            <div className="mt-3 grid grid-cols-1 gap-2 rounded-md bg-slate-50 p-3 text-[11px] text-slate-600 sm:grid-cols-3">
              <span>
                <strong className="text-slate-800">Polygon-Klick</strong> →
                Detail-Karte unten
              </span>
              <span>
                <strong className="text-slate-800">Plattform-Filter</strong>
                {' '}→ nur Satellit / UAV / beide
              </span>
              <span>
                <strong className="text-slate-800">Upload</strong> → JPEG/TIFF,
                YOLOv8 inference + Footprint
              </span>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// GeointSceneDetailPanel — only renders when a scene is selected. Surfaces
// the full metadata, detection-list with confidence bars, and footprint
// summary.
// ---------------------------------------------------------------------------
interface SceneDetailPanelProps {
  scene: SatelliteScene | null;
  onClose: () => void;
}

function GeointSceneDetailPanel({ scene, onClose }: SceneDetailPanelProps) {
  if (!scene) {
    return (
      <section
        data-testid="geoint-detail-empty"
        className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-xs text-slate-500"
      >
        <strong className="text-slate-700">Detail-Karte:</strong> Klicken Sie
        auf einen Polygon-Umriss in der Karte, um Stammdaten, YOLOv8-
        Detektions-Liste und Footprint-Daten zu sehen.
      </section>
    );
  }

  const detections = scene.yolo_detections ?? [];
  const ringCount = scene.footprint?.coordinates.length ?? 0;
  const coordCount = scene.footprint?.coordinates.reduce(
    (acc, ring) => acc + ring.length,
    0,
  ) ?? 0;

  return (
    <section
      data-testid="geoint-detail"
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500">
            Detail-Karte
          </div>
          <h3 className="text-base font-semibold text-slate-900">
            {scene.sensor}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <PlatformBadge kind={scene.platform_kind} />
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-mono text-slate-700">
            {detections.length} Detektion{detections.length === 1 ? '' : 'en'}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Detail schließen"
            className="rounded p-0.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            <X size={14} />
          </button>
        </div>
      </header>

      <div className="mt-4 grid gap-5 lg:grid-cols-3">
        <div className="space-y-2 text-xs">
          <div className="text-xs uppercase tracking-wider text-slate-500">Stammdaten</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-slate-700">
            <dt className="text-slate-500">Aufgenommen</dt>
            <dd className="font-mono">
              {new Date(scene.captured_at).toLocaleString('de-DE')}
            </dd>
            <dt className="text-slate-500">Plattform</dt>
            <dd className="font-mono">{scene.platform_kind}</dd>
            {scene.platform_kind === 'uav' && (
              <>
                <dt className="text-slate-500">Höhe</dt>
                <dd className="font-mono">
                  {scene.altitude_m != null ? `${scene.altitude_m} m` : '—'}
                </dd>
                <dt className="text-slate-500">Kurs</dt>
                <dd className="font-mono">
                  {scene.heading_deg != null ? `${scene.heading_deg}°` : '—'}
                </dd>
              </>
            )}
            {scene.cloud_cover != null && (
              <>
                <dt className="text-slate-500">Wolkendecke</dt>
                <dd className="font-mono">{scene.cloud_cover}%</dd>
              </>
            )}
            <dt className="text-slate-500">Object-Storage</dt>
            <dd className="font-mono text-[10px] text-slate-500 break-all">
              {scene.image_uri ?? '—'}
            </dd>
            <dt className="text-slate-500">OLS-Label</dt>
            <dd className="font-mono">{scene.ols_label ?? '—'}</dd>
            <dt className="text-slate-500">Scene-ID</dt>
            <dd className="font-mono text-[10px] text-slate-500">
              {scene.scene_id.slice(0, 12)}…
            </dd>
          </dl>
        </div>

        <div className="space-y-2 text-xs">
          <div className="text-xs uppercase tracking-wider text-slate-500">
            YOLOv8-Detektionen
          </div>
          {detections.length === 0 ? (
            <p className="text-slate-500">Keine Detektionen für diese Szene.</p>
          ) : (
            <ul className="space-y-1.5">
              {detections.slice(0, 12).map((d, i) => (
                <li key={i} className="flex items-center gap-2 text-[11px]">
                  <span className="w-24 font-medium text-slate-700">
                    {d.cls}
                  </span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-[#C74634]"
                      style={{ width: `${Math.round(d.confidence * 100)}%` }}
                    />
                  </div>
                  <span className="w-10 text-right font-mono text-slate-700">
                    {(d.confidence * 100).toFixed(0)}%
                  </span>
                </li>
              ))}
              {detections.length > 12 && (
                <li className="text-[10px] text-slate-500">
                  …+{detections.length - 12} weitere
                </li>
              )}
            </ul>
          )}
        </div>

        <div className="space-y-2 text-xs">
          <div className="text-xs uppercase tracking-wider text-slate-500">
            WGS84-Footprint
          </div>
          {!scene.footprint ? (
            <p className="text-slate-500">
              Kein Footprint hinterlegt. Bestand-Szenen aus der Vor-Fix-Phase
              sind ohne Geometrie persistiert.
            </p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-slate-700">
              <dt className="text-slate-500">Geometrie-Typ</dt>
              <dd className="font-mono">{scene.footprint.type}</dd>
              <dt className="text-slate-500">Ringe</dt>
              <dd className="font-mono">{ringCount}</dd>
              <dt className="text-slate-500">Punkte gesamt</dt>
              <dd className="font-mono">{coordCount}</dd>
              {scene.footprint.coordinates[0]?.[0] && (
                <>
                  <dt className="text-slate-500">Ankerpunkt</dt>
                  <dd className="font-mono text-[10px]">
                    {scene.footprint.coordinates[0][0][1].toFixed(3)}°N /{' '}
                    {scene.footprint.coordinates[0][0][0].toFixed(3)}°E
                  </dd>
                </>
              )}
            </dl>
          )}
        </div>
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
