/**
 * Procedural 3D isometric vehicle, bus, SBB train, cyclist, and Lake Zurich vessel renderers.
 * Upgraded with dynamic brake lights (with CHMSL & asphalt glow), deterministic 1.4 Hz amber
 * turn/hazard blinkers, Alpenglow/Night headlight cones with queue dimming, and crisp daytime
 * bus ground contact shadow & tinted ZVV glazing.
 */

import { samplePathAt } from '../sim/schedule.js';

const spriteCache = {};

function createPixelBuffer(w, h) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const cctx = c.getContext('2d');
  const img = cctx.createImageData(w, h);
  return { c, cctx, img, data: img.data, w, h };
}

function setPx(buf, x, y, rgb, a = 255) {
  const ix = x | 0;
  const iy = y | 0;
  if (ix < 0 || ix >= buf.w || iy < 0 || iy >= buf.h) return;
  const o = (iy * buf.w + ix) * 4;
  buf.data[o] = rgb[0];
  buf.data[o + 1] = rgb[1];
  buf.data[o + 2] = rgb[2];
  buf.data[o + 3] = a;
}

function fillPolyPx(buf, pts, rgb, a = 255) {
  let minY = buf.h;
  let maxY = -1;
  for (let i = 0; i < pts.length; i++) {
    if (pts[i][1] < minY) minY = pts[i][1];
    if (pts[i][1] > maxY) maxY = pts[i][1];
  }
  const y0 = Math.max(0, Math.floor(minY));
  const y1 = Math.min(buf.h - 1, Math.ceil(maxY));
  const xs = [];
  for (let y = y0; y <= y1; y++) {
    const py = y + 0.5;
    xs.length = 0;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const x1 = pts[j][0];
      const y1p = pts[j][1];
      const x2 = pts[i][0];
      const y2p = pts[i][1];
      if ((y1p <= py && y2p > py) || (y2p <= py && y1p > py)) {
        xs.push(x1 + ((py - y1p) * (x2 - x1)) / (y2p - y1p));
      }
    }
    xs.sort((aVal, bVal) => aVal - bVal);
    for (let k = 0; k + 1 < xs.length; k += 2) {
      const xStart = Math.max(0, Math.floor(xs[k] + 0.5));
      const xEnd = Math.min(buf.w - 1, Math.floor(xs[k + 1] - 0.5));
      for (let x = xStart; x <= xEnd; x++) {
        setPx(buf, x, y, rgb, a);
      }
    }
  }
}

function applySelOutAndShade(buf, mode) {
  const mult = mode === 'night' ? [0.46, 0.54, 0.74] : (mode === 'sunset' ? [1.04, 0.86, 0.74] : [1.0, 1.0, 1.0]);
  const w = buf.w;
  const h = buf.h;
  const d = buf.data;
  const solid = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const o = i * 4;
    if (d[o + 3] === 255) {
      solid[i] = 1;
      d[o] = Math.min(255, Math.round(d[o] * mult[0]));
      d[o + 1] = Math.min(255, Math.round(d[o + 1] * mult[1]));
      d[o + 2] = Math.min(255, Math.round(d[o + 2] * mult[2]));
    } else if (d[o + 3] === 254) {
      solid[i] = 1;
      d[o + 3] = 255;
    }
  }
  const outCol = mode === 'night' ? [14, 18, 28] : [28, 32, 40];
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const idx = y * w + x;
      if (solid[idx] || d[idx * 4 + 3] > 0) continue;
      if (solid[idx - 1] || solid[idx + 1] || solid[idx - w] || solid[idx + w]) {
        setPx(buf, x, y, outCol, 225);
      }
    }
  }
  buf.cctx.putImageData(buf.img, 0, 0);
}

function makeIsoBasis(cx, cy, tx, ty) {
  const gx = tx;
  const gy = ty * 2.0;
  const gLen = Math.hypot(gx, gy) || 1;
  const ux = gx / gLen;
  const uy = gy / gLen;
  const fx = ux;
  const fy = uy * 0.5;
  const rx = -uy;
  const ry = ux * 0.5;
  const pt = (s, w, z) => [
    cx + fx * s + rx * w,
    cy + fy * s + ry * w - z * 0.866,
  ];
  return {
    fx, fy, rx, ry, pt,
    visSide: ry >= 0 ? 1 : -1,
    visEnd: fy >= 0 ? 1 : -1,
  };
}

function drawIsoBox(buf, cx, cy, tx, ty, halfLen, halfWid, heightPx, zBase, colors, drawShadow = true, basisOverride = null) {
  const B = basisOverride || makeIsoBasis(cx, cy, tx, ty);
  const { pt, visSide, visEnd } = B;

  if (drawShadow) {
    fillPolyPx(buf, [
      pt(-halfLen - 1.2, -halfWid - 1.2, -0.5),
      pt(halfLen + 1.2, -halfWid - 1.2, -0.5),
      pt(halfLen + 1.2, halfWid + 1.2, -0.5),
      pt(-halfLen - 1.2, halfWid + 1.2, -0.5),
    ], [14, 18, 26], 115);
  }

  const z0 = zBase;
  const z1 = zBase + heightPx;
  const alpha = colors.emissive ? 254 : 255;

  fillPolyPx(buf, [
    pt(-halfLen, visSide * halfWid, z0),
    pt(halfLen, visSide * halfWid, z0),
    pt(halfLen, visSide * halfWid, z1),
    pt(-halfLen, visSide * halfWid, z1),
  ], colors.side, alpha);

  fillPolyPx(buf, [
    pt(visEnd * halfLen, -halfWid, z0),
    pt(visEnd * halfLen, halfWid, z0),
    pt(visEnd * halfLen, halfWid, z1),
    pt(visEnd * halfLen, -halfWid, z1),
  ], colors.front, alpha);

  fillPolyPx(buf, [
    pt(-halfLen, -halfWid, z1),
    pt(halfLen, -halfWid, z1),
    pt(halfLen, halfWid, z1),
    pt(-halfLen, halfWid, z1),
  ], colors.roof, alpha);

  return B;
}

export function getVehicleSprite(type, variant, angleIdx, mode, angleSteps = 32) {
  const key = `${type}:${variant}:${angleIdx}:${angleSteps}:${mode}`;
  if (spriteCache[key]) return spriteCache[key];

  const ang = (angleIdx / angleSteps) * Math.PI * 2;
  const tx = Math.cos(ang);
  const ty = Math.sin(ang);
  const isNight = mode === 'night';
  const winCol = isNight ? [255, 220, 126] : [42, 58, 82];
  const winAlpha = isNight ? 254 : 255;

  let buf;
  if (type === 'zsg_steamer') {
    buf = createPixelBuffer(210, 160);
    const cx = 105;
    const cy = 88;
    const nx = -ty * 0.72;
    const ny = tx * 0.52;
    const pt = (s, w, z) => [cx + tx * s + nx * w, cy + ty * s + ny * w - z];

    fillPolyPx(buf, [
      pt(-68, -12, 0), pt(44, -13, 0), pt(74, 0, 0), pt(44, 13, 0), pt(-68, 12, 0),
    ], [36, 58, 54], 255);
    fillPolyPx(buf, [
      pt(-66, -11.5, 4.5), pt(44, -12.5, 4.5), pt(73, 0, 5.5), pt(44, 12.5, 4.5), pt(-66, 11.5, 4.5),
    ], [186, 150, 104], 255);

    const salon1Basis = makeIsoBasis(cx - tx * 6, cy - ty * 6, tx, ty);
    const drawSponson = (sideDir) => {
      const spCx = cx + tx * 2 + salon1Basis.rx * sideDir * 10.6;
      const spCy = cy + ty * 2 + salon1Basis.ry * sideDir * 10.6;
      const spB = drawIsoBox(buf, spCx, spCy, tx, ty, 7.6, 2.2, 6.7, 4.5, {
        roof: [238, 234, 226], side: [224, 220, 212], front: [230, 226, 218],
      }, false);
      if (sideDir === salon1Basis.visSide) {
        const sv = spB.visSide * 2.28;
        fillPolyPx(buf, [
          spB.pt(-5.8, sv, 4.7), spB.pt(5.8, sv, 4.7),
          spB.pt(4.0, sv, 8.9), spB.pt(0.0, sv, 9.8), spB.pt(-4.0, sv, 8.9),
        ], [42, 56, 66], 255);
        fillPolyPx(buf, [
          spB.pt(-6.8, sv, 9.8), spB.pt(6.8, sv, 9.8),
          spB.pt(6.8, sv, 10.9), spB.pt(-6.8, sv, 10.9),
        ], [226, 198, 134], 255);
      }
    };

    drawSponson(-salon1Basis.visSide);

    const salon1 = drawIsoBox(buf, cx - tx * 6, cy - ty * 6, tx, ty, 46.0, 10.2, 8.0, 4.5, {
      roof: [232, 230, 224], side: [216, 214, 208], front: [224, 222, 216],
    }, false, salon1Basis);
    drawSponson(salon1Basis.visSide);

    const salon2 = drawIsoBox(buf, cx - tx * 4, cy - ty * 4, tx, ty, 32.0, 8.4, 7.0, 12.5, {
      roof: [240, 238, 232], side: [222, 220, 214], front: [228, 226, 220],
    }, false);
    drawIsoBox(buf, cx + tx * 20, cy + ty * 20, tx, ty, 7.0, 6.5, 5.5, 19.5, {
      roof: [238, 236, 230], side: [62, 84, 108], front: [62, 84, 108],
    }, false);
    drawIsoBox(buf, cx + tx * 2, cy + ty * 2, tx, ty, 4.2, 3.6, 9.0, 19.5, {
      roof: [52, 54, 58], side: [226, 198, 134], front: [234, 208, 146],
    }, false);

    for (let s = -44; s <= 32; s += 6.5) {
      fillPolyPx(buf, [
        salon1.pt(s - 2.0, salon1.visSide * 10.4, 6.5),
        salon1.pt(s + 2.0, salon1.visSide * 10.4, 6.5),
        salon1.pt(s + 2.0, salon1.visSide * 10.4, 10.8),
        salon1.pt(s - 2.0, salon1.visSide * 10.4, 10.8),
      ], winCol, winAlpha);
    }
    for (let s = -30; s <= 20; s += 6.5) {
      fillPolyPx(buf, [
        salon2.pt(s - 2.0, salon2.visSide * 8.6, 14.2),
        salon2.pt(s + 2.0, salon2.visSide * 8.6, 14.2),
        salon2.pt(s + 2.0, salon2.visSide * 8.6, 17.8),
        salon2.pt(s - 2.0, salon2.visSide * 8.6, 17.8),
      ], winCol, winAlpha);
    }
    const st = pt(-67, 0, 11);
    fillPolyPx(buf, [
      [st[0] - 5, st[1] - 6], [st[0] + 1, st[1] - 6],
      [st[0] + 1, st[1] - 1], [st[0] - 5, st[1] - 1],
    ], [212, 42, 38], 254);
    setPx(buf, st[0] - 2, st[1] - 4, [250, 248, 244], 254);
    setPx(buf, st[0] - 3, st[1] - 4, [250, 248, 244], 254);
    setPx(buf, st[0] - 1, st[1] - 4, [250, 248, 244], 254);
    setPx(buf, st[0] - 2, st[1] - 5, [250, 248, 244], 254);
    setPx(buf, st[0] - 2, st[1] - 3, [250, 248, 244], 254);

    applySelOutAndShade(buf, mode);
    spriteCache[key] = { canvas: buf.c, cx, cy };
    return spriteCache[key];
  }

  if (type === 'sailboat') {
    buf = createPixelBuffer(64, 72);
    const cx = 32;
    const cy = 52;
    const nx = -ty * 0.72;
    const ny = tx * 0.52;
    const pt = (s, w, z) => [cx + tx * s + nx * w, cy + ty * s + ny * w - z];
    fillPolyPx(buf, [
      pt(-13, -4.2, 0), pt(8, -4.2, 0), pt(16, 0, 1.5), pt(8, 4.2, 0), pt(-13, 4.2, 0),
    ], [230, 228, 222], 255);
    fillPolyPx(buf, [
      pt(2, 0, 4), pt(-11, 2.2, 5), pt(1, 0, 36),
    ], [244, 242, 236], 255);
    fillPolyPx(buf, [
      pt(3, 0, 5), pt(14, -1.5, 4), pt(1, 0, 32),
    ], [222, 226, 232], 255);
    applySelOutAndShade(buf, mode);
    spriteCache[key] = { canvas: buf.c, cx, cy };
    return spriteCache[key];
  }

  // Boesch classic Kilchberg mahogany runabout
  buf = createPixelBuffer(48, 42);
  const cx = 24;
  const cy = 24;
  const nx = -ty * 0.72;
  const ny = tx * 0.52;
  const pt = (s, w, z) => [cx + tx * s + nx * w, cy + ty * s + ny * w - z];
  fillPolyPx(buf, [
    pt(-12, -4.5, 0), pt(7, -4.5, 0), pt(15, 0, 1.5), pt(7, 4.5, 0), pt(-12, 4.5, 0),
  ], [148, 78, 46], 255);
  fillPolyPx(buf, [
    pt(-3, -3.4, 2.0), pt(4, -3.4, 2.0), pt(4, 3.4, 2.0), pt(-3, 3.4, 2.0),
  ], [198, 212, 226], 255);
  applySelOutAndShade(buf, mode);
  spriteCache[key] = { canvas: buf.c, cx, cy };
  return spriteCache[key];
}

