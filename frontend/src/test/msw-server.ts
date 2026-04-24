import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterEach } from 'vitest';
import {
  collabShares,
  complianceControls,
  complianceScore,
  docHits,
  osintEntities,
  osintGraph,
  ragReply,
  sceneFixtures,
  scEdges,
  scNodes,
  scRisk,
} from './fixtures';

export * from './fixtures';

// ---------------------------------------------------------------------------
// Call log — tests can introspect requests the component made.
// ---------------------------------------------------------------------------
export interface CallRecord {
  method: string;
  url: string;
  tenantHeader: string | null;
  body?: unknown;
  query: Record<string, string>;
}
export const calls: CallRecord[] = [];

function record(method: string, req: Request, body?: unknown) {
  const url = new URL(req.url);
  calls.push({
    method,
    url: url.pathname,
    tenantHeader: req.headers.get('x-tenant-id'),
    body,
    query: Object.fromEntries(url.searchParams.entries()),
  });
}

// ---------------------------------------------------------------------------
// Handlers — cover every axios call declared in src/services/api.ts.
// ---------------------------------------------------------------------------
export const handlers = [
  // GEOINT
  http.get('*/api/geoint/scenes', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(sceneFixtures);
  }),
  http.post('*/api/geoint/scenes', async ({ request }) => {
    record('POST', request, '[multipart]');
    return HttpResponse.json(sceneFixtures[0]);
  }),
  http.post('*/api/geoint/scenes/upload', async ({ request }) => {
    record('POST', request, '[multipart]');
    return HttpResponse.json(sceneFixtures[0]);
  }),

  // Document Intelligence
  http.get('*/api/docs/search', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(docHits);
  }),
  http.post('*/api/documents/search', async ({ request }) => {
    const body = await request.json().catch(() => ({}));
    record('POST', request, body);
    return HttpResponse.json(docHits);
  }),
  http.post('*/api/docs/chat', async ({ request }) => {
    const body = await request.json().catch(() => ({}));
    record('POST', request, body);
    return HttpResponse.json(ragReply);
  }),
  http.post('*/api/documents/chat', async ({ request }) => {
    const body = await request.json().catch(() => ({}));
    record('POST', request, body);
    return HttpResponse.json(ragReply);
  }),

  // Collaboration
  http.get('*/api/collab/shares', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(collabShares);
  }),

  // OSINT
  http.get('*/api/osint/graph', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(osintGraph);
  }),
  http.post('*/api/osint/query-graph', async ({ request }) => {
    const body = await request.json().catch(() => ({}));
    record('POST', request, body);
    return HttpResponse.json(osintGraph);
  }),
  http.get('*/api/osint/entities', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(osintEntities);
  }),

  // Supply Chain
  http.get('*/api/sc/nodes', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(scNodes);
  }),
  http.get('*/api/sc/edges', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(scEdges);
  }),
  http.get(/\/api\/sc\/nodes\/[^/]+\/risk$/, ({ request }) => {
    record('GET', request);
    return HttpResponse.json(scRisk);
  }),
  http.get(/\/api\/sc\/risk\/[^/]+$/, ({ request }) => {
    record('GET', request);
    return HttpResponse.json(scRisk);
  }),

  // Compliance
  http.get('*/api/compliance/controls', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(complianceControls);
  }),
  http.get(/\/api\/compliance\/controls\/[^/]+$/, ({ request }) => {
    record('GET', request);
    const framework = request.url.split('/').pop();
    return HttpResponse.json(
      complianceControls.filter((c) => c.framework === framework),
    );
  }),
  http.get('*/api/compliance/score', ({ request }) => {
    record('GET', request);
    return HttpResponse.json(complianceScore);
  }),
];

export const server = setupServer(...handlers);

// Reset the call log between tests.
afterEach(() => {
  calls.length = 0;
});
