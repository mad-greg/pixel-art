/**
 * Deterministic seeded PRNG utilities (zero Math.random() usage).
 * Guarantees pixel-identical ?t= snapshots and reproducible simulation runs.
 */

export function hashString(str) {
  const s = String(str);
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function hashCoords(a, b, salt = 0) {
  let h = (Math.imul((a | 0), 0x9e3779b1) ^ Math.imul((b | 0), 0x85ebca6b) ^ Math.imul((salt | 0), 0xc2b2ae35)) >>> 0;
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b) >>> 0;
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35) >>> 0;
  h ^= h >>> 16;
  return h >>> 0;
}

export function mulberry32(seed) {
  let a = (seed >>> 0) || 1;
  return function next() {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function createRng(seedOrKey) {
  const baseSeed = typeof seedOrKey === 'number' && Number.isFinite(seedOrKey)
    ? (seedOrKey >>> 0)
    : hashString(seedOrKey == null ? 'kilchberg' : String(seedOrKey));
  const rawNext = mulberry32(baseSeed);

  return {
    seed: baseSeed,
    next: rawNext,
    range(lo, hi) {
      return lo + rawNext() * (hi - lo);
    },
    int(lo, hi) {
      const a = Math.ceil(lo);
      const b = Math.floor(hi);
      if (b <= a) return a;
      return a + Math.floor(rawNext() * (b - a + 1));
    },
    pick(arr) {
      if (!arr || arr.length === 0) return undefined;
      return arr[Math.floor(rawNext() * arr.length)];
    },
    chance(p) {
      return rawNext() < p;
    },
    fork(subKey) {
      const subHash = typeof subKey === 'number' && Number.isFinite(subKey)
        ? (subKey >>> 0)
        : hashString(String(subKey));
      return createRng(hashCoords(baseSeed, subHash, 0x517cc1b7));
    },
  };
}
