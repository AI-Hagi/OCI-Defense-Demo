import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/helpers';
import { calls } from '../../test/msw-server';

async function loadView() {
  const mod = await import('../DocumentView');
  return mod.default ?? (mod as Record<string, unknown>).DocumentView;
}

describe('DocumentView (london school)', () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it('renders a chat input', async () => {
    const View = await loadView();
    renderWithProviders(<View />);
    // Chat input — narrowed via placeholder so it doesn't collide with the
// upload widget's title field (also a textbox role).
const input = await screen.findByPlaceholderText(/Frage stellen/);
    expect(input).toBeInTheDocument();
  });

  it('sends a POST to /chat with the last message role=user when the user submits', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    const user = userEvent.setup();
    // Chat input — narrowed via placeholder so it doesn't collide with the
// upload widget's title field (also a textbox role).
const input = await screen.findByPlaceholderText(/Frage stellen/);
    await user.type(input, 'geo');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      const chat = calls.find(
        (c) =>
          c.method === 'POST' &&
          (c.url.endsWith('/api/docs/chat') || c.url.endsWith('/api/documents/chat')),
      );
      expect(chat).toBeTruthy();
      // Body shape is { messages: [...] }. The last message must be a user turn.
      const body = chat?.body as { messages?: Array<{ role: string; content: string }> };
      const last = body?.messages?.[body.messages.length - 1];
      expect(last?.role).toBe('user');
      expect(last?.content.toLowerCase()).toContain('geo');
    });
  });

  it('renders the assistant reply text and citation badges', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    const user = userEvent.setup();
    // Chat input — narrowed via placeholder so it doesn't collide with the
// upload widget's title field (also a textbox role).
const input = await screen.findByPlaceholderText(/Frage stellen/);
    await user.type(input, 'geo{Enter}');

    await waitFor(() => {
      expect(screen.getByText(/NIS2 erfordert geo-redundante Systeme\./i)).toBeInTheDocument();
    });

    // Citations should appear — the fixture has one doc_id D001.
    await waitFor(() => {
      expect(screen.getByText(/D001|NIS2 Annex/i)).toBeInTheDocument();
    });
  });
});
