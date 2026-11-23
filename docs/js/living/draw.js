/**
 * Shared pixel-art drawing primitives for the Kilchberg v13.0 Living Layer.
 *
 * Hard guardrails:
 *   - Deterministic seeded rendering only (no wall-clock or unseeded RNG)
 *   - Pre-baked 64x64 pixel-buffer glow sprites (no per-frame radial gradients)
 *   - Pure vector/pixel geometry (all building signage is baked via pipeline/signage.py)
 */

const GLOW_SPRITE_SIZE = 64;
const GLOW_CACHE_MAX = 32;
const glowSpriteCache = new Map();

const GLOW_COLOR_PRESETS = {
  amber: [255, 198, 96],
  warm: [255, 224, 146],
  gold: [255, 212, 92],
  cool: [216, 236, 255],
  blue: [59, 130, 246],
  cyan: [120, 232, 255],
  green: [34, 229, 132],
  red: [255, 59, 59],
  moonlight: [186, 216, 255],
  white: [248, 250, 252],
};

function parseGlowRgb(colorKey) {
  if (GLOW_COLOR_PRESETS[colorKey]) return GLOW_COLOR_PRESETS[colorKey];
  if (typeof colorKey === 'string') {
    const parts = colorKey.split(',');
    if (parts.length >= 3) {
      const r = Math.max(0, Math.min(255, Math.round(Number(parts[0]) || 255)));
      const g = Math.max(0, Math.min(255, Math.round(Number(parts[1]) || 224)));
      const b = Math.max(0, Math.min(255, Math.round(Number(parts[2]) || 146)));
      return [r, g, b];
    }
  }
  return GLOW_COLOR_PRESETS.warm;
}

function getOrCreateGlowSprite(colorKey) {
  if (typeof document === 'undefined' || !document.createElement) return null;
  const key = String(colorKey || 'warm');
  let sprite = glowSpriteCache.get(key);
  if (sprite) return sprite;

  const [r, g, b] = parseGlowRgb(key);
  const canvas = document.createElement('canvas');
  canvas.width = GLOW_SPRITE_SIZE;
  canvas.height = GLOW_SPRITE_SIZE;
  const gctx = canvas.getContext('2d');
  if (!gctx || typeof gctx.createImageData !== 'function') return null;

  const img = gctx.createImageData(GLOW_SPRITE_SIZE, GLOW_SPRITE_SIZE);
  const data = img.data;
  const half = (GLOW_SPRITE_SIZE - 1) * 0.5;
  const invHalf = 1 / half;
  for (let y = 0; y < GLOW_SPRITE_SIZE; y++) {
    const dy = (y - half) * invHalf;
    for (let x = 0; x < GLOW_SPRITE_SIZE; x++) {
      const dx = (x - half) * invHalf;
      const dist = Math.hypot(dx, dy);
      if (dist >= 1.0) continue;
      const falloff = Math.pow(1.0 - dist, 2.15);
      const idx = (y * GLOW_SPRITE_SIZE + x) * 4;
      data[idx] = r;
      data[idx + 1] = g;
      data[idx + 2] = b;
      data[idx + 3] = Math.round(falloff * 255);
    }
  }
  gctx.putImageData(img, 0, 0);

  if (glowSpriteCache.size >= GLOW_CACHE_MAX) {
    const oldest = glowSpriteCache.keys().next().value;
    if (oldest !== undefined) glowSpriteCache.delete(oldest);
  }
  glowSpriteCache.set(key, canvas);
  return canvas;
}

/**
 * Draw a soft pre-cached radial glow sprite (no per-frame radial gradient calls).
 * Gracefully falls back to concentric alpha arcs in non-DOM headless environments.
 */
