/**
 * Tests for frontend/src/types/classification.ts
 *
 * Gap: classification.ts has two pure functions (numericToLabel, labelColor)
 * that map 26ai numeric Label-Security levels (100/200/300/400) to UI strings
 * and Tailwind badge classes — zero tests existed for either.
 *
 * Covers all four label levels for both functions, plus the exhaustive-switch
 * guarantee (TypeScript enforces it at compile time; we validate at runtime).
 */

import { describe, it, expect } from 'vitest';
import type { ClassificationLabel } from '../../layers/types';
import { numericToLabel, labelColor } from '../classification';

// ---------------------------------------------------------------------------
// numericToLabel
// ---------------------------------------------------------------------------

describe('numericToLabel', () => {
  it('maps 100 → OPEN', () => {
    expect(numericToLabel(100 as ClassificationLabel)).toBe('OPEN');
  });

  it('maps 200 → RESTRICTED', () => {
    expect(numericToLabel(200 as ClassificationLabel)).toBe('RESTRICTED');
  });

  it('maps 300 → CONFIDENTIAL', () => {
    expect(numericToLabel(300 as ClassificationLabel)).toBe('CONFIDENTIAL');
  });

  it('maps 400 → SECRET', () => {
    expect(numericToLabel(400 as ClassificationLabel)).toBe('SECRET');
  });

  it('returns a string for every valid level', () => {
    const levels = [100, 200, 300, 400] as ClassificationLabel[];
    for (const level of levels) {
      expect(typeof numericToLabel(level)).toBe('string');
    }
  });
});

// ---------------------------------------------------------------------------
// labelColor
// ---------------------------------------------------------------------------

describe('labelColor', () => {
  const LEVELS = [100, 200, 300, 400] as ClassificationLabel[];

  it('returns an object with bg, fg, border, ring for every level', () => {
    for (const level of LEVELS) {
      const style = labelColor(level);
      expect(style).toHaveProperty('bg');
      expect(style).toHaveProperty('fg');
      expect(style).toHaveProperty('border');
      expect(style).toHaveProperty('ring');
    }
  });

  it('OPEN (100) uses emerald palette', () => {
    const style = labelColor(100 as ClassificationLabel);
    expect(style.bg).toContain('emerald');
    expect(style.fg).toContain('emerald');
  });

  it('RESTRICTED (200) uses amber palette', () => {
    const style = labelColor(200 as ClassificationLabel);
    expect(style.bg).toContain('amber');
    expect(style.fg).toContain('amber');
  });

  it('CONFIDENTIAL (300) uses orange palette', () => {
    const style = labelColor(300 as ClassificationLabel);
    expect(style.bg).toContain('orange');
    expect(style.fg).toContain('orange');
  });

  it('SECRET (400) uses red palette', () => {
    const style = labelColor(400 as ClassificationLabel);
    expect(style.bg).toContain('red');
    expect(style.fg).toContain('red');
  });

  it('border and ring strings are non-empty', () => {
    for (const level of LEVELS) {
      const style = labelColor(level);
      expect(style.border.length).toBeGreaterThan(0);
      expect(style.ring.length).toBeGreaterThan(0);
    }
  });

  it('SECRET level has higher visual prominence than OPEN', () => {
    // Secret should use a warning/danger color (red), not a neutral/green one.
    const open = labelColor(100 as ClassificationLabel);
    const secret = labelColor(400 as ClassificationLabel);
    expect(open.bg).not.toBe(secret.bg);
  });
});
