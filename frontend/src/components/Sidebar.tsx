import { NavLink } from 'react-router-dom';
import {
  FileText,
  Network,
  Satellite,
  ShieldCheck,
  Truck,
  Users,
  type LucideIcon,
} from 'lucide-react';

interface NavEntry {
  to: string;
  label: string;
  icon: LucideIcon;
}

// Navigation entries in German, in the canonical order of the six use cases.
const NAV_ENTRIES: NavEntry[] = [
  { to: '/geoint', label: 'GEOINT', icon: Satellite },
  { to: '/documents', label: 'Dokumenten-Intelligenz', icon: FileText },
  { to: '/collaboration', label: 'Zusammenarbeit', icon: Users },
  { to: '/osint', label: 'OSINT-Fusion', icon: Network },
  { to: '/supply-chain', label: 'Lieferkette', icon: Truck },
  { to: '/compliance', label: 'Compliance', icon: ShieldCheck },
];

// Left-hand navigation column. Dark surface, Redwood accent for active links.
export function Sidebar() {
  return (
    <aside className="flex h-full flex-col bg-[#1A1816] text-slate-100">
      <div className="border-b border-slate-800 px-5 py-5">
        <div className="text-xs uppercase tracking-[0.2em] text-slate-400">
          Sovereign
        </div>
        <div className="mt-1 text-lg font-semibold text-white">Defence</div>
        <div className="mt-0.5 text-xs text-slate-500">
          Intelligence Platform
        </div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        {NAV_ENTRIES.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              [
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-[#C74634] text-white shadow-sm'
                  : 'text-slate-300 hover:bg-slate-800 hover:text-white',
              ].join(' ')
            }
          >
            <Icon size={18} strokeWidth={2} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-slate-800 px-5 py-3 text-[11px] text-slate-500">
        DICE-EU · OCI 26ai
      </div>
    </aside>
  );
}

export default Sidebar;
