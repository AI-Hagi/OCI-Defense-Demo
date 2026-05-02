--==============================================================================
-- File:        02_core_tables.sql
-- Purpose:     Core domain tables for the Sovereign Defence Intelligence
--              Platform, covering the six canonical use cases:
--                1) GEOINT                    (satellite_scenes, scene_embeddings)
--                2) Document Intelligence     (documents, document_chunks,
--                                              document_embeddings)
--                3) Multi-Tenant Collaboration(collab_shares, shared_artefacts)
--                4) OSINT & Threat Fusion     (osint_entities, osint_relationships)
--                5) Supply Chain              (sc_nodes, sc_edges, sc_risk)
--                6) Compliance Automation     (compliance_controls,
--                                              compliance_findings,
--                                              compliance_evidence)
-- Target:      Oracle AI Database 26ai (Autonomous Transaction Processing)
-- Depends on:  01_tenants_and_security.sql  (tenants table, OLS policy
--              DICE_POLICY with levels U=10, R=30, C=50, S=70 and compartments
--              INTEL, OPS, LOGISTICS, LEGAL)
--
-- Conventions:
--   * Every sensitive table carries an OLS label column `ols_label NUMBER`.
--     The OLS policy `DICE_POLICY` is attached in 01_tenants_and_security.sql.
--   * VECTOR columns are declared here but their HNSW indexes are created in
--     04_vector_search.sql.
--   * SDO_GEOMETRY columns are declared here but their spatial indexes are
--     created in 06_spatial.sql.
--   * JSON payloads use the native 26ai `JSON` data type (OSON binary).
--==============================================================================

SET DEFINE OFF;

--------------------------------------------------------------------------------
-- USE CASE 1: GEOINT (Satellite Imagery + YOLOv8 detections)
--------------------------------------------------------------------------------

CREATE TABLE satellite_scenes (
    scene_id         VARCHAR2(36)  DEFAULT SYS_GUID() NOT NULL,
    tenant_id        VARCHAR2(36)                     NOT NULL,
    captured_at      TIMESTAMP WITH TIME ZONE         NOT NULL,
    sensor           VARCHAR2(40)                     NOT NULL,
    footprint        SDO_GEOMETRY,
    cloud_cover      NUMBER(5,2),
    yolo_detections  JSON,
    ols_label        NUMBER,
    ingested_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_satellite_scenes PRIMARY KEY (scene_id),
    CONSTRAINT fk_scenes_tenant    FOREIGN KEY (tenant_id)
                                   REFERENCES tenants (tenant_id),
    CONSTRAINT ck_scenes_cloud     CHECK (cloud_cover BETWEEN 0 AND 100)
);

CREATE INDEX idx_scenes_tenant_time
    ON satellite_scenes (tenant_id, captured_at DESC);
CREATE INDEX idx_scenes_sensor
    ON satellite_scenes (sensor);

COMMENT ON TABLE satellite_scenes IS
  'GEOINT use case: raw satellite scene metadata with WGS84 footprint and YOLOv8 detection payload. Spatial index in 06_spatial.sql.';

CREATE TABLE scene_embeddings (
    scene_id    VARCHAR2(36) NOT NULL,
    model_name  VARCHAR2(80) DEFAULT 'clip-vit-l-14' NOT NULL,
    embedding   VECTOR(768, FLOAT32),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_scene_embeddings PRIMARY KEY (scene_id, model_name),
    CONSTRAINT fk_scene_emb_scene  FOREIGN KEY (scene_id)
                                   REFERENCES satellite_scenes (scene_id)
                                   ON DELETE CASCADE
);

COMMENT ON TABLE scene_embeddings IS
  'GEOINT use case: 768-dim image embedding per scene for similarity search. HNSW index in 04_vector_search.sql.';

--------------------------------------------------------------------------------
-- USE CASE 2: Document Intelligence (RAG over classified documents)
--------------------------------------------------------------------------------

CREATE TABLE documents (
    doc_id          VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    tenant_id       VARCHAR2(36)                    NOT NULL,
    title           VARCHAR2(400)                   NOT NULL,
    classification  VARCHAR2(10)                    NOT NULL,
    source_uri      VARCHAR2(2000),
    uploaded_at     TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    ols_label       NUMBER,
    content_json    JSON,
    CONSTRAINT pk_documents          PRIMARY KEY (doc_id),
    CONSTRAINT fk_documents_tenant   FOREIGN KEY (tenant_id)
                                     REFERENCES tenants (tenant_id),
    CONSTRAINT ck_documents_class    CHECK (classification IN
                                     ('U','R','C','S','VS-NFD'))
);

CREATE INDEX idx_documents_tenant  ON documents (tenant_id, uploaded_at DESC);
CREATE INDEX idx_documents_class   ON documents (classification);

