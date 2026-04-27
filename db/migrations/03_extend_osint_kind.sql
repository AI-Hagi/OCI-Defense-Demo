-- =============================================================================
--  Migration 03 — extend osint_entities.kind with 'ems_emission'
-- -----------------------------------------------------------------------------
--  DEV9 spec UC4 ("OSINT & EMS-Lagebildfusion") fuses electromagnetic-spectrum
--  indicators alongside conventional OSINT entities so the existing property
--  graph (``osint_relations``, ``intel_fusion``) carries EMS edges natively.
--
--  ``osint_entities.kind`` is constrained by ``ck_osint_ent_kind``
--  (db/schema/02_core_tables.sql:192-195). This migration drops and recreates
--  that constraint with ``'ems_emission'`` added to the allowed list.
--
--  Idempotent — the recreate is wrapped so a second run leaves the constraint
--  exactly as the spec demands.
-- =============================================================================
SET ECHO ON
SET DEFINE OFF

DECLARE
    constraint_exists  NUMBER;
BEGIN
    -- Drop the old constraint if present.
    SELECT COUNT(*) INTO constraint_exists
      FROM user_constraints
     WHERE table_name = 'OSINT_ENTITIES'
       AND constraint_name = 'CK_OSINT_ENT_KIND';

    IF constraint_exists = 1 THEN
        EXECUTE IMMEDIATE
          'ALTER TABLE osint_entities DROP CONSTRAINT ck_osint_ent_kind';
    END IF;
END;
/

ALTER TABLE osint_entities ADD CONSTRAINT ck_osint_ent_kind CHECK (kind IN (
    'person','organization','location',
    'vessel','aircraft','company','asset',
    'event','indicator','malware','actor',
    'ems_emission'
));

COMMIT;

-- =============================================================================
--  Rollback (manual):
--    ALTER TABLE osint_entities DROP CONSTRAINT ck_osint_ent_kind;
--    -- then re-add the original list (without 'ems_emission')
-- =============================================================================
