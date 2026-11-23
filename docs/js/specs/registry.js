/**
 * Declarative, Hot-Injectable Specification Registry for Kilchberg v14.
 *
 * Decouples Kilchberg simulation schedules, routes, inhabitants, vessels, and
 * sports venues from core simulation physics so real-world GTFS/ZVV/SBB/resident
 * data packs can be injected or updated at boot or runtime without engine edits.
 */

import { SBB_KILCHBERG_SERVICES } from './sbb_kilchberg.js';
import { ZVV_KILCHBERG_ROUTES } from './zvv_kilchberg.js';
import { KILCHBERG_INHABITANTS } from './inhabitants_kilchberg.js';
import { KILCHBERG_VESSELS } from './vessels_kilchberg.js';
import { KILCHBERG_SPORTS_SCHEDULES } from './sports_kilchberg.js';

const DOMAINS = Object.freeze(['rail', 'bus', 'inhabitants', 'vessels', 'sports']);
const VALID_LISTENER_DOMAINS = new Set([...DOMAINS, '*']);

function assertPlainObject(val, ctx) {
  if (!val || typeof val !== 'object' || Array.isArray(val)) {
    throw new Error(`SpecRegistry.${ctx}: spec must be a non-null object`);
  }
}

function assertNonEmptyString(val, field, ctx) {
  if (typeof val !== 'string' || val.trim().length === 0) {
    throw new Error(`SpecRegistry.${ctx}: required non-empty string field "${field}" is missing or invalid`);
  }
}

function assertPositiveFinite(val, field, ctx) {
  if (typeof val !== 'number' || !Number.isFinite(val) || val <= 0) {
    throw new Error(`SpecRegistry.${ctx}: required positive finite number field "${field}" is missing or invalid`);
  }
}

function validateRailService(spec) {
  const ctx = 'registerRailService';
  assertPlainObject(spec, ctx);
  assertNonEmptyString(spec.id, 'id', ctx);
  assertNonEmptyString(spec.line, 'line', ctx);
  assertNonEmptyString(spec.trackId, 'trackId', ctx);
  if (spec.trackRank !== undefined && (typeof spec.trackRank !== 'number' || !Number.isFinite(spec.trackRank))) {
    throw new Error(`SpecRegistry.${ctx}: optional "trackRank" must be a finite number`);
  }
  if (spec.carriages !== undefined) {
    assertPositiveFinite(spec.carriages, 'carriages', ctx);
  }
  if (spec.stops !== undefined && !Array.isArray(spec.stops)) {
    throw new Error(`SpecRegistry.${ctx}: optional "stops" must be an array`);
  }
  return { ...spec, id: spec.id.trim() };
}

function validateBusRoute(spec) {
  const ctx = 'registerBusRoute';
  assertPlainObject(spec, ctx);
  assertNonEmptyString(spec.id, 'id', ctx);
  assertNonEmptyString(spec.line, 'line', ctx);
  if (!Array.isArray(spec.corridorSegments) || spec.corridorSegments.length === 0) {
    throw new Error(`SpecRegistry.${ctx}: required non-empty array field "corridorSegments" is missing or invalid`);
  }
  for (let i = 0; i < spec.corridorSegments.length; i++) {
    const seg = spec.corridorSegments[i];
    if (!seg || typeof seg !== 'object' || typeof seg.roadId !== 'string' || !seg.roadId.trim()) {
      throw new Error(`SpecRegistry.${ctx}: corridorSegments[${i}] must have a non-empty string "roadId"`);
    }
  }
  if (spec.stops !== undefined && !Array.isArray(spec.stops)) {
    throw new Error(`SpecRegistry.${ctx}: optional "stops" must be an array`);
  }
  return { ...spec, id: spec.id.trim() };
}

