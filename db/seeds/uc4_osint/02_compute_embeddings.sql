-- ===========================================================================
-- UC4_OSINT — Tag 5 (Teil 2): Embeddings für signal_vectors
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1)
--
-- !!  STATUS: BLOCKED — DEFERRED FOR DEMO  !!
-- ---------------------------------------------------------------------------
-- Voraussetzung OCI_GENAI_CRED ist nicht erfüllt: das in-DB-Credential
-- braucht eine OCI-API-Key-Konfiguration (User-OCID + Tenancy + Compartment
-- + Private-Key + Fingerprint), und die `oci setup keys`-Generierung
-- liefert standardmäßig einen passphrasen-verschlüsselten PEM, den
-- DBMS_VECTOR.CREATE_CREDENTIAL nicht akzeptiert. Decrypt-Step
-- (openssl pkcs8 -nocrypt) braucht interaktive Passphrase-Eingabe,
-- die im aktuellen Demo-Setup nicht zuverlässig automatisierbar war.
--
-- Konsequenz: signal_vectors.embedding bleibt NULL.
--   * vector_hybrid_search returns 503 mit klarem retry-after
--   * graph_query, spatial_aggregate, persist_briefing — alle live
--   * Demo-Story trägt die Multi-Correlation-Graph-Query als Hauptbeat
--
-- Roll-Forward: sobald OCI-API-Key in PEM-PKCS#8-unencrypted-Form auf
-- der Dev-VM verfügbar ist, einmalig als ADMIN ausführen:
--
--   BEGIN
--     DBMS_VECTOR.CREATE_CREDENTIAL(
--       credential_name => 'OCI_GENAI_CRED',
--       params => JSON('{
--         "user_ocid":        "ocid1.user.oc1..<dedicated-svc-user>",
--         "tenancy_ocid":     "<tenancy>",
--         "compartment_ocid": "ocid1.compartment.oc1..<oci-defence-demo>",
--         "private_key":      "<PEM body, no BEGIN/END headers>",
--         "fingerprint":      "<aa:bb:...>"
--       }'));
--   END;
--   /
--
-- Danach diese Datei via apply-migration.sh applien — der Pre-Check
-- erkennt das Credential und füllt die 120 NULL-Embeddings.
-- ===========================================================================
--
-- Geltungsbereich (sobald entsperrt):
--   Berechnet die fehlenden VECTOR(1024,FLOAT32)-Embeddings in
--   signal_vectors via DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING gegen
--   Cohere multilingual-v3.0 (volle Variante, 1024 dim) im
--   OCI-Generative-AI-Service eu-frankfurt-1.
--
--   Embedding-Quelle pro Zeile: title || ' — ' || summary aus
--   signal_normalized. summary kann NULL sein → Fallback nur title.
--
-- Idempotenz:
--   Nur Rows wo signal_vectors.embedding IS NULL werden angefasst.
--   Ein zweiter Run ist No-Op. Bei einer einzelnen Embedding-Failure
--   wird die Zeile übersprungen (gelogged) und die nächste verarbeitet
--   — die UPDATE läuft pro Zeile in einer eigenen impliziten
--   Transaktion (PL/SQL bulk-fetch + autonomous commit pro Batch).
--
-- ===========================================================================
-- VORAUSSETZUNG: OCI-GenAI-Credential im DB
-- ===========================================================================
-- DBMS_VECTOR_CHAIN braucht eine vorab konfigurierte Credential, die der
-- DB API-Key-basierten Zugriff auf den OCI-GenAI-Endpoint gibt. Auf
-- ATP-Shared geht das nicht via Instance Principal (das hat nur die
-- Dev-VM, nicht die DB selbst). Daher einmalig als ADMIN ausführen:
--
--   BEGIN
--     DBMS_VECTOR.CREATE_CREDENTIAL(
--       credential_name => 'OCI_GENAI_CRED',
--       params          => JSON('{
--         "user_ocid":        "<ocid1.user.oc1...>",
--         "tenancy_ocid":     "ocid1.tenancy.oc1..aaaaaaaaljjkqnhc6exmzulbb7ki4qf7mxswjbpgahraojzccnxwm3o3htvq",
--         "compartment_ocid": "ocid1.compartment.oc1..aaaaaaaamcjaobwgnwwwkaphfzuzavq2dez6jkonahdwsn6ys7apqgiqelmq",
--         "private_key":      "<RSA-PEM-Body, ohne BEGIN/END-Header>",
--         "fingerprint":      "<XX:XX:...>"
--       }'));
--   END;
--   /
--
-- Die `private_key`/`fingerprint` müssen zu einem konfigurierten OCI-User
-- gehören, der die Policy "use generative-ai-family" im Compartment hat
-- (siehe defence-demo-genai-policy aus Skill oci-crossplane). Empfehlung:
-- dedizierter Service-User "uc4-osint-genai-svc" mit minimal-Privilegien.
--
-- Der eigentliche Endpoint wird nicht in der Credential, sondern im
-- profile-Parameter unten angegeben. eu-frankfurt-1 ist hardcoded —
-- niemals in eine andere Region routen (Sovereignty-Regel).
--
-- Wenn OCI_GENAI_CRED fehlt oder unbrauchbar ist:
--   * Pre-Check unten raised ORA-20007 mit klarer Anleitung.
--   * Der Seed-Run kann ohne Embeddings ausgeliefert werden — Vector-
--     Search-Demos brauchen sie, der Rest der UC4-Pipeline funktioniert
--     auch mit embedding=NULL (IVF-Index toleriert NULL-Rows).
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

-- ---------------------------------------------------------------------------
-- (1) Pre-Check: Credential vorhanden?
-- ---------------------------------------------------------------------------
DECLARE
  v_cnt NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_cnt FROM all_credentials
   WHERE credential_name = 'OCI_GENAI_CRED';
  IF v_cnt = 0 THEN
    RAISE_APPLICATION_ERROR(-20007,
      '02_compute_embeddings.sql: Credential OCI_GENAI_CRED fehlt. '
      ||'Siehe Header-Kommentar für DBMS_VECTOR.CREATE_CREDENTIAL-Beispiel. '
      ||'Bis dahin ist embedding=NULL akzeptabel — Vector-Search-Demos '
      ||'sind dann allerdings deaktiviert.');
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (2) Embeddings berechnen pro Zeile mit embedding IS NULL
--
-- DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING signature:
--   FUNCTION UTL_TO_EMBEDDING (
--     DATA   IN CLOB,
--     PARAMS IN JSON
--   ) RETURN VECTOR;
--
-- params ist eine JSON-Konfiguration; für OCI Generative AI (Cohere v3):
--   {
--     "provider": "OCIGenAI",
--     "credential_name": "OCI_GENAI_CRED",
--     "url":      "https://inference.generativeai.eu-frankfurt-1.oci.oraclecloud.com/20231130/actions/embedText",
--     "model":    "cohere.embed-multilingual-v3.0",
--     "input_type": "SEARCH_DOCUMENT"
--   }
--
-- Cohere unterscheidet input_type SEARCH_DOCUMENT vs SEARCH_QUERY —
-- für den Seed (alle Zeilen sind Dokumente) ist SEARCH_DOCUMENT korrekt.
-- ---------------------------------------------------------------------------
DECLARE
  c_genai_params CONSTANT JSON := JSON('{
    "provider":        "OCIGenAI",
    "credential_name": "OCI_GENAI_CRED",
    "url":             "https://inference.generativeai.eu-frankfurt-1.oci.oraclecloud.com/20231130/actions/embedText",
    "model":           "cohere.embed-multilingual-v3.0",
    "input_type":      "SEARCH_DOCUMENT"
  }');

  v_total_to_embed NUMBER;
  v_done           NUMBER := 0;
  v_failed         NUMBER := 0;
  v_text           CLOB;
  v_vec            VECTOR;
  v_event_id       RAW(16);

  CURSOR c_pending IS
    SELECT sv.event_id, sn.title, sn.summary
      FROM signal_vectors sv
      JOIN signal_normalized sn ON sn.event_id = sv.event_id
     WHERE sv.embedding IS NULL
       AND sn.source_provider = 'seed:uc4-demo'
     ORDER BY sn.observed_at;
BEGIN
  SELECT COUNT(*) INTO v_total_to_embed
    FROM signal_vectors sv
    JOIN signal_normalized sn ON sn.event_id = sv.event_id
   WHERE sv.embedding IS NULL
     AND sn.source_provider = 'seed:uc4-demo';

  IF v_total_to_embed = 0 THEN
    DBMS_OUTPUT.PUT_LINE('02_compute_embeddings.sql: nothing to embed (all rows already have vectors).');
    RETURN;
  END IF;

  DBMS_OUTPUT.PUT_LINE('02_compute_embeddings.sql: '||v_total_to_embed||' rows to embed.');

  FOR r IN c_pending LOOP
    BEGIN
      v_text := r.title;
      IF r.summary IS NOT NULL THEN
        v_text := v_text || ' — ' || r.summary;
      END IF;

      v_vec := DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING(
                 DATA   => v_text,
                 PARAMS => c_genai_params);

      UPDATE signal_vectors
         SET embedding   = v_vec,
             embedded_at = SYSTIMESTAMP
       WHERE event_id = r.event_id
         AND embedding IS NULL;

      COMMIT;
      v_done := v_done + 1;

      -- Heartbeat alle 20 Zeilen, sonst stiller-Spinner-Eindruck
      IF MOD(v_done, 20) = 0 THEN
        DBMS_OUTPUT.PUT_LINE('  ... '||v_done||'/'||v_total_to_embed||' embedded');
      END IF;
    EXCEPTION
      WHEN OTHERS THEN
        v_failed := v_failed + 1;
        DBMS_OUTPUT.PUT_LINE(
          '  WARN: failed to embed event_id='||RAWTOHEX(r.event_id)
          ||' — '||SUBSTR(SQLERRM, 1, 120));
        -- Pro-Row-Fehler: nicht abbrechen, weitermachen
        ROLLBACK;
    END;
  END LOOP;

  DBMS_OUTPUT.PUT_LINE(
    '02_compute_embeddings.sql done: '||v_done||' embedded, '||v_failed||' failed.');
END;
/

-- ---------------------------------------------------------------------------
-- Tail-Sanity: wie viele NULL-embeddings sind noch übrig?
-- (Akzeptabel: 0 wenn Credential funktioniert; alles > 0 ist ein Failure-
-- Indikator. Wir raisen NICHT — der Seed soll auch bei teilweise-erfolgten
-- Embeddings nutzbar sein.)
-- ---------------------------------------------------------------------------
DECLARE
  v_remaining NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_remaining
    FROM signal_vectors sv
    JOIN signal_normalized sn ON sn.event_id = sv.event_id
   WHERE sv.embedding IS NULL
     AND sn.source_provider = 'seed:uc4-demo';

  IF v_remaining > 0 THEN
    DBMS_OUTPUT.PUT_LINE(
      '02_compute_embeddings.sql sanity: '||v_remaining
      ||' rows still NULL — re-run after fixing credential / network / quota.');
  ELSE
    DBMS_OUTPUT.PUT_LINE(
      '02_compute_embeddings.sql sanity OK: 0 NULL embeddings remaining.');
  END IF;
END;
/
