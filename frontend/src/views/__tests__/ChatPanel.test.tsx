/**
 * Tests for ChatPanel.
 *
 * Strategy:
 *   * The pure event-fold (`folder`) is unit-tested directly — exercises
 *     all five event types plus the tool_call → tool_result merge.
 *   * The component renders behind a fake WebSocket so we can drive the
 *     event stream deterministically.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/helpers';
import { ChatPanel, folder } from '../ChatPanel';
import type { ChatEvent } from '../../services/uc4Chat';
import {
  _resetMapActionsForTest,
  subscribeMapAction,
  type MapAction,
} from '../../state/mapActions';

// ---------------------------------------------------------------------------
// Fake WebSocket — captures sent frames and lets us push events back.
// ---------------------------------------------------------------------------
class FakeWs {
  static instances: FakeWs[] = [];
  static reset() {
    FakeWs.instances = [];
  }

  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;

  sent: string[] = [];
  closed = false;
  static OPEN = 1;
  static CLOSED = 3;
  readyState = 0;

  constructor(public url: string) {
    FakeWs.instances.push(this);
    queueMicrotask(() => {
      this.readyState = FakeWs.OPEN;
      this.onopen?.();
    });
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
    this.readyState = FakeWs.CLOSED;
    this.onclose?.({ code: 1000 });
  }
  push(evt: ChatEvent) {
    this.onmessage?.({ data: JSON.stringify(evt) });
  }
}

beforeEach(() => {
  FakeWs.reset();
  vi.stubGlobal('WebSocket', FakeWs);
  _resetMapActionsForTest();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Pure reducer
// ---------------------------------------------------------------------------
describe('folder()', () => {
  it('appends operator + agent messages and updates the matching tool_call in place', () => {
    let s: ReturnType<typeof folder> = [];
    s = folder(s, { type: 'started', ols_cap: 'NFD' });
    s = folder(s, {
      type: 'tool_call',
      tool: 'flights_query',
      args: { kind: 'mil' },
      hop: 0,
    });
    expect(s).toHaveLength(2);
    expect(s[1].kind).toBe('tool');
    if (s[1].kind === 'tool') expect(s[1].ok).toBeNull();

    s = folder(s, {
      type: 'tool_result',
      tool: 'flights_query',
      ok: true,
      duration_ms: 42,
      error: null,
      summary: { counts: { mil: 3 }, sample_count: 1 },
    });
    expect(s).toHaveLength(2);
    if (s[1].kind === 'tool') {
      expect(s[1].ok).toBe(true);
      expect(s[1].durationMs).toBe(42);
    }

    s = folder(s, {
      type: 'answer',
      text: 'fertig',
      model: 'cohere.command-r-plus',
      hops: 1,
    });
    expect(s[2].kind).toBe('agent');

    s = folder(s, { type: 'error', message: 'oh no' });
    expect(s[3].kind).toBe('error');
  });

  it('does not collapse a fresh tool_call onto a completed one', () => {
    let s: ReturnType<typeof folder> = [];
    s = folder(s, {
      type: 'tool_call',
      tool: 'flights_query',
      args: {},
      hop: 0,
    });
    s = folder(s, {
      type: 'tool_result',
      tool: 'flights_query',
      ok: true,
      duration_ms: 1,
      error: null,
      summary: {},
    });
    s = folder(s, {
      type: 'tool_call',
      tool: 'flights_query',
      args: {},
      hop: 1,
    });
    // Two separate tool entries, one completed, one pending.
    expect(s.filter((m) => m.kind === 'tool')).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Component — drives the FakeWs through a full happy-path turn.
// ---------------------------------------------------------------------------
describe('<ChatPanel /> happy path', () => {
  it('streams started → tool_call → tool_result → answer into the log', async () => {
    renderWithProviders(<ChatPanel cap="NFD" />);
    const input = screen.getByTestId('uc4-chat-input') as HTMLInputElement;
    await userEvent.type(input, 'Welche militärischen Flugzeuge fliegen über DE?');
    await userEvent.click(screen.getByRole('button', { name: /senden/i }));

    expect(screen.getByText(/Welche militärischen/)).toBeInTheDocument();

    await waitFor(() => expect(FakeWs.instances).toHaveLength(1));
    const ws = FakeWs.instances[0];
    expect(ws.sent).toHaveLength(1);
    const sent = JSON.parse(ws.sent[0]);
    expect(sent.type).toBe('ask');
    expect(sent.ols_cap).toBe('NFD');

    act(() => {
      ws.push({ type: 'started', ols_cap: 'NFD' });
      ws.push({
        type: 'tool_call',
        tool: 'flights_query',
        args: { kind: 'mil', region: 'germany' },
        hop: 0,
      });
      ws.push({
        type: 'tool_result',
        tool: 'flights_query',
        ok: true,
        duration_ms: 87,
        error: null,
        summary: { counts: { mil: 3 }, sample_count: 3 },
      });
      ws.push({
        type: 'answer',
        text: 'Drei militärische Maschinen sind aktuell über Deutschland.',
        model: 'cohere.command-r-plus',
        hops: 1,
      });
      ws.close();
    });

    await waitFor(() =>
      expect(screen.getByText(/Drei militärische Maschinen/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/flights_query/)).toBeInTheDocument();
    expect(screen.getByText(/mil: 3/)).toBeInTheDocument();
    // Input re-enabled after onclose.
    await waitFor(() => expect(input.disabled).toBe(false));
  });

  it('renders error events from the server', async () => {
    renderWithProviders(<ChatPanel cap="OFFEN" />);
    const input = screen.getByTestId('uc4-chat-input') as HTMLInputElement;
    await userEvent.type(input, 'test');
    await userEvent.click(screen.getByRole('button', { name: /senden/i }));

    await waitFor(() => expect(FakeWs.instances).toHaveLength(1));
    const ws = FakeWs.instances[0];
    act(() => {
      ws.push({ type: 'error', message: 'upstream-failed' });
      ws.close();
    });
    await waitFor(() => expect(screen.getByText(/upstream-failed/)).toBeInTheDocument());
  });

  it('disables the send button while streaming', async () => {
    renderWithProviders(<ChatPanel cap="OFFEN" />);
    const input = screen.getByTestId('uc4-chat-input');
    await userEvent.type(input, 'hi');
    const sendBtn = screen.getByRole('button', { name: /senden/i });
    fireEvent.click(sendBtn);
    await waitFor(() => expect(sendBtn).toBeDisabled());
  });

  it('dispatches map_action events to the mapActions store and folds a confirmation message', async () => {
    const observed: MapAction[] = [];
    subscribeMapAction((a) => observed.push(a));

    renderWithProviders(<ChatPanel cap="OFFEN" />);
    const input = screen.getByTestId('uc4-chat-input');
    await userEvent.type(input, 'Zoom auf Frankfurt');
    await userEvent.click(screen.getByRole('button', { name: /senden/i }));

    await waitFor(() => expect(FakeWs.instances).toHaveLength(1));
    const ws = FakeWs.instances[0];
    act(() => {
      ws.push({
        type: 'tool_call',
        tool: 'map_action',
        args: { action: 'flyto', lat: 50.11, lon: 8.68 },
        hop: 0,
      });
      ws.push({
        type: 'tool_result',
        tool: 'map_action',
        ok: true,
        duration_ms: 1,
        error: null,
        summary: {},
      });
      ws.push({
        type: 'map_action',
        action: 'flyto',
        lat: 50.11,
        lon: 8.68,
      });
      ws.push({
        type: 'answer',
        text: 'Kamera fliegt nach Frankfurt.',
        model: 'cohere.command-r-plus',
        hops: 1,
      });
      ws.close();
    });

    await waitFor(() => expect(observed).toHaveLength(1));
    expect(observed[0]).toMatchObject({ action: 'flyto', lat: 50.11, lon: 8.68 });
    await waitFor(() =>
      expect(screen.getByText(/Lagebild: flyto/)).toBeInTheDocument(),
    );
  });

  it('drops malformed map_action events silently (no dispatch, no crash)', async () => {
    const observed: MapAction[] = [];
    subscribeMapAction((a) => observed.push(a));

    renderWithProviders(<ChatPanel cap="OFFEN" />);
    const input = screen.getByTestId('uc4-chat-input');
    await userEvent.type(input, 'test');
    await userEvent.click(screen.getByRole('button', { name: /senden/i }));

    await waitFor(() => expect(FakeWs.instances).toHaveLength(1));
    const ws = FakeWs.instances[0];
    act(() => {
      // out-of-range lat — parseMapActionEvent rejects it
      ws.push({
        type: 'map_action',
        action: 'flyto',
        lat: 999,
        lon: 0,
      });
      ws.close();
    });

    // 200ms grace for any pending state flush
    await new Promise((r) => setTimeout(r, 50));
    expect(observed).toHaveLength(0);
  });
});
