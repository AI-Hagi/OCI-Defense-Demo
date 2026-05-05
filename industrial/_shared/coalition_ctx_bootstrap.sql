-- =====================================================================
-- Shared Coalition VPD foundation (UC07/08/09/10).
--
-- Provides:
--   * coalition_ctx_pkg  — package with set_session/clear_session;
--                          handlers for SYS_CONTEXT('coalition_ctx', ...)
--   * coalition_ctx      — application context attached to the package
--   * coalition_security_policy(schema, table) — VPD function returning
--                          a row predicate based on clearance + nation
--                          + releasability set in the session context.
--
-- Idempotent — safe to re-run.
-- =====================================================================

SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

-- ---------------------------------------------------------------------
-- 1. coalition_ctx_pkg — sets/clears the per-session security context.
-- ---------------------------------------------------------------------
CREATE OR REPLACE PACKAGE coalition_ctx_pkg AS
  PROCEDURE set_session(
    p_user_id        IN VARCHAR2,
    p_clearance      IN VARCHAR2,
    p_nation         IN VARCHAR2,
    p_releasability  IN VARCHAR2
  );
  PROCEDURE clear_session;
  -- UC10 program-isolation. Lives in this package (not a standalone
  -- proc) because the application context is bound USING this package
  -- — a standalone proc would get ORA-01031 from DBMS_SESSION.SET_CONTEXT.
  PROCEDURE set_program(p_programs IN VARCHAR2);
  PROCEDURE clear_program;
END coalition_ctx_pkg;
/

CREATE OR REPLACE PACKAGE BODY coalition_ctx_pkg AS
  PROCEDURE set_session(
    p_user_id        IN VARCHAR2,
    p_clearance      IN VARCHAR2,
    p_nation         IN VARCHAR2,
    p_releasability  IN VARCHAR2
  ) IS
  BEGIN
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'user_id',       p_user_id);
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'clearance',     p_clearance);
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'nation',        p_nation);
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'releasability', p_releasability);
  END set_session;

  PROCEDURE clear_session IS
  BEGIN
    DBMS_SESSION.CLEAR_ALL_CONTEXT('coalition_ctx');
  END clear_session;

  PROCEDURE set_program(p_programs IN VARCHAR2) IS
  BEGIN
    -- Comma-separated list of program_id values.
    --   'BOXER-MOD'                       → engineer scoped to one program
    --   'BOXER-MOD,SPZ-NEXTGEN'           → architect with multi-program access
    DBMS_SESSION.SET_CONTEXT('coalition_ctx', 'program_list', p_programs);
  END set_program;

  PROCEDURE clear_program IS
  BEGIN
    DBMS_SESSION.CLEAR_CONTEXT('coalition_ctx', NULL, 'program_list');
  END clear_program;
END coalition_ctx_pkg;
/

-- ---------------------------------------------------------------------
-- 2. Application context — attached to coalition_ctx_pkg.
-- ---------------------------------------------------------------------
DECLARE
  l_count NUMBER;
BEGIN
  -- USER_CONTEXT only shows contexts owned by current user; that's what
  -- ATP allows UC10_APP to introspect.
  SELECT COUNT(*) INTO l_count FROM all_context
   WHERE namespace = 'COALITION_CTX';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE
      'CREATE OR REPLACE CONTEXT coalition_ctx USING coalition_ctx_pkg';
  END IF;
END;
/

-- ---------------------------------------------------------------------
-- 3. coalition_security_policy — base VPD predicate.
--
-- Reads clearance / nation / releasability from coalition_ctx and
-- returns a row-filter predicate compatible with the columns defined
-- on UC10's `requirements` table:
--
--   clearance_required    VARCHAR2(20) DEFAULT 'RESTRICTED'
--   releasable_to         VARCHAR2(100) DEFAULT 'NATO'
--
-- Rows are visible when:
--   1. the session has a context (else fail-closed: '1=0')
--   2. the session's clearance >= row's clearance_required
--   3. the row's releasable_to is one of: 'PUBLIC', 'NATO', 'EU',
--      'ALL', or the session's nation/releasability.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION coalition_security_policy(
  schema_var IN VARCHAR2,
  table_var  IN VARCHAR2
) RETURN VARCHAR2 AS
  l_clearance      VARCHAR2(20);
  l_nation         VARCHAR2(20);
  l_releasability  VARCHAR2(50);
BEGIN
  l_clearance     := SYS_CONTEXT('coalition_ctx', 'clearance');
  l_nation        := SYS_CONTEXT('coalition_ctx', 'nation');
  l_releasability := SYS_CONTEXT('coalition_ctx', 'releasability');

  -- Fail-closed: no context → no rows.
  IF l_clearance IS NULL THEN
    RETURN '1=0';
  END IF;

  -- Clearance ladder: UNCLASSIFIED < RESTRICTED < CONFIDENTIAL < SECRET < TOP_SECRET
  -- Encoded as a numeric scale in the predicate. Higher session clearance
  -- can read at-or-below the row's required level.
  RETURN q'[
    DECODE(clearance_required,
           'UNCLASSIFIED', 1, 'RESTRICTED', 2,
           'CONFIDENTIAL', 3, 'SECRET',     4,
           'TOP_SECRET',   5, 99)
    <=
    DECODE(']' || l_clearance || q'[',
           'UNCLASSIFIED', 1, 'RESTRICTED', 2,
           'CONFIDENTIAL', 3, 'SECRET',     4,
           'TOP_SECRET',   5, 0)
  ]' ||
  ' AND (releasable_to IN (''PUBLIC'',''NATO'',''EU'',''ALL'') ' ||
  '       OR releasable_to = ''' || NVL(l_nation, '___') || ''' ' ||
  '       OR releasable_to = ''' || NVL(l_releasability, '___') || ''')';
END coalition_security_policy;
/

PROMPT shared coalition_ctx + coalition_security_policy installed.
