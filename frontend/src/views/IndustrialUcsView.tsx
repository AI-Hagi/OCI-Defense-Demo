import { ExternalLink, Factory, GraduationCap, ListChecks, ShieldAlert } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

// Deep-link target for the OCI Generative AI Agents UI in eu-frankfurt-1.
// When a UC has a specific agent provisioned, the link opens that agent
// directly. Otherwise it opens the agents-list page so the operator can
// navigate to whichever agent exists.
const REGION = 'eu-frankfurt-1';
const AGENT_LIST_URL = `https://cloud.oracle.com/ai-service/generative-ai-agents/agents?region=${REGION}`;
const agentDeepLink = (ocid?: string) =>
  ocid
    ? `https://cloud.oracle.com/ai-service/generative-ai-agents/agents/${ocid}?region=${REGION}`
    : AGENT_LIST_URL;

interface IndustrialUc {
  id: string;
  number: number;
  title: string;
  audience: string;
  description: string;
  capabilities: string[];
  agentSpecPath: string;
  agentOcid?: string;
  status: 'live-on-atp' | 'schema-deployable';
  icon: LucideIcon;
}

const INDUSTRIAL_UCS: IndustrialUc[] = [
  {
    id: 'uc07',
    number: 7,
    title: 'Engineering Knowledge Assistant',
    audience: 'Engineering',
    description:
      'RAG-Recherche über klassifizierte PLM-Dokumente — CAD-Spezifikationen, Stücklisten, Konstruktionsleitlinien — direkt in 26ai. Coalition-VPD bleibt aktiv.',
    capabilities: [
      'Vector Search über PLM-Korpus',
      'INCOSE-Quality-Heuristiken',
      'Tenant-isoliert pro Programm',
    ],
    agentSpecPath: 'industrial/01-engineering-knowledge/agent/engineering-knowledge.agent.yaml',
    status: 'schema-deployable',
    icon: GraduationCap,
  },
  {
    id: 'uc08',
    number: 8,
    title: 'Quality & Incident Analysis',
    audience: 'Manufacturing / Quality',
    description:
      'Vector-Clustering und ML-Anomaly-Detection auf NCR-Berichten und SPC-Streams. Erkennt wiederkehrende Defekt-Muster über Werke und Programme hinweg.',
    capabilities: [
      'Vector-Clustering NCR-Daten',
      'SPC-Anomaly-Detection',
      'Plant-Level-Access-Layer (VPD)',
    ],
    agentSpecPath: 'industrial/02-quality-incident/agent/quality-incident.agent.yaml',
    agentOcid: 'ocid1.genaiagent.oc1.eu-frankfurt-1.amaaaaaaqfczboqa34yzgvlp7a5jmm32tcr7tbqfjghcwavmaiwl3yslyi3q',
    status: 'live-on-atp',
    icon: ShieldAlert,
  },
  {
    id: 'uc09',
    number: 9,
    title: 'Software Assurance Assistant',
    audience: 'V&V Leads / Auditoren',
    description:
      'Property-Graph-Traceability für Anforderungen → Tests → Defects. Analysiert Defect-Impact über die Lieferkette und generiert AQAP-2110-Auditberichte.',
    capabilities: [
      'Property-Graph (SQL/PGQ)',
      'Defect-Impact-Analyse',
      'Project-Level-Access',
    ],
    agentSpecPath: 'industrial/03-software-assurance/agent/software-assurance.agent.yaml',
    status: 'schema-deployable',
    icon: ListChecks,
  },
  {
    id: 'uc10',
    number: 10,
    title: 'Requirements Intelligence',
    audience: 'Defence Industry RE',
    description:
      'Programm-übergreifende Anforderungs-Wiederverwendung mit ReqIF-Ingest, INCOSE/SMART/AQAP-2110-Quality-Checks, Vector-Reuse-Suche und Programm-Isolation. Live auf sovdef26 mit 160 synthetischen Anforderungen.',
    capabilities: [
      'ReqIF-Import (DOORS/Polarion)',
      'Vector-Reuse-Suche',
      'Programm-Isolation (Boxer ≠ FCAS)',
      'Quality-Frameworks: SMART/INCOSE/AQAP-2110',
    ],
    agentSpecPath:
      'industrial/10-requirements-intelligence/agent/requirements-intelligence.agent.yaml',
    status: 'live-on-atp',
    icon: Factory,
  },
];

