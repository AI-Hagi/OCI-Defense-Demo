-- =============================================================================
--  Migration 02 — UAV / drone platform support on satellite_scenes
-- -----------------------------------------------------------------------------
--  DEV9 spec UC1 ("Multi-Source GEOINT & UAV-Aufklärungsfusion") requires the
--  GEOINT pipeline to ingest both satellite and UAV / drone feeds. Rather than
--  introduce a parallel uav_feeds table — which would duplicate the spatial
--  index, the YOLO-detection JSON column, the vector embedding linkage, and
--  the API surface — this migration extends ``satellite_scenes`` with three
--  optional columns that describe the originating platform:
--
--     platform_kind   'satellite' (default) | 'uav'
--     altitude_m      flight altitude in metres (UAV only; satellites NULL)
--     heading_deg     compass heading 0..360 (UAV only; satellites NULL)
--
--  Existing rows take the default ``platform_kind = 'satellite'`` so reading
--  paths stay backward-compatible.
--
--  Idempotent — re-running the migration is a no-op once the columns exist.
-- =============================================================================
SET ECHO ON
SET DEFINE OFF

DECLARE
    has_kind      NUMBER;
    has_altitude  NUMBER;
    has_heading   NUMBER;
    has_check     NUMBER;
BEGIN
    SELECT COUNT(*) INTO has_kind
      FROM user_tab_columns
     WHERE table_name = 'SATELLITE_SCENES' AND column_name = 'PLATFORM_KIND';

    SELECT COUNT(*) INTO has_altitude
      FROM user_tab_columns
     WHERE table_name = 'SATELLITE_SCENES' AND column_name = 'ALTITUDE_M';

    SELECT COUNT(*) INTO has_heading
      FROM user_tab_columns
     WHERE table_name = 'SATELLITE_SCENES' AND column_name = 'HEADING_DEG';

    IF has_kind = 0 THEN
        EXECUTE IMMEDIATE
          'ALTER TABLE satellite_scenes ADD ('
          || 'platform_kind VARCHAR2(20) DEFAULT ''satellite'' NOT NULL'
          || ')';
    END IF;

    IF has_altitude = 0 THEN
        EXECUTE IMMEDIATE
          'ALTER TABLE satellite_scenes ADD (altitude_m NUMBER(8,2))';
    END IF;

    IF has_heading = 0 THEN
        EXECUTE IMMEDIATE
          'ALTER TABLE satellite_scenes ADD (heading_deg NUMBER(5,2))';
    END IF;

    SELECT COUNT(*) INTO has_check
      FROM user_constraints
     WHERE table_name = 'SATELLITE_SCENES' AND constraint_name = 'CK_SCENES_PLATFORM_KIND';

    IF has_check = 0 THEN
        EXECUTE IMMEDIATE
          'ALTER TABLE satellite_scenes ADD CONSTRAINT ck_scenes_platform_kind '
          || 'CHECK (platform_kind IN (''satellite'',''uav''))';
    END IF;
END;
/

COMMENT ON COLUMN satellite_scenes.platform_kind IS
  'Originating platform: satellite (default) or uav. UC1 multi-source GEOINT.';
COMMENT ON COLUMN satellite_scenes.altitude_m IS
  'Flight altitude in metres above ground (UAV feeds only; NULL for satellites).';
COMMENT ON COLUMN satellite_scenes.heading_deg IS
  'Compass heading 0-360 (UAV feeds only; NULL for satellites).';

COMMIT;

-- =============================================================================
--  Rollback (manual):
--    ALTER TABLE satellite_scenes DROP CONSTRAINT ck_scenes_platform_kind;
--    ALTER TABLE satellite_scenes DROP (heading_deg, altitude_m, platform_kind);
-- =============================================================================