export function blitWorldSprite(targetCtx, cam, sp, wx, wy, wScale) {
  const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
  const drawScale = scale * wScale;
  const sx = Math.round(offsetX + (wx - sp.cx * wScale) * scale);
  const sy = Math.round(offsetY + (wy - sp.cy * wScale) * scale);
  const sw = Math.max(2, Math.round(sp.canvas.width * drawScale));
  const sh = Math.max(2, Math.round(sp.canvas.height * drawScale));
  if (sx + sw < -20 || sx > canvasW + 20 || sy + sh < -20 || sy > canvasH + 20) return;
  targetCtx.imageSmoothingEnabled = drawScale < 0.65;
  targetCtx.drawImage(sp.canvas, sx, sy, sw, sh);
}

export function drawPixelRectWorld(targetCtx, cam, wx, wy, pw, ph, fillStyle, wScale) {
  const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
  const sx = Math.round(offsetX + wx * scale);
  const sy = Math.round(offsetY + wy * scale);
  if (sx < -20 || sx > canvasW + 20 || sy < -20 || sy > canvasH + 20) return;
  const sw = Math.max(1, Math.round(pw * wScale * scale));
  const sh = Math.max(1, Math.round(ph * wScale * scale));
  targetCtx.fillStyle = fillStyle;
  targetCtx.fillRect(sx, sy, sw, sh);
}

export function shadeHex(hex, factor, mode) {
  let r = parseInt(hex.slice(1, 3), 16);
  let g = parseInt(hex.slice(3, 5), 16);
  let b = parseInt(hex.slice(5, 7), 16);
  if (mode === 'sunset') {
    r = Math.min(255, r * 1.12 + 10);
    g = Math.min(255, g * 0.94 + 4);
    b = Math.max(0, b * 0.80);
  } else if (mode === 'night') {
    r = r * 0.44 + 8;
    g = g * 0.50 + 12;
    b = Math.min(255, b * 0.72 + 24);
  }
  r = Math.max(0, Math.min(255, Math.round(r * factor)));
  g = Math.max(0, Math.min(255, Math.round(g * factor)));
  b = Math.max(0, Math.min(255, Math.round(b * factor)));
  return `rgb(${r},${g},${b})`;
}

export function makeScreenIsoBasis(cam, wx, wy, tx, ty, wScale) {
  const { scale, offsetX, offsetY } = cam;
  const s = scale * wScale;
  const cx = offsetX + wx * scale;
  const cy = offsetY + wy * scale;
  const isoScaleY = 0.55;
  const gx = tx;
  const gy = ty / isoScaleY;
  const gMag = Math.hypot(gx, gy) || 1;
  const rx = -gy / gMag;
  const ry = (gx / gMag) * isoScaleY;
  const proj = (l, w, z) => [
    cx + (l * tx + w * rx) * s,
    cy + (l * ty + w * ry - z * 0.84) * s,
  ];
  const dirShade = (nl, nw) => {
    const nx = nl * tx + nw * rx;
    const ny = nl * ty + nw * ry;
    const nm = Math.hypot(nx, ny) || 1;
    const dot = (nx / nm) * (-0.72) + (ny / nm) * (-0.69);
    return 0.78 + Math.max(-1, Math.min(1, dot)) * 0.26;
  };
  return { cx, cy, s, tx, ty, rx, ry, proj, dirShade };
}

export function makeTwoPointIsoBasis(cam, pRear, pFront, hl, wScale) {
  const { scale, offsetX, offsetY } = cam;
  const s = scale * wScale;
  const fx = offsetX + pFront.wx * scale;
  const fy = offsetY + pFront.wy * scale;
  const rx0 = offsetX + pRear.wx * scale;
  const ry0 = offsetY + pRear.wy * scale;
  const cx = (fx + rx0) * 0.5;
  const cy = (fy + ry0) * 0.5;
  const dx = fx - rx0;
  const dy = fy - ry0;
  const mag = Math.hypot(dx, dy) || 1;
  const tx = dx / mag;
  const ty = dy / mag;
  const isoScaleY = 0.55;
  const gx = tx;
  const gy = ty / isoScaleY;
  const gMag = Math.hypot(gx, gy) || 1;
  const rx = -gy / gMag;
  const ry = (gx / gMag) * isoScaleY;
  const inv2hl = 1 / (2 * hl);
  const proj = (l, w, z) => {
    const u = (l + hl) * inv2hl;
    return [
      rx0 + u * dx + w * rx * s,
      ry0 + u * dy + (w * ry - z * 0.84) * s,
    ];
  };
  const dirShade = (nl, nw) => {
    const nx = nl * tx + nw * rx;
    const ny = nl * ty + nw * ry;
    const nm = Math.hypot(nx, ny) || 1;
    const dot = (nx / nm) * (-0.72) + (ny / nm) * (-0.69);
    return 0.78 + Math.max(-1, Math.min(1, dot)) * 0.26;
  };
  return { cx, cy, s, tx, ty, rx, ry, proj, dirShade };
}

export function fillPoly(targetCtx, pts, fill, stroke = null, lw = 1) {
  targetCtx.beginPath();
  targetCtx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) targetCtx.lineTo(pts[i][0], pts[i][1]);
  targetCtx.closePath();
  targetCtx.fillStyle = fill;
  targetCtx.fill();
  if (stroke) {
    targetCtx.strokeStyle = stroke;
    targetCtx.lineWidth = lw;
    targetCtx.stroke();
  }
}

function drawAmberDot(targetCtx, pt, sz, isSunsetOrNight) {
  if (isSunsetOrNight) {
    targetCtx.save();
    targetCtx.fillStyle = 'rgba(255, 170, 0, 0.28)';
    targetCtx.beginPath();
    targetCtx.arc(pt[0], pt[1], Math.max(2.0, sz * 1.45), 0, Math.PI * 2);
    targetCtx.fill();
    targetCtx.restore();
  }
  targetCtx.fillStyle = '#ffaa00';
  targetCtx.fillRect(pt[0] - sz * 0.5, pt[1] - sz * 0.5, sz, sz);
}