function validateInhabitant(spec) {
  const ctx = 'registerInhabitant';
  assertPlainObject(spec, ctx);
  assertNonEmptyString(spec.id, 'id', ctx);
  assertNonEmptyString(spec.name, 'name', ctx);
  if (!spec.home || typeof spec.home !== 'object') {
    throw new Error(`SpecRegistry.${ctx}: required object field "home" is missing or invalid`);
  }
  const hasHomeAnchor = (typeof spec.home.poiId === 'string' && spec.home.poiId.trim().length > 0)
    || (typeof spec.home.buildingId === 'string' && spec.home.buildingId.trim().length > 0)
    || (typeof spec.home.buildingId === 'number' && Number.isFinite(spec.home.buildingId))
    || (Array.isArray(spec.home.uv) && spec.home.uv.length >= 2
      && Number.isFinite(spec.home.uv[0]) && Number.isFinite(spec.home.uv[1]));
  if (!hasHomeAnchor) {
    throw new Error(`SpecRegistry.${ctx}: "home" must specify a valid "poiId", "buildingId", or "uv"`);
  }
  if (!Array.isArray(spec.routine) || spec.routine.length === 0) {
    throw new Error(`SpecRegistry.${ctx}: required non-empty array field "routine" is missing or invalid`);
  }
  for (let i = 0; i < spec.routine.length; i++) {
    const step = spec.routine[i];
    if (!step || typeof step !== 'object'
      || typeof step.startMin !== 'number' || !Number.isFinite(step.startMin)
      || typeof step.endMin !== 'number' || !Number.isFinite(step.endMin)
      || typeof step.activity !== 'string' || !step.activity.trim()) {
      throw new Error(`SpecRegistry.${ctx}: routine[${i}] must have finite "startMin", finite "endMin", and non-empty string "activity"`);
    }
  }
  return { ...spec, id: spec.id.trim() };
}

function validateVessel(spec) {
  const ctx = 'registerVessel';
  assertPlainObject(spec, ctx);
  assertNonEmptyString(spec.id, 'id', ctx);
  assertNonEmptyString(spec.kind, 'kind', ctx);
  assertPositiveFinite(spec.hullLengthM, 'hullLengthM', ctx);
  if (spec.hullBeamM !== undefined) {
    assertPositiveFinite(spec.hullBeamM, 'hullBeamM', ctx);
  }
  if (spec.maxSpeedMps !== undefined) {
    assertPositiveFinite(spec.maxSpeedMps, 'maxSpeedMps', ctx);
  }
  return { ...spec, id: spec.id.trim() };
}

function validateSportsSchedule(spec) {
  const ctx = 'registerSportsSchedule';
  assertPlainObject(spec, ctx);
  assertNonEmptyString(spec.id, 'id', ctx);
  assertNonEmptyString(spec.venueId, 'venueId', ctx);
  assertNonEmptyString(spec.sport, 'sport', ctx);
  return { ...spec, id: spec.id.trim() };
}

