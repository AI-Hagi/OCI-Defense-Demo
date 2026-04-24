import axios, { type AxiosInstance } from 'axios';
import type {
  ComplianceControl,
  ComplianceFrameworkScore,
  CollabShare,
  Framework,
  OsintGraph,
  RagMessage,
  SatelliteScene,
  ScEdge,
  ScNode,
  ScRiskPoint,
} from '../types';

// Axios instance bound to the Sovereign Defence backend.
// baseURL comes from VITE_API_BASE; falls back to /api (proxied by Vite / ORDS).
const baseURL = import.meta.env.VITE_API_BASE ?? '/api';

export const apiClient: AxiosInstance = axios.create({
  baseURL,
  timeout: 30_000,
});

// Request interceptor: inject the selected tenant as X-Tenant-Id on every call.
apiClient.interceptors.request.use((config) => {
  const tenantId =
    (typeof localStorage !== 'undefined'
      ? localStorage.getItem('sov:tenant')
      : null) ?? 'T001';
  config.headers = config.headers ?? {};
  (config.headers as Record<string, string>)['X-Tenant-Id'] = tenantId;
  return config;
});

// ---------------------------------------------------------------------------
// USE CASE 1: GEOINT
// ---------------------------------------------------------------------------
export const geoint = {
  async listScenes(): Promise<SatelliteScene[]> {
    const { data } = await apiClient.get<SatelliteScene[]>('/geoint/scenes');
    return data;
  },
  async uploadScene(file: File): Promise<SatelliteScene> {
    const form = new FormData();
    form.append('file', file);
    const { data } = await apiClient.post<SatelliteScene>(
      '/geoint/scenes',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return data;
  },
};

// ---------------------------------------------------------------------------
// USE CASE 2: Document Intelligence (RAG)
// ---------------------------------------------------------------------------
export interface DocSearchHit {
  doc_id: string;
  chunk_idx: number;
  title: string;
  snippet: string;
  score: number;
}

export const docs = {
  async search(q: string, k = 10): Promise<DocSearchHit[]> {
    const { data } = await apiClient.get<DocSearchHit[]>('/docs/search', {
      params: { q, k },
    });
    return data;
  },
  async ragChat(messages: RagMessage[]): Promise<RagMessage> {
    const { data } = await apiClient.post<RagMessage>('/docs/chat', {
      messages,
    });
    return data;
  },
};

// ---------------------------------------------------------------------------
// USE CASE 3: Multi-Tenant Collaboration
// ---------------------------------------------------------------------------
export const collab = {
  async shares(): Promise<CollabShare[]> {
    const { data } = await apiClient.get<CollabShare[]>('/collab/shares');
    return data;
  },
};

// ---------------------------------------------------------------------------
// USE CASE 4: OSINT & Threat Fusion
// ---------------------------------------------------------------------------
export const osint = {
  async graph(startId: string, maxHops = 2): Promise<OsintGraph> {
    const { data } = await apiClient.get<OsintGraph>('/osint/graph', {
      params: { start: startId, hops: maxHops },
    });
    return data;
  },
};

// ---------------------------------------------------------------------------
// USE CASE 5: Supply Chain
// ---------------------------------------------------------------------------
export const sc = {
  async nodes(): Promise<ScNode[]> {
    const { data } = await apiClient.get<ScNode[]>('/sc/nodes');
    return data;
  },
  async edges(): Promise<ScEdge[]> {
    const { data } = await apiClient.get<ScEdge[]>('/sc/edges');
    return data;
  },
  async risk(nodeId: string): Promise<ScRiskPoint[]> {
    const { data } = await apiClient.get<ScRiskPoint[]>(
      `/sc/nodes/${encodeURIComponent(nodeId)}/risk`,
    );
    return data;
  },
};

// ---------------------------------------------------------------------------
// USE CASE 6: Compliance Automation
// ---------------------------------------------------------------------------
export const compliance = {
  async controls(framework?: Framework): Promise<ComplianceControl[]> {
    const { data } = await apiClient.get<ComplianceControl[]>(
      '/compliance/controls',
      { params: framework ? { framework } : undefined },
    );
    return data;
  },
  async score(): Promise<ComplianceFrameworkScore[]> {
    const { data } = await apiClient.get<ComplianceFrameworkScore[]>(
      '/compliance/score',
    );
    return data;
  },
};

export const api = { geoint, docs, collab, osint, sc, compliance };
export default api;
