// UC4/UC6 — numeric Label-Security level helpers for UI.
//
// 26ai uses NUMBER labels (100/200/300/400). UI strings and badge colours
// derive from these. This helper is additive — `frontend/src/types/index.ts`
// keeps its own string-based `Classification` union for the existing UCs.

import type { ClassificationLabel } from '../layers/types';

export type ClassificationName =
  | 'OPEN'
  | 'RESTRICTED'
  | 'CONFIDENTIAL'
  | 'SECRET';

export function numericToLabel(n: ClassificationLabel): ClassificationName {
  switch (n) {
    case 100:
      return 'OPEN';
    case 200:
      return 'RESTRICTED';
    case 300:
      return 'CONFIDENTIAL';
    case 400:
      return 'SECRET';
  }
}

// Tailwind-compatible badge colours (text/background) for each level.
// Picked to read on both the dark sidebar and the light intel panel.
export interface BadgeStyle {
  bg: string;
  fg: string;
  border: string;
  ring: string;
}

export function labelColor(n: ClassificationLabel): BadgeStyle {
  switch (n) {
    case 100:
      return {
        bg: 'bg-emerald-100',
        fg: 'text-emerald-800',
        border: 'border-emerald-300',
        ring: 'ring-emerald-300',
      };
    case 200:
      return {
        bg: 'bg-amber-100',
        fg: 'text-amber-800',
        border: 'border-amber-300',
        ring: 'ring-amber-300',
      };
    case 300:
      return {
        bg: 'bg-orange-100',
        fg: 'text-orange-800',
        border: 'border-orange-300',
        ring: 'ring-orange-300',
      };
    case 400:
      return {
        bg: 'bg-red-100',
        fg: 'text-red-800',
        border: 'border-red-300',
        ring: 'ring-red-300',
      };
  }
}
