// UC4 — Satellite layers helper.
//
// All three sub-layers (stations / resource / active) consume the same
// CelesTrak TLE feed and run identical SGP4 propagation client-side via
// `satellite.js`. This module centralises:
//
//   * `parseTleCollection` — backend wire-format → typed `SatelliteRecord[]`
//   * `propagatePosition`  — single SGP4 step (date → lat/lon/alt)
//   * `orbitClass`         — LEO/MEO/GEO bucket from altitude
//   * `orbitalPeriodMin`   — derived from TLE mean motion
//
// The 1 Hz update loop lives in each layer module (Cesium types differ
// between Entity-API and PointPrimitiveCollection), but the math is here.

import {
  twoline2satrec,
  propagate,
  gstime,
  eciToGeodetic,
  degreesLat,
  degreesLong,
  type SatRec,
  type EciVec3,
  type GeodeticLocation,
} from 'satellite.js';

// ---------------------------------------------------------------------------
// Wire format from /api/osint/satellites/{group}/current.
// ---------------------------------------------------------------------------

export interface TleEntry {
  name: string;
  norad_id: string;
  line1: string;
  line2: string;
}

export interface TleCollection {
  type: 'TleCollection';
  group: 'stations' | 'resource' | 'active' | string;
  tle: TleEntry[];
  count: number;
  source?: string;
  fetched_at?: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// Parsed satellite record carried inside the layer modules.
// ---------------------------------------------------------------------------

export interface SatelliteRecord {
  name: string;
  noradId: string;
  satrec: SatRec;
  /** Mean motion (revs/day) read straight from line2 — drives orbit class. */
  meanMotion: number;
  /** Computed orbital period in minutes. Stable across SGP4 ticks. */
  periodMinutes: number;
}

// ---------------------------------------------------------------------------
// Parsing.
// ---------------------------------------------------------------------------

function parseMeanMotion(line2: string): number {
  // TLE line 2 columns 53-63 hold mean motion (revolutions/day) in fixed
  // 11.8 format. Tolerate ragged inputs by best-effort parse.
  if (line2.length < 63) return 0;
  const raw = line2.substring(52, 63).trim();
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/**
 * Build the satellite.js SatRec for every entry in the wire payload.
 * Records that fail to parse (e.g. bad TLE checksum) are dropped — the
 * frontend never wants to render a satellite that satellite.js can't
 * propagate.
 */
export function parseTleCollection(payload: TleCollection): SatelliteRecord[] {
  if (!payload || !Array.isArray(payload.tle)) return [];
  const out: SatelliteRecord[] = [];
  for (const entry of payload.tle) {
    if (!entry?.line1 || !entry?.line2) continue;
    let satrec: SatRec;
    try {
      satrec = twoline2satrec(entry.line1, entry.line2);
    } catch {
      continue;
    }
    // satellite.js sets `error` on the satrec when parsing fails non-throwing-ly.
    const errMaybe = (satrec as unknown as { error?: number }).error;
    if (errMaybe && errMaybe !== 0) continue;
    const meanMotion = parseMeanMotion(entry.line2);
    out.push({
      name: entry.name,
      noradId: entry.norad_id,
      satrec,
      meanMotion,
      periodMinutes: meanMotion > 0 ? 1440 / meanMotion : 0,
    });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Propagation.
// ---------------------------------------------------------------------------

export interface SatPosition {
  lat: number;   // degrees
  lon: number;   // degrees
  altKm: number; // height above ellipsoid in km
}

/**
 * Run one SGP4 step at `date` and return geodetic lat/lon/alt. Returns
 * null when satellite.js fails (bad TLE for that epoch — common for
 * decayed satellites in the active catalog).
 */
export function propagatePosition(satrec: SatRec, date: Date): SatPosition | null {
  const pv = propagate(satrec, date);
  if (!pv || !pv.position || typeof pv.position === 'boolean') return null;
  const eci = pv.position as EciVec3<number>;
  const gmst = gstime(date);
  const geo: GeodeticLocation = eciToGeodetic(eci, gmst);
  if (!Number.isFinite(geo.latitude) || !Number.isFinite(geo.longitude)) {
    return null;
  }
  return {
    lat: degreesLat(geo.latitude),
    lon: degreesLong(geo.longitude),
    altKm: geo.height,
  };
}

// ---------------------------------------------------------------------------
// Orbit-class bucket — used in the intel-panel meta + `_wvType`/sources.
// ---------------------------------------------------------------------------

export type OrbitClass = 'LEO' | 'MEO' | 'GEO' | 'HEO' | 'unknown';

export function orbitClass(altKm: number, periodMinutes: number): OrbitClass {
  if (!Number.isFinite(altKm) || altKm <= 0) return 'unknown';
  // Fast-and-friendly classification: GEO is ~35786 km circular, MEO is
  // 2000–35000 km, LEO is below 2000 km. HEO covers highly-elliptic
  // (period >> 800 min) which we identify via period-vs-altitude mismatch.
  if (altKm >= 35000) return 'GEO';
  if (altKm >= 2000) {
    return periodMinutes > 800 ? 'HEO' : 'MEO';
  }
  return 'LEO';
}
