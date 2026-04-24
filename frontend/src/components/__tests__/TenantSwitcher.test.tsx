import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TenantProvider, useTenant } from '../../hooks/useTenant';
import { TenantSwitcher } from '../TenantSwitcher';

// Probe component reads context so assertions can compare to the DOM.
function TenantProbe() {
  const { current } = useTenant();
  return <div data-testid="current-tenant">{current.tenant_id}</div>;
}

describe('TenantSwitcher (london school)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders with the default tenant selected', () => {
    render(
      <TenantProvider>
        <TenantSwitcher />
        <TenantProbe />
      </TenantProvider>,
    );
    expect(screen.getByTestId('current-tenant')).toHaveTextContent('T001');
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('T001');
  });

  it('updates useTenant().current when the user picks a different option', async () => {
    render(
      <TenantProvider>
        <TenantSwitcher />
        <TenantProbe />
      </TenantProvider>,
    );
    const user = userEvent.setup();
    const select = screen.getByRole('combobox');
    await user.selectOptions(select, 'T002');

    await waitFor(() => {
      expect(screen.getByTestId('current-tenant')).toHaveTextContent('T002');
    });
  });

  it('persists the selected tenant to localStorage', async () => {
    const setSpy = vi.spyOn(Storage.prototype, 'setItem');
    render(
      <TenantProvider>
        <TenantSwitcher />
      </TenantProvider>,
    );
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole('combobox'), 'T003');
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('sov:tenant', 'T003');
    });
  });

  it('hydrates from localStorage on initial mount', () => {
    localStorage.setItem('sov:tenant', 'T003');
    render(
      <TenantProvider>
        <TenantSwitcher />
        <TenantProbe />
      </TenantProvider>,
    );
    expect(screen.getByTestId('current-tenant')).toHaveTextContent('T003');
  });
});
