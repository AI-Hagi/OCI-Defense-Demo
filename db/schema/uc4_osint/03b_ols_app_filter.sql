-- ===========================================================================
-- UC4_OSINT — Tag 3 (Erweiterung): App-Level OLS-Filter-Infrastruktur
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1)
--
-- Kontext (siehe 03_security.sql Header für die volle Erklärung):
--   ATP-Shared blockiert SA_SYSDBA.CREATE_POLICY mit ORA-42911. Native
--   Oracle Label Security ist somit nicht durchsetzbar. Wir ersetzen
--   die zeilen-basierte Filterung defensiv im Application Layer:
--     * ols_label-Spalten sind weiter NOT NULL und werden vom Ingest
--       befüllt (das ändert sich gegenüber dem OLS-Plan nicht).
--     * Jede Lese-Query trägt eine zusätzliche WHERE-Klausel
--       "AND ols_label <= UC4_OSINT.label_cap()".
--     * Der Cap-Wert kommt aus einer Application-Context-Variable, die
--       der Request-Pre-Handler (ORDS) bzw. die FastAPI-Dependency
--       beim Session-Acquire setzt.
--
-- Was dieser File anlegt:
--   1) Application-Context-Namespace UC4_OSINT_OLS_CTX (System-Operation,
--      muss als ADMIN gemacht werden — daher dieser File läuft als ADMIN).
--   2) Trusted Package UC4_OSINT.OLS_CTX_PKG mit set/clear/get-Procs;
--      DBMS_SESSION.SET_CONTEXT akzeptiert Writes nur aus diesem Package.
--   3) Stand-alone Function UC4_OSINT.LABEL_CAP() — komfortable Ein-Punkt-
--      Lookup-Funktion für WHERE-Klauseln, mit Fallback 10 (OFFEN) wenn
--      keine Session-Variable gesetzt ist (fail-safe).
--   4) EXECUTE-Grants:
--        * UC4_OSINT.LABEL_CAP() → PUBLIC (read-only, harmlos)
--        * UC4_OSINT.OLS_CTX_PKG → UC4_AUDIT_APPENDER (für Service-Roles
--          später — Pattern etablieren, auch wenn die Rolle heute primär
--          für audit_trail-Writes da ist)
--
-- Threat-Model-Lücken (für /docs/audits dokumentiert):
--   * DBA mit SELECT-Privileg kann WHERE-Klausel weglassen → bypass.
--   * Service-Account, der die Session-Context-Variable nicht setzt,
--     bekommt fail-safe Cap = OFFEN(10) und sieht nichts höheres
--     → kein Leak, aber unbrauchbares Lesergebnis (gewollt: lieber
--     leeres Ergebnis als classified-leak).
--   * Bösartiger Service-Code könnte SET_LABEL_CAP(50) hardcoden
--     unabhängig vom Header → Mitigation: Code-Review + Audit-Log
--     korreliert auf Tool-Call-Trace-IDs.
--
-- Roll-forward-Pfad: sobald Oracle SR den OLS-Admin auf ATP-Shared
-- freischaltet (oder Migration zu ATP-Dedicated erfolgt), wird ein
-- 03c_ols_native.sql geschrieben, der zusätzlich SA_SYSDBA-Setup +
-- APPLY_TABLE_POLICY erledigt. Die hier angelegte App-Layer-Filterung
-- bleibt als Defense-In-Depth aktiv (zwei voneinander unabhängige
-- Filter-Mechanismen — verstärkt sich gegenseitig).
--
-- Idempotenz: alle CREATE-Statements mit OR REPLACE bzw. EXCEPTION-
-- swallowing für ORA-955 / ORA-1031 falls schon vorhanden.
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON

-- ---------------------------------------------------------------------------
-- (1) Application Context Namespace
--
-- "USING UC4_OSINT.OLS_CTX_PKG" macht dieses Package zum einzigen
-- vertrauenswürdigen Schreiber für die Context-Attribute. Andere Sessions
-- können nur READ via SYS_CONTEXT() — kein Write ohne den Package-Pfad.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE CONTEXT UC4_OSINT_OLS_CTX USING UC4_OSINT.OLS_CTX_PKG;

