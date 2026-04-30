--==============================================================================
-- File:        11_flights_curated.sql
-- Purpose:     Two military-aircraft reference tables for the UC4 flights
--              hybrid classifier. The classifier looks up an aircraft hex24
--              against:
--                1. mil_aircraft_curated   — sovereign / hand-vetted entries
--                                             (NATO Geilenkirchen, Bundeswehr,
--                                             coalition partners). Wins on
--                                             conflict.
--                2. mil_aircraft_mictronics — community feed loaded weekly
--                                             from the Mictronics readsb
--                                             aircrafts.json (filtered to
--                                             mil-flag-bit=1 entries only).
--              Both are queried via the union view mil_aircraft_unified.
--
-- Target:      Oracle AI Database 26ai (ATP)
-- Depends on:  none — standalone reference tables, no FKs into existing schema.
--
-- Idempotency: CREATE wrapped in PL/SQL exception handlers. The seed insert
--              uses MERGE so re-running is safe.
--==============================================================================

SET DEFINE OFF;
SET SERVEROUTPUT ON SIZE UNLIMITED;
WHENEVER SQLERROR CONTINUE;

--------------------------------------------------------------------------------
-- 1. mil_aircraft_curated — sovereign, hand-curated
--------------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE mil_aircraft_curated (
      hex24            VARCHAR2(6)   PRIMARY KEY,
      callsign_pattern VARCHAR2(60),
      operator         VARCHAR2(120) NOT NULL,
      icao_type        VARCHAR2(8),
      registration     VARCHAR2(20),
      notes            VARCHAR2(400),
      source           VARCHAR2(20)  DEFAULT 'curated' NOT NULL,
      classification   VARCHAR2(20)  DEFAULT 'OPEN' NOT NULL,
      created_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
      last_modified    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
    )
  ]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -955 THEN DBMS_OUTPUT.PUT_LINE('mil_aircraft_curated exists - skip');
    ELSE DBMS_OUTPUT.PUT_LINE('curated create: '||SQLERRM); END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    ALTER TABLE mil_aircraft_curated ADD CONSTRAINT mil_curated_classification_chk
      CHECK (classification IN ('OPEN','RESTRICTED','CONFIDENTIAL','SECRET'))
  ]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE IN (-2264, -2275) THEN NULL; ELSE DBMS_OUTPUT.PUT_LINE('curated chk: '||SQLERRM); END IF;
END;
/

--------------------------------------------------------------------------------
-- 2. mil_aircraft_mictronics — community feed (Mictronics readsb DB)
--------------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE mil_aircraft_mictronics (
      hex24         VARCHAR2(6)   PRIMARY KEY,
      registration  VARCHAR2(20),
      icao_type     VARCHAR2(8),
      description   VARCHAR2(200),
      flag_bits_hex VARCHAR2(8)   NOT NULL,
      source        VARCHAR2(20)  DEFAULT 'mictronics' NOT NULL,
      loaded_at     TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
    )
  ]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -955 THEN DBMS_OUTPUT.PUT_LINE('mil_aircraft_mictronics exists - skip');
    ELSE DBMS_OUTPUT.PUT_LINE('mictronics create: '||SQLERRM); END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX mil_mictronics_loaded_idx ON mil_aircraft_mictronics (loaded_at DESC)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE IN (-955, -1408) THEN NULL; ELSE DBMS_OUTPUT.PUT_LINE('mictronics idx: '||SQLERRM); END IF;
END;
/

--------------------------------------------------------------------------------
-- 3. mil_aircraft_unified — UNION view, classifier reads only this
--------------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW mil_aircraft_unified AS
      SELECT hex24, operator AS label, registration, icao_type, source, classification
        FROM mil_aircraft_curated
       UNION ALL
      SELECT m.hex24,
             COALESCE(m.description, m.registration) AS label,
             m.registration,
             m.icao_type,
             m.source,
             'OPEN' AS classification
        FROM mil_aircraft_mictronics m
       WHERE NOT EXISTS (
         SELECT 1 FROM mil_aircraft_curated c WHERE c.hex24 = m.hex24
       )
  ]';