export function blitGlow(ctx, x, y, radius, colorKey = 'warm', alpha = 0.42, radiusY = null, rotRad = 0) {
  const rx = Number.isFinite(radius) ? radius : 0;
  const ry = (radiusY != null && Number.isFinite(radiusY)) ? radiusY : rx;
  if (rx <= 0.5 || ry <= 0.5 || alpha <= 0.01) return;

  const sprite = getOrCreateGlowSprite(colorKey);
  if (sprite) {
    ctx.save();
    ctx.globalAlpha = Math.max(0, Math.min(1, alpha));
    if (rotRad) {
      ctx.translate(x, y);
      ctx.rotate(rotRad);
      ctx.drawImage(sprite, -rx, -ry, rx * 2, ry * 2);
    } else {
      ctx.drawImage(sprite, x - rx, y - ry, rx * 2, ry * 2);
    }
    ctx.restore();
    return;
  }

  // Headless / non-DOM canvas fallback: 3 concentric circles without radial gradients
  const [r, g, b] = parseGlowRgb(colorKey);
  ctx.save();
  ctx.translate(x, y);
  if (rotRad) ctx.rotate(rotRad);
  if (Math.abs(rx - ry) > 0.25 && rx > 0) ctx.scale(1, ry / rx);
  const rings = [
    [1.0, 0.22],
    [0.62, 0.36],
    [0.30, 0.58],
  ];
  for (let i = 0; i < rings.length; i++) {
    ctx.fillStyle = `rgba(${r},${g},${b},${(alpha * rings[i][1]).toFixed(3)})`;
    ctx.beginPath();
    ctx.arc(0, 0, rx * rings[i][0], 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

/**
 * Crisp isometric pixel-art villager/commuter/visitor v2.
 * Supports stride bounce, swinging arms, coat shading, hats/scarves,
 * umbrellas/sun parasols, shopping/Lindt gold bags, and subtle chatting cues.
 */
export function drawMiniPersonV2(ctx, x, y, s, opts = {}) {
  const p = Math.max(0.75, s);
  const canvasW = opts.canvasW != null ? opts.canvasW : 4096;
  const canvasH = opts.canvasH != null ? opts.canvasH : 4096;
  const pad = 20 * p;
  if (x < -pad || x > canvasW + pad || y < -pad || y > canvasH + pad) return;

  const isNight = !!opts.isNight;
  const coatCol = opts.coatCol || '#2b6cb0';
  const pantsCol = opts.pantsCol || '#243040';
  const hairCol = opts.hairCol || '#3a3430';
  const phase = Number.isFinite(opts.phase) ? opts.phase : (Number.isFinite(opts.stridePhase) ? opts.stridePhase : 0);
  const bagCol = opts.bagCol || opts.bag || null;
  const umbrellaCol = opts.umbrellaCol || opts.parasolCol || null;
  const hatCol = opts.hatCol || null;
  const scarfCol = opts.scarfCol || null;
  const sweatbandCol = opts.sweatbandCol || null;
  const isJogger = !!opts.isJogger;
  const isChatting = !!opts.isChatting;
  const isWaving = !!opts.isWaving;
  const facing = opts.facing != null ? (opts.facing >= 0 ? 1 : -1) : 1;

  const rx = Math.round(x);
  const ry = Math.round(y);
  const sinP = Math.sin(phase);
  const strideAmp = isJogger ? 1.15 : 0.85;
  const step = Math.round(sinP * strideAmp * p);
  const bounce = Math.round(Math.abs(sinP) * (isJogger ? 0.55 : 0.25) * p);
  const armSwing = Math.round(-sinP * (isJogger ? 0.95 : 0.65) * p);

  // Crisp isometric ground shadow ellipse
  ctx.fillStyle = isNight ? 'rgba(6,10,20,0.48)' : 'rgba(18,24,32,0.28)';
  ctx.beginPath();
  ctx.ellipse(rx, ry + 0.4 * p, Math.max(1.5, 1.7 * p), Math.max(0.8, 0.75 * p), 0, 0, Math.PI * 2);
  ctx.fill();

  // Legs (alternating stride)
  ctx.fillStyle = pantsCol;
  const legW = Math.max(1, Math.round(0.95 * p));
  const legH = Math.max(1, Math.round(2.2 * p));
  ctx.fillRect(rx - Math.round(0.85 * p) + step, ry - Math.round(2.2 * p), legW, legH);
  ctx.fillRect(rx + Math.round(0.05 * p) - step, ry - Math.round(2.2 * p), legW, legH);

  // Back arm
  const torsoTop = ry - Math.round(4.6 * p) - bounce;
  const torsoH = Math.max(2, Math.round(2.5 * p));
  const armW = Math.max(1, Math.round(0.65 * p));
  const armH = Math.max(1, Math.round(1.8 * p));
  ctx.fillStyle = coatCol;
  ctx.fillRect(rx - Math.round(1.35 * p), torsoTop + Math.round(0.3 * p) - armSwing, armW, armH);

  // Torso / coat with subtle shoulder highlight
  const torsoW = Math.max(2, Math.round(2.1 * p));
  ctx.fillStyle = coatCol;
  ctx.fillRect(rx - Math.round(1.0 * p), torsoTop, torsoW, torsoH);
  if (p >= 1.1) {
    ctx.fillStyle = isNight ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.22)';
    ctx.fillRect(rx - Math.round(0.9 * p), torsoTop, Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(0.6 * p)));
  }

  // Front arm (swinging, waving, or slightly raised while chatting)
  const waveLift = isWaving ? Math.round((1.2 + 0.5 * Math.sin(phase * 2.4)) * p) : (isChatting ? Math.round(0.6 * p) : 0);
  ctx.fillStyle = coatCol;
  ctx.fillRect(rx + Math.round(0.9 * p), torsoTop + Math.round(0.3 * p) + armSwing - waveLift, armW, armH);

  // Optional scarf
  if (scarfCol && p >= 0.95) {
    ctx.fillStyle = scarfCol;
    ctx.fillRect(rx - Math.round(0.95 * p), torsoTop - Math.round(0.15 * p), Math.max(2, Math.round(1.9 * p)), Math.max(1, Math.round(0.55 * p)));
  }

  // Optional shopping / Lindt gold bag
  if (bagCol) {
    const bx = rx + Math.round(facing * 1.1 * p);
    const by = ry - Math.round(3.1 * p) - bounce + Math.round(armSwing * 0.4);
    ctx.fillStyle = bagCol;
    ctx.fillRect(bx, by, Math.max(1, Math.round(1.15 * p)), Math.max(1, Math.round(1.55 * p)));
    if (p >= 1.2) {
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.fillRect(bx, by, Math.max(1, Math.round(0.9 * p)), Math.max(1, Math.round(0.4 * p)));
    }
  }

  // Head (subtle chat head-turn offset)
  const headTurn = isChatting ? Math.round(Math.sin(phase * 1.4) * 0.35 * p) : 0;
  const headY = ry - Math.round(5.9 * p) - bounce;
  ctx.fillStyle = isNight ? '#a88c72' : '#ecc29c';
  ctx.fillRect(rx - Math.round(0.7 * p) + headTurn, headY, Math.max(1, Math.round(1.4 * p)), Math.max(1, Math.round(1.3 * p)));

  // Hair / hat / jogger sweatband
  if (hatCol) {
    ctx.fillStyle = hatCol;
    ctx.fillRect(rx - Math.round(1.05 * p) + headTurn, headY - Math.round(0.55 * p), Math.max(2, Math.round(2.1 * p)), Math.max(1, Math.round(0.75 * p)));
    ctx.fillRect(rx - Math.round(0.7 * p) + headTurn, headY - Math.round(1.05 * p), Math.max(1, Math.round(1.4 * p)), Math.max(1, Math.round(0.6 * p)));
  } else {
    ctx.fillStyle = hairCol;
    ctx.fillRect(rx - Math.round(0.75 * p) + headTurn, headY - Math.round(0.5 * p), Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(0.75 * p)));
    if (sweatbandCol && p >= 0.95) {
      ctx.fillStyle = sweatbandCol;
      ctx.fillRect(rx - Math.round(0.75 * p) + headTurn, headY + Math.round(0.05 * p), Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(0.4 * p)));
    }
  }

  // Optional open umbrella / sun parasol
  if (umbrellaCol) {
    const ux = rx + Math.round(facing * 0.3 * p);
    const uy = headY - Math.round(1.7 * p);
    ctx.strokeStyle = isNight ? '#64748b' : '#334155';
    ctx.lineWidth = Math.max(0.7, 0.55 * p);
    ctx.beginPath();
    ctx.moveTo(rx + Math.round(facing * 0.8 * p), torsoTop + Math.round(0.5 * p));
    ctx.lineTo(ux, uy);
    ctx.stroke();

    ctx.fillStyle = umbrellaCol;
    ctx.beginPath();
    ctx.ellipse(ux, uy, Math.max(2.2, 2.6 * p), Math.max(1.2, 1.35 * p), 0, Math.PI, 0);
    ctx.closePath();
    ctx.fill();
    if (p >= 1.1) {
      ctx.fillStyle = 'rgba(255,255,255,0.28)';
      ctx.fillRect(Math.round(ux - 1.1 * p), Math.round(uy - 1.0 * p), Math.max(1, Math.round(1.2 * p)), Math.max(1, Math.round(0.5 * p)));
    }
  }
}

