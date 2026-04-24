import { useLocation } from 'react-router-dom';
import { TenantSwitcher } from './TenantSwitcher';

// Route title map (German). Keys are the first path segment.
const ROUTE_TITLES: Record<string, string> = {
  geoint: 'GEOINT · Satellitenaufklärung',
  documents: 'Dokumenten-Intelligenz · RAG',
  collaboration: 'Multi-Tenant Zusammenarbeit',
  osint: 'OSINT · Threat Fusion',
  'supply-chain': 'Lieferketten-Graph',
  compliance: 'Compliance-Automatisierung',
};

function titleForPath(pathname: string): string {
  const segment = pathname.split('/').filter(Boolean)[0] ?? '';
  return ROUTE_TITLES[segment] ?? 'Sovereign Defence';
}

// Top bar: route title on the left, tenant switcher on the right.
export function TopBar() {
  const { pathname } = useLocation();
  const title = titleForPath(pathname);

  return (
    <header className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-6">
      <div className="flex items-baseline gap-3">
        <h1 className="text-base font-semibold text-slate-900">{title}</h1>
        <span className="text-xs text-slate-500">
          Oracle AI Database 26ai · OCI EU Sovereign Cloud
        </span>
      </div>
      <TenantSwitcher />
    </header>
  );
}

export default TopBar;
