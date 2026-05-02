-- =============================================================================
--  Migration 01 — add image_uri column to satellite_scenes
-- -----------------------------------------------------------------------------
--  Stores the OCI Object Storage key (e.g. "tenant/T001/scene/<uuid>.jpg") for
--  the image whose YOLOv8 detections live in `yolo_detections`. Bucket is
--  configured via the OCI_BUCKET_* env vars on the geoint deployment, so the
--  column intentionally holds the object NAME only — the namespace and bucket
--  are stack-level config, not per-row metadata.
--
--  Idempotent: the ALTER is wrapped in a PL/SQL probe so re-running the
--  migration (e.g. as part of bootstrap) does not error.
-- =============================================================================
SET ECHO ON
SET DEFINE OFF

DECLARE
    column_exists  NUMBER;
BEGIN
    SELECT COUNT(*)
      INTO column_exists
      FROM user_tab_columns
     WHERE table_name  = 'SATELLITE_SCENES'
       AND column_name = 'IMAGE_URI';

    IF column_exists = 0 THEN
        EXECUTE IMMEDIATE
            'ALTER TABLE satellite_scenes ADD (image_uri VARCHAR2(2000))';
    END IF;
END;
/

COMMENT ON COLUMN satellite_scenes.image_uri IS
  'OCI Object Storage object name for the scene image. Bucket+namespace come from the geoint service env (OCI_BUCKET_NAMESPACE / OCI_BUCKET_NAME).';

COMMIT;
