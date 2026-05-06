-- =====================================================================
-- coalition_ctx_bootstrap.sql
-- Shared Application Context + VPD policy infrastructure for all
-- defence-industrial use cases.
--
-- Target: Oracle AI Database 26ai
-- Run as: DEFENCE_ADMIN (created by oracle-26ai-schema skill)
-- Run once per ADB instance.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Application Context for coalition / clearance / releasability
-- ---------------------------------------------------------------------
CREATE OR REPLACE PACKAGE coalition_ctx_pkg AS
  PROCEDURE set_session(
    p_user_id       IN VARCHAR2,
    p_clearance     IN VARCHAR2,  -- e.g. 'UNCLASSIFIED', 'RESTRICTED', 'CONFIDENTIAL', 'SECRET'
    p_nation        IN VARCHAR2,  -- ISO 3166-1 alpha-3, e.g. 'DEU', 'FRA', 'NLD'
    p_releasability IN VARCHAR2   -- e.g. 'NATO', 'EU', 'FVEY', 'NATIONAL_ONLY', 'ALL_COALITION'
  );
  PROCEDURE clear_session;

  -- UC10-specific program isolation. Lives in this package because the
  -- application context coalition_ctx is bound USING coalition_ctx_pkg
  -- — a standalone proc would fail with ORA-01031 when calling
  -- DBMS_SESSION.SET_CONTEXT against this namespace.
  PROCEDURE set_program(p_programs IN VARCHAR2);  -- comma list of program_id
  PROCEDURE clear_program;
END coalition_ctx_pkg;
/

CREATE OR REPLACE PACKAGE BODY coalition_ctx_pkg AS
  PROCEDURE set_session(
    p_user_id       IN VARCHAR2,
    p_clearance     IN VARCHAR2,
    p_nation        IN VARCHAR2,
    p_releasability IN VARCHAR2
  ) IS
  BEGIN
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'user_id',       p_user_id);
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'clearance_level', p_clearance);
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'nation_code',   p_nation);
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'releasability', p_releasability);
  END set_session;

  PROCEDURE clear_session IS
  BEGIN
    DBMS_SESSION.CLEAR_CONTEXT('coalition_ctx');
  END clear_session;

  PROCEDURE set_program(p_programs IN VARCHAR2) IS
  BEGIN
    -- Comma-separated list of program_id values. Examples:
    --   'BOXER-MOD'                       — engineer scoped to one program
    --   'BOXER-MOD,SPZ-NEXTGEN'           — architect with multi-program access
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'program_list', p_programs);
  END set_program;

  PROCEDURE clear_program IS
  BEGIN
    DBMS_SESSION.CLEAR_CONTEXT('coalition_ctx', NULL, 'program_list');
  END clear_program;
END coalition_ctx_pkg;
/

CREATE OR REPLACE CONTEXT coalition_ctx
  USING coalition_ctx_pkg;

-- ---------------------------------------------------------------------
-- 2. Clearance hierarchy lookup (ordered, fail-closed)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clearance_hierarchy (
  level_code   VARCHAR2(20) PRIMARY KEY,
  level_rank   NUMBER       NOT NULL UNIQUE,
  description  VARCHAR2(200)
);

MERGE INTO clearance_hierarchy t
USING (
  SELECT 'UNCLASSIFIED'  AS level_code, 0 AS level_rank, 'Open / non-sensitive' AS description FROM DUAL UNION ALL
  SELECT 'RESTRICTED',     1, 'VS-NfD equivalent'                  FROM DUAL UNION ALL
  SELECT 'CONFIDENTIAL',   2, 'VS-Vertraulich equivalent'          FROM DUAL UNION ALL
  SELECT 'SECRET',         3, 'VS-Geheim equivalent'               FROM DUAL UNION ALL
  SELECT 'TOP_SECRET',     4, 'VS-Streng-Geheim equivalent'        FROM DUAL
) s ON (t.level_code = s.level_code)
WHEN NOT MATCHED THEN INSERT (level_code, level_rank, description)
                      VALUES (s.level_code, s.level_rank, s.description);
COMMIT;

-- ---------------------------------------------------------------------
-- 3. Reusable VPD policy function
--    Each protected object must carry columns:
--      - clearance_required (FK to clearance_hierarchy.level_code)
--      - releasable_to      (VARCHAR2: NATO, EU, FVEY, ALL_COALITION, or comma list of nation codes)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION coalition_security_policy(
  p_schema IN VARCHAR2,
  p_object IN VARCHAR2
) RETURN VARCHAR2 AS
  l_clearance     VARCHAR2(50);
  l_clearance_rank NUMBER;
  l_nation        VARCHAR2(10);
  l_releasability VARCHAR2(100);
  l_predicate     VARCHAR2(4000);
