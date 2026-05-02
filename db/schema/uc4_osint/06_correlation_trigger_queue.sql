-- ===========================================================================
-- UC4_OSINT — Tag 7b: TxEventQ-Trigger für Threat-Fusion-Agent
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1)
--
-- Geltungsbereich:
--   1) UC4_OSINT.CORRELATION_TRIGGER  TxEventQ (JSON payload, multi-consumer)
--   2) UC4_OSINT.CORRELATION_TRIGGER_DLQ Dead-Letter-Queue (after 5 retries)
--   3) Subscriber 'threat_fusion_consumer' für den Tag-7-Agenten
--   4) AFTER INSERT-Trigger auf correlation_event, der bei
--      "interessanten" Korrelationen ein JSON-Event ans Queue
--      schreibt (gleiche Transaktion wie der INSERT — atomar).
--
--   Filter im Trigger:
--     correlation_kind IN ('JAMMING_OVERLAP','GRAPH_CHAIN',
--                           'CO_LOCATED','TEMPORAL_CLUSTER')
--     AND ols_label <= 50            -- Demo-Cap NFD
--     AND score >= 0.6               -- nur belastbare Korrelationen
--
--   Payload-Contract (siehe oci-agent-factory-defence/txeventq-triggers.md):
--     event_type        VARCHAR2 ('correlation_detected')
--     trigger_id        UUID hex
--     emitted_at        ISO8601 UTC
--     ols_label         NUMBER (10/30/50)
--     compartments      JSON-Array (['EW'] | ['OSINT'])
--     correlation_id    UUID hex
--     composite_score   NUMBER
--     pattern_name      VARCHAR2 (= correlation_kind)
--     geo               GeoJSON (von SDO_UTIL.TO_GEOJSON)
--
-- Voraussetzungen:
--   * 01_tables.sql .. 05_ords_tools.sql appliziert.
--   * ADMIN-Connection (DBMS_AQADM braucht AQ_ADMINISTRATOR_ROLE,
--     ADMIN hat das auf ATP).
--   * Queues werden im UC4_OSINT-Schema erstellt (qualified queue_name),
--     damit UC4_OSINT.AFTER-INSERT-Trigger ohne explizite Grants
--     ENQUEUE rufen kann.
--
-- Idempotenz:
--   * Queue creation: swallow ORA-24006 (queue exists) / ORA-24018
--     (subscriber exists)
--   * START_QUEUE: swallow ORA-24010 (queue not stopped) and ORA-24017
--     (already started).
--   * Trigger: CREATE OR REPLACE — always idempotent.
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

-- ---------------------------------------------------------------------------
-- (1) CORRELATION_TRIGGER queue
-- ---------------------------------------------------------------------------
BEGIN
  DBMS_AQADM.CREATE_TRANSACTIONAL_EVENT_QUEUE(
    queue_name         => 'UC4_OSINT.CORRELATION_TRIGGER',
    queue_payload_type => 'JSON',
    multiple_consumers => TRUE,
    max_retries        => 5);
  DBMS_OUTPUT.PUT_LINE('Queue UC4_OSINT.CORRELATION_TRIGGER created.');
EXCEPTION
  WHEN OTHERS THEN
    -- ORA-24006 = queue table already exists; ORA-24001 = queue already exists
    IF SQLCODE NOT IN (-24001, -24006) THEN RAISE; END IF;
    DBMS_OUTPUT.PUT_LINE('Queue CORRELATION_TRIGGER already exists — skipping.');
END;
/

-- ---------------------------------------------------------------------------
-- (2) Dead-Letter Queue
-- ---------------------------------------------------------------------------
BEGIN
  DBMS_AQADM.CREATE_TRANSACTIONAL_EVENT_QUEUE(
    queue_name         => 'UC4_OSINT.CORRELATION_TRIGGER_DLQ',
    queue_payload_type => 'JSON',
    multiple_consumers => TRUE,
    max_retries        => 0);
  DBMS_OUTPUT.PUT_LINE('Queue UC4_OSINT.CORRELATION_TRIGGER_DLQ created.');
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-24001, -24006) THEN RAISE; END IF;
    DBMS_OUTPUT.PUT_LINE('Queue CORRELATION_TRIGGER_DLQ already exists — skipping.');
END;
/

-- ---------------------------------------------------------------------------
-- (3) Start both queues
-- ---------------------------------------------------------------------------
BEGIN
  DBMS_AQADM.START_QUEUE(queue_name => 'UC4_OSINT.CORRELATION_TRIGGER');
  DBMS_OUTPUT.PUT_LINE('Queue CORRELATION_TRIGGER started.');
EXCEPTION
  WHEN OTHERS THEN
    -- Already started codes: ORA-24010, -24017
    IF SQLCODE NOT IN (-24010, -24017, -24210) THEN RAISE; END IF;
    DBMS_OUTPUT.PUT_LINE('Queue CORRELATION_TRIGGER already running.');
