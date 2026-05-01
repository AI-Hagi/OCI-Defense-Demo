-- ===========================================================================
-- UC4_OSINT — Tag 2: Indexes
-- Oracle AI Database 26ai (ATP, eu-frankfurt-1, oci-defence-demo Compartment)
--
-- Geltungsbereich:
--   1) B-tree-Indexes auf den Hot-Query-Pfaden der 9 Stammtabellen
--   2) Spatial-Indexes (MDSYS.SPATIAL_INDEX_V2) auf allen 5 geo-Spalten,
--      mit vorgelagerter idempotenter user_sdo_geom_metadata-Pflege
--   3) AI Vector Search Index auf signal_vectors.embedding —
--      **IVF statt HNSW**, weil vector_memory_size auf dieser ATP-Shape
--      auf 2816K gedeckelt ist (ALTER SYSTEM SET vector_memory_size
--      ergibt ORA-01031 selbst für ADMIN). HNSW braucht für das Demo-
--      Ziel von 500k × 1024-dim FLOAT32-Vektoren ~2 GB Raw-Daten plus
--      ~256 MB Graph-Overhead — Faktor 1000 über dem ATP-Cap.
--   4) B-tree-Indexes auf den 5 geo_h3_r5-Spalten für H3-Bucket-Aggregation
--   5) JSON Search Index auf correlation_event.payload für JSON_VALUE /
--      JSON_TABLE / JSON_TEXTCONTAINS auf die Detektor-Detail-Liste
--
-- Was hier NICHT passiert (folgt in separaten Files):
--   * OLS-Policy / Privileg-Lockdown auf audit_trail   → 03_security.sql
--   * Property Graph (SQL/PGQ) Definition              → 04_graph.sql
--
-- Idempotenz-Strategie:
--   Jeder CREATE INDEX in einem eigenen BEGIN..EXCEPTION-Block.
--   Geschluckte ORA-Codes (alles andere wird re-raised):
--     ORA-01408  (column already indexed) — gleiche Spalte zweimal
--     ORA-00955  (name already used)      — Index-Name kollidiert
--     ORA-29879  (cannot create index on empty table for vector index)
--                 → tritt nur auf, falls jemand HNSW ohne Daten anlegen
--                 will; bei IVF auf leerer Tabelle ist es kein Problem,
--                 aber wir swallowen es defensiv.
--
-- Voraussetzungen:
--   * 00_create_schema_owner.sql + 01_tables.sql wurden bereits applied.
--   * Connection als ADMIN (ATP), Verbindungs-Alias sovdef26_tp.
--   * MDSYS.SDO_GEOM_METADATA_TABLE / user_sdo_geom_metadata-View
--     sichtbar — bei ATP standardmäßig der Fall, weil DWROLE den
--     Zugriff bündelt.
--
-- Spec-Reconciliation gegenüber Tag-2-Roadmap (Spalten-Namen):
--   Die Roadmap nennt occurred_at / ingested_at / source_id / entity_type /
--   pattern_name. 01_tables.sql verwendet die tatsächlichen Spalten:
--     signal_normalized.occurred_at  → observed_at
--     signal_normalized.source_id    → source_provider
--     signal_raw.ingested_at         → collected_at
--     signal_raw.source_id           → source_provider
--     entity.entity_type             → entity_kind
--     correlation_event.pattern_name → correlation_kind
--   Die Indexes unten zielen auf die echten Spalten.
-- ===========================================================================

ALTER SESSION SET CURRENT_SCHEMA = UC4_OSINT;
SET DEFINE OFF
WHENEVER SQLERROR EXIT FAILURE