export function draw3DCar(targetCtx, cam, pos, colorIdx, wScale, mode, tSec = 0, signals = null) {
  const b = makeScreenIsoBasis(cam, pos.wx, pos.wy, pos.tx, pos.ty, wScale);
  if (b.cx < -56 || b.cx > cam.width + 56 || b.cy < -56 || b.cy > cam.height + 56) return;

  const isEmergency = (colorIdx % 29 === 17);
  const isAmbulance = isEmergency && (Math.floor(colorIdx / 29) % 2 === 1);
  const isPostVan = !isEmergency && (colorIdx % 11 === 4);
  const isLindtVan = !isEmergency && !isPostVan && (colorIdx % 13 === 7);
  const isMigrosVan = !isEmergency && !isPostVan && !isLindtVan && (colorIdx % 17 === 9);
  const isCoopVan = !isEmergency && !isPostVan && !isLindtVan && !isMigrosVan && (colorIdx % 19 === 11);
  const isCamper = !isEmergency && !isPostVan && !isLindtVan && !isMigrosVan && !isCoopVan && (colorIdx % 15 === 3);
  const isVan = isEmergency || isPostVan || isLindtVan || isMigrosVan || isCoopVan || isCamper;
  const carSub = colorIdx % 3;
  const isEstate = !isVan && carSub === 0;
  const isHatch = !isVan && carSub === 1;

  const palette = ['#c92c28', '#f2f5f8', '#254d82', '#d4a548', '#2b6b4c', '#c6cfd9', '#3b4350', '#54708c'];
  let baseHex = palette[colorIdx % palette.length];
  if (isEmergency) baseHex = isAmbulance ? '#f6d026' : '#d91e18';
  else if (isPostVan) baseHex = '#f6c216';
  else if (isLindtVan) baseHex = '#f7f3e6';
  else if (isMigrosVan || isCoopVan) baseHex = '#f4f6f9';
  else if (isCamper) baseHex = (colorIdx % 2 === 0) ? '#2c7a7b' : '#2b6cb0';

  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';

  const hl = isLindtVan ? 10.8 : (isEmergency ? 10.4 : (isCamper ? 10.2 : (isVan ? 10.6 : (isEstate ? 9.6 : (isHatch ? 8.2 : 9.2)))));
  const hw = isLindtVan ? 4.6 : (isCamper ? 4.4 : (isVan ? 4.5 : (isHatch ? 4.0 : 4.2)));
  const zBot = 1.2;
  const zBelt = isCamper ? 4.7 : (isEmergency ? 4.8 : (isVan ? 5.0 : (isEstate ? 4.3 : (isHatch ? 4.2 : 4.4))));
  const zRoof = isLindtVan ? 9.4 : (isEmergency ? 8.8 : (isCamper ? 8.4 : (isVan ? 9.2 : (isHatch ? 7.1 : 7.2))));

  const shOff = [2.6 * b.s, 2.0 * b.s];
  const shPts = [
    b.proj(hl + 1.2, -hw - 0.8, 0),
    b.proj(hl + 1.2, hw + 0.8, 0),
    b.proj(-hl - 1.2, hw + 0.8, 0),
    b.proj(-hl - 1.2, -hw - 0.8, 0),
  ].map(([x, y]) => [x + shOff[0], y + shOff[1]]);
  fillPoly(targetCtx, shPts, isNight ? 'rgba(6,10,20,0.62)' : 'rgba(20,26,34,0.44)');

  const sideSign = b.ry >= 0 ? 1 : -1;
  const frontVis = b.ty >= 0;
  const endSign = frontVis ? 1 : -1;
  const outlineCol = isNight ? 'rgba(10,16,28,0.85)' : 'rgba(26,30,38,0.72)';
  const lw = Math.max(0.7, Math.min(1.4, b.s * 0.45));

  const sideShade = b.dirShade(0, sideSign);
  const endShade = b.dirShade(endSign, 0);

  if (isVan) {
    fillPoly(targetCtx, [
      b.proj(-hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBelt),
      b.proj(-hl, sideSign * hw, zBelt),
    ], shadeHex(baseHex, sideShade * 0.92, mode), outlineCol, lw);

    const upperHex = isCamper ? '#eef2f6' : (isAmbulance ? '#f4f6f9' : baseHex);
    fillPoly(targetCtx, [
      b.proj(-hl, sideSign * hw, zBelt),
      b.proj(hl * 0.56, sideSign * hw, zBelt),
      b.proj(hl * 0.50, sideSign * hw, zRoof),
      b.proj(-hl, sideSign * hw, zRoof),
    ], shadeHex(upperHex, sideShade * 0.98, mode), outlineCol, lw * 0.9);

    if (isCamper) {
      fillPoly(targetCtx, [
        b.proj(-hl * 0.78, sideSign * (hw + 0.08), zBelt + 0.6),
        b.proj(hl * 0.30, sideSign * (hw + 0.08), zBelt + 0.6),
        b.proj(hl * 0.30, sideSign * (hw + 0.08), zRoof - 0.8),
        b.proj(-hl * 0.78, sideSign * (hw + 0.08), zRoof - 0.8),
      ], isNight ? '#ffd978' : '#26384c');
    } else if (isCoopVan) {
      fillPoly(targetCtx, [
        b.proj(-hl * 0.92, sideSign * (hw + 0.08), zBot + 0.8),
        b.proj(hl * 0.42, sideSign * (hw + 0.08), zBot + 0.8),
        b.proj(hl * 0.42, sideSign * (hw + 0.08), zBelt + 0.4),
        b.proj(-hl * 0.92, sideSign * (hw + 0.08), zBelt + 0.4),
      ], shadeHex('#f07d00', sideShade * 1.04, mode));
      fillPoly(targetCtx, [
        b.proj(-hl * 0.84, sideSign * (hw + 0.09), zBelt + 0.8),
        b.proj(hl * 0.34, sideSign * (hw + 0.09), zBelt + 0.8),
        b.proj(hl * 0.34, sideSign * (hw + 0.09), zBelt + 2.0),
        b.proj(-hl * 0.84, sideSign * (hw + 0.09), zBelt + 2.0),
      ], shadeHex('#e03124', sideShade * 1.05, mode));
    } else {
      const stripeHex = isEmergency
        ? (isAmbulance ? '#e63928' : '#f8fafc')
        : (isPostVan ? '#d62828' : (isMigrosVan ? '#ff6600' : '#d4a02c'));
      fillPoly(targetCtx, [
        b.proj(-hl * 0.88, sideSign * (hw + 0.08), zBelt + 0.6),
        b.proj(hl * 0.36, sideSign * (hw + 0.08), zBelt + 0.6),
        b.proj(hl * 0.36, sideSign * (hw + 0.08), zBelt + 2.0),
        b.proj(-hl * 0.88, sideSign * (hw + 0.08), zBelt + 2.0),
      ], shadeHex(stripeHex, sideShade * 1.05, mode));
    }

    fillPoly(targetCtx, [
      b.proj(hl * 0.48, sideSign * (hw + 0.05), zBelt),
      b.proj(hl * 0.86, sideSign * (hw + 0.05), zBelt),
      b.proj(hl * 0.64, sideSign * (hw + 0.02), zRoof - 0.5),
      b.proj(hl * 0.46, sideSign * (hw + 0.02), zRoof - 0.5),
    ], isNight ? '#334d6e' : '#26384c', outlineCol, lw * 0.7);

    const endTopZ = (endSign > 0) ? zBelt : zRoof;
    const endHex = (isMigrosVan && endSign > 0) ? '#ff6600' : baseHex;
    fillPoly(targetCtx, [
      b.proj(endSign * hl, -hw, zBot),
      b.proj(endSign * hl, hw, zBot),
      b.proj(endSign * hl, hw, endTopZ),
      b.proj(endSign * hl, -hw, endTopZ),
    ], shadeHex(endHex, endShade * 0.90, mode), outlineCol, lw);

    fillPoly(targetCtx, [
      b.proj(hl * 0.92, -hw * 0.88, zBelt + 0.1),
      b.proj(hl * 0.92, hw * 0.88, zBelt + 0.1),
      b.proj(hl * 0.56, hw * 0.84, zRoof),
      b.proj(hl * 0.56, -hw * 0.84, zRoof),
    ], isNight ? '#48688c' : '#35506b', outlineCol, lw * 0.7);

    const roofHex = isEmergency
      ? (isAmbulance ? '#f8fafc' : '#e02620')
      : (isPostVan ? '#f8d238' : (isCamper ? '#f1f5f9' : '#fcf9f0'));
    fillPoly(targetCtx, [
      b.proj(-hl, -hw, zRoof),
      b.proj(hl * 0.56, -hw, zRoof),
      b.proj(hl * 0.56, hw, zRoof),
      b.proj(-hl, hw, zRoof),
    ], shadeHex(roofHex, 1.08, mode), outlineCol, lw * 0.8);

    if (isLindtVan) {
      fillPoly(targetCtx, [
        b.proj(-hl * 0.55, -hw * 0.42, zRoof + 0.1),
        b.proj(hl * 0.15, -hw * 0.42, zRoof + 0.1),
        b.proj(hl * 0.15, hw * 0.42, zRoof + 0.1),
        b.proj(-hl * 0.55, hw * 0.42, zRoof + 0.1),
      ], shadeHex('#d4a02c', 1.1, mode));
    } else if (isCamper) {
      fillPoly(targetCtx, [
        b.proj(-hl * 0.72, -hw * 0.65, zRoof + 0.4),
        b.proj(hl * 0.25, -hw * 0.65, zRoof + 0.4),
        b.proj(hl * 0.25, hw * 0.65, zRoof + 0.4),
        b.proj(-hl * 0.72, hw * 0.65, zRoof + 0.4),
      ], shadeHex('#cbd5e1', 1.04, mode), outlineCol, lw * 0.6);
    } else if (isEmergency) {
      const flashSide = (Math.floor(tSec * 6.0 + colorIdx) % 2 === 0) ? -1 : 1;
      const barPt = b.proj(hl * 0.38, flashSide * hw * 0.35, zRoof + 0.55);
      const dimPt = b.proj(hl * 0.38, -flashSide * hw * 0.35, zRoof + 0.55);
      const lSz = Math.max(1.4, 1.8 * b.s);
      if (isNight || isSunset) {
        targetCtx.save();
        targetCtx.fillStyle = isNight ? 'rgba(56, 189, 248, 0.38)' : 'rgba(56, 189, 248, 0.22)';
        targetCtx.beginPath();
        targetCtx.arc(barPt[0], barPt[1], Math.max(2.2, 2.5 * b.s), 0, Math.PI * 2);
        targetCtx.fill();
        targetCtx.restore();
      }
      targetCtx.fillStyle = '#1e3a8a';
      targetCtx.fillRect(Math.round(dimPt[0] - lSz * 0.4), Math.round(dimPt[1] - lSz * 0.4), Math.max(1, Math.round(lSz * 0.85)), Math.max(1, Math.round(lSz * 0.85)));
      targetCtx.fillStyle = '#38bdf8';
      targetCtx.fillRect(Math.round(barPt[0] - lSz * 0.5), Math.round(barPt[1] - lSz * 0.5), Math.max(1.5, Math.round(lSz)), Math.max(1.5, Math.round(lSz)));
    }
  } else {
    fillPoly(targetCtx, [
      b.proj(-hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBelt),
      b.proj(-hl, sideSign * hw, zBelt),
    ], shadeHex(baseHex, sideShade * 0.92, mode), outlineCol, lw);

    const rearWinBot = isEstate ? -hl * 0.78 : (isHatch ? -hl * 0.68 : -hl * 0.56);
    const rearRoofL = isEstate ? -hl * 0.70 : (isHatch ? -hl * 0.60 : -hl * 0.44);
    const frontRoofL = isEstate ? hl * 0.26 : hl * 0.28;

    fillPoly(targetCtx, [
      b.proj(rearWinBot, sideSign * hw * 0.92, zBelt),
      b.proj(hl * 0.46, sideSign * hw * 0.92, zBelt),
      b.proj(frontRoofL, sideSign * hw * 0.82, zRoof),
      b.proj(rearRoofL, sideSign * hw * 0.82, zRoof),
    ], isNight ? '#334d6e' : '#26384c', outlineCol, lw * 0.8);

    fillPoly(targetCtx, [
      b.proj(endSign * hl, -hw, zBot),
      b.proj(endSign * hl, hw, zBot),
      b.proj(endSign * hl, hw, zBelt),
      b.proj(endSign * hl, -hw, zBelt),
    ], shadeHex(baseHex, endShade * 0.90, mode), outlineCol, lw);

    fillPoly(targetCtx, [
      b.proj(-hl, -hw, zBelt),
      b.proj(hl, -hw, zBelt),
      b.proj(hl, hw, zBelt),
      b.proj(-hl, hw, zBelt),
    ], shadeHex(baseHex, 1.04, mode));

    fillPoly(targetCtx, [
      b.proj(hl * 0.54, -hw * 0.84, zBelt + 0.1),
      b.proj(hl * 0.54, hw * 0.84, zBelt + 0.1),
      b.proj(frontRoofL, hw * 0.78, zRoof),
      b.proj(frontRoofL, -hw * 0.78, zRoof),
    ], isNight ? '#446387' : '#354f68');
    if (!isNight) {
      fillPoly(targetCtx, [
        b.proj(hl * 0.46, -hw * 0.64, zBelt + 0.7),
        b.proj(hl * 0.46, -hw * 0.12, zBelt + 0.7),
        b.proj(frontRoofL + hl * 0.06, -hw * 0.12, zRoof - 0.5),
        b.proj(frontRoofL + hl * 0.06, -hw * 0.60, zRoof - 0.5),
      ], 'rgba(216,238,255,0.34)');
    }

    fillPoly(targetCtx, [
      b.proj(rearRoofL, -hw * 0.78, zRoof),
      b.proj(frontRoofL, -hw * 0.78, zRoof),
      b.proj(frontRoofL, hw * 0.78, zRoof),
      b.proj(rearRoofL, hw * 0.78, zRoof),
    ], shadeHex(baseHex, 1.15, mode), outlineCol, lw * 0.8);

    if (isEstate) {
      targetCtx.strokeStyle = shadeHex('#d4dce6', 1.0, mode);
      targetCtx.lineWidth = Math.max(0.7, 0.75 * b.s);
      for (const rSide of [-hw * 0.62, hw * 0.62]) {
        const r0 = b.proj(rearRoofL + 0.8, rSide, zRoof + 0.35);
        const r1 = b.proj(frontRoofL - 0.8, rSide, zRoof + 0.35);
        targetCtx.beginPath();
        targetCtx.moveTo(r0[0], r0[1]);
        targetCtx.lineTo(r1[0], r1[1]);
        targetCtx.stroke();
      }
    }
  }

  const wDot = Math.max(1.5, 2.2 * b.s);
  const hDot = Math.max(0.8, 0.9 * b.s);
  for (const wl of [-hl * 0.58, hl * 0.58]) {
    const wp = b.proj(wl, sideSign * (hw + 0.06), zBot + 0.4);
    targetCtx.fillStyle = isNight ? '#11161f' : '#1c222b';
    targetCtx.fillRect(Math.round(wp[0] - wDot * 0.55), Math.round(wp[1] - wDot * 0.45), Math.max(2, Math.round(wDot * 1.1)), Math.max(1.5, Math.round(wDot * 0.95)));
    targetCtx.fillStyle = shadeHex('#9aa6b4', 0.95, mode);
    targetCtx.fillRect(Math.round(wp[0] - hDot * 0.5), Math.round(wp[1] - hDot * 0.4), Math.max(1, Math.round(hDot)), Math.max(1, Math.round(hDot)));
  }

  const braking = !!(signals && signals.braking);
  const blinker = (signals && signals.blinker) ? signals.blinker : 'none';
  const dim = Math.max(0.25, Math.min(1.0, (signals && typeof signals.headlightDim === 'number') ? signals.headlightDim : 1.0));
  const hl1 = b.proj(hl + 0.3, -hw * 0.62, zBot + 1.6);
  const hl2 = b.proj(hl + 0.3, hw * 0.62, zBot + 1.6);
  const tl1 = b.proj(-hl - 0.3, -hw * 0.62, zBot + 1.8);
  const tl2 = b.proj(-hl - 0.3, hw * 0.62, zBot + 1.8);
  const rDot = Math.max(1.2, 1.6 * b.s);

  if (isNight || isSunset) {
    const coneLen = hl + (10 + 14 * dim);
    const coneAlpha = (isNight ? 0.22 : 0.11) * dim;
    const coneCol = isNight
      ? `rgba(255,244,186,${coneAlpha.toFixed(3)})`
      : `rgba(255,236,178,${coneAlpha.toFixed(3)})`;
    fillPoly(targetCtx, [
      hl1, hl2,
      b.proj(coneLen, hw * (1.5 + 0.7 * dim), 0.2),
      b.proj(coneLen, -hw * (1.5 + 0.7 * dim), 0.2),
    ], coneCol);
  }

  if (isNight || isSunset || braking) {
    const glowA = braking
      ? (isNight ? 0.34 : (isSunset ? 0.22 : 0.14))
      : (isNight ? 0.16 : 0.08);
    const glowLen = braking ? -hl - 11.0 : -hl - 9.5;
    fillPoly(targetCtx, [
      tl1, tl2,
      b.proj(glowLen, hw * 1.45, 0.2),
      b.proj(glowLen, -hw * 1.45, 0.2),
    ], `rgba(255, 38, 32, ${glowA.toFixed(2)})`);
  }

  targetCtx.fillStyle = isNight ? '#fff8c8' : '#fffbe0';
  targetCtx.fillRect(hl1[0] - rDot * 0.5, hl1[1] - rDot * 0.5, rDot, rDot);
  targetCtx.fillRect(hl2[0] - rDot * 0.5, hl2[1] - rDot * 0.5, rDot, rDot);

  const tSz = braking ? rDot * 1.35 : rDot;
  targetCtx.fillStyle = braking ? '#ff2a22' : (isNight ? '#ff3b30' : '#d62828');
  targetCtx.fillRect(tl1[0] - tSz * 0.5, tl1[1] - tSz * 0.5, tSz, tSz);
  targetCtx.fillRect(tl2[0] - tSz * 0.5, tl2[1] - tSz * 0.5, tSz, tSz);

  if (braking) {
    const chmsl = b.proj(-hl * 0.72, 0, isVan ? zRoof - 0.8 : zBelt + 1.8);
    const cSz = Math.max(1.1, rDot * 0.95);
    targetCtx.fillStyle = '#ff2a22';
    targetCtx.fillRect(chmsl[0] - cSz * 0.5, chmsl[1] - cSz * 0.5, cSz, cSz);
  }

  if (blinker !== 'none' && (Math.floor(tSec * 2.8) % 2 === 0)) {
    const aSz = Math.max(1.3, 1.7 * b.s);
    const sides = blinker === 'hazard' ? [-1, 1] : (blinker === 'right' ? [1] : [-1]);
    for (const sw of sides) {
      const af = b.proj(hl - 0.5, sw * hw * 0.92, zBot + 1.8);
      const ar = b.proj(-hl + 0.5, sw * hw * 0.92, zBot + 1.8);
      drawAmberDot(targetCtx, af, aSz, isNight || isSunset);
      drawAmberDot(targetCtx, ar, aSz, isNight || isSunset);
    }
  }
}

