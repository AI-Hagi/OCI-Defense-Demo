/**
 * Tests for ComplianceTiles.tsx — pure helpers and component rendering.
 *
 * Gaps: scoreColor thresholds, formatRelative (all time buckets + edge cases),
 * ScoreCard radial/label rendering, LiveTile degraded vs. ok states,
 * StatusIcon for all five ControlStatus variants.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  scoreColor,
  formatRelative,
  COLOR_BAD,
  COLOR_WARN,
  COLOR_OK,
  ScoreCard,
  LiveTile,
  StatusIcon,
  DEGRADED_TOOLTIP,
} from '../compliance/ComplianceTiles';
import type { ComplianceFrameworkScore } from '../../types';

// ---------------------------------------------------------------------------
// scoreColor — threshold bands
// ---------------------------------------------------------------------------

describe('scoreColor', () => {
  it('returns COLOR_BAD for score below 60', () => {
    expect(scoreColor(0)).toBe(COLOR_BAD);
    expect(scoreColor(59)).toBe(COLOR_BAD);
    expect(scoreColor(59.9)).toBe(COLOR_BAD);
  });

  it('returns COLOR_WARN for score in [60, 80)', () => {
    expect(scoreColor(60)).toBe(COLOR_WARN);
    expect(scoreColor(75)).toBe(COLOR_WARN);
    expect(scoreColor(79.9)).toBe(COLOR_WARN);
  });

  it('returns COLOR_OK for score >= 80', () => {
    expect(scoreColor(80)).toBe(COLOR_OK);
    expect(scoreColor(100)).toBe(COLOR_OK);
    expect(scoreColor(95.5)).toBe(COLOR_OK);
  });

  it('handles boundary exactly at 60', () => {
    expect(scoreColor(60)).toBe(COLOR_WARN);
  });

  it('handles boundary exactly at 80', () => {
    expect(scoreColor(80)).toBe(COLOR_OK);
  });
});

// ---------------------------------------------------------------------------
// formatRelative — time bucket rendering
// ---------------------------------------------------------------------------

const NOW = Date.now();

describe('formatRelative', () => {
  it('returns "—" when iso is undefined', () => {
    expect(formatRelative(undefined, NOW)).toBe('—');
  });

  it('returns "—" when iso is not a valid date', () => {
    expect(formatRelative('not-a-date', NOW)).toBe('—');
  });

  it('formats seconds (< 60) as "vor X Sek."', () => {
    const iso = new Date(NOW - 30_000).toISOString();
    expect(formatRelative(iso, NOW)).toBe('vor 30 Sek.');
  });

  it('formats exactly 0 seconds as "vor 0 Sek."', () => {
    const iso = new Date(NOW).toISOString();
    expect(formatRelative(iso, NOW)).toBe('vor 0 Sek.');
  });

  it('formats minutes (60s–3599s) as "vor X Min."', () => {
    const iso = new Date(NOW - 5 * 60_000).toISOString();
    expect(formatRelative(iso, NOW)).toBe('vor 5 Min.');
  });

  it('formats hours (3600s–86399s) as "vor X Std."', () => {
    const iso = new Date(NOW - 2 * 3_600_000).toISOString();
    expect(formatRelative(iso, NOW)).toBe('vor 2 Std.');
  });

  it('formats days (>= 86400s) as "vor X Tagen"', () => {
    const iso = new Date(NOW - 3 * 86_400_000).toISOString();
    expect(formatRelative(iso, NOW)).toBe('vor 3 Tagen');
  });

  it('clamps negative diffs to 0', () => {
    // Timestamp slightly in the future — diff is negative, Math.max clamps to 0
    const iso = new Date(NOW + 5_000).toISOString();
    expect(formatRelative(iso, NOW)).toBe('vor 0 Sek.');
  });
});

// ---------------------------------------------------------------------------
// ScoreCard — rendering
// ---------------------------------------------------------------------------

const BASE_SCORE: ComplianceFrameworkScore = {
  framework: 'NIS2',
  total: 20,
  implemented: 14,
  score_pct: 70,
  live_penalty: 0,
};

describe('ScoreCard', () => {
  it('renders the data-testid for the framework', () => {
    render(<ScoreCard score={BASE_SCORE} />);
    expect(screen.getByTestId('score-card-NIS2')).toBeInTheDocument();
  });

  it('shows the rounded score percentage', () => {
    render(<ScoreCard score={BASE_SCORE} />);
    expect(screen.getByText('70%')).toBeInTheDocument();
  });

  it('shows total controls count', () => {
    render(<ScoreCard score={BASE_SCORE} />);
    expect(screen.getByText(/20 Controls/)).toBeInTheDocument();
  });

  it('shows implemented count', () => {
    render(<ScoreCard score={BASE_SCORE} />);
    expect(screen.getByText(/14 implementiert von 20/)).toBeInTheDocument();
  });

  it('renders with no score (undefined) without crashing', () => {
    render(<ScoreCard score={undefined} />);
    expect(screen.getByTestId('score-card-NIS2')).toBeInTheDocument();
  });

  it('shows "—" when score is undefined', () => {
    render(<ScoreCard score={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('renders DORA framework label', () => {
    render(<ScoreCard score={{ ...BASE_SCORE, framework: 'DORA', total: 10, implemented: 8, score_pct: 80 }} />);
    expect(screen.getByText(/DORA/)).toBeInTheDocument();
  });

  it('renders VS-NfD label for VSNFD framework', () => {
    render(<ScoreCard score={{ ...BASE_SCORE, framework: 'VSNFD' }} />);
    expect(screen.getByText(/VS-NfD/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// LiveTile — degraded vs. ok vs. clickable
// ---------------------------------------------------------------------------

const TILE_PROPS = {
  label: 'Offene Probleme',
  value: <span>3</span>,
  icon: <span data-testid="icon">⚠</span>,
  asOf: new Date(Date.now() - 15_000).toISOString(),
  now: Date.now(),
  degraded: false,
};

describe('LiveTile', () => {
  it('shows value when not degraded', () => {
    render(<LiveTile {...TILE_PROPS} testId="tile-test" />);
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('shows "—" instead of value when degraded', () => {
    render(<LiveTile {...TILE_PROPS} degraded testId="tile-test" />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('shows degraded triangle icon when degraded=true', () => {
    render(<LiveTile {...TILE_PROPS} degraded testId="tile-test" />);
    expect(screen.getByTestId('tile-test-degraded')).toBeInTheDocument();
  });

  it('does not show degraded icon when degraded=false', () => {
    render(<LiveTile {...TILE_PROPS} degraded={false} testId="tile-test" />);
    expect(screen.queryByTestId('tile-test-degraded')).not.toBeInTheDocument();
  });

  it('renders the label text', () => {
    render(<LiveTile {...TILE_PROPS} />);
    expect(screen.getByText('Offene Probleme')).toBeInTheDocument();
  });

  it('has role=button when onClick is provided', () => {
    render(<LiveTile {...TILE_PROPS} onClick={() => {}} testId="clickable" />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('does not have role=button when onClick is absent', () => {
    render(<LiveTile {...TILE_PROPS} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn();
    render(<LiveTile {...TILE_PROPS} onClick={onClick} testId="clickable" />);
    await userEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('calls onClick when Enter key is pressed', async () => {
    const onClick = vi.fn();
    render(<LiveTile {...TILE_PROPS} onClick={onClick} testId="clickable" />);
    await userEvent.keyboard('{Enter}');
    // Focus the button first then press Enter
    screen.getByRole('button').focus();
    await userEvent.keyboard('{Enter}');
    expect(onClick).toHaveBeenCalled();
  });

  it('shows relative time from asOf', () => {
    render(<LiveTile {...TILE_PROPS} />);
    expect(screen.getByText(/Sek\./)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// StatusIcon — all five ControlStatus variants
// ---------------------------------------------------------------------------

describe('StatusIcon', () => {
  it('renders "mitigated" with check icon text', () => {
    render(<StatusIcon status="mitigated" />);
    expect(screen.getByText('mitigated')).toBeInTheDocument();
  });

  it('renders "closed" with check icon text', () => {
    render(<StatusIcon status="closed" />);
    expect(screen.getByText('closed')).toBeInTheDocument();
  });

  it('renders "open" with its label', () => {
    render(<StatusIcon status="open" />);
    expect(screen.getByText('open')).toBeInTheDocument();
  });

  it('renders "accepted" with its label', () => {
    render(<StatusIcon status="accepted" />);
    expect(screen.getByText('accepted')).toBeInTheDocument();
  });

  it('renders "false_positive" with its label', () => {
    render(<StatusIcon status="false_positive" />);
    expect(screen.getByText('false positive')).toBeInTheDocument();
  });

  it('renders fallback "—" for undefined status', () => {
    render(<StatusIcon status={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
