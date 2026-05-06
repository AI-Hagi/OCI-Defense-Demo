import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Sidebar } from '../Sidebar';

const NAV_CONTRACT: Array<{ href: string; label: RegExp }> = [
  { href: '/geoint', label: /GEOINT/ },
  { href: '/documents', label: /Dokumenten-Intelligenz/ },
  { href: '/collaboration', label: /Zusammenarbeit/ },
  { href: '/lagebild', label: /Lagebild/ },
  { href: '/osint', label: /OSINT-Fusion/ },
  { href: '/uc4-tools', label: /UC4-Tools/ },
  { href: '/supply-chain', label: /Lieferkette/ },
  { href: '/compliance', label: /Compliance/ },
  { href: '/industrial', label: /Industrie UCs/ },
];

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe('Sidebar (london school)', () => {
  it('renders exactly 9 nav items with correct hrefs and labels', () => {
    renderAt('/geoint');
    const links = screen.getAllByRole('link');
    expect(links.length).toBe(NAV_CONTRACT.length);

    NAV_CONTRACT.forEach(({ href, label }) => {
      const link = links.find((a) => a.getAttribute('href') === href);
      expect(link, `missing link to ${href}`).toBeDefined();
      expect(link!.textContent ?? '').toMatch(label);
    });
  });

  it('applies the Redwood (#C74634) background class to the active route', () => {
    renderAt('/osint');
    const active = screen
      .getAllByRole('link')
      .find((a) => a.getAttribute('href') === '/osint')!;
    expect(active.className).toMatch(/C74634/);
  });

  it('does NOT apply the Redwood background to inactive routes', () => {
    renderAt('/osint');
    const inactive = screen
      .getAllByRole('link')
      .find((a) => a.getAttribute('href') === '/compliance')!;
    // Inactive links use slate-300 text, not the #C74634 bg.
    expect(inactive.className).not.toMatch(/bg-\[#C74634\]/);
  });
});