function drawBusSection(targetCtx, b, hl, hw, mode, tSec, opts) {
  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';
  const isFront = opts.isFront;
  const isRear = opts.isRear;
  const isDwelling = !!opts.isDwelling;
  const speedRatio = opts.speedRatio != null ? opts.speedRatio : 1.0;
  const wheelPositions = opts.wheelPositions || [-hl * 0.56, hl * 0.56];
  const dim = Math.max(0.25, Math.min(1.0, typeof opts.headlightDim === 'number' ? opts.headlightDim : 1.0));
  const blinker = opts.blinker || (isDwelling ? 'hazard' : 'none');

  const zBot = 1.4;
  const zBlue = 5.4;
  const zWinBot = 6.2;
  const zWinTop = 10.6;
  const zRoof = 12.2;

  const shOff = [3.6 * b.s, 2.8 * b.s];
  fillPoly(targetCtx, [
    b.proj(hl + 1.2, -hw - 1.0, 0),
    b.proj(hl + 1.2, hw + 1.0, 0),
    b.proj(-hl - 1.2, hw + 1.0, 0),
    b.proj(-hl - 1.2, -hw - 1.0, 0),
  ].map(([x, y]) => [x + shOff[0], y + shOff[1]]), isNight ? 'rgba(6,10,20,0.65)' : 'rgba(8,12,18,0.58)');

  const sideSign = b.ry >= 0 ? 1 : -1;
  const frontVis = b.ty >= 0;
  const endSign = frontVis ? 1 : -1;
  const outlineCol = isNight ? 'rgba(10,16,28,0.88)' : 'rgba(24,30,40,0.78)';
  const lw = Math.max(0.8, Math.min(1.5, b.s * 0.5));

  const sideShade = b.dirShade(0, sideSign);
  fillPoly(targetCtx, [
    b.proj(-hl, sideSign * hw, zBot),
    b.proj(hl, sideSign * hw, zBot),
    b.proj(hl, sideSign * hw, zBlue),
    b.proj(-hl, sideSign * hw, zBlue),
  ], shadeHex('#0d5ea6', sideShade, mode), outlineCol, lw);

  fillPoly(targetCtx, [
    b.proj(-hl, sideSign * hw, zBlue),
    b.proj(hl, sideSign * hw, zBlue),
    b.proj(hl, sideSign * hw, zRoof),
    b.proj(-hl, sideSign * hw, zRoof),
  ], shadeHex('#f2f5f8', sideShade, mode), outlineCol, lw);

  const winStart = -hl + 1.6;
  const winEnd = hl - 1.4;
  fillPoly(targetCtx, [
    b.proj(winStart, sideSign * (hw + 0.05), zWinBot),
    b.proj(winEnd, sideSign * (hw + 0.05), zWinBot),
    b.proj(winEnd, sideSign * (hw + 0.05), zWinTop),
    b.proj(winStart, sideSign * (hw + 0.05), zWinTop),
  ], isNight ? '#ffd978' : '#1a3048');

  targetCtx.strokeStyle = isNight ? '#263345' : shadeHex('#dce3ec', sideShade * 0.92, mode);
  targetCtx.lineWidth = Math.max(0.75, lw * 0.85);
  for (let ml = winStart + 5.2; ml < winEnd - 2.0; ml += 5.4) {
    const m0 = b.proj(ml, sideSign * (hw + 0.08), zWinBot);
    const m1 = b.proj(ml, sideSign * (hw + 0.08), zWinTop);
    targetCtx.beginPath();
    targetCtx.moveTo(m0[0], m0[1]);
    targetCtx.lineTo(m1[0], m1[1]);
    targetCtx.stroke();
  }

  if (isFront) {
    fillPoly(targetCtx, [
      b.proj(hl - 5.6, sideSign * (hw + 0.10), zWinTop - 1.3),
      b.proj(hl - 1.9, sideSign * (hw + 0.10), zWinTop - 1.3),
      b.proj(hl - 1.9, sideSign * (hw + 0.10), zWinTop - 0.1),
      b.proj(hl - 5.6, sideSign * (hw + 0.10), zWinTop - 0.1),
    ], '#161c24');
    fillPoly(targetCtx, [
      b.proj(hl - 5.2, sideSign * (hw + 0.12), zWinTop - 1.05),
      b.proj(hl - 2.3, sideSign * (hw + 0.12), zWinTop - 1.05),
      b.proj(hl - 2.3, sideSign * (hw + 0.12), zWinTop - 0.35),
      b.proj(hl - 5.2, sideSign * (hw + 0.12), zWinTop - 0.35),
    ], '#ff9e1b');
  }

  for (const wl of wheelPositions) {
    fillPoly(targetCtx, [
      b.proj(wl - 2.4, sideSign * (hw + 0.09), zBot - 0.3),
      b.proj(wl + 2.4, sideSign * (hw + 0.09), zBot - 0.3),
      b.proj(wl + 2.0, sideSign * (hw + 0.09), zBot + 2.4),
      b.proj(wl - 2.0, sideSign * (hw + 0.09), zBot + 2.4),
    ], isNight ? '#11161f' : '#1c222b');
    const hp = b.proj(wl, sideSign * (hw + 0.11), zBot + 0.9);
    const hSz = Math.max(1.0, 1.3 * b.s);
    targetCtx.fillStyle = shadeHex('#9aa6b4', 0.96, mode);
    targetCtx.fillRect(Math.round(hp[0] - hSz * 0.5), Math.round(hp[1] - hSz * 0.5), Math.max(1, Math.round(hSz)), Math.max(1, Math.round(hSz)));
  }

  const endShade = b.dirShade(endSign, 0);
  const drawOuterEnd = (endSign > 0 && isFront) || (endSign < 0 && isRear);
  fillPoly(targetCtx, [
    b.proj(endSign * hl, -hw, zBot),
    b.proj(endSign * hl, hw, zBot),
    b.proj(endSign * hl, hw, zBlue),
    b.proj(endSign * hl, -hw, zBlue),
  ], shadeHex(drawOuterEnd ? '#0d5ea6' : '#262c34', endShade, mode), outlineCol, lw);
  fillPoly(targetCtx, [
    b.proj(endSign * hl, -hw, zBlue),
    b.proj(endSign * hl, hw, zBlue),
    b.proj(endSign * hl, hw, zRoof),
    b.proj(endSign * hl, -hw, zRoof),
  ], shadeHex(drawOuterEnd ? '#f2f5f8' : '#2e3540', endShade, mode), outlineCol, lw);

  if (frontVis && isFront) {
    fillPoly(targetCtx, [
      b.proj(hl + 0.06, -hw * 0.85, zWinBot - 0.4),
      b.proj(hl + 0.06, hw * 0.85, zWinBot - 0.4),
      b.proj(hl + 0.06, hw * 0.85, zWinTop - 0.1),
      b.proj(hl + 0.06, -hw * 0.85, zWinTop - 0.1),
    ], isNight ? '#58789c' : '#1a3048');
    fillPoly(targetCtx, [
      b.proj(hl + 0.10, -hw * 0.62, zWinTop + 0.1),
      b.proj(hl + 0.10, hw * 0.62, zWinTop + 0.1),
      b.proj(hl + 0.10, hw * 0.62, zRoof - 0.35),
      b.proj(hl + 0.10, -hw * 0.62, zRoof - 0.35),
    ], '#141920');
    fillPoly(targetCtx, [
      b.proj(hl + 0.14, -hw * 0.48, zWinTop + 0.35),
      b.proj(hl + 0.14, hw * 0.48, zWinTop + 0.35),
      b.proj(hl + 0.14, hw * 0.48, zRoof - 0.6),
      b.proj(hl + 0.14, -hw * 0.48, zRoof - 0.6),
    ], '#ffb340');
  }

  fillPoly(targetCtx, [
    b.proj(-hl, -hw, zRoof),
    b.proj(hl, -hw, zRoof),
    b.proj(hl, hw, zRoof),
    b.proj(-hl, hw, zRoof),
  ], shadeHex('#ffffff', 1.05, mode), outlineCol, lw);

  if (opts.hasAcPod !== false) {
    const acHalf = Math.min(7.0, hl * 0.36);
    fillPoly(targetCtx, [
      b.proj(-acHalf, -hw * 0.58, zRoof + 1.4),
      b.proj(acHalf, -hw * 0.58, zRoof + 1.4),
      b.proj(acHalf, hw * 0.58, zRoof + 1.4),
      b.proj(-acHalf, hw * 0.58, zRoof + 1.4),
    ], shadeHex('#cfd7e0', 1.0, mode), outlineCol, lw * 0.7);
  }

  const rDot = Math.max(1.4, 1.8 * b.s);

  if (isFront) {
    const hl1 = b.proj(hl + 0.18, -hw * 0.68, zBot + 1.8);
    const hl2 = b.proj(hl + 0.18, hw * 0.68, zBot + 1.8);
    if (isNight || isSunset) {
      const coneLen = hl + (12 + 18 * dim);
      const coneAlpha = (isNight ? 0.25 : 0.12) * dim;
      const coneCol = isNight
        ? `rgba(255,244,186,${coneAlpha.toFixed(3)})`
        : `rgba(255,236,178,${coneAlpha.toFixed(3)})`;
      fillPoly(targetCtx, [
        hl1, hl2,
        b.proj(coneLen, hw * (1.8 + 0.8 * dim), 0.2),
        b.proj(coneLen, -hw * (1.8 + 0.8 * dim), 0.2),
      ], coneCol);
    }
    targetCtx.fillStyle = isNight ? '#fff8c8' : '#fffbe0';
    targetCtx.fillRect(hl1[0] - rDot * 0.5, hl1[1] - rDot * 0.5, rDot, rDot);
    targetCtx.fillRect(hl2[0] - rDot * 0.5, hl2[1] - rDot * 0.5, rDot, rDot);
  }

  if (isRear) {
    const isBraking = !!opts.braking || isDwelling || speedRatio < 0.45;
    const tl1 = b.proj(-hl - 0.18, -hw * 0.68, zBot + 2.0);
    const tl2 = b.proj(-hl - 0.18, hw * 0.68, zBot + 2.0);
    if (isNight || isSunset || isBraking) {
      const glowA = isBraking
        ? (isNight ? 0.30 : (isSunset ? 0.20 : 0.14))
        : (isNight ? 0.16 : 0.08);
      fillPoly(targetCtx, [
        tl1, tl2,
        b.proj(-hl - 12, hw * 1.55, 0.2),
        b.proj(-hl - 12, -hw * 1.55, 0.2),
      ], `rgba(255, 42, 36, ${glowA.toFixed(2)})`);
    }
    targetCtx.fillStyle = isBraking ? '#ff2a22' : (isNight ? '#ff3b30' : '#d62828');
    const tSz = isBraking ? rDot * 1.3 : rDot;
    targetCtx.fillRect(tl1[0] - tSz * 0.5, tl1[1] - tSz * 0.5, tSz, tSz);
    targetCtx.fillRect(tl2[0] - tSz * 0.5, tl2[1] - tSz * 0.5, tSz, tSz);

    if (isBraking) {
      const u1 = b.proj(-hl - 0.18, -hw * 0.62, zWinTop - 0.4);
      const u2 = b.proj(-hl - 0.18, hw * 0.62, zWinTop - 0.4);
      const uSz = Math.max(1.2, rDot * 0.95);
      targetCtx.fillRect(u1[0] - uSz * 0.5, u1[1] - uSz * 0.5, uSz, uSz);
      targetCtx.fillRect(u2[0] - uSz * 0.5, u2[1] - uSz * 0.5, uSz, uSz);
    }
  }

  if (blinker !== 'none' && (Math.floor(tSec * 2.8) % 2 === 0)) {
    const aSz = Math.max(1.5, 1.9 * b.s);
    const sides = blinker === 'hazard' ? [-1, 1] : (blinker === 'right' ? [1] : [-1]);
    if (isFront) {
      for (const sw of sides) {
        const af = b.proj(hl - 0.6, sw * hw * 0.95, zBot + 2.0);
        drawAmberDot(targetCtx, af, aSz, isNight || isSunset);
      }
      if (blinker === 'hazard' || isDwelling) {
        const ad = b.proj(hl - 4.0, sideSign * (hw + 0.12), zWinTop + 0.5);
        drawAmberDot(targetCtx, ad, aSz, isNight || isSunset);
      }
    }
    if (isRear) {
      for (const sw of sides) {
        const ar = b.proj(-hl + 0.6, sw * hw * 0.95, zBot + 2.0);
        drawAmberDot(targetCtx, ar, aSz, isNight || isSunset);
      }
    }
  }
}

