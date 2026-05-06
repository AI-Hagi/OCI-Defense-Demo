-- =====================================================================
-- UC #2 Quality & Incident Analysis — Step 5: Create AI Workload
-- =====================================================================
-- Three flavors of AI:
--   - Vector embeddings + k-means clustering on NCR descriptions
--   - OML anomaly detection on SPC hourly aggregates
--   - Select AI RAG over NCR text
-- =====================================================================

-- ---------------------------------------------------------------------
-- 5a. Vector store for NCR descriptions
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ncr_embeddings (
  ncr_id              VARCHAR2(40) PRIMARY KEY,
  plant_code          VARCHAR2(10),
  part_number         VARCHAR2(40),
  defect_category     VARCHAR2(30),
  description         CLOB,
  description_embed   VECTOR(1024, FLOAT32),
  cluster_id          NUMBER,
  clearance_required  VARCHAR2(20),
  releasable_to       VARCHAR2(100)
);

CREATE OR REPLACE PROCEDURE refresh_ncr_embeddings AS
BEGIN
  MERGE INTO ncr_embeddings t
  USING (
    SELECT
      n.ncr_id, n.plant_code, n.part_number, n.defect_category,
      n.description, n.clearance_required, n.releasable_to,
      DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING(
        n.description,
        JSON('{"provider":"oci","credential_name":"OCI_GENAI_CRED",
               "model":"cohere.embed-multilingual-v3.0"}')
      ) AS embed
    FROM ncr_recent_mv n
  ) s
  ON (t.ncr_id = s.ncr_id)
  WHEN MATCHED THEN UPDATE SET
    description_embed  = s.embed,
    plant_code         = s.plant_code,
    part_number        = s.part_number,
    defect_category    = s.defect_category,
    description        = s.description,
    clearance_required = s.clearance_required,
    releasable_to      = s.releasable_to
  WHEN NOT MATCHED THEN INSERT (
    ncr_id, plant_code, part_number, defect_category,
    description, description_embed, clearance_required, releasable_to
  ) VALUES (
    s.ncr_id, s.plant_code, s.part_number, s.defect_category,
    s.description, s.embed, s.clearance_required, s.releasable_to
  );
  COMMIT;
END refresh_ncr_embeddings;
/

CREATE VECTOR INDEX IF NOT EXISTS ncr_hnsw_idx
  ON ncr_embeddings (description_embed)
  ORGANIZATION INMEMORY NEIGHBOR GRAPH
  DISTANCE COSINE WITH TARGET ACCURACY 95
  PARAMETERS (TYPE HNSW, NEIGHBORS 32, EFCONSTRUCTION 200);

-- ---------------------------------------------------------------------
-- 5b. K-means clustering of NCRs (OML)
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE recluster_ncrs(p_num_clusters NUMBER DEFAULT 8) AS
BEGIN
  BEGIN DBMS_DATA_MINING.DROP_MODEL('NCR_CLUSTER_MODEL'); EXCEPTION WHEN OTHERS THEN NULL; END;
  DBMS_DATA_MINING.CREATE_MODEL2(
    model_name           => 'NCR_CLUSTER_MODEL',
    mining_function      => DBMS_DATA_MINING.CLUSTERING,
    data_query           => 'SELECT ncr_id, description_embed FROM ncr_embeddings',
    case_id_column_name  => 'ncr_id',
    set_list             => DBMS_DATA_MINING.SETTING_LIST(
      'ALGO_NAME'           => DBMS_DATA_MINING.ALGO_KMEANS,
      'CLUS_NUM_CLUSTERS'   => TO_CHAR(p_num_clusters)
    )
  );

  UPDATE ncr_embeddings n
  SET cluster_id = (
    SELECT CLUSTER_ID(NCR_CLUSTER_MODEL USING n.description_embed)
    FROM DUAL
  );
  COMMIT;
END recluster_ncrs;
/

