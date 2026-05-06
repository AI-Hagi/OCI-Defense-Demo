/**
 * Tests for CloudGuardDetailView.
 *
 * Gap: no test file — the view has demo-mode, degraded, zero-problems, and
 * problem-table rendering paths; two pure helper functions (riskBadge,
 * formatTimestamp) are completely untested.
 *
 * Strategy:
 *   - Pure functions tested directly (dynamic import after vi.resetModules).
 *   - Component tested with renderWithProviders + local MSW handler overrides
 *     for the two compliance/live endpoints this view consumes.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../../test/helpers';
import { server } from '../../test/msw-server';

beforeEach(() => vi.resetModules());
afterEach(() => vi.restoreAllMocks());

// ---------------------------------------------------------------------------
// Helper: load the module so pure functions can be extracted
// ---------------------------------------------------------------------------

async function loadModule() {
  const mod = await import('../CloudGuardDetailView');
  return mod;
}

// ---------------------------------------------------------------------------
// riskBadge (pure function, not exported — exercised indirectly via render)
// We test the rendered badge class via DOM assertions below.
//
// Direct unit tests use dynamic module access — only works if the function
// is exported. If not exported, these are covered by the render tests.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// formatTimestamp (pure function, not exported — tested via render assertions)
// ---------------------------------------------------------------------------
// We can also import the module and call the non-exported function via module
// internals in some bundler setups, but the safest approach is DOM assertion.

// ---------------------------------------------------------------------------
// Component tests
// ---------------------------------------------------------------------------

const PROBLEMS_EMPTY = { problems: [], demo: true };
const PROBLEMS_LIST = {
  demo: true,
  problems: [
    {
      id: 'P001',
      risk_level: 'CRITICAL',
      detector_rule: 'OCI.SecurityZone.001',
      resource_name: 'sovdef-bucket',
      resource_type: 'objectstorage.bucket',
      compartment: 'oci-defence-demo',
      first_detected: '2026-05-01T10:00:00Z',
    },
    {
      id: 'P002',
      risk_level: 'MEDIUM',
      detector_rule: 'OCI.SecurityZone.002',
      resource_name: 'test-resource',
      resource_type: 'compute.instance',
      compartment: 'oci-defence-demo',
      first_detected: null,
    },
  ],
};

const CG_DEMO = { open_problems: 3, high_risk: 1, as_of: '2026-05-04T08:00:00Z', demo: true };
const CG_DEGRADED = {
  open_problems: 0,
  high_risk: 0,
  as_of: '2026-05-04T08:00:00Z',
  error: 'instance_principal_unavailable',
};
const CG_CLEAN = { open_problems: 0, high_risk: 0, as_of: '2026-05-04T08:00:00Z' };

function useHandlers(cgData: unknown, problemsData: unknown) {
  server.use(
    http.get('*/api/compliance/live/cloud-guard', () => HttpResponse.json(cgData)),
    http.get('*/api/compliance/live/cloud-guard/problems', () =>
      HttpResponse.json(problemsData),
    ),
  );
}

describe('CloudGuardDetailView', () => {
  it('renders the section heading', async () => {
    useHandlers(CG_DEMO, PROBLEMS_EMPTY);
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      expect(screen.getByText(/Cloud Guard/i)).toBeInTheDocument();
    });
  });

  it('shows demo-mode banner when cg.demo is true', async () => {
    useHandlers(CG_DEMO, PROBLEMS_EMPTY);
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      expect(screen.getByText(/Demo-Modus/i)).toBeInTheDocument();
    });
  });

  it('shows degraded banner when error is instance_principal_unavailable', async () => {
    useHandlers(CG_DEGRADED, { problems: [] });
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      expect(
        screen.getByText(/Live-Daten derzeit nicht verfügbar/i),
      ).toBeInTheDocument();
    });
  });

  it('shows zero-problems banner when open_problems is 0 (no demo, no degraded)', async () => {
    useHandlers(CG_CLEAN, { problems: [] });
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      expect(screen.getByText(/Keine offenen Probleme/i)).toBeInTheDocument();
    });
  });

  it('renders problem rows in the findings table', async () => {
    useHandlers(CG_DEMO, PROBLEMS_LIST);
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      expect(screen.getByText('sovdef-bucket')).toBeInTheDocument();
      expect(screen.getByText('OCI.SecurityZone.001')).toBeInTheDocument();
    });
  });

  it('renders CRITICAL risk badge with rose coloring', async () => {
    useHandlers(CG_DEMO, PROBLEMS_LIST);
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      const badge = screen.getByText('CRITICAL');
      expect(badge.className).toContain('rose');
    });
  });

  it('renders MEDIUM risk badge with amber coloring', async () => {
    useHandlers(CG_DEMO, PROBLEMS_LIST);
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      const badge = screen.getByText('MEDIUM');
      expect(badge.className).toContain('amber');
    });
  });

  it('shows null first_detected as em-dash', async () => {
    useHandlers(CG_DEMO, PROBLEMS_LIST);
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      // The second problem has null first_detected → formatTimestamp returns '—'
      const dashes = screen.getAllByText('—');
      expect(dashes.length).toBeGreaterThan(0);
    });
  });

  it('shows open_problems count in the metric tile', async () => {
    useHandlers(CG_DEMO, PROBLEMS_LIST);
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      // open_problems = 3
      expect(screen.getByText('3')).toBeInTheDocument();
    });
  });

  it('shows loading state while data is in flight', async () => {
    // Delay response to catch loading state
    server.use(
      http.get('*/api/compliance/live/cloud-guard', async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json(CG_DEMO);
      }),
      http.get('*/api/compliance/live/cloud-guard/problems', async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json(PROBLEMS_EMPTY);
      }),
    );
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    expect(screen.getByText(/Lade Findings/i)).toBeInTheDocument();
  });

  it('renders back-link to /compliance', async () => {
    useHandlers(CG_DEMO, PROBLEMS_EMPTY);
    const { CloudGuardDetailView } = await loadModule();
    renderWithProviders(<CloudGuardDetailView />, { route: '/compliance/cloud-guard' });
    await waitFor(() => {
      expect(screen.getByText(/Zurück zu Compliance/i)).toBeInTheDocument();
    });
  });
});
