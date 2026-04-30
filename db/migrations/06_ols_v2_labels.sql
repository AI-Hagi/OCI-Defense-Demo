-- =============================================================================
--  Migration 06 — OLS v2 label tags
-- -----------------------------------------------------------------------------
--  Encoding: label_tag = level * 10_000_000 + compartment * 10_000 + group_num.
--    e.g. U:GEOINT:DEU = 100 * 10_000_000 + 200 * 10_000 + 1000 = 1_002_001_000.
--
--  This migration creates the new label tags actually needed by the demo data:
--      U:GEOINT:<DEU|FRA|NLD>      — satellite scenes, default fallback
--      U:LOGISTICS:<DEU|FRA|NLD>   — supply_nodes, supply_edges
--      U:EW:<DEU|FRA|NLD>          — osint_entities WHERE kind='ems_emission'
--
--  Other compartments (HUMINT/SIGINT/C_UAS/UAS_OPS) are reserved for future
--  data ingestion and intentionally not bound to label tags here — adding
--  more is a one-line CALL when that data shows up.
-- =============================================================================
SET ECHO ON
SET DEFINE OFF

DECLARE
    PROCEDURE create_label(p_tag NUMBER, p_value VARCHAR2) IS
    BEGIN
        SA_LABEL_ADMIN.CREATE_LABEL(
            policy_name => 'DICE_POLICY',
            label_tag   => p_tag,
            label_value => p_value);
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('label '||p_value||': '||SQLERRM);
    END;
BEGIN
    -- U : GEOINT (200) : <group>
    create_label(1002001000, 'U:GEOINT:DEU');
    create_label(1002001010, 'U:GEOINT:FRA');
    create_label(1002001020, 'U:GEOINT:NLD');

    -- U : LOGISTICS (230) : <group>
    create_label(1002301000, 'U:LOGISTICS:DEU');
    create_label(1002301010, 'U:LOGISTICS:FRA');
    create_label(1002301020, 'U:LOGISTICS:NLD');

    -- U : EW (240) : <group>
    create_label(1002401000, 'U:EW:DEU');
    create_label(1002401010, 'U:EW:FRA');
    create_label(1002401020, 'U:EW:NLD');
END;
/

COMMIT;
