/**
 * Tests for uc4Tools.ts — the four UC4 ORDS tool wrappers.
 *
 * Strategy: vi.doMock('axios') so the module factory re-runs each test
 * (same pattern as api.test.ts).  We verify:
 *   - correct endpoints are hit
 *   - X-OLS-Label-Max header is forwarded with caller-supplied cap
 *   - ToolError is thrown when the server returns a ProblemDetails body
 *   - non-ProblemDetails Axios errors are re-thrown as-is
 *   - 503 retry-after field is preserved on ToolError
 *   - uc4Tools namespace re-exports all four functions
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { AxiosError } from 'axios';

beforeEach(() => {
  vi.resetModules();
});
afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type PostSpy = ReturnType<typeof vi.fn>;

async function loadWithPostSpy(resolveWith: unknown) {
  const postSpy: PostSpy = vi.fn().mockResolvedValue({ data: resolveWith });

  vi.doMock('axios', () => ({
    default: {
      create: vi.fn(() => ({
        post: postSpy,
      })),
    },
  }));

  const mod = await import('../uc4Tools');
  return { mod, postSpy };
}

async function loadWithPostRejection(error: unknown) {
  const postSpy: PostSpy = vi.fn().mockRejectedValue(error);

  vi.doMock('axios', () => ({
    default: {
      create: vi.fn(() => ({
        post: postSpy,
      })),
    },
  }));

  const mod = await import('../uc4Tools');
  return { mod, postSpy };
}

const TOOL_RESPONSE_BASE = {
  request_id: 'req-001',
  duration_ms: 42,
  ols_cap_applied: 100,
  ols_cap_label: 'OFFEN' as const,
};

// ---------------------------------------------------------------------------
// ToolError
// ---------------------------------------------------------------------------

describe('ToolError', () => {
  it('is an Error subclass with name ToolError', async () => {
    vi.doMock('axios', () => ({ default: { create: vi.fn(() => ({ post: vi.fn() })) } }));
    const { ToolError } = await import('../uc4Tools');
    const err = new ToolError({ type: 'about:blank', title: 'Not Found', status: 404 });
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('ToolError');
    expect(err.message).toBe('Not Found');
    expect(err.problem.status).toBe(404);
  });

  it('preserves retry-after on 503 ProblemDetails', async () => {
    vi.doMock('axios', () => ({ default: { create: vi.fn(() => ({ post: vi.fn() })) } }));
    const { ToolError } = await import('../uc4Tools');
    const err = new ToolError({
      type: 'about:blank',
      title: 'Service Unavailable',
      status: 503,
      'retry-after': 60,
    });
    expect(err.problem['retry-after']).toBe(60);
  });
});

// ---------------------------------------------------------------------------
// postTool error paths
// ---------------------------------------------------------------------------

describe('postTool — error handling', () => {
  it('wraps ProblemDetails response in ToolError', async () => {
    const axErr = {
      response: {
        data: {
          type: 'about:blank',
          title: 'Bad Request',
          status: 400,
          detail: 'pattern is required',
        },
      },
    } as AxiosError;
    const { mod } = await loadWithPostRejection(axErr);

    await expect(
      mod.graphQuery(
        { pattern: 'multi_source_entity', args: { hours: 1, min_correlations: 2 } },
        'OFFEN',
      ),
    ).rejects.toMatchObject({ name: 'ToolError', message: 'Bad Request' });
  });

  it('re-throws non-ProblemDetails Axios error as-is', async () => {
    const networkErr = Object.assign(new Error('Network Error'), { response: undefined });
    const { mod } = await loadWithPostRejection(networkErr);

    await expect(
      mod.graphQuery(
        { pattern: 'multi_source_entity', args: { hours: 1, min_correlations: 2 } },
        'OFFEN',
      ),
    ).rejects.toThrow('Network Error');
  });

  it('re-throws when response.data is not an object', async () => {
    const axErr = { response: { data: 'plain string error' } } as AxiosError;
    const { mod } = await loadWithPostRejection(axErr);

    await expect(
      mod.spatialAggregate({ h3_resolution: 5, hours: 6, min_events: 1 }, 'OFFEN'),
    ).rejects.not.toMatchObject({ name: 'ToolError' });
  });
});

// ---------------------------------------------------------------------------
// graphQuery
// ---------------------------------------------------------------------------

describe('graphQuery', () => {
  it('POSTs to /graph_query with multi_source_entity pattern', async () => {
    const data = { entities: [{ entity_id: 'E1', entity_kind: 'vessel', display_name: 'V1', canonical_id: 'C1', corr_count: 3, correlation_ids: [] }] };
    const { mod, postSpy } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data });

    const result = await mod.graphQuery(
      { pattern: 'multi_source_entity', args: { hours: 24, min_correlations: 2 } },
      'NFD',
    );

    expect(postSpy).toHaveBeenCalledTimes(1);
    const [endpoint, body, config] = postSpy.mock.calls[0] as [string, unknown, { headers: Record<string, string> }];
    expect(endpoint).toBe('/graph_query');
    expect((body as { pattern: string }).pattern).toBe('multi_source_entity');
    expect(config.headers['X-OLS-Label-Max']).toBe('NFD');
    expect(result.data).toEqual(data);
  });

  it('POSTs to /graph_query with convergence pattern', async () => {
    const data = { h3_cell: '8a1234567ffffff', hours: 6, correlations: null };
    const { mod, postSpy } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data });

    await mod.graphQuery(
      { pattern: 'convergence', args: { hours: 6, h3_cell: '8a1234567ffffff' } },
      'GEHEIM',
    );

    const [, body] = postSpy.mock.calls[0] as [string, { pattern: string; args: { h3_cell: string } }];
    expect(body.pattern).toBe('convergence');
    expect(body.args.h3_cell).toBe('8a1234567ffffff');
  });

  it('forwards GEHEIM cap in header', async () => {
    const { mod, postSpy } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data: { entities: null } });
    await mod.graphQuery(
      { pattern: 'multi_source_entity', args: { hours: 1, min_correlations: 1 } },
      'GEHEIM',
    );
    const [, , config] = postSpy.mock.calls[0] as [string, unknown, { headers: Record<string, string> }];
    expect(config.headers['X-OLS-Label-Max']).toBe('GEHEIM');
  });
});

// ---------------------------------------------------------------------------
// spatialAggregate
// ---------------------------------------------------------------------------

describe('spatialAggregate', () => {
  it('POSTs to /spatial_aggregate with h3_resolution 5', async () => {
    const data: import('../uc4Tools').SpatialAggregateData = { type: 'FeatureCollection', features: [] };
    const { mod, postSpy } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data });

    await mod.spatialAggregate({ h3_resolution: 5, hours: 12, min_events: 3 }, 'INTERN');

    const [endpoint, body] = postSpy.mock.calls[0] as [string, { h3_resolution: number }];
    expect(endpoint).toBe('/spatial_aggregate');
    expect(body.h3_resolution).toBe(5);
  });

  it('includes bbox when provided', async () => {
    const { mod, postSpy } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data: { type: 'FeatureCollection', features: null } });

    await mod.spatialAggregate(
      {
        h3_resolution: 5,
        hours: 6,
        min_events: 1,
        bbox: { min_lat: 47.0, max_lat: 55.0, min_lon: 5.0, max_lon: 15.0 },
      },
      'OFFEN',
    );

    const [, body] = postSpy.mock.calls[0] as [string, { bbox?: object }];
    expect(body.bbox).toBeDefined();
  });

  it('omits bbox when not provided', async () => {
    const { mod, postSpy } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data: { type: 'FeatureCollection', features: [] } });
    await mod.spatialAggregate({ h3_resolution: 5, hours: 1, min_events: 1 }, 'OFFEN');
    const [, body] = postSpy.mock.calls[0] as [string, { bbox?: object }];
    expect(body.bbox).toBeUndefined();
  });

  it('returns FeatureCollection with features array', async () => {
    const feature: import('../uc4Tools').H3BucketFeature = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [8.5, 51.0] },
      properties: { h3_cell: '8a1234567ffffff', event_count: 5, variety: 2, centroid_lat: 51.0, centroid_lon: 8.5 },
    };
    const { mod } = await loadWithPostSpy({
      ...TOOL_RESPONSE_BASE,
      data: { type: 'FeatureCollection', features: [feature] },
    });

    const result = await mod.spatialAggregate({ h3_resolution: 5, hours: 1, min_events: 1 }, 'OFFEN');
    expect((result.data as import('../uc4Tools').SpatialAggregateData).features).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// persistBriefing
// ---------------------------------------------------------------------------

describe('persistBriefing', () => {
  const BRIEFING_BODY: import('../uc4Tools').BriefingRequest = {
    briefing: {
      title: 'Test Briefing',
      summary: 'Summary text',
      classification: 'NFD',
      findings: [{ text: 'Finding 1' }],
      confidence: 0.85,
      correlation_id: 'CORR-001',
    },
  };

  it('POSTs to /persist_briefing', async () => {
    const data: import('../uc4Tools').BriefingPersisted = {
      briefing_id: 'BRF-001',
      persisted_at: '2026-05-02T10:00:00Z',
    };
    const { mod, postSpy } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data });

    await mod.persistBriefing(BRIEFING_BODY, 'NFD');

    const [endpoint] = postSpy.mock.calls[0] as [string];
    expect(endpoint).toBe('/persist_briefing');
  });

  it('returns briefing_id and persisted_at', async () => {
    const data: import('../uc4Tools').BriefingPersisted = {
      briefing_id: 'BRF-042',
      persisted_at: '2026-05-02T12:00:00Z',
    };
    const { mod } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data });
    const result = await mod.persistBriefing(BRIEFING_BODY, 'INTERN');
    expect(result.data.briefing_id).toBe('BRF-042');
    expect(result.data.persisted_at).toBeTruthy();
  });

  it('includes optional geo field when provided', async () => {
    const { mod, postSpy } = await loadWithPostSpy({
      ...TOOL_RESPONSE_BASE,
      data: { briefing_id: 'BRF-043', persisted_at: '' },
    });
    await mod.persistBriefing(
      {
        briefing: {
          ...BRIEFING_BODY.briefing,
          geo: { type: 'Point', coordinates: [8.68, 50.11] },
        },
      },
      'OFFEN',
    );
    const [, body] = postSpy.mock.calls[0] as [string, { briefing: { geo?: object } }];
    expect(body.briefing.geo).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// vectorHybridSearch — currently 503
// ---------------------------------------------------------------------------

describe('vectorHybridSearch', () => {
  it('POSTs to /vector_hybrid_search', async () => {
    const data: import('../uc4Tools').VectorHybridSearchData = {
      hits: [],
      embedding_model: 'cohere-embed-v3',
      total_corpus_size: 0,
    };
    const { mod, postSpy } = await loadWithPostSpy({ ...TOOL_RESPONSE_BASE, data });
    await mod.vectorHybridSearch({ query: 'jamming event', top_k: 5 }, 'OFFEN');
    const [endpoint] = postSpy.mock.calls[0] as [string];
    expect(endpoint).toBe('/vector_hybrid_search');
  });

  it('throws ToolError with retry-after on 503', async () => {
    const axErr = {
      response: {
        data: {
          type: 'about:blank',
          title: 'Service Unavailable',
          status: 503,
          detail: 'embeddings not yet computed',
          'retry-after': 3600,
        },
      },
    } as AxiosError;
    const { mod } = await loadWithPostRejection(axErr);

    await expect(
      mod.vectorHybridSearch({ query: 'test', top_k: 3 }, 'OFFEN'),
    ).rejects.toMatchObject({ name: 'ToolError', problem: { status: 503, 'retry-after': 3600 } });
  });

  it('forwards source_types filter when provided', async () => {
    const { mod, postSpy } = await loadWithPostSpy({
      ...TOOL_RESPONSE_BASE,
      data: { hits: [], embedding_model: '', total_corpus_size: 0 },
    });
    await mod.vectorHybridSearch(
      { query: 'ais anomaly', top_k: 10, filters: { source_types: ['ais', 'ems'] } },
      'NFD',
    );
    const [, body] = postSpy.mock.calls[0] as [string, { filters?: { source_types?: string[] } }];
    expect(body.filters?.source_types).toEqual(['ais', 'ems']);
  });
});

// ---------------------------------------------------------------------------
// uc4Tools namespace re-exports
// ---------------------------------------------------------------------------

describe('uc4Tools default export', () => {
  it('re-exports all four functions', async () => {
    vi.doMock('axios', () => ({ default: { create: vi.fn(() => ({ post: vi.fn() })) } }));
    const { uc4Tools } = await import('../uc4Tools');
    expect(typeof uc4Tools.graphQuery).toBe('function');
    expect(typeof uc4Tools.spatialAggregate).toBe('function');
    expect(typeof uc4Tools.persistBriefing).toBe('function');
    expect(typeof uc4Tools.vectorHybridSearch).toBe('function');
  });
});
