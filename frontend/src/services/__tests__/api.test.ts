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

  it('geoint.uploadScene POSTs to /geoint/scenes/upload with multipart/form-data', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    const file = new File(['x'], 'scene.jpg', { type: 'image/jpeg' });
    await api.geoint.uploadScene(file);
    expect(fakeInstance.post).toHaveBeenCalled();
    const [url, body, config] = fakeInstance.post.mock.calls[0];
    expect(url).toBe('/geoint/scenes/upload');
    expect(body).toBeInstanceOf(FormData);
    expect(
      (config as { headers: Record<string, string> }).headers['Content-Type'],
    ).toBe('multipart/form-data');
  });

  it('geoint.uploadScene forwards UAV platform headers when supplied', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    const file = new File(['x'], 'drone.jpg', { type: 'image/jpeg' });
    await api.geoint.uploadScene(file, {
      platformKind: 'uav',
      altitudeM: 120.5,
      headingDeg: 270,
    });
    const [, , config] = fakeInstance.post.mock.calls[0];
    const headers = (config as { headers: Record<string, string> }).headers;
    expect(headers['X-Platform-Kind']).toBe('uav');
    expect(headers['X-Altitude-M']).toBe('120.5');
    expect(headers['X-Heading-Deg']).toBe('270');
  });

  it('docs.search POSTs /documents/search with { q, k }', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.docs.search('geo', 5);
    const [url, body] = fakeInstance.post.mock.calls[0];
    expect(url).toBe('/documents/search');
    expect(body).toEqual({ q: 'geo', k: 5 });
  });

  it('docs.ragChat POSTs /documents/chat with { messages }', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    const msgs = [{ role: 'user' as const, content: 'hi' }];
    await api.docs.ragChat(msgs);
    const [url, body] = fakeInstance.post.mock.calls[0];
    expect(url).toBe('/documents/chat');
    expect(body).toEqual({ messages: msgs });
  });

  it('collab.shares issues GET /compliance/collab-shares with federated=true', async () => {
    const { api, fakeInstance } = await loadApiWithMockedAxios();
    await api.collab.shares();
    expect(fakeInstance.get).toHaveBeenCalledWith('/compliance/collab-shares', {
      params: { federated: true },
    });
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
    expect(urls).toEqual(['/sc/nodes', '/sc/edges', '/sc/risk/N001']);
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
