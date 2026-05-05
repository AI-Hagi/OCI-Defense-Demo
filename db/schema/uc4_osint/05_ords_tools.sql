-- ===========================================================================
-- UC4_OSINT — Tag 6: ORDS Tools für den Threat-Fusion-Agent (Tag 7)
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1) + embedded ORDS
--
-- Vier POST-Tools unter /ords/uc4_osint/api/v1/tools/:
--   * graph_query           SQL/PGQ-Patterns über osint_graph
--   * spatial_aggregate     H3-Bucket-Heatmap aus signal_normalized
--   * persist_briefing      Agent-Briefings mit OLS-Klassifikations-Cap-Check
--   * vector_hybrid_search  Skeleton — heute 503, sobald Embeddings da → live
--
-- Architektur-Pattern:
--   * Pro Tool eine eigene Stored Procedure UC4_OSINT.TOOL_*. Die enthält
--     die ganze Tool-Logik: OLS-Pre-Handler-Aufruf, Audit-Insert, eigentliche
--     Arbeit, Response-Build, RFC-7807-Exception-Handler.
--   * Der ORDS-Handler ist ein One-Liner-Wrapper:
--         BEGIN UC4_OSINT.TOOL_GRAPH_QUERY(:body_text); END;
--   * Vorteile:
--       - Code testbar ohne ORDS (Direct-PL/SQL-Call mit p_body)
--       - 32k-Limit der ORDS-Handler-Source umgangen
--       - Cleaner separation of concerns (ORDS = Routing, Schema = Logik)
--
-- App-Layer-OLS-Filterung:
--   * UC4_OSINT.OLS_PRE_HANDLER liest X-OLS-Label-Max, normalisiert
--     ('OFFEN'/'INTERN'/'NFD'/'GEHEIM' oder '10'/'30'/'50'/'70'),
--     ruft UC4_OSINT.OLS_CTX_PKG.SET_LABEL_CAP. Fehlende Header → OFFEN(10).
--   * Tool-Body filtert Reads zusätzlich mit
--     "AND ols_label <= UC4_OSINT.LABEL_CAP()" und Writes (persist_briefing)
--     verifiziert "briefing.ols_label <= UC4_OSINT.LABEL_CAP()".
--
-- Audit-Strategie:
--   * Audit-Insert PASSIERT VOR der Arbeit, sodass auch Failure-/Timeout-
--     Calls eine Spur hinterlassen. invocation_id ist SYS_GUID() —
--     wird im Response zurückgegeben (request_id), damit Frontend / Agent
--     den Trace finden kann.
--   * Action-Codes: 'INVOKE' für jeden Tool-Call,
--     zusätzlich 'PERSIST_BRIEFING' nach erfolgreichem Briefing-Insert.
--
-- Voraussetzungen:
--   * 01_tables.sql .. 04_graph.sql + 03b_ols_app_filter.sql appliziert.
--   * ADMIN-Connection (CREATE PROCEDURE auf UC4_OSINT, ORDS-Admin-Calls).
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

-- ---------------------------------------------------------------------------
-- (0.1) ORDS-enable Schema UC4_OSINT, idempotent
--
-- Wir laufen den Skript als UC4_OSINT (Schema-Owner enabled sich selbst).
-- ORDS.ENABLE_SCHEMA ist idempotent — zweiter Aufruf mit gleichen Params
-- ist No-Op. Falls ORA-20999 (oder ähnliches "already enabled") kommt:
-- swallow.
-- ---------------------------------------------------------------------------
BEGIN
  ORDS.ENABLE_SCHEMA(
    p_enabled             => TRUE,
    p_schema              => 'UC4_OSINT',
    p_url_mapping_type    => 'BASE_PATH',
    p_url_mapping_pattern => 'uc4_osint',
    p_auto_rest_auth      => FALSE);
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('UC4_OSINT ORDS-enabled (BASE_PATH=uc4_osint).');
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE IN (-20999, -20000) THEN
    DBMS_OUTPUT.PUT_LINE('UC4_OSINT already ORDS-enabled — skipping.');
  ELSE
    RAISE;
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (0.2) audit_trail.actor_type CHECK um 'TOOL' erweitern
--       (01_tables.sql ließ nur USER/AGENT/SYSTEM/SCHEDULER zu)
-- ---------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE audit_trail DROP CONSTRAINT ck_audit_actor';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE NOT IN (-2443) THEN  -- ORA-02443 = constraint not found
    RAISE;
  END IF;
END;
/
ALTER TABLE audit_trail ADD CONSTRAINT ck_audit_actor
  CHECK (actor_type IN ('USER','AGENT','SYSTEM','SCHEDULER','TOOL'));

-- ---------------------------------------------------------------------------
-- (1) UC4_OSINT.OLS_PRE_HANDLER
--     Reads X-OLS-Label-Max from CGI-env, normalises to numeric, sets cap.
--     Fail-safe: missing/garbage header → OFFEN(10).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE UC4_OSINT.OLS_PRE_HANDLER(p_label_max IN VARCHAR2 DEFAULT NULL) AS
  v_raw  VARCHAR2(40);
  v_cap  NUMBER;