END;
/

BEGIN
  DBMS_AQADM.START_QUEUE(queue_name => 'UC4_OSINT.CORRELATION_TRIGGER_DLQ');
  DBMS_OUTPUT.PUT_LINE('Queue CORRELATION_TRIGGER_DLQ started.');
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-24010, -24017, -24210) THEN RAISE; END IF;
    DBMS_OUTPUT.PUT_LINE('Queue CORRELATION_TRIGGER_DLQ already running.');
END;
/

-- ---------------------------------------------------------------------------
-- (4) Subscriber for the Threat-Fusion-Agent
-- ---------------------------------------------------------------------------
BEGIN
  DBMS_AQADM.ADD_SUBSCRIBER(
    queue_name => 'UC4_OSINT.CORRELATION_TRIGGER',
    subscriber => SYS.AQ$_AGENT('threat_fusion_consumer', NULL, NULL));
  DBMS_OUTPUT.PUT_LINE('Subscriber threat_fusion_consumer added.');
EXCEPTION
  WHEN OTHERS THEN
    -- ORA-24033 = no recipients; ORA-24034 = subscriber already exists
    IF SQLCODE NOT IN (-24033, -24034) THEN RAISE; END IF;
    DBMS_OUTPUT.PUT_LINE('Subscriber already registered — skipping.');
END;
/

-- ---------------------------------------------------------------------------
-- (4b) Grants — UC4_OSINT needs EXECUTE on DBMS_AQ for the trigger body
--      and ENQUEUE privilege on the queue itself.  ADMIN owns AQ, so the
--      grants happen here once.
-- ---------------------------------------------------------------------------
GRANT EXECUTE ON DBMS_AQ TO UC4_OSINT;

BEGIN
  DBMS_AQADM.GRANT_QUEUE_PRIVILEGE(
    privilege    => 'ENQUEUE',
    queue_name   => 'UC4_OSINT.CORRELATION_TRIGGER',
    grantee      => 'UC4_OSINT',
    grant_option => FALSE);
EXCEPTION WHEN OTHERS THEN
  -- ORA-01932 / -24055 = grant already in place
  IF SQLCODE NOT IN (-1932, -24055) THEN RAISE; END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (5) AFTER INSERT trigger on correlation_event
--
-- Enqueues a standardised JSON event for every NEW correlation that:
--   * has correlation_kind in our supported set
--   * is at or below the demo-cap (NFD = 50)
--   * has a score ≥ 0.6 (skip noise / low-confidence detections)
--
-- The enqueue runs INSIDE the same transaction as the INSERT — if the
-- insert rolls back, the enqueue does too. No orphan triggers, no
-- duplicate notifications.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TRIGGER UC4_OSINT.correlation_event_after_insert
AFTER INSERT ON UC4_OSINT.correlation_event
FOR EACH ROW
DECLARE
  v_compartments  VARCHAR2(80);
  v_geo_geojson   CLOB;
  v_payload       JSON;
  v_payload_str   CLOB;
  v_msgid         RAW(16);
  v_props         DBMS_AQ.MESSAGE_PROPERTIES_T := DBMS_AQ.MESSAGE_PROPERTIES_T();
  v_options       DBMS_AQ.ENQUEUE_OPTIONS_T   := DBMS_AQ.ENQUEUE_OPTIONS_T();
BEGIN
  -- Filter: only "interesting" correlations get an agent invocation.
  IF :NEW.correlation_kind NOT IN (
       'JAMMING_OVERLAP','GRAPH_CHAIN','CO_LOCATED','TEMPORAL_CLUSTER')
     OR :NEW.ols_label > 50              -- demo cap NFD
     OR :NEW.score IS NULL OR :NEW.score < 0.6
  THEN
    RETURN;
  END IF;

  -- Compartment hint for the agent (used in the audit chain).
  v_compartments := CASE :NEW.correlation_kind
                      WHEN 'JAMMING_OVERLAP' THEN '["EW"]'
                      ELSE '["OSINT"]'
                    END;

  -- GeoJSON of the correlation centroid (NULL-safe).
  IF :NEW.geo IS NOT NULL THEN
    v_geo_geojson := SDO_UTIL.TO_GEOJSON(:NEW.geo);
  END IF;

  -- Build the standardised payload per
  -- oci-agent-factory-defence/references/txeventq-triggers.md
  v_payload_str :=
    '{'
    ||'"event_type":"correlation_detected"'
    ||',"trigger_id":"'        ||RAWTOHEX(SYS_GUID())                                    ||'"'
    ||',"emitted_at":"'        ||TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC',
                                          'YYYY-MM-DD"T"HH24:MI:SS"Z"')                  ||'"'
    ||',"ols_label":'          ||:NEW.ols_label
    ||',"compartments":'       ||v_compartments
    ||',"correlation_id":"'    ||RAWTOHEX(:NEW.correlation_id)                           ||'"'
    ||',"composite_score":'    ||TO_CHAR(:NEW.score, 'FM0.99')
    ||',"pattern_name":"'      ||:NEW.correlation_kind                                   ||'"'
    ||',"geo_h3_r5":'          ||CASE WHEN :NEW.geo_h3_r5 IS NULL THEN 'null'
                                       ELSE '"'||:NEW.geo_h3_r5||'"' END
    ||CASE WHEN v_geo_geojson IS NULL THEN ''
           ELSE ',"geo":'||v_geo_geojson END
    ||'}';
  v_payload := JSON(v_payload_str);

  DBMS_AQ.ENQUEUE(
    queue_name         => 'UC4_OSINT.CORRELATION_TRIGGER',
    enqueue_options    => v_options,
    message_properties => v_props,
    payload            => v_payload,
    msgid              => v_msgid);
