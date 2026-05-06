-- =====================================================================
-- UC #10 Requirements Intelligence — Step 4: Augment Security
-- =====================================================================
-- Two-layer VPD:
--   Layer 1: shared coalition_security_policy (clearance + nation + releasability)
--   Layer 2: shared program_security_policy   (Boxer ≠ Schützenpanzer ≠ Marine)
-- Both live in industrial/_shared/coalition_ctx_bootstrap.sql now —
-- this file only:
--   * defines requirements_security_policy as the AND-combination
--   * attaches the policy to UC10 tables
--
-- Prerequisite: industrial/_shared/coalition_ctx_bootstrap.sql is run
-- first (provides coalition_ctx_pkg, coalition_security_policy,
-- program_security_policy, attach_coalition_policy).
-- =====================================================================

SET DEFINE OFF

-- ---------------------------------------------------------------------
-- 4a. Combined policy: coalition + program (UC10-specific)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION requirements_security_policy(
  schema_var IN VARCHAR2,
  table_var  IN VARCHAR2
) RETURN VARCHAR2 AS
  l_coalition_pred VARCHAR2(4000);
  l_program_pred   VARCHAR2(4000);
BEGIN
  l_coalition_pred := coalition_security_policy(schema_var, table_var);
  l_program_pred   := program_security_policy(schema_var, table_var);
  -- Both policies must hold (AND).
  RETURN '(' || l_coalition_pred || ') AND (' || l_program_pred || ')';
END;
/

-- ---------------------------------------------------------------------
-- 4b. Attach the combined policy to UC10 tables
--
-- Notes:
--   * statement_types = 'SELECT' only — ATP 23.26 throws ORA-28104 for
--     multi-statement attachments. Writes go through coalition_ctx-aware
--     procs that already enforce the same rules application-side.
--   * policy_type CONTEXT_SENSITIVE re-evaluates the predicate when the
--     session context changes (after coalition_ctx_pkg.set_program).
--   * user_policies (NOT dba_policies) — UC10_APP can't read SYS views
--     on Autonomous.
-- ---------------------------------------------------------------------
DECLARE
  l_count NUMBER;
BEGIN
  -- requirements
  SELECT COUNT(*) INTO l_count FROM user_policies
   WHERE object_name = 'REQUIREMENTS' AND policy_name = 'REQ_VPD_POLICY';
  IF l_count = 0 THEN
    DBMS_RLS.ADD_POLICY(
      object_schema   => USER,
      object_name     => 'REQUIREMENTS',
      policy_name     => 'REQ_VPD_POLICY',
      function_schema => USER,
      policy_function => 'REQUIREMENTS_SECURITY_POLICY',
      statement_types => 'SELECT',
      policy_type     => DBMS_RLS.CONTEXT_SENSITIVE
    );
  END IF;

  -- requirements_reuse_mv (read-only)
  SELECT COUNT(*) INTO l_count FROM user_policies
   WHERE object_name = 'REQUIREMENTS_REUSE_MV' AND policy_name = 'REUSE_VPD_POLICY';
  IF l_count = 0 THEN
    DBMS_RLS.ADD_POLICY(
      object_schema   => USER,
      object_name     => 'REQUIREMENTS_REUSE_MV',
      policy_name     => 'REUSE_VPD_POLICY',
      function_schema => USER,
      policy_function => 'REQUIREMENTS_SECURITY_POLICY',
      statement_types => 'SELECT',
      policy_type     => DBMS_RLS.CONTEXT_SENSITIVE
    );
  END IF;

  -- programs (coalition-only — programs catalogue is visible to anyone
  -- with the right clearance, even if they can't read the requirements)
  SELECT COUNT(*) INTO l_count FROM user_policies
   WHERE object_name = 'PROGRAMS' AND policy_name = 'PROGRAMS_VPD_POLICY';
  IF l_count = 0 THEN
    DBMS_RLS.ADD_POLICY(
      object_schema   => USER,
      object_name     => 'PROGRAMS',
      policy_name     => 'PROGRAMS_VPD_POLICY',
      function_schema => USER,
      policy_function => 'COALITION_SECURITY_POLICY',
      statement_types => 'SELECT',
      policy_type     => DBMS_RLS.CONTEXT_SENSITIVE
    );
  END IF;
END;
/

PROMPT UC10 step 4 (security) complete.
PROMPT NB: scope a session via coalition_ctx_pkg.set_program('BOXER-MOD').
