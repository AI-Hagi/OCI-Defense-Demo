--==============================================================================
-- File:        12_ports.sql
-- Purpose:     Curated reference table for the UC4 Ports hybrid classifier
--              (Layer #6). The classifier looks up an OSM port by 5 km
--              nearest-neighbor against:
--                1. ports_curated   — sovereign / hand-vetted NATO + Bundeswehr
--                                     reference (~30 strategic Atlantic +
--                                     Mediterranean + Baltic ports). Wins on
--                                     5 km match.
--                2. OSM Overpass    — wide-net loader fills the rest from
--                                     OpenStreetMap; classifier reads OSM
--                                     tags to derive port_type.
--
-- Target:      Oracle AI Database 26ai (ATP)
-- Depends on:  none — standalone reference table, no FKs into existing schema.
--              SDO_GEOMETRY column requires the MDSYS spatial package
--              (pre-installed on ATP).
--
-- Idempotency: CREATE wrapped in PL/SQL exception handlers. Seed inserts
--              use MERGE so re-running is safe — handy when augmenting the
--              curated set in production.
--==============================================================================

SET DEFINE OFF;
SET SERVEROUTPUT ON SIZE UNLIMITED;
WHENEVER SQLERROR CONTINUE;

--------------------------------------------------------------------------------
-- 1. ports_curated — sovereign, hand-curated reference table
--------------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE ports_curated (
      id                  NUMBER       PRIMARY KEY,
      name                VARCHAR2(200) NOT NULL,
      country             VARCHAR2(2)  NOT NULL,
      unlocode            VARCHAR2(5),
      port_type           VARCHAR2(20) NOT NULL,
      latitude            NUMBER       NOT NULL,
      longitude           NUMBER       NOT NULL,
      geometry            SDO_GEOMETRY,
      nato_member         NUMBER(1)    DEFAULT 0 NOT NULL,
      bundeswehr_facility NUMBER(1)    DEFAULT 0 NOT NULL,
      notes               VARCHAR2(500),
      source              VARCHAR2(20) DEFAULT 'curated' NOT NULL,
      classification      VARCHAR2(20) DEFAULT 'OPEN' NOT NULL,
      created_at          TIMESTAMP    DEFAULT SYSTIMESTAMP NOT NULL,
      last_modified       TIMESTAMP    DEFAULT SYSTIMESTAMP NOT NULL
    )
  ]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -955 THEN DBMS_OUTPUT.PUT_LINE('ports_curated exists - skip');
    ELSE DBMS_OUTPUT.PUT_LINE('ports_curated create: '||SQLERRM); END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    ALTER TABLE ports_curated ADD CONSTRAINT ports_port_type_chk
      CHECK (port_type IN ('commercial','military','fishing','marina','mixed'))
  ]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE IN (-2264, -2275) THEN NULL; ELSE DBMS_OUTPUT.PUT_LINE('ports_curated chk: '||SQLERRM); END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    ALTER TABLE ports_curated ADD CONSTRAINT ports_classification_chk
      CHECK (classification IN ('OPEN','RESTRICTED','CONFIDENTIAL','SECRET'))
  ]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE IN (-2264, -2275) THEN NULL; ELSE DBMS_OUTPUT.PUT_LINE('ports_classification chk: '||SQLERRM); END IF;
END;
/

--------------------------------------------------------------------------------
-- 2. Spatial + secondary indexes
--------------------------------------------------------------------------------
-- Spatial index requires user_sdo_geom_metadata to declare the SRID +
-- bounds before CREATE INDEX. user_sdo_geom_metadata is a *view* over
-- MDSYS.SDO_GEOM_METADATA_TABLE, which means Oracle MERGE rejects it
-- (ORA-38106). Use a PL/SQL block with EXCEPTION handler instead so
-- the script stays idempotent across re-runs.
BEGIN
  INSERT INTO user_sdo_geom_metadata (table_name, column_name, diminfo, srid)
  VALUES ('PORTS_CURATED', 'GEOMETRY',
          SDO_DIM_ARRAY(
            SDO_DIM_ELEMENT('LON', -180, 180, 0.005),
            SDO_DIM_ELEMENT('LAT',  -90,  90, 0.005)
          ),
          4326);
