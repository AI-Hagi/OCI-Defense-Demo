-- =============================================================================
--  Migration 05 — OLS v2 compartments
-- -----------------------------------------------------------------------------
--  Spec compartments per CLAUDE_DEV9.md §Konventionen → Datenbank:
--
--      GEOINT     200    UC1 satellite + UAV
--      HUMINT     210    (future)
--      SIGINT     220    (future)
--      LOGISTICS  230    UC5 supply chain
--      EW         240    UC4 EMS emitters
--      C_UAS      250    counter-UAS overlay (UC1 + UC4)
--      UAS_OPS    260    UAV mission planning (UC1)
--
--  Original schema used 100/110/120/130 (INTEL/OPS/LOG/LEGAL). The new IDs
--  start at 200 to avoid collisions during the transition window — both
--  sets remain alive until migration 08 drops the legacy compartments.
-- =============================================================================
SET ECHO ON
SET DEFINE OFF

DECLARE
    PROCEDURE create_comp(p_num NUMBER, p_short VARCHAR2, p_long VARCHAR2) IS
    BEGIN
        SA_COMPONENTS.CREATE_COMPARTMENT(
            policy_name => 'DICE_POLICY',
            comp_num    => p_num,
            short_name  => p_short,
            long_name   => p_long);
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('comp '||p_short||': '||SQLERRM);
    END;
BEGIN
    create_comp(200, 'GEOINT',    'Geospatial Intelligence');
    create_comp(210, 'HUMINT',    'Human Intelligence');
    create_comp(220, 'SIGINT',    'Signals Intelligence');
    create_comp(230, 'LOGISTICS', 'Logistics & Supply Chain');
    create_comp(240, 'EW',        'Electronic Warfare / EMS');
    create_comp(250, 'C_UAS',     'Counter-UAS');
    create_comp(260, 'UAS_OPS',   'UAS Operations');
END;
/

COMMIT;