BEGIN
  -- The X-OLS-Label-Max header is wired through as a bind parameter
  -- via ORDS.DEFINE_PARAMETER (see Section 7 below). The ORDS handler
  -- one-liner forwards :header_x_ols_label_max as the second positional
  -- argument. Custom headers are NOT surfaced via OWA_UTIL.GET_CGI_ENV
  -- without explicit parameter binding in ORDS.
  v_raw := p_label_max;
  IF v_raw IS NULL OR v_raw = '' THEN
    v_cap := 10;
  ELSE
    v_raw := UPPER(TRIM(v_raw));
    -- Symbolic forms
    IF v_raw = 'OFFEN'   THEN v_cap := 10;
    ELSIF v_raw = 'INTERN' THEN v_cap := 30;
    ELSIF v_raw = 'NFD'    THEN v_cap := 50;
    ELSIF v_raw = 'GEHEIM' THEN v_cap := 70;  -- clamps to 50 in SET_LABEL_CAP
    ELSE
      -- Numeric fallback
      BEGIN
        v_cap := TO_NUMBER(v_raw);
      EXCEPTION WHEN OTHERS THEN v_cap := 10; END;
    END IF;
  END IF;
  UC4_OSINT.OLS_CTX_PKG.SET_LABEL_CAP(v_cap);
END;
/

GRANT EXECUTE ON UC4_OSINT.OLS_PRE_HANDLER TO PUBLIC;

-- ---------------------------------------------------------------------------
-- (2) Common helpers: audit_invoke, write_problem
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE UC4_OSINT.AUDIT_TOOL_INVOKE(
  p_tool_name      IN  VARCHAR2,
  p_payload_hash   IN  VARCHAR2,
  p_invocation_id  IN  VARCHAR2,
  p_action         IN  VARCHAR2 DEFAULT 'INVOKE',
  p_table_name     IN  VARCHAR2 DEFAULT 'TOOLS',
  p_row_id         IN  RAW      DEFAULT NULL
) AS
  PRAGMA AUTONOMOUS_TRANSACTION;
BEGIN
  -- AUTONOMOUS so audit row commits even if outer tool-call rolls back later.
  -- The append-only / no-update / no-delete invariant is enforced by the
  -- privilege model from 03_security.sql.
  INSERT INTO audit_trail (
    actor_type, actor_id, action, table_name, row_id,
    ols_label, payload_hash, invocation_id
  ) VALUES (
    'TOOL', 'ords:'||p_tool_name, p_action, p_table_name, p_row_id,
    UC4_OSINT.LABEL_CAP(), p_payload_hash, p_invocation_id
  );
  COMMIT;
END;
/

CREATE OR REPLACE PROCEDURE UC4_OSINT.WRITE_PROBLEM(
  p_status     IN NUMBER,
  p_type_slug  IN VARCHAR2,
  p_title      IN VARCHAR2,
  p_detail     IN VARCHAR2,
  p_instance   IN VARCHAR2
) AS
BEGIN
  OWA_UTIL.STATUS_LINE(p_status, NULL, FALSE);
  OWA_UTIL.MIME_HEADER('application/problem+json', FALSE);
  OWA_UTIL.HTTP_HEADER_CLOSE;
  HTP.PRN(JSON_OBJECT(
    'type'     VALUE 'https://uc4.cloudebility.com/errors/'||p_type_slug,
    'title'    VALUE p_title,
    'status'   VALUE p_status,
    'detail'   VALUE p_detail,
    'instance' VALUE p_instance
  ));
END;
/

GRANT EXECUTE ON UC4_OSINT.AUDIT_TOOL_INVOKE TO PUBLIC;
GRANT EXECUTE ON UC4_OSINT.WRITE_PROBLEM     TO PUBLIC;

-- ---------------------------------------------------------------------------
-- (3) TOOL_GRAPH_QUERY
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE UC4_OSINT.TOOL_GRAPH_QUERY(p_body IN CLOB, p_label_max IN VARCHAR2 DEFAULT NULL) AS
  c_tool_name  CONSTANT VARCHAR2(40) := 'graph_query';
  v_invocation VARCHAR2(64) := RAWTOHEX(SYS_GUID());
  v_started    TIMESTAMP WITH TIME ZONE := SYSTIMESTAMP;
  v_payload_h  VARCHAR2(64);
  v_pattern    VARCHAR2(40);
  v_data       CLOB;
  v_dur_ms     NUMBER;
  v_cap        NUMBER;

  -- args
  v_hours          NUMBER;
  v_min_corr       NUMBER;
  v_h3_cell        VARCHAR2(40);
