import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { createElement } from 'react';
import type { Tenant } from '../types';

// Three demo tenants for the DICE-EU federation.
const DEMO_TENANTS: Tenant[] = [
  {
    tenant_id: 'T001',
    code: 'DEU_BMVG',
    display_name: 'Germany BMVg',
    country_iso3: 'DEU',
  },
  {
    tenant_id: 'T002',
    code: 'FRA_DGA',
    display_name: 'France DGA',
    country_iso3: 'FRA',
  },
  {
    tenant_id: 'T003',
    code: 'NLD_MOD',
    display_name: 'Netherlands MoD',
    country_iso3: 'NLD',
  },
];

const STORAGE_KEY = 'sov:tenant';

interface TenantContextValue {
  current: Tenant;
  setCurrent: (tenantId: string) => void;
  all: Tenant[];
}

const TenantContext = createContext<TenantContextValue | undefined>(undefined);

interface TenantProviderProps {
  children: ReactNode;
}

// React context provider that persists the selected tenant in localStorage
// and exposes the list of known tenants to all consumers.
export function TenantProvider({ children }: TenantProviderProps) {
  const [currentId, setCurrentId] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? DEMO_TENANTS[0].tenant_id;
    } catch {
      return DEMO_TENANTS[0].tenant_id;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, currentId);
    } catch {
      // ignore quota / privacy errors
    }
  }, [currentId]);

  const setCurrent = useCallback((tenantId: string) => {
    setCurrentId(tenantId);
  }, []);

  const value = useMemo<TenantContextValue>(() => {
    const current =
      DEMO_TENANTS.find((t) => t.tenant_id === currentId) ?? DEMO_TENANTS[0];
    return { current, setCurrent, all: DEMO_TENANTS };
  }, [currentId, setCurrent]);

  return createElement(TenantContext.Provider, { value }, children);
}

// Consumer hook. Throws if used outside the provider to surface bugs early.
export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) {
    throw new Error('useTenant must be used within a <TenantProvider>');
  }
  return ctx;
}
