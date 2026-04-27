import type { ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  CircleX,
} from 'lucide-react';
import {
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
} from 'recharts';
import type {
  ComplianceFrameworkScore,
  ControlStatus,
  Framework,
} from '../../types';

// ---------------------------------------------------------------------------
// Shared constants — labels and color thresholds for the score / live tiles.
// Kept beside the components so ComplianceView.tsx stays slim.
// ---------------------------------------------------------------------------
export const FRAMEWORK_LABEL: Record<Framework, string> = {
  NIS2: 'NIS2',
  DORA: 'DORA',
  GDPR: 'GDPR',
  VSNFD: 'VS-NfD',
};

export const COLOR_BAD = '#C74634'; // redwood
export const COLOR_WARN = '#D97706'; // amber
export const COLOR_OK = '#059669'; // emerald

export const DEGRADED_TOOLTIP = 'Live-Daten temporär nicht verfügbar';
export const DEGRADED_ERROR = 'instance_principal_unavailable';

export function scoreColor(score: number): string {
  if (score < 60) return COLOR_BAD;
  if (score < 80) return COLOR_WARN;
  return COLOR_OK;
}

// Render an ISO timestamp as "vor X Sek." / "vor X Min." relative to `now`.
export function formatRelative(
  iso: string | undefined,
  now: number,
): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const diff = Math.max(0, Math.round((now - t) / 1000));
  if (diff < 60) return `vor ${diff} Sek.`;
  if (diff < 3600) return `vor ${Math.round(diff / 60)} Min.`;
  if (diff < 86400) return `vor ${Math.round(diff / 3600)} Std.`;
  return `vor ${Math.round(diff / 86400)} Tagen`;
}

// ---------------------------------------------------------------------------
// Score card — radial bar tinted by score band.
// ---------------------------------------------------------------------------
export function ScoreCard({
  score,
}: {
  score: ComplianceFrameworkScore | undefined;
}) {
  const value = score?.score_pct ?? 0;
  const total = score?.total ?? 0;
  const compliantCount = score?.implemented ?? 0;
  const fw = score?.framework ?? 'NIS2';
  const fill = scoreColor(value);
  const data = [{ name: 'score', value }];
  return (
    <div
      className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
      data-testid={`score-card-${fw}`}
    >
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
              fill={fill}
              background={{ fill: '#F5F4F2' }}
            />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-500">
          {FRAMEWORK_LABEL[fw]} — {total} Controls
        </div>
        <div className="text-2xl font-semibold" style={{ color: fill }}>
          {value.toFixed(0)}%
        </div>
        <div className="mt-1 text-[11px] text-slate-500">
          {score ? `${compliantCount} implementiert von ${total}` : '—'}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Live tile — shared shell used by the 4 live security telemetry tiles.
// ---------------------------------------------------------------------------
export interface LiveTileProps {
  label: string;
  value: ReactNode;
  icon: ReactNode;
  asOf: string | undefined;
  now: number;
  degraded: boolean;
  ok?: boolean;
  badge?: ReactNode;
  onClick?: () => void;
  testId?: string;
}

export function LiveTile({
  label,
  value,
  icon,
  asOf,
  now,
  degraded,
  ok,
  badge,
  onClick,
  testId,
}: LiveTileProps) {
  const clickable = !!onClick;
  return (
    <div
      className={[
        'relative rounded-xl border border-slate-200 bg-white p-4 shadow-sm',
        clickable
          ? 'cursor-pointer transition-colors hover:border-slate-300'
          : '',
      ].join(' ')}
      onClick={onClick}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      data-testid={testId}
    >
      <div className="absolute right-3 top-3 flex items-center gap-1 text-slate-400">
        {badge}
        {degraded ? (
          <span title={DEGRADED_TOOLTIP} data-testid={`${testId}-degraded`}>
            <AlertTriangle size={16} className="text-amber-500" />
          </span>
        ) : (
          icon
        )}
      </div>
      <div className="text-2xl font-semibold text-slate-900">
        {degraded ? '—' : value}
        {!degraded && ok ? (
          <CheckCircle2
            size={18}
            className="ml-2 inline text-emerald-600 align-[-2px]"
          />
        ) : null}
      </div>
      <div className="mt-1 text-xs text-slate-600">{label}</div>
      <div className="mt-3 text-[11px] text-slate-400">
        {formatRelative(asOf, now)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status icon — used in the controls table.
// ---------------------------------------------------------------------------
export function StatusIcon({ status }: { status: ControlStatus | undefined }) {
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
