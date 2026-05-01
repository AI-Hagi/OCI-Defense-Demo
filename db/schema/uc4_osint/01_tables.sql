-- ===========================================================================
-- UC4_OSINT — Tag 1: Kerntabellen (kein Index, keine OLS-Policy, kein Graph)
-- Oracle AI Database 26ai (eu-frankfurt-1, ATP, oci-defence-demo Compartment)
--
-- Geltungsbereich:
--   9 Stammtabellen für die OSINT-/Threat-Fusion-Pipeline (UC4):
--     1) signal_raw          — rohe Provider-Pulls vor Normalisierung
--     2) signal_normalized   — entitäts-, raum-, zeitbezogen
--     3) signal_vectors      — Cohere-Embeddings, VECTOR(1024,FLOAT32)
--     4) entity              — Akteure / Vessel / Aircraft / Locations
--     5) entity_mention      — Edges für UC4-Property-Graph
--     6) ems_emitter         — EW-Emitter (Jammer / Radar / Comms / Sat-TX)
--     7) correlation_event   — vom Detektor erzeugte Patterns
--     8) briefing            — vom Threat-Fusion-Agent erzeugte Lagebilder
--     9) audit_trail         — immutable Audit-Log (Append-only Konvention,
--                              wird in 03_security.sql per OLS / Trigger
--                              gegen UPDATE/DELETE gesperrt)
--
-- Was hier NICHT passiert (folgt in separaten Files):
--   * Indexes (B-tree, HNSW, Spatial)        → 02_indexes.sql
--   * Oracle Label Security Policy / Realms  → 03_security.sql
--   * Property Graph (SQL/PGQ) Definition    → 04_graph.sql
--   * JSON-Duality-Views, ORDS-Endpoints     → 05_views.sql / 06_ords.sql
--
-- Konventionen (per .claude/skills/oracle-26ai-schema):
--   * Tabellen snake_case, singular
--   * Primärschlüssel RAW(16) DEFAULT SYS_GUID()
--   * Zeitstempel TIMESTAMP WITH TIME ZONE — niemals naive TIMESTAMP
--   * SDO_GEOMETRY immer SRID 4326 (WGS84)
--   * Embedding-Dimension 1024 / FLOAT32 (cohere.embed-multilingual-v3.0,
--     volle Variante — NICHT light)
--   * ols_label NUMBER(10) NOT NULL auf jeder defence-relevanten Tabelle
--   * H3-Bucket geo_h3_r5 VARCHAR2(16) parallel zu jeder Geo-Spalte
--
-- Idempotenz-Strategie:
--   ALTER SESSION setzt das CURRENT_SCHEMA, dann werden alle 9 Tabellen
--   per PL/SQL-Block mit EXCEPTION WHEN OTHERS / SQLCODE = -942
--   defensiv gedroppt (CASCADE CONSTRAINTS PURGE — keine Recyclebin-Leichen,
--   keine Kollisionen mit FKs aus der vorigen Iteration). Die Drop-Reihenfolge
--   ist die Umkehrung der Create-Reihenfolge, damit Child-Tabellen vor ihren
--   Parents verschwinden.
--
-- Voraussetzung:
--   Schema-Owner UC4_OSINT existiert bereits (aus 01_tenants_and_security.sql
--   oder Bootstrap-DDL). Dieser File legt KEINEN User an — das ist ein
--   Provisioning-Schritt mit DBA-Privilegien und gehört nicht in die
--   Migration einer einzelnen Use-Case-Domäne.
-- ===========================================================================

ALTER SESSION SET CURRENT_SCHEMA = UC4_OSINT;

-- ---------------------------------------------------------------------------
-- Idempotente Drops — Reverse-Creation-Order. ORA-00942 wird stillschweigend
-- geschluckt, weil die Tabelle dann einfach noch nicht existiert. Alles
-- andere wird re-raised, damit Provisioning-Fehler nicht maskiert werden.
-- ---------------------------------------------------------------------------
BEGIN EXECUTE IMMEDIATE 'DROP TABLE audit_trail CASCADE CONSTRAINTS PURGE';        EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE briefing CASCADE CONSTRAINTS PURGE';           EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE correlation_event CASCADE CONSTRAINTS PURGE';  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE ems_emitter CASCADE CONSTRAINTS PURGE';        EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE entity_mention CASCADE CONSTRAINTS PURGE';     EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE entity CASCADE CONSTRAINTS PURGE';             EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE signal_vectors CASCADE CONSTRAINTS PURGE';     EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE signal_normalized CASCADE CONSTRAINTS PURGE';  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'DROP TABLE signal_raw CASCADE CONSTRAINTS PURGE';         EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;
/

