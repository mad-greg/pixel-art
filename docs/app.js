import { createAudioEngine } from './js/audio.js';
import { createCameraController } from './js/camera.js';
import { createTileManager } from './js/tiles.js';
import { createDepthManager } from './js/render/depth.js';
import { evalBellState } from './js/sim/schedule.js';
import { createKilchbergLivingRuntime } from './js/living/index.js';

  const canvas = document.getElementById('diorama-canvas');
  const ctx = canvas.getContext('2d', { alpha: false });
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
  const rawModeParam = urlParams.get('mode');
  const explicitMode = urlParams.has('mode')
    ? (['day', 'sunset', 'night'].includes(rawModeParam) ? rawModeParam : 'day')
    : null;

  const ASSET_VER = '14.0';
  const MAX_CACHED_TILES = 128;
  const MODE_BACKDROPS = {
    day: '#1b2b42',
    sunset: '#2a2034',
    night: '#0a101f',
  };

  // Overview images, 2-level 0.22/0.11 m/px async ImageBitmap tile manager & 16-bit 3D Depth Manager
  const overviewImages = {};
  const tileManifests = {};   // mode -> { width, height, tileSize, cols, rows, mpp, z1? } | null
  const depthMgr = createDepthManager();

  function formatMppCm(mpp) {
    return `${(mpp * 100).toFixed(1).replace(/\.0$/, '')} cm/px`;
  }
  const initialClockOpts = fixedAnimTime !== null
    ? {
      mode: 'deterministic',
      tSec: fixedAnimTime,
      preset: explicitMode || 'day',
      presetOverride: 'auto',
    }
    : {
      mode: 'live',
      presetOverride: explicitMode || 'auto',
    };
  const livingRuntime = createKilchbergLivingRuntime({
    clockOpts: initialClockOpts,
    initialTSec: fixedAnimTime !== null ? fixedAnimTime : 0,
  });
  const livingEngine = livingRuntime.engine;
  const kilchbergClock = livingRuntime.clock;
  const specRegistry = livingRuntime.specs;
  if (fixedAnimTime !== null) {
    kilchbergClock.setDeterministic(fixedAnimTime, explicitMode || 'day');
    if (livingEngine._ctx) {
      livingEngine._ctx.clock = kilchbergClock.sample(Date.now(), fixedAnimTime);
    }
  }
  const initClockSnap = livingRuntime.getClockSnapshot(fixedAnimTime !== null ? fixedAnimTime : 0);
  let livingInitialized = false;
  let liveAnimSec = 0;

  let currentMode = fixedAnimTime !== null
    ? (explicitMode || 'day')
    : (explicitMode || initClockSnap.effectivePreset || 'day');
  let meta = null;
  let animData = null;

  let showAnimations = true;
  let showPins = true;
  let showLoupe = false;
  let wheelMode = 'zoom'; // 'zoom' | 'pan'
  let lastMouse = { x: 0, y: 0 };

  // HiDPI: the canvas backing store is `dpr` x its CSS size (capped at 2 for 60 fps pixel-art rendering).
  // All camera maths (scale, offsets, hit radii) run in backing-store ("device") pixels; the user-facing
  // zoom (readout, URL, debug, presets) is expressed in CSS pixels per world pixel = scale / dpr.
  const DPR_CAP = 2;
  let dpr = 1;
  let activeLandmarkId = null;
  let selectedBuilding = null;
  let selectedEntity = null;
  let pointerDownFollow = null;
  let searchResultCount = 0;

  // Frame telemetry & unified 60fps rAF state
  const renderStamps = [];
  const frameDurations = [];
  const MAX_FRAME_SAMPLES = 60;
  let lastFrameMs = 0;
  let p95FrameMs = 0;
  let droppedFrames = 0;
  let rafId = 0;
  let lastRafTs = 0;
  let needsDraw = false;
  let lastTileLevel = 'overview';
  let lastTilesLoaded = 0;

  // Offscreen snapshot crossfade for Day / Sunset / Night transitions (bypassed on ?t=)
  let modeFadeCanvas = null;
  let modeFade = null; // { startMs, durationMs, ready }
  let modeSwitchGen = 0;
  let modeSwitchAnchor = null;

  // Dirty-check caches to prevent per-frame DOM layout thrash
  let lastLodText = '';
  let lastZoomReadoutText = '';
  let lastScaleBarPx = -1;
  let lastScaleBarLabel = '';
  let lastMinimapKey = '';
  let lastClockHudKey = '';
  let lastReplaceStateMs = 0;

  function safeReplaceState(url) {
    const now = performance.now();
    if (now - lastReplaceStateMs < 350) return;
    lastReplaceStateMs = now;
    try { window.history.replaceState(null, '', url); } catch (_) { /* sandboxed */ }
  }

  function getDeviceRatio() {
    return Math.max(1, Math.min(DPR_CAP, window.devicePixelRatio || 1));
  }

  function getWorldSize() {
    const mf = tileManifests[currentMode];
    const mfW = mf && (mf.width || mf.full_width);
    const mfH = mf && (mf.height || mf.full_height);
    if (mfW && mfH) {
      return { width: mfW, height: mfH, tiled: true, mf };
    }
    const ov = overviewImages[currentMode];
    if (ov) {
      return { width: ov.width, height: ov.height, tiled: false, mf: null };
    }
    return { width: 4462, height: 2146, tiled: false, mf: null };
  }

  const camCtrl = createCameraController({
    getViewportSize: () => ({ width: canvas.width || 1, height: canvas.height || 1 }),
    getWorldSize: () => getWorldSize(),
    getDpr: () => dpr,
    isDeterministic: () => fixedAnimTime !== null,
  });
  const camState = camCtrl.state;

  const tileMgr = createTileManager({
    assetVer: ASSET_VER,
    maxInflight: 8,
    maxCached: MAX_CACHED_TILES,
    crossfadeMs: 120,
    onTileReady: () => scheduleDraw(),
  });

  function cssScale() {
    return camState.scale / dpr;
  }

  function scheduleDraw() {
    needsDraw = true;
    if (!rafId && !document.hidden) {
      rafId = requestAnimationFrame(frameTick);
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
        if (data) {
          if (!data.width && data.full_width) data.width = data.full_width;
          if (!data.height && data.full_height) data.height = data.full_height;
        }
        tileManifests[mode] = data;
        tileMgr.setManifest(mode, data);
        if (data && data.mpp && data.width && data.height) {
          const fidEl = document.getElementById('spec-fidelity');
          if (fidEl) fidEl.textContent = `${formatMppCm(data.mpp)} · ${data.width.toLocaleString()}×${data.height.toLocaleString()}`;
        }
        return data;
      })
      .catch(() => {
        tileManifests[mode] = null;
        tileMgr.setManifest(mode, null);
        return null;
      });
  }

  function clampOffsets() {
    const { width, height } = getWorldSize();
    const scaledW = width * camState.scale;
    const scaledH = height * camState.scale;
    const marginX = Math.max(120, canvas.width * 0.25);
    const marginY = Math.max(120, canvas.height * 0.25);
    const minX = canvas.width - scaledW - marginX;
    const maxX = marginX;
    const minY = canvas.height - scaledH - marginY;
    const maxY = marginY;
    if (scaledW + marginX * 2 <= canvas.width) {
      camState.offsetX = (canvas.width - scaledW) * 0.5;
    } else {
      camState.offsetX = Math.min(maxX, Math.max(minX, camState.offsetX));
    }
    if (scaledH + marginY * 2 <= canvas.height) {
      camState.offsetY = (canvas.height - scaledH) * 0.5;
    } else {
      camState.offsetY = Math.min(maxY, Math.max(minY, camState.offsetY));
    }
  }

  function resizeViewport(skipDraw = false) {
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
      const haveCam = camState.scale > 0 && width > 0 && prevW > 300;
      const cwx = haveCam ? (prevW * 0.5 - camState.offsetX) / camState.scale : 0;
      const cwy = haveCam ? (prevH * 0.5 - camState.offsetY) / camState.scale : 0;
      camState.scale = camState.scale * nd / dpr;
      camState.targetScale = camState.targetScale * nd / dpr;
      dpr = nd;
      canvas.width = newW;
      canvas.height = newH;
      if (haveCam) {
        camState.offsetX = newW * 0.5 - cwx * camState.scale;
        camState.offsetY = newH * 0.5 - cwy * camState.scale;
        clampOffsets();
      }
      updateZoomReadout();
    }
    const tb = document.getElementById('topbar');
    if (tb) document.documentElement.style.setProperty('--topbar-h', `${Math.round(tb.getBoundingClientRect().height)}px`);
    sizeMinimap();
    if (skipDraw !== true) draw();
  }

  function getCenterUV() {
    const { width, height } = getWorldSize();
    const u = (width > 0 && camState.scale > 0) ? (canvas.width * 0.5 - camState.offsetX) / (width * camState.scale) : 0.5;
    const v = (height > 0 && camState.scale > 0) ? (canvas.height * 0.5 - camState.offsetY) / (height * camState.scale) : 0.5;
    return { u, v };
  }

  function clampScale(sc) {
    const { width } = getWorldSize();
    const minScale = Math.min(0.06 * dpr, (canvas.width * 0.5) / Math.max(1, width));
    const maxScale = 8.0 * dpr;
    return Math.min(maxScale, Math.max(minScale, sc));
  }

  function animateCamera(targetScale, cu, cv, ms, keepCentre = false) {
    camCtrl.flyTo(cu, cv, targetScale, { ms, keepCentre, instant: !(ms > 0) });
    updateZoomReadout();
    scheduleDraw();
  }

  function pendingScale() {
    return camCtrl.getTargetScale();
  }

  function zoomPreset(cssZoom) {
    if (followTarget) {
      camState.scale = clampScale(cssZoom * dpr);
      camState.targetScale = camState.scale;
      updateZoomReadout();
      scheduleDraw();
      return;
    }
    const c = getCenterUV();
    camCtrl.flyTo(c.u, c.v, cssZoom * dpr, { ms: 340, keepCentre: true, noArc: true });
    updateZoomReadout();
    scheduleDraw();
  }

  function zoomStep(factor) {
    const c = getCenterUV();
    camCtrl.flyTo(c.u, c.v, pendingScale() * factor, { ms: followTarget ? 0 : 240, keepCentre: true, noArc: true });
    updateZoomReadout();
    scheduleDraw();
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
      camCtrl.flyTo(0.5, 0.5, target, { ms: 340, noArc: true });
      updateZoomReadout();
      scheduleDraw();
      return;
    }
    camCtrl.setView(0.5, 0.5, target, { unclamped: true, skipClamp: true });
    updateZoomReadout();
    scheduleDraw();
  }

  function zoomAt(factor, cx, cy, exactScale = null) {
    const { width, height } = getWorldSize();
    if (!width || !height) return;
    camCtrl.cancelMotion();
    const prevScale = camState.scale;
    camState.scale = exactScale !== null
      ? clampScale(exactScale * dpr)
      : clampScale(camState.scale * factor);
    camState.targetScale = camState.scale;

    const wx = (cx - camState.offsetX) / prevScale;
    const wy = (cy - camState.offsetY) / prevScale;
    camState.offsetX = cx - wx * camState.scale;
    camState.offsetY = cy - wy * camState.scale;
    clampOffsets();
    updateZoomReadout();
    scheduleDraw();
  }

  function panBy(dx, dy) {
    if (followTarget) setFollowMode(null);
    camCtrl.panBy(dx, dy);
    scheduleDraw();
  }

  function updateZoomReadout() {
    const el = document.getElementById('zoom-readout');
    if (el) {
      const cs = cssScale();
      let txt;
      if (cs >= 0.98) {
        const rounded = Math.abs(cs - Math.round(cs)) < 0.03 ? Math.round(cs) : cs.toFixed(2);
        txt = `${rounded}× px`;
      } else {
        txt = `${Math.round(cs * 100)}%`;
      }
      if (txt !== lastZoomReadoutText) {
        lastZoomReadoutText = txt;
        el.textContent = txt;
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
    const fallbackW = (meta && meta.canvas_width) || (animData && animData.canvas_width) || 28024;
    const fallbackMpp = (meta && meta.camera && meta.camera.mpp) || (animData && animData.mpp) || 0.11;
    const mpp = (mf && mf.mpp ? mf.mpp : fallbackMpp) * (mf && mf.width ? 1 : fallbackW / Math.max(1, world.width));
    const metresPerCssPx = mpp / Math.max(1e-6, cssScale());
    const minM = metresPerCssPx * 64;
    const pow = Math.pow(10, Math.floor(Math.log10(minM)));
    let nice = pow;
    for (const m of [1, 2, 5, 10]) {
      if (m * pow >= minM) { nice = m * pow; break; }
    }
    const px = Math.round(nice / metresPerCssPx);
    const lbl = nice >= 1000 ? `${nice / 1000} km` : `${nice} m`;
    if (px !== lastScaleBarPx) {
      lastScaleBarPx = px;
      bar.style.width = `${px}px`;
    }
    if (lbl !== lastScaleBarLabel) {
      lastScaleBarLabel = lbl;
      label.textContent = lbl;
    }
  }

  function draw(nowMs = performance.now(), simTimeSec = null) {
    needsDraw = false;
    ctx.fillStyle = MODE_BACKDROPS[currentMode] || '#141c2b';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // While awaiting the next mode's overview/manifest, hold the previous mode's
    // snapshot at full opacity so rapid mode switches never flash a solid backdrop.
    if (modeFade && !modeFade.ready && modeFadeCanvas && fixedAnimTime === null) {
      ctx.drawImage(modeFadeCanvas, 0, 0, canvas.width, canvas.height);
      return false;
    }

    const ov = overviewImages[currentMode];
    const { width, height, tiled, mf } = getWorldSize();
    if (!ov && !tiled) {
      if (modeFade && modeFadeCanvas && fixedAnimTime === null) {
        ctx.drawImage(modeFadeCanvas, 0, 0, canvas.width, canvas.height);
      }
      return false;
    }

    const moving = camCtrl.isMoving();
    const scale = camState.scale;
    const offsetX = camState.offsetX;
    const offsetY = camState.offsetY;
    const snapInt = !moving && scale >= 0.95 && Math.abs(scale - Math.round(scale)) < 0.02;

    const destX = snapInt ? Math.round(offsetX) : offsetX;
    const destY = snapInt ? Math.round(offsetY) : offsetY;
    const destW = snapInt ? Math.round(width * scale) : (width * scale);
    const destH = snapInt ? Math.round(height * scale) : (height * scale);

    // 1. Always draw exact LANCZOS overview image underneath (zero blank flashes)
    ctx.imageSmoothingQuality = moving ? 'low' : 'high';
    if (ov) {
      const ovRatio = width / ov.width;
      ctx.imageSmoothingEnabled = moving || (scale * ovRatio) < 0.95;
      ctx.drawImage(ov, destX, destY, destW, destH);
    }

    // 2. Stream 2-level lossless WebP tile pyramid via async ImageBitmap tile manager
    const speedPxPerSec = Math.hypot(camState.vx, camState.vy);
    const tileRes = tileMgr.drawTiles(ctx, {
      width: canvas.width,
      height: canvas.height,
      offsetX,
      offsetY,
      scale,
      targetScale: camCtrl.getTargetScale(),
      worldW: width,
      worldH: height,
      overview: ov,
      moving,
      speedPxPerSec,
      vx: camState.vx,
      vy: camState.vy,
      fixedAnimTime,
      nowMs,
    }, { mode: currentMode });

    lastTileLevel = tileRes.tileLevel;
    lastTilesLoaded = tileRes.tilesLoaded;

    if (lodStatusEl) {
      let nextLodText;
      if (tileRes.needTiles) {
        const mppStr = tileRes.activeMpp ? formatMppCm(tileRes.activeMpp) : 'HD';
        nextLodText = tileRes.tilesLoaded < tileRes.tilesVisible
          ? `Streaming ${mppStr} HD Tiles (${tileRes.tilesLoaded}/${tileRes.tilesVisible})…`
          : `Ultra-HD ${mppStr} Pixel Art Active (${scale >= 1 ? scale.toFixed(1) + '×' : Math.round(scale * 100) + '%'})`;
      } else {
        nextLodText = 'Drag / Arrows to Pan · Scroll / Pinch to Zoom Close';
      }
      if (nextLodText !== lastLodText) {
        lastLodText = nextLodText;
        lodStatusEl.textContent = nextLodText;
      }
    }

    if (animData) {
      const animSec = simTimeSec !== null ? simTimeSec : getAnimTimeSec();
      // If draw() was called synchronously outside frameTick (e.g. boot/resize), ensure sim is up to date
      if (simTimeSec === null && livingInitialized) {
        livingEngine.update(animSec, 0.016, currentMode);
      }
      if (showAnimations) {
        drawAnimations(width, height, animSec);
      }
    }

    drawSelectionMarker(width, height);

    // Smooth 220 ms preset crossfade overlay (bypassed when fixedAnimTime !== null)
    let modeFading = false;
    if (modeFade && modeFade.ready && modeFadeCanvas && fixedAnimTime === null) {
      const t = (nowMs - modeFade.startMs) / modeFade.durationMs;
      if (t < 1.0) {
        const prevAlpha = ctx.globalAlpha;
        ctx.globalAlpha = Math.max(0, 1.0 - t);
        ctx.drawImage(modeFadeCanvas, 0, 0, canvas.width, canvas.height);
        ctx.globalAlpha = prevAlpha;
        modeFading = true;
      } else {
        modeFade = null;
      }
    }

    updatePins(width, height);
    drawMinimap(ov, width, height);
    if (showLoupe) drawLoupe(ov, width, height, tiled, mf);

    const nowStamp = performance.now();
    renderStamps.push(nowStamp);
    while (renderStamps.length && nowStamp - renderStamps[0] > 1000) renderStamps.shift();

    return tileRes.crossfading || modeFading;
  }

  // Gold diamond reticle on inspected building, or teal tracking reticle on inspected moving entity.
  function drawSelectionMarker(worldW, worldH) {
    const scale = camState.scale;
    const offsetX = camState.offsetX;
    const offsetY = camState.offsetY;
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
      const liveList = livingEngine._inspectables || [];
      const live = liveList.find((e) => e.id === selectedEntity.id) || selectedEntity;
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
    const scale = camState.scale;
    const offsetX = camState.offsetX;
    const offsetY = camState.offsetY;
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
      // Dirty-check & GPU-composited translate3d() positioning (zero Blink layout/paint thrash).
      const key = vis ? `${Math.round(sx * 2)}|${Math.round(sy * 2)}` : (isDecluttered ? 'decluttered' : 'hidden');
      if (pin._key !== key) {
        pin._key = key;
        if (vis) {
          pin.style.transform = `translate3d(${sx.toFixed(1)}px, ${sy.toFixed(1)}px, 0) translate(-50%, -100%)`;
          if (pin.style.display !== 'block') pin.style.display = 'block';
        } else {
          if (pin.style.display !== 'none') pin.style.display = 'none';
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

  // Minimap: cache the scaled overview once per mode/size; dirty-check camera so idle animation frames skip redraw.
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
      lastMinimapKey = '';
    }
  }

  function drawMinimap(ov, worldW, worldH) {
    if (!minimapCtx || !ov) return;
    const mw = minimapCanvas.width;
    const mh = minimapCanvas.height;
    const scale = camState.scale;
    const offsetX = camState.offsetX;
    const offsetY = camState.offsetY;
    const mmKey = `${currentMode}|${mw}|${mh}|${Math.round(offsetX)}|${Math.round(offsetY)}|${scale.toFixed(5)}|${canvas.width}|${canvas.height}`;
    if (mmKey === lastMinimapKey && minimapBase && minimapBase.ov === ov) return;
    lastMinimapKey = mmKey;

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
    const scale = camState.scale;
    const offsetX = camState.offsetX;
    const offsetY = camState.offsetY;
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
          const tImg = tileMgr.getTileImage(currentMode, 'l2', c, r, '');
          if (tImg) {
            const dx = (c * ts - sx0) * mag;
            const dy = (r * ts - sy0) * mag;
            const tw = tImg.width || tImg.naturalWidth || ts;
            const th = tImg.height || tImg.naturalHeight || ts;
            loupeCtx.drawImage(tImg, dx, dy, tw * mag, th * mag);
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
    loupeCanvas.style.transform = `translate3d(${lx.toFixed(1)}px, ${ly.toFixed(1)}px, 0)`;
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
    if (!showAnimations || !livingInitialized) return false;
    const rect = viewport.getBoundingClientRect();
    const best = livingEngine.hitTest(clientX, clientY, rect, getCamState(), wasFollowing);
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
    const u = (mx - camState.offsetX) / (width * camState.scale);
    const v = (my - camState.offsetY) / (height * camState.scale);
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
  // Unified Pointer Pan (with iOS Flick Inertia) + Multi-Touch Pinch + Minimap Drag
  // ---------------------------------------------------------------------------
  const activePointers = new Map();
  let gestureMovedDist = 0;
  let downTarget = null;
  let isSingleDragging = false;

  viewport.addEventListener('contextmenu', (e) => e.preventDefault());

  viewport.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.viewport-ui') || e.target.closest('.exit-cinema-btn')) return;
    pointerDownFollow = followTarget;
    if (followTarget) setFollowMode(null);
    camCtrl.cancelMotion();
    e.preventDefault();
    viewport.focus({ preventScroll: true });
    if (activePointers.size === 0) {
      gestureMovedDist = 0;
      downTarget = e.target;
      isSingleDragging = true;
      camCtrl.beginDrag(e.clientX * dpr, e.clientY * dpr, performance.now());
    } else {
      isSingleDragging = false;
      camCtrl.endDrag(performance.now());
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
      if (isSingleDragging) {
        camCtrl.moveDrag(e.clientX * dpr, e.clientY * dpr, performance.now());
        scheduleDraw();
      } else {
        panBy(dx * dpr, dy * dpr);
      }
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
      camState.offsetX += (newMidX - prevMidX) * dpr;
      camState.offsetY += (newMidY - prevMidY) * dpr;
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
      if (isSingleDragging) {
        isSingleDragging = false;
        if (gestureMovedDist >= 5) {
          camCtrl.endDrag(performance.now());
          scheduleDraw();
        } else {
          camCtrl.cancelMotion();
          scheduleDraw();
        }
      }
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

  // Wheel / Trackpad: log-space smooth pinch-zoom, smooth scroll-zoom, or two-finger pan
  viewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const cx = (e.clientX - rect.left) * dpr;
    const cy = (e.clientY - rect.top) * dpr;

    // Pinch-to-zoom on trackpad sets ctrlKey = true
    if (e.ctrlKey || e.metaKey) {
      camCtrl.wheelZoom(e.deltaY, e.deltaMode, true, cx, cy);
      updateZoomReadout();
      scheduleDraw();
      return;
    }

    const lineMult = e.deltaMode === 1 ? 16 : (e.deltaMode === 2 ? window.innerHeight : 1);
    const dx = e.deltaX * lineMult;
    const dy = e.deltaY * lineMult;

    // Pan when wheelMode === 'pan', Shift is held, or user swipes horizontally/diagonally on a trackpad
    const isTrackpad2DPan = Math.abs(dx) > 1.5 && Math.abs(dx) > Math.abs(dy) * 0.4;
    if (wheelMode === 'pan' || e.shiftKey || isTrackpad2DPan) {
      panBy(-dx * dpr, -dy * dpr);
    } else {
      camCtrl.wheelZoom(e.deltaY, e.deltaMode, false, cx, cy);
      updateZoomReadout();
      scheduleDraw();
    }
  }, { passive: false });

  // Interactive Minimap click & drag to pan anywhere immediately!
  let minimapDragging = false;
  function panFromMinimap(clientX, clientY) {
    if (followTarget) setFollowMode(null);
    camCtrl.cancelMotion();
    const rect = minimapCanvas.getBoundingClientRect();
    const u = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const v = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    const { width, height } = getWorldSize();
    camState.offsetX = canvas.width * 0.5 - u * width * camState.scale;
    camState.offsetY = canvas.height * 0.5 - v * height * camState.scale;
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
    const cu = ((e.clientX - rect.left) * dpr - camState.offsetX) / (width * camState.scale);
    const cv = ((e.clientY - rect.top) * dpr - camState.offsetY) / (height * camState.scale);
    camCtrl.flyTo(Math.min(1, Math.max(0, cu)), Math.min(1, Math.max(0, cv)), pendingScale() * 2, { ms: 360, noArc: true });
    scheduleDraw();
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

  // Continuous Keyboard Pan (Arrows / WASD), Zoom (+ / - / 0) & Masterpiece Shortcuts
  window.addEventListener('keydown', (e) => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'Shift') {
      camCtrl.setHeldKey('Shift', true);
      return;
    }
    if (
      e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'ArrowUp' || e.key === 'ArrowDown'
      || e.key === 'a' || e.key === 'A' || e.key === 'd' || e.key === 'D'
      || e.key === 'w' || e.key === 'W' || e.key === 's' || e.key === 'S'
    ) {
      e.preventDefault();
      if (followTarget) setFollowMode(null);
      camCtrl.setHeldKey('Shift', !!e.shiftKey);
      camCtrl.setHeldKey(e.code || e.key, true);
      scheduleDraw();
      return;
    }
    if (e.key === '=' || e.key === '+') { e.preventDefault(); zoomStep(1.35); }
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

  window.addEventListener('keyup', (e) => {
    if (e.key === 'Shift') {
      camCtrl.setHeldKey('Shift', false);
      return;
    }
    camCtrl.setHeldKey(e.code || e.key, false);
  });
  window.addEventListener('blur', () => {
    camCtrl.clearHeldKeys();
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
  }

  async function switchLightingMode(nextMode) {
    if (!['day', 'sunset', 'night'].includes(nextMode)) return;
    if (nextMode === currentMode) return;
    const myGen = ++modeSwitchGen;
    if (!modeSwitchAnchor) {
      const prevWorld = getWorldSize();
      const centerU = ((canvas.width / 2) - camState.offsetX) / (camState.scale * prevWorld.width);
      const centerV = ((canvas.height / 2) - camState.offsetY) / (camState.scale * prevWorld.height);
      const relZoom = camState.scale * prevWorld.width;
      modeSwitchAnchor = { centerU, centerV, relZoom };
    }
    camCtrl.cancelMotion();

    // Snapshot previous canvas for smooth 220 ms crossfade (bypassed when fixedAnimTime !== null).
    // Preserve the original settled snapshot across overlapping rapid mode switches.
    if (fixedAnimTime === null && canvas.width > 0 && canvas.height > 0) {
      if (!modeFade || modeFade.ready) {
        if (!modeFadeCanvas) modeFadeCanvas = document.createElement('canvas');
        if (modeFadeCanvas.width !== canvas.width || modeFadeCanvas.height !== canvas.height) {
          modeFadeCanvas.width = canvas.width;
          modeFadeCanvas.height = canvas.height;
        }
        const fctx = modeFadeCanvas.getContext('2d');
        fctx.drawImage(canvas, 0, 0);
      }
      modeFade = { startMs: 0, durationMs: 220, ready: false };
    } else {
      modeFade = null;
    }

    document.querySelectorAll('.seg-btn').forEach((b) => {
      b.classList.toggle('active', b.dataset.mode === nextMode);
    });
    currentMode = nextMode;
    tileMgr.setMode(currentMode);
    document.body.dataset.mode = currentMode;
    if (animData && livingInitialized) {
      livingEngine.update(getAnimTimeSec(), 0.016, currentMode);
    }
    // Recompute audio gain targets immediately (crickets/birds balance) rather than waiting for the throttle
    audioEngine.forceUpdate();
    viewport.classList.add('mode-switching');
    await Promise.all([loadModeOverview(nextMode), loadTileManifest(nextMode)]);
    if (myGen !== modeSwitchGen) return;
    viewport.classList.remove('mode-switching');

    const anchor = modeSwitchAnchor;
    modeSwitchAnchor = null;
    const nextWorld = getWorldSize();
    if (anchor) {
      const nextScale = anchor.relZoom / nextWorld.width;
      camState.scale = nextScale;
      camState.targetScale = nextScale;
      camState.offsetX = (canvas.width / 2) - anchor.centerU * nextWorld.width * nextScale;
      camState.offsetY = (canvas.height / 2) - anchor.centerV * nextWorld.height * nextScale;
    }
    if (modeFade) {
      modeFade.startMs = performance.now();
      modeFade.ready = true;
    }
    updateZoomReadout();
    scheduleDraw();
  }

  const clockTimeEl = document.getElementById('clock-time');
  const clockTzEl = document.getElementById('clock-tz');
  const clockDotEl = document.getElementById('clock-dot');
  const clockScrubEl = document.getElementById('clock-scrub');
  const btnClockLiveEl = document.getElementById('btn-clock-live');
  const clockToggleBtn = document.getElementById('clock-pill-toggle');
  const clockScrubPanel = document.getElementById('clock-scrub-panel');

  function updateClockHud(force = false, snapOverride = null) {
    const snap = snapOverride || livingRuntime.getClockSnapshot(getAnimTimeSec());
    if (!snap) return;
    const hudKey = `${snap.formattedHHMM}|${snap.tzLabel}|${snap.clockMode}`;
    if (!force && hudKey === lastClockHudKey) return;
    lastClockHudKey = hudKey;
    if (clockTimeEl) clockTimeEl.textContent = snap.formattedHHMM;
    if (clockTzEl) clockTzEl.textContent = snap.tzLabel;
    if (clockDotEl) {
      clockDotEl.classList.toggle('live', snap.clockMode === 'live');
      clockDotEl.classList.toggle('manual', snap.clockMode === 'manual');
      clockDotEl.classList.toggle('deterministic', snap.clockMode === 'deterministic');
    }
    if (clockScrubEl && document.activeElement !== clockScrubEl) {
      clockScrubEl.value = String((snap.hours * 60) + snap.minutes);
    }
    if (btnClockLiveEl) {
      btnClockLiveEl.classList.toggle('active', snap.clockMode === 'live');
    }
  }

  function syncClockMutation(triggerAutoPreset = true) {
    const tNow = getAnimTimeSec();
    const snap = kilchbergClock.sample(Date.now(), tNow);
    if (livingEngine._ctx) {
      livingEngine._ctx.clock = snap;
    }
    if (triggerAutoPreset && fixedAnimTime === null && snap.effectivePreset && snap.effectivePreset !== currentMode) {
      switchLightingMode(snap.effectivePreset);
    } else if (animData && livingInitialized) {
      livingEngine.update(tNow, 0.016, currentMode);
    }
    updateClockHud(true, snap);
    scheduleDraw();
    return snap;
  }

  if (clockToggleBtn && clockScrubPanel) {
    clockToggleBtn.addEventListener('click', () => {
      const hidden = clockScrubPanel.classList.toggle('hidden');
      clockToggleBtn.setAttribute('aria-expanded', hidden ? 'false' : 'true');
    });
  }
  if (clockScrubEl) {
    clockScrubEl.addEventListener('input', () => {
      kilchbergClock.setMode('manual');
      kilchbergClock.setPresetOverride('auto');
      kilchbergClock.setManualMinutes(Number(clockScrubEl.value));
      syncClockMutation(true);
    });
  }
  if (btnClockLiveEl) {
    btnClockLiveEl.addEventListener('click', () => {
      kilchbergClock.setMode('live');
      kilchbergClock.setPresetOverride('auto');
      syncClockMutation(true);
    });
  }

  specRegistry.onChange('*', () => {
    if (animData && livingInitialized) {
      livingEngine.update(getAnimTimeSec(), 0.016, currentMode);
    }
    scheduleDraw();
    if (showAnimations && animData && fixedAnimTime === null) {
      startAnimLoop();
    }
  });

  document.querySelectorAll('.seg-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const nextMode = btn.dataset.mode;
      if (!['day', 'sunset', 'night'].includes(nextMode)) return;
      kilchbergClock.setPresetOverride(nextMode);
      const snap = kilchbergClock.sample(Date.now(), getAnimTimeSec());
      if (livingEngine._ctx) livingEngine._ctx.clock = snap;
      updateClockHud(true, snap);
      await switchLightingMode(nextMode);
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
    return {
      scale: camState.scale,
      offsetX: camState.offsetX,
      offsetY: camState.offsetY,
      width: canvas.width,
      height: canvas.height,
      dpr,
    };
  }

  function drawAnimations(worldW, worldH, tSec) {
    if (!livingInitialized) return;
    livingEngine.draw(ctx, getCamState(), worldW, worldH, tSec, currentMode, fixedAnimTime);
  }

  const audioEngine = createAudioEngine({
    assetVer: ASSET_VER,
    getCamera: () => getCamState(),
    getMode: () => currentMode,
    getWorldSize: () => getWorldSize(),
    getAnimData: () => animData,
    getTrafficSim: () => (livingEngine._ctx && livingEngine._ctx.shared ? livingEngine._ctx.shared.trafficSim : null),
    getLivingAudioSignals: (worldW, worldH, tSec, mode) => (
      livingInitialized ? livingEngine.getAudioSignals(worldW, worldH, tSec, mode) : []
    ),
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
    return fixedAnimTime !== null ? fixedAnimTime : liveAnimSec;
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
      updateFollowCamera(getAnimTimeSec(), true, 0.016, true);
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

  function updateFollowCamera(tSec, snap, dt = 0.016, stepSimIfNeeded = false) {
    if (!followTarget || !animData || !livingInitialized) return;
    const { width: worldW, height: worldH } = getWorldSize();
    if (stepSimIfNeeded) {
      livingEngine.update(tSec, dt, currentMode);
    }
    const targetPos = livingEngine.getFollowTarget(followTarget, worldW, worldH);
    if (!targetPos) return;
    const desiredX = canvas.width * 0.5 - targetPos.wx * camState.scale;
    const desiredY = canvas.height * 0.5 - targetPos.wy * camState.scale;
    const jumpDist = Math.hypot(desiredX - camState.offsetX, desiredY - camState.offsetY);
    if (snap || jumpDist > canvas.width * 0.8) {
      camState.offsetX = desiredX;
      camState.offsetY = desiredY;
      clampOffsets();
    } else {
      camCtrl.followStep(desiredX, desiredY, dt);
    }
  }

  function recordFrameTiming(frameMs) {
    if (!(frameMs > 0 && frameMs < 1000)) return;
    lastFrameMs = frameMs;
    if (frameMs > 28) droppedFrames++;
    frameDurations.push(frameMs);
    if (frameDurations.length > MAX_FRAME_SAMPLES) frameDurations.shift();
    if (frameDurations.length >= 4) {
      const sorted = frameDurations.slice().sort((a, b) => a - b);
      const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
      p95FrameMs = sorted[idx];
    } else {
      p95FrameMs = frameMs;
    }
  }

  // Single unified 60fps requestAnimationFrame loop (guarantees <= 1 pending rAF at all times)
  function startAnimLoop() {
    if (!rafId && !document.hidden) {
      lastRafTs = 0;
      rafId = requestAnimationFrame(frameTick);
    }
  }

  function stopAnimLoop() {
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
    lastRafTs = 0;
  }

  function frameTick(nowMs) {
    rafId = 0;
    if (document.hidden) {
      lastRafTs = 0;
      return;
    }
    const frameMs = lastRafTs > 0 ? (nowMs - lastRafTs) : 16.67;
    lastRafTs = nowMs;
    const dt = Math.max(0.001, Math.min(0.05, frameMs * 0.001));

    const { width: worldW, height: worldH } = getWorldSize();
    const camChanged = camCtrl.step(dt, nowMs, {
      vpW: canvas.width || 1,
      vpH: canvas.height || 1,
      worldW,
      worldH,
      dpr,
    });
    if (camChanged) {
      updateZoomReadout();
    }

    // Step modular LivingEngine ONCE per frame (pedestrians -> traffic -> remaining plugins)
    let animSec = null;
    if (animData && livingInitialized) {
      if (fixedAnimTime === null && showAnimations) {
        liveAnimSec += dt;
      }
      animSec = getAnimTimeSec();
      livingEngine.update(animSec, dt, currentMode);
      const clockSnap = livingRuntime.getClockSnapshot(animSec);
      updateClockHud(false, clockSnap);
      if (fixedAnimTime === null && clockSnap && clockSnap.effectivePreset && clockSnap.effectivePreset !== currentMode) {
        switchLightingMode(clockSnap.effectivePreset);
      }
      if (followTarget) {
        updateFollowCamera(animSec, false, dt, false);
      }
    }

    const activeFades = draw(nowMs, animSec);
    recordFrameTiming(frameMs);

    const keepRunning = (showAnimations && !!animData && fixedAnimTime === null)
      || camCtrl.isAnimating()
      || activeFades
      || needsDraw;
    if (keepRunning && !document.hidden) {
      rafId = requestAnimationFrame(frameTick);
    } else {
      lastRafTs = 0;
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
      camCtrl.clearHeldKeys();
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

  window.addEventListener('resize', () => resizeViewport());
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
  const initMode = fixedAnimTime !== null
    ? (explicitMode || 'day')
    : (explicitMode || initClockSnap.effectivePreset || 'day');
  // Always normalise the preset (malformed ?mode= falls back to live solar preset or day under ?t=)
  currentMode = initMode;
  tileMgr.setMode(currentMode);
  document.body.dataset.mode = currentMode;
  document.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === currentMode));
  updateClockHud(true, initClockSnap);
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

  // ---- Instant address & landmark search (1,887 swisstopo addresses + 16 landmarks)
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
      safeReplaceState(link);
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
      livingEngine.init(animData, meta, depthMgr);
      livingInitialized = true;
      if (fixedAnimTime !== null) {
        livingRuntime.warmupToTime(fixedAnimTime, currentMode);
      } else {
        livingEngine.update(0, 0.016, currentMode);
      }
    }
    populateSidebar();
    resizeViewport(true);
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
      const cu = Number.isFinite(qU) ? Math.min(1, Math.max(0, qU)) : 0.5;
      const cv = Number.isFinite(qV) ? Math.min(1, Math.max(0, qV)) : 0.5;
      camCtrl.setView(cu, cv, clampScale(qZoom * dpr));
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
    // Preload remaining lighting modes after initial viewport tiles settle (avoids saturating boot bandwidth)
    setTimeout(() => {
      for (const m of ['day', 'sunset', 'night']) {
        if (m !== currentMode) {
          loadModeOverview(m);
          loadTileManifest(m);
        }
      }
    }, 600);
  });

  // Non-intrusive read-only telemetry snapshot (PROJECT.md § Interface Contracts)
  Object.defineProperty(window, '__dioramaDebug', {
    configurable: true,
    enumerable: false,
    get() {
      const { u: cu, v: cv } = getCenterUV();
      const tNow = getAnimTimeSec();
      const fallbackBell = evalBellState(tNow, currentMode).bellPhase;
      const simStats = livingInitialized
        ? livingEngine.getSimStats()
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
          pedVehicleOverlapCount: 0,
          cyclists: 0,
        };
      const tStats = tileMgr.getStats();
      const cssZoom = camState.scale / dpr;
      const lrStats = livingEngine.getEngineStats();
      const clockSnap = livingRuntime.getClockSnapshot(tNow);
      return {
        mode: currentMode,
        zoom: cssZoom,
        scale: cssZoom,
        u: cu,
        v: cv,
        offsetX: camState.offsetX,
        offsetY: camState.offsetY,
        dpr,
        tileLevel: lastTileLevel,
        tilesLoaded: lastTilesLoaded,
        animEnabled: showAnimations,
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
        livingCounts: livingEngine.getLivingCounts(),
        simStats,
        clock: {
          ...clockSnap,
          setMode(mode) {
            const res = kilchbergClock.setMode(mode);
            syncClockMutation(true);
            return res;
          },
          setManualMinutes(minutesOfDay) {
            const res = kilchbergClock.setManualMinutes(minutesOfDay);
            syncClockMutation(true);
            return res;
          },
          setPresetOverride(preset) {
            const res = kilchbergClock.setPresetOverride(preset);
            syncClockMutation(true);
            return res;
          },
          setSpeedMultiplier(mult) {
            const res = kilchbergClock.setSpeedMultiplier(mult);
            syncClockMutation(false);
            return res;
          },
        },
        specs: specRegistry,
        railTelemetry: livingRuntime.getRailTelemetry(),
        sportsTelemetry: livingRuntime.getSportsTelemetry(),
        vesselTelemetry: livingRuntime.getVesselTelemetry(),
        livingRegistry: {
          ...lrStats,
          register(plugin) {
            livingEngine.register(plugin);
            if (animData && livingInitialized) {
              livingEngine.update(getAnimTimeSec(), 0.016, currentMode);
            }
            scheduleDraw();
            if (showAnimations && animData) startAnimLoop();
            return true;
          },
          unregister(id) {
            const removed = livingEngine.unregister(id);
            scheduleDraw();
            return removed;
          },
          setEnabled(id, enabled) {
            const ok = livingEngine.setEnabled(id, enabled);
            scheduleDraw();
            return ok;
          },
        },
        frameStats: {
          fps: renderStamps.length,
          p95FrameMs: Number(p95FrameMs.toFixed(2)),
          lastFrameMs: Number(lastFrameMs.toFixed(2)),
          droppedFrames,
          tileInflight: tStats.inflight,
          tileCacheSize: tStats.cacheSize,
          camSpeedPxPerSec: Number(Math.hypot(camState.vx, camState.vy).toFixed(1)),
          rafActive: rafId !== 0,
        },
      };
    },
  });
