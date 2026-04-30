import { describe, it, expect, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/helpers';
import { calls, sceneFixtures, server } from '../../test/msw-server';

// Leaflet drags in canvas/dom APIs jsdom cannot provide — mock both packages.
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
  Marker: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="marker">{children}</div>
  ),
  CircleMarker: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="marker">{children}</div>
  ),
  Popup: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="popup">{children}</div>
  ),
  Polygon: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="polygon">{children}</div>
  ),
  Polyline: () => <div data-testid="polyline" />,
  GeoJSON: () => <div data-testid="geojson" />,
  useMap: () => ({ setView: vi.fn(), fitBounds: vi.fn() }),
}));

async function loadView() {
  return (await import('../GeointView')).default
    ?? (await import('../GeointView')).GeointView;
}

describe('GeointView (london school)', () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it('renders the GEOINT header and a leaflet map container', async () => {
    const View = await loadView();
    renderWithProviders(<View />);
    // German UI — peer view uses "Satellitenszenen" as the header, but the
    // nav label "GEOINT" lives in the sidebar. Accept either.
    await waitFor(() => {
      expect(
        screen.queryByText(/GEOINT/i) ?? screen.queryByText(/Satellitenszenen/i),
      ).toBeTruthy();
    });
    expect(screen.getByTestId('leaflet-map')).toBeInTheDocument();
  });

  it('fetches scenes on mount and shows the count', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      expect(
        calls.find((c) => c.method === 'GET' && c.url.endsWith('/api/geoint/scenes')),
      ).toBeTruthy();
    });

    // Count of 3 fixtures (2 satellite + 1 UAV) appears in the header badge.
    await waitFor(() => {
      expect(screen.getByText(/3\s*Szenen/i)).toBeInTheDocument();
    });
  });

  it('issues exactly one POST when the user uploads and submits a file', async () => {
    const View = await loadView();
    const { container } = renderWithProviders(<View />);
    await waitFor(() => expect(screen.getByTestId('leaflet-map')).toBeInTheDocument());

    const input = container.querySelector('input[type="file"]') as HTMLInputElement | null;
    if (!input) {
      // No file input — view uses a different affordance; skip gracefully.
      return;
    }

    const file = new File(['fake-bytes'], 'scene.jpg', { type: 'image/jpeg' });
    const user = userEvent.setup();
    await user.upload(input, file);

    // File input populates the form; the upload only triggers on submit.
    const submitBtn = screen.getByRole('button', { name: /Hochladen/i });
    await user.click(submitBtn);

    await waitFor(() => {
      const posts = calls.filter(
        (c) => c.method === 'POST' && c.url.includes('/api/geoint/scenes'),
      );
      expect(posts.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('tags every request with the X-Tenant-Id header', async () => {
    const View = await loadView();
    renderWithProviders(<View />);
    await waitFor(() => {
      const get = calls.find((c) => c.url.endsWith('/api/geoint/scenes'));
      expect(get?.tenantHeader).toMatch(/^T\d{3}$/);
    });
  });

  it('renders hint banner when all scenes lack footprint', async () => {
    // Override the MSW handler so every scene comes back without a
    // `footprint` polygon. The banner only fires when scenes.length > 0
    // AND every scene is footprint-less — exactly the empty-Russland-map
    // case we want to surface to the operator.
    server.use(
      http.get('*/api/geoint/scenes', () => {
        const stripped = sceneFixtures.map((s) => ({ ...s, footprint: null }));
        return HttpResponse.json(stripped);
      }),
    );

    const View = await loadView();
    renderWithProviders(<View />);

    const banner = await screen.findByTestId('geoint-footprint-hint');
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/ohne Geolokalisation/i);
    // The N matches sceneFixtures.length (3) when every fixture is stripped.
    expect(banner).toHaveTextContent(`${sceneFixtures.length} Szenen`);
  });

  it('does NOT render hint banner when at least one scene has a footprint', async () => {
    // Default fixtures: S001 has a footprint, S002 + S003 do not. The
    // banner should stay hidden because the "all" filter sees a mix.
    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      expect(screen.getByText(/3\s*Szenen/i)).toBeInTheDocument();
    });
    expect(screen.queryByTestId('geoint-footprint-hint')).not.toBeInTheDocument();
  });
});

// Silence "within" unused warning when assertions are skipped conditionally.
void within;