-- ---------------------------------------------------------------------------
-- (2) Trusted Package — set/clear/get
--
-- Schema-qualifiziert (UC4_OSINT.) damit ADMIN den Code in der UC4_OSINT-
-- Domäne anlegt, ohne CURRENT_SCHEMA umstellen zu müssen.
--
-- set_label_cap clampt:
--   * NULL → 10 (OFFEN, fail-safe)
--   * < 10 → 10
--   * > 50 → 50 (Demo-Hard-Cap NFD; GEHEIM ist out of scope)
--   * Werte außerhalb {10, 30, 50} → 10 (defensiv, kein versteckter
--     Range-Drift bei Roundtrip-Bugs)
--
-- AUTHID DEFINER — der Aufrufer braucht EXECUTE auf das Package; die
-- DBMS_SESSION.SET_CONTEXT-Berechtigung ist beim Definer (UC4_OSINT)
-- nötig, was DWROLE liefert.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PACKAGE UC4_OSINT.ols_ctx_pkg AUTHID DEFINER AS
  -- Setzt die Session-weite Label-Obergrenze. Wird vom Pre-Handler
  -- (ORDS) bzw. von der FastAPI-Dependency direkt nach Connection-
  -- Acquire aufgerufen.
  PROCEDURE set_label_cap(p_cap IN NUMBER);

  -- Hebt die Cap auf — Session-Acquire/Release-Lifecycle-Hilfe.
  -- Nach clear_label_cap() liefert label_cap() wieder 10 (Fallback).
  PROCEDURE clear_label_cap;

  -- Konvenienz-Read für PL/SQL-Kontexte (außerhalb von WHERE-Klauseln).
  -- WHERE-Klauseln nutzen die Stand-alone-Function LABEL_CAP() unten,
  -- weil Stand-alone-Functions im SQL-Optimizer effizienter sind.
  FUNCTION  get_label_cap RETURN NUMBER;
END ols_ctx_pkg;
/

CREATE OR REPLACE PACKAGE BODY UC4_OSINT.ols_ctx_pkg AS

  -- Demo-konforme Cap-Stufen — deckungsgleich mit der OLS-Levels-Doku.
  c_offen   CONSTANT NUMBER := 10;
  c_intern  CONSTANT NUMBER := 30;
  c_nfd     CONSTANT NUMBER := 50;
  c_demo_hard_cap CONSTANT NUMBER := 50;  -- Demo cap = NFD

  -- GEHEIM(70) ist erlaubter Header-Wert (für Operatoren mit GEHEIM-
  -- Clearance), wird aber per Demo-Tenancy-Regel auf NFD(50) geclampt.
  -- Alles außerhalb {10,30,50,70} ist ungültig und fällt fail-safe
  -- auf OFFEN(10) zurück — kein versteckter Drift bei Roundtrip-Bugs.
  c_geheim  CONSTANT NUMBER := 70;

  PROCEDURE set_label_cap(p_cap IN NUMBER) IS
    v_cap NUMBER;
  BEGIN
    IF p_cap IS NULL THEN
      v_cap := c_offen;                                -- NULL → fail-safe
    ELSIF p_cap NOT IN (c_offen, c_intern, c_nfd, c_geheim) THEN
      v_cap := c_offen;                                -- ungültig → fail-safe
    ELSIF p_cap > c_demo_hard_cap THEN
      v_cap := c_demo_hard_cap;                        -- GEHEIM → Demo-Cap NFD
    ELSE
      v_cap := p_cap;                                  -- 10/30/50 → unverändert
    END IF;
    DBMS_SESSION.SET_CONTEXT('UC4_OSINT_OLS_CTX', 'LABEL_CAP', TO_CHAR(v_cap));
  END set_label_cap;

  PROCEDURE clear_label_cap IS
  BEGIN
    DBMS_SESSION.CLEAR_CONTEXT('UC4_OSINT_OLS_CTX', 'LABEL_CAP');
  END clear_label_cap;

  FUNCTION get_label_cap RETURN NUMBER IS
    v_raw VARCHAR2(40);
  BEGIN
    v_raw := SYS_CONTEXT('UC4_OSINT_OLS_CTX', 'LABEL_CAP');
    IF v_raw IS NULL THEN
      RETURN c_offen;
    END IF;
    RETURN TO_NUMBER(v_raw);
  EXCEPTION
    -- Sollte nicht passieren (set_label_cap clampt vorher), aber
    -- defensive Antwort: fail-safe auf OFFEN.
    WHEN OTHERS THEN RETURN c_offen;
  END get_label_cap;

END ols_ctx_pkg;
/

