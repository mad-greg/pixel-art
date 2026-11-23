/**
 * Kilchberg Realistic Sports Physics Simulation Engine (v14).
 *
 * Replaces stateless sinusoidal/Lissajous animations with genuine seeded,
 * deterministic state machines:
 *   - TennisRallySim (F10): 2-segment ballistic arc with mid-flight clay bounce,
 *     clay dust puff, 1.25–1.75 s club groundstrokes (1.15–1.35 s serves),
 *     4–12 shot rallies, 3–5 s point pauses, 2.5–5.5 m/s footwork, displacement stride.
 *   - SoccerMatchSim (F11): Real 3D ball kinematics (gravity -9.81 m/s^2, grass
 *     rolling drag -1.8 m/s^2, damped bounce e = 0.52), possession/dribble/pass/
 *     shot/goal-kick/kickoff state machine, <= 6.5 m/s hard player speed cap,
 *     >= 2.5 m (full) / >= 1.8 m (multisport) separation, displacement stride.
 *
 * 100% deterministic (zero Math.random()), extreme-timestamp safe (?t=-5, 1e16, NaN).
 */

import { hashString, mulberry32 } from './rng.js';
import { uvToMeters } from './spatial.js';

const PERIOD_SEC = 180.0;
const FIXED_DT = 0.05;
const GRAVITY = 9.81;
const GRASS_DRAG = 1.8;
const AIR_DRAG = 0.22;
const BOUNCE_RESTITUTION = 0.52;

const DEFAULT_TC_COURTS = [
  { sw: [0.17328, 0.34316], ne: [0.17907, 0.33876], lat: [0.00074, 0.00126] },
  { sw: [0.17637, 0.34803], ne: [0.18205, 0.34351], lat: [0.00076, 0.00124] },
  { sw: [0.16329, 0.35330], ne: [0.16909, 0.34874], lat: [0.00075, 0.00124] },
];

const DEFAULT_HOCHWEID = {
  center: [0.31344, 0.22808],
  half_l: [0.01366, -0.00941],
  half_w: [0.00507, 0.00951],
};