/**
 * Backwards-compatible alias matching legacy drawMiniPerson(...) parameter list.
 */
export function drawMiniPerson(
  targetCtx,
  sx,
  sy,
  s,
  coatCol,
  pantsCol,
  hairCol,
  isNight,
  stridePhase,
  bagCol = null,
  canvasW = 4096,
  canvasH = 4096,
) {
  drawMiniPersonV2(targetCtx, sx, sy, s, {
    coatCol,
    pantsCol,
    hairCol,
    isNight,
    phase: stridePhase,
    bagCol,
    canvasW,
    canvasH,
  });
}

export function getZurichClockTime(tSec, mode = 'day') {
  const baseSec = mode === 'night'
    ? (22 * 3600 + 15 * 60)
    : (mode === 'sunset' ? (19 * 3600 + 42 * 60) : (14 * 3600 + 22 * 60));
  const totalSec = (((baseSec + tSec) % 86400) + 86400) % 86400;
  const hr = Math.floor(totalSec / 3600) % 24;
  const min = Math.floor((totalSec % 3600) / 60);
  const sec = totalSec % 60;
  return { hr, min, sec };
}

/**
 * Authentic Swiss clock dial (SBB Mondaine red-lollipop, church, or civic).
 * Pure vector hands and baton ticks (no text rendering).
 */