BEGIN
  UC4_OSINT.OLS_PRE_HANDLER(p_label_max);
  v_cap := UC4_OSINT.LABEL_CAP();

  v_payload_h := RAWTOHEX(SYS_GUID())||RAWTOHEX(SYS_GUID()); -- 64-hex unique trace, not a crypto hash
  UC4_OSINT.AUDIT_TOOL_INVOKE(c_tool_name, v_payload_h, v_invocation);

  v_pattern := JSON_VALUE(p_body, '$.pattern' RETURNING VARCHAR2(40));
  IF v_pattern IS NULL THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Missing pattern',
      'Request body must include "pattern": "multi_source_entity" | "convergence".',
      v_invocation);
    RETURN;
  END IF;

  IF v_pattern = 'multi_source_entity' THEN
    v_hours    := NVL(JSON_VALUE(p_body, '$.args.hours'             RETURNING NUMBER), 72);
    v_min_corr := NVL(JSON_VALUE(p_body, '$.args.min_correlations'  RETURNING NUMBER), 2);

    -- Dynamic SQL: GRAPH_TABLE doesn't accept PL/SQL bind variables in
    -- its MATCH/WHERE clauses (ORA-49028). Sanitise inputs to integers
    -- and inline them; UC4_OSINT.LABEL_CAP() is a stand-alone function
    -- so it stays inline-callable without any extra plumbing.
    v_hours    := TRUNC(GREATEST(LEAST(NVL(v_hours,    72), 720), 1));   -- 1..720h
    v_min_corr := TRUNC(GREATEST(LEAST(NVL(v_min_corr, 2),  20), 1));    -- 1..20
    EXECUTE IMMEDIATE
      'SELECT JSON_OBJECT('
      ||'  ''entities'' VALUE JSON_ARRAYAGG('
      ||'    JSON_OBJECT('
      ||'      ''entity_id''       VALUE RAWTOHEX(entity_id),'
      ||'      ''entity_kind''     VALUE entity_kind,'
      ||'      ''display_name''    VALUE display_name,'
      ||'      ''canonical_id''    VALUE canonical_id,'
      ||'      ''corr_count''      VALUE corr_count,'
      ||'      ''correlation_ids'' VALUE correlation_ids FORMAT JSON'
      ||'    ) ORDER BY corr_count DESC'
      ||'  ) RETURNING CLOB'
      ||')'
      ||' FROM ('
      ||'   SELECT e_id            AS entity_id,'
      ||'          MAX(e_kind)     AS entity_kind,'
      ||'          MAX(e_display)  AS display_name,'
      ||'          MAX(e_canon)    AS canonical_id,'
      ||'          COUNT(DISTINCT c_id) AS corr_count,'
      ||'          JSON_ARRAYAGG(RAWTOHEX(c_id)) AS correlation_ids'
      ||'     FROM GRAPH_TABLE (UC4_OSINT.osint_graph'
      ||'       MATCH (c IS correlation) -[r IS correlation_concerns]-> (e IS entity)'
      ||'       WHERE c.detected_at > SYSTIMESTAMP - NUMTODSINTERVAL('||TO_CHAR(v_hours)||', ''HOUR'')'
      ||'         AND c.ols_label <= UC4_OSINT.LABEL_CAP()'
      ||'         AND e.ols_label <= UC4_OSINT.LABEL_CAP()'
      ||'       COLUMNS ('
      ||'         e.entity_id    AS e_id,'
      ||'         e.entity_kind  AS e_kind,'
      ||'         e.display_name AS e_display,'
      ||'         e.canonical_id AS e_canon,'
      ||'         c.correlation_id AS c_id'
      ||'       )'
      ||'     ) gt'
      ||'    GROUP BY e_id'
      ||'   HAVING COUNT(DISTINCT c_id) >= '||TO_CHAR(v_min_corr)
      ||'    FETCH FIRST 50 ROWS ONLY'
      ||')'
      INTO v_data;

  ELSIF v_pattern = 'convergence' THEN
    v_hours   := NVL(JSON_VALUE(p_body, '$.args.hours'    RETURNING NUMBER), 72);
    v_h3_cell := JSON_VALUE(p_body, '$.args.h3_cell' RETURNING VARCHAR2(40));

    IF v_h3_cell IS NULL THEN
      UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
        'Missing args.h3_cell',
        'pattern=convergence requires args.h3_cell (string).',
        v_invocation);
      RETURN;
    END IF;

    SELECT JSON_OBJECT(
             'h3_cell'      VALUE v_h3_cell,
             'hours'        VALUE v_hours,
             'correlations' VALUE JSON_ARRAYAGG(
               JSON_OBJECT(
                 'correlation_id'   VALUE RAWTOHEX(correlation_id),
                 'correlation_kind' VALUE correlation_kind,
                 'summary'          VALUE summary,
                 'detected_at'      VALUE TO_CHAR(detected_at, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
                 'score'            VALUE score,
                 'event_count'      VALUE event_count,
                 'event_ids'        VALUE event_ids FORMAT JSON
               ) ORDER BY detected_at DESC
             ) RETURNING CLOB
           )
      INTO v_data
      FROM (
        SELECT ce.correlation_id, ce.correlation_kind, ce.summary,
               ce.detected_at, ce.score,
               COUNT(cie.event_id) AS event_count,
               JSON_ARRAYAGG(RAWTOHEX(cie.event_id)) AS event_ids
          FROM correlation_event ce
          LEFT JOIN correlation_includes_event cie
                 ON cie.correlation_id = ce.correlation_id
                AND EXISTS (SELECT 1 FROM signal_normalized sn
                             WHERE sn.event_id = cie.event_id
                               AND sn.ols_label <= UC4_OSINT.LABEL_CAP())
         WHERE ce.geo_h3_r5 = v_h3_cell
           AND ce.detected_at > SYSTIMESTAMP - NUMTODSINTERVAL(v_hours, 'HOUR')
           AND ce.ols_label <= UC4_OSINT.LABEL_CAP()
         GROUP BY ce.correlation_id, ce.correlation_kind, ce.summary,
                  ce.detected_at, ce.score
         ORDER BY ce.detected_at DESC
         FETCH FIRST 50 ROWS ONLY
      );

  ELSE
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Unknown pattern',
      'pattern must be "multi_source_entity" or "convergence". Got: '||v_pattern,
      v_invocation);
    RETURN;
  END IF;

  v_dur_ms := EXTRACT(SECOND FROM (SYSTIMESTAMP - v_started)) * 1000;

  OWA_UTIL.MIME_HEADER('application/json', FALSE);
  OWA_UTIL.HTTP_HEADER_CLOSE;
  HTP.PRN(JSON_OBJECT(
    'request_id'      VALUE v_invocation,
    'duration_ms'     VALUE ROUND(v_dur_ms, 1),
    'data'            VALUE NVL(v_data, TO_CLOB('{"entities":[]}')) FORMAT JSON,
    'ols_cap_applied' VALUE v_cap,
    'ols_cap_label'   VALUE CASE v_cap WHEN 10 THEN 'OFFEN' WHEN 30 THEN 'INTERN'
                                       WHEN 50 THEN 'NFD'   WHEN 70 THEN 'GEHEIM' END));
