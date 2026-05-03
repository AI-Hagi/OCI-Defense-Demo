/**
 * UC4 Briefing-Werkstatt — automated briefing creation + chat-style log.
 *
 * Wires three existing pieces of the UC4 stack:
 *
 *   1. GET /api/osint/correlations  -> picker of recent correlation events
 *   2. POST /api/uc4/tools/graph_query -> entities tied to that correlation
 *   3. POST /api/uc4/tools/persist_briefing -> persist the synthesised draft
 *   4. GET /api/osint/briefings      -> chat-style timeline of past briefings
 *
 * The drafting step itself is **deterministic, in the browser**. The
 * Threat-Fusion-Agent runtime (Llama 3.3 70B on-demand) is deployed but its
 * tool-runtime call still 500s, so we synthesise a template-based briefing
 * out of the correlation summary + graph entities. When the agent comes
 * back online, this component swaps the synthesizer for a real chat round
 * trip without changing the persist contract.
 */
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  FilePlus,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  User,
} from 'lucide-react';
import {
  graphQuery,
  listBriefings,
  listCorrelations,
  persistBriefing,
  type BriefingRow,
  type CorrelationEvent,
  type MultiSourceEntity,
  type OlsLabel,
} from '../services/uc4Tools';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function classFromCap(cap: OlsLabel): 'OFFEN' | 'INTERN' | 'NFD' {
  // persist_briefing only accepts OFFEN/INTERN/NFD; demo cap maxes at NFD.
  if (cap === 'OFFEN' || cap === 'INTERN' || cap === 'NFD') return cap;
  return 'NFD';
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

// Deterministic German-language briefing draft from a correlation + the
// multi-source entities the graph_query tool returns. Keeps the wording
// disciplined: facts only, no kinetic recommendations (Plattform-Disziplin
// per CLAUDE.md). Output stays under the 4000-char persist_briefing cap.
function synthesiseBody(
  correlation: CorrelationEvent,
  entities: MultiSourceEntity[],
): string {
  const lines: string[] = [];
  lines.push(
    `**Lagebild — ${correlation.correlation_kind}**`,
    '',
    `Der Korrelations-Detektor hat am ${formatTime(correlation.detected_at)} ein Pattern vom Typ \`${correlation.correlation_kind}\` aufgenommen.`,
    correlation.summary
      ? `Detektor-Zusammenfassung: ${correlation.summary}`
      : 'Keine Detektor-Zusammenfassung im Pattern hinterlegt.',
    '',
  );

  if (entities.length > 0) {
    const top = entities.slice(0, 5);
    lines.push('**Beobachtete Entitäten (Top 5 nach Korrelations-Häufigkeit)**');
    for (const e of top) {
      lines.push(
        `- ${e.entity_kind} **${e.display_name}** — ${e.corr_count} Korrelation${e.corr_count === 1 ? '' : 'en'}`,
      );
    }
    lines.push('');
  } else {
    lines.push(
      'Keine Multi-Source-Entitäten dieser Korrelation unter dem aktuellen Cap sichtbar.',
      '',
    );
  }

  lines.push(
    '**Bewertung**',
    correlation.score && correlation.score >= 0.7
      ? `Konfidenz × Severity = ${correlation.score.toFixed(2)} — relevant für tägliches Lagebild.`
      : correlation.score
        ? `Konfidenz × Severity = ${correlation.score.toFixed(2)} — Hintergrund-Beobachtung.`
        : 'Score nicht gesetzt — Bewertung erfolgt im Vier-Augen-Review.',
    '',
    '**Empfehlung**',
    'Pattern in den nächsten 24 h re-evaluieren. Plattform-Disziplin: keine kinetischen Maßnahmen-Empfehlungen aus diesem Briefing.',
  );

  return lines.join('\n').slice(0, 3800);
}

// ---------------------------------------------------------------------------
// Chat bubble primitives
// ---------------------------------------------------------------------------

type ChatBubble = {
  id: string;
  role: 'user' | 'agent' | 'system';
  text: string;
  meta?: string;
};

function Bubble({ bubble }: { bubble: ChatBubble }) {
  const isUser = bubble.role === 'user';
  const isSystem = bubble.role === 'system';
  const Icon = isUser ? User : isSystem ? CheckCircle2 : Bot;
  const tone = isUser
    ? 'border-slate-300 bg-slate-50 text-slate-800'
    : isSystem
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
      : 'border-sky-200 bg-sky-50 text-sky-900';
  return (
    <div className={`rounded-lg border p-3 text-xs ${tone}`}>
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider opacity-80">
        <Icon size={11} />
        {isUser ? 'Operator' : isSystem ? 'System' : 'Agent (Demo)'}
        {bubble.meta && (
          <span className="ml-2 font-normal normal-case opacity-70">
            · {bubble.meta}
          </span>
        )}
      </div>
      <div className="whitespace-pre-wrap leading-relaxed">{bubble.text}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Briefing-Werkstatt panel
// ---------------------------------------------------------------------------

export function BriefingPanel({ cap }: { cap: OlsLabel }) {
  const queryClient = useQueryClient();
  const [selectedCorrelationId, setSelectedCorrelationId] = useState<string>('');
  const [chat, setChat] = useState<ChatBubble[]>([]);
  const [draftBody, setDraftBody] = useState<string>('');
  const [draftTitle, setDraftTitle] = useState<string>('');

  const correlationsQuery = useQuery({
    queryKey: ['uc4.correlations', cap],
    queryFn: () => listCorrelations(cap),
  });
  const briefingsQuery = useQuery({
    queryKey: ['uc4.briefings', cap],
    queryFn: () => listBriefings(cap),
  });

  const draftMutation = useMutation({
    mutationFn: async (correlationId: string): Promise<{
      correlation: CorrelationEvent;
      entities: MultiSourceEntity[];
    }> => {
      const correlation = (correlationsQuery.data ?? []).find(
        (c) => c.correlation_id === correlationId,
      );
      if (!correlation) {
        throw new Error('Korrelation nicht gefunden — bitte Liste neu laden.');
      }
      // graph_query has no per-correlation filter; pull the top
      // multi-source entities of the last 168h (one week) and filter
      // client-side for entities whose correlation_ids include this one.
      const gqResp = await graphQuery(
        {
          pattern: 'multi_source_entity',
          args: { hours: 168, min_correlations: 2 },
        },
        cap,
      );
      const all =
        'entities' in (gqResp.data ?? {})
          ? ((gqResp.data as { entities: MultiSourceEntity[] | null }).entities ?? [])
          : [];
      const matching = all.filter((e) =>
        e.correlation_ids?.includes(correlationId),
      );
      const entities = matching.length > 0 ? matching : all.slice(0, 5);
      return { correlation, entities };
    },
    onSuccess: ({ correlation, entities }) => {
      const title = correlation.summary
        ? `${correlation.correlation_kind} — ${correlation.summary.slice(0, 60)}`
        : `Lagebild ${correlation.correlation_kind}`;
      const body = synthesiseBody(correlation, entities);
      setDraftTitle(title.slice(0, 200));
      setDraftBody(body);
      setChat((prev) => [
        ...prev,
        {
          id: `user-${Date.now()}`,
          role: 'user',
          text: `Briefing-Draft für Korrelation ${correlation.correlation_id.slice(0, 8)}…`,
          meta: correlation.correlation_kind,
        },
        {
          id: `agent-${Date.now()}`,
          role: 'agent',
          text: body,
          meta: `Template-Draft auf Basis von ${entities.length} Entität${entities.length === 1 ? '' : 'en'}`,
        },
      ]);
    },
    onError: (err: Error) => {
      setChat((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: 'system',
          text: `Draft fehlgeschlagen: ${err.message}`,
        },
      ]);
    },
  });

  const persistMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCorrelationId) throw new Error('Keine Korrelation gewählt.');
      if (!draftTitle || !draftBody) throw new Error('Kein Draft erzeugt.');
      const resp = await persistBriefing(
        {
          briefing: {
            title: draftTitle,
            summary: draftBody,
            classification: classFromCap(cap),
            findings: [{ text: draftBody.slice(0, 200) }],
            confidence: 0.82,
            correlation_id: selectedCorrelationId,
            tags: ['demo', 'template-draft'],
          },
        },
        cap,
      );
      return resp;
    },
    onSuccess: (resp) => {
      const briefingId =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (resp.data as any)?.briefing_id as string | undefined;
      setChat((prev) => [
        ...prev,
        {
          id: `sys-${Date.now()}`,
          role: 'system',
          text: `Briefing persistiert (ID ${briefingId?.slice(0, 8) ?? '—'}…). review_state = DRAFT.`,
          meta: `cap ${resp.ols_cap_label}`,
        },
      ]);
      queryClient.invalidateQueries({ queryKey: ['uc4.briefings', cap] });
    },
    onError: (err: Error) => {
      setChat((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: 'system',
          text: `Persistenz fehlgeschlagen: ${err.message}`,
        },
      ]);
    },
  });

  const correlations = correlationsQuery.data ?? [];
  const briefings: BriefingRow[] = briefingsQuery.data ?? [];

  const briefingHistoryBubbles = useMemo<ChatBubble[]>(
    () =>
      briefings.slice(0, 5).map((b) => ({
        id: `hist-${b.briefing_id}`,
        role: 'agent',
        text: `**${b.title}**\n\n${b.body.slice(0, 600)}${
          b.body.length > 600 ? '…' : ''
        }`,
        meta: `${formatTime(b.generated_at)} · ${b.review_state} · cap ${b.ols_label ?? '?'}`,
      })),
    [briefings],
  );

  return (
    <section
      data-testid="uc4-briefing-panel"
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <header className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <FilePlus size={16} className="text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-900">
            Briefing-Werkstatt
          </h3>
          <span className="rounded-md border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700">
            Demo: Template-Draft
          </span>
        </div>
        <button
          type="button"
          onClick={() =>
            queryClient.invalidateQueries({
              predicate: (q) =>
                Array.isArray(q.queryKey) &&
                (q.queryKey[0] === 'uc4.correlations' ||
                  q.queryKey[0] === 'uc4.briefings'),
            })
          }
          className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-[11px] text-slate-600 hover:border-slate-400"
          title="Listen neu laden"
        >
          <RefreshCw size={11} /> Neu laden
        </button>
      </header>

      {/* Trigger row */}
      <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_auto]">
        <select
          value={selectedCorrelationId}
          onChange={(e) => setSelectedCorrelationId(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#C74634]/40"
          disabled={correlationsQuery.isLoading || correlationsQuery.isError}
        >
          <option value="">
            {correlationsQuery.isLoading
              ? 'Lade Korrelationen…'
              : correlationsQuery.isError
                ? 'Fehler beim Laden'
                : correlations.length === 0
                  ? 'Keine Korrelationen unter aktuellem Cap'
                  : `Korrelation auswählen (${correlations.length})`}
          </option>
          {correlations.map((c) => (
            <option key={c.correlation_id} value={c.correlation_id}>
              [{c.correlation_kind}]{' '}
              {(c.summary ?? c.correlation_id.slice(0, 8)).slice(0, 80)}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={() => draftMutation.mutate(selectedCorrelationId)}
          disabled={!selectedCorrelationId || draftMutation.isPending}
          className="inline-flex items-center justify-center gap-1 rounded-md border border-slate-800 bg-slate-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {draftMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
          Draft erstellen
        </button>

        <button
          type="button"
          onClick={() => persistMutation.mutate()}
          disabled={!draftBody || persistMutation.isPending}
          className="inline-flex items-center justify-center gap-1 rounded-md border border-[#C74634] bg-[#C74634] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#A03A2C] disabled:opacity-50"
        >
          {persistMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <ClipboardCheck size={12} />}
          Persistieren
        </button>
      </div>

      {/* Chat thread */}
      <div className="mb-3 max-h-72 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
        {chat.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-6 text-xs text-slate-500">
            <MessageSquare size={14} />
            Wähle eine Korrelation und klicke „Draft erstellen".
          </div>
        ) : (
          chat.map((b) => <Bubble key={b.id} bubble={b} />)
        )}
      </div>

      {/* Recent briefings header */}
      <div className="border-t border-slate-200 pt-3">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Bestehende Briefings (Top 5)
          </h4>
          <span className="text-[11px] text-slate-400">
            cap {cap} · {briefings.length} sichtbar
          </span>
        </div>
        {briefingsQuery.isError ? (
          <div className="flex items-center gap-2 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
            <AlertTriangle size={12} /> Briefings konnten nicht geladen werden.
          </div>
        ) : briefings.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-300 bg-white p-3 text-center text-xs text-slate-500">
            Noch keine Briefings unter diesem Cap.
          </div>
        ) : (
          <div className="space-y-2">
            {briefingHistoryBubbles.map((b) => (
              <Bubble key={b.id} bubble={b} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

export default BriefingPanel;