export function draw3DBus(targetCtx, cam, pos, wScale, mode, tSec = 0, speedRatio = 1.0, isDwelling = false, routeNum = '165', signals = null) {
  const b = makeScreenIsoBasis(cam, pos.wx, pos.wy, pos.tx, pos.ty, wScale);
  if (b.cx < -64 || b.cx > cam.width + 64 || b.cy < -64 || b.cy > cam.height + 64) return;
  drawBusSection(targetCtx, b, 22.0, 6.0, mode, tSec, {
    isFront: true,
    isRear: true,
    routeNum,
    speedRatio,
    isDwelling,
    braking: !!(signals && signals.braking),
    blinker: (signals && signals.blinker) || (isDwelling ? 'hazard' : 'none'),
    headlightDim: (signals && typeof signals.headlightDim === 'number') ? signals.headlightDim : 1.0,
    wheelPositions: [-12.5, 12.5],
    hasAcPod: true,
  });
}

export function draw3DArticulatedBus(targetCtx, cam, pRear, pMidRear, pMidFront, pFront, wScale, mode, tSec = 0, speedRatio = 1.0, isDwelling = false, signals = null) {
  const hlFront = 20.4;
  const hlRear = 14.4;
  const hw = 5.8;
  const bFront = makeTwoPointIsoBasis(cam, pMidFront, pFront, hlFront, wScale);
  const bRear = makeTwoPointIsoBasis(cam, pRear, pMidRear, hlRear, wScale);
  if (bFront.cx < -100 || bFront.cx > cam.width + 100 || bFront.cy < -100 || bFront.cy > cam.height + 100) return;

  const isNight = mode === 'night';
  const outlineCol = isNight ? 'rgba(10,16,28,0.88)' : 'rgba(24,30,40,0.78)';
  const lw = Math.max(0.8, Math.min(1.4, bFront.s * 0.48));
  const sideSign = bFront.ry >= 0 ? 1 : -1;

  const drawBellows = () => {
    const bw = hw * 0.86;
    const zBot = 1.8;
    const zRoof = 11.7;
    fillPoly(targetCtx, [
      bFront.proj(-hlFront, sideSign * bw, zBot),
      bRear.proj(hlRear, sideSign * bw, zBot),
      bRear.proj(hlRear, sideSign * bw, zRoof),
      bFront.proj(-hlFront, sideSign * bw, zRoof),
    ], shadeHex('#262c34', 0.90, mode), outlineCol, lw * 0.85);
    fillPoly(targetCtx, [
      bFront.proj(-hlFront, -bw, zRoof),
      bRear.proj(hlRear, -bw, zRoof),
      bRear.proj(hlRear, bw, zRoof),
      bFront.proj(-hlFront, bw, zRoof),
    ], shadeHex('#363e48', 0.98, mode), outlineCol, lw * 0.8);
    targetCtx.strokeStyle = shadeHex('#525e6e', 1.0, mode);
    targetCtx.lineWidth = Math.max(0.7, lw * 0.75);
    for (const f of [0.33, 0.67]) {
      const a0 = bFront.proj(-hlFront, sideSign * (bw + 0.06), zBot + 0.4);
      const a1 = bRear.proj(hlRear, sideSign * (bw + 0.06), zBot + 0.4);
      const c0 = bFront.proj(-hlFront, sideSign * (bw + 0.06), zRoof - 0.3);
      const c1 = bRear.proj(hlRear, sideSign * (bw + 0.06), zRoof - 0.3);
      targetCtx.beginPath();
      targetCtx.moveTo(a0[0] + (a1[0] - a0[0]) * f, a0[1] + (a1[1] - a0[1]) * f);
      targetCtx.lineTo(c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f);
      targetCtx.stroke();
    }
  };

  const sigBraking = !!(signals && signals.braking);
  const sigBlinker = (signals && signals.blinker) || (isDwelling ? 'hazard' : 'none');
  const sigDim = (signals && typeof signals.headlightDim === 'number') ? signals.headlightDim : 1.0;

  const frontOpts = {
    isFront: true, isRear: false, routeNum: '161', speedRatio, isDwelling,
    braking: sigBraking, blinker: sigBlinker, headlightDim: sigDim,
    wheelPositions: [-11.0, 11.5], hasAcPod: true,
  };
  const rearOpts = {
    isFront: false, isRear: true, routeNum: '161', speedRatio, isDwelling,
    braking: sigBraking, blinker: sigBlinker, headlightDim: sigDim,
    wheelPositions: [-4.5], hasAcPod: true,
  };

  if (bRear.cy <= bFront.cy) {
    drawBusSection(targetCtx, bRear, hlRear, hw, mode, tSec, rearOpts);
    drawBellows();
    drawBusSection(targetCtx, bFront, hlFront, hw, mode, tSec, frontOpts);
  } else {
    drawBusSection(targetCtx, bFront, hlFront, hw, mode, tSec, frontOpts);
    drawBellows();
    drawBusSection(targetCtx, bRear, hlRear, hw, mode, tSec, rearOpts);
  }
}

