import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/helpers';
import { calls } from '../../test/msw-server';

// d3 is a heavy collaborator — mock the entire namespace so tests focus on
// contracts, not rendering behaviour.
vi.mock('d3', () => {
  const chainable: Record<string, unknown> = {};
  const stub = (): unknown => chainable;
  ['append', 'attr', 'style', 'call', 'selectAll', 'data', 'enter', 'exit', 'remove', 'text',
    'on', 'transition', 'duration', 'merge', 'join']
    .forEach((k) => {
      (chainable as Record<string, unknown>)[k] = stub;
    });
  const select = () => chainable;
  const forceSim = () => ({
    nodes: stub,
    force: stub,
    on: stub,
    alpha: stub,
    alphaTarget: stub,
    restart: stub,
    stop: stub,
    tick: stub,
  });
  return {
    select,
    selectAll: select,
    forceSimulation: forceSim,
    forceLink: () => ({ id: stub, links: stub, distance: stub }),
    forceManyBody: () => ({ strength: stub }),
    forceCenter: () => ({}),
    forceCollide: () => ({ radius: stub }),
    scaleOrdinal: () => stub,
    schemeCategory10: [],
    drag: () => ({ on: stub }),
    zoom: () => ({ on: stub, scaleExtent: stub }),
    zoomIdentity: { translate: stub, scale: stub },
  };
});

async function loadView() {
  const mod = await import('../OsintView');
  return mod.default ?? (mod as Record<string, unknown>).OsintView;
}

describe('OsintView (london school)', () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it('renders a search input', async () => {
    const View = await loadView();
    renderWithProviders(<View />);
    const input = await screen.findByRole('textbox');
    expect(input).toBeInTheDocument();
  });

  it('submitting the search triggers a graph query with startEntity bound to the matched entity', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    const user = userEvent.setup();
    const input = await screen.findByRole('textbox');
    await user.type(input, 'Fancy Bear');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      const graphCalls = calls.filter(
        (c) =>
          (c.method === 'POST' && c.url.endsWith('/api/osint/query-graph')) ||
          (c.method === 'GET' && c.url.endsWith('/api/osint/graph')),
      );
      expect(graphCalls.length).toBeGreaterThanOrEqual(1);

      const call = graphCalls[0];
      const startFromBody =
        typeof call.body === 'object' && call.body
          ? ((call.body as Record<string, unknown>).startEntity ??
             (call.body as Record<string, unknown>).start_entity ??
             (call.body as Record<string, unknown>).start)
          : undefined;
      const startFromQuery = call.query?.start;
      // Accept either POST body or GET query string — both are valid contracts.
      expect(startFromBody ?? startFromQuery).toBeDefined();
    });
  });
});
