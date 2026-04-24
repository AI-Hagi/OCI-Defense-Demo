import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
} from 'recharts';
import { CheckCircle2, CircleAlert, CircleDashed, CircleX } from 'lucide-react';
import { compliance } from '../services/api';
import type {
  ComplianceControl,
  ComplianceFrameworkScore,
  ControlStatus,
  Framework,
} from '../types';

const FRAMEWORKS: Framework[] = ['NIS2', 'DORA', 'GDPR', 'VSNFD'];

const FRAMEWORK_LABEL: Record<Framework, string> = {
  NIS2: 'NIS2',
  DORA: 'DORA',
  GDPR: 'GDPR',
  VSNFD: 'VS-NfD',
};

function ScoreCard({
  score,
}: {
  score: ComplianceFrameworkScore | undefined;
}) {
  const value = score?.score ?? 0;
  const data = [{ name: 'score', value }];
  return (
    <div className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="h-24 w-24 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            innerRadius="65%"
            outerRadius="100%"
            data={data}
            startAngle={90}
            endAngle={90 - (value / 100) * 360}
          >
            <RadialBar
              dataKey="value"
              cornerRadius={8}
              fill="#C74634"
              background={{ fill: '#F5F4F2' }}
            />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-500">
          {FRAMEWORK_LABEL[score?.framework ?? 'NIS2']}
        </div>
        <div className="text-2xl font-semibold text-slate-900">
          {value.toFixed(0)}%
        </div>
        <div className="mt-1 text-[11px] text-slate-500">
          {score
            ? `${score.compliant_controls}/${score.total_controls} Controls`
            : '—'}
        </div>
      </div>
    </div>
  );
}

function StatusIcon({ status }: { status: ControlStatus | undefined }) {
  switch (status) {
    case 'mitigated':
    case 'closed':
      return (
        <span className="inline-flex items-center gap-1 text-emerald-700">
          <CheckCircle2 size={14} />
          <span className="text-xs">{status}</span>
        </span>
      );
    case 'open':
      return (
        <span className="inline-flex items-center gap-1 text-rose-700">
          <CircleX size={14} />
          <span className="text-xs">open</span>
        </span>
      );
    case 'accepted':
      return (
        <span className="inline-flex items-center gap-1 text-amber-700">
          <CircleAlert size={14} />
          <span className="text-xs">accepted</span>
        </span>
      );
    case 'false_positive':
      return (
        <span className="inline-flex items-center gap-1 text-slate-500">
          <CircleDashed size={14} />
          <span className="text-xs">false positive</span>
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 text-slate-400">
          <CircleDashed size={14} />
          <span className="text-xs">—</span>
        </span>
      );
  }
}

export function ComplianceView() {
  const [activeFramework, setActiveFramework] = useState<Framework | 'ALL'>(
    'ALL',
  );

  const scoreQuery = useQuery({
    queryKey: ['compliance.score'],
    queryFn: () => compliance.score(),
  });

  const controlsQuery = useQuery({
    queryKey: ['compliance.controls', activeFramework],
    queryFn: () =>
      compliance.controls(
        activeFramework === 'ALL' ? undefined : (activeFramework as Framework),
      ),
  });

  const scoreByFw = useMemo(() => {
    const map = new Map<Framework, ComplianceFrameworkScore>();
    for (const s of scoreQuery.data ?? []) map.set(s.framework, s);
    return map;
  }, [scoreQuery.data]);

  const controls: ComplianceControl[] = controlsQuery.data ?? [];

  return (
    <section className="space-y-5">
      <header>
        <h2 className="text-xl font-semibold text-slate-900">
          Compliance-Automatisierung
        </h2>
        <p className="text-sm text-slate-600">
          Rahmenwerke NIS2, DORA, GDPR und VS-NfD aus Oracle 26ai Evidence-Trail.
        </p>
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