-- ---------------------------------------------------------------------------
-- (3) Stand-alone Function für WHERE-Klauseln
--
-- WHERE ols_label <= UC4_OSINT.label_cap()  ← so wird's verwendet.
--
-- Stand-alone (nicht im Package) damit der SQL-Optimizer die Function
-- bei jedem Row sauber inlinen kann. PARALLEL_ENABLE für künftige
-- IVF-Vector-Search-Queries, die parallel scannen.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION UC4_OSINT.label_cap RETURN NUMBER
  PARALLEL_ENABLE
AS
  v_raw VARCHAR2(40);
BEGIN
  v_raw := SYS_CONTEXT('UC4_OSINT_OLS_CTX', 'LABEL_CAP');
  IF v_raw IS NULL THEN
    RETURN 10;  -- fail-safe OFFEN
  END IF;
  RETURN TO_NUMBER(v_raw);
EXCEPTION
  WHEN OTHERS THEN RETURN 10;
END label_cap;
/

-- ---------------------------------------------------------------------------
-- (4) EXECUTE-Grants
--
-- LABEL_CAP() lesen darf jeder authentifizierte User — die Funktion liefert
-- nur den Session-eigenen Wert, kein Information-Disclosure.
-- OLS_CTX_PKG schreiben darf nur ein definierter Service-Role-Kreis.
-- Wir starten mit UC4_AUDIT_APPENDER als Platzhalter (die Rolle kommt aus
-- 03_security.sql); spätere UC4-Service-Rollen werden ergänzt.
-- ---------------------------------------------------------------------------
GRANT EXECUTE ON UC4_OSINT.label_cap     TO PUBLIC;
GRANT EXECUTE ON UC4_OSINT.ols_ctx_pkg   TO uc4_audit_appender;

-- ---------------------------------------------------------------------------
-- Tail-Sanity: Roundtrip-Test der Context-Variable.
-- Wir setzen, lesen, prüfen, clearen.
-- ---------------------------------------------------------------------------
DECLARE
  v_after_set   NUMBER;
  v_after_clear NUMBER;
BEGIN
  UC4_OSINT.ols_ctx_pkg.set_label_cap(50);
  v_after_set := UC4_OSINT.label_cap;
  IF v_after_set != 50 THEN
    RAISE_APPLICATION_ERROR(-20004,
      '03b_ols_app_filter.sql: SET_LABEL_CAP(50) → label_cap()='||v_after_set||' (erwartet 50).');
  END IF;

  UC4_OSINT.ols_ctx_pkg.clear_label_cap;
  v_after_clear := UC4_OSINT.label_cap;
  IF v_after_clear != 10 THEN
    RAISE_APPLICATION_ERROR(-20004,
      '03b_ols_app_filter.sql: CLEAR → label_cap()='||v_after_clear||' (erwartet 10 fail-safe).');
  END IF;

  -- Auch das Clamping testen
  UC4_OSINT.ols_ctx_pkg.set_label_cap(70);  -- GEHEIM → soll auf 50 clampen
  IF UC4_OSINT.label_cap != 50 THEN
    RAISE_APPLICATION_ERROR(-20004,
      '03b_ols_app_filter.sql: GEHEIM(70) wurde nicht auf NFD(50) geclampt.');
  END IF;

  UC4_OSINT.ols_ctx_pkg.set_label_cap(999);  -- invalid → 10 fail-safe
  IF UC4_OSINT.label_cap != 10 THEN
    RAISE_APPLICATION_ERROR(-20004,
      '03b_ols_app_filter.sql: Invalid 999 wurde nicht auf 10 fail-safe geclampt.');
  END IF;

  UC4_OSINT.ols_ctx_pkg.clear_label_cap;
  DBMS_OUTPUT.PUT_LINE(
    '03b_ols_app_filter.sql OK: context UC4_OSINT_OLS_CTX, package OLS_CTX_PKG, '
    ||'function LABEL_CAP() — set/get/clear/clamp roundtrip green.');
END;
/

-- ===========================================================================
-- Done. Folge:
--   * services/osint-fusion/app/ols.py — FastAPI-Dependency, die
--     X-OLS-Label-Max parst und UC4_OSINT.OLS_CTX_PKG.SET_LABEL_CAP
--     auf der Session aufruft, plus eine label_filter_clause()-Hilfe.
--   * services/osint-fusion/tests/test_ols.py — Unit-Tests.
--   * docs/audits/uc4-ols-app-level-filter-2026-05-01.md — Design,
--     Threat-Model, Roll-Forward.
-- ===========================================================================
