import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test/helpers';

async function loadView() {
  const mod = await import('../CollaborationView');
  return mod.default ?? (mod as Record<string, unknown>).CollaborationView;
}

describe('CollaborationView (london school)', () => {
  it('renders three tenant columns DEU_BMVG / FRA_DGA / NLD_MOD', async () => {
    const View = await loadView();
    renderWithProviders(<View />);

    await waitFor(() => {
      expect(screen.getByText(/DEU_BMVG/)).toBeInTheDocument();
      expect(screen.getByText(/FRA_DGA/)).toBeInTheDocument();
      expect(screen.getByText(/NLD_MOD/)).toBeInTheDocument();
    });
  });

  it('segments shares so each share appears in its owner and partner columns', async () => {
    const View = await loadView();
    const { container } = renderWithProviders(<View />);

    // Wait for share titles to appear (from fixtures). Each title appears
    // once per visible column — use getAllByText since there are duplicates.
    await waitFor(() => {
      expect(screen.getAllByText(/BMVg -> DGA Lagebild/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/DGA -> MoD Aufklaerung/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/MoD -> BMVg Threat Actor/i).length).toBeGreaterThan(0);
    });

    // Each share should appear in BOTH its owner column and its partner column.
    // Never in the third tenant column — so exactly 2 occurrences each.
    const html = container.innerHTML;
    const occurrences = (s: string) => (html.match(new RegExp(s, 'g')) ?? []).length;
    expect(occurrences('BMVg -&gt; DGA Lagebild')).toBe(2);
    expect(occurrences('DGA -&gt; MoD Aufklaerung')).toBe(2);
    expect(occurrences('MoD -&gt; BMVg Threat Actor')).toBe(2);
  });
});

// Silence lint for unused vi import when suite trimmed.
void vi;