export function drawSwissClockDial(ctx, cx, cy, r, tSec, opts = {}) {
  if (r < 1.6) return;
  const mode = opts.mode || 'day';
  const style = opts.style || 'sbb';
  const s = opts.s != null ? opts.s : (r / 2.6);
  const detailAlpha = opts.detailAlpha != null ? opts.detailAlpha : 1.0;
  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';
  const { hr, min, sec } = getZurichClockTime(tSec, mode);
  const minAng = ((min + sec / 60) / 60) * Math.PI * 2 - Math.PI * 0.5;
  const hrAng = (((hr % 12) + min / 60) / 12) * Math.PI * 2 - Math.PI * 0.5;

  ctx.save();
  if (style === 'sbb') {
    const sbbSec = sec < 58.5 ? (sec / 58.5) * 60 : 0;
    const sAng = (sbbSec / 60) * Math.PI * 2 - Math.PI * 0.5;
    if (isNight || isSunset) {
      blitGlow(ctx, cx, cy, r * 2.1, 'white', isNight ? 0.34 : 0.18);
    }
    ctx.fillStyle = '#f8fafc';
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = Math.max(0.75, 0.65 * s);
    ctx.stroke();

    if (detailAlpha > 0.05 && r >= 3.0) {
      ctx.strokeStyle = '#0f172a';
      ctx.lineCap = 'butt';
      for (let ti = 0; ti < 12; ti++) {
        const ta = (ti / 12) * Math.PI * 2 - Math.PI * 0.5;
        const major = (ti % 3) === 0;
        ctx.lineWidth = Math.max(0.65, (major ? 0.65 : 0.35) * s);
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(ta) * r * (major ? 0.66 : 0.76), cy + Math.sin(ta) * r * (major ? 0.66 : 0.76));
        ctx.lineTo(cx + Math.cos(ta) * r * 0.90, cy + Math.sin(ta) * r * 0.90);
        ctx.stroke();
      }
    }
    ctx.strokeStyle = '#0f172a';
    ctx.lineCap = 'butt';
    ctx.lineWidth = Math.max(1.0, 0.95 * s);
    ctx.beginPath();
    ctx.moveTo(cx - Math.cos(hrAng) * r * 0.14, cy - Math.sin(hrAng) * r * 0.14);
    ctx.lineTo(cx + Math.cos(hrAng) * r * 0.54, cy + Math.sin(hrAng) * r * 0.54);
    ctx.stroke();
    ctx.lineWidth = Math.max(0.85, 0.72 * s);
    ctx.beginPath();
    ctx.moveTo(cx - Math.cos(minAng) * r * 0.16, cy - Math.sin(minAng) * r * 0.16);
    ctx.lineTo(cx + Math.cos(minAng) * r * 0.80, cy + Math.sin(minAng) * r * 0.80);
    ctx.stroke();

    const lx = cx + Math.cos(sAng) * r * 0.68;
    const ly = cy + Math.sin(sAng) * r * 0.68;
    ctx.strokeStyle = '#dc2626';
    ctx.lineWidth = Math.max(0.6, 0.45 * s);
    ctx.beginPath();
    ctx.moveTo(cx - Math.cos(sAng) * r * 0.20, cy - Math.sin(sAng) * r * 0.20);
    ctx.lineTo(lx, ly);
    ctx.stroke();
    ctx.fillStyle = '#dc2626';
    ctx.beginPath();
    ctx.arc(lx, ly, Math.max(0.95, r * 0.14), 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    return;
  }

  const isChurch = style === 'church';
  ctx.fillStyle = isChurch ? (isNight ? '#262b34' : '#2a2e34') : (isNight ? '#1d273b' : '#1a202e');
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = isChurch ? '#8a7846' : (isNight ? '#ffe38a' : '#eec44c');
  ctx.lineWidth = Math.max(0.75, (isChurch ? 0.65 : 0.75) * s);
  ctx.stroke();

  if (detailAlpha > 0.05 && r >= 3.0) {
    ctx.strokeStyle = isNight ? 'rgba(255, 227, 138, 0.88)' : 'rgba(238, 196, 68, 0.90)';
    ctx.lineWidth = Math.max(0.6, 0.42 * s);
    for (let ti = 0; ti < 12; ti++) {
      const ta = (ti / 12) * Math.PI * 2 - Math.PI * 0.5;
      const inner = (ti % 3) === 0 ? 0.68 : 0.76;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(ta) * r * inner, cy + Math.sin(ta) * r * inner);
      ctx.lineTo(cx + Math.cos(ta) * r * 0.90, cy + Math.sin(ta) * r * 0.90);
      ctx.stroke();
    }
  }
  ctx.strokeStyle = isNight ? '#ffe38a' : '#f6ce4c';
  ctx.lineCap = 'round';
  ctx.lineWidth = Math.max(1.1, (isChurch ? 1.35 : 0.95) * s);
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + Math.cos(hrAng) * r * 0.56, cy + Math.sin(hrAng) * r * 0.56);
  ctx.stroke();
  ctx.lineWidth = Math.max(0.9, (isChurch ? 1.05 : 0.75) * s);
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + Math.cos(minAng) * r * 0.84, cy + Math.sin(minAng) * r * 0.84);
  ctx.stroke();
  ctx.fillStyle = '#fff5cc';
  const hSz = Math.max(1.4, Math.round(r * 0.22));
  ctx.fillRect(Math.round(cx - hSz * 0.5), Math.round(cy - hSz * 0.5), hSz, hSz);
  ctx.restore();
}

