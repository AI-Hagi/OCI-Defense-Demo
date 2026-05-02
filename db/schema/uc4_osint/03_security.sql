-- ===========================================================================
-- UC4_OSINT — Tag 3: audit_trail Privilege Lockdown
-- (OLS_DEFENCE Policy-Attachment ist auf dieser ATP-Shape geblockt — siehe
--  Block "BLOCKER" unten. Dieser File implementiert nur den Teil, der OHNE
--  OLS-Engine-Admin funktioniert: das audit_trail-Append-Only-Privileg-Modell.)
--
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1, oci-defence-demo Compartment)
--
-- ===========================================================================
-- BLOCKER — OLS_DEFENCE-Policy nicht attached
-- ===========================================================================
-- Pre-flight-Probe (zum Zeitpunkt dieser Migration):
--   * v$option(Oracle Label Security) = TRUE  → Engine installiert
--   * dba_role_privs: ADMIN besitzt LBAC_DBA mit DEFAULT_ROLE=YES, ADMIN_OPTION=YES
--   * SA_SYSDBA-Package: VALID, alle Procs sichtbar
--
-- Dennoch scheitert SA_SYSDBA.CREATE_POLICY mit:
--
--   ORA-42911: cannot administer Oracle Label Security policy
--   at LBACSYS.LBAC_LGSTNDBY_UTIL line 118
--   at LBACSYS.SA_SYSDBA line 23
--
-- Ursache: ATP-Shared betreibt OLS im Customer-non-administrable-Mode.
-- Die OLS-Engine ist aktiv (Reads / Filtering funktionieren, sobald
-- Policies da sind), aber CREATE_POLICY / APPLY_TABLE_POLICY sind durch
-- den Cloud-Control-Plane gegated. Workarounds:
--
--   (A) ATP-Dedicated migrieren — volle OLS-Admin-Rechte
--   (B) Oracle-SR aufmachen, "Enable OLS administration on ATP-Shared"
--       für die Tenancy oci-defence-demo aktivieren lassen
--   (C) App-Level-Filtering statt OLS — ORDS/FastAPI-Handler vergleichen
--       session_label_cap gegen row.ols_label manuell. Verliert defense-
--       in-depth (DBA-bypass möglich), funktioniert aber heute.
--
-- Status: bis (A) oder (B) gelöst sind, bleiben die ols_label-Spalten
-- gefüllt (Application-Layer setzt sie weiterhin), aber NICHT OLS-
-- gefiltert. Audit-Reports / Compliance-Tests müssen das Gap zeigen.
-- TODO im Tracker: ADR-OLS-Mode + SR mit Oracle.
-- ===========================================================================
--
-- Geltungsbereich dieses Files (was tatsächlich passiert):
--   * Audit-Trail-Append-Only-Modell auf Privilegienebene
--       - CREATE ROLE uc4_audit_appender
--       - GRANT INSERT + SELECT auf UC4_OSINT.AUDIT_TRAIL an die Rolle
--       - explizit KEINE UPDATE/DELETE/ALTER-Grants — Append-Only
--       - REVOKE jeglicher PUBLIC-Berechtigungen auf audit_trail
--       - defensive REVOKE UPDATE/DELETE auf der Rolle, falls Vorrun
--         sie versehentlich gesetzt hatte
--
-- Was NICHT passiert (auf später verschoben):
--   * OLS_DEFENCE Policy + Levels + Compartments  → siehe BLOCKER oben
--   * APPLY_TABLE_POLICY auf die 9 UC4-Tabellen   → siehe BLOCKER oben
--   * Database-Vault-Realm UC4_AUDIT_REALM (Schema-Owner-Lockdown) —
--     gehört in zentrale security-bootstrap-Datei, nicht UC-Migration
--   * Per-Tenant-User-Provisioning + SET_USER_LABELS — kommt mit (A)/(B)
--
-- Voraussetzungen:
--   * 00_create_schema_owner.sql, 01_tables.sql, 02_indexes.sql wurden
--     bereits applied.
--   * Connection als ADMIN (CREATE ROLE, REVOKE on UC4_OSINT-Tabellen).
--
-- Idempotenz:
--   * CREATE ROLE in BEGIN..EXCEPTION — ORA-1921/955 swallowed
--   * GRANT idempotent (zweiter Run verändert nichts)
--   * REVOKE in BEGIN..EXCEPTION — ORA-1927/4042 swallowed (nichts zu revoken)
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON

-- ---------------------------------------------------------------------------
-- (1) Role anlegen (idempotent)
-- ---------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE 'CREATE ROLE uc4_audit_appender';
  DBMS_OUTPUT.PUT_LINE('Role UC4_AUDIT_APPENDER created.');
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE IN (-1921, -955) THEN
      DBMS_OUTPUT.PUT_LINE('Role UC4_AUDIT_APPENDER already exists.');
    ELSE
      RAISE;
    END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (2) Genau zwei Privilegien granted: INSERT + SELECT auf audit_trail