export function draw3DTrainUnit(targetCtx, cam, pRear, pFront, kind, variant, wScale, mode, nextRear, nextFront, tSec = 0, isDwelling = false, dwellProgress = 0) {
  const hl = 34.5;
  const b = makeTwoPointIsoBasis(cam, pRear, pFront, hl, wScale);
  if (b.cx < -140 || b.cx > cam.width + 140 || b.cy < -140 || b.cy > cam.height + 140) return;

  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';
  const isKISS = (kind === 'sbb_dpz' || kind === 'sbb_kiss');
  const isLead = variant === 0;
  const isTail = variant === 2;

  const hw = 6.8;
  const zBot = 1.6;
  const zSkirt = 3.8;
  const zEave = isKISS ? 14.4 : 13.0;
  const zCrown = isKISS ? 16.8 : 15.2;

  const sideSign = b.ry >= 0 ? 1 : -1;
  const frontVis = b.ty >= 0;
  const endSign = frontVis ? 1 : -1;
  const outlineCol = isNight ? 'rgba(10,16,28,0.90)' : 'rgba(24,28,36,0.82)';
  const lw = Math.max(0.8, Math.min(1.6, b.s * 0.55));

  const shOff = [5.4 * b.s, 4.0 * b.s];
  fillPoly(targetCtx, [
    b.proj(hl + 1.5, -hw - 1.2, 0),
    b.proj(hl + 1.5, hw + 1.2, 0),
    b.proj(-hl - 1.5, hw + 1.2, 0),
    b.proj(-hl - 1.5, -hw - 1.2, 0),
  ].map(([x, y]) => [x + shOff[0], y + shOff[1]]), isNight ? 'rgba(6,10,20,0.68)' : 'rgba(20,24,32,0.48)');

  if (nextRear && nextFront) {
    const bNext = makeTwoPointIsoBasis(cam, nextRear, nextFront, hl, wScale);
    const gw = hw * 0.78;
    fillPoly(targetCtx, [
      b.proj(-hl, sideSign * gw, zSkirt),
      bNext.proj(hl, sideSign * gw, zSkirt),
      bNext.proj(hl, sideSign * gw, zEave - 0.4),
      b.proj(-hl, sideSign * gw, zEave - 0.4),
    ], shadeHex('#2c323b', 0.85, mode), outlineCol, lw * 0.8);
    fillPoly(targetCtx, [
      b.proj(-hl, -gw, zEave - 0.4),
      bNext.proj(hl, -gw, zEave - 0.4),
      bNext.proj(hl, gw, zEave - 0.4),
      b.proj(-hl, gw, zEave - 0.4),
    ], shadeHex('#3e4652', 0.95, mode), outlineCol, lw * 0.8);
  }

  const sideShade = b.dirShade(0, sideSign);
  const bodyHex = isKISS ? '#eef2f6' : ((isLead || isTail) ? '#d92121' : '#f2f5f8');
  fillPoly(targetCtx, [
    b.proj(-hl, sideSign * hw, zBot),
    b.proj(hl, sideSign * hw, zBot),
    b.proj(hl, sideSign * hw, zSkirt),
    b.proj(-hl, sideSign * hw, zSkirt),
  ], shadeHex('#2b313a', sideShade, mode), outlineCol, lw);

  const noseL = isLead ? hl - 4.0 : hl;
  const tailL = isTail ? -hl + 4.0 : -hl;
  fillPoly(targetCtx, [
    b.proj(-hl, sideSign * hw, zSkirt),
    b.proj(hl, sideSign * hw, zSkirt),
    b.proj(noseL, sideSign * hw, zEave),
    b.proj(tailL, sideSign * hw, zEave),
  ], shadeHex(bodyHex, sideShade, mode), outlineCol, lw);

  const winColor = isNight ? '#ffd670' : '#5880a4';
  const bandColor = isNight ? '#1b2432' : '#232a34';
  let doorPositions = null;
  let doorTopZ = zSkirt + 5.2;

  if (isKISS) {
    fillPoly(targetCtx, [
      b.proj(-hl + 1.5, sideSign * (hw + 0.07), zSkirt),
      b.proj(hl - 1.5, sideSign * (hw + 0.07), zSkirt),
      b.proj(hl - 1.5, sideSign * (hw + 0.07), zSkirt + 0.9),
      b.proj(-hl + 1.5, sideSign * (hw + 0.07), zSkirt + 0.9),
    ], shadeHex('#1e5cb3', sideShade * 1.05, mode));

    fillPoly(targetCtx, [
      b.proj(-hl + 5.5, sideSign * (hw + 0.06), zSkirt + 1.0),
      b.proj(hl - 5.5, sideSign * (hw + 0.06), zSkirt + 1.0),
      b.proj(hl - 5.5, sideSign * (hw + 0.06), zSkirt + 4.0),
      b.proj(-hl + 5.5, sideSign * (hw + 0.06), zSkirt + 4.0),
    ], bandColor);
    fillPoly(targetCtx, [
      b.proj(-hl + 4.5, sideSign * (hw + 0.06), zSkirt + 5.4),
      b.proj(hl - 4.5, sideSign * (hw + 0.06), zSkirt + 5.4),
      b.proj(hl - 4.5, sideSign * (hw + 0.06), zEave - 1.2),
      b.proj(-hl + 4.5, sideSign * (hw + 0.06), zEave - 1.2),
    ], bandColor);

    for (let w = -24; w <= 22; w += 8) {
      fillPoly(targetCtx, [
        b.proj(w, sideSign * (hw + 0.09), zSkirt + 1.3),
        b.proj(w + 5.2, sideSign * (hw + 0.09), zSkirt + 1.3),
        b.proj(w + 5.2, sideSign * (hw + 0.09), zSkirt + 3.7),
        b.proj(w, sideSign * (hw + 0.09), zSkirt + 3.7),
      ], winColor);
      fillPoly(targetCtx, [
        b.proj(w, sideSign * (hw + 0.09), zSkirt + 5.8),
        b.proj(w + 5.2, sideSign * (hw + 0.09), zSkirt + 5.8),
        b.proj(w + 5.2, sideSign * (hw + 0.09), zEave - 1.5),
        b.proj(w, sideSign * (hw + 0.09), zEave - 1.5),
      ], winColor);
    }

    const redDoor = shadeHex('#d92121', sideShade * 1.05, mode);
    doorPositions = [-20.5, 16.5];
    doorTopZ = zSkirt + 5.2;
    for (const dPos of doorPositions) {
      fillPoly(targetCtx, [
        b.proj(dPos, sideSign * (hw + 0.12), zSkirt),
        b.proj(dPos + 4.2, sideSign * (hw + 0.12), zSkirt),
        b.proj(dPos + 4.2, sideSign * (hw + 0.12), doorTopZ),
        b.proj(dPos, sideSign * (hw + 0.12), doorTopZ),
      ], redDoor);
    }
    fillPoly(targetCtx, [
      b.proj(tailL + 1.5, sideSign * (hw + 0.08), zEave - 1.0),
      b.proj(noseL - 1.5, sideSign * (hw + 0.08), zEave - 1.0),
      b.proj(noseL - 1.5, sideSign * (hw + 0.08), zEave),
      b.proj(tailL + 1.5, sideSign * (hw + 0.08), zEave),
    ], shadeHex('#d92121', sideShade, mode));
  } else if (!isLead && !isTail) {
    fillPoly(targetCtx, [
      b.proj(-hl + 5.0, sideSign * (hw + 0.06), zSkirt + 3.0),
      b.proj(hl - 5.0, sideSign * (hw + 0.06), zSkirt + 3.0),
      b.proj(hl - 5.0, sideSign * (hw + 0.06), zEave - 1.8),
      b.proj(-hl + 5.0, sideSign * (hw + 0.06), zEave - 1.8),
    ], bandColor);
    for (let w = -25; w <= 23; w += 8.5) {
      fillPoly(targetCtx, [
        b.proj(w, sideSign * (hw + 0.09), zSkirt + 3.4),
        b.proj(w + 5.8, sideSign * (hw + 0.09), zSkirt + 3.4),
        b.proj(w + 5.8, sideSign * (hw + 0.09), zEave - 2.1),
        b.proj(w, sideSign * (hw + 0.09), zEave - 2.1),
      ], winColor);
    }
    const redDoor = shadeHex('#d92121', sideShade * 1.05, mode);
    doorPositions = [-30.0, 26.0];
    doorTopZ = zEave - 1.8;
    for (const dPos of doorPositions) {
      fillPoly(targetCtx, [
        b.proj(dPos, sideSign * (hw + 0.12), zSkirt),
        b.proj(dPos + 4.0, sideSign * (hw + 0.12), zSkirt),
        b.proj(dPos + 4.0, sideSign * (hw + 0.12), doorTopZ),
        b.proj(dPos, sideSign * (hw + 0.12), doorTopZ),
      ], redDoor);
    }
  } else {
    const cabDir = isLead ? 1 : -1;
    fillPoly(targetCtx, [
      b.proj(cabDir * (hl - 10.5), sideSign * (hw + 0.08), zSkirt + 3.6),
      b.proj(cabDir * (hl - 3.6), sideSign * (hw + 0.08), zSkirt + 3.6),
      b.proj(cabDir * (hl - 4.8), sideSign * (hw + 0.08), zEave - 1.6),
      b.proj(cabDir * (hl - 10.5), sideSign * (hw + 0.08), zEave - 1.6),
    ], isNight ? '#58789c' : '#243a52');
    fillPoly(targetCtx, [
      b.proj(-11.0, sideSign * (hw + 0.09), zSkirt + 3.8),
      b.proj(11.0, sideSign * (hw + 0.09), zSkirt + 3.8),
      b.proj(11.0, sideSign * (hw + 0.09), zSkirt + 5.4),
      b.proj(-11.0, sideSign * (hw + 0.09), zSkirt + 5.4),
    ], shadeHex('#f4f7fa', sideShade * 1.05, mode));
    fillPoly(targetCtx, [
      b.proj(-16.0, sideSign * (hw + 0.07), zEave - 2.6),
      b.proj(16.0, sideSign * (hw + 0.07), zEave - 2.6),
      b.proj(16.0, sideSign * (hw + 0.07), zEave - 1.0),
      b.proj(-16.0, sideSign * (hw + 0.07), zEave - 1.0),
    ], shadeHex('#7d1818', sideShade, mode));
  }

  if (isDwelling && doorPositions) {
    const doorsOpen = dwellProgress >= 0.12 && dwellProgress <= 0.78;
    const closingWarn = dwellProgress > 0.62;
    const blinkOn = closingWarn ? (Math.floor(tSec * 8.0) % 2 === 0) : true;
    const dDot = Math.max(1.4, 1.8 * b.s);
    for (const dPos of doorPositions) {
      if (doorsOpen) {
        fillPoly(targetCtx, [
          b.proj(dPos + 0.7, sideSign * (hw + 0.15), zSkirt + 0.3),
          b.proj(dPos + 3.4, sideSign * (hw + 0.15), zSkirt + 0.3),
          b.proj(dPos + 3.4, sideSign * (hw + 0.15), doorTopZ - 0.5),
          b.proj(dPos + 0.7, sideSign * (hw + 0.15), doorTopZ - 0.5),
        ], (isNight || isSunset) ? '#ffe496' : '#fef3c7');
        if (isNight || isSunset) {
          fillPoly(targetCtx, [
            b.proj(dPos, sideSign * (hw + 0.2), 0.3),
            b.proj(dPos + 4.0, sideSign * (hw + 0.2), 0.3),
            b.proj(dPos + 4.8, sideSign * (hw + 5.0), 0.1),
            b.proj(dPos - 0.8, sideSign * (hw + 5.0), 0.1),
          ], isNight ? 'rgba(255, 224, 138, 0.28)' : 'rgba(255, 218, 128, 0.16)');
        }
      }
      if (blinkOn) {
        const lp = b.proj(dPos + 2.0, sideSign * (hw + 0.18), doorTopZ + 0.55);
        if (isNight || isSunset) {
          targetCtx.save();
          targetCtx.fillStyle = 'rgba(255, 210, 48, 0.42)';
          targetCtx.beginPath();
          targetCtx.arc(lp[0], lp[1], dDot * 1.9, 0, Math.PI * 2);
          targetCtx.fill();
          targetCtx.restore();
        }
        targetCtx.fillStyle = closingWarn ? '#ffd426' : '#ffbe2e';
        targetCtx.fillRect(Math.round(lp[0] - dDot * 0.5), Math.round(lp[1] - dDot * 0.5), Math.max(1.5, Math.round(dDot)), Math.max(1.5, Math.round(dDot)));
      }
    }
  }

  const endShade = b.dirShade(endSign, 0);
  const isCabFace = (endSign > 0 && isLead) || (endSign < 0 && isTail);
  const endTopL = (endSign > 0 ? noseL : tailL);
  const endHex = isCabFace ? '#d92121' : '#3a424d';
  fillPoly(targetCtx, [
    b.proj(endSign * hl, -hw, zSkirt),
    b.proj(endSign * hl, hw, zSkirt),
    b.proj(endTopL, hw, zEave),
    b.proj(endTopL, -hw, zEave),
  ], shadeHex(endHex, endShade, mode), outlineCol, lw);

  if (isCabFace) {
    const wL0 = endSign * (hl - 1.4);
    const wL1 = endSign * (hl - 3.6);
    fillPoly(targetCtx, [
      b.proj(wL0, -hw * 0.78, zSkirt + 4.4),
      b.proj(wL0, hw * 0.78, zSkirt + 4.4),
      b.proj(wL1, hw * 0.72, zEave - 1.2),
      b.proj(wL1, -hw * 0.72, zEave - 1.2),
    ], isNight ? '#58789c' : '#1d2d40');
  }

  const rw = hw * 0.62;
  const nwBevelShade = b.dirShade(0, -1) * 0.5 + 0.62;
  const seBevelShade = b.dirShade(0, 1) * 0.5 + 0.54;
  fillPoly(targetCtx, [
    b.proj(tailL, -hw, zEave),
    b.proj(noseL, -hw, zEave),
    b.proj(noseL - 0.8, -rw, zCrown),
    b.proj(tailL + 0.8, -rw, zCrown),
  ], shadeHex('#d4dce5', nwBevelShade, mode));
  fillPoly(targetCtx, [
    b.proj(tailL, hw, zEave),
    b.proj(noseL, hw, zEave),
    b.proj(noseL - 0.8, rw, zCrown),
    b.proj(tailL + 0.8, rw, zCrown),
  ], shadeHex('#c4ceda', seBevelShade, mode));
  fillPoly(targetCtx, [
    b.proj(tailL + 0.8, -rw, zCrown),
    b.proj(noseL - 0.8, -rw, zCrown),
    b.proj(noseL - 0.8, rw, zCrown),
    b.proj(tailL + 0.8, rw, zCrown),
  ], shadeHex('#e8eef5', 1.06, mode), outlineCol, lw * 0.75);

  for (const podL of [-14, 10]) {
    fillPoly(targetCtx, [
      b.proj(podL - 4.5, -rw * 0.72, zCrown + 1.1),
      b.proj(podL + 4.5, -rw * 0.72, zCrown + 1.1),
      b.proj(podL + 4.5, rw * 0.72, zCrown + 1.1),
      b.proj(podL - 4.5, rw * 0.72, zCrown + 1.1),
    ], shadeHex('#bcc6d2', 0.98, mode), outlineCol, lw * 0.6);
  }

  const rDot = Math.max(1.4, 1.8 * b.s);

  if (isLead) {
    const p0 = b.proj(-22, -rw * 0.9, zCrown + 3.4);
    const p1 = b.proj(-22, rw * 0.9, zCrown + 3.4);
    targetCtx.strokeStyle = isNight ? '#96a8c0' : '#4a5462';
    targetCtx.lineWidth = Math.max(1.0, b.s * 0.7);
    targetCtx.beginPath();
    targetCtx.moveTo(p0[0], p0[1]);
    targetCtx.lineTo(p1[0], p1[1]);
    targetCtx.stroke();

    if (!isDwelling) {
      const sparkSlot = Math.floor(tSec * 14.0);
      const sparkHash = Math.sin(sparkSlot * 127.1 + Math.round(b.cx * 0.05) * 31.7) * 43758.5453;
      if ((sparkHash - Math.floor(sparkHash)) > (isNight ? 0.945 : 0.975)) {
        const pm = b.proj(-22, 0, zCrown + 3.6);
        const spR = Math.max(2.0, 3.2 * b.s);
        targetCtx.save();
        targetCtx.fillStyle = isNight ? 'rgba(110, 230, 255, 0.55)' : 'rgba(140, 235, 255, 0.35)';
        targetCtx.beginPath();
        targetCtx.arc(pm[0], pm[1], spR * 1.9, 0, Math.PI * 2);
        targetCtx.fill();
        targetCtx.fillStyle = '#f2feff';
        targetCtx.fillRect(Math.round(pm[0] - spR * 0.5), Math.round(pm[1] - spR * 0.5), Math.max(2, Math.round(spR)), Math.max(2, Math.round(spR)));
        targetCtx.restore();
      }
    }

    if (isNight) {
      fillPoly(targetCtx, [
        b.proj(hl, -hw * 0.75, zSkirt + 2.0),
        b.proj(hl, hw * 0.75, zSkirt + 2.0),
        b.proj(hl + 52, hw * 3.4, 0.2),
        b.proj(hl + 52, -hw * 3.4, 0.2),
      ], 'rgba(255,244,186,0.28)');
    }
    const leadLamps = [
      b.proj(hl + 0.15, -hw * 0.58, zSkirt + 1.8),
      b.proj(hl + 0.15, hw * 0.58, zSkirt + 1.8),
      b.proj(noseL + 0.5, 0, zEave - 1.4),
    ];
    targetCtx.fillStyle = isNight ? '#fff8cc' : '#fffbe6';
    for (const lp of leadLamps) {
      targetCtx.fillRect(Math.round(lp[0] - rDot * 0.5), Math.round(lp[1] - rDot * 0.5), Math.max(1.5, Math.round(rDot)), Math.max(1.5, Math.round(rDot)));
    }
  }

  if (isTail) {
    const tl1 = b.proj(-hl - 0.15, -hw * 0.58, zSkirt + 1.8);
    const tl2 = b.proj(-hl - 0.15, hw * 0.58, zSkirt + 1.8);
    if (isNight || isSunset) {
      fillPoly(targetCtx, [
        b.proj(-hl, -hw * 0.8, zSkirt + 1.5),
        b.proj(-hl, hw * 0.8, zSkirt + 1.5),
        b.proj(-hl - 16, hw * 1.4, 0.2),
        b.proj(-hl - 16, -hw * 1.4, 0.2),
      ], isNight ? 'rgba(255, 40, 36, 0.18)' : 'rgba(255, 44, 38, 0.10)');
      targetCtx.save();
      targetCtx.fillStyle = isNight ? 'rgba(255, 42, 38, 0.36)' : 'rgba(255, 48, 42, 0.22)';
      for (const tp of [tl1, tl2]) {
        targetCtx.beginPath();
        targetCtx.arc(tp[0], tp[1], rDot * 2.2, 0, Math.PI * 2);
        targetCtx.fill();
      }
      targetCtx.restore();
    }
    targetCtx.fillStyle = (isNight || isSunset) ? '#ff2e2e' : '#e02424';
    targetCtx.fillRect(Math.round(tl1[0] - rDot * 0.5), Math.round(tl1[1] - rDot * 0.5), Math.max(1.5, Math.round(rDot)), Math.max(1.5, Math.round(rDot)));
    targetCtx.fillRect(Math.round(tl2[0] - rDot * 0.5), Math.round(tl2[1] - rDot * 0.5), Math.max(1.5, Math.round(rDot)), Math.max(1.5, Math.round(rDot)));
  }
}

