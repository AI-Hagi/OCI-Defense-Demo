-- ===========================================================================
-- UC4_OSINT — Tag 4: Property Graph (SQL/PGQ)
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1)
--
-- Geltungsbereich:
--   1) Zwei kleine Junction-Tabellen, die korrelations-zu-konstituent-
--      Beziehungen explizit machen — ohne sie wäre correlation_event
--      ein Insel-Vertex im Graph (nichts zeigt darauf, nichts geht raus).
--        - correlation_includes_event  (correlation → signal_normalized)
--        - correlation_includes_entity (correlation → entity)
--      Beide append-only, ols_label NOT NULL, mit Composite-PK auf
--      (correlation_id, *), ON DELETE CASCADE auf correlation_id-Seite.
--   2) Property Graph UC4_OSINT.osint_graph mit:
--        Vertices: entity, signal_normalized (LABEL event),
--                  correlation_event (LABEL correlation)
--        Edges:    entity_mention                (event → entity)
--                  correlation_includes_event    (correlation → event)
--                  correlation_includes_entity   (correlation → entity)
--   3) B-tree-Indexes auf den Junction-Tabellen-FKs für effiziente
--      GRAPH_TABLE-Joins.
--   4) Sanity: trivialer GRAPH_TABLE-Probe-Query, der die Graph-
--      Definition gegen den Optimizer kompiliert.
--
-- Konstruktive Entscheidung — Edge-Modell für correlation_event:
--   correlation_event.payload JSON hält die Korrelation-Details (Detektor-
--   spezifisch). Property Graphs in 26ai brauchen aber relationale Edges
--   mit klarem (source_key, destination_key)-Vertrag — kein JSON-Pfad-
--   Decompose at query time. Die zwei Junction-Tabellen sind die
--   minimal-invasive Lösung, die den Graph-Layer ohne Re-Design der
--   payload-JSON-Struktur ermöglicht.
--
--   Alternativen die wir verworfen haben:
--     * View über JSON_TABLE(payload): funktioniert in GRAPH_TABLE NICHT
--       (Edge-Tables müssen physische Tabellen oder Materialized Views
--       sein, mit FK-Garantien).
--     * Korrelation-Liste als separate Spalte (event_ids RAW(16)[]):
--       VARRAYs in 26ai sind nicht Edge-Table-tauglich.
--
--   Trade-off: doppelte Schreiblast für den Korrelations-Detektor (er
--   muss correlation_event UND correlation_includes_event/entity füllen).
--   Akzeptabel — die Korrelation läuft asynchron via TxEventQ, nicht im
--   Hot-Path eines Live-Requests.
--
-- Was hier NICHT passiert:
--   * Spatial-Index / HNSW auf Junction-Tabellen — keine geo-/vector-
--     Spalten dort.
--   * OLS-Policy Anwendung — Junction-Tabellen sind Append-only-Edges;
--     OLS-Filterung erbt automatisch von den verbundenen Vertex-Tabellen
--     (über die FK-Joins zur Read-Time).
--
-- Voraussetzungen:
--   * 01_tables.sql, 02_indexes.sql, 03b_ols_app_filter.sql applied.
--   * ADMIN-Verbindung — Property-Graph-CREATE braucht CREATE PROPERTY
--     GRAPH (oder schema-qualified CREATE ANY PROPERTY GRAPH von ADMIN).
--
-- Idempotenz:
--   Junction-Tabellen: DROP-then-CREATE Pattern (wie 01_tables.sql).
--   Property Graph: DROP IF EXISTS via BEGIN..EXCEPTION (Drop-Code
--   ORA-65541 swallowed) — danach sauberer CREATE.
-- ===========================================================================

ALTER SESSION SET CURRENT_SCHEMA = UC4_OSINT;
WHENEVER SQLERROR EXIT FAILURE
SET SERVEROUTPUT ON
SET DEFINE OFF

