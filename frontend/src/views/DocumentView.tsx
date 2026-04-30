import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Send, FileText } from 'lucide-react';
import { docs } from '../services/api';
import type { RagCitation, RagMessage } from '../types';

// Extracts inline citations written as [doc_id:chunk_idx] from assistant text.
function extractInlineCitations(text: string): RagCitation[] {
  const pattern = /\[([A-Za-z0-9_-]+):(\d+)\]/g;
  const hits: RagCitation[] = [];
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(text)) !== null) {
    hits.push({ doc_id: m[1], chunk_idx: Number(m[2]) });
  }
  return hits;
}

function CitationBadge({
  citation,
  onClick,
}: {
  citation: RagCitation;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mr-1 mt-1 inline-flex items-center rounded-md border border-slate-300 bg-white px-1.5 py-0.5 text-[10px] font-mono text-slate-700 hover:border-[#C74634] hover:text-[#C74634]"
    >
      [{citation.doc_id}:{citation.chunk_idx}]
    </button>
  );
}

function MessageBubble({
  msg,
  onCitation,
}: {
  msg: RagMessage;
  onCitation: (c: RagCitation) => void;
}) {
  const isUser = msg.role === 'user';
  const citations = msg.citations ?? extractInlineCitations(msg.content);
  return (
    <div
      className={['flex', isUser ? 'justify-end' : 'justify-start'].join(' ')}
    >
      <div
        className={[
          'max-w-[75%] rounded-2xl px-4 py-3 text-sm shadow-sm',
          isUser
            ? 'bg-[#C74634] text-white'
            : 'bg-slate-100 text-slate-900',
        ].join(' ')}
      >
        <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
        {!isUser && citations.length > 0 && (
          <div className="mt-2 flex flex-wrap">
            {citations.map((c, idx) => (
              <CitationBadge
                key={`${c.doc_id}-${c.chunk_idx}-${idx}`}
                citation={c}
                onClick={() => onCitation(c)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function DocumentView() {
  const [messages, setMessages] = useState<RagMessage[]>([
    {
      role: 'assistant',
      content:
        'Willkommen. Stellen Sie Fragen zu klassifizierten Dokumenten. Antworten enthalten Belege als [doc_id:chunk_idx].',
    },
  ]);
  const [input, setInput] = useState('');
  const [activeCitation, setActiveCitation] = useState<RagCitation | null>(
    null,
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  const chatMutation = useMutation({
    mutationFn: (history: RagMessage[]) => docs.ragChat(history),
    onSuccess: (reply) => {
      setMessages((prev) => [...prev, reply]);
    },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, chatMutation.isPending]);

  const handleSend = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || chatMutation.isPending) return;
    const next: RagMessage[] = [
      ...messages,
      { role: 'user', content: trimmed },
    ];
    setMessages(next);
    setInput('');
    chatMutation.mutate(next);
  };

  return (
    <section className="grid h-[calc(100vh-7rem)] grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
      {/* Chat pane */}
      <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-5 py-3">
          <h2 className="text-base font-semibold text-slate-900">
            RAG-Chat über klassifizierte Dokumente
          </h2>
          <p className="text-xs text-slate-500">
            OLS-Label erzwingt Freigabestufen (U / R / C / S / VS-NfD).
          </p>
        </div>

        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-5">
          {messages.map((m, idx) => (
            <MessageBubble
              key={idx}
              msg={m}
              onCitation={(c) => setActiveCitation(c)}
            />
          ))}
          {chatMutation.isPending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-500">
                Assistent antwortet...
              </div>
            </div>
          )}
          {chatMutation.isError && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              Fehler beim Abrufen der Antwort.
            </div>
          )}
        </div>

        <form
          onSubmit={handleSend}
          className="flex items-center gap-2 border-t border-slate-200 bg-slate-50 px-4 py-3"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Frage stellen..."
            className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-[#C74634] focus:ring-2 focus:ring-[#C74634]/30"
          />
          <button
            type="submit"
            disabled={!input.trim() || chatMutation.isPending}
            className="flex items-center gap-2 rounded-md bg-[#C74634] px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-[#A33A2C] disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            <Send size={14} />
            Senden
          </button>
        </form>
      </div>

      {/* Source panel */}
      <aside className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center gap-2 border-b border-slate-200 px-5 py-3">
          <FileText size={16} className="text-[#C74634]" />
          <h3 className="text-sm font-semibold text-slate-900">Quelle</h3>
        </div>
        <div className="flex-1 overflow-y-auto p-5 text-sm">
          {activeCitation ? (
            <div className="space-y-3">
              <div>
                <div className="text-xs uppercase tracking-wider text-slate-500">
                  Dokument
                </div>
                <div className="font-mono text-xs text-slate-900">
                  {activeCitation.doc_id}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-slate-500">
                  Chunk
                </div>
                <div className="font-mono text-xs text-slate-900">
                  #{activeCitation.chunk_idx}
                </div>
              </div>
              {activeCitation.snippet && (
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                  {activeCitation.snippet}
                </div>
              )}
            </div>
          ) : (
            <div className="text-xs text-slate-500">
              Klicken Sie auf eine Beleg-Badge im Chat, um das Quelldokument
              anzuzeigen.
            </div>
          )}
        </div>
      </aside>
    </section>
  );
}

export default DocumentView;