END;
/

-- ---------------------------------------------------------------------------
-- (6) Tail-Sanity: trigger fires on a synthetic correlation, message
--     visible to the threat_fusion_consumer subscriber.
-- ---------------------------------------------------------------------------
DECLARE
  v_corr_id     RAW(16);
  v_msgid       RAW(16);
  v_dq_options  DBMS_AQ.DEQUEUE_OPTIONS_T := DBMS_AQ.DEQUEUE_OPTIONS_T();
  v_props       DBMS_AQ.MESSAGE_PROPERTIES_T;
  v_payload     JSON;
  v_payload_str VARCHAR2(4000);
  v_pattern     VARCHAR2(40);
BEGIN
  -- Insert a deliberately-flagged correlation so the trigger fires.
  INSERT INTO UC4_OSINT.correlation_event(
    correlation_kind, summary, detected_at, start_at, end_at,
    geo_h3_r5, score, payload, ols_label
  ) VALUES (
    'JAMMING_OVERLAP',
    '[probe] tail-sanity test — to be deleted',
    SYSTIMESTAMP, SYSTIMESTAMP - INTERVAL '5' MINUTE, SYSTIMESTAMP,
    'r5/probe', 0.99,
    JSON('{"probe":"06_correlation_trigger_queue.sql"}'),
    50)
  RETURNING correlation_id INTO v_corr_id;
  COMMIT;

  -- Dequeue with a 10-second timeout
  v_dq_options.consumer_name := 'threat_fusion_consumer';
  v_dq_options.wait          := 10;
  v_dq_options.navigation    := DBMS_AQ.FIRST_MESSAGE;

  BEGIN
    DBMS_AQ.DEQUEUE(
      queue_name         => 'UC4_OSINT.CORRELATION_TRIGGER',
      dequeue_options    => v_dq_options,
      message_properties => v_props,
      payload            => v_payload,
      msgid              => v_msgid);
    -- Convert JSON → VARCHAR2 for inspection
    SELECT JSON_SERIALIZE(v_payload RETURNING VARCHAR2(4000))
      INTO v_payload_str FROM dual;
    v_pattern := JSON_VALUE(v_payload_str, '$.pattern_name');
    DBMS_OUTPUT.PUT_LINE('Probe message dequeued — pattern_name='||v_pattern);
    IF v_pattern != 'JAMMING_OVERLAP' THEN
      RAISE_APPLICATION_ERROR(-20008,
        '06_correlation_trigger_queue.sql: probe payload mismatch — '
        ||'erwartet JAMMING_OVERLAP, gefunden '||v_pattern);
    END IF;
    COMMIT;
  EXCEPTION
    WHEN OTHERS THEN
      IF SQLCODE = -25228 THEN  -- ORA-25228 = dequeue timeout (no message)
        RAISE_APPLICATION_ERROR(-20008,
          '06_correlation_trigger_queue.sql: trigger fired aber kein Message '
          ||'in CORRELATION_TRIGGER innerhalb 10s sichtbar.');
      ELSE
        RAISE;
      END IF;
  END;

  -- Cleanup the probe correlation
  DELETE FROM UC4_OSINT.correlation_event WHERE correlation_id = v_corr_id;
  COMMIT;

  DBMS_OUTPUT.PUT_LINE(
    '06_correlation_trigger_queue.sql OK: queue + trigger live, '
    ||'enqueue/dequeue roundtrip green.');
END;
/

-- ===========================================================================
-- Done. Folge:
--   * Threat-Fusion-Agent (Tag 7) trigger.type von 'http' auf 'txeventq'
--     umstellen, sobald Cohere-Cluster + OAuth2 entsperrt sind.
--   * Optional Tag 8: Frontend, das via SSE/WebSocket die Briefings
--     beobachtet, die der Agent nach jedem korrelations-getriebenen Run
--     in UC4_OSINT.briefing schreibt.
-- ===========================================================================
