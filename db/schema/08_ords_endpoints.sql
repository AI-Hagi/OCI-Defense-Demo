-- =============================================================================
-- Sovereign Defence Intelligence Platform — Oracle AI Database 26ai
-- File 08 of 8: ORDS REST Endpoints
--
-- Scope:
--   * Enable ORDS on SOVDEFENCE schema with OAuth2 (auto_rest_auth=TRUE)
--   * AutoREST on core domain tables
--   * Custom module intel.v1      (/api/intel/v1/*)
--   * Custom module compliance.v1 (/api/compliance/v1/*)
--   * OAuth2 roles + privilege-to-pattern mapping
--
-- Assumes prior files 01-07 have been run (tenants, documents, satellite_scenes,
-- osint_entities, sc_nodes, compliance_controls, audit_events, property graphs
-- intel_fusion and supply_chain, TxEventQ COMPLIANCE_Q, OLS policy DICE_POLICY).
-- =============================================================================

SET DEFINE OFF
SET SERVEROUTPUT ON

-- -----------------------------------------------------------------------------
-- 1. Enable ORDS for the SOVDEFENCE schema
-- -----------------------------------------------------------------------------
BEGIN
  BEGIN
    ORDS.ENABLE_SCHEMA(p_enabled => FALSE, p_schema => 'ADMIN');
  EXCEPTION WHEN OTHERS THEN NULL;
  END;
  ORDS.ENABLE_SCHEMA(
    p_enabled             => TRUE,
    p_schema              => 'ADMIN',
    p_url_mapping_type    => 'BASE_PATH',
    p_url_mapping_pattern => 'sovdefence',
    p_auto_rest_auth      => TRUE
  );
  COMMIT;
END;
/

-- -----------------------------------------------------------------------------
-- 2. AutoREST on core domain tables (OAuth required via p_auto_rest_auth)
--    Endpoints: /ords/sovdefence/<alias>/  (GET/POST/PUT/DELETE)
-- -----------------------------------------------------------------------------
BEGIN
  ORDS.ENABLE_OBJECT(
    p_enabled        => TRUE,
    p_schema         => 'ADMIN',
    p_object         => 'TENANTS',
    p_object_type    => 'TABLE',
    p_object_alias   => 'tenants',
    p_auto_rest_auth => TRUE);

  ORDS.ENABLE_OBJECT(
    p_enabled        => TRUE,
    p_schema         => 'ADMIN',
    p_object         => 'DOCUMENTS',
    p_object_type    => 'TABLE',
    p_object_alias   => 'documents',
    p_auto_rest_auth => TRUE);

  ORDS.ENABLE_OBJECT(
    p_enabled        => TRUE,
    p_schema         => 'ADMIN',
    p_object         => 'SATELLITE_SCENES',
    p_object_type    => 'TABLE',
    p_object_alias   => 'satellite-scenes',
    p_auto_rest_auth => TRUE);

  ORDS.ENABLE_OBJECT(
    p_enabled        => TRUE,
    p_schema         => 'ADMIN',
    p_object         => 'OSINT_ENTITIES',
    p_object_type    => 'TABLE',
    p_object_alias   => 'osint-entities',
    p_auto_rest_auth => TRUE);

  ORDS.ENABLE_OBJECT(
    p_enabled        => TRUE,
    p_schema         => 'ADMIN',
    p_object         => 'SC_NODES',
    p_object_type    => 'TABLE',
    p_object_alias   => 'sc-nodes',
    p_auto_rest_auth => TRUE);

  ORDS.ENABLE_OBJECT(
    p_enabled        => TRUE,
    p_schema         => 'ADMIN',
    p_object         => 'COMPLIANCE_CONTROLS',
    p_object_type    => 'TABLE',
    p_object_alias   => 'compliance-controls',
    p_auto_rest_auth => TRUE);

  COMMIT;
END;
/

-- -----------------------------------------------------------------------------
-- 3. Module intel.v1 at /api/intel/v1/
-- -----------------------------------------------------------------------------
BEGIN
  ORDS.DEFINE_MODULE(
    p_module_name    => 'intel.v1',
    p_base_path      => '/api/intel/v1/',
    p_items_per_page => 25,
    p_status         => 'PUBLISHED',
    p_comments       => 'Intel Fusion REST API — documents, OSINT graph, GEOINT AOI');
  COMMIT;
END;
/

-- 3.1 GET /documents/:id/similar?k=10  — vector similarity across chunks
BEGIN
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'intel.v1',
    p_pattern     => 'documents/:id/similar');

  ORDS.DEFINE_HANDLER(
    p_module_name    => 'intel.v1',
    p_pattern        => 'documents/:id/similar',
    p_method         => 'GET',
    p_source_type    => 'json/collection',
    p_items_per_page => 25,
    p_source         => q'[
      SELECT d.doc_id,
             d.title,
             VECTOR_DISTANCE(
               de.embedding,
               (SELECT embedding
                  FROM document_embeddings
                 WHERE chunk_id = (SELECT MIN(chunk_id)
                                     FROM document_chunks
                                    WHERE doc_id = :id)),
               COSINE) AS dist
        FROM document_embeddings de
        JOIN document_chunks    dc ON dc.chunk_id = de.chunk_id
        JOIN documents          d  ON d.doc_id    = dc.doc_id
       WHERE d.doc_id <> :id
       ORDER BY dist
       FETCH APPROX FIRST :k ROWS ONLY
    ]');

  ORDS.DEFINE_PARAMETER(
    p_module_name        => 'intel.v1',
    p_pattern            => 'documents/:id/similar',
    p_method             => 'GET',
    p_name               => 'k',
    p_bind_variable_name => 'k',
    p_source_type        => 'URI',
    p_param_type         => 'INT',
    p_access_method      => 'IN');

  COMMIT;
END;
/

-- 3.2 POST /osint/query-graph  — SQL/PGQ over intel_fusion graph
BEGIN
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'intel.v1',
    p_pattern     => 'osint/query-graph');

  -- Note: the quantifier {1,3} is a literal upper bound accepted by SQL/PGQ.
  -- :maxHops is accepted by the endpoint contract and enforced in the WHERE
  -- clause via PATH_LENGTH(p) so callers cannot request deeper than they asked.
  -- intel_fusion vertex label = entity, edge label = relates_to (see 05_).
  -- osint_entities key column = entity_id; human name = canonical_name; type = kind.
  ORDS.DEFINE_HANDLER(
    p_module_name    => 'intel.v1',
    p_pattern        => 'osint/query-graph',
    p_method         => 'POST',
    p_source_type    => 'json/collection',
    p_source         => q'[
      SELECT *
        FROM GRAPH_TABLE(intel_fusion
               MATCH p = (src IS entity) (-[r IS relates_to]-> (dst IS entity)){1,3}
               WHERE src.entity_id = :startEntity
                 AND PATH_LENGTH(p) <= :maxHops
               COLUMNS (
                 src.entity_id       AS src_id,
                 src.canonical_name  AS src_name,
                 src.kind            AS src_kind,
                 r.rel_type          AS rel_type,
                 r.confidence        AS confidence,
                 dst.entity_id       AS dst_id,
                 dst.canonical_name  AS dst_name,
                 dst.kind            AS dst_kind
               )) g
       FETCH FIRST 500 ROWS ONLY
    ]');

  COMMIT;
END;
/

-- 3.3 GET /geo/aoi?minX=&minY=&maxX=&maxY=  — spatial AOI query
BEGIN
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'intel.v1',
    p_pattern     => 'geo/aoi');

  ORDS.DEFINE_HANDLER(
    p_module_name    => 'intel.v1',
    p_pattern        => 'geo/aoi',
    p_method         => 'GET',
    p_source_type    => 'json/collection',
    p_items_per_page => 50,
    p_source         => q'[
      SELECT scene_id,
             captured_at
        FROM satellite_scenes
       WHERE SDO_FILTER(
               footprint,
               SDO_GEOMETRY(2003, 4326, NULL,
                 SDO_ELEM_INFO_ARRAY(1, 1003, 3),
                 SDO_ORDINATE_ARRAY(:minX, :minY, :maxX, :maxY))
             ) = 'TRUE'
       ORDER BY captured_at DESC
    ]');

  ORDS.DEFINE_PARAMETER(
    p_module_name        => 'intel.v1',
    p_pattern            => 'geo/aoi',
    p_method             => 'GET',
    p_name               => 'minX',
    p_bind_variable_name => 'minX',
    p_source_type        => 'URI',
    p_param_type         => 'DOUBLE',
    p_access_method      => 'IN');

  ORDS.DEFINE_PARAMETER(
    p_module_name        => 'intel.v1',
    p_pattern            => 'geo/aoi',
    p_method             => 'GET',
    p_name               => 'minY',
    p_bind_variable_name => 'minY',
    p_source_type        => 'URI',
    p_param_type         => 'DOUBLE',
    p_access_method      => 'IN');

  ORDS.DEFINE_PARAMETER(
    p_module_name        => 'intel.v1',
    p_pattern            => 'geo/aoi',
    p_method             => 'GET',
    p_name               => 'maxX',
    p_bind_variable_name => 'maxX',
    p_source_type        => 'URI',
    p_param_type         => 'DOUBLE',
    p_access_method      => 'IN');

  ORDS.DEFINE_PARAMETER(
    p_module_name        => 'intel.v1',
    p_pattern            => 'geo/aoi',
    p_method             => 'GET',
    p_name               => 'maxY',
    p_bind_variable_name => 'maxY',
    p_source_type        => 'URI',
    p_param_type         => 'DOUBLE',
    p_access_method      => 'IN');

  COMMIT;
END;
/

-- -----------------------------------------------------------------------------
-- 4. Module compliance.v1 at /api/compliance/v1/
-- -----------------------------------------------------------------------------
BEGIN
  ORDS.DEFINE_MODULE(
    p_module_name    => 'compliance.v1',
    p_base_path      => '/api/compliance/v1/',
    p_items_per_page => 50,
    p_status         => 'PUBLISHED',
    p_comments       => 'Compliance REST API — NIS2/DORA/GDPR/VSNFD controls, audit, incidents');
  COMMIT;
END;
/

-- 4.1 GET /controls/:framework  — list controls for a given framework
BEGIN
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'compliance.v1',
    p_pattern     => 'controls/:framework');

  ORDS.DEFINE_HANDLER(
    p_module_name    => 'compliance.v1',
    p_pattern        => 'controls/:framework',
    p_method         => 'GET',
    p_source_type    => 'json/collection',
    p_items_per_page => 50,
    -- compliance_controls columns per 02_core_tables.sql:
    --   control_id, framework, code, title, description, tenant_id, ols_label
    -- Tenant scoping via SYS_CONTEXT CLIENT_IDENTIFIER (set by ORDS OAuth).
    p_source         => q'[
      SELECT control_id,
             framework,
             code,
             title,
             description,
             tenant_id
        FROM compliance_controls
       WHERE framework = UPPER(:framework)
         AND tenant_id = SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER')
       ORDER BY code
    ]');

  COMMIT;
END;
/

-- 4.2 POST /audit/query  — server-side filter on audit_events, tenant-scoped via CLIENT_IDENTIFIER
BEGIN
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'compliance.v1',
    p_pattern     => 'audit/query');

  ORDS.DEFINE_HANDLER(
    p_module_name    => 'compliance.v1',
    p_pattern        => 'audit/query',
    p_method         => 'POST',
    p_source_type    => 'json/collection',
    p_items_per_page => 100,
    -- audit_events columns per 07_audit_compliance.sql:
    --   event_id RAW(16), event_time, actor_user, actor_service, action,
    --   resource_type, resource_id, tenant_id, ols_label, payload,
    --   prev_hash, row_hash  (hash-chain column is row_hash, not event_hash)
    p_source         => q'[
      SELECT RAWTOHEX(event_id)       AS event_id,
             event_time,
             actor_user,
             actor_service,
             action,
             resource_type,
             resource_id,
             tenant_id,
             RAWTOHEX(prev_hash)      AS prev_hash,
             RAWTOHEX(row_hash)       AS row_hash
        FROM audit_events
       WHERE event_time BETWEEN TO_TIMESTAMP(:p_from, 'YYYY-MM-DD"T"HH24:MI:SS.FF')
                            AND TO_TIMESTAMP(:p_to,   'YYYY-MM-DD"T"HH24:MI:SS.FF')
         AND (:p_actor  IS NULL OR actor_user = :p_actor)
         AND (:p_action IS NULL OR action     = :p_action)
         AND tenant_id = SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER')
       ORDER BY event_time DESC
    ]');

  COMMIT;
END;
/

-- 4.3 GET /dora/incidents/open  — caller-tenant scoped open DORA incidents
BEGIN
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'compliance.v1',
    p_pattern     => 'dora/incidents/open');

  ORDS.DEFINE_HANDLER(
    p_module_name    => 'compliance.v1',
    p_pattern        => 'dora/incidents/open',
    p_method         => 'GET',
    p_source_type    => 'json/collection',
    p_items_per_page => 50,
    -- dora_incidents columns per 07_audit_compliance.sql:
    --   incident_id, tenant_id, severity, reported_at, root_cause,
    --   affected_service, rto_minutes, rpo_minutes, ols_label
    -- "Open" is defined as no recovery objective met yet, i.e. rto_minutes IS NULL.
    p_source         => q'[
      SELECT incident_id,
             reported_at,
             severity,
             root_cause,
             affected_service,
             rto_minutes,
             rpo_minutes,
             tenant_id
        FROM dora_incidents
       WHERE rto_minutes IS NULL
         AND tenant_id = SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER')
       ORDER BY reported_at DESC
    ]');

  COMMIT;
END;
/

-- -----------------------------------------------------------------------------
-- 5. OAuth2 roles + privilege-to-pattern mappings
-- -----------------------------------------------------------------------------
DECLARE
  v_intel_roles    owa.vc_arr;
  v_intel_patterns owa.vc_arr;
  v_comp_roles     owa.vc_arr;
  v_comp_patterns  owa.vc_arr;
BEGIN
  BEGIN ORDS.CREATE_ROLE(p_role_name => 'intel_user');      EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-20015, -1) THEN RAISE; END IF; END;
  BEGIN ORDS.CREATE_ROLE(p_role_name => 'compliance_user'); EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-20015, -1) THEN RAISE; END IF; END;
  BEGIN ORDS.CREATE_ROLE(p_role_name => 'sov_admin');       EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-20015, -1) THEN RAISE; END IF; END;

  v_intel_roles(1)    := 'intel_user';
  v_intel_roles(2)    := 'sov_admin';
  v_intel_patterns(1) := '/api/intel/v1/*';

  v_comp_roles(1)     := 'compliance_user';
  v_comp_roles(2)     := 'sov_admin';
  v_comp_patterns(1)  := '/api/compliance/v1/*';

  ORDS.DEFINE_PRIVILEGE(
    p_privilege_name => 'priv.intel',
    p_roles          => v_intel_roles,
    p_patterns       => v_intel_patterns,
    p_label          => 'Intel API',
    p_description    => 'Access to intel fusion endpoints');

  ORDS.DEFINE_PRIVILEGE(
    p_privilege_name => 'priv.compliance',
    p_roles          => v_comp_roles,
    p_patterns       => v_comp_patterns,
    p_label          => 'Compliance API',
    p_description    => 'Access to compliance endpoints');

  COMMIT;
END;
/

-- -----------------------------------------------------------------------------
-- 6. OAuth2 client registration (EXAMPLE — replace secrets before running)
-- -----------------------------------------------------------------------------
-- Uncomment AND replace the client_secret below with a secret issued by your IdP
-- (or a generated high-entropy secret from `openssl rand -hex 32`). Never commit
-- real secrets to git — use OCI Vault + DevOps Secrets injection at deploy time.
--
-- BEGIN
--   OAUTH.CREATE_CLIENT(
--     p_name            => 'sovdefence-intel-client',
--     p_grant_type      => 'client_credentials',
--     p_owner           => 'Sovereign Defence Platform',
--     p_description     => 'Service account for Intel + Compliance API access',
--     p_support_email   => 'ops@sovdefence.example.eu',
--     p_privilege_names => 'priv.intel,priv.compliance'
--   );
--
--   OAUTH.GRANT_CLIENT_ROLE(
--     p_client_name => 'sovdefence-intel-client',
--     p_role_name   => 'sov_admin');
--
--   -- Retrieve client_id / client_secret via:
--   --   SELECT name, client_id, client_secret
--   --     FROM user_ords_clients
--   --    WHERE name = 'sovdefence-intel-client';
--
--   COMMIT;
-- END;
-- /

-- -----------------------------------------------------------------------------
-- End of 08_ords_endpoints.sql
-- -----------------------------------------------------------------------------