--
-- INSERT — agents/services schreiben Audit-Zeilen (jede Mutation, jeder
--          tool_call, jeder map_action lt. CLAUDE.md "Audit-Row für
--          alles Externe").
-- SELECT — Compliance-Reports lesen die Trail (UC6 nutzt diesen Pfad).
--
-- Bewusst nicht granted: UPDATE, DELETE, ALTER, INDEX, REFERENCES,
-- DEBUG, FLASHBACK. Ein Träger der Rolle kann bestehende Audit-Zeilen
-- weder ändern noch löschen — Append-Only ist auf Privilegienebene
-- erzwungen, nicht nur auf Tooling-Konvention.
-- ---------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE 'GRANT INSERT ON uc4_osint.audit_trail TO uc4_audit_appender';
  EXECUTE IMMEDIATE 'GRANT SELECT ON uc4_osint.audit_trail TO uc4_audit_appender';
  DBMS_OUTPUT.PUT_LINE('UC4_AUDIT_APPENDER: INSERT+SELECT on UC4_OSINT.AUDIT_TRAIL granted.');
END;
/

-- ---------------------------------------------------------------------------
-- (3) Defensive REVOKEs — falls ein vorheriger Run die Rolle anders
--      konfiguriert hatte. Idempotent (ORA-1927/4042 swallowed).
-- ---------------------------------------------------------------------------
BEGIN EXECUTE IMMEDIATE 'REVOKE UPDATE     ON uc4_osint.audit_trail FROM uc4_audit_appender';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1927,-4042) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'REVOKE DELETE     ON uc4_osint.audit_trail FROM uc4_audit_appender';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1927,-4042) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'REVOKE ALTER      ON uc4_osint.audit_trail FROM uc4_audit_appender';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1927,-4042) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'REVOKE INDEX      ON uc4_osint.audit_trail FROM uc4_audit_appender';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1927,-4042) THEN RAISE; END IF; END;
/
BEGIN EXECUTE IMMEDIATE 'REVOKE REFERENCES ON uc4_osint.audit_trail FROM uc4_audit_appender';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1927,-4042) THEN RAISE; END IF; END;
/

-- ---------------------------------------------------------------------------
-- (4) PUBLIC darf gar nichts auf audit_trail
--
-- Schließt die Lücke, falls jemand jemals 'GRANT SELECT ... TO PUBLIC'
-- gemacht hat. Idempotent (ORA-1927/4042 falls PUBLIC eh nichts hatte).
-- ---------------------------------------------------------------------------
BEGIN EXECUTE IMMEDIATE 'REVOKE ALL ON uc4_osint.audit_trail FROM PUBLIC';
EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-1927,-4042) THEN RAISE; END IF; END;
/

-- ---------------------------------------------------------------------------
-- Tail-Sanity: prüfen, dass die Rolle existiert und genau die zwei
-- erlaubten Privilegien (INSERT+SELECT) auf audit_trail hat — und sonst
-- nichts auf dieser Tabelle.
-- ---------------------------------------------------------------------------
DECLARE
  v_role_count NUMBER;
  v_allowed    NUMBER;  -- INSERT + SELECT
  v_forbidden  NUMBER;  -- UPDATE/DELETE/ALTER/INDEX/REFERENCES
BEGIN
  SELECT COUNT(*) INTO v_role_count
    FROM dba_roles WHERE role = 'UC4_AUDIT_APPENDER';
  IF v_role_count != 1 THEN
    RAISE_APPLICATION_ERROR(-20003,
      '03_security.sql: Rolle UC4_AUDIT_APPENDER fehlt (gefunden '||v_role_count||').');
  END IF;

  SELECT COUNT(*) INTO v_allowed
    FROM dba_tab_privs
   WHERE grantee     = 'UC4_AUDIT_APPENDER'
     AND owner       = 'UC4_OSINT'
     AND table_name  = 'AUDIT_TRAIL'
     AND privilege   IN ('INSERT','SELECT');
  IF v_allowed != 2 THEN
    RAISE_APPLICATION_ERROR(-20003,
      '03_security.sql: erwartete 2 erlaubte Privilegien (INSERT+SELECT) '
      ||'auf UC4_AUDIT_APPENDER, gefunden '||v_allowed||'.');
  END IF;

  SELECT COUNT(*) INTO v_forbidden
    FROM dba_tab_privs
   WHERE grantee     = 'UC4_AUDIT_APPENDER'
     AND owner       = 'UC4_OSINT'
     AND table_name  = 'AUDIT_TRAIL'
     AND privilege   IN ('UPDATE','DELETE','ALTER','INDEX','REFERENCES');
  IF v_forbidden != 0 THEN
    RAISE_APPLICATION_ERROR(-20003,
      '03_security.sql: UC4_AUDIT_APPENDER hat verbotene Privilegien — '
      ||v_forbidden||' Treffer auf UPDATE/DELETE/ALTER/INDEX/REFERENCES.');
  END IF;

  DBMS_OUTPUT.PUT_LINE(
    '03_security.sql OK: role uc4_audit_appender = INSERT+SELECT only on '
    ||'UC4_OSINT.AUDIT_TRAIL. OLS attachment SKIPPED (see BLOCKER header).');
END;
/

-- ===========================================================================
-- Done. Folge-Schritte:
--   * UC4_OSINT-OLS-Unblocking — Oracle-SR oder ATP-Dedicated-Migration.
--     Nach Unblock: ein neuer File 03b_ols_attach.sql mit der entfernten
--     SA_SYSDBA/SA_POLICY_ADMIN-Sequenz. Die Privilege-Lockdown-Logik
--     hier bleibt unabhängig stabil.
--   * 04_graph.sql — Property Graph (SQL/PGQ).
-- ===========================================================================
