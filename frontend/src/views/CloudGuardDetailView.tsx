import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowLeft, Shield, AlertTriangle, ExternalLink } from 'lucide-react';
import { compliance } from '../services/api';
import { DEGRADED_ERROR, formatRelative } from '../components/compliance/ComplianceTiles';
import { useEffect, useState } from 'react';

const POLL_FAST = 30_000;

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

  const cg = cgQuery.data;
  const degraded = cg?.error === DEGRADED_ERROR;

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
              : `${Math.min(25, 5 * (cg?.open_problems ?? 0))} %`}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            -5 % je offenem Problem, gedeckelt bei -25 %.
          </p>
        </div>
      </div>

      {/* Degraded banner */}
      {degraded ? (
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
                Das ist erwartet auf OKE Virtual Nodes ohne Instance Metadata
                Service — in einer Production-Cluster-Variante mit
                Standard-Knoten und passender IAM-Policy würde diese Ansicht
                Problem-Liste, Severity, betroffene Ressource und Erkennungs­zeit
                live anzeigen.
              </p>
              <p>
                Der Compliance-Score-Tile auf der Compliance-Übersicht
                interpretiert <code className="rounded bg-amber-100 px-1">-1</code>{' '}
                bewusst als „degraded, kein Penalty" — Score-Werte bleiben
                unverzerrt.
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

      {/* Production-mode preview list — what the detail rows would look like */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3">
          <div className="text-sm font-semibold text-slate-900">
            Erwartete Detailspalten in Production
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Schema des produktiven Cloud-Guard-Detailfeeds — aktiv, sobald die
            Workload-Identity-Policy <code>cloud-guard:problem:read</code> auf
            dem Compartment greift.
          </p>
        </div>
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-2">Problem-ID</th>
              <th className="px-4 py-2">Risk Level</th>
              <th className="px-4 py-2">Detector</th>
              <th className="px-4 py-2">Resource</th>
              <th className="px-4 py-2">First Detected</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                — kein Live-Feed im aktuellen Cluster-Modus —
              </td>
            </tr>
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
              Bis die Workload-Policy ergänzt ist, werden offene Probleme in der
              OCI-Konsole untersucht. Region:{' '}
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
