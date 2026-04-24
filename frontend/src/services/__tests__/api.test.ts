import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// The api module reads import.meta.env.VITE_API_BASE at import time, so we
// reset the module registry between tests to re-run the module factory.
beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function loadApiWithMockedAxios() {
  const requestSpy = vi.fn((config: Record<string, unknown>) => {
    // echo the computed url via data so tests can assert it.
    return Promise.resolve({
      data:
        // api.ts .graph returns { nodes, edges } — provide a minimal shape.
        String(config.url).includes('/osint/graph')
          ? { nodes: [], edges: [] }
          : [],
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    });
  });

  type RequestUse = (
    fn: (c: Record<string, unknown>) => Record<string, unknown>,
  ) => void;
  const interceptors = {
    request: { use: vi.fn() as unknown as RequestUse },
    response: { use: vi.fn() },
  };

  const fakeInstance = {
    get: vi.fn((url: string, config?: Record<string, unknown>) =>
      requestSpy({ method: 'get', url, ...(config ?? {}) }),
    ),
    post: vi.fn(
      (url: string, body?: unknown, config?: Record<string, unknown>) =>
        requestSpy({ method: 'post', url, data: body, ...(config ?? {}) }),
    ),
    interceptors,
    defaults: { headers: {} },
  };

  vi.doMock('axios', () => ({
    default: { create: vi.fn(() => fakeInstance) },
    create: vi.fn(() => fakeInstance),
  }));

  const api = await import('../api');
  return { api, fakeInstance, interceptors };
}

describe('services/api.ts — axios contract', () => {
  it('installs a request interceptor that stamps X-Tenant-Id from localStorage', async () => {
    localStorage.setItem('sov:tenant', 'T002');
    const { interceptors } = await loadApiWithMockedAxios();

    expect(interceptors.request.use).toHaveBeenCalledTimes(1);
    const hook = (interceptors.request.use as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0][0] as (c: { headers: Record<string, string> }) => {
      headers: Record<string, string>;
    };
    const out = hook({ headers: {} });
    expect(out.headers['X-Tenant-Id']).toBe('T002');
  });

  it('falls back to T001 when no tenant is set in localStorage', async () => {
    const { interceptors } = await loadApiWithMockedAxios();
    const hook = (interceptors.request.use as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0][0] as (c: { headers: Record<string, string> }) => {
      headers: Record<string, string>;
    };
    const out = hook({ headers: {} });
    expect(out.headers['X-Tenant-Id']).toBe('T001');
  });

  it('geoint.listScenes issues GET /geoint/scenes', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.geoint.listScenes();
    expect(fakeInstance.get).toHaveBeenCalledWith('/geoint/scenes');
  });

  it('geoint.uploadScene POSTs to /geoint/scenes with multipart/form-data', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    const file = new File(['x'], 'scene.jpg', { type: 'image/jpeg' });
    await api.geoint.uploadScene(file);
    expect(fakeInstance.post).toHaveBeenCalled();
    const [url, body, config] = fakeInstance.post.mock.calls[0];
    expect(url).toBe('/geoint/scenes');
    expect(body).toBeInstanceOf(FormData);
    expect(
      (config as { headers: Record<string, string> }).headers['Content-Type'],
    ).toBe('multipart/form-data');
  });

  it('docs.search issues GET /docs/search with q + k params', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.docs.search('geo', 5);
    expect(fakeInstance.get).toHaveBeenCalledWith('/docs/search', {
      params: { q: 'geo', k: 5 },
    });
  });

  it('docs.ragChat POSTs /docs/chat with { messages }', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    const msgs = [{ role: 'user' as const, content: 'hi' }];
    await api.docs.ragChat(msgs);
    const [url, body] = fakeInstance.post.mock.calls[0];
    expect(url).toBe('/docs/chat');
    expect(body).toEqual({ messages: msgs });
  });

  it('collab.shares issues GET /collab/shares', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.collab.shares();
    expect(fakeInstance.get).toHaveBeenCalledWith('/collab/shares');
  });

  it('osint.graph issues GET /osint/graph with start + hops params', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.osint.graph('E100', 3);
    expect(fakeInstance.get).toHaveBeenCalledWith('/osint/graph', {
      params: { start: 'E100', hops: 3 },
    });
  });

  it('sc.nodes / sc.edges / sc.risk hit the right paths', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.sc.nodes();
    await api.sc.edges();
    await api.sc.risk('N001');
    const urls = fakeInstance.get.mock.calls.map((c) => c[0]);
    expect(urls).toEqual(['/sc/nodes', '/sc/edges', '/sc/nodes/N001/risk']);
  });

  it('compliance.controls sends the framework param when provided', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.compliance.controls('NIS2');
    expect(fakeInstance.get).toHaveBeenCalledWith('/compliance/controls', {
      params: { framework: 'NIS2' },
    });
  });

  it('compliance.score issues GET /compliance/score', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.compliance.score();
    expect(fakeInstance.get).toHaveBeenCalledWith('/compliance/score');
  });
});