/**
 * Authentic Swiss white cross on red OR Kilchberg (ZH) municipal Wappen
 * (4-petal white flower with golden center kGold on azure), wind-synced ripple.
 */
export function drawSwissOrMuniFlag(ctx, x, y, s, tSec, wind, kind = 'swiss', opts = {}) {
  const isNight = !!opts.isNight;
  const phaseIdx = opts.phaseIdx || 0;
  const wavePhase = (wind && Number.isFinite(wind.wavePhase)) ? wind.wavePhase : (tSec * 5.0);
  const strength = (wind && Number.isFinite(wind.strength)) ? wind.strength : 0.72;
  const waveStep = Math.floor(wavePhase) % 4;
  const billow = Math.min(1.0, Math.max(0.65, strength * 1.1));
  const fPhase = (waveStep + phaseIdx) % 4;
  const dy1 = (fPhase === 1 ? -0.6 : (fPhase === 3 ? 0.6 : 0)) * billow * s;
  const dy2 = (fPhase === 2 ? -0.7 : (fPhase === 0 ? 0.7 : 0)) * billow * s;
  const poleCol = isNight ? '#8a99b2' : '#d8dce2';
  const finialCol = isNight ? '#c8a852' : '#f2ca52';
  const whiteCross = isNight ? '#cfd6e2' : '#f8f6f0';

  const rect = (rx, ry, rw, rh, col) => {
    ctx.fillStyle = col;
    ctx.fillRect(Math.round(rx), Math.round(ry), Math.max(1, Math.round(rw)), Math.max(1, Math.round(rh)));
  };

  if (kind === 'kilchberg') {
    rect(x, y - 14.5 * s, 1.4 * s, 15.5 * s, poleCol);
    rect(x - 0.3 * s, y - 15.5 * s, 2.0 * s, 1.3 * s, finialCol);
    const kAzure = isNight ? '#12427e' : '#1a5fb4';
    const kPetal = isNight ? '#cfd6e2' : '#f8fafc';
    const kPetalShade = isNight ? '#94a3b8' : '#cbd5e1';
    const kGold = isNight ? '#c49d28' : '#f2c430';
    const kGoldEdge = isNight ? '#854d0e' : '#b45309';

    const segY0 = y - 14.5 * s;
    rect(x + 1.4 * s, segY0, 2.8 * s, 7.2 * s, kAzure);
    rect(x + 4.1 * s, segY0 + dy1, 3.0 * s, 7.2 * s, kAzure);
    rect(x + 7.0 * s, segY0 + dy2, 2.6 * s, 7.2 * s, kAzure);

    const cx = x + 5.5 * s;
    const cy = segY0 + 3.6 * s + dy1;
    const petalDist = 1.65 * s;
    const petalR = 1.25 * s;
    ctx.save();
    ctx.fillStyle = kPetal;
    ctx.strokeStyle = kPetalShade;
    ctx.lineWidth = Math.max(0.6, 0.35 * s);
    const dirs = [[0, -1], [1, 0], [0, 1], [-1, 0]];
    for (let i = 0; i < 4; i++) {
      ctx.beginPath();
      ctx.arc(cx + dirs[i][0] * petalDist, cy + dirs[i][1] * petalDist, petalR, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = kGold;
    ctx.beginPath();
    ctx.arc(cx, cy, Math.max(1.0, 0.95 * s), 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = kGoldEdge;
    ctx.lineWidth = Math.max(0.5, 0.25 * s);
    ctx.stroke();
    ctx.restore();
    return;
  }

  rect(x, y - 15 * s, 1.5 * s, 16 * s, poleCol);
  rect(x - 0.3 * s, y - 16 * s, 2.1 * s, 1.6 * s, finialCol);
  const segY0 = y - 14.5 * s;
  const redFlag = isNight ? '#9e2828' : '#d62c28';
  rect(x + 1.5 * s, segY0, 3.0 * s, 6.0 * s, redFlag);
  rect(x + 4.2 * s, segY0 + dy1, 3.2 * s, 6.0 * s, redFlag);
  rect(x + 7.2 * s, segY0 + dy2, 2.8 * s, 6.0 * s, redFlag);
  rect(x + 4.6 * s, segY0 + dy1 + 1.2 * s, 1.4 * s, 3.6 * s, whiteCross);
  rect(x + 3.4 * s, segY0 + dy1 + 2.3 * s, 3.8 * s, 1.4 * s, whiteCross);
}

/**
 * Reusable expanding concentric isometric water-lap ripples.
 */
export function drawWaterRipples(ctx, x, y, s, tSec, opts = {}) {
  const count = opts.count != null ? opts.count : 2;
  const speed = opts.speed != null ? opts.speed : 0.42;
  const phaseOff = opts.phaseOff || 0;
  const minR = (opts.minR != null ? opts.minR : 1.8) * s;
  const maxR = (opts.maxR != null ? opts.maxR : 6.5) * s;
  const isNight = !!opts.isNight;
  const isSunset = !!opts.isSunset;
  const colRgb = opts.colRgb || (isNight ? '156, 206, 238' : (isSunset ? '255, 224, 182' : '232, 248, 255'));
  const baseAlpha = opts.alpha != null ? opts.alpha : (isNight ? 0.34 : 0.46);

  ctx.save();
  ctx.lineWidth = Math.max(0.75, 0.85 * s);
  for (let i = 0; i < count; i++) {
    const prog = (((tSec * speed + phaseOff + i / count) % 1) + 1) % 1;
    const rx = minR + prog * maxR;
    const ry = rx * 0.52;
    const a = (1.0 - prog) * baseAlpha;
    if (a <= 0.03) continue;
    ctx.strokeStyle = `rgba(${colRgb}, ${a.toFixed(2)})`;
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

/**
 * Reusable pixel-art water splash plume (diving, duck dip, paddle impact).
 */
export function drawSplashPlume(ctx, x, y, s, progress, opts = {}) {
  if (progress <= 0 || progress >= 1) return;
  const isNight = !!opts.isNight;
  const isSunset = !!opts.isSunset;
  const scaleMul = opts.scaleMul != null ? opts.scaleMul : 1.0;
  const p = Math.max(0.85, s * scaleMul);
  const fade = 1.0 - progress;
  const colRgb = isNight ? '186, 220, 255' : (isSunset ? '255, 236, 208' : '244, 253, 255');

  ctx.save();
  // Expanding impact ring
  const rx = (1.6 + progress * 6.8) * p;
  ctx.strokeStyle = `rgba(${colRgb}, ${(fade * 0.72).toFixed(2)})`;
  ctx.lineWidth = Math.max(0.8, 1.0 * p);
  ctx.beginPath();
  ctx.ellipse(x, y, rx, rx * 0.52, 0, 0, Math.PI * 2);
  ctx.stroke();

  // Rising/falling pixel droplets
  const drops = opts.drops || 5;
  ctx.fillStyle = `rgba(${colRgb}, ${(fade * 0.88).toFixed(2)})`;
  for (let i = 0; i < drops; i++) {
    const spread = (i - (drops - 1) * 0.5) / Math.max(1, (drops - 1) * 0.5);
    const dx = spread * (1.2 + progress * 4.2) * p;
    const arcH = Math.sin(progress * Math.PI) * (3.8 + (1 - Math.abs(spread)) * 2.6) * p;
    const dSz = Math.max(1, Math.round((1.4 - progress * 0.6) * p));
    ctx.fillRect(Math.round(x + dx - dSz * 0.5), Math.round(y - arcH - dSz * 0.5), dSz, dSz);
  }
  ctx.restore();
}

/**
 * Reusable wind-synced pixel-art steam/smoke curls.
 */
export function drawSmokePuffs(ctx, x, y, s, tSec, wind, opts = {}) {
  const count = opts.count != null ? opts.count : 5;
  const rate = opts.rate != null ? opts.rate : 0.28;
  const phaseOff = opts.phaseOff || 0;
  const driftScale = (opts.drift != null ? opts.drift : 18) * s;
  const riseScale = (opts.rise != null ? opts.rise : 22) * s;
  const baseSz = (opts.baseSz != null ? opts.baseSz : 1.8) * s;
  const growSz = (opts.growSz != null ? opts.growSz : 3.6) * s;
  const isNight = !!opts.isNight;
  const isSunset = !!opts.isSunset;
  const alphaMul = opts.alpha != null ? opts.alpha : (isNight ? 0.44 : 0.62);
  const wx = wind ? wind.wx : 0.96;
  const wy = wind ? wind.wy : -0.28;

  const colRgb = opts.colRgb || (isNight ? '168, 186, 216' : (isSunset ? '255, 224, 198' : '244, 248, 252'));
  for (let p = 0; p < count; p++) {
    const age = (((tSec * rate + phaseOff + p / count) % 1) + 1) % 1;
    const px = x + age * driftScale * wx + Math.sin(age * 5.8 + p * 1.7) * 1.6 * s;
    const py = y - (1.5 * s + age * riseScale) + age * riseScale * 0.22 * wy;
    const a = (1 - age) * (age < 0.16 ? age / 0.16 : 1.0) * alphaMul;
    if (a <= 0.02) continue;
    const sz = baseSz + age * growSz;
    ctx.fillStyle = `rgba(${colRgb}, ${a.toFixed(2)})`;
    ctx.fillRect(
      Math.round(px - sz * 0.5),
      Math.round(py - sz * 0.36),
      Math.max(1, Math.round(sz)),
      Math.max(1, Math.round(sz * 0.72)),
    );
  }
}