EXCEPTION
  WHEN DUP_VAL_ON_INDEX THEN
    DBMS_OUTPUT.PUT_LINE('user_sdo_geom_metadata row exists - skip');
END;
/
COMMIT;

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX ports_geom_idx ON ports_curated(geometry)
                     INDEXTYPE IS MDSYS.SPATIAL_INDEX_V2';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE IN (-955, -29879) THEN NULL; ELSE DBMS_OUTPUT.PUT_LINE('ports_geom_idx: '||SQLERRM); END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX ports_country_type_idx ON ports_curated(country, port_type)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE IN (-955, -1408) THEN NULL; ELSE DBMS_OUTPUT.PUT_LINE('ports_country_type_idx: '||SQLERRM); END IF;
END;
/

--------------------------------------------------------------------------------
-- 3. Seed — NATO + Bundeswehr-relevant Atlantic / Baltic / Mediterranean ports
--    (~30 entries). PL/SQL block with INSERT + DUP_VAL_ON_INDEX exception
--    per row keeps the script idempotent without the column-alias quirks
--    that broke the original MERGE pattern in sqlcl.
--------------------------------------------------------------------------------
DECLARE
  PROCEDURE seed(p_id NUMBER, p_name VARCHAR2, p_country VARCHAR2,
                 p_unlocode VARCHAR2, p_port_type VARCHAR2,
                 p_lat NUMBER, p_lon NUMBER,
                 p_nato NUMBER, p_bw NUMBER, p_notes VARCHAR2) IS
  BEGIN
    INSERT INTO ports_curated
      (id, name, country, unlocode, port_type, latitude, longitude, geometry,
       nato_member, bundeswehr_facility, notes)
    VALUES
      (p_id, p_name, p_country, p_unlocode, p_port_type, p_lat, p_lon,
       SDO_GEOMETRY(2001, 4326,
         SDO_POINT_TYPE(p_lon, p_lat, NULL), NULL, NULL),
       p_nato, p_bw, p_notes);
  EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
      DBMS_OUTPUT.PUT_LINE('skip ' || p_id || ' ' || p_name);
  END;
