/**
 * Tests for TenantProvider / useTenant hook — default selection, localStorage
 * persistence, invalid tenant fallback, and error when used outside provider.
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { TenantProvider, useTenant } from '../useTenant';

// ── localStorage mock ─────────────────────────────────────────────────────────

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, val: string) => { store[key] = val; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

beforeEach(() => {
  localStorageMock.clear();
  Object.defineProperty(globalThis, 'localStorage', {
    value: localStorageMock,
    writable: true,
  });
});

// ── wrapper factory ───────────────────────────────────────────────────────────

function wrapper({ children }: { children: React.ReactNode }) {
  return React.createElement(TenantProvider, null, children);
}

// ── default selection ─────────────────────────────────────────────────────────

describe('useTenant — defaults', () => {
  it('defaults to T001 (Germany BMVg) when no localStorage entry', () => {
    const { result } = renderHook(() => useTenant(), { wrapper });
    expect(result.current.current.tenant_id).toBe('T001');
  });

  it('exposes all three demo tenants', () => {
    const { result } = renderHook(() => useTenant(), { wrapper });
    const ids = result.current.all.map((t) => t.tenant_id);
    expect(ids).toEqual(['T001', 'T002', 'T003']);
  });
});

// ── setCurrent ────────────────────────────────────────────────────────────────

describe('useTenant — setCurrent', () => {
  it('updates the current tenant when setCurrent is called', () => {
    const { result } = renderHook(() => useTenant(), { wrapper });

    act(() => {
      result.current.setCurrent('T002');
    });

    expect(result.current.current.tenant_id).toBe('T002');
    expect(result.current.current.display_name).toBe('France DGA');
  });

  it('persists the selection to localStorage', () => {
    const { result } = renderHook(() => useTenant(), { wrapper });

    act(() => {
      result.current.setCurrent('T003');
    });

    expect(localStorage.getItem('sov:tenant')).toBe('T003');
  });
});

// ── localStorage restore ──────────────────────────────────────────────────────

describe('useTenant — localStorage restore', () => {
  it('restores the tenant from localStorage on mount', () => {
    localStorage.setItem('sov:tenant', 'T002');
    const { result } = renderHook(() => useTenant(), { wrapper });
    expect(result.current.current.tenant_id).toBe('T002');
  });

  it('falls back to T001 when localStorage contains an unknown tenant_id', () => {
    localStorage.setItem('sov:tenant', 'UNKNOWN_TENANT');
    const { result } = renderHook(() => useTenant(), { wrapper });
    expect(result.current.current.tenant_id).toBe('T001');
  });
});

// ── localStorage error resilience ─────────────────────────────────────────────

describe('useTenant — localStorage errors', () => {
  it('defaults to T001 when localStorage.getItem throws', () => {
    vi.spyOn(localStorageMock, 'getItem').mockImplementation(() => {
      throw new Error('Storage unavailable');
    });

    const { result } = renderHook(() => useTenant(), { wrapper });
    expect(result.current.current.tenant_id).toBe('T001');
  });

  it('does not throw when localStorage.setItem fails on selection change', () => {
    vi.spyOn(localStorageMock, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceeded');
    });

    const { result } = renderHook(() => useTenant(), { wrapper });

    expect(() => {
      act(() => {
        result.current.setCurrent('T002');
      });
    }).not.toThrow();

    expect(result.current.current.tenant_id).toBe('T002');
  });
});

// ── used outside provider ─────────────────────────────────────────────────────

describe('useTenant — error boundary', () => {
  it('throws when used outside TenantProvider', () => {
    // Suppress React's console.error for this test
    vi.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => renderHook(() => useTenant())).toThrow(
      'useTenant must be used within a <TenantProvider>',
    );
  });
});