-- ---------------------------------------------------------------------------
-- (0) Idempotente Drops — zuerst Property Graph, dann Junction-Tabellen
--     (umgekehrt zur Anlegen-Reihenfolge).
-- ---------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE 'DROP PROPERTY GRAPH osint_graph';
EXCEPTION WHEN OTHERS THEN
  -- ORA-42421 = property graph does not exist (first run); ORA-942 =
  -- base table missing (sollte nicht passieren, defensiv geschluckt).
  IF SQLCODE NOT IN (-42421, -942) THEN RAISE; END IF;
END;
/

BEGIN EXECUTE IMMEDIATE 'DROP TABLE correlation_includes_entity CASCADE CONSTRAINTS PURGE';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE correlation_includes_event CASCADE CONSTRAINTS PURGE';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/

-- ---------------------------------------------------------------------------
-- (1.1) correlation_includes_event
--      correlation_event → signal_normalized (Many-to-Many)
--
-- role: 'TRIGGER' = das Signal hat die Korrelation ausgelöst (zentral),
--       'CONTEXT' = das Signal ist Hintergrundkontext (peripher).
-- confidence: optional pro Edge (Detektor kann sagen "dieses Signal
--       gehört mit Sicherheit X zur Korrelation").
-- ---------------------------------------------------------------------------
CREATE TABLE correlation_includes_event (
  correlation_id    RAW(16)        NOT NULL,
  event_id          RAW(16)        NOT NULL,
  role              VARCHAR2(16)   DEFAULT 'CONTEXT' NOT NULL,
  confidence        NUMBER(3,2),
  added_at          TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  ols_label         NUMBER(10)     NOT NULL,
  CONSTRAINT pk_corr_inc_event   PRIMARY KEY (correlation_id, event_id),
  CONSTRAINT fk_corr_inc_evt_c   FOREIGN KEY (correlation_id)
                                 REFERENCES correlation_event (correlation_id)
                                 ON DELETE CASCADE,
  CONSTRAINT fk_corr_inc_evt_e   FOREIGN KEY (event_id)
                                 REFERENCES signal_normalized (event_id),
  CONSTRAINT ck_corr_inc_evt_rol CHECK (role IN ('TRIGGER','CONTEXT')),
  CONSTRAINT ck_corr_inc_evt_cnf CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1))
);

COMMENT ON TABLE correlation_includes_event IS
  'UC4: Edge correlation_event → signal_normalized. Wird vom Korrelations-Detektor zusammen mit correlation_event-INSERT befüllt.';

-- ---------------------------------------------------------------------------
-- (1.2) correlation_includes_entity
--      correlation_event → entity (Many-to-Many)
--
-- role: 'PRIMARY' = Hauptverdächtiger / Hauptbeobachtetes Objekt,
--       'SECONDARY' = mit-erwähnt, aber nicht im Mittelpunkt,
--       'CONTEXT'  = Umfeld-Information.
-- ---------------------------------------------------------------------------
CREATE TABLE correlation_includes_entity (
  correlation_id    RAW(16)        NOT NULL,
  entity_id         RAW(16)        NOT NULL,
  role              VARCHAR2(16)   DEFAULT 'PRIMARY' NOT NULL,
  added_at          TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  ols_label         NUMBER(10)     NOT NULL,
  CONSTRAINT pk_corr_inc_entity     PRIMARY KEY (correlation_id, entity_id),
  CONSTRAINT fk_corr_inc_entity_c   FOREIGN KEY (correlation_id)
                                    REFERENCES correlation_event (correlation_id)
                                    ON DELETE CASCADE,
  CONSTRAINT fk_corr_inc_entity_e   FOREIGN KEY (entity_id)
                                    REFERENCES entity (entity_id),
  CONSTRAINT ck_corr_inc_entity_rol CHECK (role IN ('PRIMARY','SECONDARY','CONTEXT'))
);

