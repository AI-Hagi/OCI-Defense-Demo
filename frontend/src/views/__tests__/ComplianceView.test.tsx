import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/helpers';
import { calls, complianceLive } from '../../test/msw-server';

// recharts is heavy — swap ResponsiveContainer + chart internals for stubs.
vi.mock('recharts', () => {
  const Stub: React.FC<{ children?: React.ReactNode; [k: string]: unknown }> = ({
    children,
  }) => <div>{children}</div>;

  return {
    ResponsiveContainer: ({
      children,
    }: {
      children?: React.ReactElement | React.ReactNode;
    }) => <div data-testid="responsive-container">{children}</div>,
    RadialBarChart: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="rb-chart">{children}</div>
    ),
    RadialBar: Stub,
    LineChart: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="line-chart">{children}</div>
    ),
    Line: Stub,
    PolarAngleAxis: Stub,
    PolarRadiusAxis: Stub,
    Legend: Stub,
    Tooltip: Stub,
    Cell: Stub,
    BarChart: Stub,
    Bar: Stub,
    XAxis: Stub,
    YAxis: Stub,
    CartesianGrid: Stub,
  };
});

async function loadView() {
  const mod = await import('../ComplianceView');
  return mod.default ?? (mod as Record<string, unknown>).ComplianceView;
}

// Snapshot of the original fixture so individual tests can override and reset.
const originalCloudGuard = { ...complianceLive.cloudGuard };

describe('ComplianceView (london school)', () => {
  beforeEach(() => {
    calls.length = 0;
    // Reset live fixtures between tests so degraded-state cases don't leak.
    complianceLive.cloudGuard = { ...originalCloudGuard };
  });

  it('renders 4 radial charts, one per framework score', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    // Four ResponsiveContainer tiles — one per score card (NIS2 / DORA / GDPR / VSNFD).
    await waitFor(() => {
      const containers = screen.getAllByTestId('responsive-container');
      expect(containers.length).toBeGreaterThanOrEqual(4);
    });

    // Framework labels appear in score cards AND filter buttons — getAllByText.
    await waitFor(() => {
      expect(screen.getAllByText(/NIS2/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/DORA/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/GDPR/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/VS-NfD/).length).toBeGreaterThan(0);
    });

    // Each score card carries its framework testid.
    await waitFor(() => {
      expect(screen.getByTestId('score-card-NIS2')).toBeInTheDocument();
      expect(screen.getByTestId('score-card-DORA')).toBeInTheDocument();
      expect(screen.getByTestId('score-card-GDPR')).toBeInTheDocument();
      expect(screen.getByTestId('score-card-VSNFD')).toBeInTheDocument();
    });
  });

  it('renders 4 live security tiles wired to /api/compliance/live/*', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      expect(screen.getByTestId('tile-cloud-guard')).toBeInTheDocument();
      expect(screen.getByTestId('tile-adb-encryption')).toBeInTheDocument();
      expect(screen.getByTestId('tile-bucket-access')).toBeInTheDocument();
      expect(screen.getByTestId('tile-ols-status')).toBeInTheDocument();
    });

    // All four live endpoints were called.
    await waitFor(() => {
      const paths = calls.map((c) => c.url);
      expect(paths).toContain('/api/compliance/live/cloud-guard');
      expect(paths).toContain('/api/compliance/live/adb-encryption');
      expect(paths).toContain('/api/compliance/live/bucket-public-access');
      expect(paths).toContain('/api/compliance/live/ols-status');
    });
  });

  it('framework filter triggers a refetch with the framework param', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    // Wait until the initial controls load is visible.
    await waitFor(() => expect(screen.getByText(/NIS2-21/)).toBeInTheDocument());

    // Click the NIS2 filter button in the filter bar.
    const user = userEvent.setup();
    const filterButtons = screen.getAllByRole('button');
    const nis2Btn = filterButtons.find(
      (b) => b.textContent?.trim() === 'NIS2',
    );
    expect(nis2Btn, 'missing NIS2 filter button').toBeDefined();
    await user.click(nis2Btn!);

    await waitFor(() => {
      const filtered = calls.find(
        (c) =>
          c.method === 'GET' &&
          c.url.endsWith('/api/compliance/controls') &&
          c.query?.framework === 'NIS2',
      );
      expect(filtered).toBeTruthy();
    });
  });

  it('shows "—" plus warning icon when cloud-guard returns instance_principal_unavailable', async () => {
    complianceLive.cloudGuard = {
      open_problems: 0,
      high_risk: 0,
      as_of: '2026-04-27T08:00:00Z',
      error: 'instance_principal_unavailable',
    };

    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      const tile = screen.getByTestId('tile-cloud-guard');
      expect(tile.textContent).toContain('—');
    });

    // Degraded warning icon is present and labelled with the German tooltip.
    await waitFor(() => {
      const warn = screen.getByTestId('tile-cloud-guard-degraded');
      expect(warn).toBeInTheDocument();
      expect(warn.getAttribute('title')).toContain(
        'Live-Daten temporär nicht verfügbar',
      );
    });
  });
});

