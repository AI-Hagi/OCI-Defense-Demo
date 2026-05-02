-- ===========================================================================
-- UC4_OSINT — Tag 7c: Correlation Detector
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1)
--
-- Geltungsbereich:
--   Stored Procedure UC4_OSINT.RUN_CORRELATION_DETECTOR scannt die letzten
--   N Stunden in signal_normalized und emittiert correlation_event-Zeilen
--   für zwei Pattern-Familien, die unser Tag-7b-Trigger als
--   "interessant" akzeptiert.
--
--   1) TEMPORAL_CLUSTER  — ≥3 Signale der GLEICHEN source_type in derselben
--                          H3-r5-Zelle innerhalb eines 60-min-Fensters.
--                          (Beispiel: 4 AIS-Reports im Hel-Hexagon.)
--
--   2) CO_LOCATED        — ≥2 VERSCHIEDENE source_types in derselben
--                          H3-r5-Zelle innerhalb eines 60-min-Fensters.
--                          (Beispiel: AIS + JAMMING + ADS_B in einer Zelle.)
--
--   JAMMING_OVERLAP und GRAPH_CHAIN sind komplexer (zeitliche Korrelation
--   über Emitter-Frequenzen bzw. Multi-Hop-Graph-Traversierung) und in
--   diesem Detektor noch nicht implementiert — die 8 Hand-crafted seeds
--   aus Tag 5 decken sie ab; ein produktionsreifer Detektor folgt bei
--   Bedarf in Tag 7d.
--
-- Idempotenz:
--   * Ein Pattern wird NICHT erneut emittiert, wenn in der gleichen
--     H3-Zelle in den letzten 12h schon eine correlation derselben Kind
--     existiert. Verhindert Duplikat-Storms in der Queue, wenn der
--     Detektor periodisch läuft.
--   * Der Tag-7b-Trigger filtert zusätzlich score >= 0.6 — der Detektor
--     emittiert nur Zeilen über dieser Schwelle.
--
-- Operator-Vorgehen:
--   * Manueller Aufruf für Demo:
--       BEGIN UC4_OSINT.RUN_CORRELATION_DETECTOR(p_window_hours => 72); END;
--   * Periodisch (Tag 7e Roadmap, nicht in dieser Migration):
--       BEGIN
--         DBMS_SCHEDULER.CREATE_JOB(
--           job_name        => 'UC4_OSINT.JOB_CORRELATION_DETECTOR',
--           job_type        => 'PLSQL_BLOCK',
--           job_action      => 'BEGIN UC4_OSINT.RUN_CORRELATION_DETECTOR; END;',
--           start_date      => SYSTIMESTAMP,
--           repeat_interval => 'FREQ=MINUTELY;INTERVAL=5',
--           enabled         => TRUE);
--       END;
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

CREATE OR REPLACE PROCEDURE UC4_OSINT.RUN_CORRELATION_DETECTOR(
  p_window_hours IN NUMBER DEFAULT 6
) AS
  v_started      TIMESTAMP WITH TIME ZONE := SYSTIMESTAMP;
  v_temporal     NUMBER := 0;
  v_colocated    NUMBER := 0;
