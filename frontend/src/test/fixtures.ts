// Deterministic fixtures for the Sovereign Defence msw server and view tests.
// Field names align with /src/types and /db/schema/02_core_tables.sql.

export const sceneFixtures = [
  {
    scene_id: 'S001',
    tenant_id: 'T001',
    captured_at: '2026-04-20T10:15:00Z',
    sensor: 'Sentinel-2',
    footprint: {
      type: 'Polygon',
      coordinates: [[[10, 50], [11, 50], [11, 51], [10, 51], [10, 50]]],
    },
    cloud_cover: 12.4,
    yolo_detections: [{ cls: 'vessel', confidence: 0.92, bbox: [0, 0, 10, 10] }],
    ols_label: 30,
    ingested_at: '2026-04-20T10:30:00Z',
    image_uri: 'scenes/tenant=T001/abcd-S001.jpg',
  },
  {
    scene_id: 'S002',
    tenant_id: 'T001',
    captured_at: '2026-04-21T09:00:00Z',
    sensor: 'ICEYE',
    footprint: null,
    cloud_cover: null,
    yolo_detections: null,
    ols_label: 20,
    ingested_at: '2026-04-21T09:15:00Z',
    image_uri: null,
  },
];

export const docHits = [
  {
    doc_id: 'D001',
    chunk_idx: 0,
    title: 'NIS2 Annex',
    snippet: 'geo-redundancy baseline',
    score: 0.87,
  },
];

export const ragReply = {
  role: 'assistant' as const,
  content: 'NIS2 erfordert geo-redundante Systeme.',
  citations: [
    { doc_id: 'D001', chunk_idx: 0, title: 'NIS2 Annex', snippet: 'geo-redundancy' },
  ],
};

export const collabShares = [
  {
    share_id: 'SH001',
    owner_tenant: 'T001',
    partner_tenant: 'T002',
    artefact_type: 'document' as const,
    artefact_id: 'D001',
    granted_at: '2026-04-01T00:00:00Z',
    expires_at: null,
    ols_label: 30,
    classification: 'R' as const,
    title: 'BMVg -> DGA Lagebild',
  },
  {
    share_id: 'SH002',
    owner_tenant: 'T002',
    partner_tenant: 'T003',
    artefact_type: 'scene' as const,
    artefact_id: 'S010',
    granted_at: '2026-04-02T00:00:00Z',
    expires_at: null,
    ols_label: 20,
    classification: 'U' as const,
    title: 'DGA -> MoD Aufklaerung',
  },
  {
    share_id: 'SH003',
    owner_tenant: 'T003',
    partner_tenant: 'T001',
    artefact_type: 'osint_entity' as const,
    artefact_id: 'E007',
    granted_at: '2026-04-03T00:00:00Z',
    expires_at: null,
    ols_label: 30,
    classification: 'C' as const,
    title: 'MoD -> BMVg Threat Actor',
  },
];

export const osintGraph = {
  nodes: [
    {
      entity_id: 'E100',
      tenant_id: 'T001',
      kind: 'actor' as const,
      canonical_name: 'Fancy Bear',
      attributes: { country: 'RU' },
      ols_label: 40,
      created_at: '2026-04-10T00:00:00Z',
    },
    {
      entity_id: 'E101',
      tenant_id: 'T001',
      kind: 'malware' as const,
      canonical_name: 'X-Agent',
      attributes: null,
      ols_label: 40,
      created_at: '2026-04-10T00:00:00Z',
    },
  ],
  edges: [
    {
      rel_id: 'R1',
      src_id: 'E100',
      dst_id: 'E101',
      rel_type: 'uses',
      confidence: 0.8,
      evidence: null,
      ols_label: 40,
      observed_at: '2026-04-10T00:00:00Z',
    },
  ],
};

export const osintEntities = osintGraph.nodes;

