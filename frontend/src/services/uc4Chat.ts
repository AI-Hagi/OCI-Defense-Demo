/**
 * Thin WebSocket client for the uc4-chat service.
 *
 * The server contract (see services/uc4-chat/app/main.py:ws_chat):
 *   • Client sends one JSON frame: { type: "ask", question, history?, ols_cap, tenant_id? }
 *   • Server streams events:
 *       { type: "started",     ols_cap }
 *       { type: "tool_call",   tool, args, hop }
 *       { type: "tool_result", tool, ok, duration_ms, error?, summary }
 *       { type: "answer",      text, model, hops, forced? }
 *       { type: "error",       message }
 *   • Server closes the socket after the answer (or on error).
 *
 * One question = one connection. The frontend opens a fresh socket per turn.
 */
export type OlsLabel = 'OFFEN' | 'INTERN' | 'NFD' | 'GEHEIM';

export interface ChatTurn {
  role: 'USER' | 'CHATBOT' | 'SYSTEM';
  message: string;
}

export interface ChatStartedEvent {
  type: 'started';
  ols_cap: OlsLabel;
}
export interface ChatToolCallEvent {
  type: 'tool_call';
  tool: string;
  args: Record<string, unknown>;
  hop: number;
}
export interface ChatToolResultEvent {
  type: 'tool_result';
  tool: string;
  ok: boolean;
  duration_ms: number;
  error: string | null;
  summary: Record<string, unknown>;
}
export interface ChatAnswerEvent {
  type: 'answer';
  text: string;
  model: string;
  hops: number;
  forced?: boolean;
}
export interface ChatErrorEvent {
  type: 'error';
  message: string;
}
export interface ChatMapActionEvent {
  type: 'map_action';
  // Mirrors backend tools/map_action.py shape.
  action: 'flyto' | 'enable_layer' | 'disable_layer' | 'highlight_entities';
  lat?: number;
  lon?: number;
  zoom_km?: number;
  layer?: string;
  entity_ids?: string[];
}

export type ChatEvent =
  | ChatStartedEvent
  | ChatToolCallEvent
  | ChatToolResultEvent
  | ChatAnswerEvent
  | ChatErrorEvent
  | ChatMapActionEvent;

export interface AskOptions {
  question: string;
  olsCap: OlsLabel;
  history?: ChatTurn[];
  tenantId?: string;
  onEvent: (event: ChatEvent) => void;
  onClose?: (clean: boolean) => void;
  // Custom URL for tests; production uses the Ingress-proxied default.
  wsUrl?: string;
  // Custom WebSocket constructor for tests.
  wsImpl?: typeof WebSocket;
}

export interface ChatHandle {
  cancel(): void;
}

const DEFAULT_PATH = '/ws/uc4-chat';

function resolveWsUrl(override?: string): string {
  if (override) return override;
  const fromEnv = import.meta.env?.VITE_UC4_CHAT_WS_URL as string | undefined;
  const raw = fromEnv ?? DEFAULT_PATH;
  if (raw.startsWith('ws://') || raw.startsWith('wss://')) return raw;
  if (typeof window === 'undefined') return raw;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const path = raw.startsWith('/') ? raw : `/${raw}`;
  return `${proto}//${window.location.host}${path}`;
}

export function openChat(opts: AskOptions): ChatHandle {
  const Ctor = opts.wsImpl ?? WebSocket;
  const url = resolveWsUrl(opts.wsUrl);
  const socket = new Ctor(url);
  let cancelled = false;

  socket.onopen = () => {
    if (cancelled) return;
    socket.send(
      JSON.stringify({
        type: 'ask',
        question: opts.question,
        history: opts.history ?? [],
        ols_cap: opts.olsCap,
        tenant_id: opts.tenantId,
      }),
    );
  };

  socket.onmessage = (msg) => {
    if (cancelled) return;
    try {
      const data = typeof msg.data === 'string' ? JSON.parse(msg.data) : msg.data;
      opts.onEvent(data as ChatEvent);
    } catch (err) {
      opts.onEvent({
        type: 'error',
        message: `parse-error: ${(err as Error).message}`,
      });
    }
  };

  socket.onerror = () => {
    if (cancelled) return;
    opts.onEvent({ type: 'error', message: 'websocket-error' });
  };

  socket.onclose = (ev) => {
    if (opts.onClose) opts.onClose(ev.code === 1000);
  };

  return {
    cancel() {
      cancelled = true;
      try {
        socket.close();
      } catch {
        /* ignore */
      }
    },
  };
}
