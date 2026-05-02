-- =====================================================================
-- Sovereign Defence Intelligence Platform
-- File: 07_audit_compliance.sql
-- Purpose: Tamper-evident audit chain + TxEventQ streaming +
--          per-framework compliance tables for NIS2, DORA, GDPR,
--          VS-NfD + application of DICE_POLICY to every domain table
--          + Unified Audit Policy.
-- Target : Oracle AI Database 26ai (ATP)
-- Runs after: 01_tenants_and_security.sql and 02_..06_ (domain tables).
-- =====================================================================

SET SERVEROUTPUT ON SIZE UNLIMITED
SET DEFINE OFF
WHENEVER SQLERROR CONTINUE

-- ---------------------------------------------------------------------
-- 1. audit_events: tamper-evident hash-chained event log
-- ---------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE '
    CREATE TABLE audit_events (
      event_id        RAW(16)       DEFAULT SYS_GUID() PRIMARY KEY,
      event_time      TIMESTAMP     DEFAULT SYSTIMESTAMP,
      actor_user      VARCHAR2(200),
      actor_service   VARCHAR2(100),
      action          VARCHAR2(60),
      resource_type   VARCHAR2(60),
      resource_id     VARCHAR2(200),
      tenant_id       VARCHAR2(36)  REFERENCES tenants(tenant_id),
      ols_label       NUMBER,
      payload         JSON,
      prev_hash       RAW(32),
      row_hash        RAW(32)
    )';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -955 THEN
      DBMS_OUTPUT.PUT_LINE('audit_events exists - skip');
    ELSE
      DBMS_OUTPUT.PUT_LINE('audit_events create: '||SQLERRM);
    END IF;
END;
/

CREATE INDEX idx_audit_events_time     ON audit_events(event_time);
CREATE INDEX idx_audit_events_tenant   ON audit_events(tenant_id);
CREATE INDEX idx_audit_events_action   ON audit_events(action, resource_type);

-- Hash-chain trigger: row_hash = SHA256(prev_hash || canonical event fields)
CREATE OR REPLACE TRIGGER trg_audit_events_hash
BEFORE INSERT ON audit_events
FOR EACH ROW
DECLARE
  v_prev   RAW(32);
  v_input  RAW(32767);
  v_clob   VARCHAR2(32767);
BEGIN
  -- Look up previous hash (last inserted row by time)
  BEGIN
    SELECT row_hash INTO v_prev
      FROM (SELECT row_hash FROM audit_events ORDER BY event_time DESC, event_id DESC)
      WHERE ROWNUM = 1;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      v_prev := HEXTORAW(LPAD('0',64,'0'));
  END;

  :NEW.prev_hash := v_prev;

  v_clob :=
        RAWTOHEX(NVL(v_prev, HEXTORAW(LPAD('0',64,'0'))))
     || '|' || TO_CHAR(:NEW.event_time,'YYYY-MM-DD"T"HH24:MI:SS.FF6')
     || '|' || NVL(:NEW.actor_user,'')
     || '|' || NVL(:NEW.actor_service,'')
     || '|' || NVL(:NEW.action,'')
     || '|' || NVL(:NEW.resource_type,'')
     || '|' || NVL(:NEW.resource_id,'')
     || '|' || NVL(:NEW.tenant_id,'')
     || '|' || NVL(TO_CHAR(:NEW.ols_label),'')
     || '|' || NVL(JSON_SERIALIZE(:NEW.payload RETURNING VARCHAR2(16000)),'');

  v_input := UTL_RAW.CAST_TO_RAW(v_clob);
  :NEW.row_hash := DBMS_CRYPTO.HASH(v_input, DBMS_CRYPTO.HASH_SH256);
END;
/

-- ---------------------------------------------------------------------
-- 2. TxEventQ: COMPLIANCE_Q (sharded, JSON payload)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_AQADM.CREATE_SHARDED_QUEUE(
    queue_name         => 'COMPLIANCE_Q',
    queue_payload_type => 'JSON',
    multiple_consumers => TRUE);
  DBMS_AQADM.START_QUEUE('COMPLIANCE_Q');
  DBMS_OUTPUT.PUT_LINE('COMPLIANCE_Q created and started');
EXCEPTION
  WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('COMPLIANCE_Q skipped: '||SQLERRM);
END;
/

-- AFTER INSERT trigger: enqueue each audit event as JSON
CREATE OR REPLACE TRIGGER trg_audit_events_enqueue
AFTER INSERT ON audit_events
FOR EACH ROW
DECLARE
  v_msgid       RAW(16);
  v_enq_opts    DBMS_AQ.ENQUEUE_OPTIONS_T;
  v_msg_props   DBMS_AQ.MESSAGE_PROPERTIES_T;
  v_payload     JSON;
