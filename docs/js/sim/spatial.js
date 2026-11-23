/**
 * Unified 2D Spatial Hash Grid & Exact Kilchberg Ground-Plane Projection (v14).
 *
 * Shared by Traffic, Pedestrians, Cyclists, and Maritime VesselSim for O(1)
 * 2D proximity queries in ground-plane meters with zero steady-state heap allocations.
 *
 * Projection constants match `docs/js/living/plugins/sports.js` (azimuth=102 deg, pitch=30 deg).
 */

export const E_TO_U = 0.0000674436;
export const N_TO_U = 0.0003172971;
export const E_TO_V = 0.0003593489;
export const N_TO_V = -0.0000763820;

const DET = E_TO_U * N_TO_V - N_TO_U * E_TO_V;
const U_TO_E = N_TO_V / DET;
const V_TO_E = -N_TO_U / DET;
const U_TO_N = -E_TO_V / DET;
const V_TO_N = E_TO_U / DET;

/**
 * Exact inverse of Kilchberg isometric ground-to-UV projection.
 * Maps normalized canvas `(u, v)` to ground-plane meters `{ xM, yM }`.
 */
export function uvToMeters(u, v, out = null) {
  const xM = U_TO_E * u + V_TO_E * v;
  const yM = U_TO_N * u + V_TO_N * v;
  if (out) {
    out.xM = xM;
    out.yM = yM;
    return out;
  }
  return { xM, yM };
}

/**
 * Exact forward Kilchberg isometric ground-to-UV projection.
 * Maps ground-plane meters `(xM, yM)` to normalized canvas `{ u, v }`.
 */
export function metersToUv(xM, yM, out = null) {
  const u = E_TO_U * xM + N_TO_U * yM;
  const v = E_TO_V * xM + N_TO_V * yM;
  if (out) {
    out.u = u;
    out.v = v;
    return out;
  }
  return { u, v };
}

// Integer cell key hashing: safe exact integer for cell coords in [-32768, 32767]
const KEY_BIAS = 32768;
const KEY_STRIDE = 65536;

function cellKey(cx, cy) {
  return (cx + KEY_BIAS) * KEY_STRIDE + (cy + KEY_BIAS);
}

/**
 * Create a zero-allocation steady-state 2D spatial hash grid in ground-plane meters.
 * @param {number} cellSizeM - Grid cell width in meters (default 16 m).
 */
export function createSpatialGrid(cellSizeM = 16) {
  const safeCellSize = (typeof cellSizeM === 'number' && Number.isFinite(cellSizeM) && cellSizeM > 0)
    ? cellSizeM
    : 16;
  const invCell = 1 / safeCellSize;

  const cellMap = new Map();
  const usedBuckets = [];
  const entryPool = [];
  let entryCount = 0;
  let queryStamp = 0;

  function acquireEntry() {
    if (entryCount < entryPool.length) {
      return entryPool[entryCount++];
    }
    const entry = {
      id: null,
      xM: 0,
      yM: 0,
      radiusM: 0,
      kind: null,
      data: null,
      _stamp: 0,
    };
    entryPool.push(entry);
    entryCount++;
    return entry;
  }

  function clear() {
    for (let i = 0; i < usedBuckets.length; i++) {
      usedBuckets[i].length = 0;
    }
    usedBuckets.length = 0;
    entryCount = 0;
  }

  function insert(id, xM, yM, radiusM = 0, kind = null, data = null) {
    if (!Number.isFinite(xM) || !Number.isFinite(yM)) return null;
    const r = (typeof radiusM === 'number' && Number.isFinite(radiusM) && radiusM > 0) ? radiusM : 0;

    const entry = acquireEntry();
    entry.id = id;
    entry.xM = xM;
    entry.yM = yM;
    entry.radiusM = r;
    entry.kind = kind;
    entry.data = data;
    entry._stamp = 0;

    const minCx = Math.floor((xM - r) * invCell);
    const maxCx = Math.floor((xM + r) * invCell);
    const minCy = Math.floor((yM - r) * invCell);
    const maxCy = Math.floor((yM + r) * invCell);

    for (let cx = minCx; cx <= maxCx; cx++) {
      for (let cy = minCy; cy <= maxCy; cy++) {
        const key = cellKey(cx, cy);
        let bucket = cellMap.get(key);
        if (!bucket) {
          bucket = [];
          cellMap.set(key, bucket);
        }
        if (bucket.length === 0) {
          usedBuckets.push(bucket);
        }
        bucket.push(entry);
      }
    }
    return entry;
  }

  function queryRadius(xM, yM, radiusM, filterKind = null, outArray = []) {
    const out = Array.isArray(outArray) ? outArray : [];
    out.length = 0;
    if (!Number.isFinite(xM) || !Number.isFinite(yM)) return out;
    const qR = (typeof radiusM === 'number' && Number.isFinite(radiusM) && radiusM >= 0) ? radiusM : 0;

    queryStamp = (queryStamp + 1) | 0;
    if (queryStamp === 0) {
      for (let i = 0; i < entryPool.length; i++) {
        entryPool[i]._stamp = 0;
      }
      queryStamp = 1;
    }

    const minCx = Math.floor((xM - qR) * invCell);
    const maxCx = Math.floor((xM + qR) * invCell);
    const minCy = Math.floor((yM - qR) * invCell);
    const maxCy = Math.floor((yM + qR) * invCell);
    const hasFilter = filterKind !== null && filterKind !== undefined;

    for (let cx = minCx; cx <= maxCx; cx++) {
      for (let cy = minCy; cy <= maxCy; cy++) {
        const bucket = cellMap.get(cellKey(cx, cy));
        if (!bucket || bucket.length === 0) continue;
        for (let i = 0; i < bucket.length; i++) {
          const entry = bucket[i];
          if (entry._stamp === queryStamp) continue;
          entry._stamp = queryStamp;
          if (hasFilter && entry.kind !== filterKind) continue;
          const dx = entry.xM - xM;
          const dy = entry.yM - yM;
          const maxDist = qR + entry.radiusM;
          if (dx * dx + dy * dy <= maxDist * maxDist) {
            out.push(entry);
          }
        }
      }
    }
    return out;
  }

  return {
    cellSizeM: safeCellSize,
    clear,
    insert,
    queryRadius,
    uvToMeters,
    metersToUv,
    getCount() {
      return entryCount;
    },
  };
}
