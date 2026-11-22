/**
 * Critically-damped & exponential 60fps camera kinematics for the Kilchberg diorama.
 *
 * Implements the tinyrj.com smoothness benchmark:
 *   - Log-space smooth wheel & pinch zoom (tau = 80 ms, focal-point locked)
 *   - iOS-style flick drag inertia / glide (tau = 325 ms, pointer trail ~90 ms)
 *   - Parabolic flyTo() landmark transitions (subtle zoom-out apex, cancelled on user input)
 *   - Continuous held-key WASD/Arrow pan with smooth acceleration & damping
 *   - Frame-rate-independent Follow Camera damping (1 - exp(-9.0 * dt))
 *   - Deterministic / reduced-motion instant settle contract (T3.07)
 *   - Clean settle within < 650 ms (waitForCameraSettled budget = 950 ms)
 */

export function createCameraController(opts = {}) {
  const getViewportSize = opts.getViewportSize || (() => ({ width: 1280, height: 800 }));
  const getWorldSize = opts.getWorldSize || (() => ({ width: 28024, height: 12373 }));
  const getDpr = opts.getDpr || (() => 1);
  const isDeterministic = opts.isDeterministic || (() => false);

  const state = {
    offsetX: 0,
    offsetY: 0,
    scale: 0.05,
    targetScale: 0.05,
    vx: 0, // device px/s
    vy: 0, // device px/s
    moving: false,
  };

  // Drag & inertia state
  let dragging = false;
  let lastDragX = 0;
  let lastDragY = 0;
  const dragTrail = []; // { x, y, t }
  let glideActive = false;
  let glideElapsed = 0; // seconds
  let glideStartMs = 0; // wall-clock ms when glide launched

  // Smooth log-space wheel zoom state
  let zoomActive = false;
  let zoomAnchorX = 0;
  let zoomAnchorY = 0;
  let zoomAnchorWx = 0;
  let zoomAnchorWy = 0;

  // Parabolic flyTo state
  let fly = null; // { t0, ms, s0, s1, u0, v0, u1, v1, keepCentre, bump }

  // Continuous held-key pan state
  const heldKeys = new Set();
  let shiftHeld = false;
  let keyVx = 0; // device px/s
  let keyVy = 0; // device px/s

  // Constants
  const WHEEL_TAU_MS = 80;
  const GLIDE_TAU_MS = 325;
  const GLIDE_TRAIL_WINDOW_MS = 90;
  const GLIDE_RELEASE_MAX_GAP_MS = 60;
  const GLIDE_MIN_LAUNCH_PX_MS = 0.25;
  const GLIDE_STOP_PX_SEC = 12; // < 0.02 px/ms (20 px/s) and < 12 px/s
  const WHEEL_STOP_LOG_EPS = 0.0005;

  function isInstantMode() {
    if (isDeterministic()) return true;
    if (typeof window !== 'undefined' && window.matchMedia) {
      try {
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return true;
      } catch (_) {}
    }
    return false;
  }

  function resolveBounds(bounds) {
    if (bounds && bounds.vpW && bounds.vpH && bounds.worldW && bounds.worldH) {
      return {
        vpW: bounds.vpW,
        vpH: bounds.vpH,
        worldW: bounds.worldW,
        worldH: bounds.worldH,
        dpr: bounds.dpr || getDpr(),
      };
    }
    const vp = getViewportSize();
    const ws = getWorldSize();
    return {
      vpW: vp.width || 1,
      vpH: vp.height || 1,
      worldW: ws.width || 1,
      worldH: ws.height || 1,
      dpr: getDpr(),
    };
  }

  function clampScale(sc, b) {
    const { vpW, worldW, dpr } = b || resolveBounds();
    const minScale = Math.min(0.06 * dpr, (vpW * 0.5) / Math.max(1, worldW));
    const maxScale = 8.0 * dpr;
    return Math.min(maxScale, Math.max(minScale, sc));
  }

  function clampOffsets(b) {
    const { vpW, vpH, worldW, worldH } = b || resolveBounds();
    const scaledW = worldW * state.scale;
    const scaledH = worldH * state.scale;
    const marginX = Math.max(120, vpW * 0.25);
    const marginY = Math.max(120, vpH * 0.25);
    const minX = vpW - scaledW - marginX;
    const maxX = marginX;
    const minY = vpH - scaledH - marginY;
    const maxY = marginY;

    let hitX = false;
    let hitY = false;
    if (scaledW + marginX * 2 <= vpW) {
      state.offsetX = (vpW - scaledW) * 0.5;
      hitX = true;
    } else {
      const clampedX = Math.min(maxX, Math.max(minX, state.offsetX));
      if (clampedX !== state.offsetX) {
        state.offsetX = clampedX;
        hitX = true;
      }
    }
    if (scaledH + marginY * 2 <= vpH) {
      state.offsetY = (vpH - scaledH) * 0.5;
      hitY = true;
    } else {
      const clampedY = Math.min(maxY, Math.max(minY, state.offsetY));
      if (clampedY !== state.offsetY) {
        state.offsetY = clampedY;
        hitY = true;
      }
    }
    if (hitX && glideActive) state.vx = 0;
    if (hitY && glideActive) state.vy = 0;
  }

  function getCenterUV(b) {
    const { vpW, vpH, worldW, worldH } = b || resolveBounds();
    const u = (worldW > 0 && state.scale > 0) ? (vpW * 0.5 - state.offsetX) / (worldW * state.scale) : 0.5;
    const v = (worldH > 0 && state.scale > 0) ? (vpH * 0.5 - state.offsetY) / (worldH * state.scale) : 0.5;
    return { u, v };
  }

  function cancelMotion() {
    dragging = false;
    dragTrail.length = 0;
    fly = null;
    glideActive = false;
    glideElapsed = 0;
    glideStartMs = 0;
    zoomActive = false;
    state.targetScale = state.scale;
    state.vx = 0;
    state.vy = 0;
    keyVx = 0;
    keyVy = 0;
    updateMovingFlag();
  }

  function updateMovingFlag() {
    const glideMoving = glideActive && Math.hypot(state.vx, state.vy) > GLIDE_STOP_PX_SEC;
    const keyMoving = heldKeys.size > 0 || Math.hypot(keyVx, keyVy) > GLIDE_STOP_PX_SEC;
    state.moving = dragging || zoomActive || !!fly || glideMoving || keyMoving;
    return state.moving;
  }

  function isMoving() {
    return updateMovingFlag();
  }

  function isAnimating() {
    const glideMoving = glideActive && Math.hypot(state.vx, state.vy) > GLIDE_STOP_PX_SEC;
    const keyMoving = heldKeys.size > 0 || Math.hypot(keyVx, keyVy) > GLIDE_STOP_PX_SEC;
    return zoomActive || !!fly || glideMoving || keyMoving;
  }

  function getTargetScale() {
    if (fly) return fly.s1;
    if (zoomActive) return state.targetScale;
    return state.scale;
  }

  function setView(u, v, targetScale, viewOpts = {}) {
    const b = resolveBounds();
    cancelMotion();
    const nextScale = viewOpts.unclamped ? targetScale : clampScale(targetScale, b);
    state.scale = nextScale;
    state.targetScale = nextScale;
    state.offsetX = b.vpW * 0.5 - u * b.worldW * state.scale;
    state.offsetY = b.vpH * 0.5 - v * b.worldH * state.scale;
    if (!viewOpts.skipClamp) clampOffsets(b);
    updateMovingFlag();
  }

  function panBy(dxDev, dyDev) {
    fly = null;
    glideActive = false;
    glideElapsed = 0;
    glideStartMs = 0;
    state.vx = 0;
    state.vy = 0;
    if (zoomActive) {
      zoomAnchorWx -= dxDev / Math.max(1e-6, state.scale);
      zoomAnchorWy -= dyDev / Math.max(1e-6, state.scale);
    }
    state.offsetX += dxDev;
    state.offsetY += dyDev;
    clampOffsets();
    updateMovingFlag();
  }

  function beginDrag(x, y, nowMs = performance.now()) {
    fly = null;
    glideActive = false;
    glideElapsed = 0;
    glideStartMs = 0;
    zoomActive = false;
    state.targetScale = state.scale;
    state.vx = 0;
    state.vy = 0;
    dragging = true;
    lastDragX = x;
    lastDragY = y;
    dragTrail.length = 0;
    dragTrail.push({ x, y, t: nowMs });
    updateMovingFlag();
  }

  function moveDrag(x, y, nowMs = performance.now()) {
    if (!dragging) return;
    const dx = x - lastDragX;
    const dy = y - lastDragY;
    lastDragX = x;
    lastDragY = y;

    state.offsetX += dx;
    state.offsetY += dy;
    clampOffsets();

    dragTrail.push({ x, y, t: nowMs });
    // Keep pointer trail over last ~90 ms
    while (dragTrail.length > 2 && (nowMs - dragTrail[0].t) > GLIDE_TRAIL_WINDOW_MS) {
      dragTrail.shift();
    }

    // Track smoothed instantaneous velocity during drag for tile velocity-gating
    const first = dragTrail[0];
    const dtMs = nowMs - first.t;
    if (dtMs >= 4) {
      state.vx = ((x - first.x) / dtMs) * 1000;
      state.vy = ((y - first.y) / dtMs) * 1000;
    }
    updateMovingFlag();
  }

  function endDrag(nowMs = performance.now()) {
    if (!dragging) return;
    dragging = false;
    const releaseMs = Number.isFinite(nowMs) ? nowMs : performance.now();

    if (isInstantMode() || dragTrail.length < 2) {
      state.vx = 0;
      state.vy = 0;
      glideActive = false;
      glideElapsed = 0;
      glideStartMs = 0;
      dragTrail.length = 0;
      updateMovingFlag();
      return;
    }

    const last = dragTrail[dragTrail.length - 1];
    if ((releaseMs - last.t) >= GLIDE_RELEASE_MAX_GAP_MS) {
      state.vx = 0;
      state.vy = 0;
      glideActive = false;
      glideElapsed = 0;
      glideStartMs = 0;
      dragTrail.length = 0;
      updateMovingFlag();
      return;
    }

    // Find oldest sample within the trail window
    let first = dragTrail[0];
    for (let i = 0; i < dragTrail.length - 1; i++) {
      if ((last.t - dragTrail[i].t) <= GLIDE_TRAIL_WINDOW_MS) {
        first = dragTrail[i];
        break;
      }
    }

    const dtMs = Math.max(4, last.t - first.t);
    let vxMs = (last.x - first.x) / dtMs;
    let vyMs = (last.y - first.y) / dtMs;
    const speedMs = Math.hypot(vxMs, vyMs);
    dragTrail.length = 0;

    if (speedMs > GLIDE_MIN_LAUNCH_PX_MS) {
      // Cap extreme impulse speeds so glide feels crisp and always settles within < 650 ms
      const maxSpeedMs = 2.6 * getDpr();
      if (speedMs > maxSpeedMs) {
        const k = maxSpeedMs / speedMs;
        vxMs *= k;
        vyMs *= k;
      }
      state.vx = vxMs * 1000;
      state.vy = vyMs * 1000;
      glideActive = true;
      glideElapsed = 0;
      glideStartMs = releaseMs;
    } else {
      state.vx = 0;
      state.vy = 0;
      glideActive = false;
      glideElapsed = 0;
      glideStartMs = 0;
    }
    updateMovingFlag();
  }

  function wheelZoom(deltaY, deltaMode, ctrlKey, cxDev, cyDev) {
    if (!Number.isFinite(deltaY)) return;
    const b = resolveBounds();
    if (!b.worldW || !b.worldH) return;

    // Normalize deltaY across pixel (0), line (1), and page (2) modes
    const pageH = (typeof window !== 'undefined' && window.innerHeight) ? window.innerHeight : 800;
    const mult = deltaMode === 1 ? 16 : (deltaMode === 2 ? pageH : 1);
    const dy = Math.max(-300, Math.min(300, deltaY * mult));
    const factor = Math.exp(-dy * (ctrlKey ? 0.01 : 0.0022));

    fly = null;
    glideActive = false;
    glideElapsed = 0;
    glideStartMs = 0;
    state.vx = 0;
    state.vy = 0;

    const baseTarget = zoomActive ? state.targetScale : state.scale;
    const nextTarget = clampScale(baseTarget * factor, b);

    // Lock exact world coordinate under cursor
    zoomAnchorX = cxDev;
    zoomAnchorY = cyDev;
    zoomAnchorWx = (cxDev - state.offsetX) / state.scale;
    zoomAnchorWy = (cyDev - state.offsetY) / state.scale;
    state.targetScale = nextTarget;

    if (isInstantMode()) {
      state.scale = nextTarget;
      state.offsetX = zoomAnchorX - zoomAnchorWx * state.scale;
      state.offsetY = zoomAnchorY - zoomAnchorWy * state.scale;
      zoomActive = false;
      clampOffsets(b);
      updateMovingFlag();
      return;
    }

    zoomActive = Math.abs(Math.log(state.targetScale / Math.max(1e-9, state.scale))) >= WHEEL_STOP_LOG_EPS;
    if (!zoomActive) {
      state.scale = state.targetScale;
      state.offsetX = zoomAnchorX - zoomAnchorWx * state.scale;
      state.offsetY = zoomAnchorY - zoomAnchorWy * state.scale;
      clampOffsets(b);
    }
    updateMovingFlag();
  }

  function flyTo(targetU, targetV, targetScale, flyOpts = {}) {
    const b = resolveBounds();
    if (!b.worldW || !b.worldH) return;

    const s1 = clampScale(targetScale, b);
    const keepCentre = !!flyOpts.keepCentre;
    const ms = typeof flyOpts.ms === 'number' ? flyOpts.ms : 520;
    const instant = !!flyOpts.instant || !(ms > 0) || isInstantMode();

    glideActive = false;
    glideElapsed = 0;
    glideStartMs = 0;
    zoomActive = false;
    state.vx = 0;
    state.vy = 0;

    if (instant) {
      fly = null;
      if (keepCentre) {
        const wx = (b.vpW * 0.5 - state.offsetX) / state.scale;
        const wy = (b.vpH * 0.5 - state.offsetY) / state.scale;
        state.scale = s1;
        state.targetScale = s1;
        state.offsetX = b.vpW * 0.5 - wx * state.scale;
        state.offsetY = b.vpH * 0.5 - wy * state.scale;
      } else {
        state.scale = s1;
        state.targetScale = s1;
        state.offsetX = b.vpW * 0.5 - targetU * b.worldW * state.scale;
        state.offsetY = b.vpH * 0.5 - targetV * b.worldH * state.scale;
      }
      clampOffsets(b);
      updateMovingFlag();
      return;
    }

    const c0 = getCenterUV(b);
    const preserveDest = keepCentre && fly && !fly.keepCentre;
    const destU = preserveDest ? fly.u1 : targetU;
    const destV = preserveDest ? fly.v1 : targetV;
    const effectiveKeepCentre = keepCentre && !preserveDest;
    const distUV = effectiveKeepCentre ? 0 : Math.hypot(destU - c0.u, destV - c0.v);
    // Subtle parabolic zoom-out apex on cross-town flights (matches tinyrj.com)
    const bump = (effectiveKeepCentre || flyOpts.noArc) ? 0 : Math.min(0.40, distUV * 1.05);

    state.targetScale = s1;
    fly = {
      t0: performance.now(),
      ms: Math.min(ms, 520),
      s0: state.scale,
      s1,
      u0: c0.u,
      v0: c0.v,
      u1: destU,
      v1: destV,
      keepCentre: effectiveKeepCentre,
      bump,
    };
    updateMovingFlag();
  }

  function normalizePanKey(code) {
    if (code === 'ArrowLeft' || code === 'KeyA' || code === 'a' || code === 'A') return 'left';
    if (code === 'ArrowRight' || code === 'KeyD' || code === 'd' || code === 'D') return 'right';
    if (code === 'ArrowUp' || code === 'KeyW' || code === 'w' || code === 'W') return 'up';
    if (code === 'ArrowDown' || code === 'KeyS' || code === 's' || code === 'S') return 'down';
    if (code === 'ShiftLeft' || code === 'ShiftRight' || code === 'Shift') return 'shift';
    return null;
  }

  function setHeldKey(code, down) {
    const dir = normalizePanKey(code);
    if (!dir) return false;
    if (dir === 'shift') {
      shiftHeld = !!down;
      return true;
    }
    if (down) {
      heldKeys.add(dir);
      fly = null;
      glideActive = false;
      glideElapsed = 0;
      glideStartMs = 0;
      state.vx = 0;
      state.vy = 0;
    } else {
      heldKeys.delete(dir);
    }
    updateMovingFlag();
    return true;
  }

  function clearHeldKeys() {
    heldKeys.clear();
    shiftHeld = false;
    keyVx = 0;
    keyVy = 0;
    updateMovingFlag();
  }

  function followStep(desiredX, desiredY, dt) {
    const safeDt = Math.max(0.001, Math.min(0.1, dt || 0.016));
    const k = 1 - Math.exp(-9.0 * safeDt);
    state.offsetX += (desiredX - state.offsetX) * k;
    state.offsetY += (desiredY - state.offsetY) * k;
    clampOffsets();
    updateMovingFlag();
  }

  function step(dt, nowMs = performance.now(), bounds = null) {
    const b = resolveBounds(bounds);
    const safeDt = Math.max(0.0005, Math.min(0.06, dt || 0.016));
    let changed = false;

    // 1. Parabolic flyTo animation
    if (fly) {
      const k = Math.min(1, Math.max(0, (nowMs - fly.t0) / Math.max(1, fly.ms)));
      const e = 1 - Math.pow(1 - k, 3);
      const logS = Math.log(fly.s0) + (Math.log(fly.s1) - Math.log(fly.s0)) * e
        - fly.bump * Math.sin(Math.PI * k);
      const nextS = k >= 1 ? fly.s1 : clampScale(Math.exp(logS), b);

      if (fly.keepCentre) {
        const wx = (b.vpW * 0.5 - state.offsetX) / state.scale;
        const wy = (b.vpH * 0.5 - state.offsetY) / state.scale;
        state.scale = nextS;
        state.offsetX = b.vpW * 0.5 - wx * state.scale;
        state.offsetY = b.vpH * 0.5 - wy * state.scale;
      } else {
        const cu = fly.u0 + (fly.u1 - fly.u0) * e;
        const cv = fly.v0 + (fly.v1 - fly.v0) * e;
        state.scale = nextS;
        state.offsetX = b.vpW * 0.5 - cu * b.worldW * state.scale;
        state.offsetY = b.vpH * 0.5 - cv * b.worldH * state.scale;
      }
      clampOffsets(b);
      changed = true;
      if (k >= 1) {
        state.scale = fly.s1;
        state.targetScale = fly.s1;
        fly = null;
      }
    }

    // 2. Log-space smooth wheel / pinch zoom (tau = 80 ms, focal-point locked)
    if (zoomActive) {
      const logS = Math.log(Math.max(1e-9, state.scale));
      const logT = Math.log(Math.max(1e-9, state.targetScale));
      const diff = logT - logS;
      if (Math.abs(diff) < WHEEL_STOP_LOG_EPS) {
        state.scale = state.targetScale;
        zoomActive = false;
      } else {
        const alpha = 1 - Math.exp(-(safeDt * 1000) / WHEEL_TAU_MS);
        state.scale = Math.exp(logS + diff * alpha);
      }
      state.offsetX = zoomAnchorX - zoomAnchorWx * state.scale;
      state.offsetY = zoomAnchorY - zoomAnchorWy * state.scale;
      clampOffsets(b);
      changed = true;
    }

    // 3. iOS-style flick pan inertia / glide (tau = 325 ms, settles cleanly within < 650 ms wall-clock)
    if (glideActive && !dragging) {
      glideElapsed += safeDt;
      const glideWallSec = (glideStartMs > 0 && Number.isFinite(nowMs) && nowMs >= glideStartMs)
        ? Math.max(glideElapsed, (nowMs - glideStartMs) * 0.001)
        : glideElapsed;
      // Pure tau = 325 ms for natural iOS glide, gently tightening tail after 360 ms to guarantee < 650 ms wall-clock settle
      const tauEff = glideWallSec <= 0.36
        ? GLIDE_TAU_MS
        : Math.max(60, GLIDE_TAU_MS * (1 - (glideWallSec - 0.36) * 3.3));
      const decay = Math.exp(-(safeDt * 1000) / tauEff);
      // Integrate exact exponential displacement over safeDt
      const prevVx = state.vx;
      const prevVy = state.vy;
      state.vx *= decay;
      state.vy *= decay;
      state.offsetX += (prevVx + state.vx) * 0.5 * safeDt;
      state.offsetY += (prevVy + state.vy) * 0.5 * safeDt;
      clampOffsets(b);
      changed = true;

      const speed = Math.hypot(state.vx, state.vy);
      if (speed < GLIDE_STOP_PX_SEC || glideWallSec >= 0.58) {
        state.vx = 0;
        state.vy = 0;
        glideActive = false;
        glideElapsed = 0;
        glideStartMs = 0;
      }
    }

    // 4. Continuous held-key WASD / Arrow pan with smooth acceleration & damping
    let dirX = 0;
    let dirY = 0;
    if (heldKeys.has('left')) dirX += 1;
    if (heldKeys.has('right')) dirX -= 1;
    if (heldKeys.has('up')) dirY += 1;
    if (heldKeys.has('down')) dirY -= 1;

    if (dirX !== 0 || dirY !== 0) {
      const len = Math.hypot(dirX, dirY) || 1;
      const maxSpeed = (shiftHeld ? 1350 : 720) * b.dpr;
      const targetVx = (dirX / len) * maxSpeed;
      const targetVy = (dirY / len) * maxSpeed;
      const accelK = 1 - Math.exp(-14 * safeDt);
      keyVx += (targetVx - keyVx) * accelK;
      keyVy += (targetVy - keyVy) * accelK;
      state.offsetX += keyVx * safeDt;
      state.offsetY += keyVy * safeDt;
      clampOffsets(b);
      changed = true;
    } else if (Math.abs(keyVx) > 0 || Math.abs(keyVy) > 0) {
      const damp = Math.exp(-12 * safeDt);
      keyVx *= damp;
      keyVy *= damp;
      state.offsetX += keyVx * safeDt;
      state.offsetY += keyVy * safeDt;
      clampOffsets(b);
      changed = true;
      if (Math.hypot(keyVx, keyVy) < GLIDE_STOP_PX_SEC) {
        keyVx = 0;
        keyVy = 0;
      }
    }

    updateMovingFlag();
    return changed;
  }

  return {
    state,
    isMoving,
    isAnimating,
    setView,
    panBy,
    beginDrag,
    moveDrag,
    endDrag,
    wheelZoom,
    flyTo,
    setHeldKey,
    clearHeldKeys,
    followStep,
    step,
    cancelMotion,
    getTargetScale,
  };
}