export function IndustrialUcsView() {
  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-6">
      {/* Header */}
      <header>
        <div className="text-xs uppercase tracking-[0.2em] text-slate-500">
          Industrie · Defence
        </div>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">
          Industrie-Use-Cases (UC07 – UC10)
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">
          Datenbankzentrische Use Cases für Defence-Contractors und
          Manufacturing-getriebene Programme. Anders als die sechs
          Intelligence-UCs (Sidebar oben) leben diese vier vollständig in
          Oracle 26ai — als Schemas, Materialized Views, Property-Graphs und
          Vector-Stores. Konsumiert werden sie über die OCI Generative AI{' '}
          <em>Agent Factory</em>, nicht über eigene React-Views.
        </p>
        <p className="mt-2 max-w-3xl text-xs text-slate-500">
          Jede Karte verlinkt auf die Agent-Factory-UI in der OCI Console. Die
          Agent-Specs liegen als YAML im Repo unter{' '}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">
            industrial/&lt;uc&gt;/agent/
          </code>{' '}
          und werden via{' '}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">
            bootstrap-industrial.sh --import-agents
          </code>{' '}
          importiert.
        </p>
      </header>

      {/* Cards grid */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {INDUSTRIAL_UCS.map((uc) => (
          <UcCard key={uc.id} uc={uc} />
        ))}
      </div>

      {/* Footnote */}
      <footer className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
        <div className="font-medium text-slate-700">
          AFCEA-Pillar-Zuordnung
        </div>
        <p className="mt-1">
          Alle vier Industrie-UCs gehören zur Pillar{' '}
          <strong>Secure AI for Defense Industry</strong>. UC07 / UC08 / UC09
          sind Industrial-AI-Bausteine; UC10 ist die vertikale
          Defence-Industry-Story (RE-Knowledge-Base mit
          Programm-übergreifendem Reuse).
        </p>
      </footer>
    </div>
  );
}

interface UcCardProps {
  uc: IndustrialUc;
}

function UcCard({ uc }: UcCardProps) {
  const Icon = uc.icon;
  const statusBadge =
    uc.status === 'live-on-atp' ? (
      <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-[11px] font-medium text-emerald-800">
        Live auf sovdef26
      </span>
    ) : (
      <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-medium text-slate-700">
        Schema deploybar
      </span>
    );

  return (
    <article className="group flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md">
      <header className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#C74634]/10 text-[#C74634]">
          <Icon size={20} strokeWidth={2} />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500">
            <span>UC{String(uc.number).padStart(2, '0')}</span>
            <span>·</span>
            <span>{uc.audience}</span>
          </div>
          <h2 className="mt-0.5 text-base font-semibold text-slate-900">
            {uc.title}
          </h2>
        </div>
        {statusBadge}
      </header>

      <p className="text-sm leading-relaxed text-slate-700">{uc.description}</p>

      <div>
        <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
          Capabilities
        </div>
        <ul className="mt-2 space-y-1">
          {uc.capabilities.map((cap) => (
            <li key={cap} className="flex items-start gap-2 text-xs text-slate-700">
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#C74634]" />
              <span>{cap}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="border-t border-slate-100 pt-3">
        <div className="text-[11px] uppercase tracking-wider text-slate-500">
          Agent-Spec
        </div>
        <code className="mt-1 block break-all font-mono text-[11px] text-slate-600">
          {uc.agentSpecPath}
        </code>
      </div>

      <a
        href={agentDeepLink(uc.agentOcid)}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-auto inline-flex items-center justify-center gap-2 rounded-lg bg-[#C74634] px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#A23A2C]"
      >
        <span>
          {uc.agentOcid ? 'Agent in OCI Console öffnen' : 'Agent Factory öffnen'}
        </span>
        <ExternalLink size={14} strokeWidth={2.5} />
      </a>
    </article>
  );
}

export default IndustrialUcsView;