BEGIN
  -- -------------------------------------------------------------------------
  -- TEMPORAL_CLUSTER — same source_type, same H3 cell, ≥3 in 60-min window
  -- Score: 0.6 base + 0.05 per extra event (capped at 0.95).
  -- -------------------------------------------------------------------------
  FOR rec IN (
    SELECT geo_h3_r5,
           source_type,
           COUNT(*)                       AS event_count,
           MIN(observed_at)               AS first_at,
           MAX(observed_at)               AS last_at,
           MAX(ols_label)                 AS max_label,
           AVG(sn.geo.SDO_POINT.X)        AS centroid_lon,
           AVG(sn.geo.SDO_POINT.Y)        AS centroid_lat
      FROM signal_normalized sn
     WHERE observed_at > SYSTIMESTAMP - NUMTODSINTERVAL(p_window_hours, 'HOUR')
       AND geo_h3_r5 IS NOT NULL
       AND geo IS NOT NULL
       AND ols_label <= 50
     GROUP BY geo_h3_r5, source_type
    HAVING COUNT(*) >= 3
       AND MAX(observed_at) - MIN(observed_at) <= INTERVAL '60' MINUTE
  ) LOOP
    DECLARE
      v_dup    NUMBER;
      v_new_id RAW(16);
    BEGIN
      -- Idempotency guard: skip if a TEMPORAL_CLUSTER for this cell already
      -- emitted within the last 12h.
      SELECT COUNT(*) INTO v_dup FROM correlation_event
       WHERE correlation_kind = 'TEMPORAL_CLUSTER'
         AND geo_h3_r5        = rec.geo_h3_r5
         AND detected_at      > SYSTIMESTAMP - INTERVAL '12' HOUR;
      IF v_dup > 0 THEN CONTINUE; END IF;

      INSERT INTO correlation_event (
        correlation_kind, summary, detected_at, start_at, end_at,
        geo, geo_h3_r5, score, payload, ols_label
      ) VALUES (
        'TEMPORAL_CLUSTER',
        rec.event_count||' '||rec.source_type||'-Signale in '||rec.geo_h3_r5
          ||' (<=60 min)',
        SYSTIMESTAMP,
        rec.first_at, rec.last_at,
        SDO_GEOMETRY(2001, 4326,
          SDO_POINT_TYPE(rec.centroid_lon, rec.centroid_lat, NULL), NULL, NULL),
        rec.geo_h3_r5,
        LEAST(0.95, 0.6 + (rec.event_count - 3) * 0.05),
        JSON('{"detector":"temporal_cluster_v1","source_type":"'
             ||rec.source_type||'","event_count":'||rec.event_count||'}'),
        rec.max_label)
      RETURNING correlation_id INTO v_new_id;

      -- Auto-link the contributing events via correlation_includes_event
      INSERT INTO correlation_includes_event (
        correlation_id, event_id, role, confidence, ols_label)
      SELECT v_new_id, sn.event_id, 'TRIGGER', 0.9, sn.ols_label
        FROM signal_normalized sn
       WHERE sn.geo_h3_r5    = rec.geo_h3_r5
         AND sn.source_type  = rec.source_type
         AND sn.observed_at BETWEEN rec.first_at AND rec.last_at;

      v_temporal := v_temporal + 1;
    END;
  END LOOP;

  -- -------------------------------------------------------------------------
  -- CO_LOCATED — ≥2 distinct source_types, same H3 cell, 60-min window
  -- Score: 0.6 base + 0.1 per extra source_type (capped at 0.9).
  -- -------------------------------------------------------------------------
  FOR rec IN (
    SELECT geo_h3_r5,
           COUNT(DISTINCT source_type)    AS source_type_count,
           COUNT(*)                       AS event_count,
           MIN(observed_at)               AS first_at,
           MAX(observed_at)               AS last_at,
           MAX(ols_label)                 AS max_label,
           AVG(sn.geo.SDO_POINT.X)        AS centroid_lon,
           AVG(sn.geo.SDO_POINT.Y)        AS centroid_lat,
           LISTAGG(DISTINCT source_type, ',') WITHIN GROUP (ORDER BY source_type) AS kinds
      FROM signal_normalized sn
     WHERE observed_at > SYSTIMESTAMP - NUMTODSINTERVAL(p_window_hours, 'HOUR')
       AND geo_h3_r5 IS NOT NULL
       AND geo IS NOT NULL
       AND ols_label <= 50
     GROUP BY geo_h3_r5
    HAVING COUNT(DISTINCT source_type) >= 2
       AND MAX(observed_at) - MIN(observed_at) <= INTERVAL '60' MINUTE
  ) LOOP
    DECLARE
      v_dup    NUMBER;
      v_new_id RAW(16);
    BEGIN
      SELECT COUNT(*) INTO v_dup FROM correlation_event
       WHERE correlation_kind = 'CO_LOCATED'
         AND geo_h3_r5        = rec.geo_h3_r5
         AND detected_at      > SYSTIMESTAMP - INTERVAL '12' HOUR;
      IF v_dup > 0 THEN CONTINUE; END IF;

      INSERT INTO correlation_event (
        correlation_kind, summary, detected_at, start_at, end_at,
        geo, geo_h3_r5, score, payload, ols_label
      ) VALUES (
        'CO_LOCATED',
        'Multi-Source-Cluster ('||rec.kinds||') in '||rec.geo_h3_r5
          ||' (<=60 min)',
        SYSTIMESTAMP,
        rec.first_at, rec.last_at,
        SDO_GEOMETRY(2001, 4326,
          SDO_POINT_TYPE(rec.centroid_lon, rec.centroid_lat, NULL), NULL, NULL),
        rec.geo_h3_r5,
        LEAST(0.9, 0.6 + (rec.source_type_count - 2) * 0.1),
        JSON('{"detector":"co_located_v1","source_types":"'||rec.kinds
             ||'","source_type_count":'||rec.source_type_count
             ||',"event_count":'||rec.event_count||'}'),
        rec.max_label)
      RETURNING correlation_id INTO v_new_id;

      -- Auto-link contributing events
      INSERT INTO correlation_includes_event (
        correlation_id, event_id, role, confidence, ols_label)
      SELECT v_new_id, sn.event_id,
             CASE WHEN ROWNUM <= 1 THEN 'TRIGGER' ELSE 'CONTEXT' END,
             0.85, sn.ols_label
        FROM signal_normalized sn
       WHERE sn.geo_h3_r5  = rec.geo_h3_r5
         AND sn.observed_at BETWEEN rec.first_at AND rec.last_at;

      v_colocated := v_colocated + 1;
    END;
  END LOOP;

  COMMIT;

  DBMS_OUTPUT.PUT_LINE(
    'RUN_CORRELATION_DETECTOR window='||p_window_hours||'h: '
    ||'temporal_clusters='||v_temporal||', co_located='||v_colocated
    ||', took='||ROUND(EXTRACT(SECOND FROM (SYSTIMESTAMP - v_started)) * 1000, 0)
    ||' ms');
