import axios, { type AxiosInstance } from 'axios';
import type {
  AdbEncryptionLive,
  BucketAccessLive,
  CloudGuardLive,
  ComplianceControl,
  ComplianceFrameworkScore,
  CollabShare,
  Framework,
  OlsStatusLive,
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
export interface UploadSceneOptions {
  // UC1 multi-source — defaults to satellite when omitted.
  platformKind?: 'satellite' | 'uav';
  altitudeM?: number;
  headingDeg?: number;
}

// Upload response is richer than the listed-scene shape — it includes the
// detection list inline (so the UI can show counts without re-fetching) and
// a flag telling us whether the footprint was extracted from real EXIF GPS
// or synthesised from the Mitteleuropa default.
export interface UploadSceneResult {
  scene_id: string;
  image_uri: string | null;
  platform_kind: 'satellite' | 'uav';
  altitude_m: number | null;
  heading_deg: number | null;
  detections: Array<{ label: string; conf: number; bbox: [number, number, number, number] }>;
  count: number;
  footprint_lat: number;
  footprint_lon: number;
  is_synthetic_footprint: boolean;
}

export const geoint = {
  async listScenes(): Promise<SatelliteScene[]> {
    const { data } = await apiClient.get<SatelliteScene[]>('/geoint/scenes');
    return data;
  },
  async uploadScene(
    file: File,
    opts: UploadSceneOptions = {},
  ): Promise<UploadSceneResult> {
    const form = new FormData();
    form.append('file', file);
    const headers: Record<string, string> = {
      'Content-Type': 'multipart/form-data',
    };
    if (opts.platformKind) headers['X-Platform-Kind'] = opts.platformKind;
    if (opts.altitudeM != null) headers['X-Altitude-M'] = String(opts.altitudeM);
    if (opts.headingDeg != null) headers['X-Heading-Deg'] = String(opts.headingDeg);
    const { data } = await apiClient.post<UploadSceneResult>(
      '/geoint/scenes/upload',
      form,
      { headers },
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
    const { data } = await apiClient.get<DocSearchHit[]>('/documents/search', {
      params: { q, k },
    });
    return data;
  },
  async ragChat(messages: RagMessage[]): Promise<RagMessage> {
    const { data } = await apiClient.post<RagMessage>('/documents/chat', {
      messages,
    });
    return data;
  },
  async uploadDocument(
    file: File,
    title: string,
    classification: 'OFFEN' | 'INTERN' | 'NFD' | 'GEHEIM' = 'INTERN',
  ): Promise<DocUploadResult> {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('classification', classification);
    const { data } = await apiClient.post<DocUploadResult>(
      '/documents/upload',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return data;
  },
};

export interface DocUploadResult {
  doc_id: string;
  title: string;
  classification: string;
  ols_label: number;
  chunk_count: number;
  first_chunk_preview: string;
  citations_hint: Array<{ doc_id: string; chunk_idx: number }>;
}

// ---------------------------------------------------------------------------
// USE CASE 3: Multi-Tenant Collaboration
// ---------------------------------------------------------------------------
export const collab = {
  async shares(): Promise<CollabShare[]> {
    const { data } = await apiClient.get<CollabShare[]>('/compliance/collab-shares');
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
  // Live security telemetry — polled by ComplianceView. Backend may degrade
  // gracefully and return `{ error: 'instance_principal_unavailable', ... }`.
  live: {
    async cloudGuard(): Promise<CloudGuardLive> {
      const { data } = await apiClient.get<CloudGuardLive>(
        '/compliance/live/cloud-guard',
      );
      return data;
    },
    async adbEncryption(): Promise<AdbEncryptionLive> {
      const { data } = await apiClient.get<AdbEncryptionLive>(
        '/compliance/live/adb-encryption',
      );
      return data;
    },
    async bucketAccess(): Promise<BucketAccessLive> {
      const { data } = await apiClient.get<BucketAccessLive>(
        '/compliance/live/bucket-public-access',
      );
      return data;
    },
    async olsStatus(): Promise<OlsStatusLive> {
      const { data } = await apiClient.get<OlsStatusLive>(
        '/compliance/live/ols-status',
      );
      return data;
    },
  },
};

export const api = { geoint, docs, collab, osint, sc, compliance };
export default api;