function clamp(v, lo, hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

function normalizeTimeSec(tSec) {
  if (typeof tSec !== 'number' || !Number.isFinite(tSec)) return 0;
  const r = tSec % PERIOD_SEC;
  return r < 0 ? r + PERIOD_SEC : r;
}

function measureUvSpanM(du, dv) {
  const m = uvToMeters(du, dv);
  return Math.hypot(m.xM, m.yM);
}

function isVenueActiveForMode(spec, mode, clockSnapshot) {
  if (!spec) return mode !== 'night';
  if (mode === 'night') {
    return false;
  }
  if (spec.diurnal && spec.diurnal[mode] === false) {
    return false;
  }
  // In live/manual clock mode, gently consult sessions if provided;
  // in deterministic mode (or daytime), always keep venues active.
  if (clockSnapshot && clockSnapshot.clockMode !== 'deterministic' && Array.isArray(spec.sessions) && spec.sessions.length > 0) {
    const mins = (clockSnapshot.hours || 0) * 60 + (clockSnapshot.minutes || 0);
    const dow = clockSnapshot.dayOfWeek != null ? clockSnapshot.dayOfWeek : 6;
    for (let i = 0; i < spec.sessions.length; i++) {
      const ses = spec.sessions[i];
      if (Array.isArray(ses.days) && !ses.days.includes(dow)) continue;
      if (mins >= ses.startMin && mins <= ses.endMin) return true;
    }
    // Keep floodlit venues open in evening sunset
    return !!(spec.floodlit && mode === 'sunset');
  }
  return true;
}

// ============================================================================
// TENNIS RALLY SIMULATION (F10)
// ============================================================================

export class TennisRallySim {
  constructor(cfg) {
    this.id = cfg.id;
    this.venueId = cfg.venueId || cfg.id;
    this.courtIndex = cfg.courtIndex != null ? cfg.courtIndex : 0;
    this.lengthM = clamp(cfg.lengthM || 21.5, 16.0, 26.0);
    this.halfLenM = this.lengthM * 0.5;
    this.halfWidthM = clamp(cfg.halfWidthM || 4.1, 3.2, 6.0);
    this.seed = hashString(`tennis:${this.id}:${this.courtIndex}`);
    this.reset();
  }

  reset() {
    this.rng = mulberry32(this.seed);
    this.state = 'BALL_IN_FLIGHT';
    this.server = this.rng() < 0.5 ? 0 : 1; // 0 = SW (-x), 1 = NE (+x)
    this.hitter = this.server;
    this.rallyShotsRemaining = 5 + Math.floor(this.rng() * 7); // 5..11
    this.pauseTimer = 0;
    this.pauseDuration = 3.5;

    // Players in court-local meters: x in [-halfLenM, +halfLenM], y in [-halfWidthM, +halfWidthM]
    this.players = [
      {
        x: -this.halfLenM * 0.94,
        y: (this.rng() - 0.5) * this.halfWidthM * 0.6,
        vx: 0,
        vy: 0,
        stridePhase: this.rng() * 6.28,
        swingTimer: 0,
        maxSpeedMps: 4.6,
      },
      {
        x: this.halfLenM * 0.94,
        y: (this.rng() - 0.5) * this.halfWidthM * 0.6,
        vx: 0,
        vy: 0,
        stridePhase: this.rng() * 6.28,
        swingTimer: 0,
        maxSpeedMps: 4.6,
      },
    ];

    // Ball state
    this.ball = {
      x: 0,
      y: 0,
      z: 0.9,
      lu: 0,
      lv: 0,
      visible: true,
    };

    // Trail ring buffer (3 points)
    this.trail = [
      { lu: 0, lv: 0, z: 0.9, active: false },
      { lu: 0, lv: 0, z: 0.9, active: false },
      { lu: 0, lv: 0, z: 0.9, active: false },
    ];
    this.trailTimer = 0;

    // Clay dust puff at bounce point
    this.dust = {
      active: false,
      lu: 0,
      lv: 0,
      age: 0,
      maxAge: 0.58,
    };

    // Shot parameters
    this.shot = {
      x0: 0,
      y0: 0,
      z0: 0.9,
      xb: 0,
      yb: 0,
      x1: 0,
      y1: 0,
      z1: 0.9,
      peak1: 1.8,
      peak2: 0.25,
      tBounceFrac: 0.72,
      duration: 1.45,
      elapsed: 0,
      bounced: false,
      isServe: false,
    };

    // Telemetry
    this.minShotSec = Infinity;
    this.maxShotSec = 0;
    this.bouncesObserved = 0;
    this.maxPlayerMps = 0;

    // Launch initial shot at a staggered phase so courts aren't synchronized
    this._launchShot(this.hitter, false);
    const staggerFrac = 0.1 + this.rng() * 0.55;
    this.shot.elapsed = this.shot.duration * staggerFrac;
    this._evalBallOnShot();
  }

  _launchShot(hitterIdx, isServe) {
    const receiverIdx = hitterIdx === 0 ? 1 : 0;
    const dir = hitterIdx === 0 ? 1 : -1;
    const hitter = this.players[hitterIdx];

    const x0 = hitter.x;
    const y0 = hitter.y;
    const z0 = isServe ? 2.15 : 0.90;

    // Target strike point on receiver's baseline side
    const targetDepth = isServe ? (0.86 + this.rng() * 0.10) : (0.88 + this.rng() * 0.10);
    const x1 = dir * this.halfLenM * targetDepth;
    const y1 = (this.rng() * 2 - 1) * this.halfWidthM * 0.78;
    const z1 = 0.90;

    // Bounce point inside opponent's court (0.48..0.82 of halfLen for groundstrokes, 0.36..0.52 for serve)
    const bounceDepth = isServe
      ? (0.36 + this.rng() * 0.16)
      : (0.48 + this.rng() * 0.34);
    const xb = dir * this.halfLenM * bounceDepth;
    const tGeom = clamp((xb - x0) / (x1 - x0 || 1), 0.58, 0.84);
    const yb = y0 + (y1 - y0) * tGeom;

    // Physical speed: pre-bounce 14..20 m/s for groundstrokes, ~18..21 m/s for serves
    // Post-bounce ~35% slower -> tBounceFrac ~ 0.68..0.75
    const preDist = Math.hypot(xb - x0, yb - y0);
    const postDist = Math.hypot(x1 - xb, y1 - yb);
    const preSpeed = isServe
      ? (17.5 + this.rng() * 3.0)
      : (14.2 + this.rng() * 5.2);
    const postSpeed = preSpeed * 0.65;
    const rawPreT = preDist / preSpeed;
    const rawPostT = postDist / postSpeed;
    let duration = rawPreT + rawPostT;

    // Enforce authentic clay-court duration bounds [1.15, 1.35] serve, [1.25, 1.75] rally
    if (isServe) {
      duration = clamp(duration, 1.15, 1.35);
    } else {
      duration = clamp(duration, 1.25, 1.75);
    }
    const tBounceFrac = clamp(rawPreT / Math.max(0.01, rawPreT + rawPostT), 0.68, 0.76);

    this.shot.x0 = x0;
    this.shot.y0 = y0;
    this.shot.z0 = z0;
    this.shot.xb = xb;
    this.shot.yb = yb;
    this.shot.x1 = x1;
    this.shot.y1 = y1;
    this.shot.z1 = z1;
    this.shot.peak1 = isServe ? (1.35 + this.rng() * 0.30) : (1.55 + this.rng() * 0.65);
    this.shot.peak2 = 0.20 + this.rng() * 0.14;
    this.shot.tBounceFrac = tBounceFrac;
    this.shot.duration = duration;
    this.shot.elapsed = 0;
    this.shot.bounced = false;
    this.shot.isServe = isServe;

    this.hitter = hitterIdx;
    this.players[hitterIdx].swingTimer = 0.32;

    if (duration < this.minShotSec) this.minShotSec = duration;
    if (duration > this.maxShotSec) this.maxShotSec = duration;

    // Reset trail at launch
    for (let i = 0; i < 3; i++) {
      this.trail[i].active = false;
    }
    this.trailTimer = 0;

    // Receiver anticipates (x1, y1)
    this._receiverIdx = receiverIdx;
  }

  _evalBallOnShot() {
    const sh = this.shot;
    const u = clamp(sh.elapsed / sh.duration, 0, 1);
    const tb = sh.tBounceFrac;
    let bx;
    let by;
    let bz;

    if (u <= tb) {
      const s1 = u / tb;
      bx = sh.x0 + (sh.xb - sh.x0) * s1;
      by = sh.y0 + (sh.yb - sh.y0) * s1;
      // Parabola #1: starts at z0, clears net, hits clay at z = 0 when s1 = 1
      bz = sh.z0 * (1 - s1) + 4.0 * sh.peak1 * s1 * (1 - s1);
    } else {
      const s2 = (u - tb) / (1 - tb);
      bx = sh.xb + (sh.x1 - sh.xb) * s2;
      by = sh.yb + (sh.y1 - sh.yb) * s2;
      // Parabola #2: rises from z = 0 at bounce to z1 = 0.9 m at strike
      bz = sh.z1 * s2 + 4.0 * sh.peak2 * s2 * (1 - s2);
    }

    this.ball.x = bx;
    this.ball.y = by;
    this.ball.z = Math.max(0, bz);
    this.ball.lu = bx / this.halfLenM;
    this.ball.lv = by / this.halfWidthM;
    this.ball.visible = true;
  }

  _steerPlayer(pl, tx, ty, maxSpeed, dt) {
    const dx = tx - pl.x;
    const dy = ty - pl.y;
    const dist = Math.hypot(dx, dy);

    // Smooth deceleration near target so players pause naturally
    let desiredSpd = 0;
    if (dist > 0.15) {
      desiredSpd = Math.min(maxSpeed, dist * 2.8);
    }
    const desVx = dist > 1e-4 ? (dx / dist) * desiredSpd : 0;
    const desVy = dist > 1e-4 ? (dy / dist) * desiredSpd : 0;

    // Smooth acceleration/deceleration (9.5 m/s^2)
    const maxDv = 9.5 * dt;
    const dvx = desVx - pl.vx;
    const dvy = desVy - pl.vy;
    const dvMag = Math.hypot(dvx, dvy);
    if (dvMag > maxDv && dvMag > 1e-6) {
      pl.vx += (dvx / dvMag) * maxDv;
      pl.vy += (dvy / dvMag) * maxDv;
    } else {
      pl.vx = desVx;
      pl.vy = desVy;
    }

    // Hard speed cap <= 5.2 m/s (strictly <= 5.5 m/s)
    const spd = Math.hypot(pl.vx, pl.vy);
    const cap = Math.min(5.2, maxSpeed);
    if (spd > cap) {
      pl.vx = (pl.vx / spd) * cap;
      pl.vy = (pl.vy / spd) * cap;
    }

    const oldX = pl.x;
    const oldY = pl.y;
    pl.x = clamp(pl.x + pl.vx * dt, -this.halfLenM * 1.06, this.halfLenM * 1.06);
    pl.y = clamp(pl.y + pl.vy * dt, -this.halfWidthM * 1.08, this.halfWidthM * 1.08);

    const moved = Math.hypot(pl.x - oldX, pl.y - oldY);
    const actualSpeed = dt > 1e-5 ? moved / dt : 0;
    if (actualSpeed > this.maxPlayerMps) this.maxPlayerMps = actualSpeed;

    // Displacement-driven leg stride (zero leg-pumping when standing still!)
    pl.stridePhase += moved * 2.25;
    if (pl.swingTimer > 0) {
      pl.swingTimer = Math.max(0, pl.swingTimer - dt);
    }
  }

  step(dt) {
    if (dt <= 0) return;

    // Update clay dust puff
    if (this.dust.active) {
      this.dust.age += dt;
      if (this.dust.age >= this.dust.maxAge) {
        this.dust.active = false;
      }
    }

    if (this.state === 'BALL_IN_FLIGHT') {
      const prevU = this.shot.elapsed / this.shot.duration;
      this.shot.elapsed += dt;
      const curU = this.shot.elapsed / this.shot.duration;

      // Detect ground bounce crossing
      if (!this.shot.bounced && curU >= this.shot.tBounceFrac && prevU <= this.shot.tBounceFrac + 0.25) {
        this.shot.bounced = true;
        this.bouncesObserved++;
        this.dust.active = true;
        this.dust.lu = this.shot.xb / this.halfLenM;
        this.dust.lv = this.shot.yb / this.halfWidthM;
        this.dust.age = 0;
      }

      // Record trail dots every ~0.06 s
      this.trailTimer += dt;
      if (this.trailTimer >= 0.06) {
        this.trailTimer = 0;
        this.trail[2].lu = this.trail[1].lu;
        this.trail[2].lv = this.trail[1].lv;
        this.trail[2].z = this.trail[1].z;
        this.trail[2].active = this.trail[1].active;
        this.trail[1].lu = this.trail[0].lu;
        this.trail[1].lv = this.trail[0].lv;
        this.trail[1].z = this.trail[0].z;
        this.trail[1].active = this.trail[0].active;
        this.trail[0].lu = this.ball.lu;
        this.trail[0].lv = this.ball.lv;
        this.trail[0].z = this.ball.z;
        this.trail[0].active = true;
      }

      this._evalBallOnShot();

      // Steer receiver toward predicted strike point, hitter recovers toward center baseline
      const recIdx = this.hitter === 0 ? 1 : 0;
      const hitIdx = this.hitter;
      this._steerPlayer(this.players[recIdx], this.shot.x1, this.shot.y1, 4.6, dt);
      this._steerPlayer(
        this.players[hitIdx],
        (hitIdx === 0 ? -1 : 1) * this.halfLenM * 0.95,
        this.players[hitIdx].y * 0.45,
        2.8,
        dt,
      );

      if (this.shot.elapsed >= this.shot.duration) {
        // Ensure bounce counted even on coarse step
        if (!this.shot.bounced) {
          this.shot.bounced = true;
          this.bouncesObserved++;
        }
        this.rallyShotsRemaining--;
        if (this.rallyShotsRemaining > 0) {
          this._launchShot(recIdx, false);
        } else {
          // Point ends -> walk/retrieve pause (3.2..4.6 s)
          this.state = 'SERVE_PREP';
          this.pauseTimer = 0;
          this.pauseDuration = 3.2 + this.rng() * 1.4;
          this.server = this.server === 0 ? 1 : 0;
          this.serveSide = this.rng() < 0.5 ? -1 : 1;
          for (let i = 0; i < 3; i++) this.trail[i].active = false;
        }
      }
    } else {
      // SERVE_PREP: players walk calmly to serve/receive spots, then server tosses ball
      this.pauseTimer += dt;
      const srvIdx = this.server;
      const recIdx = srvIdx === 0 ? 1 : 0;
      const srvDir = srvIdx === 0 ? -1 : 1;
      const side = this.serveSide || 1;

      const srvTx = srvDir * this.halfLenM * 0.96;
      const srvTy = side * this.halfWidthM * 0.32;
      const recTx = -srvDir * this.halfLenM * 0.96;
      const recTy = -side * this.halfWidthM * 0.45;

      this._steerPlayer(this.players[srvIdx], srvTx, srvTy, 2.2, dt);
      this._steerPlayer(this.players[recIdx], recTx, recTy, 2.2, dt);

      const tossStart = this.pauseDuration - 0.75;
      if (this.pauseTimer >= tossStart) {
        const tossP = clamp((this.pauseTimer - tossStart) / 0.75, 0, 1);
        const srv = this.players[srvIdx];
        this.ball.x = srv.x;
        this.ball.y = srv.y;
        this.ball.z = 0.95 + Math.sin(tossP * Math.PI * 0.75) * 1.45;
        this.ball.lu = srv.x / this.halfLenM;
        this.ball.lv = srv.y / this.halfWidthM;
        this.ball.visible = true;
      } else {
        // Ball held by server
        const srv = this.players[srvIdx];
        this.ball.x = srv.x;
        this.ball.y = srv.y;
        this.ball.z = 0.85;
        this.ball.lu = srv.x / this.halfLenM;
        this.ball.lv = srv.y / this.halfWidthM;
        this.ball.visible = false;
      }

      if (this.pauseTimer >= this.pauseDuration) {
        this.state = 'BALL_IN_FLIGHT';
        this.rallyShotsRemaining = 4 + Math.floor(this.rng() * 8); // 4..11
        this._launchShot(srvIdx, true);
      }
    }
  }
}

// ============================================================================
// SOCCER & MULTISPORT MATCH SIMULATION (F11)
// ============================================================================

const FULL_12_FORMATIONS = [
  // Team 0 (attacks +x): GK + 5 outfield
  { team: 0, role: 'gk', fx: -0.92, fy: 0.0 },
  { team: 0, role: 'def', fx: -0.55, fy: -0.34 },
  { team: 0, role: 'def', fx: -0.52, fy: 0.34 },
  { team: 0, role: 'mid', fx: -0.10, fy: -0.26 },
  { team: 0, role: 'mid', fx: -0.05, fy: 0.28 },
  { team: 0, role: 'fwd', fx: 0.38, fy: 0.0 },
  // Team 1 (attacks -x): GK + 5 outfield
  { team: 1, role: 'gk', fx: 0.92, fy: 0.0 },
  { team: 1, role: 'def', fx: 0.55, fy: -0.34 },
  { team: 1, role: 'def', fx: 0.52, fy: 0.34 },
  { team: 1, role: 'mid', fx: 0.10, fy: -0.28 },
  { team: 1, role: 'mid', fx: 0.05, fy: 0.26 },
  { team: 1, role: 'fwd', fx: -0.38, fy: 0.0 },
];

const FULL_10_FORMATIONS = [
  // Team 0 (attacks +x): GK + 4 outfield
  { team: 0, role: 'gk', fx: -0.90, fy: 0.0 },
  { team: 0, role: 'def', fx: -0.50, fy: -0.30 },
  { team: 0, role: 'def', fx: -0.48, fy: 0.32 },
  { team: 0, role: 'mid', fx: -0.02, fy: -0.22 },
  { team: 0, role: 'fwd', fx: 0.36, fy: 0.18 },
  // Team 1 (attacks -x): GK + 4 outfield
  { team: 1, role: 'gk', fx: 0.90, fy: 0.0 },
  { team: 1, role: 'def', fx: 0.50, fy: -0.30 },
  { team: 1, role: 'def', fx: 0.48, fy: 0.32 },
  { team: 1, role: 'mid', fx: 0.02, fy: 0.22 },
  { team: 1, role: 'fwd', fx: -0.36, fy: -0.18 },
];

const MULTI_4_FORMATIONS = [
  // 2v2 / 4-player court
  { team: 0, role: 'mid', fx: -0.38, fy: -0.26 },
  { team: 0, role: 'fwd', fx: 0.20, fy: 0.26 },
  { team: 1, role: 'mid', fx: 0.38, fy: 0.24 },
  { team: 1, role: 'fwd', fx: -0.20, fy: -0.26 },
];

export class SoccerMatchSim {
  constructor(cfg) {
    this.id = cfg.id;
    this.venueId = cfg.venueId || cfg.id;
    this.isMultisport = !!cfg.isMultisport;
    this.playerCount = cfg.playerCount || (this.isMultisport ? 4 : 10);
    this.halfLengthM = clamp(cfg.halfLengthM || (this.isMultisport ? 15.0 : 45.0), 10.0, 56.0);
    this.halfWidthM = clamp(cfg.halfWidthM || (this.isMultisport ? 10.0 : 26.0), 7.0, 36.0);
    this.goalHalfWidthM = this.isMultisport ? 2.4 : 3.8;
    this.minSeparationM = this.isMultisport ? 1.8 : 2.5;
    this.seed = hashString(`soccer:${this.id}`);
    this.reset();
  }

  reset() {
    this.rng = mulberry32(this.seed);
    const tmpl = this.playerCount >= 12
      ? FULL_12_FORMATIONS
      : (this.playerCount >= 10 ? FULL_10_FORMATIONS : MULTI_4_FORMATIONS);

    this.players = tmpl.map((f, idx) => ({
      idx,
      team: f.team,
      role: f.role,
      homeX: f.fx * this.halfLengthM,
      homeY: f.fy * this.halfWidthM,
      x: f.fx * this.halfLengthM,
      y: f.fy * this.halfWidthM,
      vx: 0,
      vy: 0,
      lu: f.fx,
      lv: f.fy,
      stridePhase: this.rng() * 6.28,
      isCarrier: false,
    }));

    // Real 3D ball state in pitch-local meters
    this.ball = {
      x: 0,
      y: 0,
      z: 0,
      vx: 0,
      vy: 0,
      vz: 0,
      lu: 0,
      lv: 0,
    };

    this.trail = [
      { lu: 0, lv: 0, z: 0, active: false },
      { lu: 0, lv: 0, z: 0, active: false },
    ];
    this.trailTimer = 0;

    // Pick initial outfield carrier
    const firstCarrier = this.players.findIndex((p) => p.role !== 'gk');
    this.carrierIdx = firstCarrier >= 0 ? firstCarrier : 0;
    this.targetIdx = -1;
    this.mode = 'POSSESSION_DRIBBLE';
    this.modeTimer = 0;
    this.dribbleLimit = 1.6 + this.rng() * 1.4;
    this.restartTeam = 0;
    this.lastTouchTeam = 0;

    // Pre-allocate pre-step position buffers (zero per-step allocation)
    this._prevX = new Float64Array(this.players.length);
    this._prevY = new Float64Array(this.players.length);

    // Place carrier near ball
    const c = this.players[this.carrierIdx];
    c.x = (this.rng() - 0.5) * this.halfLengthM * 0.25;
    c.y = (this.rng() - 0.5) * this.halfWidthM * 0.25;
    c.isCarrier = true;

    // 1-pass initial separation guard so t = 0 starts with all pairs >= 1.35 m
    const HARD_MIN_SEP_M = 1.35;
    const initMaxX = this.halfLengthM * 0.94;
    const initMaxY = this.halfWidthM * 0.88;
    for (let i = 0; i < this.players.length; i++) {
      const a = this.players[i];
      for (let j = i + 1; j < this.players.length; j++) {
        const b = this.players[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d = Math.hypot(dx, dy);
        if (d < HARD_MIN_SEP_M) {
          const nx = d > 1e-4 ? dx / d : 1;
          const ny = d > 1e-4 ? dy / d : 0;
          const halfPush = (HARD_MIN_SEP_M - d) * 0.5 + 0.005;
          a.x = clamp(a.x - nx * halfPush, -initMaxX, initMaxX);
          a.y = clamp(a.y - ny * halfPush, -initMaxY, initMaxY);
          b.x = clamp(b.x + nx * halfPush, -initMaxX, initMaxX);
          b.y = clamp(b.y + ny * halfPush, -initMaxY, initMaxY);
        }
      }
    }

    this.ball.x = c.x + (c.team === 0 ? 0.8 : -0.8);
    this.ball.y = c.y;
    this._syncNormCoords();

    // Telemetry
    this.maxPlayerMps = 0;
    this.observedModes = new Set([this.mode]);
  }

  _syncNormCoords() {
    this.ball.lu = clamp(this.ball.x / this.halfLengthM, -1.0, 1.0);
    this.ball.lv = clamp(this.ball.y / this.halfWidthM, -1.0, 1.0);
    for (let i = 0; i < this.players.length; i++) {
      const p = this.players[i];
      p.lu = clamp(p.x / this.halfLengthM, -0.96, 0.96);
      p.lv = clamp(p.y / this.halfWidthM, -0.90, 0.90);
    }
  }

  _setMode(newMode) {
    this.mode = newMode;
    this.modeTimer = 0;
    this.observedModes.add(newMode);
  }

  _kickBallTo(tx, ty, speedMps, loftVz) {
    const dx = tx - this.ball.x;
    const dy = ty - this.ball.y;
    const dist = Math.hypot(dx, dy) || 1;
    this.ball.vx = (dx / dist) * speedMps;
    this.ball.vy = (dy / dist) * speedMps;
    this.ball.vz = loftVz;
    if (this.carrierIdx >= 0 && this.players[this.carrierIdx]) {
      this.players[this.carrierIdx].isCarrier = false;
      this.lastTouchTeam = this.players[this.carrierIdx].team;
    }
    this.carrierIdx = -1;
  }

  _integrateBallFree(dt) {
    const b = this.ball;
    // Vertical gravity & damped bounce
    if (b.z > 0 || b.vz > 0) {
      b.vz -= GRAVITY * dt;
      b.z += b.vz * dt;
      if (b.z <= 0) {
        b.z = 0;
        if (Math.abs(b.vz) > 0.65) {
          b.vz = -b.vz * BOUNCE_RESTITUTION;
        } else {
          b.vz = 0;
        }
      }
    }

    // Horizontal drag (grass rolling drag on ground, light air drag in flight)
    const spd = Math.hypot(b.vx, b.vy);
    if (spd > 1e-4) {
      const decel = (b.z <= 0.01 ? GRASS_DRAG : AIR_DRAG) * dt;
      const newSpd = Math.max(0, spd - decel);
      const scale = newSpd / spd;
      b.vx *= scale;
      b.vy *= scale;
    } else {
      b.vx = 0;
      b.vy = 0;
    }

    b.x += b.vx * dt;
    b.y += b.vy * dt;

    // Sideline deflection
    const maxY = this.halfWidthM * 0.92;
    if (b.y > maxY) {
      b.y = maxY;
      b.vy = -Math.abs(b.vy) * 0.5;
    } else if (b.y < -maxY) {
      b.y = -maxY;
      b.vy = Math.abs(b.vy) * 0.5;
    }

    // Endline / goal check (skip re-triggering during GOAL_CELEBRATION so modeTimer advances to KICKOFF)
    const maxX = this.halfLengthM * 0.95;
    if (this.mode !== 'GOAL_CELEBRATION' && Math.abs(b.x) >= maxX) {
      const scoringSide = b.x > 0 ? 0 : 1; // Team 0 scores at +x, Team 1 at -x
      if (Math.abs(b.y) <= this.goalHalfWidthM && b.z <= 2.6) {
        // GOAL!
        b.x = Math.sign(b.x) * maxX;
        b.vx *= 0.2;
        b.vy *= 0.2;
        this.restartTeam = scoringSide === 0 ? 1 : 0;
        this._setMode('GOAL_CELEBRATION');
      } else {
        // Missed wide -> Goal kick for defending team
        b.x = Math.sign(b.x) * (maxX - 1.5);
        b.vx = 0;
        b.vy = 0;
        b.vz = 0;
        b.z = 0;
        this.restartTeam = scoringSide === 0 ? 1 : 0;
        this._setMode('GOAL_KICK');
      }
    }
  }

  _selectPassTarget(carrier) {
    const dir = carrier.team === 0 ? 1 : -1;
    let bestIdx = -1;
    let bestScore = -1e9;
    for (let i = 0; i < this.players.length; i++) {
      const mate = this.players[i];
      if (i === carrier.idx || mate.team !== carrier.team || mate.role === 'gk') continue;
      const dx = mate.x - carrier.x;
      const dy = mate.y - carrier.y;
      const dist = Math.hypot(dx, dy);
      if (dist < (this.isMultisport ? 4.0 : 8.0) || dist > (this.isMultisport ? 24.0 : 48.0)) continue;
      // Prefer forward and open teammates
      let nearestOpp = 999;
      for (let j = 0; j < this.players.length; j++) {
        const opp = this.players[j];
        if (opp.team === carrier.team) continue;
        const od = Math.hypot(opp.x - mate.x, opp.y - mate.y);
        if (od < nearestOpp) nearestOpp = od;
      }
      const forwardBonus = dir * dx * 0.35;
      const opennessBonus = Math.min(12, nearestOpp) * 1.1;
      const score = forwardBonus + opennessBonus + (this.rng() - 0.5) * 4.0;
      if (score > bestScore) {
        bestScore = score;
        bestIdx = i;
      }
    }
    return bestIdx;
  }

  _movePlayer(pl, tx, ty, maxSpeed, dt) {
    const hardCap = pl.role === 'gk' ? 4.4 : 6.1; // Strictly <= 4.5 (GK) and <= 6.5 (outfield)
    const cap = Math.min(maxSpeed, hardCap);

    // Compute desired velocity
    const dx = tx - pl.x;
    const dy = ty - pl.y;
    const dist = Math.hypot(dx, dy);
    const desSpd = dist > 0.25 ? Math.min(cap, dist * 2.4) : 0;
    let desVx = dist > 1e-4 ? (dx / dist) * desSpd : 0;
    let desVy = dist > 1e-4 ? (dy / dist) * desSpd : 0;

    // Pairwise separation repulsion (>= 2.5 m full pitch, >= 1.8 m multisport) + inward velocity cancel < 1.50 m
    let nearCollision = false;
    const minSepSq = this.minSeparationM * this.minSeparationM;
    for (let j = 0; j < this.players.length; j++) {
      if (j === pl.idx) continue;
      const other = this.players[j];
      const sx = pl.x - other.x;
      const sy = pl.y - other.y;
      const sdSq = sx * sx + sy * sy;
      if (sdSq > 1e-8 && sdSq < minSepSq) {
        const sd = Math.sqrt(sdSq);
        const nx = sx / sd;
        const ny = sy / sd;
        const frac = (this.minSeparationM - sd) / this.minSeparationM;
        const closeBoost = sd < 1.55 ? ((1.55 - sd) / 1.55) * 8.0 : 0;
        const push = frac * 5.0 + closeBoost;
        desVx += nx * push;
        desVy += ny * push;
        // Cancel inward closing velocity when within 1.50 m
        if (sd < 1.50) {
          nearCollision = true;
          const inward = -(desVx * nx + desVy * ny);
          if (inward > 0) {
            desVx += nx * inward;
            desVy += ny * inward;
          }
        }
      }
    }

    // Clamp combined desired velocity to hardCap
    const desMag = Math.hypot(desVx, desVy);
    if (desMag > cap) {
      desVx = (desVx / desMag) * cap;
      desVy = (desVy / desMag) * cap;
    }

    // Smooth acceleration (faster sidestep/braking during close-range separation)
    const maxDv = (nearCollision ? 18.0 : 8.5) * dt;
    const dvx = desVx - pl.vx;
    const dvy = desVy - pl.vy;
    const dvMag = Math.hypot(dvx, dvy);
    if (dvMag > maxDv && dvMag > 1e-6) {
      pl.vx += (dvx / dvMag) * maxDv;
      pl.vy += (dvy / dvMag) * maxDv;
    } else {
      pl.vx = desVx;
      pl.vy = desVy;
    }

    // Final hard speed enforcement
    const spd = Math.hypot(pl.vx, pl.vy);
    if (spd > hardCap) {
      pl.vx = (pl.vx / spd) * hardCap;
      pl.vy = (pl.vy / spd) * hardCap;
    }

    pl.x = clamp(pl.x + pl.vx * dt, -this.halfLengthM * 0.94, this.halfLengthM * 0.94);
    pl.y = clamp(pl.y + pl.vy * dt, -this.halfWidthM * 0.88, this.halfWidthM * 0.88);
  }

  step(dt) {
    if (dt <= 0) return;
    const prevX = this._prevX;
    const prevY = this._prevY;
    for (let i = 0; i < this.players.length; i++) {
      prevX[i] = this.players[i].x;
      prevY[i] = this.players[i].y;
    }
    let movedCarrierIdx = -1;
    this.modeTimer += dt;

    // Update ball trail every ~0.10 s when moving fast
    this.trailTimer += dt;
    if (this.trailTimer >= 0.10) {
      this.trailTimer = 0;
      const bSpd = Math.hypot(this.ball.vx, this.ball.vy);
      this.trail[1].lu = this.trail[0].lu;
      this.trail[1].lv = this.trail[0].lv;
      this.trail[1].z = this.trail[0].z;
      this.trail[1].active = this.trail[0].active;
      this.trail[0].lu = this.ball.lu;
      this.trail[0].lv = this.ball.lv;
      this.trail[0].z = this.ball.z;
      this.trail[0].active = bSpd > 6.5;
    }

    // 1. Update ball & state machine transitions
    if (this.mode === 'POSSESSION_DRIBBLE') {
      const carrier = this.players[this.carrierIdx];
      if (!carrier) {
        this._setMode('KICKOFF');
      } else {
        const dir = carrier.team === 0 ? 1 : -1;
        // Carrier dribbles toward opponent goal
        const goalX = dir * this.halfLengthM * 0.85;
        const dribbleSpeed = this.isMultisport ? 3.8 : 4.4;
        const weaveY = Math.sin(this.modeTimer * 1.4 + carrier.idx) * 2.5;
        movedCarrierIdx = this.carrierIdx;
        this._movePlayer(carrier, goalX, clamp(carrier.y + weaveY, -this.halfWidthM * 0.72, this.halfWidthM * 0.72), dribbleSpeed, dt);

        // Keep ball ~0.8 m ahead of carrier's feet
        const cSpd = Math.hypot(carrier.vx, carrier.vy);
        const hx = cSpd > 0.2 ? carrier.vx / cSpd : dir;
        const hy = cSpd > 0.2 ? carrier.vy / cSpd : 0;
        this.ball.x = clamp(carrier.x + hx * 0.8, -this.halfLengthM * 0.94, this.halfLengthM * 0.94);
        this.ball.y = clamp(carrier.y + hy * 0.8, -this.halfWidthM * 0.88, this.halfWidthM * 0.88);
        this.ball.z = 0;
        this.ball.vx = carrier.vx;
        this.ball.vy = carrier.vy;
        this.ball.vz = 0;

        // Check nearest pressing defender
        let nearestOppDist = 999;
        let nearestOppIdx = -1;
        for (let i = 0; i < this.players.length; i++) {
          const opp = this.players[i];
          if (opp.team === carrier.team || opp.role === 'gk') continue;
          const d = Math.hypot(opp.x - carrier.x, opp.y - carrier.y);
          if (d < nearestOppDist) {
            nearestOppDist = d;
            nearestOppIdx = i;
          }
        }

        // Tackle turnover if defender gets very close after >= 0.7 s
        if (this.modeTimer > 0.7 && nearestOppDist < 1.7 && this.rng() < 0.12) {
          carrier.isCarrier = false;
          this.carrierIdx = nearestOppIdx;
          this.players[nearestOppIdx].isCarrier = true;
          this.modeTimer = 0;
          this.dribbleLimit = 1.4 + this.rng() * 1.5;
        } else {
          // Decide shoot vs pass
          const inShootRange = dir * carrier.x > this.halfLengthM * (this.isMultisport ? 0.36 : 0.50);
          const underPressure = nearestOppDist < (this.isMultisport ? 2.8 : 4.2);

          if (inShootRange && (this.modeTimer >= 0.85 || underPressure)) {
            const targetX = dir * this.halfLengthM * 1.02;
            const targetY = (this.rng() * 2 - 1) * this.goalHalfWidthM * 0.95;
            const shotSpd = this.isMultisport ? (11.5 + this.rng() * 3.5) : (16.5 + this.rng() * 4.8);
            const shotVz = 2.0 + this.rng() * 2.8;
            this._kickBallTo(targetX, targetY, shotSpd, shotVz);
            this._setMode('SHOT_ON_GOAL');
          } else if (this.modeTimer >= this.dribbleLimit || (underPressure && this.modeTimer >= 0.65)) {
            const tgt = this._selectPassTarget(carrier);
            if (tgt >= 0) {
              const mate = this.players[tgt];
              const leadX = mate.x + mate.vx * 0.45;
              const leadY = mate.y + mate.vy * 0.45;
              const isLofted = !this.isMultisport && this.rng() < 0.30;
              const passSpd = this.isMultisport
                ? (8.5 + this.rng() * 3.5)
                : (isLofted ? (12.0 + this.rng() * 3.0) : (11.5 + this.rng() * 4.5));
              const passVz = isLofted ? (3.8 + this.rng() * 1.8) : 0;
              this.targetIdx = tgt;
              this._kickBallTo(leadX, leadY, passSpd, passVz);
              this._setMode('PASS_IN_FLIGHT');
            } else {
              this.dribbleLimit += 1.0;
            }
          }
        }
      }
    } else if (this.mode === 'PASS_IN_FLIGHT') {
      this._integrateBallFree(dt);

      // Check interception by target or nearby outfield player after 0.25 s
      if (this.modeTimer > 0.25 && this.ball.z < 1.8) {
        let bestIdx = -1;
        let bestD = 1.8;
        for (let i = 0; i < this.players.length; i++) {
          const p = this.players[i];
          if (p.role === 'gk') continue;
          const d = Math.hypot(p.x - this.ball.x, p.y - this.ball.y);
          if (d < bestD) {
            bestD = d;
            bestIdx = i;
          }
        }
        if (bestIdx >= 0) {
          this.carrierIdx = bestIdx;
          this.players[bestIdx].isCarrier = true;
          this.targetIdx = -1;
          this.dribbleLimit = 1.4 + this.rng() * 1.6;
          this._setMode('POSSESSION_DRIBBLE');
        }
      }
      // Timeout fallback if ball slows to stop
      if (this.mode === 'PASS_IN_FLIGHT' && this.modeTimer > 5.0) {
        let nearest = 0;
        let minD = 1e9;
        for (let i = 0; i < this.players.length; i++) {
          if (this.players[i].role === 'gk') continue;
          const d = Math.hypot(this.players[i].x - this.ball.x, this.players[i].y - this.ball.y);
          if (d < minD) { minD = d; nearest = i; }
        }
        this.targetIdx = nearest;
      }
    } else if (this.mode === 'SHOT_ON_GOAL') {
      this._integrateBallFree(dt);

      // Check goalkeeper save
      if (this.mode === 'SHOT_ON_GOAL' && this.modeTimer > 0.2) {
        for (let i = 0; i < this.players.length; i++) {
          const p = this.players[i];
          if (p.role !== 'gk') continue;
          if (p.team === this.lastTouchTeam) continue;
          const d = Math.hypot(p.x - this.ball.x, p.y - this.ball.y);
          if (d < 2.2 && this.ball.z < 2.4) {
            // Goalkeeper save!
            this.ball.vx = 0;
            this.ball.vy = 0;
            this.ball.vz = 0;
            this.ball.z = 0;
            this.restartTeam = p.team;
            this._setMode('GOAL_KICK');
            break;
          }
        }
      }

      // If shot slows down before reaching goal, nearest outfield player picks it up
      if (this.mode === 'SHOT_ON_GOAL' && Math.hypot(this.ball.vx, this.ball.vy) < 1.2 && this.modeTimer > 1.2) {
        this._setMode('PASS_IN_FLIGHT');
      }
    } else if (this.mode === 'GOAL_CELEBRATION') {
      this._integrateBallFree(dt);
      if (this.modeTimer >= 2.4) {
        this.ball.x = 0;
        this.ball.y = 0;
        this.ball.z = 0;
        this.ball.vx = 0;
        this.ball.vy = 0;
        this.ball.vz = 0;
        this._setMode('KICKOFF');
      }
    } else if (this.mode === 'GOAL_KICK') {
      const gk = this.players.find((p) => p.role === 'gk' && p.team === this.restartTeam);
      const kickX = gk ? gk.x : (this.restartTeam === 0 ? -this.halfLengthM * 0.82 : this.halfLengthM * 0.82);
      const kickY = gk ? gk.y : 0;
      this.ball.x = kickX + (this.restartTeam === 0 ? 1.0 : -1.0);
      this.ball.y = kickY;
      this.ball.z = 0;
      this.ball.vx = 0;
      this.ball.vy = 0;
      this.ball.vz = 0;

      if (this.modeTimer >= 2.0) {
        // Kick out to a teammate
        const mate = this.players.find((p) => p.team === this.restartTeam && p.role !== 'gk');
        const tgt = mate || this.players[0];
        this.targetIdx = tgt.idx;
        this.lastTouchTeam = this.restartTeam;
        this._kickBallTo(tgt.x, tgt.y, this.isMultisport ? 9.5 : 14.0, this.isMultisport ? 0 : 3.2);
        this._setMode('PASS_IN_FLIGHT');
      }
    } else if (this.mode === 'KICKOFF') {
      this.ball.x = 0;
      this.ball.y = 0;
      this.ball.z = 0;
      if (this.modeTimer >= 1.5) {
        const starter = this.players.find((p) => p.team === this.restartTeam && p.role !== 'gk') || this.players[0];
        this.carrierIdx = starter.idx;
        starter.isCarrier = true;
        this.dribbleLimit = 1.5 + this.rng() * 1.4;
        this._setMode('POSSESSION_DRIBBLE');
      }
    }

    // 2. Move all non-carrier players realistically
    // Find nearest 1 pressing defender per team
    let presserIdx = -1;
    if (this.carrierIdx >= 0) {
      const carrierTeam = this.players[this.carrierIdx].team;
      let bestD = 1e9;
      for (let i = 0; i < this.players.length; i++) {
        const p = this.players[i];
        if (p.team === carrierTeam || p.role === 'gk') continue;
        const d = Math.hypot(p.x - this.ball.x, p.y - this.ball.y);
        if (d < bestD) { bestD = d; presserIdx = i; }
      }
    }

    for (let i = 0; i < this.players.length; i++) {
      const p = this.players[i];
      if (i === movedCarrierIdx) continue;

      if (p.role === 'gk') {
        const gx = p.team === 0 ? -this.halfLengthM * 0.91 : this.halfLengthM * 0.91;
        const gy = clamp(this.ball.y * 0.45, -this.goalHalfWidthM * 1.15, this.goalHalfWidthM * 1.15);
        this._movePlayer(p, gx, gy, 4.3, dt);
      } else if (this.mode === 'GOAL_CELEBRATION' || this.mode === 'KICKOFF') {
        // Jog back toward home positions
        const tx = p.homeX * 0.75;
        const ty = p.homeY * 0.8;
        this._movePlayer(p, tx, ty, 3.0, dt);
      } else if (i === this.targetIdx && this.mode === 'PASS_IN_FLIGHT') {
        // Sprint to intercept pass
        this._movePlayer(p, this.ball.x, this.ball.y, 5.8, dt);
      } else if (i === presserIdx) {
        // Active defender pressing the ball carrier
        this._movePlayer(p, this.ball.x, this.ball.y, 5.4, dt);
      } else {
        // Formation anchor shifted smoothly with ball position
        const shiftX = this.ball.x * 0.34;
        const shiftY = this.ball.y * 0.28;
        const tx = clamp(p.homeX + shiftX, -this.halfLengthM * 0.85, this.halfLengthM * 0.85);
        const ty = clamp(p.homeY + shiftY, -this.halfWidthM * 0.82, this.halfWidthM * 0.82);
        this._movePlayer(p, tx, ty, 3.3, dt);
      }
    }

    // 3. Post-move pairwise separation floor (1.35 m target -> >= 1.2 m hard floor, still < 1.7 m tackle radius)
    const HARD_SEP_M = 1.35;
    const HARD_SEP_SQ = HARD_SEP_M * HARD_SEP_M;
    const maxBoundX = this.halfLengthM * 0.94;
    const maxBoundY = this.halfWidthM * 0.88;
    for (let pass = 0; pass < 2; pass++) {
      let anyPushed = false;
      for (let i = 0; i < this.players.length; i++) {
        const a = this.players[i];
        for (let j = i + 1; j < this.players.length; j++) {
          const b = this.players[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dSq = dx * dx + dy * dy;
          if (dSq < HARD_SEP_SQ) {
            anyPushed = true;
            const d = Math.sqrt(dSq);
            const nx = d > 1e-4 ? dx / d : 1;
            const ny = d > 1e-4 ? dy / d : 0;
            const halfPush = (HARD_SEP_M - d) * 0.5 + 0.005;
            a.x = clamp(a.x - nx * halfPush, -maxBoundX, maxBoundX);
            a.y = clamp(a.y - ny * halfPush, -maxBoundY, maxBoundY);
            b.x = clamp(b.x + nx * halfPush, -maxBoundX, maxBoundX);
            b.y = clamp(b.y + ny * halfPush, -maxBoundY, maxBoundY);
          }
        }
      }
      if (!anyPushed) break;
    }

    // 4. Net per-step speed cap + honest finite-difference telemetry + displacement-driven stride
    for (let i = 0; i < this.players.length; i++) {
      const pl = this.players[i];
      const hardCap = pl.role === 'gk' ? 4.4 : 6.1;
      const maxDisp = hardCap * dt;
      const dx = pl.x - prevX[i];
      const dy = pl.y - prevY[i];
      const disp = Math.hypot(dx, dy);
      if (disp > maxDisp && disp > 1e-6) {
        const scale = maxDisp / disp;
        pl.x = prevX[i] + dx * scale;
        pl.y = prevY[i] + dy * scale;
      }
      const netDisp = Math.hypot(pl.x - prevX[i], pl.y - prevY[i]);
      const netSpeed = dt > 1e-5 ? netDisp / dt : 0;
      if (netSpeed > this.maxPlayerMps) this.maxPlayerMps = netSpeed;
      pl.stridePhase += netDisp * 1.9;
    }

    this._syncNormCoords();
  }
}

// ============================================================================
// UNIFIED SPORTS SIM MANAGER (Published on ctx.shared.sportsSim)
// ============================================================================

export function createSportsSim(animData, specs = null) {
  const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
  const tcSrc = Array.isArray(vig.tc_kilchberg) && vig.tc_kilchberg.length >= 3
    ? vig.tc_kilchberg
    : DEFAULT_TC_COURTS;
  const spVig = vig.sportplatz_hochweid || DEFAULT_HOCHWEID;
  const extraSports = (animData && animData.network && Array.isArray(animData.network.extra_sports))
    ? animData.network.extra_sports
    : [];

  const tennisMap = new Map();
  const soccerMap = new Map();

  // 1. TC Kilchberg 3 clay courts
  for (let ci = 0; ci < tcSrc.length; ci++) {
    const c = tcSrc[ci];
    const lenM = measureUvSpanM(c.ne[0] - c.sw[0], c.ne[1] - c.sw[1]);
    const halfWM = measureUvSpanM(c.lat[0], c.lat[1]);
    const id = `tc_kilchberg_court_${ci}`;
    tennisMap.set(id, new TennisRallySim({
      id,
      venueId: 'tc_kilchberg',
      courtIndex: ci,
      lengthM: lenM > 10 ? lenM : 21.5,
      halfWidthM: halfWM > 2 ? halfWM : 4.1,
    }));
  }

  // 2. Sportplatz Hochweid main pitch
  const hochHalfL = measureUvSpanM(spVig.half_l[0], spVig.half_l[1]);
  const hochHalfW = measureUvSpanM(spVig.half_w[0], spVig.half_w[1]);
  soccerMap.set('sportplatz_hochweid', new SoccerMatchSim({
    id: 'sportplatz_hochweid',
    venueId: 'sportplatz_hochweid',
    isMultisport: false,
    playerCount: 12,
    halfLengthM: hochHalfL > 20 ? hochHalfL : 49.3,
    halfWidthM: hochHalfW > 12 ? hochHalfW : 30.2,
  }));

  // 3. Extra sports venues (lakeside tennis, 2 football pitches, 2 multisport courts)
  for (let fi = 0; fi < extraSports.length; fi++) {
    const fld = extraSports[fi];
    const id = fld.id || `extra_sport_${fi}`;
    if (fld.kind === 'tennis') {
      tennisMap.set(id, new TennisRallySim({
        id,
        venueId: id,
        courtIndex: fi,
        lengthM: (fld.h_m || 23.9) * 0.84,
        halfWidthM: (fld.w_m || 11.1) * 0.40,
      }));
    } else if (fld.kind === 'football') {
      soccerMap.set(id, new SoccerMatchSim({
        id,
        venueId: id,
        isMultisport: false,
        playerCount: 10,
        halfLengthM: (fld.h_m || 90.0) * 0.42,
        halfWidthM: (fld.w_m || 50.0) * 0.40,
      }));
    } else {
      soccerMap.set(id, new SoccerMatchSim({
        id,
        venueId: id,
        isMultisport: true,
        playerCount: 4,
        halfLengthM: (fld.h_m || 32.0) * 0.42,
        halfWidthM: (fld.w_m || 22.0) * 0.40,
      }));
    }
  }

  let lastTNorm = null;
  let lastMode = 'day';
  let activeFlags = new Map();

  function getSpecById(specReg, id) {
    if (!specReg || typeof specReg.getSportsSchedules !== 'function') return null;
    const list = specReg.getSportsSchedules();
    for (let i = 0; i < list.length; i++) {
      if (list[i].id === id) return list[i];
    }
    return null;
  }

  function stepAll(dt) {
    for (const sim of tennisMap.values()) {
      sim.step(dt);
    }
    for (const sim of soccerMap.values()) {
      sim.step(dt);
    }
  }

  function resetAll() {
    for (const sim of tennisMap.values()) {
      sim.reset();
    }
    for (const sim of soccerMap.values()) {
      sim.reset();
    }
  }

  function updateToTime(tSec, mode = 'day', clockSnapshot = null, activeSpecs = specs) {
    const tNorm = normalizeTimeSec(tSec);
    lastMode = mode || 'day';

    // Evaluate schedule activity flags
    for (const id of tennisMap.keys()) {
      activeFlags.set(id, isVenueActiveForMode(getSpecById(activeSpecs, id), lastMode, clockSnapshot));
    }
    for (const id of soccerMap.keys()) {
      activeFlags.set(id, isVenueActiveForMode(getSpecById(activeSpecs, id), lastMode, clockSnapshot));
    }

    if (lastTNorm !== null && Math.abs(tNorm - lastTNorm) < 1e-6) {
      return;
    }

    const isLiveMode = !!(clockSnapshot && clockSnapshot.clockMode !== 'deterministic');
    const delta = lastTNorm !== null ? (tNorm - lastTNorm) : -1;
    if (isLiveMode && lastTNorm !== null && delta > 0) {
      let rem = Math.min(delta, 0.10);
      while (rem > FIXED_DT) {
        stepAll(FIXED_DT);
        rem -= FIXED_DT;
      }
      if (rem > 1e-5) {
        stepAll(rem);
      }
    } else if (lastTNorm === null || delta < 0 || delta > 0.55) {
      // Cold-start or time jump: deterministic fixed-step replay from t = 0
      resetAll();
      const jumpDt = 0.1;
      let cur = 0;
      while (cur + jumpDt <= tNorm) {
        stepAll(jumpDt);
        cur += jumpDt;
      }
      const rem = tNorm - cur;
      if (rem > 1e-5) {
        stepAll(rem);
      }
    } else if (delta > 0) {
      let rem = delta;
      while (rem > FIXED_DT) {
        stepAll(FIXED_DT);
        rem -= FIXED_DT;
      }
      if (rem > 1e-5) {
        stepAll(rem);
      }
    }
    lastTNorm = tNorm;
  }

  function getTennisCourt(id) {
    return tennisMap.get(id) || null;
  }

  function getSoccerPitch(id) {
    return soccerMap.get(id) || null;
  }

  function isVenueActive(id) {
    return activeFlags.has(id) ? !!activeFlags.get(id) : lastMode !== 'night';
  }

  function getTelemetry() {
    let maxSoccerPlayerMps = 0;
    let minTennisShotSec = Infinity;
    let maxTennisShotSec = 0;
    let tennisBouncesObserved = 0;
    const ballModes = {};

    for (const [id, sim] of tennisMap.entries()) {
      if (sim.minShotSec < minTennisShotSec) minTennisShotSec = sim.minShotSec;
      if (sim.maxShotSec > maxTennisShotSec) maxTennisShotSec = sim.maxShotSec;
      tennisBouncesObserved += sim.bouncesObserved;
      void id;
    }

    for (const [id, sim] of soccerMap.entries()) {
      if (sim.maxPlayerMps > maxSoccerPlayerMps) maxSoccerPlayerMps = sim.maxPlayerMps;
      ballModes[id] = sim.mode;
    }

    return {
      tennisCourts: tennisMap.size,
      soccerPitches: soccerMap.size,
      maxSoccerPlayerMps: Number(maxSoccerPlayerMps.toFixed(3)),
      minTennisShotSec: Number((Number.isFinite(minTennisShotSec) ? minTennisShotSec : 0).toFixed(3)),
      maxTennisShotSec: Number(maxTennisShotSec.toFixed(3)),
      tennisBouncesObserved,
      ballModes,
    };
  }

  return {
    updateToTime,
    getTennisCourt,
    getSoccerPitch,
    isVenueActive,
    getTelemetry,
    getTennisCourts: () => Array.from(tennisMap.values()),
    getSoccerPitches: () => Array.from(soccerMap.values()),
  };
}