BEGIN
  v_payload := JSON_OBJECT(
                 'event_id'      VALUE RAWTOHEX(:NEW.event_id),
                 'event_time'    VALUE TO_CHAR(:NEW.event_time,'YYYY-MM-DD"T"HH24:MI:SS.FF6TZR'),
                 'actor_user'    VALUE :NEW.actor_user,
                 'actor_service' VALUE :NEW.actor_service,
                 'action'        VALUE :NEW.action,
                 'resource_type' VALUE :NEW.resource_type,
                 'resource_id'   VALUE :NEW.resource_id,
                 'tenant_id'     VALUE :NEW.tenant_id,
                 'ols_label'     VALUE :NEW.ols_label,
                 'prev_hash'     VALUE RAWTOHEX(:NEW.prev_hash),
                 'row_hash'      VALUE RAWTOHEX(:NEW.row_hash),
                 'payload'       VALUE :NEW.payload
                 RETURNING JSON);

  DBMS_AQ.ENQUEUE(
    queue_name         => 'COMPLIANCE_Q',
    enqueue_options    => v_enq_opts,
    message_properties => v_msg_props,
    payload            => v_payload,
    msgid              => v_msgid);
EXCEPTION
  WHEN OTHERS THEN
    -- never fail the audit insert; log and continue
    DBMS_OUTPUT.PUT_LINE('enqueue COMPLIANCE_Q failed: '||SQLERRM);
END;
/

-- ---------------------------------------------------------------------
-- 3. Per-framework compliance tables
-- ---------------------------------------------------------------------

-- NIS2 controls
BEGIN
  EXECUTE IMMEDIATE '
    CREATE TABLE nis2_controls (
      control_id            VARCHAR2(40) PRIMARY KEY,
      tenant_id             VARCHAR2(36) REFERENCES tenants(tenant_id),
      nis2_article          VARCHAR2(40) NOT NULL,
      requirement_text      VARCHAR2(4000),
      implementation_status VARCHAR2(20)
        CHECK (implementation_status IN (''PLANNED'',''IN_PROGRESS'',''IMPLEMENTED'',''VERIFIED'',''FAILED'')),
      evidence_uri          VARCHAR2(500),
      created_at            TIMESTAMP DEFAULT SYSTIMESTAMP,
      updated_at            TIMESTAMP DEFAULT SYSTIMESTAMP,
      ols_label             NUMBER
    )';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE <> -955 THEN DBMS_OUTPUT.PUT_LINE('nis2_controls: '||SQLERRM); END IF;
END;
/

-- DORA incidents (ICT-related incident register)
BEGIN
  EXECUTE IMMEDIATE '
    CREATE TABLE dora_incidents (
      incident_id       VARCHAR2(40) PRIMARY KEY,
      tenant_id         VARCHAR2(36) REFERENCES tenants(tenant_id),
      severity          VARCHAR2(10)
        CHECK (severity IN (''LOW'',''MEDIUM'',''HIGH'',''CRITICAL'')),
      reported_at       TIMESTAMP DEFAULT SYSTIMESTAMP,
      root_cause        VARCHAR2(2000),
      affected_service  VARCHAR2(200),
      rto_minutes       NUMBER,
      rpo_minutes       NUMBER,
      ols_label         NUMBER
    )';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE <> -955 THEN DBMS_OUTPUT.PUT_LINE('dora_incidents: '||SQLERRM); END IF;
END;
/

-- GDPR data-subject requests
BEGIN
  EXECUTE IMMEDIATE '
    CREATE TABLE gdpr_requests (
      request_id     VARCHAR2(40) PRIMARY KEY,
      tenant_id      VARCHAR2(36) REFERENCES tenants(tenant_id),
      subject_email  VARCHAR2(320) NOT NULL,
      request_type   VARCHAR2(20) NOT NULL
        CHECK (request_type IN (''ACCESS'',''ERASURE'',''PORTABILITY'',''RECTIFICATION'')),
      received_at    TIMESTAMP DEFAULT SYSTIMESTAMP,
      completed_at   TIMESTAMP,
      status         VARCHAR2(20)
        CHECK (status IN (''OPEN'',''IN_PROGRESS'',''COMPLETED'',''REJECTED'')),
      ols_label      NUMBER
    )';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE <> -955 THEN DBMS_OUTPUT.PUT_LINE('gdpr_requests: '||SQLERRM); END IF;
