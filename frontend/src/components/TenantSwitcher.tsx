import { useTenant } from '../hooks/useTenant';

// Dropdown that switches the active tenant. Persists via the hook -> localStorage.
export function TenantSwitcher() {
  const { current, setCurrent, all } = useTenant();

  return (
    <label className="flex items-center gap-2 text-sm text-slate-700">
      <span className="text-xs uppercase tracking-wider text-slate-500">
        Mandant
      </span>
      <select
        value={current.tenant_id}
        onChange={(e) => setCurrent(e.target.value)}
        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-900 shadow-sm outline-none transition-colors focus:border-[#C74634] focus:ring-2 focus:ring-[#C74634]/40"
      >
        {all.map((t) => (
          <option key={t.tenant_id} value={t.tenant_id}>
            {t.code} · {t.display_name}
          </option>
        ))}
      </select>
    </label>
  );
}

export default TenantSwitcher;
