import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from 'd3-force';
import { select } from 'd3-selection';
import { drag, type D3DragEvent } from 'd3-drag';
import { Search } from 'lucide-react';
import { osint } from '../services/api';
import type { OsintEdge, OsintKind, OsintNode } from '../types';

// Node colour by entity kind. ems_emission gets a distinct EW-cyan so the
// EMS layer reads instantly when the toggle is on.
const KIND_COLOR: Record<OsintKind, string> = {
  person: '#C74634',
  organization: '#1f7a8c',
  location: '#8a9a5b',
  vessel: '#0f4c81',
  aircraft: '#264653',
  company: '#e9c46a',
  asset: '#b08968',
  event: '#d62828',
  indicator: '#6a4c93',
  malware: '#3d0066',
  actor: '#ef476f',
  ems_emission: '#00b4d8',
};

interface GraphNode extends SimulationNodeDatum {
  id: string;
  kind: OsintKind;
  name: string;
  attributes: Record<string, unknown> | null;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  rel_type: string;
  rel_id: string;
}

function toGraphNodes(nodes: OsintNode[]): GraphNode[] {
  return nodes.map((n) => ({
    id: n.entity_id,
    kind: n.kind,
    name: n.canonical_name,
    attributes: n.attributes,
  }));
}

function toGraphLinks(edges: OsintEdge[]): GraphLink[] {
  return edges.map((e) => ({
    source: e.src_id,
    target: e.dst_id,
    rel_type: e.rel_type,
    rel_id: e.rel_id,
  }));
}

interface SelectedInfo {
  node: GraphNode;
  outgoingRelTypes: string[];
}

function buildSelectedInfo(
  node: GraphNode,
  edges: OsintEdge[],
): SelectedInfo {
  const outgoing = edges
    .filter((e) => e.src_id === node.id)
    .map((e) => e.rel_type);
  return { node, outgoingRelTypes: Array.from(new Set(outgoing)) };
}

