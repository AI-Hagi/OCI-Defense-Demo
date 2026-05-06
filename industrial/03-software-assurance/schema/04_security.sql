-- =====================================================================
-- UC #3 Software Assurance — Step 4: Augment Security
-- =====================================================================
-- Project-level access (engineers see only the projects they're on)
-- composed with coalition VPD.
-- =====================================================================

CREATE TABLE IF NOT EXISTS project_access (
  user_id    VARCHAR2(100),
  project_id VARCHAR2(40),
  role       VARCHAR2(30),  -- VIEWER, ENGINEER, ARCHITECT, AUDITOR
  CONSTRAINT project_access_pk PRIMARY KEY (user_id, project_id)
);

CREATE OR REPLACE FUNCTION swassure_security_policy(
  p_schema IN VARCHAR2, p_object IN VARCHAR2
) RETURN VARCHAR2 AS
  l_user      VARCHAR2(100);
  l_coalition VARCHAR2(4000);
BEGIN
  l_coalition := coalition_security_policy(p_schema, p_object);
  IF l_coalition = '1=0' THEN RETURN '1=0'; END IF;

  l_user := SYS_CONTEXT('coalition_ctx', 'user_id');
  IF l_user IS NULL THEN RETURN '1=0'; END IF;

  RETURN '(' || l_coalition || ')' ||
         ' AND project_id IN (SELECT project_id FROM ' || p_schema ||
         '.project_access WHERE user_id = ''' || l_user || ''')';
END;
/

DECLARE
  TYPE name_arr IS TABLE OF VARCHAR2(40);
  v_objects name_arr := name_arr(
    'REQUIREMENTS_MV', 'TEST_CASES_MV', 'TEST_RESULTS_MV', 'DEFECTS_MV'
  );
BEGIN
  FOR i IN 1 .. v_objects.COUNT LOOP
    BEGIN
      DBMS_RLS.ADD_POLICY(
        object_schema   => USER, object_name => v_objects(i),
        policy_name     => v_objects(i) || '_SWA_POL',
        function_schema => USER, policy_function => 'SWASSURE_SECURITY_POLICY',
        statement_types => 'SELECT', policy_type => DBMS_RLS.CONTEXT_SENSITIVE
      );
    EXCEPTION
      WHEN OTHERS THEN IF SQLCODE = -28101 THEN NULL; ELSE RAISE; END IF;
    END;
  END LOOP;
END;
/

PROMPT UC3 step 4 (security) complete.
