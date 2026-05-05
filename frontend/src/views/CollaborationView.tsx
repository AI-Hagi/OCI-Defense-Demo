import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Users,
  Calendar,
  Clock,
  Shield,
  Plus,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
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

type ArtefactType =
  | 'document'
  | 'scene'
  | 'osint_entity'
  | 'sc_node'
  | 'compliance_finding';
type DEClassification = 'OFFEN' | 'INTERN' | 'NFD' | 'GEHEIM';

interface NewShareFormProps {
  tenants: Tenant[];
  onCreated: (share: CollabShare) => void;
}

function NewShareForm({ tenants, onCreated }: NewShareFormProps) {
  const [open, setOpen] = useState(false);
  const [ownerTenant, setOwnerTenant] = useState(tenants[0]?.tenant_id ?? '');
  const [partnerTenant, setPartnerTenant] = useState(
    tenants[1]?.tenant_id ?? '',
  );
  const [artefactType, setArtefactType] = useState<ArtefactType>('document');
  const [title, setTitle] = useState('');
  const [classification, setClassification] = useState<DEClassification>('INTERN');
  const [daysValid, setDaysValid] = useState(90);

  const createMutation = useMutation({
    mutationFn: () => {
      const artefactId = title
        .replace(/[^A-Z0-9-]+/gi, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 64)
        .toUpperCase() || `SHARE-${Date.now()}`;
      return collab.createShare({
        owner_tenant: ownerTenant,
        partner_tenant: partnerTenant,
        artefact_type: artefactType,
        artefact_id: artefactId,
        title,
        classification,
        days_valid: daysValid,
      });
    },
    onSuccess: (share) => {
      onCreated(share);
      setTitle('');
    },
  });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="collab-new-share-toggle"
        className="flex items-center gap-2 rounded-md border border-[#C74634] bg-white px-3 py-1.5 text-xs font-medium text-[#C74634] shadow-sm hover:bg-[#C74634] hover:text-white"
      >
        <Plus size={14} />
        Neue Freigabe
      </button>
    );
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    if (ownerTenant === partnerTenant) return;
    createMutation.mutate();
  };

  return (
    <form
      onSubmit={handleSubmit}
      data-testid="collab-new-share-form"
      className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-white p-4 text-xs shadow-sm md:grid-cols-2"
    >
      <label className="flex flex-col gap-1">
        <span className="text-slate-600">Inhaber (Owner-Mandant)</span>
        <select
          value={ownerTenant}
          onChange={(e) => setOwnerTenant(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
        >
          {tenants.map((t) => (
            <option key={t.tenant_id} value={t.tenant_id}>
              {t.code} — {t.display_name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-slate-600">Empfänger (Partner-Mandant)</span>
        <select
          value={partnerTenant}
          onChange={(e) => setPartnerTenant(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
        >
          {tenants.map((t) => (
            <option key={t.tenant_id} value={t.tenant_id}>
              {t.code} — {t.display_name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-slate-600">Artefakt-Typ</span>
        <select
          value={artefactType}
          onChange={(e) => setArtefactType(e.target.value as ArtefactType)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
        >
          <option value="document">Document</option>
          <option value="scene">Scene</option>
          <option value="osint_entity">OSINT Entity</option>
          <option value="sc_node">Supply-Chain Node</option>
          <option value="compliance_finding">Compliance Finding</option>
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-slate-600">Klassifizierung</span>
        <select
          value={classification}
          onChange={(e) =>
            setClassification(e.target.value as DEClassification)
          }
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
        >
          <option value="OFFEN">OFFEN</option>
          <option value="INTERN">INTERN</option>
          <option value="NFD">NFD (VS-NfD)</option>
          <option value="GEHEIM">GEHEIM</option>
        </select>
      </label>

      <label className="flex flex-col gap-1 md:col-span-2">
        <span className="text-slate-600">Titel / Bezeichnung</span>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="z. B. BMVg → DGA Lagebild Q3/2026"
          maxLength={400}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-slate-600">Gültig (Tage)</span>
        <input
          type="number"
          min={1}
          max={3650}
          value={daysValid}
          onChange={(e) => setDaysValid(Number(e.target.value) || 90)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
        />
      </label>

      <div className="flex items-end justify-end gap-2 md:col-span-2">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
        >
          Abbrechen
        </button>
        <button
          type="submit"
          disabled={
            !title.trim() ||
            ownerTenant === partnerTenant ||
            createMutation.isPending
          }
          className="flex items-center gap-1.5 rounded-md bg-[#C74634] px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-[#A33A2C] disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          <Plus size={12} />
          {createMutation.isPending ? 'Anlegen…' : 'Freigabe anlegen'}
        </button>
      </div>

      {createMutation.isSuccess && createMutation.data && (
        <div className="flex items-start gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-[11px] text-emerald-800 md:col-span-2">
          <CheckCircle2 size={12} className="mt-0.5 shrink-0" />
          <span>
            Freigabe <strong>{createMutation.data.title}</strong> angelegt
            (Ablauf{' '}
            {new Date(createMutation.data.expires_at ?? '').toLocaleDateString(
              'de-DE',
            )}
            ).
          </span>
        </div>
      )}
      {createMutation.isError && (
        <div className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-[11px] text-rose-700 md:col-span-2">
          <AlertCircle size={12} className="mt-0.5 shrink-0" />
          <span>
            Anlegen fehlgeschlagen:{' '}
            {(createMutation.error as Error)?.message ?? 'unknown'}
          </span>
        </div>
      )}
    </form>
  );
}

export function CollaborationView() {
  const { all } = useTenant();
  const queryClient = useQueryClient();
  const sharesQuery = useQuery({
    queryKey: ['collab.shares'],
    queryFn: () => collab.shares(true),
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
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            DICE-EU Föderation
          </h2>
          <p className="text-sm text-slate-600">
            Geteilte Artefakte zwischen verbündeten Mandanten. Oracle Label
            Security erzwingt die Freigabestufen.
          </p>
        </div>
        <NewShareForm
          tenants={all}
          onCreated={() =>
            queryClient.invalidateQueries({ queryKey: ['collab.shares'] })
          }
        />
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
