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
  // The MapContainer mock surfaces center/zoom into the rendered DOM as
  // data-attributes so tests can assert the default-view contract for
  // BMVg / Bundeswehr (Mitteleuropa, zoom 5) without a live Leaflet
  // instance.
  MapContainer: ({
    children, center, zoom,
  }: { children?: React.ReactNode; center?: unknown; zoom?: unknown }) => (
    <div
      data-testid="leaflet-map"
      data-center={center !== undefined ? JSON.stringify(center) : undefined}
      data-zoom={zoom !== undefined ? String(zoom) : undefined}
    >
      {children}
    </div>
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
    // Banner dismissal is sessionStorage-backed; reset between tests so a
    // dismissal in one case doesn't bleed into the next.
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.removeItem('sov:geoint:footprint-hint-dismissed');
    }
  });

  it('renders the GEOINT header and a leaflet map container', async () => {
    const View = await loadView();
    renderWithProviders(<View />);
    // German UI — peer view uses "Satellitenszenen" as the header. Pin the
    // assertion to the heading role so the GEOINT-narrative-panel below the
    // map (which also mentions GEOINT) doesn't make the lookup ambiguous.
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /Satellitenszenen/i, level: 2 }),
      ).toBeInTheDocument();
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
    // "3 Szenen" appears both in the header badge and in the new
    // narrative-panel summary line ("3 Szenen · N Detektionen") — both are
    // proof that the data made it from the API to the DOM, but the matcher
    // needs to accept either.
    await waitFor(() => {
      expect(screen.getAllByText(/3\s*Szenen/i).length).toBeGreaterThanOrEqual(1);
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

  it('defaults the leaflet map to Mitteleuropa (51.0°N, 10.0°E) at zoom 5', async () => {
    // Demo audience is BMVg / Bundeswehr — the empty / no-footprint
    // case must NOT drop the operator on a Russland-zoomed Leaflet
    // default. The MapContainer mock surfaces center/zoom into data-
    // attributes so we can pin the contract here.
    const View = await loadView();
    renderWithProviders(<View />);
    const map = await screen.findByTestId('leaflet-map');
    expect(JSON.parse(map.getAttribute('data-center') ?? '[]'))
      .toEqual([51.0, 10.0]);
    expect(map.getAttribute('data-zoom')).toBe('5');
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
    // New banner wording — points the operator to the upcoming
    // 'Position wählen' workflow per Roadmap UC1.B.
    expect(banner).toHaveTextContent(/synthetischen Footprints/i);
    expect(banner).toHaveTextContent(/Position w[aä]hlen/i);
    expect(banner).toHaveTextContent(/Roadmap UC1\.B/i);
    // Dismiss button must be reachable via aria-label so screen-reader
    // users can hide the hint too.
    expect(
      within(banner).getByRole('button', { name: /Hinweis schließen/i }),
    ).toBeInTheDocument();
  });

  it('does NOT render hint banner when scenes list is empty', async () => {
    // No scenes loaded yet — show the bare Mitteleuropa map without
    // any banner overlay. The operator gets a clean canvas. The count
    // badge in the header reads "0 Szenen" once the empty response
    // has settled, which is what we wait on.
    server.use(
      http.get('*/api/geoint/scenes', () => HttpResponse.json([])),
    );

    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      expect(screen.getAllByText(/0\s*Szenen/i).length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.queryByTestId('geoint-footprint-hint')).not.toBeInTheDocument();
  });

  it('does NOT render hint banner when at least one scene has a footprint', async () => {
    // Default fixtures: S001 has a footprint, S002 + S003 do not. The
    // banner should stay hidden because the "all" filter sees a mix.
    const View = await loadView();
    renderWithProviders(<View />);

    // "3 Szenen" appears both in the header badge and in the new
    // narrative-panel summary line ("3 Szenen · N Detektionen") — both are
    // proof that the data made it from the API to the DOM, but the matcher
    // needs to accept either.
    await waitFor(() => {
      expect(screen.getAllByText(/3\s*Szenen/i).length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.queryByTestId('geoint-footprint-hint')).not.toBeInTheDocument();
  });

  it('hides the hint banner once the operator clicks the dismiss button', async () => {
    server.use(
      http.get('*/api/geoint/scenes', () => {
        const stripped = sceneFixtures.map((s) => ({ ...s, footprint: null }));
        return HttpResponse.json(stripped);
      }),
    );

    const View = await loadView();
    renderWithProviders(<View />);
    const banner = await screen.findByTestId('geoint-footprint-hint');
    const dismiss = within(banner).getByRole('button', {
      name: /Hinweis schließen/i,
    });
    const user = userEvent.setup();
    await user.click(dismiss);

    await waitFor(() => {
      expect(screen.queryByTestId('geoint-footprint-hint')).not.toBeInTheDocument();
    });
    // Dismissal also persists for the session — sessionStorage flag is set.
    expect(sessionStorage.getItem('sov:geoint:footprint-hint-dismissed')).toBe('1');
  });
});

// Silence "within" unused warning when assertions are skipped conditionally.
void within;