BEGIN
  seed(1001, 'Hamburg',                   'DE', 'DEHAM', 'commercial', 53.5418,   9.9836, 1, 0, 'Largest port in Germany; major container terminal');
  seed(1002, 'Bremerhaven',               'DE', 'DEBRV', 'commercial', 53.5396,   8.5810, 1, 0, 'Major German container + auto terminal');
  seed(1003, 'Kiel',                      'DE', 'DEKEL', 'mixed',      54.3233,  10.1394, 1, 1, 'Bundeswehr Marine + civilian ferry hub');
  seed(1004, 'Wilhelmshaven',             'DE', 'DEWVN', 'military',   53.5128,   8.1378, 1, 1, 'Bundeswehr Marine main North-Sea base');
  seed(1005, 'Rostock',                   'DE', 'DERSK', 'commercial', 54.0833,  12.0950, 1, 0, 'German Baltic ferry + cargo hub');
  seed(1006, 'Eckernfoerde',              'DE', NULL,    'military',   54.4711,   9.8378, 1, 1, 'Bundeswehr Marinestuetzpunkt; submarine + special-ops base');
  seed(1007, 'Olpenitz',                  'DE', NULL,    'military',   54.6739,  10.0386, 1, 1, 'Former Bundeswehr Marinestuetzpunkt; partially demilitarised');
  seed(1008, 'Warnemuende',               'DE', 'DERSK', 'mixed',      54.1819,  12.0833, 1, 0, 'Cruise + ferry terminal (Rostock outport)');
  seed(1009, 'Rotterdam',                 'NL', 'NLRTM', 'commercial', 51.9244,   4.4777, 1, 0, 'Largest port in Europe; container + petrochemical hub');
  seed(1010, 'Antwerpen',                 'BE', 'BEANR', 'commercial', 51.2200,   4.4017, 1, 0, 'Major Belgian container port; Western Scheldt');
  seed(1011, 'Gdansk',                    'PL', 'PLGDN', 'commercial', 54.3520,  18.6466, 1, 0, 'Largest Polish Baltic port; container + LNG');
  seed(1012, 'Gdynia',                    'PL', 'PLGDY', 'mixed',      54.5333,  18.5500, 1, 0, 'Polish Baltic mixed port; PL Navy + commercial');
  seed(1013, 'Klaipeda',                  'LT', 'LTKLJ', 'commercial', 55.7172,  21.1175, 1, 0, 'Lithuanias only major commercial port');
  seed(1014, 'Riga',                      'LV', 'LVRIX', 'commercial', 56.9700,  24.0700, 1, 0, 'Largest port in Latvia');
  seed(1015, 'Tallinn',                   'EE', 'EETLL', 'mixed',      59.4444,  24.7536, 1, 0, 'Estonian capital port; cruise + ferry');
  seed(1016, 'Helsinki',                  'FI', 'FIHEL', 'mixed',      60.1539,  24.9444, 1, 0, 'Finnish capital port; cruise + ferry');
  seed(1017, 'Stockholm',                 'SE', 'SESTO', 'mixed',      59.3294,  18.0686, 1, 0, 'Swedish capital port; cruise + ferry');
  seed(1018, 'Karlskrona',                'SE', NULL,    'military',   56.1612,  15.5869, 1, 0, 'Swedish Navy main base + UNESCO heritage');
  seed(1019, 'Aarhus',                    'DK', 'DKAAR', 'commercial', 56.1500,  10.2333, 1, 0, 'Largest container terminal in Denmark');
  seed(1020, 'Copenhagen',                'DK', 'DKCPH', 'mixed',      55.7000,  12.5950, 1, 0, 'Danish capital port; cruise + ferry');
  seed(1021, 'Bergen',                    'NO', 'NOBGO', 'mixed',      60.3933,   5.3242, 1, 0, 'Norwegian Atlantic gateway; cruise + cargo');
  seed(1022, 'Trondheim',                 'NO', 'NOTRD', 'mixed',      63.4400,  10.4170, 1, 0, 'Norwegian central-coast port; mixed cargo + cruise');
  seed(1023, 'Reykjavik',                 'IS', 'ISREY', 'mixed',      64.1500, -21.9333, 1, 0, 'NATO Atlantic anchor; Icelands main commercial port');
  seed(1024, 'Faslane (HMNB Clyde)',      'GB', NULL,    'military',   56.0683,  -4.8181, 1, 0, 'UK Royal Navy SSBN base; nuclear deterrent home port');
  seed(1025, 'Plymouth (HMNB Devonport)', 'GB', NULL,    'military',   50.3700,  -4.1820, 1, 0, 'UK Royal Navy main base; submarine refit centre');
  seed(1026, 'Portsmouth (HMNB)',         'GB', NULL,    'military',   50.8000,  -1.0928, 1, 0, 'UK Royal Navy primary base; carrier home port');
  seed(1027, 'Brest',                     'FR', 'FRBES', 'military',   48.3900,  -4.4861, 1, 0, 'French Navy Atlantic main base; SSBN home port');
  seed(1028, 'Toulon',                    'FR', 'FRTLN', 'military',   43.1167,   5.9333, 1, 0, 'French Navy Mediterranean main base; carrier port');
  seed(1029, 'Cartagena',                 'ES', 'ESCAR', 'military',   37.6000,  -0.9833, 1, 0, 'Spanish Navy Mediterranean main base; submarine port');
  seed(1030, 'Souda Bay',                 'GR', NULL,    'military',   35.5117,  24.0900, 1, 0, 'NATO Mediterranean fleet anchorage; Greek + US Navy');
  COMMIT;
END;
/

PROMPT == ports_curated seed complete ==
SELECT 'Curated ports loaded: ' || COUNT(*) FROM ports_curated;