export function draw3DCyclist(targetCtx, cam, pos, colorIdx, wScale, mode, tSec) {
  const b = makeScreenIsoBasis(cam, pos.wx, pos.wy, pos.tx, pos.ty, wScale);
  if (b.cx < -28 || b.cx > cam.width + 28 || b.cy < -28 || b.cy > cam.height + 28) return;

  const isNight = mode === 'night';
  const jerseys = ['#d9382e', '#2563eb', '#eab308', '#0d9488', '#ea580c', '#16a34a'];
  const helmets = ['#f4f7fa', '#ef4444', '#facc15', '#38bdf8', '#f4f7fa', '#fb923c'];
  const jerseyHex = jerseys[colorIdx % jerseys.length];
  const helmetHex = helmets[(colorIdx * 3 + 1) % helmets.length];
  const pedal = Math.sin(tSec * 11.0 + colorIdx * 1.7);
  const pSz = Math.max(1.0, b.s);

  const pix = (l, w, z, pw, ph, col) => {
    const [x, y] = b.proj(l, w, z);
    targetCtx.fillStyle = col;
    targetCtx.fillRect(
      Math.round(x - pw * 0.5 * pSz),
      Math.round(y - ph * 0.5 * pSz),
      Math.max(1, Math.round(pw * pSz)),
      Math.max(1, Math.round(ph * pSz)),
    );
  };

  const tireCol = isNight ? '#3a4658' : '#181e26';
  const hubCol = shadeHex('#b8c4d0', 1.0, mode);
  const frameCol = shadeHex('#dce4ee', 1.04, mode);
  const shortsCol = shadeHex('#202834', 0.95, mode);
  const skinCol = shadeHex('#ecc29c', 1.02, mode);
  const jLit = shadeHex(jerseyHex, 1.15, mode);
  const jDark = shadeHex(jerseyHex, 0.76, mode);
  const helmCol = shadeHex(helmetHex, 1.08, mode);

  pix(0.0, 0.4, 0.0, 6.4, 1.6, isNight ? 'rgba(6,10,20,0.52)' : 'rgba(18,24,32,0.34)');
  for (const wl of [-2.5, 2.6]) {
    pix(wl, 0, 1.25, 2.3, 2.5, tireCol);
    pix(wl, 0, 1.25, 1.0, 1.0, hubCol);
  }
  pix(-1.1, 0, 2.1, 2.7, 0.85, frameCol);
  pix(0.5, 0, 2.9, 2.9, 0.85, frameCol);
  pix(2.0, 0, 2.5, 0.9, 2.3, frameCol);
  pix(-1.2, 0, 3.4, 1.4, 0.75, tireCol);
  pix(2.1, 0, 3.8, 1.2, 0.8, tireCol);

  const pUp = pedal * 0.65;
  pix(-0.8, 0.15, 3.1, 1.5, 1.4, shortsCol);
  pix(-0.1 + pUp * 0.5, 0.2, 2.0 - pUp * 0.5, 0.95, 1.35, skinCol);
  pix(0.1 + pUp * 0.6, 0.2, 1.1 - pUp * 0.6, 1.1, 0.8, tireCol);

  pix(-0.1, 0, 4.7, 2.3, 2.0, jDark);
  pix(0.0, -0.2, 5.2, 2.0, 1.3, jLit);
  pix(1.3, 0.1, 4.4, 1.6, 0.95, jLit);
  pix(2.0, 0.1, 3.9, 0.85, 0.85, skinCol);

  pix(1.1, 0.1, 6.2, 1.25, 1.15, skinCol);
  pix(1.0, 0.0, 6.9, 1.85, 1.0, helmCol);
  pix(1.45, 0.0, 6.5, 1.15, 0.5, tireCol);

  if (isNight || mode === 'sunset') {
    if (isNight) {
      fillPoly(targetCtx, [
        b.proj(3.0, 0, 2.8),
        b.proj(12.0, 2.4, 0.2),
        b.proj(12.0, -2.4, 0.2),
      ], 'rgba(255, 252, 224, 0.16)');
    }
    pix(2.9, 0, 3.3, 1.2, 1.2, isNight ? '#ffffff' : '#fff9c4');
    const blink = Math.floor(tSec * 4.0 + colorIdx * 1.3) % 2 === 0;
    if (blink) {
      const rp = b.proj(-2.7, 0, 2.9);
      if (isNight) {
        targetCtx.save();
        targetCtx.fillStyle = 'rgba(255, 46, 46, 0.34)';
        targetCtx.beginPath();
        targetCtx.arc(rp[0], rp[1], Math.max(2.0, 2.2 * pSz), 0, Math.PI * 2);
        targetCtx.fill();
        targetCtx.restore();
      }
      pix(-2.7, 0, 2.9, 1.2, 1.2, '#ff2e2e');
    } else {
      pix(-2.7, 0, 2.9, 0.9, 0.9, '#991b1b');
    }
  }
}