-- ---------------------------------------------------------------------------
-- 1) signal_raw — rohe Provider-Pulls vor Normalisierung
--
-- Aufbewahrt der originalen Provider-Response (JSON) für Reproduzierbarkeit
-- und Forensik. Die Normalisierungs-Pipeline liest signal_raw und schreibt
-- ein- oder mehrere Zeilen in signal_normalized. Raw-Payload kann classified
-- sein (NFD bei Defence-Feeds), daher ols_label NOT NULL.
-- ---------------------------------------------------------------------------
CREATE TABLE signal_raw (
  signal_raw_id     RAW(16)            DEFAULT SYS_GUID() NOT NULL,
  source_provider   VARCHAR2(64)       NOT NULL,                         -- 'aisstream.io', 'opensky', 'gpsjam', 'reuters', ...
  source_native_id  VARCHAR2(200),                                       -- Provider-eigene ID; nullable für anonyme Bulk-Pulls
  source_url        VARCHAR2(2000),                                      -- Origin-URL (für News / RSS / scraped sources)
  collected_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  observed_at       TIMESTAMP WITH TIME ZONE,                            -- Ereigniszeitpunkt (≠ Erfassungszeit)
  payload           JSON               NOT NULL,                         -- vollständige Provider-Response (OSON binary)
  payload_sha256    VARCHAR2(64),                                        -- Idempotenz-Hash für De-Dupe
  ols_label         NUMBER(10)         NOT NULL,
  CONSTRAINT pk_signal_raw PRIMARY KEY (signal_raw_id)
);

COMMENT ON TABLE signal_raw IS
  'UC4: rohe OSINT-Provider-Pulls vor Normalisierung. Append-only via Application-Layer. Payload ist OSON-JSON, payload_sha256 für De-Dupe.';

-- ---------------------------------------------------------------------------
-- 2) signal_normalized — entitäts-, raum-, zeitbezogene Form
--
-- Eine signal_raw-Zeile produziert n ≥ 1 signal_normalized-Zeilen (z. B. ein
-- AIS-Bulk-Pull mit 200 Schiffen). Das Embedding zu summary lebt parallel
-- in signal_vectors mit demselben event_id.
-- ---------------------------------------------------------------------------
CREATE TABLE signal_normalized (
  event_id          RAW(16)            DEFAULT SYS_GUID() NOT NULL,
  raw_signal_id     RAW(16),                                             -- nullable, falls die Quelle keine raw-Stage durchläuft
  source_type       VARCHAR2(32)       NOT NULL,                         -- 'AIS' | 'ADS_B' | 'TLE' | 'JAMMING' | 'NEWS' | 'SOCIAL' | 'SAR' | 'IMINT' | ...
  source_provider   VARCHAR2(64)       NOT NULL,
  source_native_id  VARCHAR2(200),
  collected_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  observed_at       TIMESTAMP WITH TIME ZONE,
  entity_kind       VARCHAR2(24)       NOT NULL,                         -- 'vessel' | 'aircraft' | 'satellite' | 'emitter' | 'actor' | 'location' | 'other'
  entity_ref        VARCHAR2(80),                                        -- bekannter Entity-Schlüssel (MMSI, ICAO24, NORAD-ID, ...)
  title             VARCHAR2(400)      NOT NULL,                         -- 1-Liner für UI / Tool-Calls
  summary           CLOB,                                                -- längere Zusammenfassung; Quelle für Embedding (s. signal_vectors)
  geo               SDO_GEOMETRY,                                        -- SRID 4326 (WGS84), Punkt oder Polygon
  geo_h3_r5         VARCHAR2(16),                                        -- H3-Resolution-5 für Bucket-Aggregation
  confidence        NUMBER(3,2),                                         -- [0.00, 1.00] = Quellgüte × Modellsicherheit
  attributes        JSON,                                                -- offene Attribute (Kursdaten, Schiffstyp, Frequenz, ...)
  tags              JSON,                                                -- Tag-Array, z. B. ["jamming","baltic","commercial"]
  ols_label         NUMBER(10)         NOT NULL,
  CONSTRAINT pk_signal_normalized PRIMARY KEY (event_id),
  CONSTRAINT fk_signal_normalized_raw  FOREIGN KEY (raw_signal_id)
                                       REFERENCES signal_raw (signal_raw_id),
  CONSTRAINT ck_signal_normalized_conf CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1))
);

