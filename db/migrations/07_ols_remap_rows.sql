-- =============================================================================
--  Migration 07 — remap existing ols_label values (old → DEV9 v2)
-- -----------------------------------------------------------------------------
--  Maps every domain table's ``ols_label`` column from the legacy encoding
--  (level 10..70 × compartment INTEL=100 × group 1000/1010/1020) to the
--  spec encoding from migration 06.
--
--  Strategy:
--    * default — INTEL → GEOINT  (most common case for the demo data)
--    * osint_entities WHERE kind='ems_emission' → EW
--    * supply_nodes / supply_edges                → LOGISTICS
--
--  Tables touched (every column named ``ols_label`` referencing label_tag):
--      satellite_scenes, scene_embeddings (none — derives from scenes),
--      documents, doc_chunks, shared_artefacts,
--      osint_entities, osint_relations,
--      supply_nodes, supply_edges, supply_risk_history,
--      compliance_controls, compliance_findings,
--      tenants
--
--  Idempotent: relies on a temporary mapping table that's created and
--  dropped within the migration. Re-running is a no-op (rows already on
--  the new tags don't match the WHERE clause).
-- =============================================================================
SET ECHO ON
SET DEFINE OFF

-- Build a temporary lookup of old_tag → new_tag (default INTEL → GEOINT).
-- Old encoding: level (2 dig) + compartment (3 dig) + group (4 dig) = 9 dig.
-- New encoding: level (3 dig) + compartment (3 dig) + group (4 dig) = 10 dig.

CREATE GLOBAL TEMPORARY TABLE ols_remap_v2 (
    old_tag    NUMBER PRIMARY KEY,
    new_tag    NUMBER NOT NULL
) ON COMMIT PRESERVE ROWS;

INSERT INTO ols_remap_v2 (old_tag, new_tag) VALUES
    -- U : INTEL : DEU/FRA/NLD  →  U : GEOINT : DEU/FRA/NLD
    (10001000, 1002001000),
    (10001010, 1002001010),
    (10001020, 1002001020),
    -- R : INTEL : *  →  R : GEOINT : *  (level 30→200)
    (30001000, 2002001000),
    (30001010, 2002001010),
    (30001020, 2002001020),
    -- C : INTEL : *  →  C : GEOINT : *  (level 50→300)
    (50001000, 3002001000),
    (50001010, 3002001010),
    (50001020, 3002001020),
    -- S : INTEL : *  →  S : GEOINT : *  (level 70→400)
    (70001000, 4002001000),
    (70001010, 4002001010),
    (70001020, 4002001020);

-- For the higher levels we may not have created tags in migration 06 (only
-- U:GEOINT/LOGISTICS/EW were created). To keep this migration safe even if
-- some rows carry R/C/S labels, also pre-create the matching higher-level
-- tags here. CREATE_LABEL is idempotent via the EXCEPTION WHEN OTHERS guard.
DECLARE
    PROCEDURE create_label_safe(p_tag NUMBER, p_value VARCHAR2) IS
    BEGIN
        SA_LABEL_ADMIN.CREATE_LABEL(
            policy_name => 'DICE_POLICY',
            label_tag   => p_tag,
            label_value => p_value);
    EXCEPTION
        WHEN OTHERS THEN NULL;
    END;
BEGIN
    create_label_safe(2002001000, 'R:GEOINT:DEU');
    create_label_safe(2002001010, 'R:GEOINT:FRA');
    create_label_safe(2002001020, 'R:GEOINT:NLD');
    create_label_safe(3002001000, 'C:GEOINT:DEU');
    create_label_safe(3002001010, 'C:GEOINT:FRA');
    create_label_safe(3002001020, 'C:GEOINT:NLD');
    create_label_safe(4002001000, 'S:GEOINT:DEU');
    create_label_safe(4002001010, 'S:GEOINT:FRA');
    create_label_safe(4002001020, 'S:GEOINT:NLD');
END;
/

-- ---------------------------------------------------------------------
-- Default remap: any table with ols_label that matches the lookup gets
-- swapped. Tables that don't exist in this DB are skipped via dynamic
-- SQL with EXCEPTION WHEN OTHERS.
-- ---------------------------------------------------------------------
DECLARE
    TYPE name_array IS TABLE OF VARCHAR2(64);
    tables name_array := name_array(
        'TENANTS',
        'SATELLITE_SCENES',
        'DOCUMENTS', 'DOC_CHUNKS', 'SHARED_ARTEFACTS',
        'OSINT_ENTITIES', 'OSINT_RELATIONS',
        'SUPPLY_NODES', 'SUPPLY_EDGES', 'SUPPLY_RISK_HISTORY',
        'COMPLIANCE_CONTROLS', 'COMPLIANCE_FINDINGS'
    );
    n_updated NUMBER;
BEGIN
    FOR i IN 1..tables.COUNT LOOP
        BEGIN
            EXECUTE IMMEDIATE
                'UPDATE ' || tables(i) || ' t '
                || ' SET t.ols_label = ('
                || '   SELECT m.new_tag FROM ols_remap_v2 m '
                || '    WHERE m.old_tag = t.ols_label) '
                || ' WHERE t.ols_label IN (SELECT old_tag FROM ols_remap_v2)';
            n_updated := SQL%ROWCOUNT;
            DBMS_OUTPUT.PUT_LINE(tables(i) || ': ' || n_updated || ' rows remapped');
        EXCEPTION
            WHEN OTHERS THEN
                DBMS_OUTPUT.PUT_LINE('skip ' || tables(i) || ': ' || SQLERRM);
        END;
    END LOOP;
END;
/

-- ---------------------------------------------------------------------
-- Per-table refinements: bring rows into their natural compartment.
-- ---------------------------------------------------------------------

-- 1) osint_entities WHERE kind='ems_emission'  →  U:EW:<group>
BEGIN
    UPDATE osint_entities e
       SET e.ols_label = CASE
           WHEN e.ols_label = 1002001000 THEN 1002401000  -- U:GEOINT:DEU → U:EW:DEU
           WHEN e.ols_label = 1002001010 THEN 1002401010
           WHEN e.ols_label = 1002001020 THEN 1002401020
           ELSE e.ols_label
       END
     WHERE e.kind = 'ems_emission'
       AND e.ols_label IN (1002001000, 1002001010, 1002001020);
    DBMS_OUTPUT.PUT_LINE('osint_entities EMS refinement: '||SQL%ROWCOUNT||' rows');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('skip ems refinement: '||SQLERRM);
