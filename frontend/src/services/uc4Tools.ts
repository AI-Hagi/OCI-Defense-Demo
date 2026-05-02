/**
 * Typed client for the four UC4_OSINT ORDS tools (Tag 6).
 *
 * Endpoint base:  /ords/uc4_osint/api/v1/tools/<tool>
 *
 * All four tools share:
 *   - method POST, JSON body
 *   - X-OLS-Label-Max header forwarded by the caller (default OFFEN if omitted)
 *   - Response wrapper:
 *       { request_id, duration_ms, data: <tool-specific>,
 *         ols_cap_applied, ols_cap_label }
 *   - Error responses use RFC 7807 problem+json
 *       { type, title, status, detail, instance, ... }
 *
 * vector_hybrid_search returns 503 today (embeddings NULL — see
 * db/seeds/uc4_osint/02_compute_embeddings.sql header BLOCKER block).
 */
import axios, { AxiosError } from 'axios';

export type OlsLabel = 'OFFEN' | 'INTERN' | 'NFD' | 'GEHEIM';

const ORDS_BASE: string =
  // Allow VITE_ORDS_BASE override for non-prod targets; default to the live
  // ATP endpoint which is also what scripts/test-uc4-tools.sh uses.
  (import.meta.env?.VITE_ORDS_BASE as string | undefined) ??
  'https://G8CC3767E64A14A-SOVDEF26.adb.eu-frankfurt-1.oraclecloudapps.com/ords';

const TOOLS_BASE = `${ORDS_BASE}/uc4_osint/api/v1/tools`;

// ---------------------------------------------------------------------------
// Common response wrapper
// ---------------------------------------------------------------------------
export interface ToolResponse<TData> {
  request_id: string;
  duration_ms: number;
  data: TData;
  ols_cap_applied: number;
  ols_cap_label: OlsLabel;
}

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  // vector_hybrid_search 503 carries this
  'retry-after'?: number;
}

export class ToolError extends Error {
  constructor(public readonly problem: ProblemDetails) {
    super(problem.title);
    this.name = 'ToolError';
  }
}

const httpClient = axios.create({
  baseURL: TOOLS_BASE,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

async function postTool<TBody, TData>(
  endpoint: string,
  body: TBody,
  cap: OlsLabel,
): Promise<ToolResponse<TData>> {
  try {
    const res = await httpClient.post<ToolResponse<TData>>(endpoint, body, {
      headers: { 'X-OLS-Label-Max': cap },
    });
    return res.data;
  } catch (err) {
    const ax = err as AxiosError<ProblemDetails>;
    if (ax.response?.data && typeof ax.response.data === 'object') {
      throw new ToolError(ax.response.data);
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// graph_query
// ---------------------------------------------------------------------------
export interface GraphQueryMultiSourceArgs {
  hours: number;
  min_correlations: number;
}

export interface GraphQueryConvergenceArgs {
  hours: number;
  h3_cell: string;
}

export interface MultiSourceEntity {
  entity_id: string;
  entity_kind: string;
  display_name: string;
  canonical_id: string;
  corr_count: number;
  correlation_ids: string[];
}

export interface ConvergenceCorrelation {
  correlation_id: string;
  correlation_kind: string;
  summary: string;
  detected_at: string;
  score: number | null;
  event_count: number;
  event_ids: string[];
}

export type GraphQueryData =
  | { entities: MultiSourceEntity[] | null }
  | { h3_cell: string; hours: number; correlations: ConvergenceCorrelation[] | null };

export interface GraphQueryRequest {
  pattern: 'multi_source_entity' | 'convergence';
  args: GraphQueryMultiSourceArgs | GraphQueryConvergenceArgs;
}

export function graphQuery(
  body: GraphQueryRequest,
  cap: OlsLabel,
): Promise<ToolResponse<GraphQueryData>> {
  return postTool('/graph_query', body, cap);
}

// ---------------------------------------------------------------------------
// spatial_aggregate
// ---------------------------------------------------------------------------
export interface SpatialAggregateRequest {
  h3_resolution: 5; // only 5 supported today
  hours: number;
  min_events: number;
  bbox?: {
    min_lat: number;
    max_lat: number;
    min_lon: number;
    max_lon: number;
  };
}

export interface H3BucketProperties {
  h3_cell: string;
  event_count: number;
  variety: number;
  centroid_lat: number;
  centroid_lon: number;
}

export interface H3BucketFeature {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number, number] };
  properties: H3BucketProperties;
}

export interface SpatialAggregateData {
  type: 'FeatureCollection';
  features: H3BucketFeature[] | null;
}

export function spatialAggregate(
  body: SpatialAggregateRequest,
  cap: OlsLabel,
): Promise<ToolResponse<SpatialAggregateData>> {
  return postTool('/spatial_aggregate', body, cap);
}

// ---------------------------------------------------------------------------
// persist_briefing — the agent calls this; surfaced for completeness
// ---------------------------------------------------------------------------
export interface BriefingRequest {
  briefing: {
    title: string;
    summary: string;
    classification: 'OFFEN' | 'INTERN' | 'NFD';
    findings: Array<{ text: string; [k: string]: unknown }>;
    confidence: number;
    correlation_id: string;
    tags?: string[];
    geo?: { type: 'Point'; coordinates: [number, number] };
  };
}

export interface BriefingPersisted {
  briefing_id: string;
  persisted_at: string;
}

export function persistBriefing(
  body: BriefingRequest,
  cap: OlsLabel,
): Promise<ToolResponse<BriefingPersisted>> {
  return postTool('/persist_briefing', body, cap);
}

// ---------------------------------------------------------------------------
// vector_hybrid_search — currently always 503; thin wrapper for symmetry
// ---------------------------------------------------------------------------
export interface VectorHybridSearchRequest {
  query: string;
  top_k: number;
  filters?: {
    source_types?: string[];
    occurred_after?: string;
  };
}

export interface VectorHit {
  event_id: string;
  source_type: string;
  summary: string;
  distance: number;
  score: number;
  occurred_at: string;
  ols_label: number;
}

export interface VectorHybridSearchData {
  hits: VectorHit[];
  embedding_model: string;
  total_corpus_size: number;
}

export function vectorHybridSearch(
  body: VectorHybridSearchRequest,
  cap: OlsLabel,
): Promise<ToolResponse<VectorHybridSearchData>> {
  return postTool('/vector_hybrid_search', body, cap);
}

export const uc4Tools = {
  graphQuery,
  spatialAggregate,
  persistBriefing,
  vectorHybridSearch,
};