COMMENT ON TABLE documents IS
  'Document Intelligence use case: top-level document record. Classification marker (U/R/C/S/VS-NFD) aligns with OLS label levels in DICE_POLICY.';

CREATE TABLE document_chunks (
    chunk_id    VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    doc_id      VARCHAR2(36)                    NOT NULL,
    chunk_idx   NUMBER(10)                      NOT NULL,
    text        CLOB                            NOT NULL,
    tokens      NUMBER(6),
    ols_label   NUMBER,
    CONSTRAINT pk_doc_chunks       PRIMARY KEY (chunk_id),
    CONSTRAINT uq_doc_chunks_idx   UNIQUE (doc_id, chunk_idx),
    CONSTRAINT fk_doc_chunks_doc   FOREIGN KEY (doc_id)
                                   REFERENCES documents (doc_id)
                                   ON DELETE CASCADE
);

-- idx_doc_chunks_doc removed: already covered by uq_doc_chunks_idx UNIQUE constraint index

COMMENT ON TABLE document_chunks IS
  'Document Intelligence use case: chunked text for RAG. chunk_idx is 0-based sequence within a document.';

CREATE TABLE document_embeddings (
    chunk_id    VARCHAR2(36) NOT NULL,
    model_name  VARCHAR2(80) DEFAULT 'bge-large-en-v1.5' NOT NULL,
    embedding   VECTOR(1024, FLOAT32),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_doc_embeddings     PRIMARY KEY (chunk_id, model_name),
    CONSTRAINT fk_doc_emb_chunk      FOREIGN KEY (chunk_id)
                                     REFERENCES document_chunks (chunk_id)
                                     ON DELETE CASCADE
);

COMMENT ON TABLE document_embeddings IS
  'Document Intelligence use case: 1024-dim embedding per chunk (bge-large). HNSW index in 04_vector_search.sql.';

--------------------------------------------------------------------------------
-- USE CASE 3: Multi-Tenant Collaboration (DICE-EU, Label Security)
--------------------------------------------------------------------------------

CREATE TABLE collab_shares (
    share_id        VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    owner_tenant    VARCHAR2(36)                    NOT NULL,
    partner_tenant  VARCHAR2(36)                    NOT NULL,
    artefact_type   VARCHAR2(40)                    NOT NULL,
    artefact_id     VARCHAR2(36)                    NOT NULL,
    granted_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    expires_at      TIMESTAMP WITH TIME ZONE,
    ols_label       NUMBER,
    CONSTRAINT pk_collab_shares         PRIMARY KEY (share_id),
    CONSTRAINT fk_collab_owner          FOREIGN KEY (owner_tenant)
                                        REFERENCES tenants (tenant_id),
    CONSTRAINT fk_collab_partner        FOREIGN KEY (partner_tenant)
                                        REFERENCES tenants (tenant_id),
    CONSTRAINT ck_collab_partners_diff  CHECK (owner_tenant <> partner_tenant),
    CONSTRAINT ck_collab_artefact_type  CHECK (artefact_type IN
                                        ('document','scene','osint_entity',
                                         'sc_node','compliance_finding'))
);

CREATE INDEX idx_collab_owner    ON collab_shares (owner_tenant, granted_at DESC);
CREATE INDEX idx_collab_partner  ON collab_shares (partner_tenant, granted_at DESC);
CREATE INDEX idx_collab_artefact ON collab_shares (artefact_type, artefact_id);

COMMENT ON TABLE collab_shares IS
  'Multi-Tenant Collaboration use case: grant record giving partner_tenant access to an artefact owned by owner_tenant. Enforced via OLS on the target table.';

CREATE TABLE shared_artefacts (
    share_id  VARCHAR2(36) NOT NULL,
    payload   JSON         NOT NULL,
    ols_label NUMBER,
    CONSTRAINT pk_shared_artefacts       PRIMARY KEY (share_id),
    CONSTRAINT fk_shared_artefacts_share FOREIGN KEY (share_id)
                                         REFERENCES collab_shares (share_id)
                                         ON DELETE CASCADE
);

COMMENT ON TABLE shared_artefacts IS
  'Multi-Tenant Collaboration use case: denormalised JSON snapshot of the shared artefact at grant time (frozen, not live).';

--------------------------------------------------------------------------------
-- USE CASE 4: OSINT & Threat Fusion (Graph Analytics)
--------------------------------------------------------------------------------