END;
/

-- 2) supply_nodes / supply_edges  →  U:LOGISTICS:<group>
BEGIN
    UPDATE supply_nodes n
       SET n.ols_label = CASE
           WHEN n.ols_label = 1002001000 THEN 1002301000  -- → U:LOGISTICS:DEU
           WHEN n.ols_label = 1002001010 THEN 1002301010
           WHEN n.ols_label = 1002001020 THEN 1002301020
           ELSE n.ols_label
       END
     WHERE n.ols_label IN (1002001000, 1002001010, 1002001020);
    DBMS_OUTPUT.PUT_LINE('supply_nodes refinement: '||SQL%ROWCOUNT||' rows');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('skip supply_nodes refinement: '||SQLERRM);
END;
/

BEGIN
    UPDATE supply_edges e
       SET e.ols_label = CASE
           WHEN e.ols_label = 1002001000 THEN 1002301000
           WHEN e.ols_label = 1002001010 THEN 1002301010
           WHEN e.ols_label = 1002001020 THEN 1002301020
           ELSE e.ols_label
       END
     WHERE e.ols_label IN (1002001000, 1002001010, 1002001020);
    DBMS_OUTPUT.PUT_LINE('supply_edges refinement: '||SQL%ROWCOUNT||' rows');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('skip supply_edges refinement: '||SQLERRM);
END;
/

COMMIT;

-- Drop the lookup table (it's a global temporary table — removing it cleanly
-- so re-applying the migration starts from scratch).
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE ols_remap_v2';
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/