EXCEPTION WHEN OTHERS THEN
  UC4_OSINT.WRITE_PROBLEM(500, 'internal',
    'Internal Server Error',
    SUBSTR(SQLERRM, 1, 1024),
    v_invocation);
END;
/
GRANT EXECUTE ON UC4_OSINT.TOOL_GRAPH_QUERY TO PUBLIC;

-- ---------------------------------------------------------------------------
-- (4) TOOL_SPATIAL_AGGREGATE
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE UC4_OSINT.TOOL_SPATIAL_AGGREGATE(p_body IN CLOB, p_label_max IN VARCHAR2 DEFAULT NULL) AS
  c_tool_name  CONSTANT VARCHAR2(40) := 'spatial_aggregate';
  v_invocation VARCHAR2(64) := RAWTOHEX(SYS_GUID());
  v_started    TIMESTAMP WITH TIME ZONE := SYSTIMESTAMP;
  v_payload_h  VARCHAR2(64);
  v_data       CLOB;
  v_dur_ms     NUMBER;
  v_cap        NUMBER;

  v_h3_res     NUMBER;
  v_hours      NUMBER;
  v_min_events NUMBER;
  v_min_lat    NUMBER;
  v_max_lat    NUMBER;
  v_min_lon    NUMBER;
  v_max_lon    NUMBER;
  v_have_bbox  BOOLEAN;
BEGIN
  UC4_OSINT.OLS_PRE_HANDLER(p_label_max);
  v_cap := UC4_OSINT.LABEL_CAP();
  v_payload_h := RAWTOHEX(SYS_GUID())||RAWTOHEX(SYS_GUID()); -- 64-hex unique trace, not a crypto hash
  UC4_OSINT.AUDIT_TOOL_INVOKE(c_tool_name, v_payload_h, v_invocation);

  v_h3_res     := NVL(JSON_VALUE(p_body, '$.h3_resolution' RETURNING NUMBER), 5);
  v_hours      := NVL(JSON_VALUE(p_body, '$.hours'         RETURNING NUMBER), 72);
  v_min_events := NVL(JSON_VALUE(p_body, '$.min_events'    RETURNING NUMBER), 3);

  IF v_h3_res != 5 THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Unsupported h3_resolution',
      'Only h3_resolution=5 is currently supported. resolutions 6/7 TODO.',
      v_invocation);
    RETURN;
  END IF;

  v_min_lat := JSON_VALUE(p_body, '$.bbox.min_lat' RETURNING NUMBER);
  v_max_lat := JSON_VALUE(p_body, '$.bbox.max_lat' RETURNING NUMBER);
  v_min_lon := JSON_VALUE(p_body, '$.bbox.min_lon' RETURNING NUMBER);
  v_max_lon := JSON_VALUE(p_body, '$.bbox.max_lon' RETURNING NUMBER);
  v_have_bbox := (v_min_lat IS NOT NULL AND v_max_lat IS NOT NULL
                  AND v_min_lon IS NOT NULL AND v_max_lon IS NOT NULL);

  -- Build a GeoJSON FeatureCollection. SDO_AGGR_UNION+SDO_CENTROID
  -- collapses each H3-bucket's set of points to a representative
  -- centroid; the count + variety counts come from straight aggregation.
  -- Bbox filter via SDO_FILTER on the spatial index — fast path.
  IF v_have_bbox THEN
    SELECT JSON_OBJECT(
             'type'     VALUE 'FeatureCollection',
             'features' VALUE JSON_ARRAYAGG(
               JSON_OBJECT(
                 'type'       VALUE 'Feature',
                 'geometry'   VALUE JSON_OBJECT(
                   'type'        VALUE 'Point',
                   'coordinates' VALUE JSON_ARRAY(centroid_lon, centroid_lat)
                 ) FORMAT JSON,
                 'properties' VALUE JSON_OBJECT(
                   'h3_cell'        VALUE h3_cell,
                   'event_count'    VALUE event_count,
                   'variety'        VALUE variety,
                   'centroid_lat'   VALUE centroid_lat,
                   'centroid_lon'   VALUE centroid_lon
                 ) FORMAT JSON
               ) ORDER BY event_count DESC
             ) RETURNING CLOB
           )
      INTO v_data
      FROM (
        SELECT geo_h3_r5 AS h3_cell,
               COUNT(*)                   AS event_count,
               COUNT(DISTINCT source_type) AS variety,
               AVG(sn.geo.SDO_POINT.X)    AS centroid_lon,
               AVG(sn.geo.SDO_POINT.Y)    AS centroid_lat
          FROM signal_normalized sn
         WHERE sn.observed_at > SYSTIMESTAMP - NUMTODSINTERVAL(v_hours, 'HOUR')
           AND sn.ols_label <= UC4_OSINT.LABEL_CAP()
           AND sn.geo_h3_r5 IS NOT NULL
           AND SDO_FILTER(sn.geo,
                 SDO_GEOMETRY(2003, 4326, NULL,
                   SDO_ELEM_INFO_ARRAY(1, 1003, 3),
                   SDO_ORDINATE_ARRAY(v_min_lon, v_min_lat, v_max_lon, v_max_lat))
               ) = 'TRUE'
         GROUP BY geo_h3_r5
        HAVING COUNT(*) >= v_min_events
         ORDER BY event_count DESC
         FETCH FIRST 200 ROWS ONLY
      );
  ELSE
    SELECT JSON_OBJECT(
             'type'     VALUE 'FeatureCollection',
             'features' VALUE JSON_ARRAYAGG(
               JSON_OBJECT(
                 'type'       VALUE 'Feature',
                 'geometry'   VALUE JSON_OBJECT(
                   'type'        VALUE 'Point',
                   'coordinates' VALUE JSON_ARRAY(centroid_lon, centroid_lat)
                 ) FORMAT JSON,
                 'properties' VALUE JSON_OBJECT(
                   'h3_cell'      VALUE h3_cell,
                   'event_count'  VALUE event_count,
                   'variety'      VALUE variety,
                   'centroid_lat' VALUE centroid_lat,
                   'centroid_lon' VALUE centroid_lon
                 ) FORMAT JSON
               ) ORDER BY event_count DESC
             ) RETURNING CLOB
           )
      INTO v_data
      FROM (
        SELECT geo_h3_r5 AS h3_cell,
               COUNT(*)                   AS event_count,
               COUNT(DISTINCT source_type) AS variety,
               AVG(sn.geo.SDO_POINT.X)    AS centroid_lon,
               AVG(sn.geo.SDO_POINT.Y)    AS centroid_lat
          FROM signal_normalized sn
         WHERE sn.observed_at > SYSTIMESTAMP - NUMTODSINTERVAL(v_hours, 'HOUR')
           AND sn.ols_label <= UC4_OSINT.LABEL_CAP()
           AND sn.geo_h3_r5 IS NOT NULL
         GROUP BY geo_h3_r5
        HAVING COUNT(*) >= v_min_events
         ORDER BY event_count DESC
         FETCH FIRST 200 ROWS ONLY
      );
  END IF;

  v_dur_ms := EXTRACT(SECOND FROM (SYSTIMESTAMP - v_started)) * 1000;

  OWA_UTIL.MIME_HEADER('application/json', FALSE);
  OWA_UTIL.HTTP_HEADER_CLOSE;
  HTP.PRN(JSON_OBJECT(
    'request_id'      VALUE v_invocation,
    'duration_ms'     VALUE ROUND(v_dur_ms, 1),
    'data'            VALUE NVL(v_data, TO_CLOB('{"type":"FeatureCollection","features":[]}')) FORMAT JSON,
    'ols_cap_applied' VALUE v_cap,
    'ols_cap_label'   VALUE CASE v_cap WHEN 10 THEN 'OFFEN' WHEN 30 THEN 'INTERN'
                                       WHEN 50 THEN 'NFD'   WHEN 70 THEN 'GEHEIM' END));
