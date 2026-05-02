import { describe, it, expect, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/helpers';
import { server } from '../../test/msw-server';

// Leaflet + react-leaflet share the GeointView mock pattern.
vi.mock('leaflet', () => ({
  default: {},
  Icon: { Default: { mergeOptions: vi.fn(), prototype: {} } },
  icon: vi.fn(),
  map: vi.fn(),
}));

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="leaflet-map">{children}</div>
  ),
  TileLayer: () => <div data-testid="tile-layer" />,
  CircleMarker: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="bucket-marker">{children}</div>
  ),
  Popup: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="popup">{children}</div>
  ),
  useMap: () => ({ setView: vi.fn(), fitBounds: vi.fn() }),
}));

const TOOLS_BASE_RX =
  /\/ords\/uc4_osint\/api\/v1\/tools\/(graph_query|spatial_aggregate)/;

interface CapCall {
  endpoint: string;
  cap: string | null;
}
const calls: CapCall[] = [];

// Per-cap fixtures matching the live verification numbers from the
// 7c session (Shadow-Tanker A + 3 entities at NFD).
const ENTITIES_BY_CAP: Record<string, Array<{ display_name: string; corr_count: number }>> = {
  OFFEN:  [],
  INTERN: [{ display_name: 'Bornholm Deep', corr_count: 2 }],
  NFD: [
    { display_name: 'Unknown Shadow-Tanker A', corr_count: 3 },
    { display_name: 'Baltic Oil Ltd',          corr_count: 2 },
    { display_name: 'Bornholm Deep',           corr_count: 2 },
    { display_name: 'MV Kaskol',               corr_count: 2 },
  ],
};

function makeGraphHandler() {
  return http.post('*/ords/uc4_osint/api/v1/tools/graph_query', ({ request }) => {
    const cap = request.headers.get('x-ols-label-max');
    calls.push({ endpoint: 'graph_query', cap });
    const list = ENTITIES_BY_CAP[cap ?? 'OFFEN'] ?? [];
    return HttpResponse.json({
      request_id: 'fake-' + cap,
      duration_ms: 12.3,
      data: {
        entities: list.map((e, i) => ({
          entity_id: 'eid-' + i,
          entity_kind: 'vessel',
          display_name: e.display_name,
          canonical_id: 'cid-' + i,
          corr_count: e.corr_count,
          correlation_ids: [],
        })),
      },
      ols_cap_applied: cap === 'OFFEN' ? 10 : cap === 'INTERN' ? 30 : 50,
      ols_cap_label: cap,
    });
  });
}

function makeSpatialHandler() {
  return http.post('*/ords/uc4_osint/api/v1/tools/spatial_aggregate', ({ request }) => {
    const cap = request.headers.get('x-ols-label-max');
    calls.push({ endpoint: 'spatial_aggregate', cap });
    const features = cap === 'NFD' ? [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [18.0, 55.5] },
        properties: { h3_cell: 'r5/55.5/18.0', event_count: 12, variety: 3, centroid_lat: 55.5, centroid_lon: 18.0 },
      },
    ] : [];
    return HttpResponse.json({
      request_id: 'fake-spatial-' + cap,
      duration_ms: 4.1,
      data: { type: 'FeatureCollection', features },
      ols_cap_applied: cap === 'OFFEN' ? 10 : cap === 'INTERN' ? 30 : 50,
      ols_cap_label: cap,
    });
  });
}

async function loadView() {
  return (await import('../Uc4ToolsView')).default;
}

describe('Uc4ToolsView (london school)', () => {
  beforeEach(() => {
    calls.length = 0;
    server.use(makeGraphHandler(), makeSpatialHandler());
  });

  it('mounts and renders the persona pills + both panels', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    // Header
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /UC4 OSINT/i })).toBeInTheDocument(),
    );

    // Persona pills
    expect(screen.getByRole('radio', { name: /OFFEN/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /INTERN/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /NFD/i })).toBeInTheDocument();

    // Both panels visible
    expect(screen.getByTestId('uc4-multi-corr')).toBeInTheDocument();
    expect(screen.getByTestId('uc4-spatial-heatmap')).toBeInTheDocument();
  });

  it('forwards the X-OLS-Label-Max header on every tool call', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      const graph  = calls.find((c) => c.endpoint === 'graph_query');
      const spatial = calls.find((c) => c.endpoint === 'spatial_aggregate');
      expect(graph?.cap).toBe('NFD');     // initial cap
      expect(spatial?.cap).toBe('NFD');
    });
  });

  it('renders 4 multi-correlation rows at NFD cap', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      const rows = screen.queryAllByTestId('uc4-multi-corr-row');
      expect(rows).toHaveLength(4);
    });
    expect(screen.getByText(/Unknown Shadow-Tanker A/)).toBeInTheDocument();
    expect(screen.getByText(/MV Kaskol/)).toBeInTheDocument();
  });

  it('refetches with the new cap when the persona switches', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      expect(screen.queryAllByTestId('uc4-multi-corr-row')).toHaveLength(4);
    });

    const offenPill = screen.getByRole('radio', { name: /OFFEN/i });
    const user = userEvent.setup();
    await user.click(offenPill);

    // Now the view should refetch and show 0 rows (per fixture)
    await waitFor(() => {
      const offenCall = calls.filter((c) => c.cap === 'OFFEN');
      expect(offenCall.length).toBeGreaterThanOrEqual(2);   // both endpoints
      expect(screen.queryAllByTestId('uc4-multi-corr-row')).toHaveLength(0);
    });
  });

  it('clamps INTERN to 1 row matching the seeded Bornholm Deep', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    const internPill = screen.getByRole('radio', { name: /INTERN/i });
    const user = userEvent.setup();
    await user.click(internPill);

    await waitFor(() => {
      const rows = screen.queryAllByTestId('uc4-multi-corr-row');
      expect(rows).toHaveLength(1);
    });
    expect(screen.getByText(/Bornholm Deep/)).toBeInTheDocument();
  });

  it('shows the deferred-status panel explaining agent + vector_hybrid_search', async () => {
    const View = await loadView();
    renderWithProviders(<View />);
    const status = await screen.findByTestId('uc4-status-panel');
    expect(within(status).getByText(/vector_hybrid_search/i)).toBeInTheDocument();
    expect(within(status).getByText(/Threat-Fusion-Agent/i)).toBeInTheDocument();
  });
});
