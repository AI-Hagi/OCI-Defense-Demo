/**
 * UC4 Briefing-Werkstatt — automated + manual briefing composition.
 *
 * Two modes share one OAuth-gated persist contract (POST /api/uc4/tools/persist_briefing):
 *
 *   1. Automatisch (Agent)
 *      - Pick a correlation, pick an agent profile, click "Draft erstellen".
 *      - The selected agent fetches multi-source entities via graph_query and
 *        synthesises a German draft. Today only the deterministic template
 *        agent ("Demo-Template") is wired — Llama 3.3 / Cohere R+ slots are
 *        present so a future ChatCompletion call drops in without UI churn.
 *      - The draft populates the editable form so the operator can tweak it
 *        before persisting.
 *
 *   2. Manuell (Operator)
 *      - Pick a correlation, type the briefing yourself, persist.
 *      - The form fields are the same as in auto mode.
 *
 * The chat thread tracks both flows: operator action, agent (or operator)
 * response, system persistence confirmation. A live history of past
 * briefings renders below.
 */
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  Edit3,
  FilePlus,
  Loader2,
  MessageSquare,
  RefreshCw,
  Sparkles,
  User,
  Wand2,
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

function clampClassification(
  current: 'OFFEN' | 'INTERN' | 'NFD',
  cap: OlsLabel,
): 'OFFEN' | 'INTERN' | 'NFD' {
  // Tool rejects 403 if classification > cap. Demote silently when needed.
  const rank = { OFFEN: 10, INTERN: 30, NFD: 50, GEHEIM: 70 } as const;
  return rank[current] <= rank[cap] ? current : classFromCap(cap);
}

// ---------------------------------------------------------------------------
// Agent profiles — today only the deterministic template synthesizer runs.
// Llama 3.3 / Cohere R+ are placeholders so the dropdown shape stays stable.
// ---------------------------------------------------------------------------
type AgentId = 'template-demo' | 'llama3-70b' | 'cohere-r-plus';

interface AgentProfile {
  id: AgentId;
  label: string;
  available: boolean;
  hint: string;
}

const AGENTS: AgentProfile[] = [
  {
    id: 'template-demo',
    label: 'Demo-Template (deterministisch)',
    available: true,
    hint: 'Frontend-Synthese aus correlation + graph_query. OAuth + OLS unverändert.',
  },
  {
    id: 'llama3-70b',
    label: 'Llama 3.3 70B (on-demand)',
    available: false,
    hint: 'Threat-Fusion-Agent deployed, tool-runtime hat opakes 500. Sobald gefixt, ein Drop-in.',
  },
  {
    id: 'cohere-r-plus',
    label: 'Cohere Command R+ (Dedicated AI Cluster)',
    available: false,
    hint: 'Procurement-Ziel; deployment-blocked auf LARGE_COHERE-Limit-SR.',
  },
];

// ---------------------------------------------------------------------------
// Deterministic German-language briefing synthesizer (template-demo agent)
// ---------------------------------------------------------------------------

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

type Mode = 'auto' | 'manual';