COMMENT ON TABLE correlation_includes_entity IS
  'UC4: Edge correlation_event → entity. Wird vom Korrelations-Detektor zusammen mit correlation_event-INSERT befüllt.';

-- ---------------------------------------------------------------------------
-- (2) B-tree-Indexes auf Junction-FKs
--
-- Property-Graph-Traversal joint über die FK-Spalten zur Query-Time.
-- Composite-PK indiziert (correlation_id, *) bereits — wir ergänzen
-- den Reverse-Lookup über die "Ziel"-Spalten, damit GRAPH_TABLE-Queries
-- der Form "find correlations involving event X" auch performant sind.
-- ---------------------------------------------------------------------------
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_corr_inc_event_e  ON correlation_includes_event (event_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'CREATE INDEX idx_corr_inc_entity_e ON correlation_includes_entity (entity_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1408,-955) THEN RAISE; END IF; END;
/

-- ---------------------------------------------------------------------------
-- (3) Property Graph osint_graph
--
-- Vertex-Tables:
--   * entity              → Label "entity" (default vom Tabellennamen)
--   * signal_normalized   → Label "event" (semantisch klarer im Graph;
--                           "signal_normalized" wäre für Threat-Fusion-
--                           Queries zu lang)
--   * correlation_event   → Label "correlation"
--
-- Edge-Tables:
--   * entity_mention                → Label "mentions"
--   * correlation_includes_event    → Label "correlation_includes"
--   * correlation_includes_entity   → Label "correlation_concerns"
--
-- PROPERTIES — wir explizieren NICHT alle Spalten als Properties; nur die,
-- die in typischen Demo-Queries vorkommen. Andere Spalten bleiben über die
-- Vertex-/Edge-Tabellen ohnehin per JOIN zugänglich.
-- ---------------------------------------------------------------------------
CREATE PROPERTY GRAPH osint_graph
  VERTEX TABLES (
    entity
      KEY (entity_id)
      LABEL entity
      PROPERTIES (entity_id, entity_kind, canonical_id_kind, canonical_id,
                  display_name, geo_h3_r5, ols_label),

    signal_normalized
      KEY (event_id)
      LABEL event
      PROPERTIES (event_id, source_type, source_provider, observed_at,
                  entity_kind, entity_ref, title, geo_h3_r5,
                  confidence, ols_label),

    correlation_event
      KEY (correlation_id)
      LABEL correlation
      PROPERTIES (correlation_id, correlation_kind, summary,
                  detected_at, start_at, end_at, geo_h3_r5,
                  score, ols_label)
  )
  EDGE TABLES (
    entity_mention
      KEY (mention_id)
      SOURCE      KEY (event_id)  REFERENCES signal_normalized (event_id)
      DESTINATION KEY (entity_id) REFERENCES entity (entity_id)
      LABEL mentions
      PROPERTIES (mention_id, mention_kind, confidence, detected_at, ols_label),

    correlation_includes_event
      KEY (correlation_id, event_id)
      SOURCE      KEY (correlation_id) REFERENCES correlation_event (correlation_id)
      DESTINATION KEY (event_id)       REFERENCES signal_normalized (event_id)
      LABEL correlation_includes
      PROPERTIES (correlation_id, event_id, role, confidence, added_at, ols_label),

    correlation_includes_entity
      KEY (correlation_id, entity_id)
      SOURCE      KEY (correlation_id) REFERENCES correlation_event (correlation_id)
      DESTINATION KEY (entity_id)      REFERENCES entity (entity_id)
      LABEL correlation_concerns
      PROPERTIES (correlation_id, entity_id, role, added_at, ols_label)
  );

-- ---------------------------------------------------------------------------
-- (4) Sanity-Probe: Graph-Definition kompiliert sauber
--
-- Wir laufen drei minimale GRAPH_TABLE-Queries, die jede Edge-Familie
-- einmal anfassen. Alle drei liefern aktuell 0 Zeilen (weil keine Daten
-- in den Tabellen sind), aber der Optimizer-Compile beweist, dass der
-- Graph syntaktisch und referenziell valide ist.
-- ---------------------------------------------------------------------------
DECLARE
  v_count_mentions  NUMBER;
  v_count_inc_evt   NUMBER;
  v_count_inc_ent   NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_count_mentions FROM GRAPH_TABLE (osint_graph
    MATCH (ev IS event) -[m IS mentions]-> (e IS entity)
    COLUMNS (ev.event_id AS ev_id, e.entity_id AS en_id)
  );

  SELECT COUNT(*) INTO v_count_inc_evt FROM GRAPH_TABLE (osint_graph
    MATCH (c IS correlation) -[r IS correlation_includes]-> (ev IS event)
    COLUMNS (c.correlation_id AS c_id, ev.event_id AS ev_id)
  );

  SELECT COUNT(*) INTO v_count_inc_ent FROM GRAPH_TABLE (osint_graph
    MATCH (c IS correlation) -[r IS correlation_concerns]-> (e IS entity)
    COLUMNS (c.correlation_id AS c_id, e.entity_id AS en_id)
  );

  -- Alle drei sollten 0 sein (leere Tabellen). Wenn nicht, prima — heißt
  -- jemand hat Test-Daten geseedet und wir loggen die Counts.
  DBMS_OUTPUT.PUT_LINE(
    '04_graph.sql OK: graph osint_graph compiled. '
    ||'mentions edges='||v_count_mentions
    ||', correlation_includes='||v_count_inc_evt
    ||', correlation_concerns='||v_count_inc_ent);
END;
/

-- ---------------------------------------------------------------------------
-- Tail-Sanity: existiert der Graph wirklich + alle drei Edge-Tabellen?
-- ---------------------------------------------------------------------------
DECLARE
  v_graph_count NUMBER;
  v_edge_tables NUMBER;
BEGIN
  -- Property Graph in dba_property_graphs (NOT user_property_graphs:
  -- der Connection-User ist ADMIN, der Graph gehört UC4_OSINT — gleiche
  -- session-user-vs-current_schema-Falle wie bei user_sdo_geom_metadata
  -- in 02_indexes.sql).
  SELECT COUNT(*) INTO v_graph_count
    FROM dba_property_graphs
   WHERE owner      = 'UC4_OSINT'
     AND graph_name = 'OSINT_GRAPH';
  IF v_graph_count != 1 THEN
    RAISE_APPLICATION_ERROR(-20005,
      '04_graph.sql: erwartete 1 Property Graph UC4_OSINT.OSINT_GRAPH, gefunden '||v_graph_count);
  END IF;

  -- Junction-Tabellen vorhanden (in dba_tables, gleiche Falle)
  SELECT COUNT(*) INTO v_edge_tables
    FROM dba_tables
   WHERE owner      = 'UC4_OSINT'
     AND table_name IN ('CORRELATION_INCLUDES_EVENT','CORRELATION_INCLUDES_ENTITY');
  IF v_edge_tables != 2 THEN
    RAISE_APPLICATION_ERROR(-20005,
      '04_graph.sql: erwartete 2 Junction-Tabellen, gefunden '||v_edge_tables);
  END IF;

  DBMS_OUTPUT.PUT_LINE(
    '04_graph.sql OK: 1 property graph + 2 junction tables ready.');
END;
/

-- ===========================================================================
-- Done. Folge:
--   * services/osint-fusion/app/routers/graph.py — FastAPI-Endpoint
--     /api/osint/graph der GRAPH_TABLE-Queries an /pgql_query-Tool für
--     den Threat-Fusion-Agent ausliefert (Pattern wie geoint).
--   * 05_views.sql — JSON Duality Views, falls für ORDS AutoREST gewollt.
-- ===========================================================================
