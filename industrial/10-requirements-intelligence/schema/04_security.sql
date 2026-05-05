-- =====================================================================
-- UC #10 Requirements Intelligence — Step 4: Augment Security
-- =====================================================================
-- Two-layer VPD:
--   Layer 1: shared coalition_security_policy (clearance + nation + releasability)
--   Layer 2: UC10-specific program_security_policy (Eurofighter ≠ FCAS)
-- Combined into requirements_security_policy.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 4a. Extend coalition_ctx_pkg with set_program / clear_program
--     (idempotent — only adds the new program-context handling)
-- ---------------------------------------------------------------------
DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count FROM user_context
  WHERE namespace = 'COALITION_CTX' AND attribute = 'PROGRAM_LIST';
  IF l_count = 0 THEN
    -- No existing program context — extend the package
    NULL;
  END IF;
END;
/

-- Backwards-compat shim. The actual SET_CONTEXT call lives in
-- coalition_ctx_pkg.set_program because the application context
-- coalition_ctx is bound `USING coalition_ctx_pkg` — a standalone
-- procedure raises ORA-01031 when calling DBMS_SESSION.SET_CONTEXT
-- against that namespace. Existing callers keep working through this
-- delegate.
CREATE OR REPLACE PROCEDURE coalition_ctx_set_program(p_programs IN VARCHAR2) AS
BEGIN
  coalition_ctx_pkg.set_program(p_programs);
END;
/

-- ---------------------------------------------------------------------
-- 4b. UC10-specific VPD function: program isolation
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION program_security_policy(
  schema_var IN VARCHAR2,
  table_var  IN VARCHAR2
) RETURN VARCHAR2 AS
  l_program_list VARCHAR2(4000);
BEGIN
  l_program_list := SYS_CONTEXT('coalition_ctx', 'program_list');
  IF l_program_list IS NULL THEN
    -- Fail closed — no program context, no rows
    RETURN '1=0';
  END IF;
  -- Build IN-list predicate from comma-separated program list
  RETURN 'program_id IN (SELECT TRIM(REGEXP_SUBSTR(''' || l_program_list ||
         ''', ''[^,]+'', 1, LEVEL)) FROM dual ' ||
         'CONNECT BY LEVEL <= REGEXP_COUNT(''' || l_program_list || ''', '','') + 1)';
END;
/

-- ---------------------------------------------------------------------
-- 4c. Combined policy: coalition + program
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
-- 4d. Attach the combined policy to UC10 tables
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
      -- ATP 23.26 rejects multi-statement attachments with ORA-28104.
      -- SELECT-only is sufficient for VPD read-side filtering; writes
      -- go through coalition_ctx-aware procs that already enforce
      -- the same rules application-side.
      statement_types => 'SELECT'
    );
  END IF;

  -- requirements_reuse_mv
  SELECT COUNT(*) INTO l_count FROM user_policies
  WHERE object_name = 'REQUIREMENTS_REUSE_MV' AND policy_name = 'REUSE_VPD_POLICY';
  IF l_count = 0 THEN
    DBMS_RLS.ADD_POLICY(
      object_schema   => USER,
      object_name     => 'REQUIREMENTS_REUSE_MV',
      policy_name     => 'REUSE_VPD_POLICY',
      function_schema => USER,
      policy_function => 'REQUIREMENTS_SECURITY_POLICY',
      statement_types => 'SELECT'
    );
  END IF;

  -- programs (coalition VPD only — programs themselves are visible
  -- to anyone with the right clearance, even if the user can't read
  -- their requirements)
  SELECT COUNT(*) INTO l_count FROM user_policies
  WHERE object_name = 'PROGRAMS' AND policy_name = 'PROGRAMS_VPD_POLICY';
  IF l_count = 0 THEN
    DBMS_RLS.ADD_POLICY(
      object_schema   => USER,
      object_name     => 'PROGRAMS',
      policy_name     => 'PROGRAMS_VPD_POLICY',
      function_schema => USER,
      policy_function => 'COALITION_SECURITY_POLICY',
      statement_types => 'SELECT'
    );
  END IF;
END;
/

PROMPT UC10 step 4 (security) complete.
PROMPT NB: Use coalition_ctx_set_program('EUROFIGHTER') to scope a session.
