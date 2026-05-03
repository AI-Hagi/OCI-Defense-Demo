import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowLeft, Shield, AlertTriangle, ExternalLink, Zap } from 'lucide-react';
import { compliance } from '../services/api';
import { DEGRADED_ERROR, formatRelative } from '../components/compliance/ComplianceTiles';
import { useEffect, useState } from 'react';

const POLL_FAST = 30_000;

function riskBadge(risk: string) {
  const norm = risk.toUpperCase();
  if (norm === 'CRITICAL' || norm === 'HIGH') {
    return 'bg-rose-100 text-rose-700 ring-rose-200';
  }
  if (norm === 'MEDIUM') {
    return 'bg-amber-100 text-amber-700 ring-amber-200';
  }
  return 'bg-slate-100 text-slate-700 ring-slate-200';
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export function CloudGuardDetailView() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const cgQuery = useQuery({
    queryKey: ['compliance.live.cloudGuard.detail'],
    queryFn: () => compliance.live.cloudGuard(),
    refetchInterval: POLL_FAST,
  });
  const problemsQuery = useQuery({
    queryKey: ['compliance.live.cloudGuard.problems'],
    queryFn: () => compliance.live.cloudGuardProblems(),
    refetchInterval: POLL_FAST,
  });

  const cg = cgQuery.data;
  const problemsResp = problemsQuery.data;
  const problems = problemsResp?.problems ?? [];
  const isDemo = !!(cg?.demo || problemsResp?.demo);
  // Degraded means: not in demo mode AND backend signalled instance_principal_unavailable.
  const degraded = !isDemo && (cg?.error === DEGRADED_ERROR);

  return (
    <section className="space-y-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <Link
            to="/compliance"
            className="mb-2 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"
          >
            <ArrowLeft size={12} /> Zurück zu Compliance
          </Link>
          <h2 className="text-xl font-semibold text-slate-900">
            Cloud Guard — Offene Probleme
          </h2>
          <p className="text-sm text-slate-600">
            Detail-Ansicht des OCI Cloud Guard Sicherheits-Posture für das
            Compartment <code className="rounded bg-slate-100 px-1">oci-defence-demo</code>.
          </p>
        </div>
        <span className="text-xs text-slate-500">
          Stand: {formatRelative(cg?.as_of, now)}
        </span>
      </header>

      {/* Headline metric tiles */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500">
            <Shield size={14} /> Offene Probleme
          </div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">
            {degraded ? '—' : cg?.open_problems ?? 0}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500">
            <AlertTriangle size={14} /> Davon HIGH/CRITICAL
          </div>
          <div
            className={[
              'mt-2 text-3xl font-semibold',
              degraded
                ? 'text-slate-400'
                : (cg?.high_risk ?? 0) > 0
                  ? 'text-rose-700'
                  : 'text-emerald-700',
            ].join(' ')}
          >
            {degraded ? '—' : cg?.high_risk ?? 0}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500">
            Score-Auswirkung
          </div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">
            {degraded
              ? '—'
              : `-${Math.min(25, 5 * (cg?.open_problems ?? 0))} %`}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            -5 % je offenem Problem, gedeckelt bei -25 %.
          </p>
        </div>
      </div>

      {/* Demo-mode banner — informational, not an error */}
      {isDemo ? (
        <div className="rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900 shadow-sm">
          <div className="flex items-start gap-3">
            <Zap size={20} className="mt-0.5 flex-shrink-0" />
            <div className="space-y-1">
              <div className="font-semibold">
                Demo-Modus — synthetische Cloud-Guard-Daten
              </div>
              <p>
                In der aktuellen Cluster-Variante (OKE Virtual Nodes ohne IMDS)
                wird die Cloud-Guard-Detail-Liste deterministisch synthetisiert,
                damit die Score-Logik live durchspielt werden kann. Sobald die
                Workload-Identity-Policy{' '}
                <code className="rounded bg-sky-100 px-1">
                  cloud-guard:problem:read
                </code>{' '}
                auf dem Compartment greift, ersetzt der echte ListProblems-Feed
                diese Daten ohne Code-Änderung.
              </p>
            </div>
          </div>
        </div>
      ) : degraded ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 shadow-sm">
          <div className="flex items-start gap-3">
            <AlertTriangle size={20} className="mt-0.5 flex-shrink-0" />
            <div className="space-y-1">
              <div className="font-semibold">
                Cloud Guard Live-Daten derzeit nicht verfügbar
              </div>
              <p>
                Das Workload-Identity-Token erlaubt aktuell keinen Aufruf von{' '}
                <code className="rounded bg-amber-100 px-1">ListProblems</code>.
                Setzen Sie <code className="rounded bg-amber-100 px-1">COMPLIANCE_DEMO_MODE=true</code>{' '}
                im Compliance-Deployment, um in der Demo deterministische Daten
                zu zeigen.
              </p>
            </div>
          </div>
        </div>
      ) : (cg?.open_problems ?? 0) === 0 ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 shadow-sm">
          <div className="font-semibold">Keine offenen Probleme.</div>
          <p>
            Cloud Guard meldet aktuell keine aktiven Findings im Compartment{' '}
            <code className="rounded bg-emerald-100 px-1">oci-defence-demo</code>.
          </p>
        </div>
      ) : null}

      {/* Problem list */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3">
          <div className="text-sm font-semibold text-slate-900">
            Aktive Findings
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Sortiert nach Erkennungs­zeit, neueste zuerst.
          </p>
        </div>
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-2">Risk</th>
              <th className="px-4 py-2">Detector</th>
              <th className="px-4 py-2">Resource</th>
              <th className="px-4 py-2">Compartment</th>
              <th className="px-4 py-2">First Detected</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {problemsQuery.isLoading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  Lade Findings...
                </td>
              </tr>
            ) : problems.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  {degraded
                    ? '— kein Live-Feed im aktuellen Cluster-Modus —'
                    : 'Keine aktiven Findings.'}
                </td>
              </tr>
            ) : (
              problems.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2">
                    <span
                      className={[
                        'inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset',
                        riskBadge(p.risk_level),
                      ].join(' ')}
                    >
                      {p.risk_level}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-700">
                    {p.detector_rule}
                  </td>
                  <td className="px-4 py-2 text-slate-800">
                    <div>{p.resource_name}</div>
                    <div className="text-xs text-slate-500">{p.resource_type}</div>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-600">
                    {p.compartment}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-700">
                    {formatTimestamp(p.first_detected)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Console deep link */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="font-semibold text-slate-900">
              OCI Console — Cloud Guard
            </div>
            <p className="mt-1 text-slate-600">
              Detaillierte Untersuchung pro Finding in der OCI-Konsole. Region:{' '}
              <code className="rounded bg-slate-100 px-1">eu-frankfurt-1</code>.
            </p>
          </div>
          <a
            href="https://cloud.oracle.com/security/cloud-guard/problems"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-400"
          >
            Konsole öffnen <ExternalLink size={12} />
          </a>
        </div>
      </div>
    </section>
  );
}

export default CloudGuardDetailView;