export const scNodes = [
  {
    node_id: 'N001',
    tenant_id: 'T001',
    node_type: 'mine' as const,
    display_name: 'Kiruna',
    country_iso3: 'SWE',
    latitude: 67.85,
    longitude: 20.22,
    criticality: 0.9,
    ols_label: 20,
    latest_risk_score: 0.42,
  },
  {
    node_id: 'N002',
    tenant_id: 'T001',
    node_type: 'port' as const,
    display_name: 'Hamburg',
    country_iso3: 'DEU',
    latitude: 53.55,
    longitude: 9.99,
    criticality: 0.7,
    ols_label: 20,
    latest_risk_score: 0.33,
  },
];

export const scEdges = [
  {
    edge_id: 'EDG1',
    src_node: 'N001',
    dst_node: 'N002',
    edge_type: 'ships_to' as const,
    lead_time_days: 7,
    dependency_level: 0.6,
    ols_label: 20,
  },
];

export const scRisk = [
  { node_id: 'N001', as_of: '2026-04-01', risk_score: 0.33, risk_breakdown: { geo: 0.2 } },
  { node_id: 'N001', as_of: '2026-04-15', risk_score: 0.42, risk_breakdown: { geo: 0.3 } },
];

export const complianceControls = [
  {
    control_id: 'C001',
    framework: 'NIS2' as const,
    code: 'NIS2-21',
    title: 'Risk Mgmt',
    description: 'Art 21',
    tenant_id: 'T001',
    ols_label: 20,
    status: 'mitigated' as const,
  },
  {
    control_id: 'C002',
    framework: 'DORA' as const,
    code: 'DORA-5',
    title: 'ICT Risk',
    description: null,
    tenant_id: 'T001',
    ols_label: 20,
    status: 'open' as const,
  },
  {
    control_id: 'C003',
    framework: 'GDPR' as const,
    code: 'GDPR-32',
    title: 'Security of processing',
    description: null,
    tenant_id: 'T001',
    ols_label: 20,
    status: 'closed' as const,
  },
  {
    control_id: 'C004',
    framework: 'VSNFD' as const,
    code: 'VS-1',
    title: 'VS-NfD Handling',
    description: null,
    tenant_id: 'T001',
    ols_label: 30,
    status: 'accepted' as const,
  },
];

export const complianceScore = [
  { framework: 'NIS2',  total: 12, implemented: 9,  score_pct: 75,    live_penalty: 0 },
  { framework: 'DORA',  total: 8,  implemented: 5,  score_pct: 62.5,  live_penalty: 0 },
  { framework: 'GDPR',  total: 6,  implemented: 5,  score_pct: 83.33, live_penalty: 0 },
  { framework: 'VSNFD', total: 5,  implemented: 4,  score_pct: 80,    live_penalty: 0 },
];

// ---------------------------------------------------------------------------
// Live security telemetry — fixtures for /api/compliance/live/*.
// Tests can override `complianceLive.cloudGuard.error = 'instance_principal_unavailable'`
// to exercise the degraded path in ComplianceView.
// ---------------------------------------------------------------------------
export const complianceLive: {
  cloudGuard: {
    open_problems: number;
    high_risk: number;
    as_of: string;
    error?: string;
  };
  adbEncryption: {
    adb_count: number;
    encrypted_count: number;
    compliant: boolean;
    as_of: string;
    error?: string;
  };
  bucketAccess: {
    bucket_count: number;
    public_count: number;
    compliant: boolean;
    as_of: string;
    error?: string;
  };
  olsStatus: {
    policy_name: string;
    applied_to_tables: number;
    active: boolean;
    as_of: string;
    error?: string;
  };
} = {
  cloudGuard: {
    open_problems: 4,
    high_risk: 1,
    as_of: '2026-04-27T08:00:00Z',
  },
  adbEncryption: {
    adb_count: 3,
    encrypted_count: 3,
    compliant: true,
    as_of: '2026-04-27T08:00:00Z',
  },
  bucketAccess: {
    bucket_count: 12,
    public_count: 0,
    compliant: true,
    as_of: '2026-04-27T08:00:00Z',
  },
  olsStatus: {
    policy_name: 'SOVDEF_OLS',
    applied_to_tables: 7,
    active: true,
    as_of: '2026-04-27T08:00:00Z',
  },
};