END;
/
SHOW ERRORS PROCEDURE UC4_OSINT.RUN_CORRELATION_DETECTOR

GRANT EXECUTE ON UC4_OSINT.RUN_CORRELATION_DETECTOR TO PUBLIC;

-- ---------------------------------------------------------------------------
-- Tail-sanity: run the detector on the existing demo seed (window=72h
-- should comfortably cover the seeded story signals from Tag 5).
-- ---------------------------------------------------------------------------
DECLARE
  v_corr_before  NUMBER;
  v_corr_after   NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_corr_before FROM uc4_osint.correlation_event;

  UC4_OSINT.RUN_CORRELATION_DETECTOR(p_window_hours => 72);

  SELECT COUNT(*) INTO v_corr_after FROM uc4_osint.correlation_event;
  DBMS_OUTPUT.PUT_LINE('correlation_event rows: '||v_corr_before||' -> '||v_corr_after);

  IF v_corr_after < v_corr_before THEN
    RAISE_APPLICATION_ERROR(-20009,
      '07_correlation_detector.sql: row count went DOWN after detector run.');
  END IF;
END;
/

-- ===========================================================================
-- Done. Folge:
--   * Tag 7d (optional): JAMMING_OVERLAP + GRAPH_CHAIN-Detektoren auf
--     Basis der ems_emitter-Tabelle bzw. Property Graph.
--   * Tag 7e (optional): DBMS_SCHEDULER-Job, der den Detektor periodisch
--     anstößt.
--   * Sobald Cohere-Cluster + ORDS-OAuth entsperrt sind:
--       agent.yaml: trigger.type 'http' → 'txeventq'
--       Erste vom Detektor erzeugte Korrelation triggert agent autonom.
-- ===========================================================================