EXCEPTION
  WHEN OTHERS THEN
    DBMS_OUTPUT.PUT_LINE('unified view: '||SQLERRM);
END;
/

--------------------------------------------------------------------------------
-- 4. Demo seed — five clearly-marked placeholders. Replace with the real
--    Bundeswehr/NATO authoritative list when available. Hex codes used here
--    are publicly known mode-S codes from open ADS-B catalogues; treat as
--    illustrative, not operational.
--------------------------------------------------------------------------------
MERGE INTO mil_aircraft_curated t
USING (SELECT '4D02C0' AS hex24, 'NAEW@LXN'                 AS callsign_pattern,
              'NATO AWACS Geilenkirchen' AS operator,
              'E3TF' AS icao_type, 'LX-N90442' AS registration,
              'demo placeholder; verify against authoritative roster' AS notes
         FROM dual) s
ON (t.hex24 = s.hex24)
WHEN NOT MATCHED THEN INSERT
  (hex24, callsign_pattern, operator, icao_type, registration, notes)
VALUES (s.hex24, s.callsign_pattern, s.operator, s.icao_type, s.registration, s.notes);

MERGE INTO mil_aircraft_curated t
USING (SELECT '4D02C9' AS hex24, 'NAEW@LXN' AS callsign_pattern,
              'NATO AWACS Geilenkirchen' AS operator,
              'E3TF' AS icao_type, 'LX-N90446' AS registration,
              'demo placeholder' AS notes
         FROM dual) s
ON (t.hex24 = s.hex24)
WHEN NOT MATCHED THEN INSERT
  (hex24, callsign_pattern, operator, icao_type, registration, notes)
VALUES (s.hex24, s.callsign_pattern, s.operator, s.icao_type, s.registration, s.notes);

MERGE INTO mil_aircraft_curated t
USING (SELECT '3F8032' AS hex24, 'GAF%' AS callsign_pattern,
              'Bundeswehr (German Army)' AS operator,
              'NH90' AS icao_type, '79+14' AS registration,
              'demo placeholder; NH90 TTH (NATO Helicopter)' AS notes
         FROM dual) s
ON (t.hex24 = s.hex24)
WHEN NOT MATCHED THEN INSERT
  (hex24, callsign_pattern, operator, icao_type, registration, notes)
VALUES (s.hex24, s.callsign_pattern, s.operator, s.icao_type, s.registration, s.notes);

MERGE INTO mil_aircraft_curated t
USING (SELECT 'AE1234' AS hex24, 'RCH%' AS callsign_pattern,
              'USAF (Ramstein)' AS operator,
              'C17' AS icao_type, NULL AS registration,
              'demo placeholder; USAF logistics, replace with real entry' AS notes
         FROM dual) s
ON (t.hex24 = s.hex24)
WHEN NOT MATCHED THEN INSERT
  (hex24, callsign_pattern, operator, icao_type, registration, notes)
VALUES (s.hex24, s.callsign_pattern, s.operator, s.icao_type, s.registration, s.notes);

MERGE INTO mil_aircraft_curated t
USING (SELECT '43C123' AS hex24, 'RRR%' AS callsign_pattern,
              'Royal Air Force' AS operator,
              'A400' AS icao_type, NULL AS registration,
              'demo placeholder; UK A400M Atlas, replace with real entry' AS notes
         FROM dual) s
ON (t.hex24 = s.hex24)
WHEN NOT MATCHED THEN INSERT
  (hex24, callsign_pattern, operator, icao_type, registration, notes)
VALUES (s.hex24, s.callsign_pattern, s.operator, s.icao_type, s.registration, s.notes);

COMMIT;

--==============================================================================
-- Rollback (manual):
--   DROP VIEW  mil_aircraft_unified;
--   DROP TABLE mil_aircraft_mictronics PURGE;
--   DROP TABLE mil_aircraft_curated    PURGE;
--==============================================================================
-- End of 11_flights_curated.sql
--==============================================================================