export function drawShipEntity(ctx, depthMgr, cam, ship, st, sIdx, worldW, worldH, wScale, mode, tSec) {
  if (!st || !st.visible || st.frac < 0 || st.frac > 1) return false;
  const pos = samplePathAt(ship.pts, st.frac, worldW, worldH, 3);
  if (!pos) return false;

  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';
  const isSteamer = ship.kind === 'zsg_steamer';
  const isMotor = ship.kind === 'motorboat';
  const speedRatio = st.speedRatio;
  const isDocked = st.isDocked;
  const wakeCount = isSteamer ? 14 : (isMotor ? 10 : 6);
  const wakeStep = ship.closed ? 0.0045 : 0.0026;
  const { scale, offsetX, offsetY } = cam;

  if (!isDocked && speedRatio >= 0.03) {
    const sPx = scale * wScale;
    const leftPts = [];
    const rightPts = [];
    const centerPts = [];
    const effWakeCount = Math.max(2, Math.round(wakeCount * (0.35 + 0.65 * speedRatio)));
    const sternBack = (isSteamer ? 32 : (isMotor ? 10 : 7)) * wScale;
    const initSpread = (isSteamer ? 7.5 : (isMotor ? 3.2 : 2.6)) * wScale;
    const wx0 = pos.wx - pos.tx * sternBack;
    const wy0 = pos.wy - pos.ty * sternBack;
    leftPts.push([wx0 * scale + offsetX - pos.ty * initSpread * scale, wy0 * scale + offsetY + pos.tx * initSpread * 0.55 * scale]);
    rightPts.push([wx0 * scale + offsetX + pos.ty * initSpread * scale, wy0 * scale + offsetY - pos.tx * initSpread * 0.55 * scale]);
    centerPts.push([wx0 * scale + offsetX, wy0 * scale + offsetY]);

    for (let k = 1; k <= effWakeCount; k++) {
      const fWake = ship.closed
        ? ((st.frac - k * wakeStep) % 1 + 1) % 1
        : st.frac - k * wakeStep;
      if (fWake <= 0 || fWake >= 1) break;
      const pw = samplePathAt(ship.pts, fWake, worldW, worldH, 3);
      if (!pw) break;
      const spread = (isSteamer ? 8.5 : (isMotor ? 3.8 : 3.0)) + k * (isSteamer ? 2.4 : 1.55) * (0.4 + 0.6 * speedRatio);
      const nx = -pw.ty * spread * wScale;
      const ny = pw.tx * spread * 0.55 * wScale;
      leftPts.push([(pw.wx + nx) * scale + offsetX, (pw.wy + ny) * scale + offsetY]);
      rightPts.push([(pw.wx - nx) * scale + offsetX, (pw.wy - ny) * scale + offsetY]);
      centerPts.push([pw.wx * scale + offsetX, pw.wy * scale + offsetY]);
    }

    ctx.save();
    ctx.lineCap = 'round';
    for (let k = 1; k < leftPts.length; k++) {
      const fade = Math.pow(1 - (k - 1) / Math.max(1, leftPts.length - 1), 1.35);
      const a = (isNight ? 0.34 : (isSunset ? 0.52 : 0.62)) * fade * speedRatio;
      const wCol = isNight
        ? `rgba(148,188,232,${a.toFixed(2)})`
        : (isSunset ? `rgba(255,228,200,${a.toFixed(2)})` : `rgba(232,248,255,${a.toFixed(2)})`);
      ctx.strokeStyle = wCol;
      ctx.lineWidth = Math.max(1.1, (isSteamer ? 2.6 : 1.6) * sPx * (0.55 + 0.55 * fade));
      ctx.beginPath();
      ctx.moveTo(leftPts[k - 1][0], leftPts[k - 1][1]);
      ctx.lineTo(leftPts[k][0], leftPts[k][1]);
      ctx.moveTo(rightPts[k - 1][0], rightPts[k - 1][1]);
      ctx.lineTo(rightPts[k][0], rightPts[k][1]);
      ctx.stroke();

      if ((isSteamer || isMotor) && k <= 7) {
        const pa = a * 0.58;
        ctx.strokeStyle = isNight
          ? `rgba(164,202,240,${pa.toFixed(2)})`
          : (isSunset ? `rgba(255,236,216,${pa.toFixed(2)})` : `rgba(244,253,255,${pa.toFixed(2)})`);
        ctx.lineWidth = Math.max(1.2, (isSteamer ? 4.4 : 2.0) * sPx * fade);
        ctx.beginPath();
        ctx.moveTo(centerPts[k - 1][0], centerPts[k - 1][1]);
        ctx.lineTo(centerPts[k][0], centerPts[k][1]);
        ctx.stroke();
      }
    }
    ctx.restore();

    const bowOff = (isSteamer ? 30 : (isMotor ? 10 : 7)) * wScale;
    const bowA = (isNight ? 0.55 : 0.78) * speedRatio;
    const foamCol = isNight
      ? `rgba(176,208,242,${bowA.toFixed(2)})`
      : `rgba(248,254,255,${bowA.toFixed(2)})`;
    drawPixelRectWorld(ctx, cam, pos.wx + pos.tx * bowOff, pos.wy + pos.ty * bowOff, 3.6, 1.8, foamCol, wScale);
  }

  if (isNight && isSteamer) {
    for (let r = 0; r < 5; r++) {
      const along = (-16 + r * 8) * wScale;
      for (let d = 1; d <= 3; d++) {
        const rx = pos.wx + pos.tx * along + Math.sin(tSec * 3.8 + r * 1.9 + d * 1.3) * 2.4 * wScale;
        const ry = pos.wy + pos.ty * along + (5 + d * 3.4) * wScale;
        const ra = (0.42 - d * 0.10).toFixed(2);
        drawPixelRectWorld(ctx, cam, rx, ry, 4.2, 1.6, `rgba(255,214,112,${ra})`, wScale);
      }
    }
  }

  const bobY = Math.sin(tSec * (isSteamer ? 1.8 : 2.6) + sIdx * 1.9) * (isSteamer ? 0.55 : 0.85) * wScale;
  const angIdx = ((Math.round((Math.atan2(pos.ty, pos.tx) / (Math.PI * 2)) * 32) % 32) + 32) % 32;
  const sp = getVehicleSprite(ship.kind, 0, angIdx, mode);
  const shipBounds = isSteamer
    ? { ex: 108 * wScale, eyUp: 92 * wScale, eyDn: 74 * wScale }
    : (isMotor
      ? { ex: 26 * wScale, eyUp: 28 * wScale, eyDn: 22 * wScale }
      : { ex: 34 * wScale, eyUp: 56 * wScale, eyDn: 24 * wScale });

  depthMgr.drawDepthMasked(ctx, cam, pos.wx, pos.wy, shipBounds, pos.d16, worldW, worldH, (targetCtx) => {
    const sPx = scale * wScale;
    const nx = -pos.ty * 0.72;
    const ny = pos.tx * 0.52;

    if (isSteamer && !isDocked && speedRatio > 0.03) {
      for (const side of [-1, 1]) {
        const baseWx = pos.wx + (pos.tx * 2 + nx * side * 11.5) * wScale;
        const baseWy = pos.wy + bobY + (pos.ty * 2 + ny * side * 11.5) * wScale;
        for (let p = 0; p < 5; p++) {
          const prog = (((tSec * 4.5 * speedRatio + p / 5 + (side > 0 ? 0.3 : 0)) % 1) + 1) % 1;
          const aft = prog * 16.0 * speedRatio * wScale;
          const jLat = Math.sin(tSec * 9.0 + p * 2.1 + side) * 1.4 * wScale;
          const fWx = baseWx - pos.tx * aft + nx * side * jLat;
          const fWy = baseWy - pos.ty * aft + ny * side * jLat + 0.6 * wScale;
          const fa = (1.0 - prog) * speedRatio * (isNight ? 0.52 : 0.84);
          const fCol = isNight
            ? `rgba(182, 214, 246, ${fa.toFixed(2)})`
            : (isSunset ? `rgba(255, 236, 212, ${fa.toFixed(2)})` : `rgba(248, 254, 255, ${fa.toFixed(2)})`);
          drawPixelRectWorld(targetCtx, cam, fWx, fWy, 2.4 + (1 - prog) * 1.6, 1.5, fCol, wScale);
        }
      }
    }

    blitWorldSprite(targetCtx, cam, sp, pos.wx, pos.wy + bobY, wScale);

    if (isSteamer) {
      const funWx = pos.wx + pos.tx * 2 * wScale;
      const funWy = pos.wy + bobY + pos.ty * 2 * wScale - 28.5 * wScale;
      const steamMul = isDocked ? 0.52 : 0.82;
      for (let p = 0; p < 5; p++) {
        const age = (((tSec * 0.42 + p / 5) % 1) + 1) % 1;
        const sWx = funWx - pos.tx * age * (4 + 14 * speedRatio) * wScale + Math.sin(age * 5.0 + p * 1.7) * 1.2 * wScale;
        const sWy = funWy - age * 16 * wScale - pos.ty * age * (2 + 6 * speedRatio) * wScale;
        const sa = (1 - age) * (age < 0.18 ? age / 0.18 : 1.0) * steamMul * (isNight ? 0.55 : 0.72);
        const sz = (isDocked ? 1.8 : 2.2) + age * (isDocked ? 3.2 : 4.5);
        const sCol = isNight
          ? `rgba(168, 186, 216, ${sa.toFixed(2)})`
          : (isSunset ? `rgba(255, 228, 200, ${sa.toFixed(2)})` : `rgba(246, 249, 252, ${sa.toFixed(2)})`);
        drawPixelRectWorld(targetCtx, cam, sWx - sz * 0.5 * wScale, sWy - sz * 0.4 * wScale, sz, sz * 0.72, sCol, wScale);
      }

      if (isSunset || isNight) {
        const navAlpha = isNight ? 0.92 : 0.55;
        const navPts = [
          { s: 18, w: -9.5, z: 19.5, col: '#ff3b3b', glow: 'rgba(255, 59, 59, 0.34)' },
          { s: 18, w: 9.5, z: 19.5, col: '#22e584', glow: 'rgba(34, 229, 132, 0.34)' },
          { s: 22, w: 0, z: 27.5, col: '#fff3c4', glow: 'rgba(255, 243, 196, 0.34)' },
        ];
        if (isNight) {
          navPts.push({ s: -64, w: 0, z: 12.5, col: '#ffe49a', glow: 'rgba(255, 228, 154, 0.30)' });
        }
        const dotSz = Math.max(2, Math.round(2.0 * sPx));
        targetCtx.save();
        for (const nl of navPts) {
          const lx = offsetX + (pos.wx + (pos.tx * nl.s + nx * nl.w) * wScale) * scale;
          const ly = offsetY + (pos.wy + bobY + (pos.ty * nl.s + ny * nl.w - nl.z) * wScale) * scale;
          targetCtx.globalAlpha = navAlpha;
          targetCtx.fillStyle = nl.glow;
          targetCtx.beginPath();
          targetCtx.arc(lx, ly, Math.max(2.6, 4.2 * sPx), 0, Math.PI * 2);
          targetCtx.fill();
          targetCtx.fillStyle = nl.col;
          targetCtx.fillRect(Math.round(lx - dotSz * 0.5), Math.round(ly - dotSz * 0.5), dotSz, dotSz);
        }
        targetCtx.restore();
      }
    }
  }, 6.0);

  return true;
}