CREATE TABLE osint_entities (
    entity_id       VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    tenant_id       VARCHAR2(36)                    NOT NULL,
    kind            VARCHAR2(40)                    NOT NULL,
    canonical_name  VARCHAR2(400)                   NOT NULL,
    attributes      JSON,
    ols_label       NUMBER,
    embedding       VECTOR(768, FLOAT32),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_osint_entities   PRIMARY KEY (entity_id),
    CONSTRAINT fk_osint_ent_tenant FOREIGN KEY (tenant_id)
                                   REFERENCES tenants (tenant_id),
    CONSTRAINT ck_osint_ent_kind   CHECK (kind IN
                                   ('person','organization','location',
                                    'vessel','aircraft','company','asset',
                                    'event','indicator','malware','actor'))
);

CREATE INDEX idx_osint_ent_tenant ON osint_entities (tenant_id, kind);
CREATE INDEX idx_osint_ent_name   ON osint_entities (canonical_name);

COMMENT ON TABLE osint_entities IS
  'OSINT & Threat Fusion use case: canonical entity vertex. Property graph intel_fusion built over this table in 05_property_graphs.sql.';

CREATE TABLE osint_relationships (
    rel_id      VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    src_id      VARCHAR2(36)                    NOT NULL,
    dst_id      VARCHAR2(36)                    NOT NULL,
    rel_type    VARCHAR2(60)                    NOT NULL,
    confidence  NUMBER(5,4),
    evidence    JSON,
    ols_label   NUMBER,
    observed_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_osint_rel          PRIMARY KEY (rel_id),
    CONSTRAINT fk_osint_rel_src      FOREIGN KEY (src_id)
                                     REFERENCES osint_entities (entity_id)
                                     ON DELETE CASCADE,
    CONSTRAINT fk_osint_rel_dst      FOREIGN KEY (dst_id)
                                     REFERENCES osint_entities (entity_id)
                                     ON DELETE CASCADE,
    CONSTRAINT ck_osint_rel_conf     CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_osint_rel_distinct CHECK (src_id <> dst_id)
);

CREATE INDEX idx_osint_rel_src  ON osint_relationships (src_id, rel_type);
CREATE INDEX idx_osint_rel_dst  ON osint_relationships (dst_id, rel_type);
CREATE INDEX idx_osint_rel_type ON osint_relationships (rel_type);

COMMENT ON TABLE osint_relationships IS
  'OSINT & Threat Fusion use case: directed edge (src -> dst) with relation type (e.g. owns, commands, located_in). Edge table for intel_fusion graph.';

--------------------------------------------------------------------------------
-- USE CASE 5: Supply Chain Knowledge Graph
--------------------------------------------------------------------------------

CREATE TABLE sc_nodes (
    node_id       VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    tenant_id     VARCHAR2(36)                    NOT NULL,
    node_type     VARCHAR2(40)                    NOT NULL,
    display_name  VARCHAR2(200)                   NOT NULL,
    country_iso3  CHAR(3)                         NOT NULL,
    location      SDO_GEOMETRY,
    criticality   NUMBER(3)                       DEFAULT 50,
    ols_label     NUMBER,
    CONSTRAINT pk_sc_nodes         PRIMARY KEY (node_id),
    CONSTRAINT fk_sc_nodes_tenant  FOREIGN KEY (tenant_id)
                                   REFERENCES tenants (tenant_id),
    CONSTRAINT ck_sc_nodes_type    CHECK (node_type IN
                                   ('supplier','hub','mine','port','factory')),
    CONSTRAINT ck_sc_nodes_crit    CHECK (criticality BETWEEN 0 AND 100)
);

CREATE INDEX idx_sc_nodes_tenant  ON sc_nodes (tenant_id, node_type);
CREATE INDEX idx_sc_nodes_country ON sc_nodes (country_iso3);

COMMENT ON TABLE sc_nodes IS
  'Supply Chain use case: supply-chain facility (supplier / hub / mine / port / factory). Spatial index on location in 06_spatial.sql.';

CREATE TABLE sc_edges (
    edge_id           VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    src_node          VARCHAR2(36)                    NOT NULL,
    dst_node          VARCHAR2(36)                    NOT NULL,
    edge_type         VARCHAR2(40)                    NOT NULL,
    lead_time_days    NUMBER(6),
    dependency_level  NUMBER(3),
    ols_label         NUMBER,
    CONSTRAINT pk_sc_edges         PRIMARY KEY (edge_id),
    CONSTRAINT fk_sc_edges_src     FOREIGN KEY (src_node)
                                   REFERENCES sc_nodes (node_id)
                                   ON DELETE CASCADE,
    CONSTRAINT fk_sc_edges_dst     FOREIGN KEY (dst_node)
                                   REFERENCES sc_nodes (node_id)
                                   ON DELETE CASCADE,
    CONSTRAINT ck_sc_edges_distinct CHECK (src_node <> dst_node),
    CONSTRAINT ck_sc_edges_dep     CHECK (dependency_level BETWEEN 0 AND 100),
    CONSTRAINT ck_sc_edges_type    CHECK (edge_type IN
                                   ('ships_to','supplies','transports',
                                    'depends_on','owned_by'))
);

