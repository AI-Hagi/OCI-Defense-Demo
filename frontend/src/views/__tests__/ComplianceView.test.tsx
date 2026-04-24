import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/helpers';
import { calls } from '../../test/msw-server';

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

describe('ComplianceView (london school)', () => {
  beforeEach(() => {
    calls.length = 0;
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
});
