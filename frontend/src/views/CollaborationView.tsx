import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Users, Calendar, Clock, Shield } from 'lucide-react';
import { collab } from '../services/api';
import { useTenant } from '../hooks/useTenant';
import type { Classification, CollabShare, Tenant } from '../types';

// Classification badge colour mapping (U / R / C / S).
function classificationBadge(cls: Classification | undefined): string {
  switch (cls) {
    case 'U':
      return 'bg-emerald-100 text-emerald-800 border-emerald-300';
    case 'R':
      return 'bg-amber-100 text-amber-800 border-amber-300';
    case 'C':
      return 'bg-orange-100 text-orange-800 border-orange-300';
    case 'S':
      return 'bg-rose-100 text-rose-800 border-rose-300';
    case 'VS-NFD':
      return 'bg-slate-900 text-white border-slate-900';
    default:
      return 'bg-slate-100 text-slate-700 border-slate-300';
  }
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
}

function ShareCard({ share }: { share: CollabShare }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900">
            {share.title ?? share.artefact_id}
          </div>
          <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-slate-500">
            {share.artefact_type}
          </div>
        </div>
        <span
          className={[
            'shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase',
            classificationBadge(share.classification),
          ].join(' ')}
        >
          {share.classification ?? '—'}
        </span>
      </div>

      <dl className="mt-3 space-y-1.5 text-xs text-slate-600">
        <div className="flex items-center gap-2">
          <Calendar size={12} className="text-slate-400" />
          <span>Freigabe: {formatDate(share.granted_at)}</span>
        </div>
        <div className="flex items-center gap-2">
          <Clock size={12} className="text-slate-400" />
          <span>Ablauf: {formatDate(share.expires_at)}</span>
        </div>
        <div className="flex items-center gap-2">
          <Shield size={12} className="text-slate-400" />
          <span>
            OLS-Label: {share.ols_label ?? '—'}
          </span>
        </div>
      </dl>
    </div>
  );
}

function TenantColumn({
  tenant,
  shares,
}: {
  tenant: Tenant;
  shares: CollabShare[];
}) {
  return (
    <div className="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-slate-50 p-4">
      <header className="mb-3 flex items-center justify-between">
        <div>
          <div className="font-mono text-xs uppercase tracking-wider text-slate-500">
            {tenant.code}
          </div>
          <div className="text-sm font-semibold text-slate-900">
            {tenant.display_name}
          </div>
        </div>
        <div className="flex items-center gap-1 text-xs text-slate-600">
          <Users size={14} />
          {shares.length}
        </div>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto">
        {shares.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-300 bg-white px-3 py-6 text-center text-xs text-slate-500">
            Keine Freigaben für diesen Mandanten.
          </div>
        ) : (
          shares.map((s) => <ShareCard key={s.share_id} share={s} />)
        )}
      </div>
    </div>
  );
}

export function CollaborationView() {
  const { all } = useTenant();
  const sharesQuery = useQuery({
    queryKey: ['collab.shares'],
    queryFn: () => collab.shares(),
  });

  const sharesByTenant = useMemo(() => {
    const map = new Map<string, CollabShare[]>();
    for (const t of all) map.set(t.tenant_id, []);
    for (const s of sharesQuery.data ?? []) {
      if (map.has(s.owner_tenant)) map.get(s.owner_tenant)!.push(s);
      if (s.partner_tenant !== s.owner_tenant && map.has(s.partner_tenant)) {
        map.get(s.partner_tenant)!.push(s);
      }
    }
    return map;
  }, [all, sharesQuery.data]);

  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold text-slate-900">
          DICE-EU Föderation
        </h2>
        <p className="text-sm text-slate-600">
          Geteilte Artefakte zwischen verbündeten Mandanten. Oracle Label
          Security erzwingt die Freigabestufen.
        </p>
      </header>

      {sharesQuery.isLoading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500 shadow-sm">
          Lade Freigaben...
        </div>
      ) : sharesQuery.isError ? (
        <div className="rounded-xl border border-rose-200 bg-white p-8 text-center text-sm text-rose-700 shadow-sm">
          Fehler beim Laden der Freigaben.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {all.map((t) => (
            <TenantColumn
              key={t.tenant_id}
              tenant={t}
              shares={sharesByTenant.get(t.tenant_id) ?? []}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export default CollaborationView;
