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
  | 'actor';

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

export interface ComplianceFrameworkScore {
  framework: Framework;
  score: number; // 0-100
  total_controls: number;
  compliant_controls: number;
}