COMMENT ON TABLE signal_normalized IS
  'UC4: normalisierte OSINT-Signale. Eine Zeile pro entität-/zeitbezogenem Ereignis. summary ist die Embedding-Quelle (siehe signal_vectors).';

-- ---------------------------------------------------------------------------
-- 3) signal_vectors — Cohere-Embeddings für Vector Search
--
-- Default-Modell ist cohere.embed-multilingual-v3.0 (volle Variante, nicht
-- light) → 1024 dim FLOAT32. Mischen verschiedener Dimensionen in einem
-- Vector-Index ist 26ai-seitig nicht erlaubt. Falls später ein zweites
-- Modell (z. B. v4 mit anderer Dimension) parallel betrieben werden soll,
-- separate Tabelle signal_vectors_v4 mit eigenem HNSW-Index anlegen.
-- ---------------------------------------------------------------------------
CREATE TABLE signal_vectors (
  event_id          RAW(16)            NOT NULL,
  embedding         VECTOR(1024, FLOAT32),
  embedding_model   VARCHAR2(64)       DEFAULT 'cohere.embed-multilingual-v3.0' NOT NULL,
  embedded_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  ols_label         NUMBER(10)         NOT NULL,
  CONSTRAINT pk_signal_vectors PRIMARY KEY (event_id),
  CONSTRAINT fk_signal_vectors_event FOREIGN KEY (event_id)
                                     REFERENCES signal_normalized (event_id)
                                     ON DELETE CASCADE
);

COMMENT ON TABLE signal_vectors IS
  'UC4: 1024-dim Cohere-Embeddings (cohere.embed-multilingual-v3.0) für Vector Search. HNSW-Index in 02_indexes.sql.';

-- ---------------------------------------------------------------------------
-- 4) entity — Akteure, Vessel, Aircraft, Satellites, Locations
--
-- Resolved-Entity-Layer. signal_normalized.entity_ref ist ein Roh-Schlüssel
-- (MMSI, ICAO24, ...); entity ist die kanonische, deduplizierte Form mit
-- Aliases und letzter bekannter Position.
-- ---------------------------------------------------------------------------
CREATE TABLE entity (
  entity_id         RAW(16)            DEFAULT SYS_GUID() NOT NULL,
  entity_kind       VARCHAR2(24)       NOT NULL,                         -- 'vessel' | 'aircraft' | 'satellite' | 'emitter' | 'actor' | 'location' | 'organisation'
  canonical_id_kind VARCHAR2(24)       NOT NULL,                         -- 'MMSI' | 'ICAO24' | 'NORAD' | 'WIKIPEDIA' | 'OPEN_CORPORATES' | 'GEONAMES' | 'INTERNAL'
  canonical_id      VARCHAR2(120)      NOT NULL,                         -- Wert in der canonical_id_kind-Domäne
  display_name      VARCHAR2(200)      NOT NULL,
  aliases           JSON,                                                -- Array alternativer Namen / IDs
  attributes        JSON,                                                -- domänenspezifisch (Schiffstyp, Tonnage, Operator, ...)
  geo               SDO_GEOMETRY,                                        -- letzte bekannte Position (SRID 4326)
  geo_h3_r5         VARCHAR2(16),
  first_seen_at     TIMESTAMP WITH TIME ZONE,
  last_seen_at      TIMESTAMP WITH TIME ZONE,
  ols_label         NUMBER(10)         NOT NULL,
  CONSTRAINT pk_entity PRIMARY KEY (entity_id),
  CONSTRAINT uq_entity_canonical UNIQUE (canonical_id_kind, canonical_id)
);

COMMENT ON TABLE entity IS
  'UC4: kanonische Entity-Form (Vessel/Aircraft/Satellite/Actor/Location). signal_normalized referenziert über (canonical_id_kind, canonical_id).';