EXCEPTION WHEN OTHERS THEN
  UC4_OSINT.WRITE_PROBLEM(500, 'internal',
    'Internal Server Error',
    SUBSTR(SQLERRM, 1, 1024),
    v_invocation);
END;
/
GRANT EXECUTE ON UC4_OSINT.TOOL_SPATIAL_AGGREGATE TO PUBLIC;

-- ---------------------------------------------------------------------------
-- (5) TOOL_PERSIST_BRIEFING
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE UC4_OSINT.TOOL_PERSIST_BRIEFING(p_body IN CLOB, p_label_max IN VARCHAR2 DEFAULT NULL) AS
  c_tool_name  CONSTANT VARCHAR2(40) := 'persist_briefing';
  v_invocation VARCHAR2(64) := RAWTOHEX(SYS_GUID());
  v_started    TIMESTAMP WITH TIME ZONE := SYSTIMESTAMP;
  v_payload_h  VARCHAR2(64);
  v_dur_ms     NUMBER;
  v_cap        NUMBER;

  v_title          VARCHAR2(400);
  v_summary        CLOB;
  v_classification VARCHAR2(20);
  v_findings       CLOB;
  v_findings_n     NUMBER;
  v_confidence     NUMBER;
  v_correlation_id RAW(16);
  v_correlation_h  VARCHAR2(64);
  v_corr_exists    NUMBER;
  v_label          NUMBER;
  v_lon            NUMBER;
  v_lat            NUMBER;
  v_geo            SDO_GEOMETRY;

  v_briefing_id    RAW(16);