export function createSpecRegistry(initialPacks = {}) {
  const stores = {
    rail: new Map(),
    bus: new Map(),
    inhabitants: new Map(),
    vessels: new Map(),
    sports: new Map(),
  };

  const listeners = {
    rail: new Set(),
    bus: new Set(),
    inhabitants: new Set(),
    vessels: new Set(),
    sports: new Set(),
    '*': new Set(),
  };

  function emit(domain, action, id, spec) {
    const evt = { domain, action, id, spec };
    const domainSet = listeners[domain];
    const starSet = listeners['*'];
    const domainFns = domainSet ? [...domainSet] : [];
    const starFns = [...starSet];
    for (let i = 0; i < domainFns.length; i++) {
      const fn = domainFns[i];
      if (domainSet.has(fn)) {
        fn(evt);
      }
    }
    for (let i = 0; i < starFns.length; i++) {
      const fn = starFns[i];
      if (starSet.has(fn)) {
        fn(evt);
      }
    }
  }

  function registerInDomain(domain, validator, spec) {
    const normalized = validator(spec);
    const map = stores[domain];
    const existed = map.has(normalized.id);
    map.set(normalized.id, normalized);
    emit(domain, existed ? 'update' : 'register', normalized.id, normalized);
    return normalized;
  }

  function removeFromDomain(domain, id) {
    if (typeof id !== 'string' || !id.trim()) return false;
    const key = id.trim();
    const map = stores[domain];
    const prev = map.get(key);
    if (!prev) return false;
    map.delete(key);
    emit(domain, 'remove', key, prev);
    return true;
  }

  function getFromDomain(domain) {
    return Array.from(stores[domain].values());
  }

  const registry = {
    registerRailService(spec) {
      return registerInDomain('rail', validateRailService, spec);
    },
    removeRailService(id) {
      return removeFromDomain('rail', id);
    },
    getRailServices() {
      return getFromDomain('rail');
    },

    registerBusRoute(spec) {
      return registerInDomain('bus', validateBusRoute, spec);
    },
    removeBusRoute(id) {
      return removeFromDomain('bus', id);
    },
    getBusRoutes() {
      return getFromDomain('bus');
    },

    registerInhabitant(spec) {
      return registerInDomain('inhabitants', validateInhabitant, spec);
    },
    removeInhabitant(id) {
      return removeFromDomain('inhabitants', id);
    },
    getInhabitants() {
      return getFromDomain('inhabitants');
    },

    registerVessel(spec) {
      return registerInDomain('vessels', validateVessel, spec);
    },
    removeVessel(id) {
      return removeFromDomain('vessels', id);
    },
    getVessels() {
      return getFromDomain('vessels');
    },

    registerSportsSchedule(spec) {
      return registerInDomain('sports', validateSportsSchedule, spec);
    },
    removeSportsSchedule(id) {
      return removeFromDomain('sports', id);
    },
    getSportsSchedules() {
      return getFromDomain('sports');
    },

    onChange(domain, listener) {
      if (!VALID_LISTENER_DOMAINS.has(domain)) {
        throw new Error(`SpecRegistry.onChange: invalid domain "${domain}" (expected one of ${[...VALID_LISTENER_DOMAINS].join(', ')})`);
      }
      if (typeof listener !== 'function') {
        throw new Error('SpecRegistry.onChange: listener must be a function');
      }
      listeners[domain].add(listener);
      return function unsubscribe() {
        listeners[domain].delete(listener);
      };
    },

    getSummary() {
      return {
        rail: stores.rail.size,
        bus: stores.bus.size,
        inhabitants: stores.inhabitants.size,
        vessels: stores.vessels.size,
        sports: stores.sports.size,
      };
    },
  };

  if (initialPacks && typeof initialPacks === 'object') {
    if (Array.isArray(initialPacks.rail)) {
      for (let i = 0; i < initialPacks.rail.length; i++) {
        registry.registerRailService(initialPacks.rail[i]);
      }
    }
    if (Array.isArray(initialPacks.bus)) {
      for (let i = 0; i < initialPacks.bus.length; i++) {
        registry.registerBusRoute(initialPacks.bus[i]);
      }
    }
    if (Array.isArray(initialPacks.inhabitants)) {
      for (let i = 0; i < initialPacks.inhabitants.length; i++) {
        registry.registerInhabitant(initialPacks.inhabitants[i]);
      }
    }
    if (Array.isArray(initialPacks.vessels)) {
      for (let i = 0; i < initialPacks.vessels.length; i++) {
        registry.registerVessel(initialPacks.vessels[i]);
      }
    }
    if (Array.isArray(initialPacks.sports)) {
      for (let i = 0; i < initialPacks.sports.length; i++) {
        registry.registerSportsSchedule(initialPacks.sports[i]);
      }
    }
  }

  return registry;
}

export function createDefaultKilchbergRegistry() {
  return createSpecRegistry({
    rail: SBB_KILCHBERG_SERVICES,
    bus: ZVV_KILCHBERG_ROUTES,
    inhabitants: KILCHBERG_INHABITANTS,
    vessels: KILCHBERG_VESSELS,
    sports: KILCHBERG_SPORTS_SCHEDULES,
  });
}
