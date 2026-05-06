-- =====================================================================
-- ai_profile_template.sql
-- Shared Select AI profiles for defence-industrial use cases.
--
-- Two profiles:
--   - DEFENCE_GENAI_EU      → OCI Generative AI in eu-frankfurt-1 (default)
--   - DEFENCE_PRIVATE_LLM   → Private AI Services Container (VS-NfD)
--
-- Run as DEFENCE_ADMIN. Substitute :variables before running.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Credential for OCI Generative AI (resource principal preferred)
-- ---------------------------------------------------------------------
BEGIN
  -- For demo: API key based. Production: use resource principal via
  -- DBMS_CLOUD.ENABLE_RESOURCE_PRINCIPAL on the ADB.
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'OCI_GENAI_CRED',
    user_ocid       => '&OCI_USER_OCID',
    tenancy_ocid    => '&OCI_TENANCY_OCID',
    private_key     => '&OCI_API_KEY_PEM',
    fingerprint     => '&OCI_API_KEY_FINGERPRINT'
  );
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -20022 THEN NULL; -- already exists
    ELSE RAISE; END IF;
END;
/

-- ---------------------------------------------------------------------
-- Profile 1: OCI Generative AI EU (default)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD_AI.DROP_PROFILE(profile_name => 'DEFENCE_GENAI_EU', force => TRUE);
EXCEPTION WHEN OTHERS THEN NULL; END;
/

BEGIN
  DBMS_CLOUD_AI.CREATE_PROFILE(
    profile_name => 'DEFENCE_GENAI_EU',
    attributes   => '{
      "provider":         "oci",
      "credential_name":  "OCI_GENAI_CRED",
      "region":           "eu-frankfurt-1",
      "model":            "cohere.command-r-plus-08-2024",
      "embedding_model":  "cohere.embed-multilingual-v3.0",
      "comments":         "true",
      "annotations":      "true",
      "vector_index_type":"HNSW",
      "max_tokens":       4096,
      "temperature":      0.2
    }'
  );
END;
/

-- ---------------------------------------------------------------------
-- Profile 2: Private LLM via vLLM/Ollama (VS-NfD fallback)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'PRIVATE_LLM_CRED',
    username        => '&PRIVATE_LLM_USER',
    password        => '&PRIVATE_LLM_TOKEN'
  );
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -20022 THEN NULL;
    ELSE RAISE; END IF;
END;
/

BEGIN
  DBMS_CLOUD_AI.DROP_PROFILE(profile_name => 'DEFENCE_PRIVATE_LLM', force => TRUE);
EXCEPTION WHEN OTHERS THEN NULL; END;
/

BEGIN
  DBMS_CLOUD_AI.CREATE_PROFILE(
    profile_name => 'DEFENCE_PRIVATE_LLM',
    attributes   => '{
      "provider":         "openai",
      "credential_name":  "PRIVATE_LLM_CRED",
      "endpoint":         "&PRIVATE_LLM_ENDPOINT",
      "model":            "meta-llama/Llama-3.3-70B-Instruct",
      "comments":         "true",
      "annotations":      "true",
      "max_tokens":       4096,
      "temperature":      0.1
    }'
  );
END;
/

PROMPT ai_profile_template complete. Verify with: SELECT profile_name FROM DBA_CLOUD_AI_PROFILES;
