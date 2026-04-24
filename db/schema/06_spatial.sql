--==============================================================================
-- File:        06_spatial.sql
-- Purpose:     Spatial metadata, spatial indexes and example spatial queries
--              for the Sovereign Defence Intelligence Platform.
--
--              Two SDO_GEOMETRY columns are indexed:
--                * satellite_scenes.footprint  (POLYGON, WGS84 / SRID 4326)
--                * sc_nodes.location           (POINT,   WGS84 / SRID 4326)
--
-- Target:      Oracle AI Database 26ai (SPATIAL_INDEX_V2)
-- Depends on:  02_core_tables.sql (satellite_scenes, sc_nodes)
--
-- Notes:
--   * All geometries are WGS84 (SRID 4326) — longitude/latitude.
--   * user_sdo_geom_metadata entries must exist before creating spatial
--     indexes; we DELETE any stale rows first for idempotent re-runs.
--==============================================================================

SET DEFINE OFF;

--------------------------------------------------------------------------------
-- 1) SDO metadata — delete any previous rows, then insert fresh entries
--------------------------------------------------------------------------------
DELETE FROM user_sdo_geom_metadata
 WHERE table_name IN ('SATELLITE_SCENES', 'SC_NODES');

INSERT INTO user_sdo_geom_metadata (table_name, column_name, diminfo, srid)
VALUES (
    'SATELLITE_SCENES',
    'FOOTPRINT',
    SDO_DIM_ARRAY(
        SDO_DIM_ELEMENT('LONG', -180.0, 180.0, 0.0005),
        SDO_DIM_ELEMENT('LAT',   -90.0,  90.0, 0.0005)
    ),
    4326
);

INSERT INTO user_sdo_geom_metadata (table_name, column_name, diminfo, srid)
VALUES (
    'SC_NODES',
    'LOCATION',
    SDO_DIM_ARRAY(
        SDO_DIM_ELEMENT('LONG', -180.0, 180.0, 0.0005),
        SDO_DIM_ELEMENT('LAT',   -90.0,  90.0, 0.0005)
    ),
    4326
);

COMMIT;

--------------------------------------------------------------------------------
-- 2) Spatial indexes (SPATIAL_INDEX_V2, R-tree based)
--------------------------------------------------------------------------------
CREATE INDEX idx_scene_geom
    ON satellite_scenes (footprint)
    INDEXTYPE IS MDSYS.SPATIAL_INDEX_V2
    PARAMETERS ('layer_gtype=POLYGON');

CREATE INDEX idx_sc_node_geom
    ON sc_nodes (location)
    INDEXTYPE IS MDSYS.SPATIAL_INDEX_V2
    PARAMETERS ('layer_gtype=POINT');

--------------------------------------------------------------------------------
-- 3) Example query — SDO_FILTER
--     All satellite scenes whose footprint intersects a caller-supplied
--     bounding box. SDO_FILTER uses the R-tree index only (primary filter),
--     making it the fastest coarse selector for map-tile viewports.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_scenes_in_bbox (
    p_min_lon IN NUMBER,
    p_min_lat IN NUMBER,
    p_max_lon IN NUMBER,
    p_max_lat IN NUMBER
) RETURN SYS_REFCURSOR
AS
    l_cur  SYS_REFCURSOR;
    l_bbox SDO_GEOMETRY;
BEGIN
    l_bbox := SDO_GEOMETRY(
        2003,
        4326,
        NULL,
        SDO_ELEM_INFO_ARRAY(1, 1003, 3),
        SDO_ORDINATE_ARRAY(p_min_lon, p_min_lat, p_max_lon, p_max_lat)
    );

    OPEN l_cur FOR
        SELECT scene_id,
               captured_at,
               sensor,
               cloud_cover
          FROM satellite_scenes
         WHERE SDO_FILTER(footprint, l_bbox) = 'TRUE'
         ORDER BY captured_at DESC;
    RETURN l_cur;
END fn_scenes_in_bbox;
/

--------------------------------------------------------------------------------
-- 4) Example query — SDO_WITHIN_DISTANCE
--     All supply-chain nodes within N metres of a caller-supplied lon/lat
--     point. Useful for "critical facilities within 50 km of this incident".
--     SRID 4326 is a geodetic SRS, so DISTANCE is interpreted in metres by
--     default.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_sc_nodes_near (
    p_lon         IN NUMBER,
    p_lat         IN NUMBER,
    p_distance_m  IN NUMBER DEFAULT 50000
) RETURN SYS_REFCURSOR
AS
    l_cur   SYS_REFCURSOR;
    l_point SDO_GEOMETRY;
    l_params VARCHAR2(200);
BEGIN
    l_point := SDO_GEOMETRY(
        2001,
        4326,
        SDO_POINT_TYPE(p_lon, p_lat, NULL),
        NULL,
        NULL
    );

    l_params := 'distance=' || TO_CHAR(p_distance_m) || ' unit=METER';

    OPEN l_cur FOR
        SELECT node_id,
               node_type,
               display_name,
               country_iso3,
               criticality
          FROM sc_nodes
         WHERE SDO_WITHIN_DISTANCE(location, l_point, l_params) = 'TRUE'
         ORDER BY criticality DESC;
    RETURN l_cur;
END fn_sc_nodes_near;
/

--------------------------------------------------------------------------------
-- 5) Convenience view: GeoJSON projection of sc_nodes for the frontend map.
--    Uses the native SDO_UTIL.TO_GEOJSON converter introduced in 26ai.
--------------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_sc_nodes_geojson AS
    SELECT node_id,
           tenant_id,
           node_type,
           display_name,
           country_iso3,
           criticality,
           ols_label,
           SDO_UTIL.TO_GEOJSON(location) AS geometry_geojson
      FROM sc_nodes
     WHERE location IS NOT NULL;

COMMENT ON TABLE vw_sc_nodes_geojson IS
  'GeoJSON projection of sc_nodes for the Leaflet/Mapbox frontend.';

--==============================================================================
-- End of 06_spatial.sql
--==============================================================================
