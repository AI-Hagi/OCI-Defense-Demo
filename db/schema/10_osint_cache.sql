--==============================================================================
-- File:        10_osint_cache.sql
-- Purpose:     Generic cache table for Sovereign Proxy Pattern-A layers
--              (REST-poll layers like GPS Jamming, Sentinel-2, OpenSky, etc.).
--              Each row is one fetched-and-transformed payload, addressable
--              by `layer` name. Consumers SELECT the latest row per layer
--              with FETCH FIRST 1 ROWS ONLY.
--
-- Target:      Oracle AI Database 26ai (Autonomous Transaction Processing)
-- Depends on:  01_tenants_and_security.sql (no FK — cache is tenant-agnostic)
--              07_audit_compliance.sql      (audit_events table)
--
-- Pattern:     Pattern-A services (e.g. services/jamming-poller) write here
--              on each refresh tick; serving handlers read the latest row.
--              Old rows accumulate but are not auto-pruned (cheap to keep).
--==============================================================================

SET DEFINE OFF;
SET SERVEROUTPUT ON SIZE UNLIMITED;
WHENEVER SQLERROR CONTINUE;

--------------------------------------------------------------------------------
-- 1. osint_cache: layer-name-keyed payload archive
--------------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE osint_cache (
      cache_id         RAW(16)       DEFAULT SYS_GUID() PRIMARY KEY,
      layer            VARCHAR2(60)  NOT NULL,
      fetched_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
      payload          JSON          NOT NULL,
      classification   VARCHAR2(20)  NOT NULL,
      source           VARCHAR2(200) NOT NULL,
      created_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
    )
  ]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -955 THEN
      DBMS_OUTPUT.PUT_LINE('osint_cache exists - skip create');
    ELSE
      DBMS_OUTPUT.PUT_LINE('osint_cache create: '||SQLERRM);
    END IF;
END;
/

--------------------------------------------------------------------------------
-- 2. Index — TTL-style lookup (latest payload by layer name)
--------------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX osint_cache_layer_time_idx
                       ON osint_cache (layer, fetched_at DESC)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -955 OR SQLCODE = -1408 THEN
      DBMS_OUTPUT.PUT_LINE('osint_cache_layer_time_idx exists - skip');
    ELSE
      DBMS_OUTPUT.PUT_LINE('osint_cache_layer_time_idx create: '||SQLERRM);
    END IF;
END;
/

--------------------------------------------------------------------------------
-- 3. Constraint — classification must be one of the OLS-aligned strings
--    (we keep the string form here for human readability of the cache;
--     numeric ols_label is used in audit_events).
--------------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE q'[
    ALTER TABLE osint_cache
      ADD CONSTRAINT osint_cache_classification_chk
      CHECK (classification IN ('OPEN','RESTRICTED','CONFIDENTIAL','SECRET'))
  ]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -2264 OR SQLCODE = -2275 THEN
      DBMS_OUTPUT.PUT_LINE('osint_cache_classification_chk exists - skip');
    ELSE
      DBMS_OUTPUT.PUT_LINE('osint_cache_classification_chk: '||SQLERRM);
    END IF;
END;
/

COMMIT;

--==============================================================================
-- Rollback (manuell, nur wenn explizit erwünscht):
--   DROP TABLE osint_cache PURGE;
--==============================================================================
-- End of 10_osint_cache.sql
--==============================================================================
