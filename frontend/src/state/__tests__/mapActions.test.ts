/**
 * Tests for the mapActions pub/sub store and the WS-event parser.
 */
import { afterEach, describe, it, expect, vi } from 'vitest';
import {
  _resetMapActionsForTest,
  dispatchMapAction,
  parseMapActionEvent,
  subscribeMapAction,
  type MapAction,
} from '../mapActions';

afterEach(() => {
  _resetMapActionsForTest();
});

describe('parseMapActionEvent()', () => {
  it('accepts a well-formed flyto frame and copies lat/lon/zoom_km', () => {
    const out = parseMapActionEvent({
      type: 'map_action',
      action: 'flyto',
      lat: 50.1109,
      lon: 8.6821,
      zoom_km: 50,
    });
    expect(out).toEqual({
      action: 'flyto',
      lat: 50.1109,
      lon: 8.6821,
      zoom_km: 50,
    });
  });

  it('rejects flyto with missing lat/lon', () => {
    expect(parseMapActionEvent({ action: 'flyto', lat: 50 })).toBeNull();
    expect(parseMapActionEvent({ action: 'flyto', lat: 91, lon: 0 })).toBeNull();
  });

  it('accepts enable_layer + disable_layer + rejects empty layer', () => {
    expect(parseMapActionEvent({ action: 'enable_layer', layer: 'maritime' })).toEqual({
      action: 'enable_layer',
      layer: 'maritime',
    });
    expect(parseMapActionEvent({ action: 'disable_layer', layer: 'jamming' })).toEqual({
      action: 'disable_layer',
      layer: 'jamming',
    });
    expect(parseMapActionEvent({ action: 'enable_layer', layer: '' })).toBeNull();
  });

  it('strips non-string entity ids in highlight_entities', () => {
    const out = parseMapActionEvent({
      action: 'highlight_entities',
      entity_ids: ['V001', 42, null, 'V002'],
    });
    expect(out).toEqual({ action: 'highlight_entities', entity_ids: ['V001', 'V002'] });
  });

  it('returns null for unknown actions', () => {
    expect(parseMapActionEvent({ action: 'detonate' })).toBeNull();
    expect(parseMapActionEvent({})).toBeNull();
  });
});

describe('dispatchMapAction() / subscribeMapAction()', () => {
  it('delivers actions to all subscribers and unsubscribe stops delivery', () => {
    const a = vi.fn();
    const b = vi.fn();
    const unsub = subscribeMapAction(a);
    subscribeMapAction(b);

    const action: MapAction = { action: 'flyto', lat: 0, lon: 0 };
    dispatchMapAction(action);
    expect(a).toHaveBeenCalledWith(action);
    expect(b).toHaveBeenCalledWith(action);

    unsub();
    dispatchMapAction({ action: 'enable_layer', layer: 'maritime' });
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(2);
  });

  it('listener errors do not block other listeners', () => {
    const errSpy = vi.fn(() => {
      throw new Error('boom');
    });
    const ok = vi.fn();
    subscribeMapAction(errSpy);
    subscribeMapAction(ok);
    dispatchMapAction({ action: 'flyto', lat: 1, lon: 2 });
    expect(errSpy).toHaveBeenCalled();
    expect(ok).toHaveBeenCalled();
  });
});