-- ---------------------------------------------------------------------------
-- 5) entity_mention — Signal-zu-Entity-Edges für Property Graph
--
-- Many-to-many: ein Signal kann mehrere Entities erwähnen, eine Entity
-- erscheint in vielen Signals. mention_kind unterscheidet Primär-Subjekt
-- (z. B. das beobachtete Schiff) von Kontext-Erwähnungen (z. B. der Hafen).
-- Wird in 04_graph.sql als Edge im UC4-Property-Graph projiziert.
-- ---------------------------------------------------------------------------
CREATE TABLE entity_mention (
  mention_id        RAW(16)            DEFAULT SYS_GUID() NOT NULL,
  event_id          RAW(16)            NOT NULL,
  entity_id         RAW(16)            NOT NULL,
  mention_kind      VARCHAR2(16)       DEFAULT 'PRIMARY' NOT NULL,       -- 'PRIMARY' | 'SECONDARY' | 'CONTEXT'
  confidence        NUMBER(3,2),
  offset_start      NUMBER(10),                                          -- Position in summary (für News / Doc-Mentions)
  offset_end        NUMBER(10),
  detected_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  ols_label         NUMBER(10)         NOT NULL,
  CONSTRAINT pk_entity_mention PRIMARY KEY (mention_id),
  CONSTRAINT fk_em_event   FOREIGN KEY (event_id)  REFERENCES signal_normalized (event_id) ON DELETE CASCADE,
  CONSTRAINT fk_em_entity  FOREIGN KEY (entity_id) REFERENCES entity (entity_id),
  CONSTRAINT ck_em_kind    CHECK (mention_kind IN ('PRIMARY','SECONDARY','CONTEXT')),
  CONSTRAINT ck_em_conf    CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
  CONSTRAINT ck_em_offsets CHECK (offset_start IS NULL OR offset_end IS NULL OR offset_end >= offset_start)
);

COMMENT ON TABLE entity_mention IS
  'UC4: Edge-Tabelle Signal→Entity. Wird in 04_graph.sql als Property-Graph-Edge MENTIONS projiziert.';

-- ---------------------------------------------------------------------------
-- 6) ems_emitter — EW-spezifische Sensoren / Emitter
--
-- Frequenzlage, Bandbreite, Modulation. entity_id ist nullable, weil ein
-- detektierter Emitter nicht zwingend einer bekannten Plattform zugeordnet
-- ist (Anonymous Jamming Source). Sobald die Zuordnung erfolgt, wird die
-- entity_id nachträglich gesetzt.
-- ---------------------------------------------------------------------------
CREATE TABLE ems_emitter (
  emitter_id        RAW(16)            DEFAULT SYS_GUID() NOT NULL,
  emitter_kind      VARCHAR2(24)       NOT NULL,                         -- 'JAMMER' | 'RADAR' | 'COMMS' | 'SAT_TX' | 'BEACON' | 'UNKNOWN'
  frequency_mhz     NUMBER(12,4),                                        -- Trägerfrequenz, MHz
  bandwidth_mhz     NUMBER(12,4),
  power_dbm         NUMBER(6,2),                                         -- gemessene oder geschätzte EIRP, dBm
  modulation        VARCHAR2(40),                                        -- 'CW' | 'FM' | 'OFDM' | 'PULSE' | 'CHIRP' | ...
  platform_kind     VARCHAR2(24),                                        -- 'FIXED' | 'MOBILE_GROUND' | 'AIRBORNE' | 'NAVAL' | 'SPACEBORNE' | 'UNKNOWN'
  entity_id         RAW(16),                                             -- nullable: Emitter ggf. ohne bekannte Plattform-Zuordnung
  geo               SDO_GEOMETRY,                                        -- letzte bekannte Position (SRID 4326)
  geo_h3_r5         VARCHAR2(16),
  first_observed_at TIMESTAMP WITH TIME ZONE,
  last_observed_at  TIMESTAMP WITH TIME ZONE,
  ols_label         NUMBER(10)         NOT NULL,
  CONSTRAINT pk_ems_emitter PRIMARY KEY (emitter_id),
  CONSTRAINT fk_ems_emitter_entity FOREIGN KEY (entity_id) REFERENCES entity (entity_id),
  CONSTRAINT ck_ems_emitter_freq   CHECK (frequency_mhz IS NULL OR frequency_mhz > 0),
  CONSTRAINT ck_ems_emitter_bw     CHECK (bandwidth_mhz IS NULL OR bandwidth_mhz > 0)
);

COMMENT ON TABLE ems_emitter IS
  'UC4: EW-Emitter (Jammer/Radar/Comms/Sat-TX). entity_id nullable bis Plattform-Zuordnung geklärt ist.';

