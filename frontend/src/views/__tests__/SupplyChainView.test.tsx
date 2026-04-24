import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/helpers';
import { calls, scNodes } from '../../test/msw-server';

vi.mock('leaflet', () => ({
  default: {},
  Icon: { Default: { mergeOptions: vi.fn(), prototype: {} } },
  icon: vi.fn(),
  map: vi.fn(),
}));

vi.mock('react-leaflet', () => {
  const MarkerStub = ({ children, eventHandlers }: {
    children?: React.ReactNode;
    eventHandlers?: { click?: () => void };
  }) => (
    <button type="button" data-testid="marker" onClick={eventHandlers?.click}>
      {children}
    </button>
  );
  return {
    MapContainer: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="leaflet-map">{children}</div>
    ),
    TileLayer: () => <div data-testid="tile-layer" />,
    Marker: MarkerStub,
    CircleMarker: MarkerStub,
    Popup: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="popup">{children}</div>
    ),
    Polygon: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="polygon">{children}</div>
    ),
    Polyline: () => <div data-testid="polyline" />,
    GeoJSON: () => <div data-testid="geojson" />,
    useMap: () => ({ setView: vi.fn() }),
  };
});

async function loadView() {
  const mod = await import('../SupplyChainView');
  return mod.default ?? (mod as Record<string, unknown>).SupplyChainView;
}

describe('SupplyChainView (london school)', () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it('renders one marker per supply chain node fixture', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      const markers = screen.getAllByTestId('marker');
      expect(markers.length).toBeGreaterThanOrEqual(scNodes.length);
    });
  });

  it('clicking a marker triggers a GET to /sc/nodes/:id/risk (or /sc/risk/:id)', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    const markers = await screen.findAllByTestId('marker');
    const user = userEvent.setup();
    await user.click(markers[0]);

    await waitFor(() => {
      const riskCall = calls.find(
        (c) =>
          c.method === 'GET' &&
          (/\/api\/sc\/nodes\/[^/]+\/risk$/.test(c.url) ||
            /\/api\/sc\/risk\/[^/]+$/.test(c.url)),
      );
      expect(riskCall).toBeTruthy();
    });
  });
});