export function OsintView() {
  const [searchTerm, setSearchTerm] = useState('');
  const [startId, setStartId] = useState<string>('root');
  const [selected, setSelected] = useState<SelectedInfo | null>(null);
  // UC4 — toggles a dedicated EMS overlay derived from kind === 'ems_emission'.
  // When `true`, the graph filters to EMS nodes + their immediate edges so the
  // operator sees the spectrum-fusion view in isolation.
  const [emsOnly, setEmsOnly] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<Simulation<GraphNode, GraphLink> | null>(null);

  const graphQuery = useQuery({
    queryKey: ['osint.graph', startId],
    queryFn: () => osint.graph(startId, 2),
  });

  const allNodes = graphQuery.data?.nodes ?? [];
  const allEdges = graphQuery.data?.edges ?? [];
  const visibleNodes = useMemo(
    () => (emsOnly ? allNodes.filter((n) => n.kind === 'ems_emission') : allNodes),
    [allNodes, emsOnly],
  );
  const visibleNodeIds = useMemo(
    () => new Set(visibleNodes.map((n) => n.entity_id)),
    [visibleNodes],
  );
  const visibleEdges = useMemo(
    () => (emsOnly
      ? allEdges.filter(
          (e) => visibleNodeIds.has(e.src_id) || visibleNodeIds.has(e.dst_id),
        )
      : allEdges),
    [allEdges, emsOnly, visibleNodeIds],
  );

  const nodes = useMemo(() => toGraphNodes(visibleNodes), [visibleNodes]);
  const links = useMemo(() => toGraphLinks(visibleEdges), [visibleEdges]);

  const emsCount = allNodes.filter((n) => n.kind === 'ems_emission').length;

  // D3 force simulation + SVG render.
  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = select(svgEl);
    svg.selectAll('*').remove();

    const width = svgEl.clientWidth || 800;
    const height = svgEl.clientHeight || 600;

    const container = svg
      .append('g')
      .attr('class', 'graph-root');

    const linkSel = container
      .append('g')
      .attr('stroke', '#94a3b8')
      .attr('stroke-opacity', 0.6)
      .selectAll<SVGLineElement, GraphLink>('line')
      .data(links)
      .join('line')
      .attr('stroke-width', 1.4);

    const nodeSel = container
      .append('g')
      .selectAll<SVGGElement, GraphNode>('g')
      .data(nodes, (d) => d.id)
      .join('g')
      .attr('cursor', 'pointer')
      .on('click', (_event, d) => {
        setSelected(buildSelectedInfo(d, visibleEdges));
      });

    nodeSel
      .append('circle')
      .attr('r', 10)
      .attr('fill', (d) => KIND_COLOR[d.kind] ?? '#475569')
      .attr('stroke', '#ffffff')
      .attr('stroke-width', 1.5);

    nodeSel
      .append('text')
      .attr('dy', -14)
      .attr('text-anchor', 'middle')
      .attr('font-size', 10)
      .attr('fill', '#1A1816')
      .text((d) => d.name);

    const dragBehaviour = drag<SVGGElement, GraphNode>()
      .on('start', (event: D3DragEvent<SVGGElement, GraphNode, GraphNode>, d) => {
        if (!event.active) simRef.current?.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event: D3DragEvent<SVGGElement, GraphNode, GraphNode>, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event: D3DragEvent<SVGGElement, GraphNode, GraphNode>, d) => {
        if (!event.active) simRef.current?.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeSel.call(dragBehaviour);

    const sim = forceSimulation<GraphNode, GraphLink>(nodes)
      .force(
        'link',
        forceLink<GraphNode, GraphLink>(links)
          .id((d) => d.id)
          .distance(80),
      )
      .force('charge', forceManyBody<GraphNode>().strength(-220))
      .force('center', forceCenter<GraphNode>(width / 2, height / 2))
      .on('tick', () => {
        linkSel
          .attr('x1', (d) => (d.source as GraphNode).x ?? 0)
          .attr('y1', (d) => (d.source as GraphNode).y ?? 0)
          .attr('x2', (d) => (d.target as GraphNode).x ?? 0)
          .attr('y2', (d) => (d.target as GraphNode).y ?? 0);
        nodeSel.attr('transform', (d) => `translate(${d.x ?? 0}, ${d.y ?? 0})`);
      });

    simRef.current = sim;

    return () => {
      sim.stop();
      simRef.current = null;
    };
  }, [nodes, links, visibleEdges]);

  const handleSearch = (e: FormEvent) => {
    e.preventDefault();
    if (searchTerm.trim()) setStartId(searchTerm.trim());
  };

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            OSINT · Threat Fusion
          </h2>
          <p className="text-sm text-slate-600">
            Property-Graph <span className="font-mono">intel_fusion</span> über
            Oracle 26ai — 2 Hops ab Startentität.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            role="switch"
            aria-checked={emsOnly}
            onClick={() => setEmsOnly((v) => !v)}
            className={[
              'flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium',
              emsOnly
                ? 'border-[#00b4d8] bg-[#00b4d8] text-white'
                : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50',
            ].join(' ')}
            title="Filter auf elektromagnetisches Spektrum"
          >
            <span
              className={[
                'h-2 w-2 rounded-full',
                emsOnly ? 'bg-white' : 'bg-[#00b4d8]',
              ].join(' ')}
            />
            EMS-Layer
            <span className="rounded bg-black/10 px-1.5 py-0.5 text-[10px] font-bold">
              {emsCount}
            </span>
          </button>
          <form onSubmit={handleSearch} className="flex items-center gap-2">
            <div className="relative">
              <Search
                size={14}
                className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="canonical_name"
                className="rounded-md border border-slate-300 bg-white py-1.5 pl-7 pr-3 text-sm outline-none focus:border-[#C74634] focus:ring-2 focus:ring-[#C74634]/30"
              />
            </div>
            <button
              type="submit"
              className="rounded-md bg-[#C74634] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#A33A2C]"
            >
              Suche
            </button>
          </form>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div className="relative h-[70vh] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          {graphQuery.isLoading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center text-sm text-slate-500">
              Lade Graph...
            </div>
          )}
          {graphQuery.isError && (
            <div className="absolute inset-0 z-10 flex items-center justify-center text-sm text-rose-700">
              Fehler beim Laden des Graphen.
            </div>
          )}
          <svg ref={svgRef} className="h-full w-full" />
        </div>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900">Entität</h3>
          {selected ? (
            <div className="mt-3 space-y-4 overflow-y-auto text-sm">
              <div>
                <div className="text-xs uppercase tracking-wider text-slate-500">
                  Name
                </div>
                <div className="font-medium text-slate-900">
                  {selected.node.name}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-slate-500">
                  Typ
                </div>
                <div
                  className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs"
                  style={{ color: KIND_COLOR[selected.node.kind] }}
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{
                      backgroundColor: KIND_COLOR[selected.node.kind],
                    }}
                  />
                  {selected.node.kind}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-slate-500">
                  Attribute
                </div>
                <pre className="mt-1 max-h-40 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-700">
                  {JSON.stringify(selected.node.attributes ?? {}, null, 2)}
                </pre>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-slate-500">
                  Ausgehende Beziehungen
                </div>
                <ul className="mt-1 space-y-1 text-xs text-slate-700">
                  {selected.outgoingRelTypes.length === 0 ? (
                    <li className="text-slate-400">keine</li>
                  ) : (
                    selected.outgoingRelTypes.map((rt) => (
                      <li
                        key={rt}
                        className="rounded-md bg-slate-100 px-2 py-1 font-mono"
                      >
                        {rt}
                      </li>
                    ))
                  )}
                </ul>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-xs text-slate-500">
              Knoten anklicken, um Details und Beziehungen zu sehen.
            </p>
          )}
        </aside>
      </div>
    </section>
  );
}

export default OsintView;
