import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { server } from './msw-server';

// MSW lifecycle — tests do not hit the real network.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// IntersectionObserver is not implemented in jsdom — mock for recharts/leaflet.
class IntersectionObserverMock {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn().mockReturnValue([]);
  root = null;
  rootMargin = '';
  thresholds: number[] = [];
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IntersectionObserver = IntersectionObserverMock as any;

// matchMedia stub so tailwind / framer-motion don't blow up.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}

// ResizeObserver stub — recharts ResponsiveContainer uses it.
class ResizeObserverMock {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).ResizeObserver = ResizeObserverMock as any;

// jsdom does not implement Element.prototype.scrollTo — polyfill as no-op so
// smooth-scroll side effects in views don't throw during render.
if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (Element.prototype as any).scrollTo = function scrollTo(): void {
    /* noop */
  };
}
// Stub window.scroll* to avoid "not implemented" warnings.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(window as any).scrollTo = vi.fn();
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(HTMLElement.prototype as any).scrollIntoView = vi.fn();
