/**
 * Unit tests for the uc4Chat WebSocket client.
 *
 * Focus: lifecycle + cancel + url resolution. The chat reducer ('folder')
 * lives in ChatPanel.tsx and is covered there.
 */
import { describe, it, expect, vi } from 'vitest';
import { openChat, type ChatEvent } from '../uc4Chat';

class FakeWs {
  static last: FakeWs | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  sent: string[] = [];
  closed = false;

  constructor(public url: string) {
    FakeWs.last = this;
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
    this.onclose?.({ code: 1000 });
  }
}

describe('openChat()', () => {
  it('sends an ask frame on open with the question, cap, and history', () => {
    const events: ChatEvent[] = [];
    const handle = openChat({
      question: 'Test',
      olsCap: 'NFD',
      history: [{ role: 'USER', message: 'frühere Frage' }],
      tenantId: 'T002',
      onEvent: (e) => events.push(e),
      wsUrl: 'ws://localhost:1/ws/uc4-chat',
      wsImpl: FakeWs as unknown as typeof WebSocket,
    });

    expect(FakeWs.last).not.toBeNull();
    FakeWs.last?.onopen?.();
    expect(FakeWs.last?.sent).toHaveLength(1);
    const sent = JSON.parse(FakeWs.last?.sent[0] ?? '{}');
    expect(sent).toEqual({
      type: 'ask',
      question: 'Test',
      history: [{ role: 'USER', message: 'frühere Frage' }],
      ols_cap: 'NFD',
      tenant_id: 'T002',
    });
    handle.cancel();
    expect(FakeWs.last?.closed).toBe(true);
  });

  it('forwards parsed JSON events to onEvent', () => {
    const events: ChatEvent[] = [];
    openChat({
      question: 'q',
      olsCap: 'OFFEN',
      onEvent: (e) => events.push(e),
      wsUrl: 'ws://x/ws',
      wsImpl: FakeWs as unknown as typeof WebSocket,
    });
    FakeWs.last?.onmessage?.({
      data: JSON.stringify({ type: 'started', ols_cap: 'OFFEN' }),
    });
    expect(events).toEqual([{ type: 'started', ols_cap: 'OFFEN' }]);
  });

  it('emits a parse-error event on malformed payloads', () => {
    const events: ChatEvent[] = [];
    openChat({
      question: 'q',
      olsCap: 'OFFEN',
      onEvent: (e) => events.push(e),
      wsUrl: 'ws://x/ws',
      wsImpl: FakeWs as unknown as typeof WebSocket,
    });
    FakeWs.last?.onmessage?.({ data: '{not-json' });
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe('error');
  });

  it('cancel() short-circuits late events', () => {
    const events: ChatEvent[] = [];
    const handle = openChat({
      question: 'q',
      olsCap: 'OFFEN',
      onEvent: (e) => events.push(e),
      wsUrl: 'ws://x/ws',
      wsImpl: FakeWs as unknown as typeof WebSocket,
    });
    handle.cancel();
    FakeWs.last?.onmessage?.({
      data: JSON.stringify({ type: 'answer', text: 'late', model: 'x', hops: 0 }),
    });
    expect(events).toHaveLength(0);
  });
});
