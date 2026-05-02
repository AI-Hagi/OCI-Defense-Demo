// Pure-logic tests for satellites-shared — no Cesium mocking required.
// satellite.js runs in Node directly (it's a pure JS SGP4 implementation).

import { describe, expect, it } from 'vitest';
import {
  orbitClass,
  parseTleCollection,
  propagatePosition,
  type TleCollection,
} from '../satellites-shared';

const ISS_TLE: TleCollection = {
  type: 'TleCollection',
  group: 'stations',
  count: 1,
  tle: [
    {
      name: 'ISS (ZARYA)',
      norad_id: '25544',
      line1: '1 25544U 98067A   24001.50000000  .00010000  00000-0  18000-3 0  9999',
      line2: '2 25544  51.6400 200.0000 0007000  10.0000 350.0000 15.50000000564200',
    },
  ],
};

describe('satellites-shared', () => {
  it('parseTleCollection returns one record per valid TLE entry', () => {
    const records = parseTleCollection(ISS_TLE);
    expect(records.length).toBe(1);
    const r = records[0];
    expect(r.noradId).toBe('25544');
    expect(r.name).toBe('ISS (ZARYA)');
    expect(r.satrec).toBeDefined();
    // Mean motion ~15.5 revs/day → period ≈ 92.9 min
    expect(r.periodMinutes).toBeGreaterThan(80);
    expect(r.periodMinutes).toBeLessThan(120);
  });

  it('parseTleCollection drops malformed TLE pairs without throwing', () => {
    const malformed: TleCollection = {
      type: 'TleCollection',
      group: 'stations',
      count: 2,
      tle: [
        { name: 'EMPTY', norad_id: '', line1: '', line2: '' },
        ISS_TLE.tle[0],
      ],
    };
    const records = parseTleCollection(malformed);
    expect(records.length).toBe(1);
    expect(records[0].noradId).toBe('25544');
  });

  it('propagatePosition returns a plausible ISS position (lat in valid band)', () => {
    const records = parseTleCollection(ISS_TLE);
    expect(records.length).toBe(1);
    const pos = propagatePosition(records[0].satrec, new Date('2024-01-02T00:00:00Z'));
    // ISS inclination ≈ 51.6°, so |lat| should never exceed ~52°.
    expect(pos).not.toBeNull();
    expect(Math.abs(pos!.lat)).toBeLessThan(53);
    expect(pos!.lon).toBeGreaterThanOrEqual(-180);
    expect(pos!.lon).toBeLessThanOrEqual(180);
  });

  it('propagatePosition altitude is in the LEO band for ISS', () => {
    const records = parseTleCollection(ISS_TLE);
    const pos = propagatePosition(records[0].satrec, new Date('2024-01-02T00:00:00Z'));
    // ISS orbits 380–460 km; SGP4 should land us in the 350–500 km band.
    expect(pos!.altKm).toBeGreaterThan(350);
    expect(pos!.altKm).toBeLessThan(500);
  });

  it('orbitClass buckets known altitudes correctly', () => {
    expect(orbitClass(420, 92.9)).toBe('LEO');     // ISS
    expect(orbitClass(20200, 720)).toBe('MEO');    // GPS-class
    expect(orbitClass(35786, 1436)).toBe('GEO');   // geostationary
    expect(orbitClass(25000, 900)).toBe('HEO');    // Molniya-ish
    expect(orbitClass(0, 0)).toBe('unknown');
  });
});