BEGIN
  UC4_OSINT.OLS_PRE_HANDLER(p_label_max);
  v_cap := UC4_OSINT.LABEL_CAP();
  v_payload_h := RAWTOHEX(SYS_GUID())||RAWTOHEX(SYS_GUID()); -- 64-hex unique trace, not a crypto hash
  UC4_OSINT.AUDIT_TOOL_INVOKE(c_tool_name, v_payload_h, v_invocation);

  v_title          := JSON_VALUE(p_body, '$.briefing.title'          RETURNING VARCHAR2(400));
  v_summary        := JSON_QUERY(p_body, '$.briefing.summary'        RETURNING CLOB);
  IF v_summary IS NULL THEN
    v_summary := JSON_VALUE(p_body, '$.briefing.summary' RETURNING CLOB);
  END IF;
  v_classification := UPPER(JSON_VALUE(p_body, '$.briefing.classification' RETURNING VARCHAR2(20)));
  v_findings       := JSON_QUERY(p_body, '$.briefing.findings'       RETURNING CLOB);
  v_confidence     := JSON_VALUE(p_body, '$.briefing.confidence'     RETURNING NUMBER);
  v_correlation_h  := JSON_VALUE(p_body, '$.briefing.correlation_id' RETURNING VARCHAR2(64));
  v_lon            := JSON_VALUE(p_body, '$.briefing.geo.coordinates[0]' RETURNING NUMBER);
  v_lat            := JSON_VALUE(p_body, '$.briefing.geo.coordinates[1]' RETURNING NUMBER);

  -- Validation: title length
  IF v_title IS NULL OR LENGTH(v_title) > 200 THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Invalid title',
      'briefing.title is required and must be ≤ 200 chars.',
      v_invocation);
    RETURN;
  END IF;

  -- Validation: summary length (CLOB but cap at 4000 char user-facing)
  IF v_summary IS NULL OR DBMS_LOB.GETLENGTH(v_summary) > 4000 THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Invalid summary',
      'briefing.summary is required and must be ≤ 4000 chars.',
      v_invocation);
    RETURN;
  END IF;

  -- Validation: classification.  Note the explicit NULL branch — without
  -- it, "NULL NOT IN ('OFFEN','INTERN','NFD')" evaluates to NULL (not
  -- TRUE), the IF skips, and we'd let an unclassified row reach the
  -- INSERT and surface as a generic 500 from the NOT-NULL constraint.
  IF v_classification IS NULL OR v_classification NOT IN ('OFFEN','INTERN','NFD') THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Invalid classification',
      'briefing.classification must be OFFEN, INTERN, or NFD (got: '
        ||COALESCE(v_classification, '<missing>')||').',
      v_invocation);
    RETURN;
  END IF;
  v_label := CASE v_classification WHEN 'OFFEN' THEN 10 WHEN 'INTERN' THEN 30 WHEN 'NFD' THEN 50 END;

  -- Validation: ols_label must be ≤ user cap (no privilege escalation)
  IF v_label > v_cap THEN
    UC4_OSINT.WRITE_PROBLEM(403, 'forbidden',
      'Classification exceeds caller cap',
      'User-Cap erlaubt nur bis '
        ||CASE v_cap WHEN 10 THEN 'OFFEN' WHEN 30 THEN 'INTERN' WHEN 50 THEN 'NFD' END
        ||', Briefing-Klassifikation ist '||v_classification||'.',
      v_invocation);
    RETURN;
  END IF;

  -- Validation: findings is non-empty array
  IF v_findings IS NULL OR DBMS_LOB.GETLENGTH(v_findings) < 3 THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Missing findings',
      'briefing.findings must be a non-empty array of objects.',
      v_invocation);
    RETURN;
  END IF;
  SELECT COUNT(*) INTO v_findings_n FROM JSON_TABLE(v_findings, '$[*]' COLUMNS (rn FOR ORDINALITY));
  IF v_findings_n = 0 THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Empty findings',
      'briefing.findings must contain ≥ 1 finding.',
      v_invocation);
    RETURN;
  END IF;

  -- Validation: correlation_id must exist
  IF v_correlation_h IS NULL THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Missing correlation_id',
      'briefing.correlation_id is required (uuid hex form).',
      v_invocation);
    RETURN;
  END IF;
  BEGIN
    v_correlation_id := HEXTORAW(v_correlation_h);
  EXCEPTION WHEN OTHERS THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Invalid correlation_id format',
      'correlation_id must be a 32-char hex UUID.',
      v_invocation);
    RETURN;
  END;
  SELECT COUNT(*) INTO v_corr_exists
    FROM correlation_event
   WHERE correlation_id = v_correlation_id;
  IF v_corr_exists = 0 THEN
    UC4_OSINT.WRITE_PROBLEM(400, 'bad-request',
      'Unknown correlation_id',
      'No correlation_event row matches '||v_correlation_h||'.',
      v_invocation);
    RETURN;
  END IF;

  -- Optional geo
  IF v_lon IS NOT NULL AND v_lat IS NOT NULL THEN
    v_geo := SDO_GEOMETRY(2001, 4326, SDO_POINT_TYPE(v_lon, v_lat, NULL), NULL, NULL);
  END IF;

  -- Validated → insert
  INSERT INTO briefing (
    correlation_id, title, body, model_id, prompt_hash,
    generated_at, generated_by, review_state,
    geo, geo_h3_r5, ols_label
  ) VALUES (
    v_correlation_id, v_title, v_summary,
    'tool:persist_briefing/1.0',
    v_payload_h,
    SYSTIMESTAMP,
    'tool:persist_briefing',
    'DRAFT',
    v_geo,
    CASE WHEN v_lat IS NOT NULL AND v_lon IS NOT NULL
         THEN 'r5/'||TO_CHAR(ROUND(v_lat,1))||'/'||TO_CHAR(ROUND(v_lon,1)) END,
    v_label
  ) RETURNING briefing_id INTO v_briefing_id;
  COMMIT;

  -- Second audit row capturing the persisted briefing_id
  UC4_OSINT.AUDIT_TOOL_INVOKE(c_tool_name, v_payload_h, v_invocation,
    p_action => 'PERSIST_BRIEFING', p_table_name => 'BRIEFING', p_row_id => v_briefing_id);

  v_dur_ms := EXTRACT(SECOND FROM (SYSTIMESTAMP - v_started)) * 1000;
  OWA_UTIL.STATUS_LINE(201, NULL, FALSE);
  OWA_UTIL.MIME_HEADER('application/json', FALSE);
  OWA_UTIL.HTTP_HEADER_CLOSE;
  HTP.PRN(JSON_OBJECT(
    'request_id'      VALUE v_invocation,
    'duration_ms'     VALUE ROUND(v_dur_ms, 1),
    'data'            VALUE JSON_OBJECT(
      'briefing_id'   VALUE RAWTOHEX(v_briefing_id),
      'persisted_at'  VALUE TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ) FORMAT JSON,
    'ols_cap_applied' VALUE v_cap,
    'ols_cap_label'   VALUE CASE v_cap WHEN 10 THEN 'OFFEN' WHEN 30 THEN 'INTERN'
                                       WHEN 50 THEN 'NFD'   WHEN 70 THEN 'GEHEIM' END));