END;
/

-- VS-NfD classification markers
BEGIN
  EXECUTE IMMEDIATE '
    CREATE TABLE vsnfd_markers (
      marker_id             VARCHAR2(40) PRIMARY KEY,
      tenant_id             VARCHAR2(36) REFERENCES tenants(tenant_id),
      classification_level  VARCHAR2(20) NOT NULL
        CHECK (classification_level IN (''OFFEN'',''VS-NfD'',''VS-VERTRAULICH'',''GEHEIM'',''STRENG GEHEIM'')),
      caveat                VARCHAR2(200),
      handling_instructions VARCHAR2(2000),
      applies_to_table      VARCHAR2(128),
      applies_to_row_id     VARCHAR2(200),
      created_at            TIMESTAMP DEFAULT SYSTIMESTAMP,
      ols_label             NUMBER
    )';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE <> -955 THEN DBMS_OUTPUT.PUT_LINE('vsnfd_markers: '||SQLERRM); END IF;
END;
/

-- ---------------------------------------------------------------------
-- 4. Apply DICE_POLICY to every domain table (idempotent)
-- ---------------------------------------------------------------------
BEGIN sp_apply_dice_policy('AUDIT_EVENTS');         EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('NIS2_CONTROLS');        EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('DORA_INCIDENTS');       EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('GDPR_REQUESTS');        EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('VSNFD_MARKERS');        EXCEPTION WHEN OTHERS THEN NULL; END;
/

-- Tables from 02_geoint.sql
BEGIN sp_apply_dice_policy('SATELLITE_SCENES');     EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('SCENE_EMBEDDINGS');     EXCEPTION WHEN OTHERS THEN NULL; END;
/

-- Tables from 03_docintel.sql
BEGIN sp_apply_dice_policy('DOCUMENTS');            EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('DOCUMENT_CHUNKS');      EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('DOCUMENT_EMBEDDINGS');  EXCEPTION WHEN OTHERS THEN NULL; END;
/

-- Tables from 04_collab.sql
BEGIN sp_apply_dice_policy('COLLAB_SHARES');        EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('SHARED_ARTEFACTS');     EXCEPTION WHEN OTHERS THEN NULL; END;
/

-- Tables from 05_osint.sql
BEGIN sp_apply_dice_policy('OSINT_ENTITIES');       EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('OSINT_RELATIONSHIPS');  EXCEPTION WHEN OTHERS THEN NULL; END;
/

-- Tables from 06_supplychain.sql
BEGIN sp_apply_dice_policy('SC_NODES');             EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('SC_EDGES');             EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('SC_RISK');              EXCEPTION WHEN OTHERS THEN NULL; END;
/

-- Compliance-control tables (defined elsewhere in the 8-file set)
BEGIN sp_apply_dice_policy('COMPLIANCE_CONTROLS');  EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('COMPLIANCE_FINDINGS');  EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN sp_apply_dice_policy('COMPLIANCE_EVIDENCE');  EXCEPTION WHEN OTHERS THEN NULL; END;
/

-- ---------------------------------------------------------------------
-- 5. Unified Audit Policy for classified tables
-- ---------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE AUDIT POLICY dice_audit_pol
      ACTIONS
        SELECT ON audit_events,
        INSERT ON audit_events,
        UPDATE ON audit_events,
        DELETE ON audit_events,
        SELECT ON nis2_controls,
        INSERT ON nis2_controls,
        UPDATE ON nis2_controls,
        DELETE ON nis2_controls,
        SELECT ON dora_incidents,
        INSERT ON dora_incidents,
        UPDATE ON dora_incidents,
        DELETE ON dora_incidents,
        SELECT ON gdpr_requests,
        INSERT ON gdpr_requests,
        UPDATE ON gdpr_requests,
        DELETE ON gdpr_requests,
        SELECT ON vsnfd_markers,
        INSERT ON vsnfd_markers,
        UPDATE ON vsnfd_markers,
        DELETE ON vsnfd_markers,
        SELECT ON tenants,
        INSERT ON tenants,
        UPDATE ON tenants,
        DELETE ON tenants
      CONTAINER = CURRENT
  ]';
EXCEPTION
  WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('audit policy create skipped: '||SQLERRM);
END;
/

BEGIN
  EXECUTE IMMEDIATE 'AUDIT POLICY dice_audit_pol';
EXCEPTION
  WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('AUDIT POLICY enable skipped: '||SQLERRM);
END;
/

-- End of 07_audit_compliance.sql
