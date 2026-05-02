-- ===========================================================================
-- UC4_OSINT — Schema-Owner-Provisioning (vor 01_tables.sql ausführen)
-- Oracle AI Database 26ai (ATP, eu-frankfurt-1, oci-defence-demo Compartment)
--
-- Was dieser File macht:
--   * Erstellt den DB-User (= Schema) UC4_OSINT idempotent.
--   * Vergibt die Mindest-Privilegien zum Anlegen der 9 Kerntabellen aus
--     01_tables.sql (Tabellen, Views, Sequences, Procedures, Trigger, Types).
--   * Gibt UNLIMITED-Quota auf dem ATP-Default-Tablespace DATA — sonst
--     kann der Owner trotz CREATE TABLE keine Zeilen einfügen.
--   * GRANTed das Default-Warehouse-Role DWROLE, das in ATP die übliche
--     Sammlung an Lesegrants auf Standard-Packages (UTL_HTTP, MDSYS
--     für Spatial, etc.) bündelt.
--
-- Was dieser File NICHT macht:
--   * Setzt KEIN Passwort im Klartext im Repo. Das Passwort kommt aus der
--     SQLcl-Substitutionsvariable &uc4_pwd, die VOR @-Ausführung des Files
--     definiert werden muss (siehe Invocation unten).
--   * Legt KEINE Tabellen an (das ist 01_tables.sql).
--   * Hängt KEINE OLS-Policy / DBV-Realm an (das ist 03_security.sql).
--
-- Aufruf-Pattern (nicht über apply-migration.sh, weil dieses Skript keine
-- DEFINE-Variablen forwarded — Schema-Owner-Bootstrap ist ohnehin ein
-- Once-per-Lifetime-Schritt):
--
--   sql -S "$ADB_USER/$ADB_ADMIN_PASSWORD@$ADB_TNS_ALIAS" <<EOF
--   SET VERIFY OFF
--   SET DEFINE ON
--   DEFINE uc4_pwd='$UC4_OSINT_PWD'
--   @db/schema/uc4_osint/00_create_schema_owner.sql
--   EXIT
--   EOF
--
-- Erwartet exportiert:
--   ADB_ADMIN_PASSWORD   ADMIN-Passwort der ATP-Instanz
--   UC4_OSINT_PWD        Passwort für den neuen Schema-Owner UC4_OSINT
--                        (ATP-Anforderungen: 12-30 Zeichen, mind. 1 Großbuchstabe,
--                        1 Kleinbuchstabe, 1 Ziffer, 1 Sonderzeichen, kein doppelter
--                        Buchstabe, nicht reverbar zum Username)
--
-- Nach dem ersten erfolgreichen Run:
--   * UC4_OSINT_PWD direkt in OCI Vault als Secret anlegen
--     (Compartment oci-defence-demo, Vault demo-vault).
--   * Die Workload-Identity der UC4-Services bekommt READ_SECRET-Policy
--     auf genau dieses Secret — dann braucht kein Service mehr das Klartext-
--     Passwort in seinem ConfigMap.
-- ===========================================================================

SET VERIFY OFF
SET DEFINE ON
WHENEVER SQLERROR EXIT FAILURE

-- ---------------------------------------------------------------------------
-- Existence-Check: nur anlegen, wenn UC4_OSINT noch nicht existiert.
-- Idempotent — bei wiederholten Runs ist dies ein No-Op und das Passwort
-- aus &uc4_pwd wird ignoriert (NICHT überschrieben — das wäre destruktiv).
-- Wenn das Passwort rotiert werden soll, separater ALTER USER ... IDENTIFIED
-- BY-Step in einer eigenen Migration.
-- ---------------------------------------------------------------------------
DECLARE
  v_exists      NUMBER;
  v_create_stmt VARCHAR2(4000);
  v_pwd         VARCHAR2(120) := '&uc4_pwd';
BEGIN
  SELECT COUNT(*) INTO v_exists
    FROM all_users
   WHERE username = 'UC4_OSINT';

  IF v_exists = 0 THEN
    -- ATP erlaubt CREATE USER mit gequotetem Passwort. Doppelte
    -- Anführungszeichen erlauben Sonderzeichen im Passwort. Single-quotes
    -- innerhalb des Passworts müssten escaped werden — die ATP-Passwort-
    -- Policy verbietet sie aber ohnehin nicht durchgängig, also defensiv:
    -- der Aufrufer wählt ein Passwort ohne single-quotes.
    v_create_stmt := 'CREATE USER UC4_OSINT IDENTIFIED BY "' || v_pwd || '" '
                  || 'DEFAULT TABLESPACE DATA '
                  || 'TEMPORARY TABLESPACE TEMP '
                  || 'QUOTA UNLIMITED ON DATA';
    EXECUTE IMMEDIATE v_create_stmt;

    -- Mindest-Privilegien für die DDL aus 01_tables.sql:
    EXECUTE IMMEDIATE 'GRANT CREATE SESSION   TO UC4_OSINT';
    EXECUTE IMMEDIATE 'GRANT CREATE TABLE     TO UC4_OSINT';
    EXECUTE IMMEDIATE 'GRANT CREATE VIEW      TO UC4_OSINT';
    EXECUTE IMMEDIATE 'GRANT CREATE SEQUENCE  TO UC4_OSINT';
    EXECUTE IMMEDIATE 'GRANT CREATE PROCEDURE TO UC4_OSINT';
    EXECUTE IMMEDIATE 'GRANT CREATE TRIGGER   TO UC4_OSINT';
    EXECUTE IMMEDIATE 'GRANT CREATE TYPE      TO UC4_OSINT';

    -- DWROLE bündelt die Standard-Lese-Grants auf MDSYS (Spatial),
    -- CTXSYS (Oracle Text) und andere Server-Packages. Ohne DWROLE
    -- schlägt SDO_GEOMETRY-Verwendung in 02_indexes.sql fehl.
    EXECUTE IMMEDIATE 'GRANT DWROLE TO UC4_OSINT';

    DBMS_OUTPUT.PUT_LINE('UC4_OSINT created with privileges + DWROLE.');
  ELSE
    DBMS_OUTPUT.PUT_LINE('UC4_OSINT already exists — skipping CREATE USER.');
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- Sanity-Check: existiert der User wirklich?
-- ---------------------------------------------------------------------------
DECLARE
  v_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_count
    FROM all_users
   WHERE username = 'UC4_OSINT';
  IF v_count != 1 THEN
    RAISE_APPLICATION_ERROR(-20002,
      '00_create_schema_owner.sql: UC4_OSINT post-condition failed (count='
      || v_count || ')');
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- Done. Folge-Schritt: 01_tables.sql gegen ADMIN-Connection ausführen
-- (über apply-migration.sh — der `ALTER SESSION SET CURRENT_SCHEMA = UC4_OSINT`
-- am Anfang von 01_tables.sql funktioniert ab jetzt, weil der User existiert).
-- ===========================================================================
