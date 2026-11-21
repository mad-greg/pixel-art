import { createAudioEngine } from './js/audio.js';
import { createDepthManager } from './js/render/depth.js';
import {
  shadeHex,
  draw3DCar,
  draw3DBus,
  draw3DArticulatedBus,
  draw3DTrainUnit,
  draw3DCyclist,
  drawShipEntity,
} from './js/render/vehicles.js';
import {
  drawAmbientEffects,
  drawAtmosphereAndLife,
  drawKilchbergDetails,
  drawMiniPerson,
  drawPreTrainVignettes,
  drawShorelineWaves,
} from './js/render/vignettes.js';
import {
  evalBellState,
  evalShipState,
  evalTrainState,
  samplePathAt,
} from './js/sim/schedule.js';
import { createPedestrianSim, drawPedestrianEntity } from './js/sim/pedestrians.js';
import { createTrafficSim } from './js/sim/traffic.js';

  const canvas = document.getElementById('diorama-canvas');
  const ctx = canvas.getContext('2d');
  const viewport = document.getElementById('viewport');
  const pinsLayer = document.getElementById('pins-layer');
  const loupeCanvas = document.getElementById('loupe-canvas');
  const loupeCtx = loupeCanvas.getContext('2d');
  const minimapBox = document.getElementById('minimap-box');
  const minimapCanvas = document.getElementById('minimap-canvas');
  const minimapCtx = minimapCanvas.getContext('2d');
  const lodStatusEl = document.getElementById('lod-status');

  const urlParams = new URLSearchParams(window.location.search);
  const rawFixedT = urlParams.has('t') ? parseFloat(urlParams.get('t')) : NaN;
  const fixedAnimTime = Number.isFinite(rawFixedT)
    ? Math.max(0, Math.min(1e9, rawFixedT))
    : null;

  const CROPS = [
    { file: '01_lindt_home_of_chocolate.webp', label: 'Lindt Home of Chocolate', lmId: 'lindt_hoc' },
    { file: '02_reformierte_kirche_dorf.webp', label: 'Reformierte Kirche & Graves', lmId: 'reformierte_kirche' },
    { file: '03_bendlikon_harbor_pier.webp', label: 'Bendlikon Pier & Sailboats', lmId: 'bendlikon_pier' },
    { file: '04_bahnhof_kilchberg_weinberg.webp', label: 'Bahnhof & Dorfstrasse Viaduct', lmId: 'bahnhof_stockengut' },
    { file: '05_schooren_seebad.webp', label: 'Schooren & Seebad', lmId: 'schooren_seebad' },
    { file: '06_sanatorium_ridge.webp', label: 'Sanatorium Kilchberg', lmId: 'sanatorium_ridge' },
    { file: '07_st_elisabeth_church.webp', label: 'Kath. Kirche St. Elisabeth', lmId: 'st_elisabeth' },
    { file: '08_cf_meyer_haus.webp', label: 'C.F. Meyer-Haus', lmId: 'cf_meyer_haus' },
    { file: '09_gemeindehaus_alte_landstrasse.webp', label: 'Gemeindehaus & Schulhaus', lmId: 'gemeindehaus_alte_landstr' },
    { file: '10_stockengut_ridge_farm.webp', label: 'Stockengut Ridge Farm', lmId: 'stockengut_farm' },
  ];

  const ASSET_VER = '9.0';

  // Overview images, ultra-high-res 0.25 m/px tile pyramids & 16-bit 3D Depth Manager
  const overviewImages = {};
  const tileManifests = {};   // mode -> { width, height, tileSize, cols, rows, mpp } | null
  const tileCache = {};       // "mode:c:r" -> HTMLImageElement | 'loading' | 'error'
  const depthMgr = createDepthManager();
  let trafficSim = null;
  let pedSim = null;
  let lastSimSnapshot = null;

  let currentMode = 'day';
  let meta = null;
  let animData = null;

  // World space = full-resolution diorama pixel space (either tileManifest width/height or overview width/height)
  let scale = 0.25;
  let offsetX = 0;
  let offsetY = 0;

  let showAnimations = true;
  let showPins = true;
  let showLoupe = false;
  let wheelMode = 'zoom'; // 'zoom' | 'pan'
  let lastMouse = { x: 0, y: 0 };
  let drawScheduled = false;

  // HiDPI: the canvas backing store is `dpr` x its CSS size (capped at 2 for 60 fps pixel-art rendering).
  // All camera maths (scale, offsets, hit radii) run in backing-store ("device") pixels; the user-facing
  // zoom (readout, URL, debug, presets) is expressed in CSS pixels per world pixel = scale / dpr.
  const DPR_CAP = 2;
  let dpr = 1;
  let activeLandmarkId = null;
  let selectedBuilding = null;
  let selectedEntity = null;
  let lastHitTestEntities = [];
  let pointerDownFollow = null;
  let searchResultCount = 0;
  let camAnim = null;
  const renderStamps = [];

  function getDeviceRatio() {
    return Math.max(1, Math.min(DPR_CAP, window.devicePixelRatio || 1));
  }
  function cssScale() {
    return scale / dpr;
  }

  function getWorldSize() {
    const mf = tileManifests[currentMode];
    if (mf && mf.width && mf.height) {
      return { width: mf.width, height: mf.height, tiled: true, mf };
    }
    const ov = overviewImages[currentMode];
    if (ov) {
      return { width: ov.width, height: ov.height, tiled: false, mf: null };
    }
    return { width: 4462, height: 2146, tiled: false, mf: null };
  }

  function scheduleDraw() {
    if (!drawScheduled) {
      drawScheduled = true;
      requestAnimationFrame(() => {
        drawScheduled = false;
        draw();
      });
    }
  }

  function loadModeOverview(mode) {
    if (overviewImages[mode]) return Promise.resolve(overviewImages[mode]);
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        overviewImages[mode] = img;
        resolve(img);
      };
      img.onerror = () => resolve(null);
      img.src = `assets/diorama_${mode}.webp?v=${ASSET_VER}`;
    });
  }

  function loadTileManifest(mode) {
    if (mode in tileManifests) return Promise.resolve(tileManifests[mode]);
    return fetch(`assets/tiles/${mode}/manifest.json?v=${ASSET_VER}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        tileManifests[mode] = data;
        if (data && data.mpp) {
          const fidEl = document.getElementById('spec-fidelity');
          if (fidEl) fidEl.textContent = `${Math.round(data.mpp * 100)} cm/px · ${data.width.toLocaleString()}×${data.height.toLocaleString()}`;
        }
        return data;
      })
      .catch(() => {
        tileManifests[mode] = null;
        return null;
      });
  }

  function requestTile(mode, col, row) {
    const key = `${mode}:${col}:${row}`;
    if (tileCache[key]) return tileCache[key];
    tileCache[key] = 'loading';
    const img = new Image();
    img.onload = () => {
      tileCache[key] = img;
      scheduleDraw();
    };
    img.onerror = () => {
      tileCache[key] = 'error';
    };
    img.src = `assets/tiles/${mode}/${col}_${row}.webp?v=${ASSET_VER}`;
    return 'loading';
  }

  function clampOffsets() {
    const { width, height } = getWorldSize();
    const scaledW = width * scale;
    const scaledH = height * scale;
    const marginX = Math.max(120, canvas.width * 0.25);
    const marginY = Math.max(120, canvas.height * 0.25);
    const minX = canvas.width - scaledW - marginX;
    const maxX = marginX;
    const minY = canvas.height - scaledH - marginY;
    const maxY = marginY;
    if (scaledW + marginX * 2 <= canvas.width) {
      offsetX = (canvas.width - scaledW) * 0.5;
    } else {
      offsetX = Math.min(maxX, Math.max(minX, offsetX));
    }
    if (scaledH + marginY * 2 <= canvas.height) {
      offsetY = (canvas.height - scaledH) * 0.5;
    } else {
      offsetY = Math.min(maxY, Math.max(minY, offsetY));
    }
  }

  function resizeViewport() {
    const rect = viewport.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return;
    const nd = getDeviceRatio();
    const newW = Math.max(1, Math.round(rect.width * nd));
    const newH = Math.max(1, Math.round(rect.height * nd));
    const sizeChanged = canvas.width !== newW || canvas.height !== newH || nd !== dpr;
    if (sizeChanged) {
      // Keep the world point under the viewport centre (and the CSS zoom) stable across resizes / DPR changes.
      const { width, height } = getWorldSize();
      const prevW = canvas.width;
      const prevH = canvas.height;
      const haveCam = scale > 0 && width > 0 && prevW > 300;
      const cwx = haveCam ? (prevW * 0.5 - offsetX) / scale : 0;
      const cwy = haveCam ? (prevH * 0.5 - offsetY) / scale : 0;
      scale = scale * nd / dpr;
      dpr = nd;
      canvas.width = newW;
      canvas.height = newH;
      if (haveCam) {
        offsetX = newW * 0.5 - cwx * scale;
        offsetY = newH * 0.5 - cwy * scale;
        clampOffsets();
      }
      updateZoomReadout();
    }
    const tb = document.getElementById('topbar');
    if (tb) document.documentElement.style.setProperty('--topbar-h', `${Math.round(tb.getBoundingClientRect().height)}px`);
    sizeMinimap();
    draw();
  }

  function getCenterUV() {
    const { width, height } = getWorldSize();
    const u = (width > 0 && scale > 0) ? (canvas.width * 0.5 - offsetX) / (width * scale) : 0.5;
    const v = (height > 0 && scale > 0) ? (canvas.height * 0.5 - offsetY) / (height * scale) : 0.5;
    return { u, v };
  }

  function clampScale(sc) {
    const { width } = getWorldSize();
    const minScale = Math.min(0.06 * dpr, (canvas.width * 0.5) / Math.max(1, width));
    const maxScale = 8.0 * dpr; // Up to 8x magnification of native 25 cm pixels (CSS px)
    return Math.min(maxScale, Math.max(minScale, sc));
  }

  // F24: cubic ease-out camera flight (log-space zoom + linear centre) shared by landmarks, presets & search.
  function stepCameraAnim(nowMs) {
    const a = camAnim;
    if (!a) return;
    const { width, height } = getWorldSize();
    const k = Math.min(1, Math.max(0, (nowMs - a.t0) / a.ms));
    const e = 1 - Math.pow(1 - k, 3);
    const sc = Math.exp(Math.log(a.s0) + (Math.log(a.s1) - Math.log(a.s0)) * e);
    if (a.keepCentre) {
      const wx = (canvas.width * 0.5 - offsetX) / scale;
      const wy = (canvas.height * 0.5 - offsetY) / scale;
      scale = sc;
      offsetX = canvas.width * 0.5 - wx * scale;
      offsetY = canvas.height * 0.5 - wy * scale;
    } else {
      const cu = a.u0 + (a.u1 - a.u0) * e;
      const cv = a.v0 + (a.v1 - a.v0) * e;
      scale = sc;
      offsetX = canvas.width * 0.5 - cu * width * scale;
      offsetY = canvas.height * 0.5 - cv * height * scale;
    }
    clampOffsets();
    updateZoomReadout();
    scheduleDraw();
    if (k < 1) {
      requestAnimationFrame(stepCameraAnim);
    } else {
      camAnim = null;
    }
  }

  function animateCamera(targetScale, cu, cv, ms, keepCentre = false) {
    const { width, height } = getWorldSize();
    if (!width || !height) return;
    const s1 = clampScale(targetScale);
    const c0 = getCenterUV();
    const instant = !(ms > 0) || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    if (instant) {
      camAnim = null;
      scale = s1;
      offsetX = canvas.width * 0.5 - cu * width * scale;
      offsetY = canvas.height * 0.5 - cv * height * scale;
      clampOffsets();
      updateZoomReadout();
      scheduleDraw();
      return;
    }
    const wasRunning = !!camAnim;
    camAnim = { t0: performance.now(), ms, s0: scale, s1, u0: c0.u, v0: c0.v, u1: cu, v1: cv, keepCentre };
    if (!wasRunning) requestAnimationFrame(stepCameraAnim);
  }

  function pendingScale() {
    return camAnim ? camAnim.s1 : scale;
  }

  function zoomPreset(cssZoom) {
    if (followTarget) {
      scale = clampScale(cssZoom * dpr);
      updateZoomReadout();
      scheduleDraw();
      return;
    }
    const c = camAnim && !camAnim.keepCentre ? { u: camAnim.u1, v: camAnim.v1 } : getCenterUV();
    animateCamera(cssZoom * dpr, c.u, c.v, 340);
  }

  function zoomStep(factor) {
    const c = camAnim && !camAnim.keepCentre ? { u: camAnim.u1, v: camAnim.v1 } : getCenterUV();
    animateCamera(pendingScale() * factor, c.u, c.v, followTarget ? 0 : 240, !!followTarget);
  }

  function fitToScreen(animate = true) {
    if (followTarget) setFollowMode(null);
    const { width, height } = getWorldSize();
    if (!width || !height) return;
    const pad = 20 * dpr;
    const sx = (canvas.width - pad * 2) / width;
    const sy = (canvas.height - pad * 2) / height;
    const target = Math.min(sx, sy);
    if (animate && canvas.width > 300) {
      animateCamera(target, 0.5, 0.5, 340);
      return;
    }
    camAnim = null;
    scale = target;
    offsetX = Math.round((canvas.width - width * scale) * 0.5);
    offsetY = Math.round((canvas.height - height * scale) * 0.5);
    updateZoomReadout();
    scheduleDraw();
  }

  function zoomAt(factor, cx, cy, exactScale = null) {
    const { width, height } = getWorldSize();
    if (!width || !height) return;
    camAnim = null;
    const prevScale = scale;
    scale = exactScale !== null
      ? clampScale(exactScale * dpr)
      : clampScale(scale * factor);

    const wx = (cx - offsetX) / prevScale;
    const wy = (cy - offsetY) / prevScale;
    offsetX = cx - wx * scale;
    offsetY = cy - wy * scale;
    clampOffsets();
    updateZoomReadout();
    scheduleDraw();
  }

  function panBy(dx, dy) {
    if (followTarget) setFollowMode(null);
    camAnim = null;
    offsetX += dx;
    offsetY += dy;
    clampOffsets();
    scheduleDraw();
  }

  function updateZoomReadout() {
    const el = document.getElementById('zoom-readout');
    if (el) {
      const cs = cssScale();
      if (cs >= 0.98) {
        const rounded = Math.abs(cs - Math.round(cs)) < 0.03 ? Math.round(cs) : cs.toFixed(2);
        el.textContent = `${rounded}× px`;
      } else {
        el.textContent = `${Math.round(cs * 100)}%`;
      }
    }
    updateScaleBar();
  }

  // Dynamic metric scale bar (nice 1-2-5 lengths, 64–150 CSS px wide) from the true ground resolution.
  function updateScaleBar() {
    const bar = document.getElementById('scale-bar-line');
    const label = document.getElementById('scale-bar-label');
    if (!bar || !label) return;
    const mf = tileManifests[currentMode];
    const world = getWorldSize();
    const mpp = (mf && mf.mpp ? mf.mpp : 0.25) * (mf && mf.width ? 1 : 12331 / Math.max(1, world.width));
    const metresPerCssPx = mpp / Math.max(1e-6, cssScale());
    const minM = metresPerCssPx * 64;
    const pow = Math.pow(10, Math.floor(Math.log10(minM)));
    let nice = pow;
    for (const m of [1, 2, 5, 10]) {
      if (m * pow >= minM) { nice = m * pow; break; }
    }
    const px = nice / metresPerCssPx;
    bar.style.width = `${Math.round(px)}px`;
    label.textContent = nice >= 1000 ? `${nice / 1000} km` : `${nice} m`;
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const ov = overviewImages[currentMode];
    const { width, height, tiled, mf } = getWorldSize();
    if (!ov && !tiled) return;

    const destX = Math.round(offsetX);
    const destY = Math.round(offsetY);
    const destW = Math.round(width * scale);
    const destH = Math.round(height * scale);

    // 1. Always draw exact 2:1 LANCZOS overview image underneath (zero blank flashes & identical colors!)
    ctx.imageSmoothingQuality = 'high';
    if (ov) {
      const ovRatio = width / ov.width;
      ctx.imageSmoothingEnabled = (scale * ovRatio) < 0.95;
      ctx.drawImage(ov, destX, destY, destW, destH);
    }

    // 2. Stream ultra-crisp 0.25 m/px lossless WebP tiles seamlessly once zoomed past 2:1 overview density (~50%)!
    let tilesLoaded = 0;
    let tilesVisible = 0;
    const ovWidth = ov ? ov.width : 0;
    const needTiles = tiled && mf && (!ov || (width * scale) > ovWidth * 0.98);

    if (needTiles) {
      const ts = mf.tileSize;
      const c0 = Math.max(0, Math.floor((-offsetX / scale) / ts));
      const c1 = Math.min(mf.cols - 1, Math.floor(((canvas.width - offsetX) / scale) / ts));
      const r0 = Math.max(0, Math.floor((-offsetY / scale) / ts));
      const r1 = Math.min(mf.rows - 1, Math.floor(((canvas.height - offsetY) / scale) / ts));

      ctx.imageSmoothingEnabled = scale < 0.95;
      for (let r = r0; r <= r1; r++) {
        for (let c = c0; c <= c1; c++) {
          tilesVisible++;
          const tImg = requestTile(currentMode, c, r);
          if (tImg && tImg !== 'loading' && tImg !== 'error') {
            tilesLoaded++;
            const sxWorld = c * ts;
            const syWorld = r * ts;
            const tx0 = Math.round(offsetX + sxWorld * scale);
            const ty0 = Math.round(offsetY + syWorld * scale);
            const tx1 = Math.round(offsetX + (sxWorld + tImg.width) * scale);
            const ty1 = Math.round(offsetY + (syWorld + tImg.height) * scale);
            ctx.drawImage(tImg, tx0, ty0, tx1 - tx0, ty1 - ty0);
          }
        }
      }
    }

    if (lodStatusEl) {
      if (needTiles) {
        const mppStr = mf.mpp ? `${Math.round(mf.mpp * 100)} cm/px` : 'HD';
        lodStatusEl.textContent = tilesLoaded < tilesVisible
          ? `Streaming ${mppStr} HD Tiles (${tilesLoaded}/${tilesVisible})…`
          : `Ultra-HD ${mppStr} Pixel Art Active (${scale >= 1 ? scale.toFixed(1) + '×' : Math.round(scale * 100) + '%'})`;
      } else {
        lodStatusEl.textContent = 'Drag / Arrows to Pan · Scroll / Pinch to Zoom Close';
      }
    }

    if (animData) {
      const animSec = getAnimTimeSec();
      const liveSnap = (lastSimSnapshot && lastSimSnapshot.mode === currentMode) ? lastSimSnapshot : null;
      if (pedSim) {
        pedSim.updateToTime(animSec, currentMode, liveSnap);
      }
      if (trafficSim) {
        const cwOcc = pedSim ? pedSim.getOccupiedCrosswalks() : null;
        if (pedSim) trafficSim.setExternalPedestrianStats(pedSim.getStats());
        lastSimSnapshot = trafficSim.updateToTime(animSec, currentMode, cwOcc);
      }
      if (showAnimations) {
        drawAnimations(width, height, animSec);
      }
    }

    drawSelectionMarker(width, height);
    updatePins(width, height);
    drawMinimap(ov, width, height);
    if (showLoupe) drawLoupe(ov, width, height, tiled, mf);

    const nowStamp = performance.now();
    renderStamps.push(nowStamp);
    while (renderStamps.length && nowStamp - renderStamps[0] > 1000) renderStamps.shift();
  }

  // Gold diamond reticle on inspected building, or teal tracking reticle on inspected moving entity.
  function drawSelectionMarker(worldW, worldH) {
    if (selectedBuilding) {
      const sx = Math.round(offsetX + selectedBuilding.u * worldW * scale);
      const sy = Math.round(offsetY + selectedBuilding.v * worldH * scale);
      if (sx < -20 || sx > canvas.width + 20 || sy < -20 || sy > canvas.height + 20) return;
      const r = Math.round(7 * dpr);
      ctx.save();
      ctx.lineWidth = Math.max(1, Math.round(1.5 * dpr));
      ctx.strokeStyle = '#0d1420';
      ctx.beginPath();
      ctx.moveTo(sx, sy - r - 1); ctx.lineTo(sx + (r + 1) * 1.6, sy); ctx.lineTo(sx, sy + r + 1); ctx.lineTo(sx - (r + 1) * 1.6, sy); ctx.closePath();
      ctx.stroke();
      ctx.strokeStyle = '#e2b45b';
      ctx.lineWidth = Math.max(1, Math.round(dpr));
      ctx.beginPath();
      ctx.moveTo(sx, sy - r); ctx.lineTo(sx + r * 1.6, sy); ctx.lineTo(sx, sy + r); ctx.lineTo(sx - r * 1.6, sy); ctx.closePath();
      ctx.stroke();
      ctx.restore();
      return;
    }
    if (selectedEntity && showAnimations) {
      const live = lastHitTestEntities.find((e) => e.id === selectedEntity.id) || selectedEntity;
      if (!live || !Number.isFinite(live.wx) || !Number.isFinite(live.wy)) return;
      const sx = Math.round(offsetX + live.wx * scale);
      const sy = Math.round(offsetY + live.wy * scale);
      if (sx < -24 || sx > canvas.width + 24 || sy < -24 || sy > canvas.height + 24) return;
      const r = Math.round(6.5 * dpr);
      ctx.save();
      ctx.lineWidth = Math.max(1, Math.round(1.5 * dpr));
      ctx.strokeStyle = '#0d1420';
      ctx.beginPath();
      ctx.moveTo(sx, sy - r - 1); ctx.lineTo(sx + (r + 1) * 1.5, sy); ctx.lineTo(sx, sy + r + 1); ctx.lineTo(sx - (r + 1) * 1.5, sy); ctx.closePath();
      ctx.stroke();
      ctx.strokeStyle = '#48b8c0';
      ctx.lineWidth = Math.max(1, Math.round(dpr));
      ctx.beginPath();
      ctx.moveTo(sx, sy - r); ctx.lineTo(sx + r * 1.5, sy); ctx.lineTo(sx, sy + r); ctx.lineTo(sx - r * 1.5, sy); ctx.closePath();
      ctx.stroke();
      ctx.restore();
    }
  }

  let pinFontsHooked = false;
  function updatePins(worldW, worldH) {
    if (!meta || !showPins) {
      if (pinsLayer.children.length) pinsLayer.innerHTML = '';
      return;
    }
    const n = meta.landmarks.length;
    if (pinsLayer.children.length !== n) {
      pinsLayer.innerHTML = '';
      for (let idx = 0; idx < n; idx++) {
        const lm = meta.landmarks[idx];
        const btn = document.createElement('button');
        btn.className = 'lm-pin';
        btn.dataset.lmIdx = String(idx);
        btn.textContent = `${idx + 1}. ${lm.name.split('&')[0].trim()}`;
        pinsLayer.appendChild(btn);
      }
      // Single batched intrinsic measurement pass (zero per-frame layout thrash)
      for (let i = 0; i < pinsLayer.children.length; i++) {
        const btn = pinsLayer.children[i];
        if (btn.offsetWidth > 0 && btn.offsetHeight > 0) {
          btn._w = btn.offsetWidth;
          btn._h = btn.offsetHeight;
          btn._measured = true;
        } else {
          btn._w = Math.max(76, Math.ceil(btn.textContent.length * 7.2 + 18));
          btn._h = 24;
          btn._measured = false;
        }
      }
      if (!pinFontsHooked && document.fonts && document.fonts.ready) {
        pinFontsHooked = true;
        document.fonts.ready.then(() => {
          for (let i = 0; i < pinsLayer.children.length; i++) {
            pinsLayer.children[i]._measured = false;
          }
          scheduleDraw();
        });
      }
    }

    const cssW = canvas.width / dpr;
    const cssH = canvas.height / dpr;
    const declutter = cssScale() < 0.7;
    const coords = new Array(n);
    let activeIdx = -1;
    for (let idx = 0; idx < n; idx++) {
      const lm = meta.landmarks[idx];
      const pin = pinsLayer.children[idx];
      if (!pin._measured && pin.style.display === 'block' && pin.offsetWidth > 0 && pin.offsetHeight > 0) {
        pin._w = pin.offsetWidth;
        pin._h = pin.offsetHeight;
        pin._measured = true;
      }
      if (lm.id === activeLandmarkId) activeIdx = idx;
      const sx = (offsetX + lm.uv[0] * worldW * scale) / dpr;
      const sy = (offsetY + lm.uv[1] * worldH * scale) / dpr;
      const onScreen = !(sx < -100 || sx > cssW + 100 || sy < -40 || sy > cssH + 50);
      coords[idx] = { sx, sy, onScreen };
    }

    const hiddenByDeclutter = new Uint8Array(n);
    if (declutter) {
      const PAD_X = 6;
      const PAD_Y = 6;
      const order = [];
      if (activeIdx >= 0) order.push(activeIdx);
      for (let i = 0; i < n; i++) {
        if (i !== activeIdx) order.push(i);
      }
      const placed = [];
      for (let oi = 0; oi < order.length; oi++) {
        const idx = order[oi];
        const c = coords[idx];
        if (!c.onScreen) continue;
        const pin = pinsLayer.children[idx];
        const w = pin._w || 120;
        const h = pin._h || 24;
        const box = {
          left: c.sx - w * 0.5 - PAD_X,
          right: c.sx + w * 0.5 + PAD_X,
          top: c.sy - h - PAD_Y,
          bottom: c.sy + PAD_Y,
        };
        if (idx === activeIdx) {
          placed.push(box);
          continue;
        }
        let hit = false;
        for (let pi = 0; pi < placed.length; pi++) {
          const b = placed[pi];
          if (box.left < b.right && box.right > b.left && box.top < b.bottom && box.bottom > b.top) {
            hit = true;
            break;
          }
        }
        if (hit) hiddenByDeclutter[idx] = 1;
        else placed.push(box);
      }
    }

    for (let idx = 0; idx < n; idx++) {
      const pin = pinsLayer.children[idx];
      const lm = meta.landmarks[idx];
      const { sx, sy, onScreen } = coords[idx];
      const isDecluttered = declutter && hiddenByDeclutter[idx] === 1;
      const vis = onScreen && !isDecluttered;
      // Dirty-check so panning/animating never rewrites unchanged pins (avoids layout churn).
      const key = vis ? `${Math.round(sx * 2)}|${Math.round(sy * 2)}` : (isDecluttered ? 'decluttered' : 'hidden');
      if (pin._key !== key) {
        pin._key = key;
        if (vis) {
          pin.style.left = `${sx}px`;
          pin.style.top = `${sy}px`;
          pin.style.display = 'block';
        } else {
          pin.style.display = 'none';
        }
      }
      if (pin._decluttered !== isDecluttered) {
        pin._decluttered = isDecluttered;
        pin.classList.toggle('decluttered', isDecluttered);
      }
      const isActive = lm.id === activeLandmarkId;
      if (pin._active !== isActive) {
        pin._active = isActive;
        pin.classList.toggle('active', isActive);
      }
    }
  }

  // Minimap: cache the scaled overview once per mode/size; each frame only paints the viewport box.
  let minimapBase = null;
  function sizeMinimap() {
    const rect = minimapCanvas.getBoundingClientRect();
    const cssW = rect.width || 220;
    const cssH = rect.height || 106;
    const w = Math.max(2, Math.round(cssW * dpr));
    const h = Math.max(2, Math.round(cssH * dpr));
    if (minimapCanvas.width !== w || minimapCanvas.height !== h) {
      minimapCanvas.width = w;
      minimapCanvas.height = h;
      minimapBase = null;
    }
  }

  function drawMinimap(ov, worldW, worldH) {
    if (!minimapCtx || !ov) return;
    const mw = minimapCanvas.width;
    const mh = minimapCanvas.height;
    if (!minimapBase || minimapBase.mode !== currentMode || minimapBase.w !== mw || minimapBase.h !== mh || minimapBase.ov !== ov) {
      const off = document.createElement('canvas');
      off.width = mw;
      off.height = mh;
      const octx = off.getContext('2d');
      octx.fillStyle = '#101724';
      octx.fillRect(0, 0, mw, mh);
      octx.imageSmoothingEnabled = true;
      octx.imageSmoothingQuality = 'high';
      octx.drawImage(ov, 0, 0, mw, mh);
      minimapBase = { mode: currentMode, w: mw, h: mh, ov, canvas: off };
    }
    minimapCtx.drawImage(minimapBase.canvas, 0, 0);

    // Viewport indicator box
    const vx0 = (-offsetX / (worldW * scale)) * mw;
    const vy0 = (-offsetY / (worldH * scale)) * mh;
    const vw = (canvas.width / (worldW * scale)) * mw;
    const vh = (canvas.height / (worldH * scale)) * mh;

    minimapCtx.strokeStyle = '#e2b45b';
    minimapCtx.lineWidth = 1.6 * dpr;
    minimapCtx.strokeRect(
      Math.max(1, vx0),
      Math.max(1, vy0),
      Math.min(mw - 2, vw),
      Math.min(mh - 2, vh)
    );
  }

  function drawLoupe(ov, worldW, worldH, tiled, mf) {
    const mag = 6;
    const lw = loupeCanvas.width;
    const lh = loupeCanvas.height;
    const srcSpan = Math.floor(lw / mag);
    const wxCenter = (lastMouse.x - offsetX) / scale;
    const wyCenter = (lastMouse.y - offsetY) / scale;
    const sx0 = Math.floor(wxCenter - srcSpan / 2);
    const sy0 = Math.floor(wyCenter - srcSpan / 2);

    loupeCtx.fillStyle = '#0f1520';
    loupeCtx.fillRect(0, 0, lw, lh);
    loupeCtx.imageSmoothingEnabled = false;

    if (tiled && mf) {
      const ts = mf.tileSize;
      const c0 = Math.max(0, Math.floor(sx0 / ts));
      const c1 = Math.min(mf.cols - 1, Math.floor((sx0 + srcSpan) / ts));
      const r0 = Math.max(0, Math.floor(sy0 / ts));
      const r1 = Math.min(mf.rows - 1, Math.floor((sy0 + srcSpan) / ts));
      let drewAll = true;
      for (let r = r0; r <= r1; r++) {
        for (let c = c0; c <= c1; c++) {
          const tImg = requestTile(currentMode, c, r);
          if (tImg && tImg !== 'loading' && tImg !== 'error') {
            const dx = (c * ts - sx0) * mag;
            const dy = (r * ts - sy0) * mag;
            loupeCtx.drawImage(tImg, dx, dy, tImg.width * mag, tImg.height * mag);
          } else {
            drewAll = false;
          }
        }
      }
      if (!drewAll && ov) {
        const rx = ov.width / worldW;
        const ry = ov.height / worldH;
        loupeCtx.drawImage(ov, sx0 * rx, sy0 * ry, srcSpan * rx, srcSpan * ry, 0, 0, lw, lh);
      }
    } else if (ov) {
      loupeCtx.drawImage(ov, sx0, sy0, srcSpan, srcSpan, 0, 0, lw, lh);
    }

    loupeCtx.strokeStyle = 'rgba(255,255,255,0.09)';
    loupeCtx.lineWidth = 1;
    for (let p = 0; p < lw; p += mag) {
      loupeCtx.beginPath();
      loupeCtx.moveTo(p, 0);
      loupeCtx.lineTo(p, lh);
      loupeCtx.stroke();
      loupeCtx.beginPath();
      loupeCtx.moveTo(0, p);
      loupeCtx.lineTo(lw, p);
      loupeCtx.stroke();
    }
    const lx = Math.min(canvas.width / dpr - lw - 16, Math.max(14, lastMouse.x / dpr + 22));
    const ly = Math.min(canvas.height / dpr - lh - 16, Math.max(14, lastMouse.y / dpr - lw * 0.5));
    loupeCanvas.style.left = `${lx}px`;
    loupeCanvas.style.top = `${ly}px`;
  }

  function setActiveLandmark(id) {
    activeLandmarkId = id;
    document.querySelectorAll('#landmark-list .lm-item').forEach((el) => {
      const on = el.dataset.lmId === id;
      el.classList.toggle('active', on);
      if (on) el.setAttribute('aria-current', 'true');
      else el.removeAttribute('aria-current');
    });
  }

  function flyToLandmark(lm, targetZoom = null, instant = false) {
    if (followTarget) setFollowMode(null);
    const { width, height, tiled } = getWorldSize();
    if (!width || !height) return;
    // Zoom closely so individual windows, roof tiles, trees & boats are crisp (target is CSS px per world px)
    const zoomCss = targetZoom !== null ? targetZoom : (tiled ? 1.5 : 2.2);
    selectedBuilding = null;
    selectedEntity = null;
    setActiveLandmark(lm.id);
    animateCamera(zoomCss * dpr, lm.uv[0], lm.uv[1], instant ? 0 : 640);
    showInspector({
      title: lm.name,
      sub: lm.subtitle,
      specs: [
        ['Category', lm.category],
        ['LV95 Easting', `E ${Math.round(lm.e).toLocaleString('de-CH')}`],
        ['LV95 Northing', `N ${Math.round(lm.n).toLocaleString('de-CH')}`],
        ['Crest Elevation', `${lm.z.toFixed(1)} m a.s.l.`],
      ],
    });
    if (instant) draw();
  }

  function cycleLandmark(delta) {
    if (!meta || !Array.isArray(meta.landmarks) || meta.landmarks.length === 0) return;
    const len = meta.landmarks.length;
    const curIdx = activeLandmarkId ? meta.landmarks.findIndex((l) => l.id === activeLandmarkId) : -1;
    const nextIdx = curIdx < 0
      ? (delta > 0 ? 0 : len - 1)
      : (curIdx + delta + len) % len;
    flyToLandmark(meta.landmarks[nextIdx]);
  }

  function showInspector({ title, sub, specs }) {
    document.getElementById('insp-title').textContent = title;
    document.getElementById('insp-sub').textContent = sub;
    const dl = document.getElementById('insp-specs');
    dl.innerHTML = specs
      .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
      .join('');
  }

  function selectEntity(ent) {
    selectedEntity = ent;
    selectedBuilding = null;
    showInspector({
      title: ent.title,
      sub: ent.sub,
      specs: ent.specs,
    });
    scheduleDraw();
  }

  function selectBuilding(best) {
    selectedBuilding = best;
    selectedEntity = null;
    document.getElementById('coord-lv95').textContent = `LV95 E ${best.e.toLocaleString('de-CH')} · N ${best.n.toLocaleString('de-CH')}`;
    document.getElementById('coord-elev').textContent = `Ground ${best.zg} m · Roof ${best.zr} m`;
    showInspector({
      title: best.addr || `${best.type} (${best.nb})`,
      sub: `Neighbourhood: ${best.nb} · swisstopo LOD2 Class: ${best.type}`,
      specs: [
        ['Ground Elev.', `${best.zg.toFixed(1)} m a.s.l.`],
        ['Roof Ridge', `${best.zr.toFixed(1)} m (+${best.h.toFixed(1)} m)`],
        ['LV95 Coords', `${best.e}, ${best.n}`],
        ['SWISSIMAGE RGB', `rgb(${best.rgb.join(', ')})`],
      ],
    });
    scheduleDraw();
  }

  function hitTestEntity(clientX, clientY, wasFollowing) {
    if (!showAnimations || (!wasFollowing && cssScale() < 0.85) || lastHitTestEntities.length === 0) return false;
    const rect = viewport.getBoundingClientRect();
    const clickX = clientX - rect.left;
    const clickY = clientY - rect.top;
    let best = null;
    let bestDist = Infinity;
    for (let i = 0; i < lastHitTestEntities.length; i++) {
      const ent = lastHitTestEntities[i];
      const sx = (offsetX + ent.wx * scale) / dpr;
      const sy = (offsetY + ent.wy * scale) / dpr;
      const dist = Math.hypot(sx - clickX, sy - clickY);
      const isFollowedKind = wasFollowing && ent.kind === wasFollowing;
      const maxR = isFollowedKind ? Math.max(ent.radiusCss, 32) : ent.radiusCss;
      if (dist <= maxR && dist < bestDist) {
        bestDist = dist;
        best = ent;
      }
    }
    if (!best) return false;
    selectEntity(best);
    return true;
  }

  function hitTestBuilding(clientX, clientY) {
    if (!meta) return;
    const { width, height } = getWorldSize();
    const rect = viewport.getBoundingClientRect();
    const mx = (clientX - rect.left) * dpr;
    const my = (clientY - rect.top) * dpr;
    const u = (mx - offsetX) / (width * scale);
    const v = (my - offsetY) / (height * scale);
    if (u < 0 || u > 1 || v < 0 || v > 1) return;

    let best = null;
    let bestD2 = 0.00028;
    for (const b of meta.buildings) {
      const du = b.u - u;
      const dv = b.v - v;
      const d2 = du * du + dv * dv;
      if (d2 < bestD2) {
        bestD2 = d2;
        best = b;
      }
    }
    if (best) selectBuilding(best);
  }

  // ---------------------------------------------------------------------------
  // Bulletproof Unified Pointer Pan + Multi-Touch Pinch Zoom + Minimap Drag
  // ---------------------------------------------------------------------------
  const activePointers = new Map();
  let gestureMovedDist = 0;
  let downTarget = null;

  viewport.addEventListener('contextmenu', (e) => e.preventDefault());

  viewport.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.viewport-ui') || e.target.closest('.exit-cinema-btn')) return;
    pointerDownFollow = followTarget;
    if (followTarget) setFollowMode(null);
    camAnim = null;
    e.preventDefault();
    viewport.focus({ preventScroll: true });
    if (activePointers.size === 0) {
      gestureMovedDist = 0;
      downTarget = e.target;
    }
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try {
      viewport.setPointerCapture(e.pointerId);
    } catch (_) {}
  });

  viewport.addEventListener('pointermove', (e) => {
    const rect = viewport.getBoundingClientRect();
    lastMouse = { x: (e.clientX - rect.left) * dpr, y: (e.clientY - rect.top) * dpr };

    if (!activePointers.has(e.pointerId)) {
      if (showLoupe) scheduleDraw();
      return;
    }
    e.preventDefault();

    if (activePointers.size === 1) {
      const prev = activePointers.get(e.pointerId);
      const dx = e.clientX - prev.x;
      const dy = e.clientY - prev.y;
      prev.x = e.clientX;
      prev.y = e.clientY;
      gestureMovedDist += Math.hypot(dx, dy);
      if (gestureMovedDist > 3) {
        viewport.classList.add('is-dragging');
      }
      panBy(dx * dpr, dy * dpr);
    } else if (activePointers.size >= 2) {
      const pts = Array.from(activePointers.entries());
      const [idA, pA] = pts[0];
      const [idB, pB] = pts[1];
      const prevMidX = (pA.x + pB.x) * 0.5;
      const prevMidY = (pA.y + pB.y) * 0.5;
      const prevDist = Math.max(8, Math.hypot(pB.x - pA.x, pB.y - pA.y));

      const cur = activePointers.get(e.pointerId);
      cur.x = e.clientX;
      cur.y = e.clientY;

      const qA = activePointers.get(idA);
      const qB = activePointers.get(idB);
      const newMidX = (qA.x + qB.x) * 0.5;
      const newMidY = (qA.y + qB.y) * 0.5;
      const newDist = Math.max(8, Math.hypot(qB.x - qA.x, qB.y - qA.y));

      gestureMovedDist += 20;
      viewport.classList.add('is-dragging');
      offsetX += (newMidX - prevMidX) * dpr;
      offsetY += (newMidY - prevMidY) * dpr;
      zoomAt(newDist / prevDist, (newMidX - rect.left) * dpr, (newMidY - rect.top) * dpr);
    }
  });

  function finishPointer(e) {
    if (!activePointers.has(e.pointerId)) return;
    activePointers.delete(e.pointerId);
    try {
      viewport.releasePointerCapture(e.pointerId);
    } catch (_) {}
    if (activePointers.size === 0) {
      viewport.classList.remove('is-dragging');
      if (gestureMovedDist < 5) {
        const pinEl = downTarget && downTarget.closest ? downTarget.closest('.lm-pin') : null;
        if (pinEl && meta) {
          const idx = Number(pinEl.dataset.lmIdx);
          if (meta.landmarks[idx]) flyToLandmark(meta.landmarks[idx]);
        } else if (!hitTestEntity(e.clientX, e.clientY, pointerDownFollow)) {
          hitTestBuilding(e.clientX, e.clientY);
        }
      }
      downTarget = null;
      pointerDownFollow = null;
    }
  }

  viewport.addEventListener('pointerup', finishPointer);
  viewport.addEventListener('pointercancel', finishPointer);

  // Wheel / Trackpad: smooth pinch-zoom, smooth scroll-zoom, or two-finger pan!
  viewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const cx = (e.clientX - rect.left) * dpr;
    const cy = (e.clientY - rect.top) * dpr;

    const lineMult = e.deltaMode === 1 ? 18 : (e.deltaMode === 2 ? 240 : 1);
    const dx = e.deltaX * lineMult;
    const dy = e.deltaY * lineMult;

    // Pinch-to-zoom on trackpad sets ctrlKey = true
    if (e.ctrlKey || e.metaKey) {
      const factor = Math.exp(-dy * 0.0085);
      zoomAt(factor, cx, cy);
      return;
    }

    // Pan when wheelMode === 'pan', Shift is held, or user swipes horizontally/diagonally on a trackpad
    const isTrackpad2DPan = Math.abs(dx) > 1.5 && Math.abs(dx) > Math.abs(dy) * 0.4;
    if (wheelMode === 'pan' || e.shiftKey || isTrackpad2DPan) {
      panBy(-dx * dpr, -dy * dpr);
    } else {
      const clampedDy = Math.max(-160, Math.min(160, dy));
      const factor = Math.exp(-clampedDy * 0.0028);
      zoomAt(factor, cx, cy);
    }
  }, { passive: false });

  // Interactive Minimap click & drag to pan anywhere immediately!
  let minimapDragging = false;
  function panFromMinimap(clientX, clientY) {
    if (followTarget) setFollowMode(null);
    const rect = minimapCanvas.getBoundingClientRect();
    const u = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const v = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    const { width, height } = getWorldSize();
    offsetX = canvas.width * 0.5 - u * width * scale;
    offsetY = canvas.height * 0.5 - v * height * scale;
    clampOffsets();
    scheduleDraw();
  }
  minimapBox.addEventListener('pointerdown', (e) => {
    e.stopPropagation();
    e.preventDefault();
    minimapDragging = true;
    try { minimapBox.setPointerCapture(e.pointerId); } catch (_) {}
    panFromMinimap(e.clientX, e.clientY);
  });
  minimapBox.addEventListener('pointermove', (e) => {
    if (!minimapDragging) return;
    e.stopPropagation();
    e.preventDefault();
    panFromMinimap(e.clientX, e.clientY);
  });
  minimapBox.addEventListener('pointerup', (e) => {
    minimapDragging = false;
    try { minimapBox.releasePointerCapture(e.pointerId); } catch (_) {}
  });
  minimapBox.addEventListener('pointercancel', () => { minimapDragging = false; });

  // Double-click / double-tap: glide a 2x zoom-in centred on the clicked point
  viewport.addEventListener('dblclick', (e) => {
    if (e.target.closest('.viewport-ui') || e.target.closest('.lm-pin')) return;
    if (followTarget) setFollowMode(null);
    const { width, height } = getWorldSize();
    const rect = viewport.getBoundingClientRect();
    const cu = ((e.clientX - rect.left) * dpr - offsetX) / (width * scale);
    const cv = ((e.clientY - rect.top) * dpr - offsetY) / (height * scale);
    animateCamera(pendingScale() * 2, Math.min(1, Math.max(0, cu)), Math.min(1, Math.max(0, cv)), 360);
  });

  // On-screen D-Pad buttons
  document.querySelectorAll('.dpad-btn[data-dx]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      panBy(Number(btn.dataset.dx) * dpr, Number(btn.dataset.dy) * dpr);
    });
  });
  document.getElementById('btn-dpad-fit').addEventListener('click', (e) => {
    e.stopPropagation();
    fitToScreen();
  });

  // Keyboard Pan (Arrows / WASD), Zoom (+ / - / 0) & Masterpiece Shortcuts (1/2/3, F, H, M, Space, Esc)
  window.addEventListener('keydown', (e) => {
    if (!document.getElementById('modal-overlay').classList.contains('hidden')) {
      if (e.key === 'Escape') document.getElementById('modal-overlay').classList.add('hidden');
      return;
    }
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const step = (e.shiftKey ? 320 : 140) * dpr;
    if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') { e.preventDefault(); panBy(step, 0); }
    else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') { e.preventDefault(); panBy(-step, 0); }
    else if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W') { e.preventDefault(); panBy(0, step); }
    else if (e.key === 'ArrowDown' || e.key === 's' || e.key === 'S') { e.preventDefault(); panBy(0, -step); }
    else if (e.key === '=' || e.key === '+') { e.preventDefault(); zoomStep(1.35); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomStep(1 / 1.35); }
    else if (e.key === '0') { e.preventDefault(); if (followTarget) setFollowMode(null); fitToScreen(); }
    else if (e.key === '1') { const b = document.getElementById('btn-mode-day'); if (b) b.click(); }
    else if (e.key === '2') { const b = document.getElementById('btn-mode-sunset'); if (b) b.click(); }
    else if (e.key === '3') { const b = document.getElementById('btn-mode-night'); if (b) b.click(); }
    else if (e.key === 'f' || e.key === 'F') { const b = document.getElementById('btn-follow'); if (b) b.click(); }
    else if (e.key === 'h' || e.key === 'H') { setCinemaMode(!cinemaMode); }
    else if (e.key === 'm' || e.key === 'M') { const b = document.getElementById('btn-toggle-sound'); if (b) b.click(); }
    else if (e.key === ' ') { e.preventDefault(); const b = document.getElementById('btn-toggle-anim'); if (b) b.click(); }
    else if (e.key === 'i' || e.key === 'I') { e.preventDefault(); setSidebarCollapsed(!sidebarCollapsed); }
    else if (e.key === '/') { e.preventDefault(); const si = document.getElementById('search-input'); if (si) si.focus(); }
    else if (e.key === '[') { e.preventDefault(); cycleLandmark(-1); }
    else if (e.key === ']') { e.preventDefault(); cycleLandmark(1); }
    else if (e.key === 'Escape') {
      if (cinemaMode) setCinemaMode(false);
      else if (followTarget) setFollowMode(null);
    }
  });

  // ---------------------------------------------------------------------------
  // Interactive Pan/Zoom Modal for 0.22 m/px Detail Plates
  // ---------------------------------------------------------------------------
  const modalOverlay = document.getElementById('modal-overlay');
  const modalViewport = document.getElementById('modal-viewport');
  const modalCanvas = document.getElementById('modal-canvas');
  const modalCtx = modalCanvas.getContext('2d');
  let modalImg = null;
  let mScale = 1.0;
  let mOffX = 0;
  let mOffY = 0;
  let mDrag = false;
  let mPrev = { x: 0, y: 0 };

  function drawModal() {
    if (!modalImg) return;
    const rect = modalViewport.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return;
    const mdpr = getDeviceRatio();
    modalCanvas.width = Math.floor(rect.width * mdpr);
    modalCanvas.height = Math.floor(rect.height * mdpr);
    modalCtx.setTransform(mdpr, 0, 0, mdpr, 0, 0);
    modalCtx.fillStyle = '#0f1520';
    modalCtx.fillRect(0, 0, rect.width, rect.height);
    modalCtx.imageSmoothingEnabled = mScale < 0.92;
    modalCtx.drawImage(
      modalImg,
      Math.round(mOffX),
      Math.round(mOffY),
      Math.round(modalImg.width * mScale),
      Math.round(modalImg.height * mScale)
    );
  }

  function fitModal(exact = null) {
    if (!modalImg) return;
    const rect = modalViewport.getBoundingClientRect();
    mScale = exact !== null ? exact : Math.min((rect.width - 24) / modalImg.width, (rect.height - 24) / modalImg.height);
    mOffX = (rect.width - modalImg.width * mScale) * 0.5;
    mOffY = (rect.height - modalImg.height * mScale) * 0.5;
    drawModal();
  }

  let modalCrop = null;
  function openCropModal(c) {
    modalCrop = c;
    document.getElementById('modal-title').textContent = `${c.label} — Ultra-Fine Isometric Pixel Art (Drag to Pan · Scroll to Zoom)`;
    modalOverlay.classList.remove('hidden');
    const img = new Image();
    img.onload = () => {
      modalImg = img;
      fitModal(1.0);
    };
    img.src = `assets/${c.file}?v=${ASSET_VER}`;
  }

  modalViewport.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    mDrag = true;
    mPrev = { x: e.clientX, y: e.clientY };
    modalViewport.classList.add('is-dragging');
    try { modalViewport.setPointerCapture(e.pointerId); } catch (_) {}
  });
  modalViewport.addEventListener('pointermove', (e) => {
    if (!mDrag) return;
    e.preventDefault();
    mOffX += e.clientX - mPrev.x;
    mOffY += e.clientY - mPrev.y;
    mPrev = { x: e.clientX, y: e.clientY };
    drawModal();
  });
  modalViewport.addEventListener('pointerup', (e) => {
    mDrag = false;
    modalViewport.classList.remove('is-dragging');
    try { modalViewport.releasePointerCapture(e.pointerId); } catch (_) {}
  });
  modalViewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (!modalImg) return;
    const rect = modalViewport.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const prev = mScale;
    mScale = Math.min(8.0, Math.max(0.2, mScale * Math.exp(-e.deltaY * 0.003)));
    mOffX = cx - ((cx - mOffX) / prev) * mScale;
    mOffY = cy - ((cy - mOffY) / prev) * mScale;
    drawModal();
  }, { passive: false });

  document.getElementById('btn-modal-1x').addEventListener('click', () => fitModal(1.0));
  document.getElementById('btn-modal-2x').addEventListener('click', () => fitModal(2.0));
  document.getElementById('btn-modal-4x').addEventListener('click', () => fitModal(4.0));
  document.getElementById('btn-modal-fit').addEventListener('click', () => fitModal(null));
  document.getElementById('btn-modal-fly').addEventListener('click', () => {
    const lm = modalCrop && meta ? meta.landmarks.find((l) => l.id === modalCrop.lmId) : null;
    modalOverlay.classList.add('hidden');
    if (lm) flyToLandmark(lm);
  });
  document.getElementById('btn-close-modal').addEventListener('click', () => modalOverlay.classList.add('hidden'));
  modalOverlay.addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') modalOverlay.classList.add('hidden');
  });

  // ---------------------------------------------------------------------------
  // Sidebar & Toolbar Controls
  // ---------------------------------------------------------------------------
  function populateSidebar() {
    if (!meta) return;
    const stopCountEl = document.getElementById('landmark-count') || document.querySelector('.tour-section .mono-tag');
    if (stopCountEl) stopCountEl.textContent = `${meta.landmarks.length} STOPS`;
    const list = document.getElementById('landmark-list');
    list.innerHTML = '';
    meta.landmarks.forEach((lm, idx) => {
      const btn = document.createElement('button');
      btn.className = 'lm-item';
      btn.dataset.lmId = lm.id;
      btn.innerHTML = `
        <div class="lm-item-title">${idx + 1}. ${lm.name}</div>
        <div class="lm-item-meta">E ${Math.round(lm.e)} · N ${Math.round(lm.n)} · ${lm.z.toFixed(0)} m a.s.l.</div>
      `;
      btn.addEventListener('click', () => flyToLandmark(lm));
      list.appendChild(btn);
    });

    const gal = document.getElementById('crop-gallery');
    gal.innerHTML = '';
    CROPS.forEach((c) => {
      const card = document.createElement('div');
      card.className = 'crop-thumb';
      card.innerHTML = `<img src="assets/${c.file}?v=${ASSET_VER}" alt="${c.label}" loading="lazy" /><span>${c.label}</span>`;
      card.addEventListener('click', () => openCropModal(c));
      gal.appendChild(card);
    });
  }

  document.querySelectorAll('.seg-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const prevWorld = getWorldSize();
      const centerU = (canvas.width * 0.5 - offsetX) / (prevWorld.width * scale);
      const centerV = (canvas.height * 0.5 - offsetY) / (prevWorld.height * scale);
      const relZoom = (prevWorld.width * pendingScale()) / canvas.width;
      camAnim = null;

      document.querySelectorAll('.seg-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.mode;
      document.body.dataset.mode = currentMode;
      // Recompute audio gain targets immediately (crickets/birds balance) rather than waiting for the throttle
      audioEngine.forceUpdate();
      viewport.classList.add('mode-switching');
      await Promise.all([loadModeOverview(currentMode), loadTileManifest(currentMode)]);
      viewport.classList.remove('mode-switching');

      const nextWorld = getWorldSize();
      scale = (relZoom * canvas.width) / nextWorld.width;
      offsetX = canvas.width * 0.5 - centerU * nextWorld.width * scale;
      offsetY = canvas.height * 0.5 - centerV * nextWorld.height * scale;
      updateZoomReadout();
      scheduleDraw();
    });
  });

  document.getElementById('btn-zoom-in').addEventListener('click', () => zoomStep(1.4));
  document.getElementById('btn-zoom-out').addEventListener('click', () => zoomStep(1 / 1.4));
  document.getElementById('btn-zoom-1x').addEventListener('click', () => zoomPreset(1.0));
  document.getElementById('btn-zoom-2x').addEventListener('click', () => zoomPreset(2.0));
  document.getElementById('btn-zoom-4x').addEventListener('click', () => zoomPreset(4.0));
  document.getElementById('btn-zoom-fit').addEventListener('click', () => fitToScreen());

  // ---------------------------------------------------------------------------
  // 90s Isometric Pixel-Art Moving Elements Engine (Trains, Cars, Ships, Steam & Flags)
  // ---------------------------------------------------------------------------
  function getCamState() {
    return { scale, offsetX, offsetY, width: canvas.width, height: canvas.height, dpr };
  }

  function drawDepthMasked(wx, wy, boundsOrPadW, vehD16, worldW, worldH, drawFn, extraVertPx = 4.0) {
    depthMgr.drawDepthMasked(ctx, getCamState(), wx, wy, boundsOrPadW, vehD16, worldW, worldH, drawFn, extraVertPx);
  }

  const livingFrameCounts = {
    ships: 0, cars: 0, buses: 0, cyclists: 0, roadPeds: 0,
    busStopCommuters: 0, trains: 0, gulls: 0, swans: 0, sups: 0, ducks: 0, redKites: 0,
  };

  function drawAnimations(worldW, worldH, tSec) {
    const wScale = worldW / (animData.canvas_width || 12331);
    const isNight = currentMode === 'night';
    const isSunset = currentMode === 'sunset';
    const cam = getCamState();
    const hasDepth = depthMgr.hasDepthMap();

    depthMgr.resetDepthStats();
    lastHitTestEntities.length = 0;
    livingFrameCounts.ships = 0;
    livingFrameCounts.cars = 0;
    livingFrameCounts.buses = 0;
    livingFrameCounts.cyclists = 0;
    livingFrameCounts.roadPeds = 0;
    livingFrameCounts.busStopCommuters = 0;
    livingFrameCounts.trains = 0;
    livingFrameCounts.gulls = 0;
    livingFrameCounts.swans = 0;
    livingFrameCounts.sups = 0;
    livingFrameCounts.ducks = 0;
    livingFrameCounts.redKites = 0;

    // 1. Shoreline Waves (waterMask-strict)
    if (animData.ambient && animData.ambient.shoreline) {
      drawShorelineWaves(ctx, cam, depthMgr, animData.ambient.shoreline, worldW, worldH, wScale, tSec, currentMode);
    }

    // 2. Lake Zurich ZSG Paddle Steamer, Sailboats & Boesch Runabout
    for (let sIdx = 0; sIdx < (animData.ships || []).length; sIdx++) {
      const ship = animData.ships[sIdx];
      const st = evalShipState(ship, tSec, currentMode);
      if (drawShipEntity(ctx, depthMgr, cam, ship, st, sIdx, worldW, worldH, wScale, currentMode, tSec)) {
        livingFrameCounts.ships++;
        if (st.frac >= 0 && st.frac <= 1) {
          const spPos = samplePathAt(ship.pts, st.frac, worldW, worldH, 2);
          if (spPos) {
            const isSteamer = ship.kind === 'zsg_steamer';
            lastHitTestEntities.push({
              kind: 'boat',
              id: ship.id || `ship:${sIdx}`,
              wx: spPos.wx,
              wy: spPos.wy,
              radiusCss: isSteamer ? 18 : 13,
              title: isSteamer ? 'ZSG MS Helvetia → Bendlikon Pier' : (ship.name || 'Lake Zurich Vessel'),
              sub: isSteamer
                ? (st.isDocked ? 'Docked at Bendlikon Pier (gangplank deployed)' : 'Cruising Lake Zurich shoreline')
                : 'Lake Zurich recreational vessel',
              specs: [
                ['Service', isSteamer ? 'ZSG Zürichsee' : 'Private Craft'],
                ['Status', st.isDocked ? 'Docked · Boarding' : 'Underway'],
                ['Route', isSteamer ? 'Zürich Bürkliplatz – Bendlikon – Thalwil' : 'Lake Zurich'],
                ['Speed', `${Math.round((ship.speed_mps || 5) * st.speedRatio * 3.6)} km/h`],
              ],
            });
          }
        }
      }
    }

    // 3. Unified Y-Sorted Depth-Masked Road Vehicles, Cyclists & Purposeful O-D Pedestrians
    const roadDrawList = [];
    const drawables = trafficSim ? trafficSim.getDrawableVehicles(worldW, worldH, wScale) : null;

    if (drawables) {
      for (const bItem of drawables.buses) {
        if (!hasDepth && bItem.pos.occ) continue;
        livingFrameCounts.buses++;
        roadDrawList.push(bItem);
        const routeNum = bItem.routeNum || '161';
        lastHitTestEntities.push({
          kind: 'bus',
          id: bItem.id,
          wx: bItem.pos.wx,
          wy: bItem.pos.wy,
          radiusCss: 14,
          title: bItem.tripLabel || `ZVV Bus ${routeNum} · Kilchberg`,
          sub: bItem.isDwelling ? 'Dwelling at bus stop (boarding & alighting)' : 'In service along Kilchberg corridor',
          specs: [
            ['Line', `ZVV ${routeNum}`],
            ['Status', bItem.isDwelling ? 'Stop Dwell' : (bItem.signals && bItem.signals.braking ? 'Braking' : 'Cruising')],
            ['Vehicle', bItem.type === 'bus_artic' ? 'Articulated 19 m' : 'Standard 12 m'],
            ['Speed', `${Math.round((bItem.speedRatio || 0) * 42)} km/h`],
          ],
        });
      }
      for (const cItem of drawables.cars) {
        if (!hasDepth && cItem.pos.occ) continue;
        livingFrameCounts.cars++;
        roadDrawList.push(cItem);
        const sig = cItem.signals || {};
        lastHitTestEntities.push({
          kind: 'car',
          id: cItem.id,
          wx: cItem.pos.wx,
          wy: cItem.pos.wy,
          radiusCss: 10,
          title: cItem.tripLabel || 'Local Traffic · Kilchberg',
          sub: sig.isDeliveryStop
            ? 'Curbside delivery pause (hazard flashers)'
            : (sig.braking ? 'Braking / yielding to traffic or zebra crossing' : 'En route along Kilchberg road network'),
          specs: [
            ['Type', sig.isDeliveryStop ? 'Delivery Van' : 'Passenger Vehicle'],
            ['Status', sig.isDeliveryStop ? 'Delivery Stop' : (sig.braking ? 'Yielding / Braking' : 'Cruising')],
            ['Speed', `${Math.round((sig.speedRatio || 0) * 50)} km/h`],
            ['Corridor', cItem.id && cItem.id.includes('motorway') ? 'A3 Motorway' : 'Kilchberg Local'],
          ],
        });
      }
      if (scale >= 0.35) {
        for (const cycItem of drawables.cyclists) {
          if (!hasDepth && cycItem.pos.occ) continue;
          livingFrameCounts.cyclists++;
          roadDrawList.push(cycItem);
          lastHitTestEntities.push({
            kind: 'cyclist',
            id: cycItem.id,
            wx: cycItem.pos.wx,
            wy: cycItem.pos.wy,
            radiusCss: 9,
            title: 'Cyclist · Kilchberg Corridor',
            sub: 'Grade-aware pace rider on Kilchberg road network',
            specs: [
              ['Mode', 'Bicycle'],
              ['Status', 'Active Ride'],
              ['Route', 'Seestrasse / Dorfstrasse'],
              ['Priority', 'Yields at stops & crossings'],
            ],
          });
        }
        const cwCoats = ['#c53030', '#2b6cb0', '#2f855a', '#d69e2e', '#6b46c1', '#dd6b20'];
        const cwHairs = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
        for (const cwW of drawables.crosswalkWalkers) {
          livingFrameCounts.roadPeds++;
          roadDrawList.push({
            type: 'stop_commuter',
            pos: cwW.pos,
            coat: shadeHex(cwCoats[cwW.colorIdx % cwCoats.length], 1.0, currentMode),
            pants: shadeHex('#243040', 1.0, currentMode),
            hair: cwHairs[cwW.colorIdx % cwHairs.length],
            stride: cwW.stride,
            bag: null,
          });
        }
      }
    }

    // M4 Purposeful O-D Pedestrians (Bahnhof, Bus Stops, Bendlikon Pier, Lindt, Crosswalks, Micro-Archetypes)
    if (pedSim && scale >= 0.35) {
      const pedItems = pedSim.getDrawablePedestrians(worldW, worldH, wScale, cam, depthMgr);
      for (let i = 0; i < pedItems.length; i++) {
        const pItem = pedItems[i];
        if (pItem.role === 'bus_rider' && (pItem.state === 'queue_bus' || pItem.state === 'boarding' || pItem.state === 'alighting')) {
          livingFrameCounts.busStopCommuters++;
        } else {
          livingFrameCounts.roadPeds++;
        }
        roadDrawList.push(pItem);
        lastHitTestEntities.push({
          kind: 'pedestrian',
          id: pItem.id,
          wx: pItem.pos.wx,
          wy: pItem.pos.wy,
          radiusCss: 8,
          title: pItem.tripLabel || 'Villager · Kilchberg',
          sub: `Purposeful Footpath Trip · ${pItem.state.replace(/_/g, ' ')}`,
          specs: [
            ['Origin', pItem.originName || 'Kilchberg'],
            ['Destination', pItem.destName || 'Kilchberg'],
            ['Role', pItem.role.replace(/_/g, ' ')],
            ['Status', pItem.state.replace(/_/g, ' ')],
          ],
        });
      }
    }

    roadDrawList.sort((a, b) => a.pos.wy - b.pos.wy);
    for (const v of roadDrawList) {
      let bounds;
      let extraVertPx = 3.0;
      if (v.type === 'bus_artic') {
        const hdx = Math.abs(v.pFront.wx - v.pRear.wx) * 0.5;
        const hdy = Math.abs(v.pFront.wy - v.pRear.wy) * 0.5;
        const nExtra = isNight ? 32 * wScale : (isSunset ? 18 * wScale : 6 * wScale);
        const yExtra = isNight ? 20 * wScale : (isSunset ? 12 * wScale : 0);
        bounds = {
          ex: hdx + 16 * wScale + nExtra,
          eyUp: hdy + 20 * wScale + yExtra,
          eyDn: hdy + 10 * wScale + yExtra,
        };
        extraVertPx = 6.5;
      } else if (v.type === 'bus') {
        const atx = Math.abs(v.pos.tx);
        const aty = Math.abs(v.pos.ty);
        const nExtra = isNight ? 32 * wScale : (isSunset ? 18 * wScale : 4 * wScale);
        const yExtra = isNight ? 18 * wScale : (isSunset ? 12 * wScale : 0);
        bounds = {
          ex: (atx * 24 + 9) * wScale + nExtra,
          eyUp: (aty * 24 + 16) * wScale + yExtra,
          eyDn: (aty * 24 + 7) * wScale + yExtra,
        };
        extraVertPx = 6.5;
      } else if (v.type === 'car') {
        const atx = Math.abs(v.pos.tx);
        const aty = Math.abs(v.pos.ty);
        const nExtra = isNight ? 24 * wScale : (isSunset ? 16 * wScale : 4 * wScale);
        const yExtra = isNight ? 14 * wScale : (isSunset ? 10 * wScale : 2 * wScale);
        bounds = {
          ex: (atx * 12 + 7) * wScale + nExtra,
          eyUp: (aty * 12 + 11) * wScale + yExtra,
          eyDn: (aty * 12 + 6) * wScale + yExtra,
        };
        extraVertPx = 3.0;
      } else if (v.type === 'cyclist') {
        bounds = {
          ex: (isNight ? 14 : 7) * wScale,
          eyUp: 11 * wScale,
          eyDn: (isNight ? 9 : 4) * wScale,
        };
        extraVertPx = 2.0;
      } else if (v.type === 'ped_sim') {
        bounds = v.bounds || { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };
        extraVertPx = 2.0;
      } else {
        bounds = { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };
        extraVertPx = 2.0;
      }

      drawDepthMasked(v.pos.wx, v.pos.wy, bounds, v.pos.d16, worldW, worldH, (targetCtx) => {
        if (v.type === 'bus_artic') {
          draw3DArticulatedBus(targetCtx, cam, v.pRear, v.pMidRear, v.pMidFront, v.pFront, wScale, currentMode, tSec, v.speedRatio, v.isDwelling, v.signals);
        } else if (v.type === 'bus') {
          draw3DBus(targetCtx, cam, v.pos, wScale, currentMode, tSec, v.speedRatio, v.isDwelling, v.routeNum, v.signals);
        } else if (v.type === 'car') {
          draw3DCar(targetCtx, cam, v.pos, v.colorIdx, wScale, currentMode, tSec, v.signals);
        } else if (v.type === 'cyclist') {
          draw3DCyclist(targetCtx, cam, v.pos, v.colorIdx, wScale, currentMode, tSec);
        } else if (v.type === 'ped_sim') {
          drawPedestrianEntity(targetCtx, cam, v, wScale, currentMode, tSec);
        } else if (v.type === 'stop_commuter') {
          drawMiniPerson(
            targetCtx,
            offsetX + v.pos.wx * scale,
            offsetY + v.pos.wy * scale,
            scale * wScale * 0.90,
            v.coat, v.pants, v.hair, isNight, v.stride, v.bag,
            canvas.width, canvas.height,
          );
        }
      }, extraVertPx);
    }

    // 3b. NW-platform Bahnhof board & clock drawn before SBB trains so passing trains cleanly pass in front
    drawPreTrainVignettes(ctx, cam, animData, worldW, worldH, wScale, tSec, currentMode);

    // 4. SBB Seebahn Multi-Carriage Trains
    for (const tr of (animData.trains || [])) {
      const trSt = evalTrainState(tr, tSec);
      const headFrac = trSt.headFrac;
      if (headFrac < 0 || headFrac > 1.12) continue;
      const coachPitchFrac = 19.5 / tr.length_m;
      const bodyLenFrac = 18.1 / tr.length_m;
      const nCars = tr.carriages || 4;
      const carSamples = [];
      for (let cIdx = 0; cIdx < nCars; cIdx++) {
        const fFront = headFrac - cIdx * coachPitchFrac;
        const fRear = fFront - bodyLenFrac;
        if (fRear < 0.004 || fFront > 0.996) {
          carSamples.push(null);
          continue;
        }
        const pFront = samplePathAt(tr.pts, fFront, worldW, worldH, 2);
        const pRear = samplePathAt(tr.pts, fRear, worldW, worldH, 2);
        if (pFront && pRear && (hasDepth || (!pFront.occ && !pRear.occ))) {
          carSamples.push({
            cIdx,
            variant: cIdx === 0 ? 0 : (cIdx === nCars - 1 ? 2 : 1),
            pFront,
            pRear,
            midWx: (pFront.wx + pRear.wx) * 0.5,
            midWy: (pFront.wy + pRear.wy) * 0.5,
            midD16: Math.round((pFront.d16 + pRear.d16) * 0.5),
          });
        } else {
          carSamples.push(null);
        }
      }
      const units = [];
      for (let cIdx = 0; cIdx < nCars; cIdx++) {
        const u = carSamples[cIdx];
        if (!u) continue;
        const nxt = (cIdx < nCars - 1) ? carSamples[cIdx + 1] : null;
        units.push({
          ...u,
          nextRear: nxt ? nxt.pRear : null,
          nextFront: nxt ? nxt.pFront : null,
        });
      }
      if (units.length > 0) {
        livingFrameCounts.trains++;
        const isS8 = tr.id === 'sbb_s8_south';
        const trainMeta = {
          kind: 'train',
          id: tr.id,
          radiusCss: 18,
          title: isS8 ? 'SBB S8 · Seebahn Southbound' : 'SBB S24 / IC · Seebahn Northbound',
          sub: trSt.isDwelling ? 'Boarding at Bahnhof Kilchberg' : (isS8 ? 'Zürich HB → Kilchberg → Pfäffikon SZ' : 'Thalwil → Kilchberg → Zürich HB'),
          specs: [
            ['Service', isS8 ? 'SBB S8 Double-Decker' : 'SBB S24 / IC'],
            ['Status', trSt.isDwelling ? 'Station Dwell · Doors Open' : 'Cruising'],
            ['Speed', `${Math.round((tr.speed_mps || 20) * trSt.speedRatio * 3.6)} km/h`],
            ['Track', isS8 ? 'Gleis 2 (Seebahn)' : 'Gleis 1 (Seebahn)'],
          ],
        };
        if (trSt.midFrac >= 0 && trSt.midFrac <= 1) {
          const midPos = samplePathAt(tr.pts, trSt.midFrac, worldW, worldH, 2);
          if (midPos) {
            lastHitTestEntities.push({ ...trainMeta, wx: midPos.wx, wy: midPos.wy });
          }
        }
        for (const u of units) {
          lastHitTestEntities.push({ ...trainMeta, wx: u.midWx, wy: u.midWy });
        }
      }
      units.sort((a, b) => a.midWy - b.midWy);
      for (const u of units) {
        const hdx = Math.abs(u.pFront.wx - u.pRear.wx) * 0.5;
        const hdy = Math.abs(u.pFront.wy - u.pRear.wy) * 0.5;
        const isLeadCar = u.variant === 0;
        const isTailCar = u.variant === 2;
        const beamX = (isNight && isLeadCar) ? 54 * wScale : ((isNight && isTailCar) ? 20 * wScale : 0);
        const beamY = (isNight && isLeadCar) ? 32 * wScale : ((isNight && isTailCar) ? 14 * wScale : 0);
        const trainBounds = {
          ex: hdx + 16 * wScale + beamX,
          eyUp: hdy + 26 * wScale + beamY,
          eyDn: hdy + 12 * wScale + beamY,
        };
        drawDepthMasked(u.midWx, u.midWy, trainBounds, u.midD16, worldW, worldH, (targetCtx) => {
          draw3DTrainUnit(
            targetCtx, cam,
            u.pRear, u.pFront, tr.kind, u.variant, wScale, currentMode,
            u.nextRear, u.nextFront, tSec, trSt.isDwelling, trSt.dwellProgress,
          );
        }, 7.5);
      }
    }

    // 5. Wind-Coherent Ambient Effects, Landmark Vignettes, Sports Fields, Lake Micro-Life & Atmosphere
    drawAmbientEffects(ctx, cam, animData, livingFrameCounts, worldW, worldH, wScale, tSec, currentMode);
    drawKilchbergDetails(ctx, cam, depthMgr, animData, livingFrameCounts, worldW, worldH, wScale, tSec, currentMode, fixedAnimTime, {
      hasDynamicPeds: !!pedSim,
    });
    drawAtmosphereAndLife(ctx, cam, depthMgr, animData, meta, livingFrameCounts, worldW, worldH, wScale, tSec, currentMode);
  }

  const audioEngine = createAudioEngine({
    assetVer: ASSET_VER,
    getCamera: () => getCamState(),
    getMode: () => currentMode,
    getWorldSize: () => getWorldSize(),
    getAnimData: () => animData,
    getTrafficSim: () => trafficSim,
    getAnimTimeSec: () => getAnimTimeSec(),
  });

  let followTarget = null; // null | 'train' | 'boat' | 'bus'
  let cinemaMode = false;

  const FOLLOW_LABELS = {
    train: 'Follow: Train',
    boat: 'Follow: Boat',
    bus: 'Follow: Bus',
  };

  function getAnimTimeSec() {
    return fixedAnimTime !== null ? fixedAnimTime : performance.now() * 0.001;
  }

  function showFollowInspector(kind) {
    if (kind === 'train') {
      showInspector({
        title: 'SBB S8 · Seebahn Corridor',
        sub: 'Following live SBB train through Bahnhof Kilchberg',
        specs: [
          ['Service', 'SBB S8 / S24'],
          ['Station', 'Bahnhof Kilchberg'],
          ['Route', 'Zürich HB ↔ Kilchberg ↔ Thalwil'],
          ['Camera', 'Follow: Train'],
        ],
      });
    } else if (kind === 'boat') {
      showInspector({
        title: 'ZSG MS Helvetia · Lake Zurich',
        sub: 'Following Lake Zurich steamer approaching Bendlikon Pier',
        specs: [
          ['Operator', 'ZSG Zürichsee'],
          ['Pier', 'Bendlikon (Badweg 1.1)'],
          ['Route', 'Zürich Bürkliplatz ↔ Bendlikon'],
          ['Camera', 'Follow: Boat'],
        ],
      });
    } else if (kind === 'bus') {
      showInspector({
        title: 'ZVV Bus 165 · Dorfstrasse Viaduct',
        sub: 'Following live ZVV bus climbing Kilchberg village corridor',
        specs: [
          ['Line', 'ZVV Bus 165 / 161'],
          ['Corridor', 'Dorfstrasse Horseshoe Viaduct'],
          ['Route', 'Bürkliplatz ↔ Kilchberg Dorf'],
          ['Camera', 'Follow: Bus'],
        ],
      });
    }
  }

  function setFollowMode(mode) {
    followTarget = (mode === 'train' || mode === 'boat' || mode === 'bus') ? mode : null;
    const btn = document.getElementById('btn-follow');
    if (btn) {
      btn.textContent = FOLLOW_LABELS[followTarget] || 'Follow: Off';
      btn.classList.toggle('active', !!followTarget);
      btn.title = 'Cycle Follow Camera: Train → Boat → Bus → Off (F)';
    }
    if (followTarget) {
      if (!showAnimations) {
        showAnimations = true;
        const ba = document.getElementById('btn-toggle-anim');
        if (ba) { ba.textContent = 'Live: On'; ba.classList.add('active'); }
        startAnimLoop();
      }
      if (cssScale() < 1.5) {
        animateCamera(2.0 * dpr, getCenterUV().u, getCenterUV().v, 360, true);
      }
      showFollowInspector(followTarget);
      updateFollowCamera(getAnimTimeSec(), true);
      scheduleDraw();
    }
  }

  function setCinemaMode(enabled) {
    cinemaMode = !!enabled;
    document.body.classList.toggle('cinema-mode', cinemaMode);
    const btn = document.getElementById('btn-cinema');
    if (btn) btn.classList.toggle('active', cinemaMode);
    setTimeout(() => { resizeViewport(); scheduleDraw(); }, 30);
  }

  function updateFollowCamera(tSec, snap) {
    if (!followTarget || !animData) return;
    const { width: worldW, height: worldH } = getWorldSize();
    let targetPos = null;
    if (trafficSim) {
      const cwOcc = pedSim ? pedSim.getOccupiedCrosswalks() : null;
      trafficSim.updateToTime(tSec, currentMode, cwOcc);
      targetPos = trafficSim.getFollowTarget(followTarget, worldW, worldH);
    }
    if (!targetPos) return;
    const desiredX = canvas.width * 0.5 - targetPos.wx * scale;
    const desiredY = canvas.height * 0.5 - targetPos.wy * scale;
    const jumpDist = Math.hypot(desiredX - offsetX, desiredY - offsetY);
    if (snap || jumpDist > canvas.width * 0.8) {
      offsetX = desiredX;
      offsetY = desiredY;
    } else {
      offsetX += (desiredX - offsetX) * 0.14;
      offsetY += (desiredY - offsetY) * 0.14;
    }
    clampOffsets();
  }

  let lastAnimPaint = 0;
  let animLoopId = 0;
  function startAnimLoop() {
    if (!animLoopId && showAnimations && animData && !document.hidden) {
      animLoopId = requestAnimationFrame(animLoop);
    }
  }
  function stopAnimLoop() {
    if (animLoopId) {
      cancelAnimationFrame(animLoopId);
      animLoopId = 0;
    }
  }
  function animLoop(nowMs) {
    animLoopId = 0;
    if (showAnimations && animData && !document.hidden) {
      if (nowMs - lastAnimPaint >= 33 && !drawScheduled) {
        lastAnimPaint = nowMs;
        if (followTarget) updateFollowCamera(getAnimTimeSec(), false);
        draw();
      }
      startAnimLoop();
    }
  }

  const btnFollow = document.getElementById('btn-follow');
  if (btnFollow) {
    btnFollow.title = 'Cycle Follow Camera: Train → Boat → Bus → Off (F)';
    btnFollow.addEventListener('click', () => {
      const next = !followTarget
        ? 'train'
        : (followTarget === 'train' ? 'boat' : (followTarget === 'boat' ? 'bus' : null));
      setFollowMode(next);
    });
  }

  const btnCinema = document.getElementById('btn-cinema');
  if (btnCinema) {
    btnCinema.addEventListener('click', () => setCinemaMode(!cinemaMode));
  }
  const btnExitCinema = document.getElementById('btn-exit-cinema');
  if (btnExitCinema) {
    btnExitCinema.addEventListener('click', () => setCinemaMode(false));
  }

  const btnToggleAnim = document.getElementById('btn-toggle-anim');
  if (btnToggleAnim) {
    btnToggleAnim.addEventListener('click', (e) => {
      showAnimations = !showAnimations;
      e.currentTarget.textContent = showAnimations ? 'Live: On' : 'Live: Off';
      e.currentTarget.classList.toggle('active', showAnimations);
      if (showAnimations) {
        startAnimLoop();
      } else {
        stopAnimLoop();
        scheduleDraw();
      }
    });
  }

  audioEngine.bindUI();
  audioEngine.startClock();

  document.addEventListener('visibilitychange', () => {
    audioEngine.handleVisibilityChange(document.hidden);
    if (document.hidden) {
      stopAnimLoop();
    } else if (showAnimations && animData) {
      startAnimLoop();
    }
  });

  document.getElementById('btn-wheel-mode').addEventListener('click', (e) => {
    wheelMode = wheelMode === 'zoom' ? 'pan' : 'zoom';
    const isPan = wheelMode === 'pan';
    e.currentTarget.textContent = isPan ? 'Scroll: Pan' : 'Scroll: Zoom';
    e.currentTarget.classList.toggle('active', isPan);
  });

  document.getElementById('btn-toggle-pins').addEventListener('click', (e) => {
    showPins = !showPins;
    e.currentTarget.classList.toggle('active', showPins);
    scheduleDraw();
  });

  document.getElementById('btn-toggle-loupe').addEventListener('click', (e) => {
    showLoupe = !showLoupe;
    e.currentTarget.classList.toggle('active', showLoupe);
    loupeCanvas.classList.toggle('hidden', !showLoupe);
    scheduleDraw();
  });

  window.addEventListener('resize', resizeViewport);
  if (window.ResizeObserver) {
    new ResizeObserver(() => resizeViewport()).observe(viewport);
  }
  // Moving the window between a Retina and a standard monitor changes devicePixelRatio without a resize
  try {
    window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`).addEventListener('change', () => resizeViewport());
  } catch (_) { /* older browsers */ }

  if (urlParams.get('pins') === '0') {
    showPins = false;
    const btnPins = document.getElementById('btn-toggle-pins');
    if (btnPins) btnPins.classList.remove('active');
  }
  if (urlParams.get('cinema') === '1') {
    setCinemaMode(true);
  }
  const initMode = ['day', 'sunset', 'night'].includes(urlParams.get('mode')) ? urlParams.get('mode') : 'day';
  // Always normalise the preset (malformed ?mode= falls back to day) & expose it for atmospheric theming
  currentMode = initMode;
  document.body.dataset.mode = currentMode;
  document.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === currentMode));
  resizeViewport();

  // ---------------------------------------------------------------------------
  // Swiss cartographic chrome: collapsible inspector, address search, mixer, share & postcard
  // ---------------------------------------------------------------------------
  let sidebarCollapsed = false;
  const btnSidebar = document.getElementById('btn-toggle-sidebar');
  const narrowQuery = window.matchMedia('(max-width: 760px)');

  function setSidebarCollapsed(collapsed) {
    sidebarCollapsed = !!collapsed;
    document.body.classList.toggle('sidebar-collapsed', sidebarCollapsed);
    if (btnSidebar) {
      btnSidebar.classList.toggle('active', !sidebarCollapsed);
      btnSidebar.setAttribute('aria-expanded', sidebarCollapsed ? 'false' : 'true');
    }
    resizeViewport();
  }
  if (btnSidebar) btnSidebar.addEventListener('click', () => setSidebarCollapsed(!sidebarCollapsed));
  // Phones start with the inspector as a closed drawer so the map gets the whole screen
  setSidebarCollapsed(narrowQuery.matches && urlParams.get('sidebar') !== '1');

  const toastEl = document.getElementById('toast');
  let toastTimer = null;
  function showToast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), 2200);
  }

  // ---- Instant address & landmark search (1,887 swisstopo addresses + 10 landmarks)
  const searchInput = document.getElementById('search-input');
  const searchList = document.getElementById('search-results');
  let searchIndex = null;
  let searchHits = [];
  let searchCursor = -1;

  function buildSearchIndex() {
    if (searchIndex || !meta) return;
    searchIndex = [];
    (meta.landmarks || []).forEach((lm) => {
      searchIndex.push({ kind: 'landmark', ref: lm, text: `${lm.name} ${lm.subtitle || ''} ${lm.category || ''}`.toLowerCase(), label: lm.name });
    });
    (meta.buildings || []).forEach((b) => {
      if (!b.addr) return;
      searchIndex.push({ kind: 'building', ref: b, text: `${b.addr} ${b.nb || ''}`.toLowerCase(), label: b.addr });
    });
  }

  function rankSearch(entry, query) {
    if (entry.text.startsWith(query)) return 0;
    if (entry.text.includes(` ${query}`)) return 1;
    return 2;
  }

  function runSearch(raw) {
    const query = (raw || '').trim().toLowerCase();
    searchHits = [];
    searchCursor = -1;
    if (query && meta) {
      buildSearchIndex();
      const tokens = query.split(/\s+/);
      const hits = [];
      for (const entry of searchIndex) {
        if (tokens.every((t) => entry.text.includes(t))) hits.push(entry);
      }
      hits.sort((a, b) => (rankSearch(a, query) - rankSearch(b, query))
        || ((a.kind === 'landmark' ? 0 : 1) - (b.kind === 'landmark' ? 0 : 1))
        || (a.label.length - b.label.length)
        || a.label.localeCompare(b.label, 'de'));
      searchHits = hits;
    }
    searchResultCount = searchHits.length;
    renderSearchResults(query);
  }

  function renderSearchResults(query) {
    if (!searchList) return;
    searchList.innerHTML = '';
    if (!query) {
      searchList.classList.add('hidden');
      return;
    }
    if (!searchHits.length) {
      const li = document.createElement('li');
      li.className = 'search-empty';
      li.textContent = 'No matching address or landmark';
      searchList.appendChild(li);
    }
    searchHits.slice(0, 8).forEach((h, i) => {
      const li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.className = 'search-item';
      li.dataset.idx = String(i);
      const title = document.createElement('span');
      title.className = 'search-item-title';
      title.textContent = h.label;
      const sub = document.createElement('span');
      sub.className = 'search-item-sub';
      sub.textContent = h.kind === 'landmark' ? 'Landmark' : `${h.ref.nb || 'Kilchberg'} · ${h.ref.type || 'Building'}`;
      li.append(title, sub);
      searchList.appendChild(li);
    });
    if (searchHits.length > 8) {
      const li = document.createElement('li');
      li.className = 'search-empty';
      li.textContent = `+${searchHits.length - 8} more — keep typing to narrow`;
      searchList.appendChild(li);
    }
    searchList.classList.remove('hidden');
  }

  function chooseSearchHit(hit) {
    if (!hit) return;
    if (followTarget) setFollowMode(null);
    if (hit.kind === 'landmark') {
      flyToLandmark(hit.ref);
    } else {
      setActiveLandmark(null);
      selectBuilding(hit.ref);
      animateCamera(3.0 * dpr, hit.ref.u, hit.ref.v, 640);
    }
    if (searchInput) searchInput.value = hit.label;
    if (searchList) searchList.classList.add('hidden');
    if (narrowQuery.matches) setSidebarCollapsed(true);
  }

  function highlightSearchCursor() {
    if (!searchList) return;
    [...searchList.querySelectorAll('.search-item')].forEach((el, i) => el.classList.toggle('active', i === searchCursor));
  }

  if (searchInput && searchList) {
    searchInput.addEventListener('input', () => runSearch(searchInput.value));
    searchInput.addEventListener('focus', () => { if (searchInput.value.trim()) renderSearchResults(searchInput.value.trim().toLowerCase()); });
    searchInput.addEventListener('keydown', (e) => {
      e.stopPropagation();
      const shown = Math.min(8, searchHits.length);
      if (e.key === 'ArrowDown') { e.preventDefault(); searchCursor = Math.min(shown - 1, searchCursor + 1); highlightSearchCursor(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); searchCursor = Math.max(0, searchCursor - 1); highlightSearchCursor(); }
      else if (e.key === 'Enter') { e.preventDefault(); chooseSearchHit(searchHits[Math.max(0, searchCursor)]); }
      else if (e.key === 'Escape') {
        e.preventDefault();
        searchInput.value = '';
        runSearch('');
        searchInput.blur();
      }
    });
    searchList.addEventListener('mousedown', (e) => e.preventDefault());
    searchList.addEventListener('click', (e) => {
      const li = e.target.closest('.search-item');
      if (li) chooseSearchHit(searchHits[Number(li.dataset.idx)]);
    });
    document.addEventListener('pointerdown', (e) => {
      if (!e.target.closest('.search-wrap')) searchList.classList.add('hidden');
    });
  }

  // Audio layer mixer UI is bound via audioEngine.bindUI()

  // ---- Share permalink & postcard PNG
  function buildPermalink() {
    const c = getCenterUV();
    const p = new URLSearchParams();
    p.set('mode', currentMode);
    p.set('zoom', cssScale().toFixed(3));
    p.set('u', c.u.toFixed(5));
    p.set('v', c.v.toFixed(5));
    if (!showPins) p.set('pins', '0');
    if (followTarget) p.set('follow', followTarget);
    return `${window.location.href.split('#')[0].split('?')[0]}?${p.toString()}`;
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_) { /* fall through to legacy path */ }
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand && document.execCommand('copy');
      ta.remove();
      return !!ok;
    } catch (_) {
      return false;
    }
  }

  const btnShare = document.getElementById('btn-share');
  if (btnShare) {
    btnShare.addEventListener('click', async () => {
      const link = buildPermalink();
      const copied = await copyText(link);
      try { window.history.replaceState(null, '', link); } catch (_) { /* sandboxed */ }
      showToast(copied ? 'Permalink copied to clipboard' : 'Permalink set in the address bar');
    });
  }

  const btnPostcard = document.getElementById('btn-postcard');
  if (btnPostcard) {
    btnPostcard.addEventListener('click', () => {
      const border = Math.round(26 * dpr);
      const foot = Math.round(52 * dpr);
      const out = document.createElement('canvas');
      out.width = canvas.width + border * 2;
      out.height = canvas.height + border + foot;
      const o = out.getContext('2d');
      o.fillStyle = '#f2ede2';
      o.fillRect(0, 0, out.width, out.height);
      o.drawImage(canvas, border, border);
      o.strokeStyle = '#1a2230';
      o.lineWidth = Math.max(1, dpr);
      o.strokeRect(border - 0.5, border - 0.5, canvas.width + 1, canvas.height + 1);
      // Swiss cross + cartographic caption
      const cx = border;
      const cy = canvas.height + border + Math.round(10 * dpr);
      const cs = Math.round(26 * dpr);
      o.fillStyle = '#d62828';
      o.fillRect(cx, cy, cs, cs);
      o.fillStyle = '#faf9f6';
      o.fillRect(cx + cs * 0.42, cy + cs * 0.17, cs * 0.16, cs * 0.66);
      o.fillRect(cx + cs * 0.17, cy + cs * 0.42, cs * 0.66, cs * 0.16);
      o.fillStyle = '#1a2230';
      o.textBaseline = 'middle';
      o.font = `600 ${Math.round(14 * dpr)}px 'IBM Plex Mono', monospace`;
      o.fillText('KILCHBERG ZH · BFS #0135', cx + cs + Math.round(12 * dpr), cy + cs * 0.32);
      o.font = `${Math.round(11 * dpr)}px 'IBM Plex Mono', monospace`;
      const modeName = { day: 'Midday', sunset: 'Alpenglow', night: 'Night' }[currentMode] || currentMode;
      o.fillText(`swisstopo · ${modeName} · ${document.getElementById('scale-bar-label')?.textContent || ''} scale bar`, cx + cs + Math.round(12 * dpr), cy + cs * 0.78);
      out.toBlob((blob) => {
        if (!blob) { showToast('Postcard export unavailable'); return; }
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `kilchberg-${currentMode}-postcard.png`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
        showToast('Postcard saved');
      }, 'image/png');
    });
  }

  // Compass rose: the camera looks from azimuth 102°, so true north is rotated off screen-up
  (function initCompass() {
    const rose = document.getElementById('compass-rose');
    if (!rose) return;
    const az = 102;
    // screen-up looks toward bearing (az+180); north is therefore (360 - (az+180)) clockwise from up
    rose.style.transform = `rotate(${(540 - az) % 360}deg)`;
  })();

  // Boot
  Promise.all([
    loadModeOverview(currentMode),
    currentMode === 'day' ? Promise.resolve() : loadModeOverview('day'),
    loadTileManifest(currentMode),
    depthMgr.loadDepthMap(ASSET_VER),
    fetch(`data/kilchberg_interactive.json?v=${ASSET_VER}`).then((r) => r.json()).catch(() => null),
    fetch(`data/kilchberg_animations.json?v=${ASSET_VER}`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]).then(([_, __, ___, ____, loadedMeta, loadedAnim]) => {
    meta = loadedMeta;
    animData = loadedAnim;
    depthMgr.setAnimData(animData);
    depthMgr.buildWaterMask(overviewImages.day);
    if (animData) {
      trafficSim = createTrafficSim(animData);
      trafficSim.setCrosswalkOverrideMode(true);
      pedSim = createPedestrianSim(animData);
      const t0 = getAnimTimeSec();
      const ped0 = pedSim.updateToTime(t0, currentMode, null);
      trafficSim.setExternalPedestrianStats(ped0.stats);
      lastSimSnapshot = trafficSim.updateToTime(t0, currentMode, ped0.occupiedCrosswalks);
    }
    populateSidebar();
    resizeViewport();
    const qLandmarkId = (urlParams.get('landmark') || '').trim();
    const qLandmark = (qLandmarkId && meta && Array.isArray(meta.landmarks))
      ? meta.landmarks.find((l) => l.id === qLandmarkId)
      : null;
    const qZoom = parseFloat(urlParams.get('zoom'));
    const qU = parseFloat(urlParams.get('u'));
    const qV = parseFloat(urlParams.get('v'));
    if (qLandmark) {
      flyToLandmark(qLandmark, (Number.isFinite(qZoom) && qZoom > 0) ? qZoom : null, true);
    } else if (Number.isFinite(qZoom) && qZoom > 0) {
      const { width, height } = getWorldSize();
      const cu = Number.isFinite(qU) ? Math.min(1, Math.max(0, qU)) : 0.5;
      const cv = Number.isFinite(qV) ? Math.min(1, Math.max(0, qV)) : 0.5;
      scale = clampScale(qZoom * dpr);
      offsetX = canvas.width * 0.5 - cu * width * scale;
      offsetY = canvas.height * 0.5 - cv * height * scale;
      clampOffsets();
      updateZoomReadout();
      draw();
    } else {
      fitToScreen(false);
    }
    const qFollow = (urlParams.get('follow') || '').toLowerCase();
    if (qFollow === 'train' || qFollow === 'boat' || qFollow === 'bus') {
      setFollowMode(qFollow);
      draw();
    }
    if (showAnimations && animData) {
      startAnimLoop();
    }
    // Preload remaining lighting modes
    for (const m of ['day', 'sunset', 'night']) {
      if (m !== currentMode) {
        loadModeOverview(m);
        loadTileManifest(m);
      }
    }
  });

  // Non-intrusive read-only telemetry snapshot (PROJECT.md § Interface Contract #5)
  Object.defineProperty(window, '__dioramaDebug', {
    configurable: true,
    enumerable: false,
    get() {
      const { u: cu, v: cv } = getCenterUV();
      const tNow = getAnimTimeSec();
      const fallbackBell = evalBellState(tNow, currentMode).bellPhase;
      const simStats = trafficSim
        ? trafficSim.getStats()
        : {
          vehicles: 0,
          brakingCount: 0,
          yieldingCount: 0,
          pedestrians: 0,
          boardingCount: 0,
          activeTrips: 0,
          bellPhase: fallbackBell,
          minBusGapM: 999,
          clippingCount: 0,
          overlapCount: 0,
          cyclists: 0,
        };
      return {
        mode: currentMode,
        scale: scale / dpr,
        u: cu,
        v: cv,
        dpr,
        fps: renderStamps.length,
        audioEnabled: audioEngine.isEnabled(),
        audioState: audioEngine.getStateName(),
        audioGains: audioEngine.getGainReport(),
        activeLandmark: activeLandmarkId,
        selectedBuilding: selectedBuilding ? selectedBuilding.id : null,
        selectedEntity: selectedEntity ? selectedEntity.id : null,
        searchResultCount,
        animTime: tNow,
        followTarget,
        showAnimations,
        waterMaskReady: depthMgr.isWaterMaskReady(),
        depthStats: depthMgr.getDepthStats(),
        livingCounts: { ...livingFrameCounts },
        simStats,
      };
    },
  });
