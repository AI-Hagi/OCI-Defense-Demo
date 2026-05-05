import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { TenantProvider } from '../../hooks/useTenant';
import { TopBar } from '../TopBar';

// Wrap TopBar in a router (it calls useLocation) and TenantProvider (used by TenantSwitcher).
function renderTopBar(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TenantProvider>
        <Routes>
          <Route path="*" element={<TopBar />} />
        </Routes>
      </TenantProvider>
    </MemoryRouter>,
  );
}

describe('TopBar', () => {
  it('renders a header element', () => {
    renderTopBar('/geoint');
    expect(screen.getByRole('banner')).toBeInTheDocument();
  });

  it('shows the GEOINT title for /geoint', () => {
    renderTopBar('/geoint');
    expect(screen.getByRole('heading')).toHaveTextContent('GEOINT');
  });

  it('shows the documents title for /documents', () => {
    renderTopBar('/documents');
    expect(screen.getByRole('heading')).toHaveTextContent('Dokumenten-Intelligenz');
  });

  it('shows the collaboration title for /collaboration', () => {
    renderTopBar('/collaboration');
    expect(screen.getByRole('heading')).toHaveTextContent('Multi-Tenant');
  });

  it('shows the OSINT title for /osint', () => {
    renderTopBar('/osint');
    expect(screen.getByRole('heading')).toHaveTextContent('OSINT');
  });

  it('shows the supply-chain title for /supply-chain', () => {
    renderTopBar('/supply-chain');
    expect(screen.getByRole('heading')).toHaveTextContent('Lieferketten');
  });

  it('shows the compliance title for /compliance', () => {
    renderTopBar('/compliance');
    expect(screen.getByRole('heading')).toHaveTextContent('Compliance');
  });

  it('falls back to "Sovereign Defence" for unknown routes', () => {
    renderTopBar('/unknown-route');
    expect(screen.getByRole('heading')).toHaveTextContent('Sovereign Defence');
  });

  it('falls back to "Sovereign Defence" for the root path', () => {
    renderTopBar('/');
    expect(screen.getByRole('heading')).toHaveTextContent('Sovereign Defence');
  });

  it('renders the Oracle subtitle badge', () => {
    renderTopBar('/geoint');
    expect(screen.getByText(/Oracle AI Database 26ai/)).toBeInTheDocument();
  });

  it('renders the TenantSwitcher (combobox present)', () => {
    renderTopBar('/geoint');
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });
});
