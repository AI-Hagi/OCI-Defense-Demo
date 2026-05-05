import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Eye,
  FileLock,
  Lock,
  Pause,
  Play,
  Shield,
  ShieldCheck,
} from 'lucide-react';
import { compliance } from '../services/api';
import {
  DEGRADED_ERROR,
  FRAMEWORK_LABEL,
  LiveTile,
  ScoreCard,
  StatusIcon,
  formatRelative,
} from '../components/compliance/ComplianceTiles';
import type {
  AdbEncryptionLive,
  BucketAccessLive,
  CloudGuardLive,
  ComplianceControl,
  ComplianceFrameworkScore,
  Framework,
  OlsStatusLive,
} from '../types';

// Polling cadences (ms) — 30s for fast-changing telemetry, 5min for slower.
const POLL_FAST = 30_000;
const POLL_SLOW = 5 * 60_000;
const POLL_SCORE = 30_000;

const FRAMEWORKS: Framework[] = ['NIS2', 'DORA', 'GDPR', 'VSNFD'];

export function ComplianceView() {
  const navigate = useNavigate();
  const [activeFramework, setActiveFramework] = useState<Framework | 'ALL'>(
    'ALL',
  );
  // Pause/Resume toggles refetchInterval globally for all live + score queries.
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  // Re-render every second so the "vor X Sek." indicators stay live.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const scoreQuery = useQuery({
    queryKey: ['compliance.score'],
    queryFn: () => compliance.score(),
    refetchInterval: autoRefresh ? POLL_SCORE : false,
  });

  const controlsQuery = useQuery({
    queryKey: ['compliance.controls', activeFramework],
    queryFn: () =>
      compliance.controls(
        activeFramework === 'ALL' ? undefined : (activeFramework as Framework),
      ),
  });

  const cloudGuardQuery = useQuery<CloudGuardLive>({
    queryKey: ['compliance.live.cloudGuard'],
    queryFn: () => compliance.live.cloudGuard(),
    refetchInterval: autoRefresh ? POLL_FAST : false,
  });

  const adbEncryptionQuery = useQuery<AdbEncryptionLive>({
    queryKey: ['compliance.live.adbEncryption'],
    queryFn: () => compliance.live.adbEncryption(),
    refetchInterval: autoRefresh ? POLL_SLOW : false,
  });

  const bucketAccessQuery = useQuery<BucketAccessLive>({
    queryKey: ['compliance.live.bucketAccess'],
    queryFn: () => compliance.live.bucketAccess(),
    refetchInterval: autoRefresh ? POLL_SLOW : false,
  });

  const olsStatusQuery = useQuery<OlsStatusLive>({
    queryKey: ['compliance.live.olsStatus'],
    queryFn: () => compliance.live.olsStatus(),
    refetchInterval: autoRefresh ? POLL_SLOW : false,
  });

  const scoreByFw = useMemo(() => {
    const map = new Map<Framework, ComplianceFrameworkScore>();
    for (const s of scoreQuery.data ?? []) map.set(s.framework, s);
    return map;
  }, [scoreQuery.data]);

  const controls: ComplianceControl[] = useMemo(() => {
    const list = [...(controlsQuery.data ?? [])];
    list.sort((a, b) => a.code.localeCompare(b.code));
    return list;
  }, [controlsQuery.data]);

  // Most-recent successful update across the four live queries — used by the
  // "Letzte Aktualisierung" indicator next to the Pause/Resume button.
  const lastRefresh: number | undefined = useMemo(() => {
    const candidates = [
      cloudGuardQuery.dataUpdatedAt,
      adbEncryptionQuery.dataUpdatedAt,
      bucketAccessQuery.dataUpdatedAt,
      olsStatusQuery.dataUpdatedAt,
      scoreQuery.dataUpdatedAt,
    ].filter((n): n is number => typeof n === 'number' && n > 0);
    return candidates.length ? Math.max(...candidates) : undefined;
  }, [
    cloudGuardQuery.dataUpdatedAt,
    adbEncryptionQuery.dataUpdatedAt,
    bucketAccessQuery.dataUpdatedAt,
    olsStatusQuery.dataUpdatedAt,
    scoreQuery.dataUpdatedAt,
  ]);

  const lastRefreshIso = lastRefresh
    ? new Date(lastRefresh).toISOString()
    : undefined;

  // Live data + degraded flags (backend returns error when instance principal
  // / workload identity is missing — show "—" + warning instead of stale data).
  // demo:true means the backend is intentionally returning synthetic data and
  // the tile should render normally (not as degraded).
  const cg = cloudGuardQuery.data;
  const cgDegraded = !cg?.demo && cg?.error === DEGRADED_ERROR;
  const adb = adbEncryptionQuery.data;
  const adbDegraded = !adb?.demo && adb?.error === DEGRADED_ERROR;
  const buckets = bucketAccessQuery.data;
  const bucketsDegraded = !buckets?.demo && buckets?.error === DEGRADED_ERROR;
  const ols = olsStatusQuery.data;
  const olsDegraded = ols?.error === DEGRADED_ERROR;

  return (
    <section className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            Compliance &amp; Sicherheit
          </h2>
          <p className="text-sm text-slate-600">
            Rahmenwerke NIS2, DORA, GDPR und VS-NfD — mit Live-Telemetrie aus
            Cloud Guard, ATP, Object Storage und Oracle Label Security.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500" data-testid="last-refresh">
            Letzte Aktualisierung: {formatRelative(lastRefreshIso, now)}
          </span>
          <button
            type="button"
            onClick={() => setAutoRefresh((v) => !v)}
            aria-pressed={autoRefresh}
            data-testid="pause-resume"
            className={[
              'inline-flex items-center gap-1 rounded-md border px-3 py-1 text-xs font-medium transition-colors',
              autoRefresh
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300'
                : 'border-slate-300 bg-white text-slate-700 hover:border-slate-400',
            ].join(' ')}
          >
            {autoRefresh ? (
              <>
                <Pause size={12} /> Pause
              </>
            ) : (
              <>
                <Play size={12} /> Resume
              </>
            )}
          </button>
        </div>
      </header>

      {/* Score cards */}
      {scoreQuery.isLoading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500 shadow-sm">
          Lade Scores...
        </div>
      ) : scoreQuery.isError ? (
        <div className="rounded-xl border border-rose-200 bg-white p-8 text-center text-sm text-rose-700 shadow-sm">
          Fehler beim Laden der Scores.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FRAMEWORKS.map((fw) => (
            <ScoreCard key={fw} score={scoreByFw.get(fw)} />
          ))}
        </div>
      )}

      {/* Live security telemetry tiles */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <LiveTile
          testId="tile-cloud-guard"
          label="Cloud Guard offene Probleme"
          value={cg?.open_problems ?? 0}
          icon={<Shield size={16} />}
          asOf={cg?.as_of}
          now={now}
          degraded={cgDegraded}
          badge={
            !cgDegraded && (cg?.high_risk ?? 0) > 0 ? (
              <span
                className="inline-flex items-center justify-center rounded-md bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold text-rose-700"
                data-testid="cloud-guard-high-risk"
              >
                {cg!.high_risk} HIGH
              </span>
            ) : null
          }
          onClick={() => navigate('/compliance/cloud-guard-detail')}
        />
        <LiveTile
          testId="tile-adb-encryption"
          label="ATP-Verschlüsselung"
          value={adb ? `${adb.encrypted_count} / ${adb.adb_count}` : '0 / 0'}
          icon={<Lock size={16} />}
          asOf={adb?.as_of}
          now={now}
          degraded={adbDegraded}
          ok={!adbDegraded && !!adb?.compliant}
        />
        <LiveTile
          testId="tile-bucket-access"
          label="Bucket-Zugriff"
          value={
            <span
              className={
                (buckets?.public_count ?? 0) > 0
                  ? 'text-rose-700'
                  : 'text-emerald-700'
              }
            >
              {buckets?.public_count ?? 0}
            </span>
          }
          icon={<Eye size={16} />}
          asOf={buckets?.as_of}
          now={now}
          degraded={bucketsDegraded}
          ok={!bucketsDegraded && (buckets?.public_count ?? 0) === 0}
        />
        <LiveTile
          testId="tile-ols-status"
          label={
            ols
              ? `${ols.policy_name} · ${ols.applied_to_tables} Tabellen`
              : 'OLS-Richtlinie'
          }
          value={
            <span className="inline-flex items-center gap-2 text-base font-semibold text-slate-900">
              {ols?.active ? <ShieldCheck size={20} /> : null}
              {ols?.active ? 'aktiv' : 'inaktiv'}
            </span>
          }
          icon={<FileLock size={16} />}
          asOf={ols?.as_of}
          now={now}
          degraded={olsDegraded}
          ok={!olsDegraded && !!ols?.active}
        />
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wider text-slate-500">
          Filter:
        </span>
        {(['ALL', ...FRAMEWORKS] as const).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setActiveFramework(f)}
            className={[
              'rounded-md border px-3 py-1 text-xs font-medium transition-colors',
              activeFramework === f
                ? 'border-[#C74634] bg-[#C74634] text-white'
                : 'border-slate-300 bg-white text-slate-700 hover:border-slate-400',
            ].join(' ')}
          >
            {f === 'ALL' ? 'Alle' : FRAMEWORK_LABEL[f as Framework]}
          </button>
        ))}
      </div>

      {/* Controls table */}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-2">Code</th>
              <th className="px-4 py-2">Titel</th>
              <th className="px-4 py-2">Framework</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Mandant</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {controlsQuery.isLoading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  Lade Controls...
                </td>
              </tr>
            ) : controlsQuery.isError ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-rose-700">
                  Fehler beim Laden der Controls.
                </td>
              </tr>
            ) : controls.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  Keine Controls für diese Auswahl.
                </td>
              </tr>
            ) : (
              controls.map((c) => (
                <tr key={c.control_id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-mono text-xs text-slate-900">
                    {c.code}
                  </td>
                  <td className="px-4 py-2 text-slate-800">{c.title}</td>
                  <td className="px-4 py-2">
                    <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                      {FRAMEWORK_LABEL[c.framework]}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <StatusIcon status={c.status} />
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-600">
                    {c.tenant_id}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default ComplianceView;
