import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { TenantProvider } from '../../hooks/useTenant';
import { Layout } from '../Layout';

function renderLayout(path = '/geoint', outlet = <div data-testid="outlet-content">page</div>) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TenantProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="*" element={outlet} />
          </Route>
        </Routes>
      </TenantProvider>
    </MemoryRouter>,
  );
}

describe('Layout', () => {
  it('renders the sidebar navigation', () => {
    renderLayout();
    // Sidebar renders a <nav> element.
    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });

  it('renders the top bar banner', () => {
    renderLayout();
    expect(screen.getByRole('banner')).toBeInTheDocument();
  });

  it('renders the outlet content inside a <main>', () => {
    renderLayout('/geoint', <span data-testid="child">child content</span>);
    const main = screen.getByRole('main');
    expect(main).toBeInTheDocument();
    expect(main).toContainElement(screen.getByTestId('child'));
  });

  it('uses a two-column grid layout (sidebar + content area)', () => {
    renderLayout();
    // The root grid div has an inline gridTemplateColumns style.
    const root = document.querySelector('[style*="gridTemplateColumns"]');
    expect(root).not.toBeNull();
    expect((root as HTMLElement).style.gridTemplateColumns).toBe('240px 1fr');
  });

  it('applies the Oracle dark background to the root grid', () => {
    renderLayout();
    const root = document.querySelector('.bg-\\[\\#1A1816\\]');
    expect(root).not.toBeNull();
  });

  it('applies the Oracle light background to the content area', () => {
    renderLayout();
    const content = document.querySelector('.bg-\\[\\#F5F4F2\\]');
    expect(content).not.toBeNull();
  });

  it('content area is full viewport height with overflow-auto on main', () => {
    renderLayout();
    const main = screen.getByRole('main');
    expect(main.className).toMatch(/overflow-auto/);
  });
});
