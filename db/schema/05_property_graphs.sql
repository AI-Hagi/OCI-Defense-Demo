--==============================================================================
-- File:        05_property_graphs.sql
-- Purpose:     SQL Property Graph definitions for the Sovereign Defence
--              Intelligence Platform. Two graphs are created over the
--              relational base tables from 02_core_tables.sql:
--
--                1) intel_fusion  — OSINT entities and their relationships
--                                   (use case 4: OSINT & Threat Fusion)
--                2) supply_chain  — Supply-chain nodes and directed edges
--                                   (use case 5: Supply Chain Knowledge Graph)
--
--              Graphs are queried with SQL/PGQ via GRAPH_TABLE(...). No data
--              is duplicated: the graph is a view over the base tables.
-- Target:      Oracle AI Database 26ai
-- Depends on:  02_core_tables.sql (osint_entities, osint_relationships,
--              sc_nodes, sc_edges)
--==============================================================================

SET DEFINE OFF;

--------------------------------------------------------------------------------
-- Graph 1: intel_fusion
-- Vertices: osint_entities (label: entity)
-- Edges   : osint_relationships (label: relates_to)
--------------------------------------------------------------------------------
CREATE PROPERTY GRAPH intel_fusion
    VERTEX TABLES (
        osint_entities
            KEY (entity_id)
            LABEL entity
            PROPERTIES ALL COLUMNS
    )
    EDGE TABLES (
        osint_relationships
            KEY (rel_id)
            SOURCE      KEY (src_id) REFERENCES osint_entities (entity_id)
            DESTINATION KEY (dst_id) REFERENCES osint_entities (entity_id)
            LABEL relates_to
            PROPERTIES ALL COLUMNS
    );

--------------------------------------------------------------------------------
-- Graph 2: supply_chain
-- Vertices: sc_nodes (label: sc_node)
-- Edges   : sc_edges (label: sc_flow)
--------------------------------------------------------------------------------
CREATE PROPERTY GRAPH supply_chain
    VERTEX TABLES (
        sc_nodes
            KEY (node_id)
            LABEL sc_node
            PROPERTIES ( node_id, tenant_id, node_type, display_name,
                         country_iso3, criticality, ols_label )
    )
    EDGE TABLES (
        sc_edges
            KEY (edge_id)
            SOURCE      KEY (src_node) REFERENCES sc_nodes (node_id)
            DESTINATION KEY (dst_node) REFERENCES sc_nodes (node_id)
            LABEL sc_flow
            PROPERTIES ALL COLUMNS
    );

--------------------------------------------------------------------------------
-- Example query 1 (intel_fusion)
-- All one-hop relationships where the source entity is a person. Wrapped in a
-- view so ORDS can expose it without the caller having to know SQL/PGQ.
--------------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_intel_fusion_person_edges AS
    SELECT *
      FROM GRAPH_TABLE (
               intel_fusion
               MATCH (a IS entity) -[r IS relates_to]-> (b IS entity)
               WHERE a.kind = 'person'
               COLUMNS (
                   a.canonical_name AS src,
                   r.rel_type       AS rel_type,
                   r.confidence     AS confidence,
                   b.canonical_name AS dst,
                   b.kind           AS dst_kind
               )
           );

COMMENT ON TABLE vw_intel_fusion_person_edges IS
  'SQL/PGQ example: one-hop outgoing relationships from any person entity in the intel_fusion graph.';

--------------------------------------------------------------------------------
-- Example query 2 (supply_chain)
-- Two-hop transitive dependencies between supply-chain nodes of two specific
-- countries. Useful to surface indirect single-source dependencies.
--------------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_sc_transitive_dependencies AS
    SELECT *
      FROM GRAPH_TABLE (
               supply_chain
               MATCH (a IS sc_node) -[e1 IS sc_flow]-> (m IS sc_node)
                                    -[e2 IS sc_flow]-> (b IS sc_node)
               COLUMNS (
                   a.display_name AS src_name,
                   a.country_iso3 AS src_country,
                   m.display_name AS intermediate,
                   b.display_name AS dst_name,
                   b.country_iso3 AS dst_country,
                   e1.edge_type   AS hop1,
                   e2.edge_type   AS hop2,
                   LEAST(e1.dependency_level, e2.dependency_level)
                                  AS path_dependency
               )
           );

COMMENT ON TABLE vw_sc_transitive_dependencies IS
  'SQL/PGQ example: two-hop supply-chain dependencies. path_dependency is the weakest link on the path (min dependency_level).';

--==============================================================================
-- End of 05_property_graphs.sql
--==============================================================================