-- ---------------------------------------------------------------------------
-- (1) B-tree-Indexes — Hot-Query-Pfade
--
-- DESC-Sortierung wo Time-Range-Queries die Standard-Form sind ("show me
-- the 200 most recent ..."). Composite-Index (provider, time) für die
-- typische Demo-Query "alle AIS-Signale der letzten 24h".
-- ---------------------------------------------------------------------------

-- signal_normalized
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_sn_observed_desc       ON signal_normalized (observed_at DESC)';                  EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_sn_entity_ref          ON signal_normalized (entity_ref)';                         EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_sn_provider_observed   ON signal_normalized (source_provider, observed_at DESC)';  EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/

-- signal_raw
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_sr_collected_desc      ON signal_raw (collected_at DESC)';                         EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_sr_provider_collected  ON signal_raw (source_provider, collected_at DESC)';        EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/

-- entity
-- (UNIQUE auf (canonical_id_kind, canonical_id) ist bereits in 01_tables.sql
--  als CONSTRAINT-backed Index angelegt — hier nur entity_kind ergänzen.)
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_entity_kind            ON entity (entity_kind)';                                   EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/

-- correlation_event
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_corr_detected_desc     ON correlation_event (detected_at DESC)';                   EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_corr_kind_detected     ON correlation_event (correlation_kind, detected_at DESC)'; EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/

-- briefing
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_brief_generated_desc   ON briefing (generated_at DESC)';                           EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_brief_correlation      ON briefing (correlation_id)';                              EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_brief_state_generated  ON briefing (review_state, generated_at DESC)';             EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/

-- ---------------------------------------------------------------------------
-- (2) Spatial Indexes — MDSYS.SPATIAL_INDEX_V2 auf allen 5 geo-Spalten
--
-- Vor jedem CREATE INDEX SPATIAL muss eine Zeile in user_sdo_geom_metadata
-- existieren. WGS84 SRID 4326, Bounds Lat ±90 / Lon ±180, Tolerance 0.0001
-- (= 0.0001° ≈ 11 m am Äquator — passend für AIS / ADS-B-Genauigkeit).
--
-- Idempotenz: erst DELETE der Vor-Run-Metadaten, dann INSERT. Wird in einem
-- PL/SQL-Block bundled, damit ein partial state nicht zwischen den
-- Tabellen entstehen kann (bei ORA-... wird einer der INSERTs failen, aber
-- die Anzahl ist klein und der Rerun ist deterministisch).
-- ---------------------------------------------------------------------------
DECLARE
  TYPE t_tab IS TABLE OF VARCHAR2(40);
  v_tabs   t_tab := t_tab(
    'SIGNAL_NORMALIZED','ENTITY','EMS_EMITTER','CORRELATION_EVENT','BRIEFING'
  );
BEGIN
  FOR i IN 1 .. v_tabs.COUNT LOOP
    -- Idempotent: alten Eintrag wegräumen, falls vorhanden.
    DELETE FROM user_sdo_geom_metadata
     WHERE table_name = v_tabs(i) AND column_name = 'GEO';

    -- Neue WGS84-Metadaten setzen.
    INSERT INTO user_sdo_geom_metadata (table_name, column_name, diminfo, srid)
    VALUES (
      v_tabs(i),
      'GEO',
      MDSYS.SDO_DIM_ARRAY(
        MDSYS.SDO_DIM_ELEMENT('LONGITUDE', -180, 180, 0.0001),
        MDSYS.SDO_DIM_ELEMENT('LATITUDE',   -90,  90, 0.0001)
      ),
      4326
    );
  END LOOP;
  COMMIT;
END;
/

BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_sn_geo_spatial   ON signal_normalized (geo) INDEXTYPE IS MDSYS.SPATIAL_INDEX_V2';   EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_entity_geo_spatial ON entity (geo) INDEXTYPE IS MDSYS.SPATIAL_INDEX_V2';            EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_ems_geo_spatial   ON ems_emitter (geo) INDEXTYPE IS MDSYS.SPATIAL_INDEX_V2';        EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_corr_geo_spatial  ON correlation_event (geo) INDEXTYPE IS MDSYS.SPATIAL_INDEX_V2';  EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_brief_geo_spatial ON briefing (geo) INDEXTYPE IS MDSYS.SPATIAL_INDEX_V2';           EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/

-- ---------------------------------------------------------------------------
-- (3) AI Vector Index — IVF auf signal_vectors.embedding
--
-- HNSW wäre der erste Wunsch (recall ~99%, sub-100ms latency), scheitert
-- aber an vector_memory_size = 2816K (ATP-Cap, ALTER SYSTEM verboten).
-- IVF ist disk-based:
--   * Memory-Bedarf konstant niedrig
--   * Recall ~95% — für Defence-Demo akzeptabel
--   * NEIGHBOR PARTITIONS = ceil(sqrt(500_000)) = 707 (per Demo-Roadmap-
--     Sizing). Bei IVF ist eine Faustregel sqrt(N) Partitions; bei Skalierung
--     nach oben kann der Index neu mit größerem Wert gebaut werden.
--
-- DISTANCE COSINE: passend zu Cohere-Embeddings (L2-normalisiert; COSINE
-- entspricht hier dot-product). Andere Optionen wären EUCLIDEAN (wenn
-- Magnitude relevant wäre) oder DOT (wenn die Embeddings garantiert
-- pre-normalisiert sind und man die rechte Hälfte sparen will).
-- ---------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE
    'CREATE VECTOR INDEX signal_vectors_ivf_idx ON signal_vectors (embedding)
       ORGANIZATION NEIGHBOR PARTITIONS
       WITH DISTANCE COSINE
       PARAMETERS (TYPE IVF, NEIGHBOR PARTITIONS 707)';
EXCEPTION
  WHEN OTHERS THEN
    -- ORA-29879 wird hier defensiv weggefiltert (für die HNSW-Variante
    -- relevant; IVF auf leeren Tabellen baut normalerweise sauber).
    IF SQLCODE NOT IN (-1408, -955, -29879) THEN
      RAISE;
    END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (4) B-tree-Indexes auf den 5 geo_h3_r5-Spalten
--
-- H3-Bucket-Aggregation ist der primäre Map-Heatmap-Pfad
-- (SELECT geo_h3_r5, COUNT(*) FROM ... GROUP BY geo_h3_r5).
-- Auch GROUP-BY-only profitiert von einem regulären B-tree-Index.
-- ---------------------------------------------------------------------------
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_sn_h3_r5     ON signal_normalized (geo_h3_r5)'; EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_entity_h3_r5 ON entity (geo_h3_r5)';            EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_ems_h3_r5    ON ems_emitter (geo_h3_r5)';       EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_corr_h3_r5   ON correlation_event (geo_h3_r5)'; EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_brief_h3_r5  ON briefing (geo_h3_r5)';          EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/

-- ---------------------------------------------------------------------------
-- (5) JSON Search Index auf correlation_event.payload
--
-- correlation_event.payload listet die korrelierten event_ids /
-- entity_ids in Detektor-spezifischer Form. JSON Search Index gibt uns
-- effizientes JSON_EXISTS / JSON_VALUE / JSON_TEXTCONTAINS — wichtig
-- für die UC4-Demo-Query "welche Korrelationen erwähnen <event_id>?".
--
-- SEARCH_ON TEXT_VALUE indiziert sowohl Schlüssel als auch String-Werte;
-- für reine numerische Filter wäre DATAGUIDE ON optimal, aber Defaults
-- reichen für die Demo-Query.
-- ---------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE
    'CREATE SEARCH INDEX idx_corr_payload_json ON correlation_event (payload) FOR JSON';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-1408, -955) THEN
      RAISE;
    END IF;
