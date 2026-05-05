-- =====================================================================
-- Creates the UC10_APP database user for the Requirements Intelligence
-- bootstrap (industrial/10-requirements-intelligence/schema/0[1-5]_*.sql).
--
-- Run as ADMIN against the ATP instance:
--
--   DB_APP_PWD=$(grep ^DB_APP_PWD= .env | cut -d= -f2-)
--   sql -L ADMIN/$ADMIN_PWD@sovdef26_tp \
--       industrial/_shared/create-uc10-app-user.sql \
--       "$DB_APP_PWD"
--
-- Idempotent: if the user already exists, the password is rotated and
-- the privilege set is re-granted (no-op on existing grants).
-- =====================================================================

SET ECHO OFF
SET FEEDBACK ON
SET VERIFY OFF
WHENEVER SQLERROR EXIT FAILURE

-- &1 is the new password, passed positionally so it never lands in the
-- spool file or the SQL history.
DEFINE NEW_PWD = '&1'

DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count
    FROM dba_users
   WHERE username = 'UC10_APP';

  IF l_count = 0 THEN
    EXECUTE IMMEDIATE
      'CREATE USER UC10_APP IDENTIFIED BY "&NEW_PWD" '
      || 'DEFAULT TABLESPACE DATA '
      || 'TEMPORARY TABLESPACE TEMP '
      || 'QUOTA UNLIMITED ON DATA';
    DBMS_OUTPUT.PUT_LINE('  ok — user UC10_APP created');
  ELSE
    EXECUTE IMMEDIATE 'ALTER USER UC10_APP IDENTIFIED BY "&NEW_PWD"';
    DBMS_OUTPUT.PUT_LINE('  ok — user UC10_APP password rotated');
  END IF;
END;
/

-- Core session + DDL privileges UC10 schema files need
-- (see industrial/10-requirements-intelligence/schema/0[1-5]_*.sql).
GRANT CREATE SESSION                 TO UC10_APP;
GRANT CREATE TABLE                   TO UC10_APP;
GRANT CREATE VIEW                    TO UC10_APP;
GRANT CREATE MATERIALIZED VIEW       TO UC10_APP;
GRANT CREATE SEQUENCE                TO UC10_APP;
GRANT CREATE PROCEDURE               TO UC10_APP;
GRANT CREATE TRIGGER                 TO UC10_APP;
GRANT CREATE TYPE                    TO UC10_APP;
GRANT CREATE PROPERTY GRAPH          TO UC10_APP;
GRANT CREATE ANY CONTEXT             TO UC10_APP;

-- DBMS_CLOUD + DBMS_CLOUD_AI for external table import + Select-AI
-- (used by 02_performance.sql, 05_ai_workload.sql).
GRANT EXECUTE ON DBMS_CLOUD          TO UC10_APP;
GRANT EXECUTE ON DBMS_CLOUD_AI       TO UC10_APP;

-- VPD / row-level security for coalition isolation (UC10's whole point —
-- programs Eurofighter / FCAS must not leak rows across each other).
GRANT EXECUTE ON DBMS_RLS            TO UC10_APP;
GRANT EXECUTE ON DBMS_SESSION        TO UC10_APP;

-- AI Vector Search (HNSW) needs these in the role normally provided by
-- the DBA-managed DWROLE on Autonomous; keep the explicit grant so a
-- bare-bones ATP also works.
GRANT EXECUTE ON DBMS_VECTOR         TO UC10_APP;
GRANT EXECUTE ON DBMS_VECTOR_CHAIN   TO UC10_APP;

-- USER_POLICIES / USER_INDEXES are session-scoped data-dictionary views
-- and are readable by every user without an explicit grant. ATP-ADMIN
-- can't grant on SYS objects anyway (ORA-01031). The verification
-- script (scripts/verify-coalition-vpd.sh) introspects via these views
-- under the UC10_APP session and gets exactly the right rows.

PROMPT  ok — UC10_APP grants applied.
EXIT 0