EXCEPTION WHEN OTHERS THEN
  ROLLBACK;
  UC4_OSINT.WRITE_PROBLEM(500, 'internal',
    'Internal Server Error',
    SUBSTR(SQLERRM, 1, 1024),
    v_invocation);
END;
/
GRANT EXECUTE ON UC4_OSINT.TOOL_PERSIST_BRIEFING TO PUBLIC;

-- ---------------------------------------------------------------------------
-- (6) TOOL_VECTOR_HYBRID_SEARCH — Skeleton (today: 503 if embeddings NULL)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE UC4_OSINT.TOOL_VECTOR_HYBRID_SEARCH(p_body IN CLOB, p_label_max IN VARCHAR2 DEFAULT NULL) AS
  c_tool_name  CONSTANT VARCHAR2(40) := 'vector_hybrid_search';
  v_invocation VARCHAR2(64) := RAWTOHEX(SYS_GUID());
  v_started    TIMESTAMP WITH TIME ZONE := SYSTIMESTAMP;
  v_payload_h  VARCHAR2(64);
  v_cap        NUMBER;
  v_dur_ms     NUMBER;

  v_null_embeddings NUMBER;
BEGIN
  UC4_OSINT.OLS_PRE_HANDLER(p_label_max);
  v_cap := UC4_OSINT.LABEL_CAP();
  v_payload_h := RAWTOHEX(SYS_GUID())||RAWTOHEX(SYS_GUID()); -- 64-hex unique trace, not a crypto hash
  UC4_OSINT.AUDIT_TOOL_INVOKE(c_tool_name, v_payload_h, v_invocation);

  -- Embedding-Readiness-Check.  Solange auch nur eine Zeile NULL ist,
  -- ist der Korpus nicht stationär — wir wollen nicht halb-blind suchen.
  SELECT COUNT(*) INTO v_null_embeddings
    FROM signal_vectors
   WHERE embedding IS NULL;

  IF v_null_embeddings > 0 THEN
    OWA_UTIL.STATUS_LINE(503, NULL, FALSE);
    OWA_UTIL.MIME_HEADER('application/problem+json', FALSE);
    OWA_UTIL.HTTP_HEADER_CLOSE;
    HTP.PRN(JSON_OBJECT(
      'type'        VALUE 'https://uc4.cloudebility.com/errors/embeddings-not-ready',
      'title'       VALUE 'Embeddings not yet computed',
      'status'      VALUE 503,
      'detail'      VALUE 'Run db/seeds/uc4_osint/02_compute_embeddings.sql first. '
                          ||v_null_embeddings||' rows still NULL.',
      'instance'    VALUE v_invocation,
      'retry-after' VALUE 600));
    RETURN;
  END IF;

  -- TODO once embeddings exist:
  --   1. v_q_vec := DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING(:query, OCI_GENAI_PARAMS);
  --   2. SELECT VECTOR_DISTANCE(sv.embedding, v_q_vec, COSINE) AS distance,
  --             sn.event_id, sn.title, sn.summary, sn.observed_at, sn.ols_label
  --        FROM signal_vectors sv JOIN signal_normalized sn ON sn.event_id=sv.event_id
  --       WHERE sn.ols_label <= UC4_OSINT.LABEL_CAP()
  --         [AND sn.source_type IN (:list)]
  --         [AND sn.observed_at >= :occurred_after]
  --       ORDER BY distance
  --       FETCH APPROXIMATE FIRST :top_k ROWS ONLY
  --   3. Compose hits[] in the response shape from the spec.
  --
  -- Until then we return a clear 503 with retry-after — that's also what
  -- agents need to see so they degrade gracefully (skip the vector tool,
  -- fall back to graph_query / spatial_aggregate).
  v_dur_ms := EXTRACT(SECOND FROM (SYSTIMESTAMP - v_started)) * 1000;
  OWA_UTIL.STATUS_LINE(501, NULL, FALSE);  -- not implemented (post-readiness)
  OWA_UTIL.MIME_HEADER('application/problem+json', FALSE);
  OWA_UTIL.HTTP_HEADER_CLOSE;
  HTP.PRN(JSON_OBJECT(
    'type'        VALUE 'https://uc4.cloudebility.com/errors/not-implemented',
    'title'       VALUE 'Vector hybrid search not yet implemented',
    'status'      VALUE 501,
    'detail'      VALUE 'Embeddings are populated, but the search handler is the next deliverable. '
                        ||'Use graph_query or spatial_aggregate today.',
    'instance'    VALUE v_invocation));
EXCEPTION WHEN OTHERS THEN
  UC4_OSINT.WRITE_PROBLEM(500, 'internal',
    'Internal Server Error',
    SUBSTR(SQLERRM, 1, 1024),
    v_invocation);
END;
/
GRANT EXECUTE ON UC4_OSINT.TOOL_VECTOR_HYBRID_SEARCH TO PUBLIC;

-- ---------------------------------------------------------------------------
-- (7) ORDS Module + Templates + Handlers
--     Module first, THEN templates, THEN handlers (per Stolperfalle Nr. 1
--     in der Aufgabe — separate ORDS calls, keine Ein-Block-Definition).
-- ---------------------------------------------------------------------------
DECLARE
  v_module_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_module_count FROM user_ords_modules
   WHERE name = 'api.v1.tools';
  IF v_module_count = 0 THEN
    ORDS.DEFINE_MODULE(
      p_module_name    => 'api.v1.tools',
      p_base_path      => '/api/v1/tools/',
      p_items_per_page => 25,
      p_status         => 'PUBLISHED',
      p_comments       => 'UC4_OSINT tools for Threat-Fusion-Agent (Tag 7).');
    DBMS_OUTPUT.PUT_LINE('ORDS module api.v1.tools created.');
  END IF;