CREATE INDEX idx_sc_edges_src  ON sc_edges (src_node, edge_type);
CREATE INDEX idx_sc_edges_dst  ON sc_edges (dst_node, edge_type);

COMMENT ON TABLE sc_edges IS
  'Supply Chain use case: directed dependency edge between two sc_nodes. Edge table for supply_chain property graph.';

CREATE TABLE sc_risk (
    node_id         VARCHAR2(36) NOT NULL,
    as_of           DATE         NOT NULL,
    risk_score      NUMBER(5,2)  NOT NULL,
    risk_breakdown  JSON,
    ols_label       NUMBER,
    CONSTRAINT pk_sc_risk          PRIMARY KEY (node_id, as_of),
    CONSTRAINT fk_sc_risk_node     FOREIGN KEY (node_id)
                                   REFERENCES sc_nodes (node_id)
                                   ON DELETE CASCADE,
    CONSTRAINT ck_sc_risk_score    CHECK (risk_score BETWEEN 0 AND 100)
);

CREATE INDEX idx_sc_risk_asof ON sc_risk (as_of DESC);

COMMENT ON TABLE sc_risk IS
  'Supply Chain use case: daily composite risk score per sc_node with JSON breakdown (geopolitical, sanctions, weather, cyber, ...).';

--------------------------------------------------------------------------------
-- USE CASE 6: Compliance Automation (NIS2 / DORA / GDPR / VS-NfD)
--------------------------------------------------------------------------------

CREATE TABLE compliance_controls (
    control_id  VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    framework   VARCHAR2(10)                    NOT NULL,
    code        VARCHAR2(40)                    NOT NULL,
    title       VARCHAR2(400)                   NOT NULL,
    description CLOB,
    tenant_id   VARCHAR2(36)                    NOT NULL,
    ols_label   NUMBER,
    CONSTRAINT pk_comp_controls        PRIMARY KEY (control_id),
    CONSTRAINT fk_comp_controls_tenant FOREIGN KEY (tenant_id)
                                       REFERENCES tenants (tenant_id),
    CONSTRAINT uq_comp_controls_code   UNIQUE (tenant_id, framework, code),
    CONSTRAINT ck_comp_controls_fw     CHECK (framework IN
                                       ('NIS2','DORA','GDPR','VSNFD'))
);

CREATE INDEX idx_comp_controls_fw ON compliance_controls (framework, code);

COMMENT ON TABLE compliance_controls IS
  'Compliance Automation use case: catalogue of control definitions per tenant and framework (NIS2 / DORA / GDPR / VSNFD).';

CREATE TABLE compliance_findings (
    finding_id    VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    control_id    VARCHAR2(36)                    NOT NULL,
    status        VARCHAR2(20)                    NOT NULL,
    detected_at   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    evidence_ref  VARCHAR2(400),
    ols_label     NUMBER,
    CONSTRAINT pk_comp_findings        PRIMARY KEY (finding_id),
    CONSTRAINT fk_comp_findings_ctrl   FOREIGN KEY (control_id)
                                       REFERENCES compliance_controls (control_id)
                                       ON DELETE CASCADE,
    CONSTRAINT ck_comp_findings_status CHECK (status IN
                                       ('open','mitigated','accepted',
                                        'false_positive','closed'))
);

CREATE INDEX idx_comp_findings_ctrl   ON compliance_findings (control_id, status);
CREATE INDEX idx_comp_findings_status ON compliance_findings (status, detected_at DESC);

COMMENT ON TABLE compliance_findings IS
  'Compliance Automation use case: open/closed findings per control.';

CREATE TABLE compliance_evidence (
    evidence_id  VARCHAR2(36) DEFAULT SYS_GUID() NOT NULL,
    finding_id   VARCHAR2(36)                    NOT NULL,
    blob_uri     VARCHAR2(2000)                  NOT NULL,
    sha256       CHAR(64)                        NOT NULL,
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    ols_label    NUMBER,
    CONSTRAINT pk_comp_evidence       PRIMARY KEY (evidence_id),
    CONSTRAINT fk_comp_evidence_find  FOREIGN KEY (finding_id)
                                      REFERENCES compliance_findings (finding_id)
                                      ON DELETE CASCADE
);

CREATE INDEX idx_comp_evidence_find ON compliance_evidence (finding_id);

COMMENT ON TABLE compliance_evidence IS
  'Compliance Automation use case: immutable evidence pointer (object storage URI + SHA-256) for a finding. Append-only.';

--==============================================================================
-- End of 02_core_tables.sql
--==============================================================================