-- ---------------------------------------------------------------------
-- 5c. SPC anomaly detection (one-class SVM)
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE retrain_spc_anomaly AS
BEGIN
  BEGIN DBMS_DATA_MINING.DROP_MODEL('SPC_ANOMALY_MODEL'); EXCEPTION WHEN OTHERS THEN NULL; END;
  DBMS_DATA_MINING.CREATE_MODEL2(
    model_name           => 'SPC_ANOMALY_MODEL',
    mining_function      => DBMS_DATA_MINING.CLASSIFICATION,
    data_query           => 'SELECT plant_code, line_code, part_number, parameter_name,
                                    mean_value, stddev_value, oos_count, 1 AS target
                             FROM spc_hourly_mv WHERE oos_count = 0',
    case_id_column_name  => NULL,
    target_column_name   => 'target',
    set_list             => DBMS_DATA_MINING.SETTING_LIST(
      'ALGO_NAME'              => DBMS_DATA_MINING.ALGO_SUPPORT_VECTOR_MACHINES,
      'SVMS_OUTLIER_RATE'      => '0.05'
    )
  );
END retrain_spc_anomaly;
/

CREATE OR REPLACE FUNCTION score_spc_anomalies RETURN SYS_REFCURSOR AS
  c SYS_REFCURSOR;
BEGIN
  OPEN c FOR
    SELECT plant_code, line_code, part_number, parameter_name, hour_bucket,
           mean_value, stddev_value, oos_count,
           PREDICTION(SPC_ANOMALY_MODEL USING *) AS pred,
           PREDICTION_PROBABILITY(SPC_ANOMALY_MODEL USING *) AS prob
    FROM spc_hourly_mv
    WHERE hour_bucket >= SYSTIMESTAMP - INTERVAL '24' HOUR;
  RETURN c;
END;
/

-- ---------------------------------------------------------------------
-- 5d. Select AI profile for the agent
-- ---------------------------------------------------------------------
BEGIN DBMS_CLOUD_AI.DROP_PROFILE(profile_name => 'QUALITY_AGENT', force => TRUE);
EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN
  DBMS_CLOUD_AI.CREATE_PROFILE(
    profile_name => 'QUALITY_AGENT',
    attributes   => '{
      "provider":"oci","credential_name":"OCI_GENAI_CRED",
      "region":"eu-frankfurt-1",
      "model":"cohere.command-r-plus-08-2024",
      "embedding_model":"cohere.embed-multilingual-v3.0",
      "vector_index_name":"ncr_hnsw_idx",
      "object_list":[
        {"owner":"DEFENCE_ADMIN","name":"ncr_recent_mv"},
        {"owner":"DEFENCE_ADMIN","name":"spc_hourly_mv"},
        {"owner":"DEFENCE_ADMIN","name":"ncr_embeddings"}
      ],
      "comments":"true","annotations":"true",
      "max_tokens":4096,"temperature":0.2
    }'
  );
END;
/

-- ---------------------------------------------------------------------
-- 5e. Schedule re-embedding and re-clustering
-- ---------------------------------------------------------------------
BEGIN
  DBMS_SCHEDULER.CREATE_JOB(
    job_name => 'NCR_EMBED_JOB', job_type => 'PLSQL_BLOCK',
    job_action => 'BEGIN refresh_ncr_embeddings; END;',
    repeat_interval => 'FREQ=HOURLY; INTERVAL=1', enabled => TRUE
  );
  DBMS_SCHEDULER.CREATE_JOB(
    job_name => 'NCR_CLUSTER_JOB', job_type => 'PLSQL_BLOCK',
    job_action => 'BEGIN recluster_ncrs(8); END;',
    repeat_interval => 'FREQ=DAILY; BYHOUR=2', enabled => TRUE
  );
EXCEPTION WHEN OTHERS THEN IF SQLCODE = -27477 THEN NULL; ELSE RAISE; END IF; END;
/

PROMPT UC2 step 5 (AI workload) complete.