BEGIN
  l_clearance     := SYS_CONTEXT('coalition_ctx', 'clearance_level');
  l_nation        := SYS_CONTEXT('coalition_ctx', 'nation_code');
  l_releasability := SYS_CONTEXT('coalition_ctx', 'releasability');

  -- Fail closed if context is unset
  IF l_clearance IS NULL OR l_nation IS NULL THEN
    RETURN '1=0';
  END IF;

  -- Resolve clearance rank
  BEGIN
    SELECT level_rank INTO l_clearance_rank
    FROM clearance_hierarchy
    WHERE level_code = l_clearance;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN RETURN '1=0';
  END;

  -- Build predicate:
  --   row.clearance_required must be <= session clearance
  --   row.releasable_to must:
  --     - be a "common coalition" group visible to any in-coalition session
  --       ('PUBLIC','NATO','EU','ALL_COALITION','ALL'), OR
  --     - include the session's nation as a comma-list element, OR
  --     - exactly equal the session's releasability tag.
  --   The common-coalition whitelist mirrors the v1 (PR-#54) behaviour
  --   that UC10's verify-coalition-vpd.sh expects (Bob FRA/EU sees
  --   SPZ-NEXTGEN rows tagged releasable_to='NATO').
  l_predicate :=
    '(SELECT level_rank FROM ' || p_schema || '.clearance_hierarchy WHERE level_code = clearance_required) <= ' || l_clearance_rank ||
    ' AND (' ||
    '  releasable_to IN (''PUBLIC'',''NATO'',''EU'',''ALL_COALITION'',''ALL'')' ||
    '  OR INSTR('','' || releasable_to || '','', '','' || ''' || l_nation || ''' || '','') > 0' ||
    '  OR releasable_to = ''' || l_releasability || '''' ||
    ')';

  RETURN l_predicate;
END coalition_security_policy;
/

-- ---------------------------------------------------------------------
-- 4. Helper macro to attach the policy to a view/MV/table
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE attach_coalition_policy(
  p_schema IN VARCHAR2,
  p_object IN VARCHAR2
) AS
BEGIN
  DBMS_RLS.ADD_POLICY(
    object_schema    => p_schema,
    object_name      => p_object,
    policy_name      => p_object || '_COALITION_POL',
    function_schema  => USER,
    policy_function  => 'COALITION_SECURITY_POLICY',
    statement_types  => 'SELECT',
    policy_type      => DBMS_RLS.CONTEXT_SENSITIVE,
    update_check     => FALSE
  );
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -28101 THEN  -- policy already exists
      NULL;
    ELSE
      RAISE;
    END IF;
END attach_coalition_policy;
/

-- ---------------------------------------------------------------------
-- 5. Smoke test (run interactively)
-- ---------------------------------------------------------------------
-- Session A (DEU, RESTRICTED, NATO)
--   EXEC coalition_ctx_pkg.set_session('alice', 'RESTRICTED', 'DEU', 'NATO');
--   SELECT * FROM <protected_view>;
--
-- Session B (FRA, CONFIDENTIAL, NATIONAL_ONLY)
--   EXEC coalition_ctx_pkg.set_session('bob', 'CONFIDENTIAL', 'FRA', 'NATIONAL_ONLY');
--   SELECT * FROM <protected_view>;
--
-- Same query, different visibility — that's the DICE-EU demo highlight.

-- ---------------------------------------------------------------------
-- 6. UC10 program-isolation layer.
--
-- Adds a second VPD predicate that filters on coalition_ctx.program_list.
-- Composed with coalition_security_policy via requirements_security_policy
-- (which lives next to its consumers in industrial/10-requirements-
-- intelligence/schema/04_security.sql for cohesion).
--
-- Plus a backwards-compat shim — earlier UC10 drops referenced a
-- standalone coalition_ctx_set_program proc, this delegates to the
-- package method so existing scripts (verify-coalition-vpd.sh) keep
-- working.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION program_security_policy(
  p_schema IN VARCHAR2,
  p_object IN VARCHAR2
) RETURN VARCHAR2 AS
  l_program_list VARCHAR2(4000);
BEGIN
  l_program_list := SYS_CONTEXT('coalition_ctx', 'program_list');
  IF l_program_list IS NULL THEN
    RETURN '1=0';   -- fail-closed: no program context, no rows
  END IF;
  RETURN 'program_id IN (SELECT TRIM(REGEXP_SUBSTR(''' || l_program_list ||
         ''', ''[^,]+'', 1, LEVEL)) FROM dual ' ||
         'CONNECT BY LEVEL <= REGEXP_COUNT(''' || l_program_list || ''', '','') + 1)';
END program_security_policy;
/

CREATE OR REPLACE PROCEDURE coalition_ctx_set_program(p_programs IN VARCHAR2) AS
BEGIN
  coalition_ctx_pkg.set_program(p_programs);
END;
/

PROMPT coalition_ctx_bootstrap complete.