export function BriefingPanel({ cap }: { cap: OlsLabel }) {
  const queryClient = useQueryClient();

  // Header / mode
  const [mode, setMode] = useState<Mode>('auto');
  const [agentId, setAgentId] = useState<AgentId>('template-demo');

  // Form fields shared by both modes
  const [selectedCorrelationId, setSelectedCorrelationId] = useState<string>('');
  const [title, setTitle] = useState<string>('');
  const [body, setBody] = useState<string>('');
  const [classification, setClassification] = useState<'OFFEN' | 'INTERN' | 'NFD'>(
    classFromCap(cap),
  );
  const [confidence, setConfidence] = useState<number>(0.82);
  const [tagsInput, setTagsInput] = useState<string>('demo,template-draft');

  // Chat thread
  const [chat, setChat] = useState<ChatBubble[]>([]);

  // Data
  const correlationsQuery = useQuery({
    queryKey: ['uc4.correlations', cap],
    queryFn: () => listCorrelations(cap),
  });
  const briefingsQuery = useQuery({
    queryKey: ['uc4.briefings', cap],
    queryFn: () => listBriefings(cap),
  });

  // Auto-draft mutation
  const draftMutation = useMutation({
    mutationFn: async (correlationId: string): Promise<{
      correlation: CorrelationEvent;
      entities: MultiSourceEntity[];
      agent: AgentProfile;
    }> => {
      const correlation = (correlationsQuery.data ?? []).find(
        (c) => c.correlation_id === correlationId,
      );
      if (!correlation) {
        throw new Error('Korrelation nicht gefunden — bitte Liste neu laden.');
      }
      const agent = AGENTS.find((a) => a.id === agentId) ?? AGENTS[0];
      if (!agent.available) {
        throw new Error(
          `Agent „${agent.label}" ist aktuell nicht verfügbar. ${agent.hint}`,
        );
      }
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
      return { correlation, entities, agent };
    },
    onSuccess: ({ correlation, entities, agent }) => {
      const newTitle = (correlation.summary
        ? `${correlation.correlation_kind} — ${correlation.summary.slice(0, 60)}`
        : `Lagebild ${correlation.correlation_kind}`
      ).slice(0, 200);
      const newBody = synthesiseBody(correlation, entities);
      setTitle(newTitle);
      setBody(newBody);
      setClassification(clampClassification('NFD', cap));
      setTagsInput('demo,template-draft');
      setChat((prev) => [
        ...prev,
        {
          id: `user-${Date.now()}`,
          role: 'user',
          text: `Auto-Draft mit „${agent.label}" für Korrelation ${correlation.correlation_id.slice(0, 8)}…`,
          meta: correlation.correlation_kind,
        },
        {
          id: `agent-${Date.now()}`,
          role: 'agent',
          text: newBody,
          meta: `${entities.length} Entität${entities.length === 1 ? '' : 'en'} · ${agent.label}`,
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

  // Persist mutation — same payload for auto + manual modes.
  const persistMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCorrelationId) throw new Error('Keine Korrelation gewählt.');
      if (!title.trim()) throw new Error('Titel ist leer.');
      if (!body.trim()) throw new Error('Briefing-Text ist leer.');
      const safeClass = clampClassification(classification, cap);
      const tags = tagsInput
        .split(',')
        .map((t) => t.trim())
        .filter((t) => t.length > 0);
      const resp = await persistBriefing(
        {
          briefing: {
            title: title.slice(0, 200),
            summary: body.slice(0, 3800),
            classification: safeClass,
            findings: [{ text: body.slice(0, 200) }],
            confidence: Math.max(0, Math.min(1, confidence)),
            correlation_id: selectedCorrelationId,
            tags: tags.length > 0 ? tags : ['demo'],
          },
        },
        cap,
      );
      return { resp, source: mode };
    },
    onSuccess: ({ resp, source }) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const briefingId = (resp.data as any)?.briefing_id as string | undefined;
      // In manual mode the user typed the body — surface it as an Operator bubble
      // first so the chat thread reads as a complete dialog.
      const next: ChatBubble[] = [];
      if (source === 'manual') {
        next.push({
          id: `user-${Date.now()}`,
          role: 'user',
          text: `**${title}**\n\n${body.slice(0, 600)}${body.length > 600 ? '…' : ''}`,
          meta: 'Manuell verfasst',
        });
      }
      next.push({
        id: `sys-${Date.now()}`,
        role: 'system',
        text: `Briefing persistiert (ID ${briefingId?.slice(0, 8) ?? '—'}…). review_state = DRAFT.`,
        meta: `cap ${resp.ols_cap_label} · ${source === 'auto' ? 'Auto' : 'Manuell'}`,
      });
      setChat((prev) => [...prev, ...next]);
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
        text: `**${b.title}**\n\n${b.body.slice(0, 600)}${b.body.length > 600 ? '…' : ''}`,
        meta: `${formatTime(b.generated_at)} · ${b.review_state} · cap ${b.ols_label ?? '?'}`,
      })),
    [briefings],
  );

  const persistDisabled =
    !selectedCorrelationId ||
    !title.trim() ||
    !body.trim() ||
    persistMutation.isPending;

  return (
    <section
      data-testid="uc4-briefing-panel"
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      {/* Header */}
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <FilePlus size={16} className="text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-900">
            Briefing-Werkstatt
          </h3>
          <span className="rounded-md border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700">
            Auto · Manuell
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Mode segmented control */}
          <div className="inline-flex overflow-hidden rounded-md border border-slate-300 text-[11px]">
            <button
              type="button"
              onClick={() => setMode('auto')}
              className={`flex items-center gap-1 px-3 py-1 ${
                mode === 'auto'
                  ? 'bg-slate-800 text-white'
                  : 'bg-white text-slate-700 hover:bg-slate-50'
              }`}
              data-testid="briefing-mode-auto"
            >
              <Sparkles size={11} /> Automatisch
            </button>
            <button
              type="button"
              onClick={() => setMode('manual')}
              className={`flex items-center gap-1 px-3 py-1 ${
                mode === 'manual'
                  ? 'bg-slate-800 text-white'
                  : 'bg-white text-slate-700 hover:bg-slate-50'
              }`}
              data-testid="briefing-mode-manual"
            >
              <Edit3 size={11} /> Manuell
            </button>
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
        </div>
      </header>

      {/* Trigger / source row */}
      <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto] lg:grid-cols-[1fr_auto_auto]">
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

        {mode === 'auto' && (
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value as AgentId)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#C74634]/40"
            title="Agent-Profil"
          >
            {AGENTS.map((a) => (
              <option key={a.id} value={a.id} disabled={!a.available}>
                {a.label}
                {!a.available ? ' (n/a)' : ''}
              </option>
            ))}
          </select>
        )}

        {mode === 'auto' ? (
          <button
            type="button"
            onClick={() => draftMutation.mutate(selectedCorrelationId)}
            disabled={!selectedCorrelationId || draftMutation.isPending}
            className="inline-flex items-center justify-center gap-1 rounded-md border border-slate-800 bg-slate-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {draftMutation.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Wand2 size={12} />
            )}
            Draft erstellen
          </button>
        ) : (
          <span className="hidden text-[11px] text-slate-500 lg:inline-flex lg:items-center">
            Manuelle Eingabe — Felder unten
          </span>
        )}
      </div>

      {/* Editable form — visible in both modes. In manual mode it starts empty;
          in auto mode it pre-fills after a successful draft. */}
      <div className="mb-3 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-[2fr_1fr]">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={
              mode === 'manual'
                ? 'Titel — z. B. „Lagebild Bornholm Deep, 24 h"'
                : 'Titel (vom Agent vorgeschlagen, editierbar)'
            }
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#C74634]/40"
            maxLength={200}
            data-testid="briefing-title"
          />
          <div className="flex items-center gap-2">
            <select
              value={classification}
              onChange={(e) =>
                setClassification(e.target.value as 'OFFEN' | 'INTERN' | 'NFD')
              }
              className="flex-1 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#C74634]/40"
              title="Klassifikation"
            >
              <option value="OFFEN">OFFEN (10)</option>
              <option value="INTERN">INTERN (30)</option>
              <option value="NFD">NFD (50)</option>
            </select>
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              value={confidence}
              onChange={(e) => setConfidence(Number(e.target.value))}
              className="w-20 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#C74634]/40"
              title="Konfidenz [0..1]"
            />
          </div>
        </div>

        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={mode === 'manual' ? 10 : 8}
          placeholder={
            mode === 'manual'
              ? 'Briefing-Text — Markdown ist erlaubt. ≤ 4000 Zeichen.'
              : 'Briefing-Text (vom Agent erzeugt, editierbar)'
          }
          className="w-full resize-y rounded-md border border-slate-300 bg-white px-2 py-1.5 font-mono text-[11px] leading-relaxed text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#C74634]/40"
          maxLength={4000}
          data-testid="briefing-body"
        />

        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            placeholder="tags, komma-getrennt"
            className="flex-1 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#C74634]/40"
            data-testid="briefing-tags"
          />
          <span className="text-[11px] text-slate-500">
            {body.length} / 4000 Zeichen
          </span>
          <button
            type="button"
            onClick={() => persistMutation.mutate()}
            disabled={persistDisabled}
            className="inline-flex items-center justify-center gap-1 rounded-md border border-[#C74634] bg-[#C74634] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#A03A2C] disabled:opacity-50"
            data-testid="briefing-persist"
          >
            {persistMutation.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <ClipboardCheck size={12} />
            )}
            Persistieren
          </button>
        </div>
      </div>

      {/* Chat thread */}
      <div className="mb-3 max-h-72 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
        {chat.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-6 text-xs text-slate-500">
            <MessageSquare size={14} />
            {mode === 'auto'
              ? 'Wähle eine Korrelation, einen Agent und klicke „Draft erstellen".'
              : 'Wähle eine Korrelation und verfasse das Briefing manuell.'}
          </div>
        ) : (
          chat.map((b) => <Bubble key={b.id} bubble={b} />)
        )}
      </div>

      {/* History */}
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
