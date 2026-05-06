-- =====================================================================
-- UC #2 Quality & Incident Analysis — Step 4: Augment Security
-- =====================================================================
-- Quality data has additional plant-level access control on top of
-- coalition VPD. We compose the policies via plant_access_v.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 4a. Plant access table (who can see which plant)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plant_access (
  user_id    VARCHAR2(100),
  plant_code VARCHAR2(10),
  CONSTRAINT plant_access_pk PRIMARY KEY (user_id, plant_code)
);

-- ---------------------------------------------------------------------
-- 4b. Custom VPD function combining coalition + plant access
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION quality_security_policy(
  p_schema IN VARCHAR2, p_object IN VARCHAR2
) RETURN VARCHAR2 AS
  l_user      VARCHAR2(100);
  l_coalition VARCHAR2(4000);
BEGIN
  -- Reuse the shared coalition predicate
  l_coalition := coalition_security_policy(p_schema, p_object);
  IF l_coalition = '1=0' THEN RETURN '1=0'; END IF;

  l_user := SYS_CONTEXT('coalition_ctx', 'user_id');
  IF l_user IS NULL THEN RETURN '1=0'; END IF;

  RETURN '(' || l_coalition || ')' ||
         ' AND plant_code IN (SELECT plant_code FROM ' || p_schema ||
         '.plant_access WHERE user_id = ''' || l_user || ''')';
END quality_security_policy;
/

-- ---------------------------------------------------------------------
-- 4c. Attach
-- ---------------------------------------------------------------------
BEGIN
  DBMS_RLS.ADD_POLICY(
    object_schema   => USER, object_name => 'NCR_RECENT_MV',
    policy_name     => 'NCR_RECENT_MV_QUAL_POL',
    function_schema => USER, policy_function => 'QUALITY_SECURITY_POLICY',
    statement_types => 'SELECT', policy_type => DBMS_RLS.CONTEXT_SENSITIVE
  );
  DBMS_RLS.ADD_POLICY(
    object_schema   => USER, object_name => 'SPC_HOURLY_MV',
    policy_name     => 'SPC_HOURLY_MV_QUAL_POL',
    function_schema => USER, policy_function => 'QUALITY_SECURITY_POLICY',
    statement_types => 'SELECT', policy_type => DBMS_RLS.CONTEXT_SENSITIVE
  );
EXCEPTION WHEN OTHERS THEN IF SQLCODE = -28101 THEN NULL; ELSE RAISE; END IF; END;
/

PROMPT UC2 step 4 (security) complete.