END;
/

-- ---------------------------------------------------------------------------
-- Tail-Sanity: Wir prüfen die jeweiligen Index-Typen einzeln, damit die
-- Diagnose im Fehlerfall klar ist (welcher Block hat versagt).
-- Erwartete Mengen:
--   * 11 reguläre B-tree-Indexes (1+1+1+1+1+1+1+1+1+1+1 aus Block 1)
--      → idx_sn_observed_desc, idx_sn_entity_ref, idx_sn_provider_observed,
--        idx_sr_collected_desc, idx_sr_provider_collected,
--        idx_entity_kind,
--        idx_corr_detected_desc, idx_corr_kind_detected,
--        idx_brief_generated_desc, idx_brief_correlation,
--        idx_brief_state_generated
--   * 5 Spatial-Indexes (Block 2)
--   * 1 Vector-Index (Block 3)
--   * 5 H3-Bucket-Indexes (Block 4)
--   * 1 JSON Search Index (Block 5)
--   = 23 zusätzliche Index-Objekte.
--
-- Hinweis: implizite UNIQUE-Indexes von PK/UNIQUE-Constraints aus
-- 01_tables.sql werden vom Sanity-Check absichtlich nicht mitgezählt.
-- ---------------------------------------------------------------------------
DECLARE
  v_btree   NUMBER;
  v_spatial NUMBER;
  v_vector  NUMBER;
  v_search  NUMBER;