-- ---------------------------------------------------------------------------
-- 7) correlation_event — vom Detektor erzeugte Patterns
--
-- correlation_kind unterscheidet die Detektor-Familie. payload enthält die
-- Detail-Liste der korrelierten event_ids / entity_ids — ein dediziertes
-- Junction-Schema kommt erst, wenn die Korrelations-Pipeline gehärtet ist.
-- score ∈ [0, 1] kombiniert Confidence und Severity (vom Detektor parametriert).
-- ---------------------------------------------------------------------------
CREATE TABLE correlation_event (
  correlation_id    RAW(16)            DEFAULT SYS_GUID() NOT NULL,
  correlation_kind  VARCHAR2(40)       NOT NULL,                         -- 'CO_LOCATED' | 'TEMPORAL_CLUSTER' | 'JAMMING_OVERLAP' | 'GRAPH_CHAIN' | ...
  summary           VARCHAR2(2000),                                      -- Detektor-generierte Kurzbeschreibung
  detected_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  start_at          TIMESTAMP WITH TIME ZONE,                            -- beobachtetes Zeitfenster, Anfang
  end_at            TIMESTAMP WITH TIME ZONE,                            -- beobachtetes Zeitfenster, Ende
  geo               SDO_GEOMETRY,                                        -- Schwerpunkt oder Bounding-Box (SRID 4326)
  geo_h3_r5         VARCHAR2(16),
  score             NUMBER(3,2),                                         -- [0.00, 1.00] — Confidence × Severity
  payload           JSON,                                                -- detektor-spezifische Details, u. a. Liste korrelierter event_ids
  ols_label         NUMBER(10)         NOT NULL,
  CONSTRAINT pk_correlation_event PRIMARY KEY (correlation_id),
  CONSTRAINT ck_corr_event_score  CHECK (score IS NULL OR (score BETWEEN 0 AND 1)),
  CONSTRAINT ck_corr_event_window CHECK (start_at IS NULL OR end_at IS NULL OR end_at >= start_at)
);

COMMENT ON TABLE correlation_event IS
  'UC4: vom Detektor erzeugte Korrelations-Patterns. payload listet die korrelierten event_ids/entity_ids; dedizierte Junction folgt bei Bedarf.';

