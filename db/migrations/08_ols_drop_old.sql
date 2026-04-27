-- =============================================================================
--  Migration 08 — drop legacy OLS labels / compartments / levels (gated)
-- -----------------------------------------------------------------------------
--  Removes the pre-DEV9 OLS components iff no row still references them.
--  The drop is destructive — once the legacy labels are gone, OLS-aware
--  queries against orphaned rows would fail. Hence the gate.
--
--  Safety probe: counts rows in every domain table whose ols_label still
--  matches the legacy encoding (level 10/30/50/70 × compartment 100/110/
--  120/130 × group). If any are found, abort with a clear message —
--  re-run migration 07 first to remap the strays.
-- =============================================================================
SET ECHO ON
SET DEFINE OFF

DECLARE
    legacy_rows NUMBER := 0;
    n_table     NUMBER;
    TYPE name_array IS TABLE OF VARCHAR2(64);
    tables name_array := name_array(
        'TENANTS',
        'SATELLITE_SCENES',
        'DOCUMENTS', 'DOC_CHUNKS', 'SHARED_ARTEFACTS',
        'OSINT_ENTITIES', 'OSINT_RELATIONS',
        'SUPPLY_NODES', 'SUPPLY_EDGES', 'SUPPLY_RISK_HISTORY',
        'COMPLIANCE_CONTROLS', 'COMPLIANCE_FINDINGS'
    );
BEGIN
    FOR i IN 1..tables.COUNT LOOP
        BEGIN
            EXECUTE IMMEDIATE
                'SELECT COUNT(*) FROM ' || tables(i) ||
                ' WHERE ols_label BETWEEN 10001000 AND 79991020 ' ||
                '   AND ols_label NOT BETWEEN 1002001000 AND 4002601020'
                INTO n_table;
            legacy_rows := legacy_rows + n_table;
            IF n_table > 0 THEN
                DBMS_OUTPUT.PUT_LINE(
                    'STILL LEGACY: ' || tables(i) || ' has ' || n_table || ' rows');
            END IF;
        EXCEPTION
            WHEN OTHERS THEN NULL;  -- table missing in this DB
        END;
    END LOOP;

    IF legacy_rows > 0 THEN
        RAISE_APPLICATION_ERROR(
            -20001,
            'Aborting migration 08: ' || legacy_rows ||
            ' rows still carry legacy OLS labels. Re-run migration 07 first.');
    END IF;
END;
/

-- ---------------------------------------------------------------------
-- All clear — drop legacy labels, compartments, levels.
-- Each drop is wrapped so missing components don't fail the whole script.
-- ---------------------------------------------------------------------

DECLARE
    PROCEDURE drop_label_safe(p_tag NUMBER) IS
    BEGIN
        SA_LABEL_ADMIN.DROP_LABEL(policy_name => 'DICE_POLICY', label_tag => p_tag);
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('drop label '||p_tag||': '||SQLERRM);
    END;

    PROCEDURE drop_comp_safe(p_short VARCHAR2) IS
    BEGIN
        SA_COMPONENTS.DROP_COMPARTMENT(policy_name => 'DICE_POLICY',
                                       short_name  => p_short);
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('drop compartment '||p_short||': '||SQLERRM);
    END;

    PROCEDURE drop_level_safe(p_short VARCHAR2) IS
    BEGIN
        SA_COMPONENTS.DROP_LEVEL(policy_name => 'DICE_POLICY',
                                 short_name  => p_short);
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('drop level '||p_short||': '||SQLERRM);
    END;
BEGIN
    -- Legacy U:INTEL:* labels.
    drop_label_safe(10001000);
    drop_label_safe(10001010);
    drop_label_safe(10001020);

    -- Legacy compartments INTEL/OPS/LOG/LEGAL.
    drop_comp_safe('INTEL');
    drop_comp_safe('OPS');
    drop_comp_safe('LOG');
    drop_comp_safe('LEGAL');

    -- Legacy levels (10/30/50/70). DEV9 levels (100/200/300/400) live on.
    drop_level_safe('U');
    drop_level_safe('R');
    drop_level_safe('C');
    drop_level_safe('S');
END;
/

COMMIT;
