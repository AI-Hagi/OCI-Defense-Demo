/**
 * UC4 Chat-Werkstatt — streaming LLM chat over the existing tool catalogue.
 *
 * Today only `flights_query` is wired in the backend (Step 1). The panel
 * is shaped so that ais/jamming/graph tools land without UI churn — every
 * incoming `tool_call` event renders the same neutral tool-card.
 *
 * The cap is owned by the parent (Uc4ToolsView) and read-only here, in line
 * with the existing pattern used by MultiCorrelationPanel / SpatialHeatmapPanel.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Send,
  User,
  Wrench,
} from 'lucide-react';
import {
  openChat,
  type ChatEvent,
  type ChatHandle,
  type ChatTurn,
  type OlsLabel,
} from '../services/uc4Chat';
import {
  dispatchMapAction,
  parseMapActionEvent,
} from '../state/mapActions';

interface OperatorMessage {
  kind: 'operator';
  text: string;
}
interface AgentMessage {
  kind: 'agent';
  text: string;
  model: string;
  hops: number;
  forced: boolean;
}
interface ToolCallMessage {
  kind: 'tool';
  tool: string;
  args: Record<string, unknown>;
  ok: boolean | null;
  durationMs: number | null;
  error: string | null;
  summary: Record<string, unknown> | null;
}
interface SystemMessage {
  kind: 'system';
  text: string;
}
interface MapActionMessage {
  kind: 'map_action';
  text: string;
}
interface ErrorMessage {
  kind: 'error';
  text: string;
}

type ChatMessage =
  | OperatorMessage
  | AgentMessage
  | ToolCallMessage
  | SystemMessage
  | MapActionMessage
  | ErrorMessage;

const SUGGESTIONS: { question: string; label: string }[] = [
  {
    question: 'Welche militärischen Flugzeuge fliegen gerade über Deutschland?',
    label: 'Mil über DE',
  },
  {
    question: 'Wie viele zivile Maschinen sind aktuell über DE in der Luft?',
    label: 'Zivil über DE',
  },
  {
    question: 'Zeige mir die zivile und militärische Luftlage über Mitteleuropa.',
    label: 'Luftlage gesamt',
  },
  {
    question: 'Aktiviere den Maritime-Layer und zoom auf die Ostsee.',
    label: 'Lagebild: Ostsee',
  },
];

interface ChatPanelProps {
  cap: OlsLabel;
}

export function ChatPanel({ cap }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const handleRef = useRef<ChatHandle | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  // History sent to the LLM — only finalised operator/agent turns.
  const llmHistory: ChatTurn[] = useMemo(() => {
    const out: ChatTurn[] = [];
    for (const m of messages) {
      if (m.kind === 'operator') out.push({ role: 'USER', message: m.text });
      else if (m.kind === 'agent') out.push({ role: 'CHATBOT', message: m.text });
    }
    return out;
  }, [messages]);

  useEffect(() => {
    return () => handleRef.current?.cancel();
  }, []);

  useEffect(() => {
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function send(question: string) {
    const trimmed = question.trim();
    if (!trimmed || streaming) return;
    setMessages((prev) => [...prev, { kind: 'operator', text: trimmed }]);
    setDraft('');
    setStreaming(true);

    const history = llmHistory;

    handleRef.current = openChat({
      question: trimmed,
      olsCap: cap,
      history,
      onEvent: (evt) => {
        if (evt.type === 'map_action') {
          // Dispatch the typed action to the LagebildView subscriber and
          // fold a confirmation message into the chat log.
          const parsed = parseMapActionEvent(evt as unknown as Record<string, unknown>);
          if (parsed) dispatchMapAction(parsed);
        }
        setMessages((prev) => folder(prev, evt));
      },
      onClose: () => {
        setStreaming(false);
        handleRef.current = null;
      },
    });
  }

  return (
    <section
      data-testid="uc4-chat-panel"
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MessageSquare size={16} className="text-[#C74634]" />
          <h3 className="text-sm font-semibold text-slate-900">
            Chat-Werkstatt — Lagefragen an den UC4-Assistenten
          </h3>
        </div>
        <span className="text-[11px] text-slate-500">
          Cap: <strong className="text-slate-700">{cap}</strong> · Tool-Loop max 5 Hops
        </span>
      </header>

      <p className="mt-1 text-xs text-slate-600">
        Beantwortet Fragen zu Luft-, Maritimer- und EW-Lage über die registrierten
        UC4-Tools. Erfindet keine Flugzeuge — wenn das Tool leer zurückkommt, sagt
        der Assistent das so. Plattform-Disziplin: keine kinetischen Empfehlungen.
      </p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => send(s.question)}
            disabled={streaming}
            className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {s.label}
          </button>
        ))}
      </div>

      <div
        ref={scrollerRef}
        data-testid="uc4-chat-log"
        className="mt-3 h-[280px] overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs"
      >
        {messages.length === 0 && !streaming && (
          <div className="text-slate-500">
            Tippen Sie eine Frage oder wählen Sie einen Vorschlag oben.
          </div>
        )}
        <ul className="space-y-2">
          {messages.map((m, idx) => (
            <li key={idx}>{renderMessage(m)}</li>
          ))}
          {streaming && (
            <li className="flex items-center gap-2 text-slate-500">
              <Loader2 size={12} className="animate-spin" />
              <span>verarbeite Anfrage…</span>
            </li>
          )}
        </ul>
      </div>

      <form
        className="mt-3 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Frage an den UC4-Assistenten…"
          disabled={streaming}
          className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-[#C74634] focus:outline-none disabled:bg-slate-100"
          data-testid="uc4-chat-input"
        />
        <button
          type="submit"
          disabled={streaming || !draft.trim()}
          className="flex items-center gap-1 rounded-md bg-[#C74634] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#A53A2A] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send size={12} />
          Senden
        </button>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Pure event → message-list reducer (exported so it can be unit-tested).
// ---------------------------------------------------------------------------
export function folder(prev: ChatMessage[], evt: ChatEvent): ChatMessage[] {
  switch (evt.type) {
    case 'started':
      return [
        ...prev,
        { kind: 'system', text: `Sitzung gestartet (Cap: ${evt.ols_cap}).` },
      ];
    case 'tool_call':
      return [
        ...prev,
        {
          kind: 'tool',
          tool: evt.tool,
          args: evt.args,
          ok: null,
          durationMs: null,
          error: null,
          summary: null,
        },
      ];
    case 'tool_result': {
      // Update the last matching tool-call entry in place.
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i--) {
        const m = next[i];
        if (m.kind === 'tool' && m.tool === evt.tool && m.ok === null) {
          next[i] = {
            ...m,
            ok: evt.ok,
            durationMs: evt.duration_ms,
            error: evt.error,
            summary: evt.summary,
          };
          return next;
        }
      }
      return next;
    }
    case 'answer':
      return [
        ...prev,
        {
          kind: 'agent',
          text: evt.text,
          model: evt.model,
          hops: evt.hops,
          forced: evt.forced ?? false,
        },
      ];
    case 'error':
      return [...prev, { kind: 'error', text: evt.message }];
    case 'map_action': {
      const text = describeMapAction(evt);
      return [...prev, { kind: 'map_action', text }];
    }
  }
}

function describeMapAction(evt: {
  action: string;
  lat?: number;
  lon?: number;
  zoom_km?: number;
  layer?: string;
  entity_ids?: string[];
}): string {
  switch (evt.action) {
    case 'flyto':
      return `Lagebild: flyto → ${evt.lat?.toFixed(3)}, ${evt.lon?.toFixed(3)}${
        evt.zoom_km ? ` · ${evt.zoom_km} km` : ''
      }`;
    case 'enable_layer':
      return `Lagebild: Layer aktiviert → ${evt.layer}`;
    case 'disable_layer':
      return `Lagebild: Layer deaktiviert → ${evt.layer}`;
    case 'highlight_entities':
      return `Lagebild: ${evt.entity_ids?.length ?? 0} Entities markiert`;
    default:
      return `Lagebild-Aktion: ${evt.action}`;
  }
}

// ---------------------------------------------------------------------------
// Per-message rendering
// ---------------------------------------------------------------------------
function renderMessage(m: ChatMessage) {
  if (m.kind === 'operator') {
    return (
      <div className="flex items-start gap-2">
        <User size={14} className="mt-0.5 shrink-0 text-slate-500" />
        <div className="rounded-md bg-white px-2 py-1.5 text-slate-800 ring-1 ring-slate-200">
          {m.text}
        </div>
      </div>
    );
  }
  if (m.kind === 'agent') {
    return (
      <div className="flex items-start gap-2">
        <Bot size={14} className="mt-0.5 shrink-0 text-[#C74634]" />
        <div className="rounded-md bg-[#FFF6F4] px-2 py-1.5 text-slate-800 ring-1 ring-rose-200">
          <div>{m.text}</div>
          <div className="mt-1 text-[10px] text-slate-500">
            {m.model} · {m.hops} Hop{m.hops === 1 ? '' : 's'}
            {m.forced && ' · max-hops erzwungen'}
          </div>
        </div>
      </div>
    );
  }
  if (m.kind === 'tool') {
    const status =
      m.ok === null ? 'läuft…' : m.ok ? `${(m.durationMs ?? 0).toFixed(0)} ms` : 'Fehler';
    const argsText = formatArgs(m.args);
    return (
      <div className="flex items-start gap-2">
        <Wrench size={14} className="mt-0.5 shrink-0 text-slate-400" />
        <div className="flex-1 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-slate-700">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] font-semibold">{m.tool}</span>
            <span className="text-[10px] text-slate-500">{status}</span>
          </div>
          {argsText && (
            <div className="mt-0.5 truncate font-mono text-[10px] text-slate-500">
              {argsText}
            </div>
          )}
          {m.error && (
            <div className="mt-1 flex items-start gap-1 text-[10px] text-rose-700">
              <AlertTriangle size={10} className="mt-0.5 shrink-0" />
              <span>{m.error}</span>
            </div>
          )}
          {m.ok === true && m.summary && (
            <div className="mt-0.5 flex items-center gap-1 text-[10px] text-emerald-700">
              <CheckCircle2 size={10} className="shrink-0" />
              <span>{summariseTool(m.summary)}</span>
            </div>
          )}
        </div>
      </div>
    );
  }
  if (m.kind === 'system') {
    return <div className="text-[10px] uppercase tracking-wide text-slate-400">{m.text}</div>;
  }
  if (m.kind === 'map_action') {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] text-amber-900">
        {m.text}
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2 text-rose-800">
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <div className="rounded-md bg-rose-50 px-2 py-1.5 ring-1 ring-rose-200">{m.text}</div>
    </div>
  );
}

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args).filter(([, v]) => v !== undefined && v !== null);
  if (entries.length === 0) return '';
  return entries.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join('  ');
}

function summariseTool(summary: Record<string, unknown>): string {
  // Per-tool shape:
  //   flights_query  → { counts: {civil, mil}, sample_count }
  //   jamming_query  → { buckets: {low, moderate, high, unknown}, total, sample_count }
  //   ais_query      → { count, sample_count, window_seconds }
  //   graph_query    → { count, sample_count, pattern, request_id, ols_cap_label }
  const counts = summary.counts as Record<string, number> | undefined;
  const buckets = summary.buckets as Record<string, number> | undefined;
  const sample = summary.sample_count != null ? ` · ${summary.sample_count} Samples` : '';
  if (counts) {
    return Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(', ') + sample;
  }
  if (buckets) {
    const nonzero = Object.entries(buckets).filter(([, v]) => Number(v) > 0);
    const total = summary.total != null ? `${summary.total} Zonen` : 'Zonen';
    if (nonzero.length === 0) return `${total}${sample}`;
    const parts = nonzero.map(([k, v]) => `${k}: ${v}`).join(', ');
    return `${total} · ${parts}${sample}`;
  }
  if (typeof summary.count === 'number') {
    const pattern = typeof summary.pattern === 'string' ? ` (${summary.pattern})` : '';
    const window = summary.window_seconds != null ? ` · ${summary.window_seconds}s Fenster` : '';
    return `${summary.count} Treffer${pattern}${window}${sample}`;
  }
  if (typeof summary.error === 'string') {
    return `Fehler: ${summary.error}`;
  }
  return JSON.stringify(summary).slice(0, 80);
}