-- ---------------------------------------------------------------------------
-- 8) briefing — vom Threat-Fusion-Agent erzeugte Lagebild-Berichte
--
-- Generiert von Cohere Command R+ via OCI Generative AI Agents (siehe
-- Skill oci-agent-factory-defence). prompt_hash + model_id reichen zur
-- Reproduktion eines Briefings. review_state steuert den
-- Vier-Augen-Workflow: DRAFT → PENDING_REVIEW → APPROVED → ARCHIVED.
-- correlation_id ist nullable, weil ein Briefing auch ohne konkretes
-- Korrelations-Pattern erzeugt werden kann (z. B. periodischer Lagebericht).
-- ---------------------------------------------------------------------------
CREATE TABLE briefing (
  briefing_id       RAW(16)            DEFAULT SYS_GUID() NOT NULL,
  correlation_id    RAW(16),                                             -- nullable: standalone Briefings möglich
  title             VARCHAR2(400)      NOT NULL,
  body              CLOB               NOT NULL,                         -- vom Agent erzeugter Markdown-/Plain-Text
  model_id          VARCHAR2(200)      NOT NULL,                         -- 'cohere.command-r-plus-08-2024 v2.0' o.ä.
  prompt_hash       VARCHAR2(64),                                        -- SHA-256 des kompletten Prompts (für Repro)
  generated_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  generated_by      VARCHAR2(200)      NOT NULL,                         -- Agent-Identifier (z. B. 'threat-fusion-agent-v1')
  review_state      VARCHAR2(20)       DEFAULT 'DRAFT' NOT NULL,         -- 'DRAFT' | 'PENDING_REVIEW' | 'APPROVED' | 'ARCHIVED'
  reviewed_by       VARCHAR2(200),                                       -- User, der approved hat
  reviewed_at       TIMESTAMP WITH TIME ZONE,
  geo               SDO_GEOMETRY,                                        -- Fokusgebiet (SRID 4326), nullable
  geo_h3_r5         VARCHAR2(16),
  ols_label         NUMBER(10)         NOT NULL,
  CONSTRAINT pk_briefing PRIMARY KEY (briefing_id),
  CONSTRAINT fk_briefing_correlation FOREIGN KEY (correlation_id)
                                     REFERENCES correlation_event (correlation_id),
  CONSTRAINT ck_briefing_state       CHECK (review_state IN ('DRAFT','PENDING_REVIEW','APPROVED','ARCHIVED')),
  CONSTRAINT ck_briefing_review_pair CHECK ((reviewed_by IS NULL AND reviewed_at IS NULL)
                                            OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

COMMENT ON TABLE briefing IS
  'UC4: vom Threat-Fusion-Agent erzeugte Lagebilder. Vier-Augen-Workflow über review_state. prompt_hash+model_id reichen zur Reproduktion.';

-- ---------------------------------------------------------------------------
-- 9) audit_trail — immutable Audit-Log
--
-- Append-only-Konvention. Die Immutabilität wird in 03_security.sql per
-- OLS-Policy (READ_CONTROL ohne WRITE_CONTROL für normale User, kein
-- UPDATE/DELETE-Privileg auf der Tabelle) plus optionaler Trigger-Wachhund
-- erzwungen — DDL-seitig hier bewusst ohne Constraint, weil 26ai keinen
-- nativen "INSERT-only"-Tabellenmodifikator hat.
--
-- Pattern aus .claude/skills/oracle-26ai-schema/SKILL.md (Standard
-- Audit-Pattern). Schreibt jede Mutation auf den 8 vorausgehenden Tabellen
-- mit row_id + payload_hash + invocation_id (für Trace-Verbindung
-- zu Agent-Calls).
-- ---------------------------------------------------------------------------
CREATE TABLE audit_trail (
  audit_id          RAW(16)            DEFAULT SYS_GUID() NOT NULL,
  occurred_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  actor_type        VARCHAR2(32)       NOT NULL,                         -- 'USER' | 'AGENT' | 'SYSTEM' | 'SCHEDULER'
  actor_id          VARCHAR2(128)      NOT NULL,                         -- DB-User, Agent-OCID, Job-Name
  action            VARCHAR2(64)       NOT NULL,                         -- 'INSERT' | 'UPDATE' | 'DELETE' | 'TOOL_CALL' | 'BRIEFING_GEN' | ...
  table_name        VARCHAR2(64),                                        -- Ziel-Tabelle (NULL für tabellenfremde Aktionen)
  row_id            RAW(16),                                             -- betroffene Zeile (NULL für tabellenfremde Aktionen)
  ols_label         NUMBER(10)         NOT NULL,                         -- Label des betroffenen Datensatzes
  payload_hash      VARCHAR2(64),                                        -- SHA-256 des relevanten Payloads (bei mutating actions)
  invocation_id     VARCHAR2(128),                                       -- Trace-ID des auslösenden Tool-Calls / Requests
  CONSTRAINT pk_audit_trail PRIMARY KEY (audit_id),
  CONSTRAINT ck_audit_actor CHECK (actor_type IN ('USER','AGENT','SYSTEM','SCHEDULER'))
);

COMMENT ON TABLE audit_trail IS
  'UC4: immutable Audit-Log. Append-only-Konvention; Immutabilität wird in 03_security.sql per OLS + Privileg-Entzug erzwungen.';

-- ---------------------------------------------------------------------------
-- Sanity-Check: alle 9 Tabellen vorhanden?
-- Ein nicht-zutreffendes COUNT bricht die Migration mit klarer Meldung ab.
-- ---------------------------------------------------------------------------
DECLARE
  v_count NUMBER;
BEGIN
  SELECT COUNT(*)
    INTO v_count
    FROM all_tables
   WHERE owner = 'UC4_OSINT'
     AND table_name IN ('SIGNAL_RAW','SIGNAL_NORMALIZED','SIGNAL_VECTORS',
                        'ENTITY','ENTITY_MENTION','EMS_EMITTER',
                        'CORRELATION_EVENT','BRIEFING','AUDIT_TRAIL');
  IF v_count != 9 THEN
    RAISE_APPLICATION_ERROR(-20001,
      'UC4_OSINT/01_tables.sql: erwartete 9 Tabellen, gefunden ' || v_count);
  END IF;
END;
/

-- ===========================================================================
-- Done. Nächste Schritte:
--   * 02_indexes.sql  — B-tree (tenant/time), HNSW (signal_vectors),
--                       Spatial (geo-Spalten via MDSYS.SPATIAL_INDEX_V2,
--                       inkl. user_sdo_geom_metadata-Registrierung)
--   * 03_security.sql — OLS-Policy OLS_DEFENCE attachen, Privilegien
--                       für audit_trail (kein UPDATE/DELETE für App-User)
--   * 04_graph.sql    — UC4-Property-Graph (Entity-Knoten, MENTIONS-Edges,
--                       CORRELATED_WITH-Edges)
-- ===========================================================================
