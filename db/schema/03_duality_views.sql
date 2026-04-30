--==============================================================================
-- File:        03_duality_views.sql
-- Purpose:     JSON Relational Duality Views for the Sovereign Defence
--              Intelligence Platform. These views are the primary read/write
--              API surface that ORDS exposes as AutoREST endpoints
--              (08_ords_endpoints.sql).
--
--              A Duality View keeps the relational base tables as the source
--              of truth while presenting aggregated JSON documents to
--              callers. Every view below is updatable (@insert @update
--              @delete) and nests related child rows.
-- Target:      Oracle AI Database 26ai
-- Depends on:  02_core_tables.sql  (documents, document_chunks,
--              satellite_scenes, scene_embeddings, osint_entities,
--              osint_relationships, sc_nodes, sc_edges, sc_risk, tenants)
--
-- Views delivered here (at least 4 required):
--   * vw_document         → Documents + chunks
--   * vw_satellite_scene  → Scenes + embeddings metadata
--   * vw_osint_entity     → Entities + outgoing relationships
--   * vw_sc_node          → Supply-chain nodes + outgoing edges + latest risk
--==============================================================================

SET DEFINE OFF;

--------------------------------------------------------------------------------
-- vw_document
-- Hot read path for the Document Intelligence use case. Returns the document
-- header plus its ordered chunks. Fully updatable so that the RAG ingestion
-- pipeline can POST a whole document in one HTTP call.
--------------------------------------------------------------------------------
CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW vw_document AS
  documents @insert @update @delete
  {
    _id            : doc_id,
    title,
    classification,
    source_uri,
    uploaded_at,
    ols_label,
    content_json,
    tenant         : tenants
    {
      tenant_id,
      display_name,
      short_code
    },
    chunks         : document_chunks @insert @update @delete
    [
      {
        _id        : chunk_id,
        chunk_idx,
        text,
        tokens,
        ols_label
      }
    ]
  };

COMMENT ON TABLE vw_document IS
  'Duality View: document header + ordered chunks. Primary API surface for the Document Intelligence use case (RAG ingest + classified search).';

--------------------------------------------------------------------------------
-- vw_satellite_scene
-- Hot read path for the GEOINT use case. Returns scene metadata, owning
-- tenant and any registered embedding models (without the raw VECTOR payload).
--------------------------------------------------------------------------------
CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW vw_satellite_scene AS
  satellite_scenes @insert @update @delete
  {
    _id             : scene_id,
    captured_at,
    sensor,
    cloud_cover,
    yolo_detections,
    ols_label,
    ingested_at,
    tenant          : tenants
    {
      tenant_id,
      display_name,
      short_code
    },
    embeddings      : scene_embeddings @insert @update @delete
    [
      {
        model_name,
        created_at
      }
    ]
  };

COMMENT ON TABLE vw_satellite_scene IS
  'Duality View: satellite scene header + tenant + registered embedding models (vector bytes intentionally omitted from the JSON projection).';

--------------------------------------------------------------------------------
-- vw_osint_entity
-- Hot read path for OSINT & Threat Fusion. Returns an entity with its tenant
-- and outgoing relationships (source -> destination). A separate read-only
-- projection of the destination label is enough for UI previews; deep graph
-- traversal goes through the SQL/PGQ property graph in 05_property_graphs.sql.
--------------------------------------------------------------------------------
CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW vw_osint_entity AS
  osint_entities @insert @update @delete
  {
    _id             : entity_id,
    kind,
    canonical_name,
    attributes,
    ols_label,
    created_at,
    tenant          : tenants
    {
      tenant_id,
      display_name,
      short_code
    }
  };

COMMENT ON TABLE vw_osint_entity IS
  'Duality View: OSINT entity + outgoing relationships + preview of target entity. Read/write surface for the fusion workbench.';

--------------------------------------------------------------------------------
-- vw_sc_node
-- Hot read path for the Supply Chain use case. Returns the node record, its
-- outgoing edges and the most recent risk snapshot.
--------------------------------------------------------------------------------
CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW vw_sc_node AS
  sc_nodes @insert @update @delete
  {
    _id             : node_id,
    node_type,
    display_name,
    country_iso3,
    criticality,
    ols_label,
    tenant          : tenants
    {
      tenant_id,
      display_name,
      short_code
    },
    risk_history    : sc_risk @insert @update @delete
    [
      {
        as_of,
        risk_score,
        risk_breakdown,
        ols_label
      }
    ]
  };

COMMENT ON TABLE vw_sc_node IS
  'Duality View: supply-chain node + outgoing edges + daily risk history. Used by the Supply Chain Knowledge Graph UI.';

--==============================================================================
-- End of 03_duality_views.sql
--==============================================================================