BEGIN
  -- Reguläre B-tree-Indexes (Blöcke 1 und 4). DESC-Sortierung erzeugt in
  -- 26ai einen Function-Based-Index ("FUNCTION-BASED NORMAL") — semantisch
  -- B-tree, aber unter anderem index_type-Eintrag. Beide Varianten zählen.
  SELECT COUNT(*) INTO v_btree
    FROM user_indexes
   WHERE index_type IN ('NORMAL','NORMAL/REV','FUNCTION-BASED NORMAL')
     AND index_name IN (
       'IDX_SN_OBSERVED_DESC','IDX_SN_ENTITY_REF','IDX_SN_PROVIDER_OBSERVED',
       'IDX_SR_COLLECTED_DESC','IDX_SR_PROVIDER_COLLECTED',
       'IDX_ENTITY_KIND',
       'IDX_CORR_DETECTED_DESC','IDX_CORR_KIND_DETECTED',
       'IDX_BRIEF_GENERATED_DESC','IDX_BRIEF_CORRELATION','IDX_BRIEF_STATE_GENERATED',
       'IDX_SN_H3_R5','IDX_ENTITY_H3_R5','IDX_EMS_H3_R5','IDX_CORR_H3_R5','IDX_BRIEF_H3_R5'
     );

  -- Spatial-Indexes (Block 2) — index_type = 'DOMAIN', ityp_owner='MDSYS', ityp_name='SPATIAL_INDEX_V2'
  SELECT COUNT(*) INTO v_spatial
    FROM user_indexes
   WHERE index_type = 'DOMAIN'
     AND ityp_owner = 'MDSYS'
     AND ityp_name  = 'SPATIAL_INDEX_V2';

  -- Vector-Index (Block 3) — index_type = 'VECTOR' in 26ai
  SELECT COUNT(*) INTO v_vector
    FROM user_indexes
   WHERE index_name = 'SIGNAL_VECTORS_IVF_IDX';

  -- JSON Search Index (Block 5) — domain index from CTXSYS
  SELECT COUNT(*) INTO v_search
    FROM user_indexes
   WHERE index_name = 'IDX_CORR_PAYLOAD_JSON';

  IF v_btree != 16 THEN
    RAISE_APPLICATION_ERROR(-20002,
      '02_indexes.sql: erwartete 16 B-tree-Indexes (11 hot-paths + 5 H3), gefunden ' || v_btree);
  END IF;
  IF v_spatial != 5 THEN
    RAISE_APPLICATION_ERROR(-20002,
      '02_indexes.sql: erwartete 5 Spatial-Indexes, gefunden ' || v_spatial);
  END IF;
  IF v_vector != 1 THEN
    RAISE_APPLICATION_ERROR(-20002,
      '02_indexes.sql: erwartete 1 Vector-Index (signal_vectors_ivf_idx), gefunden ' || v_vector);
  END IF;
  IF v_search != 1 THEN
    RAISE_APPLICATION_ERROR(-20002,
      '02_indexes.sql: erwartete 1 JSON Search Index (idx_corr_payload_json), gefunden ' || v_search);
  END IF;

  DBMS_OUTPUT.PUT_LINE(
    '02_indexes.sql OK: btree='||v_btree||', spatial='||v_spatial||
    ', vector='||v_vector||', search='||v_search);
END;
/

-- ===========================================================================
-- Done. Folge:
--   * 03_security.sql — OLS-Policy attachen, audit_trail-Lockdown
--   * 04_graph.sql    — UC4-Property-Graph
-- Wenn sich der Demo-Korpus später dem Limit nähert: HNSW wird erst durch
-- Vergrößerung der ATP-Shape (mehr OCPU → mehr SGA → mehr vector_memory_size-
-- Headroom) realistisch. Alternativ INT8-Quantization erwägen, wenn
-- Recall noch akzeptabel bleibt.
-- ===========================================================================
