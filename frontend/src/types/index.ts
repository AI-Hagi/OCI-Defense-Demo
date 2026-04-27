// Type definitions for the Sovereign Defence Intelligence Platform.
// Field names are aligned with /db/schema/02_core_tables.sql (Oracle 26ai).

// ---------------------------------------------------------------------------
// Tenant (from 01_tenants_and_security.sql).
// ---------------------------------------------------------------------------
export interface Tenant {
  tenant_id: string;
  code: string; // e.g. DEU_BMVG
  display_name: string; // e.g. Germany BMVg
  country_iso3: string; // e.g. DEU
}

// ---------------------------------------------------------------------------
// USE CASE 1: GEOINT
// ---------------------------------------------------------------------------
export type Classification = 'U' | 'R' | 'C' | 'S' | 'VS-NFD';

export interface GeoJsonPolygon {
  type: 'Polygon';
  coordinates: number[][][]; // [ring][point][lon,lat]
}

export interface YoloDetection {
  cls: string;
  confidence: number;
  bbox: [number, number, number, number];
}

export type PlatformKind = 'satellite' | 'uav';

export interface SatelliteScene {
  scene_id: string;
  tenant_id: string;
  captured_at: string;
  sensor: string;
  footprint: GeoJsonPolygon | null;
  cloud_cover: number | null;
  yolo_detections: YoloDetection[] | null;
  ols_label: number | null;
  ingested_at: string;
  // Object Storage object name within sovdefence-images. Null when the bucket
  // upload was skipped (env unset, IMDS unavailable, or PUT failed); the
  // detections+row are still persisted so the table view stays functional.
  image_uri: string | null;
  // UC1 multi-source: 'satellite' (default) | 'uav'.
  platform_kind: PlatformKind;
  // UAV-only telemetry; null for satellite captures.
  altitude_m: number | null;
  heading_deg: number | null;
}

// ---------------------------------------------------------------------------
// USE CASE 2: Document Intelligence (RAG)
// ---------------------------------------------------------------------------
export interface DocumentSummary {
  doc_id: string;
  tenant_id: string;
  title: string;
  classification: Classification;
  source_uri: string | null;
  uploaded_at: string;
  ols_label: number | null;
}

export interface RagCitation {
  doc_id: string;
  chunk_idx: number;
  title?: string;
  snippet?: string;
}

export interface RagMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  citations?: RagCitation[];
}

// ---------------------------------------------------------------------------
// USE CASE 3: Multi-Tenant Collaboration
// ---------------------------------------------------------------------------
export type ArtefactType =
  | 'document'
  | 'scene'
  | 'osint_entity'
  | 'sc_node'
  | 'compliance_finding';

export interface CollabShare {
  share_id: string;
  owner_tenant: string;
  partner_tenant: string;
  artefact_type: ArtefactType;
  artefact_id: string;
  granted_at: string;
  expires_at: string | null;
  ols_label: number | null;
  classification?: Classification;
  title?: string;
}

// ---------------------------------------------------------------------------
// USE CASE 4: OSINT & Threat Fusion
// ---------------------------------------------------------------------------
export type OsintKind =
  | 'person'
  | 'organization'
  | 'location'
  | 'vessel'
  | 'aircraft'
  | 'company'
  | 'asset'
  | 'event'
  | 'indicator'
  | 'malware'
  | 'actor'
  // UC4 EMS-Lagebildfusion: electromagnetic spectrum emitter / indicator.
  | 'ems_emission';

// UC4 — frequency-bucket aggregate from /api/osint/ems/clusters.
export interface EmsCluster {
  bucket_mhz_start: number | null;
  bucket_mhz_end: number | null;
  emitter_count: number;
  sample_entity_id: string;
}

export interface OsintNode {
  entity_id: string;
  tenant_id: string;
  kind: OsintKind;
  canonical_name: string;
  attributes: Record<string, unknown> | null;
  ols_label: number | null;
  created_at: string;
}

export interface OsintEdge {
  rel_id: string;
  src_id: string;
  dst_id: string;
  rel_type: string;
  confidence: number | null;
  evidence: Record<string, unknown> | null;
  ols_label: number | null;
  observed_at: string;
}

export interface OsintGraph {
  nodes: OsintNode[];
  edges: OsintEdge[];
}

// ---------------------------------------------------------------------------
// USE CASE 5: Supply Chain
// ---------------------------------------------------------------------------
export type ScNodeType = 'supplier' | 'hub' | 'mine' | 'port' | 'factory';
export type ScEdgeType =
  | 'ships_to'
  | 'supplies'
  | 'transports'
  | 'depends_on'
  | 'owned_by';

export interface ScNode {
  node_id: string;
  tenant_id: string;
  node_type: ScNodeType;
  display_name: string;
  country_iso3: string;
  latitude: number | null;
  longitude: number | null;
  criticality: number;
  ols_label: number | null;
  latest_risk_score?: number | null;
}

export interface ScEdge {
  edge_id: string;
  src_node: string;
  dst_node: string;
  edge_type: ScEdgeType;
  lead_time_days: number | null;
  dependency_level: number | null;
  ols_label: number | null;
}

export interface ScRiskPoint {
  node_id: string;
  as_of: string; // ISO date
  risk_score: number;
  risk_breakdown: Record<string, number> | null;
}

// ---------------------------------------------------------------------------
// USE CASE 6: Compliance Automation
// ---------------------------------------------------------------------------
export type Framework = 'NIS2' | 'DORA' | 'GDPR' | 'VSNFD';
export type ControlStatus =
  | 'open'
  | 'mitigated'
  | 'accepted'
  | 'false_positive'
  | 'closed';

export interface ComplianceControl {
  control_id: string;
  framework: Framework;
  code: string;
  title: string;
  description: string | null;
  tenant_id: string;
  ols_label: number | null;
  status?: ControlStatus; // derived from latest finding
}

// Matches the JSON returned by GET /api/compliance/score (compliance.py:177).
// score_pct = (implemented / total) * 100 + live_penalty, clamped to [0, 100].
export interface ComplianceFrameworkScore {
  framework: Framework;
  total: number;
  implemented: number;
  score_pct: number;
  live_penalty: number; // ≤0; -5 per open Cloud Guard problem, capped at -25
}

// Live security telemetry served by the backend under /api/compliance/live/*.
// Each shape carries an `as_of` ISO timestamp and an optional `error` string —
// when the backend cannot reach OCI (e.g. instance principal unavailable),
// it returns `error: 'instance_principal_unavailable'` and zeroed counters.
export interface CloudGuardLive {
  open_problems: number;
  high_risk: number;
  as_of: string;
  error?: string;
}

export interface AdbEncryptionLive {
  adb_count: number;
  encrypted_count: number;
  compliant: boolean;
  as_of: string;
  error?: string;
}

export interface BucketAccessLive {
  bucket_count: number;
  public_count: number;
  compliant: boolean;
  as_of: string;
  error?: string;
}

export interface OlsStatusLive {
  policy_name: string;
  applied_to_tables: number;
  active: boolean;
  as_of: string;
  error?: string;
}
