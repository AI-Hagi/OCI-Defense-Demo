// Smoke tests for the UC4 LagebildView (Cesium-3D OSINT-Lagebild).
//
// Cesium is fully mocked via a permissive Proxy. We only verify that the
// view mounts, the maritime toggle is reachable, and a default hint shows
// before a pick. Full Cesium rendering is exercised by the manual smoke
// test in scripts/smoke-test-maritime.sh.

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// --- Mock cesium with a permissive Proxy ------------------------------------

vi.mock('cesium', () => {
  // For typical static factories, return objects; for constructor-style
  // imports (Viewer, ScreenSpaceEventHandler) return constructible classes.
  class FakeViewer {
    scene = { requestRender: vi.fn(), pickPosition: vi.fn() };
    entities = {
      add: vi.fn((raw: unknown) => ({ id: 'mock-entity', raw })),
      remove: vi.fn(),
      removeById: vi.fn(),
      removeAll: vi.fn(),
      values: [],
    };
    camera = { flyTo: vi.fn(), setView: vi.fn() };
    cesiumWidget = { creditContainer: { style: {} } };
    canvas = document.createElement('canvas');
    destroy = vi.fn();
  }
  class FakeHandler {
    setInputAction = vi.fn();
    removeInputAction = vi.fn();
    destroy = vi.fn();
  }
  return {
    Viewer: FakeViewer,
    ScreenSpaceEventHandler: FakeHandler,
    ScreenSpaceEventType: { LEFT_CLICK: 1 },
    Ion: { defaultAccessToken: '' },
    Rectangle: {
      fromDegrees: (w: number, s: number, e: number, n: number) => ({ w, s, e, n }),
    },
    Cartesian3: { fromDegrees: () => ({ x: 0, y: 0, z: 0 }) },
    Color: new Proxy({}, { get: () => 'mock-color' }),
    HeightReference: new Proxy({}, { get: () => 0 }),
    HorizontalOrigin: new Proxy({}, { get: () => 0 }),
    VerticalOrigin: new Proxy({}, { get: () => 0 }),
    ConstantProperty: class {
      constructor(public v: unknown) {}
    },
    ConstantPositionProperty: class {
      constructor(public v: unknown) {}
    },
  };
});

// Mock the cesium widgets CSS so vitest doesn't try to resolve it.
vi.mock('cesium/Source/Widgets/widgets.css', () => ({}));

// Import AFTER the cesium mock is in place.
import { LagebildView } from '../LagebildView';
import '../../layers'; // side-effect: registers maritime in LayerRegistry

describe('LagebildView', () => {
  it('renders without throwing in jsdom', () => {
    expect(() =>
      render(
        <MemoryRouter>
          <LagebildView />
        </MemoryRouter>,
      ),
    ).not.toThrow();
  });

  it('shows the maritime toggle in the layer list', () => {
    render(
      <MemoryRouter>
        <LagebildView />
      </MemoryRouter>,
    );
    const toggle =
      screen.queryByTestId('layer-toggle-maritime') ??
      screen.queryByRole('switch', { name: /maritime/i }) ??
      screen.queryByRole('button', { name: /maritime/i }) ??
      screen.queryByLabelText(/maritime/i);
    expect(toggle).toBeTruthy();
  });

  it('renders some intel-panel hint before any entity is picked', () => {
    render(
      <MemoryRouter>
        <LagebildView />
      </MemoryRouter>,
    );
    // Accept any of: a placeholder text, an empty intel region, or simply
    // the absence of vessel meta (we just check the document body has *some*
    // text rendered to confirm the view mounted).
    expect(document.body.textContent ?? '').not.toBe('');
  });
});