END;
/

DECLARE
  PROCEDURE define_tool(
    p_template VARCHAR2,
    p_proc     VARCHAR2
  ) IS
    v_exists NUMBER;
  BEGIN
    -- Template (idempotent). user_ords_templates has MODULE_ID (FK to
    -- user_ords_modules.id), not MODULE_NAME — join needed.
    SELECT COUNT(*) INTO v_exists
      FROM user_ords_templates t
      JOIN user_ords_modules m ON m.id = t.module_id
     WHERE m.name = 'api.v1.tools' AND t.uri_template = p_template;
    IF v_exists = 0 THEN
      ORDS.DEFINE_TEMPLATE(
        p_module_name  => 'api.v1.tools',
        p_pattern      => p_template);
    END IF;

    -- POST handler. ORDS.DEFINE_HANDLER raises ORA-20999 (or "already
    -- exists") when a duplicate is attempted — we swallow that for
    -- idempotency. To pick up source-text changes, drop the handler
    -- manually first (or write a separate purge step).
    BEGIN
      ORDS.DEFINE_HANDLER(
        p_module_name    => 'api.v1.tools',
        p_pattern        => p_template,
        p_method         => 'POST',
        p_source_type    => 'plsql/block',
        p_mimes_allowed  => 'application/json',
        p_source         => 'BEGIN UC4_OSINT.'||p_proc||'(:body_text, :header_x_ols_label_max); END;');
    EXCEPTION WHEN OTHERS THEN
      IF SQLCODE != -20999
         AND SQLERRM NOT LIKE '%already exists%'
         AND SQLERRM NOT LIKE '%duplicate%'
      THEN
        RAISE;
      END IF;
    END;

    -- Parameter binding so ORDS surfaces the X-OLS-Label-Max request
    -- header as :header_x_ols_label_max inside the handler PL/SQL block.
    -- Without this, the bind reference in the handler source would
    -- evaluate to NULL even when the header is present.
    BEGIN
      ORDS.DEFINE_PARAMETER(
        p_module_name        => 'api.v1.tools',
        p_pattern            => p_template,
        p_method             => 'POST',
        p_name               => 'X-OLS-Label-Max',
        p_bind_variable_name => 'header_x_ols_label_max',
        p_source_type        => 'HEADER',
        p_param_type         => 'STRING',
        p_access_method      => 'IN');
    EXCEPTION WHEN OTHERS THEN
      IF SQLCODE != -20999
         AND SQLERRM NOT LIKE '%already exists%'
         AND SQLERRM NOT LIKE '%duplicate%'
      THEN
        RAISE;
      END IF;
    END;
  END;
BEGIN
  define_tool('graph_query',          'TOOL_GRAPH_QUERY');
  define_tool('spatial_aggregate',    'TOOL_SPATIAL_AGGREGATE');
  define_tool('persist_briefing',     'TOOL_PERSIST_BRIEFING');
  define_tool('vector_hybrid_search', 'TOOL_VECTOR_HYBRID_SEARCH');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('ORDS templates+handlers defined for 4 tools.');
END;
/

-- ---------------------------------------------------------------------------
-- Tail-Sanity
-- ---------------------------------------------------------------------------
DECLARE
  v_procs   NUMBER;
  v_tpls    NUMBER;
  v_hdlrs   NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_procs FROM all_procedures
   WHERE owner = 'UC4_OSINT'
     AND object_name IN ('TOOL_GRAPH_QUERY','TOOL_SPATIAL_AGGREGATE',
                         'TOOL_PERSIST_BRIEFING','TOOL_VECTOR_HYBRID_SEARCH',
                         'OLS_PRE_HANDLER','AUDIT_TOOL_INVOKE','WRITE_PROBLEM')
     AND procedure_name IS NULL;  -- top-level standalone procs
  IF v_procs != 7 THEN
    RAISE_APPLICATION_ERROR(-20007,
      '05_ords_tools.sql: erwartete 7 Top-Level-Procedures, gefunden '||v_procs);
  END IF;

  SELECT COUNT(*) INTO v_tpls
    FROM user_ords_templates t
    JOIN user_ords_modules   m ON m.id = t.module_id
   WHERE m.name = 'api.v1.tools';
  IF v_tpls != 4 THEN
    RAISE_APPLICATION_ERROR(-20007,
      '05_ords_tools.sql: erwartete 4 ORDS-Templates, gefunden '||v_tpls);
  END IF;

  SELECT COUNT(*) INTO v_hdlrs
    FROM user_ords_handlers  h
    JOIN user_ords_templates t ON t.id = h.template_id
    JOIN user_ords_modules   m ON m.id = t.module_id
   WHERE m.name = 'api.v1.tools' AND h.method = 'POST';
  IF v_hdlrs != 4 THEN
    RAISE_APPLICATION_ERROR(-20007,
      '05_ords_tools.sql: erwartete 4 POST-Handler, gefunden '||v_hdlrs);
  END IF;

  DBMS_OUTPUT.PUT_LINE('05_ords_tools.sql OK: '
    ||v_procs||' procs, '||v_tpls||' templates, '||v_hdlrs||' POST handlers.');
END;
/

-- ===========================================================================
-- Done. Reference the new endpoints from scripts/test-uc4-tools.sh
-- (curl smoke tests with the three OLS personas).
-- ===========================================================================
