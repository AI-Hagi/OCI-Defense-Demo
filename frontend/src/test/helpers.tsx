import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions, type RenderResult } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactElement, ReactNode } from 'react';
import { TenantProvider } from '../hooks/useTenant';

interface ProvidersProps {
  children: ReactNode;
  route?: string;
}

// Wrap rendered trees with QueryClient + Router + TenantProvider. Tests that
// care about a specific route pass { route: '/geoint' } etc.
export function AllProviders({ children, route = '/' }: ProvidersProps) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <TenantProvider>{children}</TenantProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

export interface ExtraRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  route?: string;
}

export function renderWithProviders(
  ui: ReactElement,
  { route, ...options }: ExtraRenderOptions = {},
): RenderResult {
  return render(ui, {
    wrapper: ({ children }) => <AllProviders route={route}>{children}</AllProviders>,
    ...options,
  });
}
