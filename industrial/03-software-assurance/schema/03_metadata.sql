-- =====================================================================
-- UC #3 Software Assurance — Step 3: Augment Metadata
-- =====================================================================

COMMENT ON MATERIALIZED VIEW requirements_mv IS
  'Software requirements federated from Polarion. Refreshed every 30 minutes. Each requirement has a project_id, status (DRAFT, REVIEWED, APPROVED, IMPLEMENTED, VERIFIED), priority, and classification.';
COMMENT ON TABLE test_cases_mv IS
  'Test case catalog. test_type: UNIT, INTEGRATION, SYSTEM, ACCEPTANCE. automation_level: MANUAL, SEMI_AUTO, AUTO.';
COMMENT ON TABLE test_results_mv IS
  'Test execution results. outcome is PASS, FAIL, BLOCKED, or SKIP. evidence_doc_id links to artefacts in Object Storage (logs, screenshots, signed protocols).';
COMMENT ON TABLE defects_mv IS
  'Defect tracker entries. severity 1=trivial..5=safety-critical. found_in_test is the test_id that surfaced the defect.';
COMMENT ON TABLE req_test_link IS
  'Many-to-many traceability link between requirements and test cases. The basis of the requirements-traceability-matrix (RTM).';

COMMENT ON COLUMN requirements_mv.status IS
  'Lifecycle state. Only APPROVED requirements may be implemented. Only VERIFIED requirements satisfy the SOW.';
COMMENT ON COLUMN test_results_mv.evidence_doc_id IS
  'Foreign reference to a document in Object Storage that contains the signed test evidence. Required for AS9100 / safety case.';

PROMPT UC3 step 3 (metadata) complete.
