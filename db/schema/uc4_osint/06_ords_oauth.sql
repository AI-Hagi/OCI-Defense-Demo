-- ===========================================================================
-- UC4_OSINT — Tag 6b: ORDS OAuth2 client_credentials für Threat-Fusion-Agent
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1)
--
-- Geltungsbereich:
--   Sperrt die vier Tool-Endpoints aus 05_ords_tools.sql hinter eine
--   OAuth2-client_credentials-Authentifizierung. Drei Schritte:
--
--     1) ORDS-Role 'uc4_tool_user' anlegen
--     2) ORDS-Privilege 'uc4.tools.invoke' definieren, die das Module
--        api.v1.tools UND alle Pattern unter /api/v1/tools/* an die Role
--        bindet
--     3) OAuth2-Client 'threat_fusion_agent_client' anlegen, der die
--        Privilege automatisch erbt
--
--   Nach Apply:
--     * Direkter POST gegen /ords/uc4_osint/api/v1/tools/<X> ohne
--       Authorization-Header → 401
--     * Mit gültigem Bearer-Token vom /ords/uc4_osint/oauth/token-Endpoint
--       → 200 wie vor Tag 6b
--
--   Token-Flow für den Agent:
--       POST /ords/uc4_osint/oauth/token
--       Authorization: Basic base64(client_id:client_secret)
--       Body: grant_type=client_credentials
--       Response: {"access_token":"...","token_type":"bearer","expires_in":3600}
--
-- Voraussetzungen:
--   * 05_ords_tools.sql appliziert (Module + 4 Templates + 4 Handlers existieren)
--   * Connection als UC4_OSINT (Schema-Owner besitzt das ORDS-Module
--     und darf eigene Privilegien/Roles/Clients verwalten)
--
-- Idempotenz:
--   Jede ORDS-API mit BEGIN..EXCEPTION-Block. Geschluckte Codes:
--     ORA-20999  generic ORDS "already exists"
--     ORA-1442 / ORA-955  duplicate role/object
--     SQLERRM enthält "already exists" / "duplicate"
--   Andere Fehler werden re-raised.
--
-- Client-Secret-Behandlung:
--   ORDS.CREATE_CLIENT generiert client_id + client_secret und speichert
--   beide in USER_ORDS_CLIENTS. Das Secret ist in der View NUR EINMAL
--   sichtbar (im Klartext für den Initial-Setup); danach gehasht.
--   Der Tail-Sanity-Block extrahiert beide Werte und gibt sie via
--   DBMS_OUTPUT aus, damit der Operator sie in OCI Vault stashen kann.
--
--   ⚠ ABER: dieser File wird via apply-migration.sh remote ausgeführt.
--   Das Secret landet im SQL*Plus-Output, der vom Apply-Skript wieder
--   in stdout geschrieben wird. Für eine echte Production-Provisionierung
--   sollte der File als Teil eines Crossplane-Composition-Steps laufen,
--   der das Secret direkt nach OCI Vault streamt und nicht logged.
--
--   Für die Demo-Provisionierung ist der DBMS_OUTPUT-Pfad akzeptabel —
--   der Operator stashed das Secret manuell ins Vault und shred't den
--   Apply-Log.
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

-- ---------------------------------------------------------------------------
-- (1) Role
-- ---------------------------------------------------------------------------
BEGIN
  ORDS.CREATE_ROLE(p_role_name => 'uc4_tool_user');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Role uc4_tool_user created.');
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE = -20999
     OR SQLERRM LIKE '%already exists%'
     OR SQLERRM LIKE '%duplicate%'
  THEN
    DBMS_OUTPUT.PUT_LINE('Role uc4_tool_user already exists — skipping.');
  ELSE
    RAISE;
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (2) Privilege bound to the api.v1.tools module + /api/v1/tools/* patterns
--
-- ORDS.DEFINE_PRIVILEGE on this ORDS version takes OWA.VC_ARR
-- (TABLE OF VARCHAR2(32767) INDEX BY BINARY_INTEGER) for roles/patterns/
-- modules — strings won't bind. Build associative arrays inline.
-- ---------------------------------------------------------------------------
DECLARE
  l_roles    OWA.VC_ARR;
  l_patterns OWA.VC_ARR;
  l_modules  OWA.VC_ARR;
BEGIN
  l_roles(1)    := 'uc4_tool_user';
  l_patterns(1) := '/api/v1/tools/*';
  l_modules(1)  := 'api.v1.tools';

  ORDS.DEFINE_PRIVILEGE(
    p_privilege_name => 'uc4.tools.invoke',
    p_roles          => l_roles,
    p_patterns       => l_patterns,
    p_modules        => l_modules,
    p_label          => 'UC4 Tools',
    p_description    => 'Privilege to invoke the four UC4 ORDS tools '
                        ||'(graph_query, spatial_aggregate, persist_briefing, '
                        ||'vector_hybrid_search). Held by the Threat-Fusion-Agent '
                        ||'OAuth2 client.');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Privilege uc4.tools.invoke defined.');
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE = -20999
     OR SQLERRM LIKE '%already exists%'
     OR SQLERRM LIKE '%duplicate%'
  THEN
    DBMS_OUTPUT.PUT_LINE('Privilege uc4.tools.invoke already exists — skipping.');
  ELSE
    RAISE;
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (3) OAuth2 client for the Threat-Fusion-Agent
--
-- Client name must match the OAUTH_CLIENT_ID in the agent.yaml's
-- env-template (after we update it post-provisioning to the actual
-- ORDS-generated client_id, which is opaque).
-- ---------------------------------------------------------------------------
BEGIN
  OAUTH.CREATE_CLIENT(
    p_name            => 'threat_fusion_agent_client',
    p_grant_type      => 'client_credentials',
    p_owner           => 'UC4 Threat-Fusion-Agent',
    p_description     => 'OAuth2 client used by the OCI Generative AI Agent '
                         ||'Factory deployment of threat-fusion-agent (Tag 7) '
                         ||'to authenticate requests to the four UC4 ORDS tools.',
    p_support_email   => 'security@cloudebility.com',
    p_privilege_names => 'uc4.tools.invoke');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('OAuth client threat_fusion_agent_client created.');
EXCEPTION WHEN OTHERS THEN
  -- ORDS_METADATA.OAUTH_CLIENTS_UNIQUE1 raises ORA-00001 on re-create.
  IF SQLCODE = -1                        -- ORA-00001 unique constraint
     OR SQLCODE = -20999
     OR SQLERRM LIKE '%already exists%'
     OR SQLERRM LIKE '%duplicate%'
     OR SQLERRM LIKE '%unique constraint%'
  THEN
    DBMS_OUTPUT.PUT_LINE('Client threat_fusion_agent_client already exists — skipping.');
  ELSE
    RAISE;
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (3b) Bind the client to the role so the bearer token is recognised.
--
--   OAUTH.CREATE_CLIENT(p_privilege_names => ...) registers the privilege
--   against the client, but on this ORDS version that is NOT sufficient
--   to make a `client_credentials`-issued bearer token validate against
--   the protected URL — the validation path checks
--   USER_ORDS_CLIENT_ROLES, which is only populated by an explicit
--   OAUTH.GRANT_CLIENT_ROLE call.
--
--   Without this step, the client gets a token, but every bearer request
--   to /api/v1/tools/* returns 401 with WWW-Authenticate: error="invalid_token".
-- ---------------------------------------------------------------------------
DECLARE
  v_already NUMBER;
BEGIN
  -- OAUTH.GRANT_CLIENT_ROLE silently appends a duplicate row on re-apply
  -- (no unique constraint on USER_ORDS_CLIENT_ROLES). Pre-check so
  -- the file stays cleanly idempotent.
  SELECT COUNT(*) INTO v_already
    FROM user_ords_client_roles
   WHERE client_name = 'threat_fusion_agent_client'
     AND role_name   = 'uc4_tool_user';

  IF v_already > 0 THEN
    DBMS_OUTPUT.PUT_LINE('Client already holds role uc4_tool_user — skipping.');
  ELSE
    OAUTH.GRANT_CLIENT_ROLE(
      p_client_name => 'threat_fusion_agent_client',
      p_role_name   => 'uc4_tool_user');
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Client threat_fusion_agent_client granted role uc4_tool_user.');
  END IF;
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE = -20999
     OR SQLERRM LIKE '%already%'
     OR SQLERRM LIKE '%duplicate%'
  THEN
    DBMS_OUTPUT.PUT_LINE('Client already holds role uc4_tool_user — skipping.');
  ELSE
    RAISE;
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (4) Surface client_id + client_secret for one-time stash to OCI Vault.
--
--     The view USER_ORDS_CLIENTS exposes client_secret in plaintext only
--     during initial-setup window. After it's read once and the operator
--     rotates the secret (via OAUTH.RENEW_CLIENT_SECRET), the column
--     stores a hash. So this DBMS_OUTPUT line is the operator's only
--     non-rotation chance to capture it — they should:
--
--        1. Read the secret from the apply-migration.sh log
--        2. Stash it in OCI Vault as 'oauth-client-secret-uc4-agent'
--        3. shred -u the apply-migration.sh log
--        4. Update agents/uc4-threat-fusion/.env.template with the
--           secret OCID (not the secret value)
-- ---------------------------------------------------------------------------
DECLARE
  v_client_id     VARCHAR2(200);
  v_client_secret VARCHAR2(200);
BEGIN
  SELECT client_id, client_secret
    INTO v_client_id, v_client_secret
    FROM user_ords_clients
   WHERE name = 'threat_fusion_agent_client';

  DBMS_OUTPUT.PUT_LINE('---');
  DBMS_OUTPUT.PUT_LINE('OAuth client provisioned. Stash these in OCI Vault NOW:');
  DBMS_OUTPUT.PUT_LINE('  client_id     = '||v_client_id);
  DBMS_OUTPUT.PUT_LINE('  client_secret = '||v_client_secret);
  DBMS_OUTPUT.PUT_LINE('  token_url     = '||
    'https://G8CC3767E64A14A-SOVDEF26.adb.eu-frankfurt-1.oraclecloudapps.com/ords/uc4_osint/oauth/token');
  DBMS_OUTPUT.PUT_LINE('---');
EXCEPTION
  WHEN NO_DATA_FOUND THEN
    DBMS_OUTPUT.PUT_LINE('WARN: client threat_fusion_agent_client not visible in '
                         ||'user_ords_clients — check ORDS metadata schema.');
END;
/

-- ---------------------------------------------------------------------------
-- Tail-Sanity: privilege + client + role all wired
-- ---------------------------------------------------------------------------
-- USER_ORDS_ROLES uses NAME (not ROLE_NAME) on ORDS v23+.
-- USER_ORDS_CLIENT_PRIVILEGES surfaces the client↔privilege link.
-- USER_ORDS_CLIENT_ROLES surfaces the client↔role link added by step (3b).
DECLARE
  v_role_count       NUMBER;
  v_priv_count       NUMBER;
  v_client_count     NUMBER;
  v_priv_role_count  NUMBER;
  v_priv_mod_count   NUMBER;
  v_client_priv_cnt  NUMBER;
  v_client_role_cnt  NUMBER;
BEGIN
  -- Use presence checks (>= 1), not exact-count, because OAUTH.GRANT_CLIENT_ROLE
  -- on re-apply appends a duplicate row to USER_ORDS_CLIENT_ROLES rather than
  -- erroring, and we can't reliably dedup from this side.

  SELECT COUNT(*) INTO v_role_count
    FROM user_ords_roles WHERE name = 'uc4_tool_user';
  IF v_role_count < 1 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '06_ords_oauth.sql: Role uc4_tool_user fehlt nach apply.');
  END IF;

  SELECT COUNT(*) INTO v_priv_count
    FROM user_ords_privileges WHERE name = 'uc4.tools.invoke';
  IF v_priv_count < 1 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '06_ords_oauth.sql: Privilege uc4.tools.invoke fehlt nach apply.');
  END IF;

  SELECT COUNT(*) INTO v_client_count
    FROM user_ords_clients WHERE name = 'threat_fusion_agent_client';
  IF v_client_count < 1 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '06_ords_oauth.sql: Client threat_fusion_agent_client fehlt nach apply.');
  END IF;

  SELECT COUNT(*) INTO v_priv_role_count
    FROM user_ords_privilege_roles
   WHERE privilege_name = 'uc4.tools.invoke'
     AND role_name      = 'uc4_tool_user';
  IF v_priv_role_count < 1 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '06_ords_oauth.sql: Privilege not bound to role uc4_tool_user.');
  END IF;

  SELECT COUNT(*) INTO v_priv_mod_count
    FROM user_ords_privilege_modules
   WHERE privilege_name = 'uc4.tools.invoke'
     AND module_name    = 'api.v1.tools';
  IF v_priv_mod_count < 1 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '06_ords_oauth.sql: Privilege not bound to module api.v1.tools.');
  END IF;

  SELECT COUNT(*) INTO v_client_priv_cnt
    FROM user_ords_client_privileges
   WHERE client_name = 'threat_fusion_agent_client'
     AND name        = 'uc4.tools.invoke';
  IF v_client_priv_cnt < 1 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '06_ords_oauth.sql: Client not bound to privilege uc4.tools.invoke.');
  END IF;

  SELECT COUNT(*) INTO v_client_role_cnt
    FROM user_ords_client_roles
   WHERE client_name = 'threat_fusion_agent_client'
     AND role_name   = 'uc4_tool_user';
  IF v_client_role_cnt < 1 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '06_ords_oauth.sql: Client not bound to role uc4_tool_user — '
      ||'OAUTH.GRANT_CLIENT_ROLE step (3b) must have failed.');
  END IF;

  DBMS_OUTPUT.PUT_LINE('06_ords_oauth.sql OK: '
    ||'role='||v_role_count
    ||', privilege='||v_priv_count
    ||', client='||v_client_count
    ||', priv↔role='||v_priv_role_count
    ||', priv↔module='||v_priv_mod_count
    ||', client↔priv='||v_client_priv_cnt
    ||', client↔role='||v_client_role_cnt);
END;
/

-- ===========================================================================
-- Done. Folge:
--   1. Operator stash't client_id + client_secret in OCI Vault
--      (oauth-client-uc4-agent-id / oauth-client-uc4-agent-secret).
--   2. agents/uc4-threat-fusion/.env.template wird mit den Vault-OCIDs
--      aktualisiert (siehe BLOCKED #2 dort).
--   3. agent.yaml's auth_config.token_url + client_id_secret_ocid +
--      client_secret_secret_ocid werden produktiv gesetzt.
--   4. Smoke-Test: scripts/test-uc4-tools.sh erweitern um einen
--      vorgelagerten Token-Fetch + Authorization: Bearer Header.
-- ===========================================================================