// ---------------------------------------------------------------------------
// Pause / Resume — assert via mocked react-query that refetchInterval flips.
// This block uses vi.mock('@tanstack/react-query', ...) so it must run in an
// isolated describe with its own dynamic import after the mock is registered.
// ---------------------------------------------------------------------------
describe('ComplianceView — pause/resume toggles refetchInterval', () => {
  it('flips refetchInterval to false on pause and back on resume', async () => {
    vi.resetModules();

    // Capture the options passed to useQuery for each query key on each render.
    const optionsByKey = new Map<string, unknown[]>();

    vi.doMock('@tanstack/react-query', () => {
      // Each useQuery call records its options under its query-key string.
      const useQuery = (opts: {
        queryKey: unknown[];
        queryFn?: () => unknown;
        refetchInterval?: number | false;
        enabled?: boolean;
      }) => {
        const key = JSON.stringify(opts.queryKey);
        const list = optionsByKey.get(key) ?? [];
        list.push(opts);
        optionsByKey.set(key, list);
        return {
          data: undefined,
          isLoading: false,
          isError: false,
          dataUpdatedAt: 0,
        };
      };
      return {
        useQuery,
        // Pass-through provider so the test renders without a real client.
        QueryClient: class {},
        QueryClientProvider: ({
          children,
        }: {
          children: React.ReactNode;
        }) => <>{children}</>,
      };
    });

    // Reuse the same recharts stub so the chart import doesn't blow up.
    vi.doMock('recharts', () => {
      const Stub: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
        <div>{children}</div>
      );
      return {
        ResponsiveContainer: Stub,
        RadialBarChart: Stub,
        RadialBar: Stub,
      };
    });

    const { renderWithProviders: renderFresh } = await import(
      '../../test/helpers'
    );
    const mod = await import('../ComplianceView');
    const View = mod.default;

    renderFresh(<View />);

    // Default state: autoRefresh is ON → refetchInterval is a positive number
    // for at least one of the live queries.
    const liveKeys = [
      '["compliance.live.cloudGuard"]',
      '["compliance.live.adbEncryption"]',
      '["compliance.live.bucketAccess"]',
      '["compliance.live.olsStatus"]',
      '["compliance.score"]',
    ];
    for (const k of liveKeys) {
      expect(optionsByKey.get(k), `useQuery called for ${k}`).toBeDefined();
      const last = optionsByKey.get(k)!.at(-1) as {
        refetchInterval?: number | false;
      };
      expect(typeof last.refetchInterval).toBe('number');
      expect(last.refetchInterval as number).toBeGreaterThan(0);
    }

    // Click Pause → autoRefresh flips to false → refetchInterval becomes false.
    const user = userEvent.setup();
    const pauseBtn = screen.getByTestId('pause-resume');
    await user.click(pauseBtn);

    await waitFor(() => {
      for (const k of liveKeys) {
        const last = optionsByKey.get(k)!.at(-1) as {
          refetchInterval?: number | false;
        };
        expect(last.refetchInterval).toBe(false);
      }
    });

    // Click Resume → refetchInterval becomes a positive number again.
    await user.click(pauseBtn);

    await waitFor(() => {
      for (const k of liveKeys) {
        const last = optionsByKey.get(k)!.at(-1) as {
          refetchInterval?: number | false;
        };
        expect(typeof last.refetchInterval).toBe('number');
        expect(last.refetchInterval as number).toBeGreaterThan(0);
      }
    });

    vi.doUnmock('@tanstack/react-query');
    vi.doUnmock('recharts');
  });
});
