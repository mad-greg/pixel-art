(() => {
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

  const CROPS = [
    { file: '01_lindt_home_of_chocolate.webp', label: 'Lindt Home of Chocolate', lmId: 'lindt_hoc' },
    { file: '02_reformierte_kirche_dorf.webp', label: 'Reformierte Kirche & Graves', lmId: 'reformierte_kirche' },
    { file: '03_bendlikon_harbor_pier.webp', label: 'Bendlikon Pier & Sailboats', lmId: 'bendlikon_pier' },
    { file: '04_bahnhof_kilchberg_weinberg.webp', label: 'Bahnhof & Dorfstrasse Viaduct', lmId: 'bahnhof_stockengut' },
    { file: '05_schooren_seebad.webp', label: 'Schooren & Seebad', lmId: 'schooren_seebad' },
    { file: '06_sanatorium_ridge.webp', label: 'Sanatorium Kilchberg', lmId: 'sanatorium_ridge' },
  ];

  const ASSET_VER = '7.0';

  // Overview images, ultra-high-res 0.25 m/px tile pyramids & 16-bit 3D Depth Map for pixel-exact partial occlusion
  const overviewImages = {};
  const tileManifests = {};   // mode -> { width, height, tileSize, cols, rows, mpp } | null
  const tileCache = {};       // "mode:c:r" -> HTMLImageElement | 'loading' | 'error'
  let depthPixels = null;     // Uint8ClampedArray (R/G = 16-bit scene depth, B = 255 if 3D occluder)
  let depthW = 0;
  let depthH = 0;
  let waterMask = null;       // Uint8Array (1 = eroded pure open water, 0 = shore/rock/boat/pier/land)
  let waterW = 0;
  let waterH = 0;

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

    if (showAnimations && animData) {
      const animSec = fixedAnimTime !== null ? fixedAnimTime : performance.now() * 0.001;
      drawAnimations(width, height, animSec);
    }

    drawSelectionMarker(width, height);
    updatePins(width, height);
    drawMinimap(ov, width, height);
    if (showLoupe) drawLoupe(ov, width, height, tiled, mf);

    const nowStamp = performance.now();
    renderStamps.push(nowStamp);
    while (renderStamps.length && nowStamp - renderStamps[0] > 1000) renderStamps.shift();
  }

  // Gold diamond reticle on the inspected building (aspect-correct, scaled for HiDPI).
  function drawSelectionMarker(worldW, worldH) {
    if (!selectedBuilding) return;
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
  }

  function updatePins(worldW, worldH) {
    if (!meta || !showPins) {
      if (pinsLayer.children.length) pinsLayer.innerHTML = '';
      return;
    }
    if (pinsLayer.children.length !== meta.landmarks.length) {
      pinsLayer.innerHTML = '';
      meta.landmarks.forEach((lm, idx) => {
        const btn = document.createElement('button');
        btn.className = 'lm-pin';
        btn.dataset.lmIdx = String(idx);
        btn.textContent = `${idx + 1}. ${lm.name.split('&')[0].trim()}`;
        pinsLayer.appendChild(btn);
      });
    }
    meta.landmarks.forEach((lm, idx) => {
      const pin = pinsLayer.children[idx];
      const sx = (offsetX + lm.uv[0] * worldW * scale) / dpr;
      const sy = (offsetY + lm.uv[1] * worldH * scale) / dpr;
      const cssW = canvas.width / dpr;
      const cssH = canvas.height / dpr;
      const vis = !(sx < -100 || sx > cssW + 100 || sy < -40 || sy > cssH + 50);
      // Dirty-check so panning/animating never rewrites unchanged pins (avoids layout churn).
      const key = vis ? `${Math.round(sx * 2)}|${Math.round(sy * 2)}` : 'hidden';
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
      const isActive = lm.id === activeLandmarkId;
      if (pin._active !== isActive) {
        pin._active = isActive;
        pin.classList.toggle('active', isActive);
      }
    });
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

  function flyToLandmark(lm, targetZoom = null) {
    if (followTarget) setFollowMode(null);
    const { width, height, tiled } = getWorldSize();
    if (!width || !height) return;
    // Zoom closely so individual windows, roof tiles, trees & boats are crisp (target is CSS px per world px)
    const zoomCss = targetZoom !== null ? targetZoom : (tiled ? 1.5 : 2.2);
    selectedBuilding = null;
    setActiveLandmark(lm.id);
    animateCamera(zoomCss * dpr, lm.uv[0], lm.uv[1], 640);
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
  }

  function showInspector({ title, sub, specs }) {
    document.getElementById('insp-title').textContent = title;
    document.getElementById('insp-sub').textContent = sub;
    const dl = document.getElementById('insp-specs');
    dl.innerHTML = specs
      .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
      .join('');
  }

  function selectBuilding(best) {
    selectedBuilding = best;
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
        } else {
          hitTestBuilding(e.clientX, e.clientY);
        }
      }
      downTarget = null;
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
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
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
      lastAudioUpdateMs = 0;
      if (soundEnabled && soundReady) {
        const w0 = getWorldSize();
        updateSoundscape(w0.width, w0.height, getAnimTimeSec());
      }
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
        const x1 = pts[j][0], y1p = pts[j][1];
        const x2 = pts[i][0], y2p = pts[i][1];
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
    const w = buf.w, h = buf.h, d = buf.data;
    const solid = new Uint8Array(w * h);
    for (let i = 0; i < w * h; i++) {
      const o = i * 4;
      if (d[o + 3] === 255) {
        solid[i] = 1;
        // Preserve emissive pixels marked with alpha 254 before final pass
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

  // Exact 2:1 orthographic isometric ground basis matching IsometricCamera (pitch=30°).
  // Given a screen-space direction (tx, ty), recovers the true un-foreshortened ground unit vector,
  // its 90° perpendicular, and projects both back to screen space so vehicles never shear or gap.
  function makeIsoBasis(cx, cy, tx, ty) {
    const gx = tx;
    const gy = ty * 2.0;
    const gLen = Math.hypot(gx, gy) || 1;
    const ux = gx / gLen;
    const uy = gy / gLen;
    const fx = ux, fy = uy * 0.5;     // Forward unit vector in screen px per world px
    const rx = -uy, ry = ux * 0.5;    // Right-hand perpendicular in screen px per world px
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

    // Side wall
    fillPolyPx(buf, [
      pt(-halfLen, visSide * halfWid, z0),
      pt(halfLen, visSide * halfWid, z0),
      pt(halfLen, visSide * halfWid, z1),
      pt(-halfLen, visSide * halfWid, z1),
    ], colors.side, alpha);

    // Front or rear end wall
    fillPolyPx(buf, [
      pt(visEnd * halfLen, -halfWid, z0),
      pt(visEnd * halfLen, halfWid, z0),
      pt(visEnd * halfLen, halfWid, z1),
      pt(visEnd * halfLen, -halfWid, z1),
    ], colors.front, alpha);

    // Roof
    fillPolyPx(buf, [
      pt(-halfLen, -halfWid, z1),
      pt(halfLen, -halfWid, z1),
      pt(halfLen, halfWid, z1),
      pt(-halfLen, halfWid, z1),
    ], colors.roof, alpha);

    return B;
  }

  function getVehicleSprite(type, variant, angleIdx, mode, angleSteps = 32) {
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
      const cx = 105, cy = 88;
      const nx = -ty * 0.72, ny = tx * 0.52;
      const pt = (s, w, z) => [cx + tx * s + nx * w, cy + ty * s + ny * w - z];

      // Tapered Lake Zurich passenger ship hull
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
        // Classic arched paddlewheel housing cutout + gold trim on visible flank
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

      // Far-side paddlewheel sponson first for accurate painter order
      drawSponson(-salon1Basis.visSide);

      // Main & upper white passenger salon decks
      const salon1 = drawIsoBox(buf, cx - tx * 6, cy - ty * 6, tx, ty, 46.0, 10.2, 8.0, 4.5, {
        roof: [232, 230, 224], side: [216, 214, 208], front: [224, 222, 216],
      }, false, salon1Basis);
      // Near-side paddlewheel sponson over main salon flank
      drawSponson(salon1Basis.visSide);

      const salon2 = drawIsoBox(buf, cx - tx * 4, cy - ty * 4, tx, ty, 32.0, 8.4, 7.0, 12.5, {
        roof: [240, 238, 232], side: [222, 220, 214], front: [228, 226, 220],
      }, false);
      // Wheelhouse & white/buff funnel
      drawIsoBox(buf, cx + tx * 20, cy + ty * 20, tx, ty, 7.0, 6.5, 5.5, 19.5, {
        roof: [238, 236, 230], side: [62, 84, 108], front: [62, 84, 108],
      }, false);
      drawIsoBox(buf, cx + tx * 2, cy + ty * 2, tx, ty, 4.2, 3.6, 9.0, 19.5, {
        roof: [52, 54, 58], side: [226, 198, 134], front: [234, 208, 146],
      }, false);

      // Promenade windows (glowing golden at night!)
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
      // Red-and-white Swiss flag flying at the stern!
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
      const cx = 32, cy = 52;
      const nx = -ty * 0.72, ny = tx * 0.52;
      const pt = (s, w, z) => [cx + tx * s + nx * w, cy + ty * s + ny * w - z];
      // Crisp white hull
      fillPolyPx(buf, [
        pt(-13, -4.2, 0), pt(8, -4.2, 0), pt(16, 0, 1.5), pt(8, 4.2, 0), pt(-13, 4.2, 0),
      ], [230, 228, 222], 255);
      // Tall white triangular mainsail & jib
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
    const cx = 24, cy = 24;
    const nx = -ty * 0.72, ny = tx * 0.52;
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

  // Exact C1-continuous piecewise multi-stop schedule (supports trains, ZSG steamer & VBZ/ZVV buses)
  const stopScheduleCache = new Map();

  function buildStopSchedule(lengthM, speedMps, stops, dwellSec, rampSec = 5.0, offscreenSec = 6.0) {
    const v = Math.max(0.5, speedMps) / Math.max(1.0, lengthM);
    const pause = Math.max(0, dwellSec || 0);
    const ramp = Math.max(0.1, rampSec || 5.0);
    const offSec = Math.max(0, offscreenSec || 0);
    const validStops = (Array.isArray(stops) ? stops : (stops != null ? [stops] : []))
      .filter((s) => typeof s === 'number' && !Number.isNaN(s) && s > 0.001 && s < 0.999)
      .sort((a, b) => a - b);

    const segs = [];
    let tCur = 0;
    let sCur = 0;

    if (validStops.length === 0 || pause <= 0) {
      const dur = 1.0 / v;
      segs.push({ t0: 0, t1: dur, type: 'cruise', s0: 0, s1: 1, stopIdx: -1 });
      tCur = dur;
    } else {
      const K = validStops.length;
      for (let k = 0; k < K; k++) {
        const sk = validStops[k];
        const gapBefore = k === 0 ? sk : 0.5 * (sk - validStops[k - 1]);
        const gapAfter = k === K - 1 ? (1.0 - sk) : 0.5 * (validStops[k + 1] - sk);
        const dsDecel = Math.min(0.5 * v * ramp, 0.9 * gapBefore);
        const tauDecel = dsDecel > 1e-9 ? (2.0 * dsDecel) / v : 0;
        const dsAccel = Math.min(0.5 * v * ramp, 0.9 * gapAfter);
        const tauAccel = dsAccel > 1e-9 ? (2.0 * dsAccel) / v : 0;

        const sDecelStart = Math.max(sCur, sk - dsDecel);
        if (sDecelStart > sCur + 1e-9) {
          const dur = (sDecelStart - sCur) / v;
          segs.push({ t0: tCur, t1: tCur + dur, type: 'cruise', s0: sCur, s1: sDecelStart, stopIdx: -1 });
          tCur += dur;
          sCur = sDecelStart;
        }
        if (tauDecel > 1e-9 && sk > sCur + 1e-9) {
          segs.push({ t0: tCur, t1: tCur + tauDecel, type: 'decel', s0: sCur, s1: sk, stopIdx: k });
          tCur += tauDecel;
          sCur = sk;
        }
        segs.push({ t0: tCur, t1: tCur + pause, type: 'dwell', s0: sk, s1: sk, stopIdx: k });
        tCur += pause;
        if (tauAccel > 1e-9) {
          const sAccelEnd = Math.min(1.0, sk + dsAccel);
          segs.push({ t0: tCur, t1: tCur + tauAccel, type: 'accel', s0: sk, s1: sAccelEnd, stopIdx: k });
          tCur += tauAccel;
          sCur = sAccelEnd;
        }
      }
      if (1.0 > sCur + 1e-9) {
        const dur = (1.0 - sCur) / v;
        segs.push({ t0: tCur, t1: tCur + dur, type: 'cruise', s0: sCur, s1: 1.0, stopIdx: -1 });
        tCur += dur;
      }
    }

    return { segs, activeSec: tCur, cycleSec: tCur + offSec };
  }

  function evalStopSchedule(sched, tSec, phase = 0) {
    const cycle = sched.cycleSec;
    if (!(cycle > 0)) {
      return { frac: -1, speedRatio: 0, isDwelling: false, stopIdx: -1, dwellProgress: 0 };
    }
    const localT = (((tSec + phase * cycle) % cycle) + cycle) % cycle;
    if (localT > sched.activeSec) {
      return { frac: -1, speedRatio: 0, isDwelling: false, stopIdx: -1, dwellProgress: 0 };
    }
    const segs = sched.segs;
    for (let i = 0; i < segs.length; i++) {
      const seg = segs[i];
      if (localT <= seg.t1 || i === segs.length - 1) {
        const dur = Math.max(1e-9, seg.t1 - seg.t0);
        const u = Math.max(0, Math.min(1, (localT - seg.t0) / dur));
        if (seg.type === 'cruise') {
          return { frac: seg.s0 + (seg.s1 - seg.s0) * u, speedRatio: 1.0, isDwelling: false, stopIdx: -1, dwellProgress: 0 };
        }
        if (seg.type === 'decel') {
          return { frac: seg.s0 + (seg.s1 - seg.s0) * (2.0 * u - u * u), speedRatio: 1.0 - u, isDwelling: false, stopIdx: seg.stopIdx, dwellProgress: 0 };
        }
        if (seg.type === 'dwell') {
          return { frac: seg.s0, speedRatio: 0.0, isDwelling: true, stopIdx: seg.stopIdx, dwellProgress: u };
        }
        return { frac: seg.s0 + (seg.s1 - seg.s0) * (u * u), speedRatio: u, isDwelling: false, stopIdx: seg.stopIdx, dwellProgress: 0 };
      }
    }
    return { frac: 1.0, speedRatio: 1.0, isDwelling: false, stopIdx: -1, dwellProgress: 0 };
  }

  function evalWithStationStop(tSec, lengthM, speedMps, stopFracOrStops, dwellSec, phase = 0, rampSec = 5.0, offscreenSec = 6.0) {
    const stopsKey = Array.isArray(stopFracOrStops)
      ? stopFracOrStops.join(',')
      : (stopFracOrStops != null ? String(stopFracOrStops) : '');
    const key = `${lengthM}|${speedMps}|${stopsKey}|${dwellSec || 0}|${rampSec}|${offscreenSec}`;
    let sched = stopScheduleCache.get(key);
    if (!sched) {
      sched = buildStopSchedule(lengthM, speedMps, stopFracOrStops, dwellSec, rampSec, offscreenSec);
      if (stopScheduleCache.size > 256) stopScheduleCache.clear();
      stopScheduleCache.set(key, sched);
    }
    return evalStopSchedule(sched, tSec, phase || 0);
  }

  function evalTrainState(tr, tSec) {
    const nCars = tr.carriages || 4;
    const trainLenM = (nCars - 1) * 19.5 + 18.1; // 76.6 m for 4-car consist
    const halfTrainM = trainLenM * 0.5;          // 38.3 m half-consist
    const effLenM = tr.length_m + trainLenM;
    if (!tr._stopSched) {
      const rawStopFrac = tr.stop_frac != null
        ? (tr.stop_frac * tr.length_m + halfTrainM) / effLenM
        : null;
      tr._stopSched = buildStopSchedule(
        effLenM,
        tr.speed_mps,
        rawStopFrac != null ? [rawStopFrac] : [],
        tr.dwell_sec || 0,
        5.0,
        6.0,
      );
    }
    const st = evalStopSchedule(tr._stopSched, tSec, tr.phase || 0);
    if (st.frac < 0) {
      return { headFrac: -1, midFrac: -1, speedRatio: 0, isDwelling: false, stopIdx: -1, dwellProgress: 0 };
    }
    const headFrac = st.frac * (effLenM / tr.length_m);
    const midFrac = headFrac - halfTrainM / tr.length_m;
    return {
      headFrac,
      midFrac,
      speedRatio: st.speedRatio,
      isDwelling: st.isDwelling,
      stopIdx: st.stopIdx,
      dwellProgress: st.dwellProgress,
    };
  }

  function evalBusState(rd, bIdx, tSec) {
    const busCount = Math.max(1, rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0));
    const laneSpeed = Math.max(1.0, rd.speed_mps * 0.88);
    if (!rd._busSched) {
      rd._busSched = buildStopSchedule(rd.length_m, laneSpeed, rd.stops || [], 2.8, 3.0, 0.0);
    }
    const phase = (rd.phase || 0) + bIdx / busCount;
    return evalStopSchedule(rd._busSched, tSec, phase);
  }

  function samplePathAt(pts, frac, worldW, worldH, tanWin = 3) {
    const n = pts.length;
    if (n < 2 || frac < 0 || frac > 1) return null;
    const fIdx = frac * (n - 1);
    const i0 = Math.min(n - 2, Math.max(0, Math.floor(fIdx)));
    const t = fIdx - i0;
    const p0 = pts[i0];
    const p1 = pts[i0 + 1];
    const wx = (p0[0] + (p1[0] - p0[0]) * t) * worldW;
    const wy = (p0[1] + (p1[1] - p0[1]) * t) * worldH;

    // Wide-chord smooth tangent so multi-carriage trains curve fluidly without wagon snapping!
    const ia = Math.max(0, i0 - tanWin);
    const ib = Math.min(n - 1, i0 + 1 + tanWin);
    let dx = (pts[ib][0] - pts[ia][0]) * worldW;
    let dy = (pts[ib][1] - pts[ia][1]) * worldH;
    const mag = Math.hypot(dx, dy) || 1;
    dx /= mag;
    dy /= mag;
    const occ = (t < 0.5 ? p0[2] : p1[2]) === 1;
    const d16 = p0.length > 3 && p1.length > 3
      ? Math.round(p0[3] + (p1[3] - p0[3]) * t)
      : 0;
    return { wx, wy, tx: dx, ty: dy, occ, d16 };
  }

  function blitWorldSprite(sp, wx, wy, wScale) {
    const drawScale = scale * wScale;
    const sx = Math.round(offsetX + (wx - sp.cx * wScale) * scale);
    const sy = Math.round(offsetY + (wy - sp.cy * wScale) * scale);
    const sw = Math.max(2, Math.round(sp.canvas.width * drawScale));
    const sh = Math.max(2, Math.round(sp.canvas.height * drawScale));
    if (sx + sw < -20 || sx > canvas.width + 20 || sy + sh < -20 || sy > canvas.height + 20) return;
    vCtx.imageSmoothingEnabled = drawScale < 0.65;
    vCtx.drawImage(sp.canvas, sx, sy, sw, sh);
  }

  function drawPixelRectWorld(wx, wy, pw, ph, fillStyle, wScale) {
    const sx = Math.round(offsetX + wx * scale);
    const sy = Math.round(offsetY + wy * scale);
    if (sx < -20 || sx > canvas.width + 20 || sy < -20 || sy > canvas.height + 20) return;
    const sw = Math.max(1, Math.round(pw * wScale * scale));
    const sh = Math.max(1, Math.round(ph * wScale * scale));
    vCtx.fillStyle = fillStyle;
    vCtx.fillRect(sx, sy, sw, sh);
  }

  // ---- CONTINUOUS 3D NW-SUN SHADED VEHICLE RENDERER + PER-PIXEL 3D Z-BUFFER OCCLUSION ----
  // Renders crisp, grounded, smoothly curving 3D isometric vehicles and masks EVERY pixel
  // against the exact 16-bit 3D depth map (kilchberg_depth.png) with row-wise 3-way fast-path!
  let vCtx = ctx;
  const vehScratch = document.createElement('canvas');
  vehScratch.width = 320;
  vehScratch.height = 240;
  const vehScratchCtx = vehScratch.getContext('2d', { willReadFrequently: true });

  const depthFrameStats = { direct: 0, fullCull: 0, partial: 0 };
  const livingFrameCounts = {
    ships: 0, cars: 0, buses: 0, cyclists: 0, roadPeds: 0,
    busStopCommuters: 0, trains: 0, gulls: 0, swans: 0, sups: 0, ducks: 0, redKites: 0,
  };

  function getDepthConstants() {
    const depthMin = (animData && typeof animData.depth_min === 'number') ? animData.depth_min : -2400.0;
    const depthMax = (animData && typeof animData.depth_max === 'number') ? animData.depth_max : 2400.0;
    const mppMaster = (animData && typeof animData.mpp === 'number') ? animData.mpp : 0.25;
    const u16PerM = 65535.0 / Math.max(1.0, depthMax - depthMin);
    const depthSlopeGround = mppMaster * Math.sqrt(3) * u16PerM;
    const shiftY = 2927.412592;
    const c0 = (0 - depthMin) * u16PerM + depthSlopeGround * shiftY;
    const slopeZ = 2.0 * 1.16 * u16PerM;
    return { depthMin, depthMax, mppMaster, u16PerM, depthSlopeGround, c0, slopeZ };
  }

  function evalWalkerD16(wx, wy, zGnd, worldW, worldH, onElevatedDeck = false) {
    const dc = getDepthConstants();
    const masterH = (animData && animData.canvas_height) ? animData.canvas_height : 5444;
    const wyMaster = wy * (masterH / Math.max(1, worldH));
    let d16 = Math.round(dc.c0 - dc.depthSlopeGround * wyMaster - dc.slopeZ * (zGnd - 348.0) - 10);
    if (onElevatedDeck && depthPixels && depthW > 0 && depthH > 0) {
      const dx = Math.min(depthW - 1, Math.max(0, Math.floor((wx / Math.max(1, worldW)) * depthW)));
      const dy = Math.min(depthH - 1, Math.max(0, Math.floor((wy / Math.max(1, worldH)) * depthH)));
      // Sample a small neighbourhood (feet, torso, head rows and +/-3 columns) so a passenger
      // stepping off a deck edge (gangplank over water) is still pinned to the deck behind them.
      // Only pixels within a depth band of the walker's own deck height count, so overhanging
      // trees / foreground buildings (much closer) are never pulled behind the walker.
      const DECK_BAND = 60;
      const DECK_MARGIN = 28; // > 2 * depthSlopeGround headroom + safety, in u16
      const ref = d16;
      let deckMin = Infinity;
      for (let oy = -8; oy <= 1; oy++) {
        const yy = dy + oy;
        if (yy < 0 || yy >= depthH) continue;
        for (let ox = -3; ox <= 3; ox++) {
          const xx = dx + ox;
          if (xx < 0 || xx >= depthW) continue;
          const di = (yy * depthW + xx) * 4;
          if (depthPixels[di + 2] > 128) {
            const deckD16 = (depthPixels[di] << 8) | depthPixels[di + 1];
            if (Math.abs(deckD16 - ref) <= DECK_BAND && deckD16 < deckMin) deckMin = deckD16;
          }
        }
      }
      if (deckMin !== Infinity) d16 = Math.min(d16, deckMin - DECK_MARGIN);
    }
    return d16;
  }

  function drawDepthMasked(wx, wy, boundsOrPadW, vehD16, worldW, worldH, drawFn, clampUpWorld = 4.0) {
    let ex, eyUp, eyDn;
    if (typeof boundsOrPadW === 'object' && boundsOrPadW !== null) {
      ex = boundsOrPadW.ex;
      eyUp = boundsOrPadW.eyUp;
      eyDn = boundsOrPadW.eyDn;
    } else {
      ex = eyUp = eyDn = boundsOrPadW;
    }

    const cx = offsetX + wx * scale;
    const cy = offsetY + wy * scale;
    // Screen-pixel safety pad scales with zoom so overview-zoom bboxes don't grow to tens of metres.
    const padPx = Math.max(1, Math.min(4, Math.ceil(2 * scale)));
    const padX = Math.ceil(ex * scale) + padPx;
    const padUp = Math.ceil(eyUp * scale) + padPx;
    const padDn = Math.ceil(eyDn * scale) + padPx;
    if (cx + padX < 0 || cx - padX > canvas.width || cy + padDn < 0 || cy - padUp > canvas.height) return;

    if (!depthPixels || !vehD16 || depthW <= 0 || depthH <= 0) {
      depthFrameStats.direct++;
      vCtx = ctx;
      drawFn();
      return;
    }

    const x0 = Math.max(0, Math.floor(cx - padX));
    const y0 = Math.max(0, Math.floor(cy - padUp));
    const x1 = Math.min(canvas.width, Math.ceil(cx + padX));
    const y1 = Math.min(canvas.height, Math.ceil(cy + padDn));
    const bw = x1 - x0;
    const bh = y1 - y0;
    if (bw <= 0 || bh <= 0) return;

    const dc = getDepthConstants();
    const depthSlopeGround = dc.depthSlopeGround;
    const masterW = (animData && animData.canvas_width) ? animData.canvas_width : 12331;
    const wScaleInv = masterW / Math.max(1, worldW);
    const invWorldScaleX = depthW / (worldW * scale);
    const invWorldScaleY = depthH / (worldH * scale);

    // Row-wise conservative 3-way pre-check over depthPixels before touching vehScratch or getImageData()
    // Roof/vertical extrusion moves closer to camera, never farther: do not push upward pixels behind
    // the base depth (clampUpWorld retained in the signature for call-site compatibility).
    const upClamp = 0;
    // Pixel loop samples centres up to x1 - 0.5 / y1 - 0.5, so the pre-check must cover the same range.
    const rawDx0 = Math.floor((x0 - offsetX) * invWorldScaleX);
    const rawDx1 = Math.floor((x1 - 0.5 - offsetX) * invWorldScaleX);
    const rawDy0 = Math.floor((y0 - offsetY) * invWorldScaleY);
    const rawDy1 = Math.floor((y1 - 0.5 - offsetY) * invWorldScaleY);
    const dx0 = Math.max(0, rawDx0);
    const dx1 = Math.min(depthW - 1, rawDx1);
    const dy0 = Math.max(0, rawDy0);
    const dy1 = Math.min(depthH - 1, rawDy1);

    if (dx0 > dx1 || dy0 > dy1) {
      // Bbox entirely outside the depth map: nothing can occlude it.
      depthFrameStats.direct++;
      vCtx = ctx;
      drawFn();
      return;
    }
    {
      let anyFrontOcc = false;
      // Parts of the bbox beyond the depth map are never masked, i.e. "clear".
      let anyClear = (rawDx0 < 0 || rawDx1 >= depthW || rawDy0 < 0 || rawDy1 >= depthH);
      const invDepthHWorld = worldH / depthH;
      for (let dy = dy0; dy <= dy1; dy++) {
        const wyTop = dy * invDepthHWorld;
        const wyBot = (dy + 1) * invDepthHWorld;
        const rawTop = (wyTop - wy) * wScaleInv;
        const rawBot = (wyBot - wy) * wScaleInv;
        const effTop = rawTop < -upClamp ? -upClamp : rawTop;
        const effBot = rawBot < -upClamp ? -upClamp : rawBot;
        const rowMaxD16 = vehD16 - effTop * depthSlopeGround;
        const rowMinD16 = vehD16 - effBot * depthSlopeGround;
        const rowOff = dy * depthW;
        for (let dx = dx0; dx <= dx1; dx++) {
          const di = (rowOff + dx) * 4;
          if (depthPixels[di + 2] > 128) {
            const sd = (depthPixels[di] << 8) | depthPixels[di + 1];
            if (sd < rowMaxD16) anyFrontOcc = true;
            if (sd >= rowMinD16) anyClear = true;
          } else {
            anyClear = true;
          }
          if (anyFrontOcc && anyClear) break;
        }
        if (anyFrontOcc && anyClear) break;
      }
      if (!anyFrontOcc) {
        // Fast Path A (Direct): Zero foreground occluders anywhere in bbox!
        depthFrameStats.direct++;
        vCtx = ctx;
        drawFn();
        return;
      }
      if (!anyClear) {
        // Fast Path B (Full Cull): 100% of bbox strictly behind solid foreground occluders!
        depthFrameStats.fullCull++;
        return;
      }
    }

    // Genuine partial occlusion: render to vehScratch (never silently drops at 5x-8x zoom!)
    depthFrameStats.partial++;
    const MAX_SCRATCH = 2048;
    const scratchScale = Math.min(1.0, MAX_SCRATCH / Math.max(bw, bh));
    const sw = Math.min(MAX_SCRATCH, Math.max(1, Math.ceil(bw * scratchScale)));
    const sh = Math.min(MAX_SCRATCH, Math.max(1, Math.ceil(bh * scratchScale)));
    if (sw > vehScratch.width) vehScratch.width = Math.min(MAX_SCRATCH, sw + 32);
    if (sh > vehScratch.height) vehScratch.height = Math.min(MAX_SCRATCH, sh + 32);

    vehScratchCtx.clearRect(0, 0, sw, sh);
    vehScratchCtx.save();
    if (scratchScale < 1.0) vehScratchCtx.scale(scratchScale, scratchScale);
    vehScratchCtx.translate(-x0, -y0);
    vCtx = vehScratchCtx;
    drawFn();
    vehScratchCtx.restore();
    vCtx = ctx;

    const imgData = vehScratchCtx.getImageData(0, 0, sw, sh);
    const d = imgData.data;
    const invScale = 1 / scale;
    const invScratch = 1 / scratchScale;
    let anyVisible = false;

    for (let ly = 0; ly < sh; ly++) {
      const sy = y0 + (ly + 0.5) * invScratch;
      const dy = Math.floor((sy - offsetY) * invWorldScaleY);
      const wyPix = (sy - offsetY) * invScale;
      const dyW = (wyPix - wy) * wScaleInv;
      const effDyW = dyW < -upClamp ? -upClamp : dyW;
      const rowD16 = vehD16 - effDyW * depthSlopeGround;
      const validY = dy >= 0 && dy < depthH;
      const rowOff = dy * depthW;
      const pRow = ly * sw * 4;
      for (let lx = 0; lx < sw; lx++) {
        const p = pRow + lx * 4;
        if (d[p + 3] === 0) continue;
        if (validY) {
          const sx = x0 + (lx + 0.5) * invScratch;
          const dx = Math.floor((sx - offsetX) * invWorldScaleX);
          if (dx >= 0 && dx < depthW) {
            const di = (rowOff + dx) * 4;
            if (depthPixels[di + 2] > 128) {
              const sceneD16 = (depthPixels[di] << 8) | depthPixels[di + 1];
              if (rowD16 > sceneD16) {
                d[p + 3] = 0;
                continue;
              }
            }
          }
        }
        anyVisible = true;
      }
    }
    if (anyVisible) {
      vehScratchCtx.putImageData(imgData, 0, 0);
      if (scratchScale < 1.0) {
        ctx.save();
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(vehScratch, 0, 0, sw, sh, x0, y0, bw, bh);
        ctx.restore();
      } else {
        ctx.drawImage(vehScratch, 0, 0, sw, sh, x0, y0, bw, bh);
      }
    }
  }

  function shadeHex(hex, factor, mode) {
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

  function makeScreenIsoBasis(wx, wy, tx, ty, wScale) {
    const s = scale * wScale;
    const cx = offsetX + wx * scale;
    const cy = offsetY + wy * scale;
    // Screen-space forward unit vector (tx, ty) and true isometric perpendicular right vector
    const isoScaleY = 0.55;
    // Invert vertical foreshortening to find orthogonal ground-plane right vector
    const gx = tx;
    const gy = ty / isoScaleY;
    const gMag = Math.hypot(gx, gy) || 1;
    const rx = -gy / gMag;
    const ry = (gx / gMag) * isoScaleY;
    // Project local (l = forward, w = right, z = up) in 0.25m-px world units to screen (x, y)
    const proj = (l, w, z) => [
      cx + (l * tx + w * rx) * s,
      cy + (l * ty + w * ry - z * 0.84) * s,
    ];
    // Directional NW sun illumination for a local horizontal normal (nl, nw)
    const dirShade = (nl, nw) => {
      const nx = nl * tx + nw * rx;
      const ny = nl * ty + nw * ry;
      const nm = Math.hypot(nx, ny) || 1;
      // Sun from upper-left (NW): light vector (-0.72, -0.69)
      const dot = (nx / nm) * (-0.72) + (ny / nm) * (-0.69);
      return 0.78 + Math.max(-1, Math.min(1, dot)) * 0.26;
    };
    return { cx, cy, s, tx, ty, rx, ry, proj, dirShade };
  }

  function makeTwoPointIsoBasis(pRear, pFront, hl, wScale) {
    // True articulated rail-car kinematics: front coupler sits on pFront and rear coupler sits on pRear!
    // Automatically preserves exact isometric foreshortening along any curve so adjacent wagons stay
    // locked end-to-end with zero center-pivot swing, zero lateral offset, and zero gap/overlap!
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
      const u = (l + hl) * inv2hl; // -hl -> 0 (pRear), +hl -> 1 (pFront)
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

  function fillPoly(pts, fill, stroke = null, lw = 1) {
    vCtx.beginPath();
    vCtx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) vCtx.lineTo(pts[i][0], pts[i][1]);
    vCtx.closePath();
    vCtx.fillStyle = fill;
    vCtx.fill();
    if (stroke) {
      vCtx.strokeStyle = stroke;
      vCtx.lineWidth = lw;
      vCtx.stroke();
    }
  }

  function draw3DCar(pos, colorIdx, wScale, mode, tSec = 0) {
    const b = makeScreenIsoBasis(pos.wx, pos.wy, pos.tx, pos.ty, wScale);
    if (b.cx < -56 || b.cx > canvas.width + 56 || b.cy < -56 || b.cy > canvas.height + 56) return;

    // Authentic Kilchberg & Swiss vehicle mix (100% deterministic from colorIdx):
    // Rare Swiss Feuerwehr/Ambulance, Die Post yellow van, Lindt gold truck, Migros, Coop, Alpine camper, Estate/Hatchback/Sedan
    const isEmergency = (colorIdx % 29 === 17);
    const isAmbulance = isEmergency && (Math.floor(colorIdx / 29) % 2 === 1);
    const isPostVan = !isEmergency && (colorIdx % 11 === 4);
    const isLindtVan = !isEmergency && !isPostVan && (colorIdx % 13 === 7);
    const isMigrosVan = !isEmergency && !isPostVan && !isLindtVan && (colorIdx % 17 === 9);
    const isCoopVan = !isEmergency && !isPostVan && !isLindtVan && !isMigrosVan && (colorIdx % 19 === 11);
    const isCamper = !isEmergency && !isPostVan && !isLindtVan && !isMigrosVan && !isCoopVan && (colorIdx % 15 === 3);
    const isVan = isEmergency || isPostVan || isLindtVan || isMigrosVan || isCoopVan || isCamper;
    const carSub = colorIdx % 3; // 0 = Swiss Estate (Kombi), 1 = Hatchback, 2 = Sedan
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

    // Crisp 1:1 miniature proportions
    const hl = isLindtVan ? 10.8 : (isEmergency ? 10.4 : (isCamper ? 10.2 : (isVan ? 10.6 : (isEstate ? 9.6 : (isHatch ? 8.2 : 9.2)))));
    const hw = isLindtVan ? 4.6 : (isCamper ? 4.4 : (isVan ? 4.5 : (isHatch ? 4.0 : 4.2)));
    const zBot = 1.2;
    const zBelt = isCamper ? 4.7 : (isEmergency ? 4.8 : (isVan ? 5.0 : (isEstate ? 4.3 : (isHatch ? 4.2 : 4.4))));
    const zRoof = isLindtVan ? 9.4 : (isEmergency ? 8.8 : (isCamper ? 8.4 : (isVan ? 9.2 : (isHatch ? 7.1 : 7.2))));

    // Grounded soft SE drop shadow
    const shOff = [2.6 * b.s, 2.0 * b.s];
    const shPts = [
      b.proj(hl + 1.2, -hw - 0.8, 0),
      b.proj(hl + 1.2, hw + 0.8, 0),
      b.proj(-hl - 1.2, hw + 0.8, 0),
      b.proj(-hl - 1.2, -hw - 0.8, 0),
    ].map(([x, y]) => [x + shOff[0], y + shOff[1]]);
    fillPoly(shPts, isNight ? 'rgba(6,10,20,0.62)' : 'rgba(20,26,34,0.44)');

    // Visible side wall (whichever has positive screen-Y normal)
    const sideSign = b.ry >= 0 ? 1 : -1;
    const frontVis = b.ty >= 0;
    const endSign = frontVis ? 1 : -1;
    const outlineCol = isNight ? 'rgba(10,16,28,0.85)' : 'rgba(26,30,38,0.72)';
    const lw = Math.max(0.7, Math.min(1.4, b.s * 0.45));

    const sideShade = b.dirShade(0, sideSign);
    const endShade = b.dirShade(endSign, 0);

    if (isVan) {
      // Lower skirt wall
      fillPoly([
        b.proj(-hl, sideSign * hw, zBot),
        b.proj(hl, sideSign * hw, zBot),
        b.proj(hl, sideSign * hw, zBelt),
        b.proj(-hl, sideSign * hw, zBelt),
      ], shadeHex(baseHex, sideShade * 0.92, mode), outlineCol, lw);

      // Upper cargo / camper / emergency body wall
      const upperHex = isCamper ? '#eef2f6' : (isAmbulance ? '#f4f6f9' : baseHex);
      fillPoly([
        b.proj(-hl, sideSign * hw, zBelt),
        b.proj(hl * 0.56, sideSign * hw, zBelt),
        b.proj(hl * 0.50, sideSign * hw, zRoof),
        b.proj(-hl, sideSign * hw, zRoof),
      ], shadeHex(upperHex, sideShade * 0.98, mode), outlineCol, lw * 0.9);

      // Signature side livery stripes & camper windows
      if (isCamper) {
        // Side camping windows
        fillPoly([
          b.proj(-hl * 0.78, sideSign * (hw + 0.08), zBelt + 0.6),
          b.proj(hl * 0.30, sideSign * (hw + 0.08), zBelt + 0.6),
          b.proj(hl * 0.30, sideSign * (hw + 0.08), zRoof - 0.8),
          b.proj(-hl * 0.78, sideSign * (hw + 0.08), zRoof - 0.8),
        ], isNight ? '#ffd978' : '#26384c');
      } else if (isCoopVan) {
        // Coop warm orange lower band + red accent stripe
        fillPoly([
          b.proj(-hl * 0.92, sideSign * (hw + 0.08), zBot + 0.8),
          b.proj(hl * 0.42, sideSign * (hw + 0.08), zBot + 0.8),
          b.proj(hl * 0.42, sideSign * (hw + 0.08), zBelt + 0.4),
          b.proj(-hl * 0.92, sideSign * (hw + 0.08), zBelt + 0.4),
        ], shadeHex('#f07d00', sideShade * 1.04, mode));
        fillPoly([
          b.proj(-hl * 0.84, sideSign * (hw + 0.09), zBelt + 0.8),
          b.proj(hl * 0.34, sideSign * (hw + 0.09), zBelt + 0.8),
          b.proj(hl * 0.34, sideSign * (hw + 0.09), zBelt + 2.0),
          b.proj(-hl * 0.84, sideSign * (hw + 0.09), zBelt + 2.0),
        ], shadeHex('#e03124', sideShade * 1.05, mode));
      } else {
        const stripeHex = isEmergency
          ? (isAmbulance ? '#e63928' : '#f8fafc')
          : (isPostVan ? '#d62828' : (isMigrosVan ? '#ff6600' : '#d4a02c'));
        fillPoly([
          b.proj(-hl * 0.88, sideSign * (hw + 0.08), zBelt + 0.6),
          b.proj(hl * 0.36, sideSign * (hw + 0.08), zBelt + 0.6),
          b.proj(hl * 0.36, sideSign * (hw + 0.08), zBelt + 2.0),
          b.proj(-hl * 0.88, sideSign * (hw + 0.08), zBelt + 2.0),
        ], shadeHex(stripeHex, sideShade * 1.05, mode));
      }

      // Cab side window
      fillPoly([
        b.proj(hl * 0.48, sideSign * (hw + 0.05), zBelt),
        b.proj(hl * 0.86, sideSign * (hw + 0.05), zBelt),
        b.proj(hl * 0.64, sideSign * (hw + 0.02), zRoof - 0.5),
        b.proj(hl * 0.46, sideSign * (hw + 0.02), zRoof - 0.5),
      ], isNight ? '#334d6e' : '#26384c', outlineCol, lw * 0.7);

      // Visible front/rear face
      const endTopZ = (endSign > 0) ? zBelt : zRoof;
      const endHex = (isMigrosVan && endSign > 0) ? '#ff6600' : baseHex;
      fillPoly([
        b.proj(endSign * hl, -hw, zBot),
        b.proj(endSign * hl, hw, zBot),
        b.proj(endSign * hl, hw, endTopZ),
        b.proj(endSign * hl, -hw, endTopZ),
      ], shadeHex(endHex, endShade * 0.90, mode), outlineCol, lw);

      // Sloped cab windshield
      fillPoly([
        b.proj(hl * 0.92, -hw * 0.88, zBelt + 0.1),
        b.proj(hl * 0.92, hw * 0.88, zBelt + 0.1),
        b.proj(hl * 0.56, hw * 0.84, zRoof),
        b.proj(hl * 0.56, -hw * 0.84, zRoof),
      ], isNight ? '#48688c' : '#35506b', outlineCol, lw * 0.7);

      // Flat sunlit cargo roof + signature crests / camper rack / emergency lightbar
      const roofHex = isEmergency
        ? (isAmbulance ? '#f8fafc' : '#e02620')
        : (isPostVan ? '#f8d238' : (isCamper ? '#f1f5f9' : '#fcf9f0'));
      fillPoly([
        b.proj(-hl, -hw, zRoof),
        b.proj(hl * 0.56, -hw, zRoof),
        b.proj(hl * 0.56, hw, zRoof),
        b.proj(-hl, hw, zRoof),
      ], shadeHex(roofHex, 1.08, mode), outlineCol, lw * 0.8);

      if (isLindtVan) {
        fillPoly([
          b.proj(-hl * 0.55, -hw * 0.42, zRoof + 0.1),
          b.proj(hl * 0.15, -hw * 0.42, zRoof + 0.1),
          b.proj(hl * 0.15, hw * 0.42, zRoof + 0.1),
          b.proj(-hl * 0.55, hw * 0.42, zRoof + 0.1),
        ], shadeHex('#d4a02c', 1.1, mode));
      } else if (isCamper) {
        // Pop-top roof rack
        fillPoly([
          b.proj(-hl * 0.72, -hw * 0.65, zRoof + 0.4),
          b.proj(hl * 0.25, -hw * 0.65, zRoof + 0.4),
          b.proj(hl * 0.25, hw * 0.65, zRoof + 0.4),
          b.proj(-hl * 0.72, hw * 0.65, zRoof + 0.4),
        ], shadeHex('#cbd5e1', 1.04, mode), outlineCol, lw * 0.6);
      } else if (isEmergency) {
        // Subtle Swiss Feuerwehr/Ambulance alternating blue roof lightbar
        const flashSide = (Math.floor(tSec * 6.0 + colorIdx) % 2 === 0) ? -1 : 1;
        const barPt = b.proj(hl * 0.38, flashSide * hw * 0.35, zRoof + 0.55);
        const dimPt = b.proj(hl * 0.38, -flashSide * hw * 0.35, zRoof + 0.55);
        const lSz = Math.max(1.4, 1.8 * b.s);
        if (isNight || isSunset) {
          vCtx.save();
          vCtx.fillStyle = isNight ? 'rgba(56, 189, 248, 0.38)' : 'rgba(56, 189, 248, 0.22)';
          vCtx.beginPath();
          vCtx.arc(barPt[0], barPt[1], Math.max(2.2, 2.5 * b.s), 0, Math.PI * 2);
          vCtx.fill();
          vCtx.restore();
        }
        vCtx.fillStyle = '#1e3a8a';
        vCtx.fillRect(Math.round(dimPt[0] - lSz * 0.4), Math.round(dimPt[1] - lSz * 0.4), Math.max(1, Math.round(lSz * 0.85)), Math.max(1, Math.round(lSz * 0.85)));
        vCtx.fillStyle = '#38bdf8';
        vCtx.fillRect(Math.round(barPt[0] - lSz * 0.5), Math.round(barPt[1] - lSz * 0.5), Math.max(1.5, Math.round(lSz)), Math.max(1.5, Math.round(lSz)));
      }
    } else {
      // Side body wall + cabin greenhouse side (Estate Kombi / Hatchback / Sedan)
      fillPoly([
        b.proj(-hl, sideSign * hw, zBot),
        b.proj(hl, sideSign * hw, zBot),
        b.proj(hl, sideSign * hw, zBelt),
        b.proj(-hl, sideSign * hw, zBelt),
      ], shadeHex(baseHex, sideShade * 0.92, mode), outlineCol, lw);

      const rearWinBot = isEstate ? -hl * 0.78 : (isHatch ? -hl * 0.68 : -hl * 0.56);
      const rearRoofL = isEstate ? -hl * 0.70 : (isHatch ? -hl * 0.60 : -hl * 0.44);
      const frontRoofL = isEstate ? hl * 0.26 : hl * 0.28;

      // Side dark tinted windows
      fillPoly([
        b.proj(rearWinBot, sideSign * hw * 0.92, zBelt),
        b.proj(hl * 0.46, sideSign * hw * 0.92, zBelt),
        b.proj(frontRoofL, sideSign * hw * 0.82, zRoof),
        b.proj(rearRoofL, sideSign * hw * 0.82, zRoof),
      ], isNight ? '#334d6e' : '#26384c', outlineCol, lw * 0.8);

      // Visible front or rear bumper face
      fillPoly([
        b.proj(endSign * hl, -hw, zBot),
        b.proj(endSign * hl, hw, zBot),
        b.proj(endSign * hl, hw, zBelt),
        b.proj(endSign * hl, -hw, zBelt),
      ], shadeHex(baseHex, endShade * 0.90, mode), outlineCol, lw);

      // Hood & trunk deck
      fillPoly([
        b.proj(-hl, -hw, zBelt),
        b.proj(hl, -hw, zBelt),
        b.proj(hl, hw, zBelt),
        b.proj(-hl, hw, zBelt),
      ], shadeHex(baseHex, 1.04, mode));

      // Windshield & rear glass with subtle sky-reflection highlight
      fillPoly([
        b.proj(hl * 0.54, -hw * 0.84, zBelt + 0.1),
        b.proj(hl * 0.54, hw * 0.84, zBelt + 0.1),
        b.proj(frontRoofL, hw * 0.78, zRoof),
        b.proj(frontRoofL, -hw * 0.78, zRoof),
      ], isNight ? '#446387' : '#354f68');
      if (!isNight) {
        fillPoly([
          b.proj(hl * 0.46, -hw * 0.64, zBelt + 0.7),
          b.proj(hl * 0.46, -hw * 0.12, zBelt + 0.7),
          b.proj(frontRoofL + hl * 0.06, -hw * 0.12, zRoof - 0.5),
          b.proj(frontRoofL + hl * 0.06, -hw * 0.60, zRoof - 0.5),
        ], 'rgba(216,238,255,0.34)');
      }

      // Sunlit top roof panel
      fillPoly([
        b.proj(rearRoofL, -hw * 0.78, zRoof),
        b.proj(frontRoofL, -hw * 0.78, zRoof),
        b.proj(frontRoofL, hw * 0.78, zRoof),
        b.proj(rearRoofL, hw * 0.78, zRoof),
      ], shadeHex(baseHex, 1.15, mode), outlineCol, lw * 0.8);

      // Silver Kombi roof rails on Swiss Estates
      if (isEstate) {
        vCtx.strokeStyle = shadeHex('#d4dce6', 1.0, mode);
        vCtx.lineWidth = Math.max(0.7, 0.75 * b.s);
        for (const rSide of [-hw * 0.62, hw * 0.62]) {
          const r0 = b.proj(rearRoofL + 0.8, rSide, zRoof + 0.35);
          const r1 = b.proj(frontRoofL - 0.8, rSide, zRoof + 0.35);
          vCtx.beginPath();
          vCtx.moveTo(r0[0], r0[1]);
          vCtx.lineTo(r1[0], r1[1]);
          vCtx.stroke();
        }
      }
    }

    // Dark wheel arches & silver hubs along visible side (all cars & vans!)
    const wDot = Math.max(1.5, 2.2 * b.s);
    const hDot = Math.max(0.8, 0.9 * b.s);
    for (const wl of [-hl * 0.58, hl * 0.58]) {
      const wp = b.proj(wl, sideSign * (hw + 0.06), zBot + 0.4);
      vCtx.fillStyle = isNight ? '#11161f' : '#1c222b';
      vCtx.fillRect(Math.round(wp[0] - wDot * 0.55), Math.round(wp[1] - wDot * 0.45), Math.max(2, Math.round(wDot * 1.1)), Math.max(1.5, Math.round(wDot * 0.95)));
      vCtx.fillStyle = shadeHex('#9aa6b4', 0.95, mode);
      vCtx.fillRect(Math.round(wp[0] - hDot * 0.5), Math.round(wp[1] - hDot * 0.4), Math.max(1, Math.round(hDot)), Math.max(1, Math.round(hDot)));
    }

    // Headlights (warm beams at night!) & red taillights + night/sunset taillight asphalt glow
    const hl1 = b.proj(hl + 0.3, -hw * 0.62, zBot + 1.6);
    const hl2 = b.proj(hl + 0.3, hw * 0.62, zBot + 1.6);
    const tl1 = b.proj(-hl - 0.3, -hw * 0.62, zBot + 1.8);
    const tl2 = b.proj(-hl - 0.3, hw * 0.62, zBot + 1.8);
    const rDot = Math.max(1.2, 1.6 * b.s);
    if (isNight) {
      fillPoly([
        hl1, hl2,
        b.proj(hl + 22, hw * 2.2, 0.2),
        b.proj(hl + 22, -hw * 2.2, 0.2),
      ], 'rgba(255,244,186,0.22)');
    }
    if (isNight || isSunset) {
      fillPoly([
        tl1, tl2,
        b.proj(-hl - 9.5, hw * 1.45, 0.2),
        b.proj(-hl - 9.5, -hw * 1.45, 0.2),
      ], isNight ? 'rgba(255, 42, 36, 0.16)' : 'rgba(255, 48, 40, 0.08)');
    }
    vCtx.fillStyle = isNight ? '#fff8c8' : '#fffbe0';
    vCtx.fillRect(hl1[0] - rDot * 0.5, hl1[1] - rDot * 0.5, rDot, rDot);
    vCtx.fillRect(hl2[0] - rDot * 0.5, hl2[1] - rDot * 0.5, rDot, rDot);
    vCtx.fillStyle = isNight ? '#ff3b30' : '#d62828';
    vCtx.fillRect(tl1[0] - rDot * 0.5, tl1[1] - rDot * 0.5, rDot, rDot);
    vCtx.fillRect(tl2[0] - rDot * 0.5, tl2[1] - rDot * 0.5, rDot, rDot);
  }

  function drawBusSection(b, hl, hw, mode, tSec, opts) {
    const isNight = mode === 'night';
    const isSunset = mode === 'sunset';
    const isFront = opts.isFront;
    const isRear = opts.isRear;
    const isDwelling = !!opts.isDwelling;
    const speedRatio = opts.speedRatio != null ? opts.speedRatio : 1.0;
    const wheelPositions = opts.wheelPositions || [-hl * 0.56, hl * 0.56];
    const zBot = 1.4;
    const zBlue = 5.4;
    const zWinBot = 6.2;
    const zWinTop = 10.6;
    const zRoof = 12.2;

    // Grounded SE shadow
    const shOff = [3.6 * b.s, 2.8 * b.s];
    fillPoly([
      b.proj(hl + 1.2, -hw - 1.0, 0),
      b.proj(hl + 1.2, hw + 1.0, 0),
      b.proj(-hl - 1.2, hw + 1.0, 0),
      b.proj(-hl - 1.2, -hw - 1.0, 0),
    ].map(([x, y]) => [x + shOff[0], y + shOff[1]]), isNight ? 'rgba(6,10,20,0.65)' : 'rgba(18,24,32,0.46)');

    const sideSign = b.ry >= 0 ? 1 : -1;
    const frontVis = b.ty >= 0;
    const endSign = frontVis ? 1 : -1;
    const outlineCol = isNight ? 'rgba(10,16,28,0.88)' : 'rgba(24,30,40,0.78)';
    const lw = Math.max(0.8, Math.min(1.5, b.s * 0.5));

    // Side wall: ZVV Cobalt Blue lower skirt + Crisp White upper body
    const sideShade = b.dirShade(0, sideSign);
    fillPoly([
      b.proj(-hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBlue),
      b.proj(-hl, sideSign * hw, zBlue),
    ], shadeHex('#0d5ea6', sideShade, mode), outlineCol, lw);

    fillPoly([
      b.proj(-hl, sideSign * hw, zBlue),
      b.proj(hl, sideSign * hw, zBlue),
      b.proj(hl, sideSign * hw, zRoof),
      b.proj(-hl, sideSign * hw, zRoof),
    ], shadeHex('#f2f5f8', sideShade, mode), outlineCol, lw);

    // Side window ribbon
    const winStart = -hl + 1.6;
    const winEnd = hl - 1.4;
    fillPoly([
      b.proj(winStart, sideSign * (hw + 0.05), zWinBot),
      b.proj(winEnd, sideSign * (hw + 0.05), zWinBot),
      b.proj(winEnd, sideSign * (hw + 0.05), zWinTop),
      b.proj(winStart, sideSign * (hw + 0.05), zWinTop),
    ], isNight ? '#ffd978' : '#243a52');

    // Crisp vertical window mullions every ~5.4 world px
    vCtx.strokeStyle = isNight ? '#263345' : shadeHex('#dce3ec', sideShade * 0.92, mode);
    vCtx.lineWidth = Math.max(0.75, lw * 0.85);
    for (let ml = winStart + 5.2; ml < winEnd - 2.0; ml += 5.4) {
      const m0 = b.proj(ml, sideSign * (hw + 0.08), zWinBot);
      const m1 = b.proj(ml, sideSign * (hw + 0.08), zWinTop);
      vCtx.beginPath();
      vCtx.moveTo(m0[0], m0[1]);
      vCtx.lineTo(m1[0], m1[1]);
      vCtx.stroke();
    }

    // Side orange LED route strip behind front door
    if (isFront) {
      fillPoly([
        b.proj(hl - 5.6, sideSign * (hw + 0.10), zWinTop - 1.3),
        b.proj(hl - 1.9, sideSign * (hw + 0.10), zWinTop - 1.3),
        b.proj(hl - 1.9, sideSign * (hw + 0.10), zWinTop - 0.1),
        b.proj(hl - 5.6, sideSign * (hw + 0.10), zWinTop - 0.1),
      ], '#161c24');
      fillPoly([
        b.proj(hl - 5.2, sideSign * (hw + 0.12), zWinTop - 1.05),
        b.proj(hl - 2.3, sideSign * (hw + 0.12), zWinTop - 1.05),
        b.proj(hl - 2.3, sideSign * (hw + 0.12), zWinTop - 0.35),
        b.proj(hl - 5.2, sideSign * (hw + 0.12), zWinTop - 0.35),
      ], '#ff9e1b');
    }

    // Dark wheel arches & silver wheel hubs along visible side
    for (const wl of wheelPositions) {
      fillPoly([
        b.proj(wl - 2.4, sideSign * (hw + 0.09), zBot - 0.3),
        b.proj(wl + 2.4, sideSign * (hw + 0.09), zBot - 0.3),
        b.proj(wl + 2.0, sideSign * (hw + 0.09), zBot + 2.4),
        b.proj(wl - 2.0, sideSign * (hw + 0.09), zBot + 2.4),
      ], isNight ? '#11161f' : '#1c222b');
      const hp = b.proj(wl, sideSign * (hw + 0.11), zBot + 0.9);
      const hSz = Math.max(1.0, 1.3 * b.s);
      vCtx.fillStyle = shadeHex('#9aa6b4', 0.96, mode);
      vCtx.fillRect(Math.round(hp[0] - hSz * 0.5), Math.round(hp[1] - hSz * 0.5), Math.max(1, Math.round(hSz)), Math.max(1, Math.round(hSz)));
    }

    // End face (front windshield or rear panel)
    const endShade = b.dirShade(endSign, 0);
    const drawOuterEnd = (endSign > 0 && isFront) || (endSign < 0 && isRear);
    fillPoly([
      b.proj(endSign * hl, -hw, zBot),
      b.proj(endSign * hl, hw, zBot),
      b.proj(endSign * hl, hw, zBlue),
      b.proj(endSign * hl, -hw, zBlue),
    ], shadeHex(drawOuterEnd ? '#0d5ea6' : '#262c34', endShade, mode), outlineCol, lw);
    fillPoly([
      b.proj(endSign * hl, -hw, zBlue),
      b.proj(endSign * hl, hw, zBlue),
      b.proj(endSign * hl, hw, zRoof),
      b.proj(endSign * hl, -hw, zRoof),
    ], shadeHex(drawOuterEnd ? '#f2f5f8' : '#2e3540', endShade, mode), outlineCol, lw);

    if (frontVis && isFront) {
      fillPoly([
        b.proj(hl + 0.06, -hw * 0.85, zWinBot - 0.4),
        b.proj(hl + 0.06, hw * 0.85, zWinBot - 0.4),
        b.proj(hl + 0.06, hw * 0.85, zWinTop - 0.1),
        b.proj(hl + 0.06, -hw * 0.85, zWinTop - 0.1),
      ], isNight ? '#58789c' : '#243a52');
      // Glowing orange VBZ/ZVV LED route matrix display (161 / 165) above front windshield
      fillPoly([
        b.proj(hl + 0.10, -hw * 0.62, zWinTop + 0.1),
        b.proj(hl + 0.10, hw * 0.62, zWinTop + 0.1),
        b.proj(hl + 0.10, hw * 0.62, zRoof - 0.35),
        b.proj(hl + 0.10, -hw * 0.62, zRoof - 0.35),
      ], '#141920');
      fillPoly([
        b.proj(hl + 0.14, -hw * 0.48, zWinTop + 0.35),
        b.proj(hl + 0.14, hw * 0.48, zWinTop + 0.35),
        b.proj(hl + 0.14, hw * 0.48, zRoof - 0.6),
        b.proj(hl + 0.14, -hw * 0.48, zRoof - 0.6),
      ], '#ffb340');
    }

    // Sunlit white roof + rooftop HVAC pod
    fillPoly([
      b.proj(-hl, -hw, zRoof),
      b.proj(hl, -hw, zRoof),
      b.proj(hl, hw, zRoof),
      b.proj(-hl, hw, zRoof),
    ], shadeHex('#ffffff', 1.05, mode), outlineCol, lw);

    if (opts.hasAcPod !== false) {
      const acHalf = Math.min(7.0, hl * 0.36);
      fillPoly([
        b.proj(-acHalf, -hw * 0.58, zRoof + 1.4),
        b.proj(acHalf, -hw * 0.58, zRoof + 1.4),
        b.proj(acHalf, hw * 0.58, zRoof + 1.4),
        b.proj(-acHalf, hw * 0.58, zRoof + 1.4),
      ], shadeHex('#cfd7e0', 1.0, mode), outlineCol, lw * 0.7);
    }

    const rDot = Math.max(1.4, 1.8 * b.s);

    // Front headlights & night beam cone
    if (isFront) {
      const hl1 = b.proj(hl + 0.18, -hw * 0.68, zBot + 1.8);
      const hl2 = b.proj(hl + 0.18, hw * 0.68, zBot + 1.8);
      if (isNight) {
        fillPoly([
          hl1, hl2,
          b.proj(hl + 30, hw * 2.6, 0.2),
          b.proj(hl + 30, -hw * 2.6, 0.2),
        ], 'rgba(255,244,186,0.25)');
      }
      vCtx.fillStyle = isNight ? '#fff8c8' : '#fffbe0';
      vCtx.fillRect(hl1[0] - rDot * 0.5, hl1[1] - rDot * 0.5, rDot, rDot);
      vCtx.fillRect(hl2[0] - rDot * 0.5, hl2[1] - rDot * 0.5, rDot, rDot);
    }

    // Rear brake/taillights (brightening during decel/dwell + night/sunset asphalt glow)
    if (isRear) {
      const isBraking = isDwelling || speedRatio < 0.45;
      const tl1 = b.proj(-hl - 0.18, -hw * 0.68, zBot + 2.0);
      const tl2 = b.proj(-hl - 0.18, hw * 0.68, zBot + 2.0);
      if (isNight || isSunset || isBraking) {
        const glowA = isNight ? (isBraking ? 0.28 : 0.16) : (isBraking ? 0.16 : 0.08);
        fillPoly([
          tl1, tl2,
          b.proj(-hl - 12, hw * 1.55, 0.2),
          b.proj(-hl - 12, -hw * 1.55, 0.2),
        ], `rgba(255, 42, 36, ${glowA.toFixed(2)})`);
      }
      vCtx.fillStyle = (isBraking || isNight) ? '#ff3b30' : '#d62828';
      const tSz = isBraking ? rDot * 1.25 : rDot;
      vCtx.fillRect(tl1[0] - tSz * 0.5, tl1[1] - tSz * 0.5, tSz, tSz);
      vCtx.fillRect(tl2[0] - tSz * 0.5, tl2[1] - tSz * 0.5, tSz, tSz);
    }

    // Blinking amber door/hazard lights during bus-stop dwell
    if (isDwelling && (Math.floor(tSec * 2.8) % 2 === 0)) {
      const aSz = Math.max(1.5, 1.9 * b.s);
      vCtx.fillStyle = '#ffaa00';
      if (isFront) {
        const af = b.proj(hl - 0.6, sideSign * hw * 0.95, zBot + 2.0);
        const ad = b.proj(hl - 4.0, sideSign * (hw + 0.12), zWinTop + 0.5);
        vCtx.fillRect(af[0] - aSz * 0.5, af[1] - aSz * 0.5, aSz, aSz);
        vCtx.fillRect(ad[0] - aSz * 0.5, ad[1] - aSz * 0.5, aSz, aSz);
      }
      if (isRear) {
        const ar = b.proj(-hl + 0.6, sideSign * hw * 0.95, zBot + 2.0);
        vCtx.fillRect(ar[0] - aSz * 0.5, ar[1] - aSz * 0.5, aSz, aSz);
      }
    }
  }

  function draw3DBus(pos, wScale, mode, tSec = 0, speedRatio = 1.0, isDwelling = false, routeNum = '165') {
    // Iconic Zurich ZVV / VBZ 12 m blue-and-white regional bus (Line 165 through Kilchberg!)
    const b = makeScreenIsoBasis(pos.wx, pos.wy, pos.tx, pos.ty, wScale);
    if (b.cx < -64 || b.cx > canvas.width + 64 || b.cy < -64 || b.cy > canvas.height + 64) return;
    drawBusSection(b, 22.0, 6.0, mode, tSec, {
      isFront: true,
      isRear: true,
      routeNum,
      speedRatio,
      isDwelling,
      wheelPositions: [-12.5, 12.5],
      hasAcPod: true,
    });
  }

  function draw3DArticulatedBus(pRear, pMidRear, pMidFront, pFront, wScale, mode, tSec = 0, speedRatio = 1.0, isDwelling = false) {
    // Authentic VBZ Line 161 18 m 2-section hinged articulated accordion bus on Seestrasse!
    const hlFront = 20.4;
    const hlRear = 14.4;
    const hw = 5.8;
    const bFront = makeTwoPointIsoBasis(pMidFront, pFront, hlFront, wScale);
    const bRear = makeTwoPointIsoBasis(pRear, pMidRear, hlRear, wScale);
    if (bFront.cx < -100 || bFront.cx > canvas.width + 100 || bFront.cy < -100 || bFront.cy > canvas.height + 100) return;

    const isNight = mode === 'night';
    const outlineCol = isNight ? 'rgba(10,16,28,0.88)' : 'rgba(24,30,40,0.78)';
    const lw = Math.max(0.8, Math.min(1.4, bFront.s * 0.48));
    const sideSign = bFront.ry >= 0 ? 1 : -1;

    const drawBellows = () => {
      const bw = hw * 0.86;
      const zBot = 1.8;
      const zRoof = 11.7;
      // Dark pleated charcoal rubber bellows bridging tractor rear to trailer front
      fillPoly([
        bFront.proj(-hlFront, sideSign * bw, zBot),
        bRear.proj(hlRear, sideSign * bw, zBot),
        bRear.proj(hlRear, sideSign * bw, zRoof),
        bFront.proj(-hlFront, sideSign * bw, zRoof),
      ], shadeHex('#262c34', 0.90, mode), outlineCol, lw * 0.85);
      fillPoly([
        bFront.proj(-hlFront, -bw, zRoof),
        bRear.proj(hlRear, -bw, zRoof),
        bRear.proj(hlRear, bw, zRoof),
        bFront.proj(-hlFront, bw, zRoof),
      ], shadeHex('#363e48', 0.98, mode), outlineCol, lw * 0.8);
      // Two crisp vertical accordion rib highlight lines
      vCtx.strokeStyle = shadeHex('#525e6e', 1.0, mode);
      vCtx.lineWidth = Math.max(0.7, lw * 0.75);
      for (const f of [0.33, 0.67]) {
        const a0 = bFront.proj(-hlFront, sideSign * (bw + 0.06), zBot + 0.4);
        const a1 = bRear.proj(hlRear, sideSign * (bw + 0.06), zBot + 0.4);
        const c0 = bFront.proj(-hlFront, sideSign * (bw + 0.06), zRoof - 0.3);
        const c1 = bRear.proj(hlRear, sideSign * (bw + 0.06), zRoof - 0.3);
        vCtx.beginPath();
        vCtx.moveTo(a0[0] + (a1[0] - a0[0]) * f, a0[1] + (a1[1] - a0[1]) * f);
        vCtx.lineTo(c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f);
        vCtx.stroke();
      }
    };

    const frontOpts = {
      isFront: true, isRear: false, routeNum: '161', speedRatio, isDwelling,
      wheelPositions: [-11.0, 11.5], hasAcPod: true,
    };
    const rearOpts = {
      isFront: false, isRear: true, routeNum: '161', speedRatio, isDwelling,
      wheelPositions: [-4.5], hasAcPod: true,
    };

    // Painter-sort rear vs front section around the hinged bellows so closer half draws cleanly on top
    if (bRear.cy <= bFront.cy) {
      drawBusSection(bRear, hlRear, hw, mode, tSec, rearOpts);
      drawBellows();
      drawBusSection(bFront, hlFront, hw, mode, tSec, frontOpts);
    } else {
      drawBusSection(bFront, hlFront, hw, mode, tSec, frontOpts);
      drawBellows();
      drawBusSection(bRear, hlRear, hw, mode, tSec, rearOpts);
    }
  }

  function draw3DTrainUnit(pRear, pFront, kind, variant, wScale, mode, nextRear, nextFront, tSec = 0, isDwelling = false, dwellProgress = 0) {
    // Museum-grade continuous 3D SBB RABe 511 KISS / DPZ Double-Decker & SBB Re 460 IC
    // True two-point rail-pinned kinematics (pFront & pRear on the track) so every wagon
    // tracks the rail like a real articulated train with locked dark rubber gangway bellows!
    const hl = 34.5; // local coordinate range [-hl, +hl] mapped directly to [pRear, pFront]
    const b = makeTwoPointIsoBasis(pRear, pFront, hl, wScale);
    if (b.cx < -140 || b.cx > canvas.width + 140 || b.cy < -140 || b.cy > canvas.height + 140) return;

    const isNight = mode === 'night';
    const isSunset = mode === 'sunset';
    const isKISS = (kind === 'sbb_dpz' || kind === 'sbb_kiss');
    const isLead = variant === 0;
    const isTail = variant === 2;

    const hw = 6.8;  // ~3.0 m wide SBB carbody
    const zBot = 1.6;
    const zSkirt = 3.8;
    const zEave = isKISS ? 14.4 : 13.0;
    const zCrown = isKISS ? 16.8 : 15.2;

    const sideSign = b.ry >= 0 ? 1 : -1;
    const frontVis = b.ty >= 0;
    const endSign = frontVis ? 1 : -1;
    const outlineCol = isNight ? 'rgba(10,16,28,0.90)' : 'rgba(24,28,36,0.82)';
    const lw = Math.max(0.8, Math.min(1.6, b.s * 0.55));

    // 1. Grounded cast SE shadow along the gravel ballast bed
    const shOff = [5.4 * b.s, 4.0 * b.s];
    fillPoly([
      b.proj(hl + 1.5, -hw - 1.2, 0),
      b.proj(hl + 1.5, hw + 1.2, 0),
      b.proj(-hl - 1.5, hw + 1.2, 0),
      b.proj(-hl - 1.5, -hw - 1.2, 0),
    ].map(([x, y]) => [x + shOff[0], y + shOff[1]]), isNight ? 'rgba(6,10,20,0.68)' : 'rgba(20,24,32,0.48)');

    // 2. Articulated dark rubber gangway bellows locked directly from this wagon's rear to next wagon's front!
    if (nextRear && nextFront) {
      const bNext = makeTwoPointIsoBasis(nextRear, nextFront, hl, wScale);
      const gw = hw * 0.78;
      fillPoly([
        b.proj(-hl, sideSign * gw, zSkirt),
        bNext.proj(hl, sideSign * gw, zSkirt),
        bNext.proj(hl, sideSign * gw, zEave - 0.4),
        b.proj(-hl, sideSign * gw, zEave - 0.4),
      ], shadeHex('#2c323b', 0.85, mode), outlineCol, lw * 0.8);
      fillPoly([
        b.proj(-hl, -gw, zEave - 0.4),
        bNext.proj(hl, -gw, zEave - 0.4),
        bNext.proj(hl, gw, zEave - 0.4),
        b.proj(-hl, gw, zEave - 0.4),
      ], shadeHex('#3e4652', 0.95, mode), outlineCol, lw * 0.8);
    }

    // 3. Undercarriage dark bogie skirt
    const sideShade = b.dirShade(0, sideSign);
    const bodyHex = isKISS ? '#eef2f6' : ((isLead || isTail) ? '#d92121' : '#f2f5f8');
    fillPoly([
      b.proj(-hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zSkirt),
      b.proj(-hl, sideSign * hw, zSkirt),
    ], shadeHex('#2b313a', sideShade, mode), outlineCol, lw);

    // 4. Main sculpted side wall (NW-sun shaded!)
    const noseL = isLead ? hl - 4.0 : hl;
    const tailL = isTail ? -hl + 4.0 : -hl;
    fillPoly([
      b.proj(-hl, sideSign * hw, zSkirt),
      b.proj(hl, sideSign * hw, zSkirt),
      b.proj(noseL, sideSign * hw, zEave),
      b.proj(tailL, sideSign * hw, zEave),
    ], shadeHex(bodyHex, sideShade, mode), outlineCol, lw);

    // Iconic SBB black window band + double-deck / single-deck windows + bright red SBB doors!
    const winColor = isNight ? '#ffd670' : '#5880a4';
    const bandColor = isNight ? '#1b2432' : '#232a34';
    let doorPositions = null;
    let doorTopZ = zSkirt + 5.2;

    if (isKISS) {
      // Iconic ZVV cobalt-blue lower accent stripe along lower sill of Zurich S-Bahn double-decker!
      fillPoly([
        b.proj(-hl + 1.5, sideSign * (hw + 0.07), zSkirt),
        b.proj(hl - 1.5, sideSign * (hw + 0.07), zSkirt),
        b.proj(hl - 1.5, sideSign * (hw + 0.07), zSkirt + 0.9),
        b.proj(-hl + 1.5, sideSign * (hw + 0.07), zSkirt + 0.9),
      ], shadeHex('#1e5cb3', sideShade * 1.05, mode));

      // Lower-deck dark window ribbon
      fillPoly([
        b.proj(-hl + 5.5, sideSign * (hw + 0.06), zSkirt + 1.0),
        b.proj(hl - 5.5, sideSign * (hw + 0.06), zSkirt + 1.0),
        b.proj(hl - 5.5, sideSign * (hw + 0.06), zSkirt + 4.0),
        b.proj(-hl + 5.5, sideSign * (hw + 0.06), zSkirt + 4.0),
      ], bandColor);
      // Upper-deck dark window ribbon
      fillPoly([
        b.proj(-hl + 4.5, sideSign * (hw + 0.06), zSkirt + 5.4),
        b.proj(hl - 4.5, sideSign * (hw + 0.06), zSkirt + 5.4),
        b.proj(hl - 4.5, sideSign * (hw + 0.06), zEave - 1.2),
        b.proj(-hl + 4.5, sideSign * (hw + 0.06), zEave - 1.2),
      ], bandColor);

      // Individual crisp window panes along both decks
      for (let w = -24; w <= 22; w += 8) {
        fillPoly([
          b.proj(w, sideSign * (hw + 0.09), zSkirt + 1.3),
          b.proj(w + 5.2, sideSign * (hw + 0.09), zSkirt + 1.3),
          b.proj(w + 5.2, sideSign * (hw + 0.09), zSkirt + 3.7),
          b.proj(w, sideSign * (hw + 0.09), zSkirt + 3.7),
        ], winColor);
        fillPoly([
          b.proj(w, sideSign * (hw + 0.09), zSkirt + 5.8),
          b.proj(w + 5.2, sideSign * (hw + 0.09), zSkirt + 5.8),
          b.proj(w + 5.2, sideSign * (hw + 0.09), zEave - 1.5),
          b.proj(w, sideSign * (hw + 0.09), zEave - 1.5),
        ], winColor);
      }

      // Signature SBB bright red boarding doors at 1/4 & 3/4 coach length!
      const redDoor = shadeHex('#d92121', sideShade * 1.05, mode);
      doorPositions = [-20.5, 16.5];
      doorTopZ = zSkirt + 5.2;
      for (const dPos of doorPositions) {
        fillPoly([
          b.proj(dPos, sideSign * (hw + 0.12), zSkirt),
          b.proj(dPos + 4.2, sideSign * (hw + 0.12), zSkirt),
          b.proj(dPos + 4.2, sideSign * (hw + 0.12), doorTopZ),
          b.proj(dPos, sideSign * (hw + 0.12), doorTopZ),
        ], redDoor);
      }
      // Subtle red cant-rail stripe under the roof
      fillPoly([
        b.proj(tailL + 1.5, sideSign * (hw + 0.08), zEave - 1.0),
        b.proj(noseL - 1.5, sideSign * (hw + 0.08), zEave - 1.0),
        b.proj(noseL - 1.5, sideSign * (hw + 0.08), zEave),
        b.proj(tailL + 1.5, sideSign * (hw + 0.08), zEave),
      ], shadeHex('#d92121', sideShade, mode));
    } else if (!isLead && !isTail) {
      // SBB IC passenger coach: bold black window band + sky-reflective panes + red boarding doors
      fillPoly([
        b.proj(-hl + 5.0, sideSign * (hw + 0.06), zSkirt + 3.0),
        b.proj(hl - 5.0, sideSign * (hw + 0.06), zSkirt + 3.0),
        b.proj(hl - 5.0, sideSign * (hw + 0.06), zEave - 1.8),
        b.proj(-hl + 5.0, sideSign * (hw + 0.06), zEave - 1.8),
      ], bandColor);
      for (let w = -25; w <= 23; w += 8.5) {
        fillPoly([
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
        fillPoly([
          b.proj(dPos, sideSign * (hw + 0.12), zSkirt),
          b.proj(dPos + 4.0, sideSign * (hw + 0.12), zSkirt),
          b.proj(dPos + 4.0, sideSign * (hw + 0.12), doorTopZ),
          b.proj(dPos, sideSign * (hw + 0.12), doorTopZ),
        ], redDoor);
      }
    } else {
      // SBB Re 460 Locomotive: dark side cab windows + iconic crisp white SBB livery stripe & louvers
      const cabDir = isLead ? 1 : -1;
      fillPoly([
        b.proj(cabDir * (hl - 10.5), sideSign * (hw + 0.08), zSkirt + 3.6),
        b.proj(cabDir * (hl - 3.6), sideSign * (hw + 0.08), zSkirt + 3.6),
        b.proj(cabDir * (hl - 4.8), sideSign * (hw + 0.08), zEave - 1.6),
        b.proj(cabDir * (hl - 10.5), sideSign * (hw + 0.08), zEave - 1.6),
      ], isNight ? '#58789c' : '#243a52');
      // Crisp white SBB CFF FFS center livery bar
      fillPoly([
        b.proj(-11.0, sideSign * (hw + 0.09), zSkirt + 3.8),
        b.proj(11.0, sideSign * (hw + 0.09), zSkirt + 3.8),
        b.proj(11.0, sideSign * (hw + 0.09), zSkirt + 5.4),
        b.proj(-11.0, sideSign * (hw + 0.09), zSkirt + 5.4),
      ], shadeHex('#f4f7fa', sideShade * 1.05, mode));
      // Dark cooling louver band along upper loco body
      fillPoly([
        b.proj(-16.0, sideSign * (hw + 0.07), zEave - 2.6),
        b.proj(16.0, sideSign * (hw + 0.07), zEave - 2.6),
        b.proj(16.0, sideSign * (hw + 0.07), zEave - 1.0),
        b.proj(-16.0, sideSign * (hw + 0.07), zEave - 1.0),
      ], shadeHex('#7d1818', sideShade, mode));
    }

    // Animated SBB yellow/amber door-closing warning flash & doorway warm interior spill during Bahnhof dwell!
    if (isDwelling && doorPositions) {
      const doorsOpen = dwellProgress >= 0.12 && dwellProgress <= 0.78;
      const closingWarn = dwellProgress > 0.62;
      const blinkOn = closingWarn ? (Math.floor(tSec * 8.0) % 2 === 0) : true;
      const dDot = Math.max(1.4, 1.8 * b.s);
      for (const dPos of doorPositions) {
        if (doorsOpen) {
          fillPoly([
            b.proj(dPos + 0.7, sideSign * (hw + 0.15), zSkirt + 0.3),
            b.proj(dPos + 3.4, sideSign * (hw + 0.15), zSkirt + 0.3),
            b.proj(dPos + 3.4, sideSign * (hw + 0.15), doorTopZ - 0.5),
            b.proj(dPos + 0.7, sideSign * (hw + 0.15), doorTopZ - 0.5),
          ], (isNight || isSunset) ? '#ffe496' : '#fef3c7');
          if (isNight || isSunset) {
            fillPoly([
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
            vCtx.save();
            vCtx.fillStyle = 'rgba(255, 210, 48, 0.42)';
            vCtx.beginPath();
            vCtx.arc(lp[0], lp[1], dDot * 1.9, 0, Math.PI * 2);
            vCtx.fill();
            vCtx.restore();
          }
          vCtx.fillStyle = closingWarn ? '#ffd426' : '#ffbe2e';
          vCtx.fillRect(Math.round(lp[0] - dDot * 0.5), Math.round(lp[1] - dDot * 0.5), Math.max(1.5, Math.round(dDot)), Math.max(1.5, Math.round(dDot)));
        }
      }
    }

    // 5. Visible front cab nose or rear end face
    const endShade = b.dirShade(endSign, 0);
    const isCabFace = (endSign > 0 && isLead) || (endSign < 0 && isTail);
    const endTopL = (endSign > 0 ? noseL : tailL);
    const endHex = isCabFace ? '#d92121' : '#3a424d';
    fillPoly([
      b.proj(endSign * hl, -hw, zSkirt),
      b.proj(endSign * hl, hw, zSkirt),
      b.proj(endTopL, hw, zEave),
      b.proj(endTopL, -hw, zEave),
    ], shadeHex(endHex, endShade, mode), outlineCol, lw);

    if (isCabFace) {
      // Sloped panoramic dark cab windshield
      const wL0 = endSign * (hl - 1.4);
      const wL1 = endSign * (hl - 3.6);
      fillPoly([
        b.proj(wL0, -hw * 0.78, zSkirt + 4.4),
        b.proj(wL0, hw * 0.78, zSkirt + 4.4),
        b.proj(wL1, hw * 0.72, zEave - 1.2),
        b.proj(wL1, -hw * 0.72, zEave - 1.2),
      ], isNight ? '#58789c' : '#1d2d40');
    }

    // 6. Sculpted 3-Facet Rounded Silver-White Roof (brighter NW bevel, crisp sunlit crown, shaded SE bevel!)
    const rw = hw * 0.62;
    const nwBevelShade = b.dirShade(0, -1) * 0.5 + 0.62;
    const seBevelShade = b.dirShade(0, 1) * 0.5 + 0.54;
    fillPoly([
      b.proj(tailL, -hw, zEave),
      b.proj(noseL, -hw, zEave),
      b.proj(noseL - 0.8, -rw, zCrown),
      b.proj(tailL + 0.8, -rw, zCrown),
    ], shadeHex('#d4dce5', nwBevelShade, mode));
    fillPoly([
      b.proj(tailL, hw, zEave),
      b.proj(noseL, hw, zEave),
      b.proj(noseL - 0.8, rw, zCrown),
      b.proj(tailL + 0.8, rw, zCrown),
    ], shadeHex('#c4ceda', seBevelShade, mode));
    fillPoly([
      b.proj(tailL + 0.8, -rw, zCrown),
      b.proj(noseL - 0.8, -rw, zCrown),
      b.proj(noseL - 0.8, rw, zCrown),
      b.proj(tailL + 0.8, rw, zCrown),
    ], shadeHex('#e8eef5', 1.06, mode), outlineCol, lw * 0.75);

    // Rooftop HVAC pods
    for (const podL of [-14, 10]) {
      fillPoly([
        b.proj(podL - 4.5, -rw * 0.72, zCrown + 1.1),
        b.proj(podL + 4.5, -rw * 0.72, zCrown + 1.1),
        b.proj(podL + 4.5, rw * 0.72, zCrown + 1.1),
        b.proj(podL - 4.5, rw * 0.72, zCrown + 1.1),
      ], shadeHex('#bcc6d2', 0.98, mode), outlineCol, lw * 0.6);
    }

    const rDot = Math.max(1.4, 1.8 * b.s);

    if (isLead) {
      // Crisp overhead pantograph bar
      const p0 = b.proj(-22, -rw * 0.9, zCrown + 3.4);
      const p1 = b.proj(-22, rw * 0.9, zCrown + 3.4);
      vCtx.strokeStyle = isNight ? '#96a8c0' : '#4a5462';
      vCtx.lineWidth = Math.max(1.0, b.s * 0.7);
      vCtx.beginPath();
      vCtx.moveTo(p0[0], p0[1]);
      vCtx.lineTo(p1[0], p1[1]);
      vCtx.stroke();

      // Authentic rare SBB pantograph-to-catenary electric arc flash (suppressed while stationary at Bahnhof!)
      if (!isDwelling) {
        const sparkSlot = Math.floor(tSec * 14.0);
        const sparkHash = Math.sin(sparkSlot * 127.1 + Math.round(b.cx * 0.05) * 31.7) * 43758.5453;
        if ((sparkHash - Math.floor(sparkHash)) > (isNight ? 0.945 : 0.975)) {
          const pm = b.proj(-22, 0, zCrown + 3.6);
          const spR = Math.max(2.0, 3.2 * b.s);
          vCtx.save();
          vCtx.fillStyle = isNight ? 'rgba(110, 230, 255, 0.55)' : 'rgba(140, 235, 255, 0.35)';
          vCtx.beginPath();
          vCtx.arc(pm[0], pm[1], spR * 1.9, 0, Math.PI * 2);
          vCtx.fill();
          vCtx.fillStyle = '#f2feff';
          vCtx.fillRect(Math.round(pm[0] - spR * 0.5), Math.round(pm[1] - spR * 0.5), Math.max(2, Math.round(spR)), Math.max(2, Math.round(spR)));
          vCtx.restore();
        }
      }

      // Iconic Swiss 3-point white LED headlights (+ night headlight cone)
      if (isNight) {
        fillPoly([
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
      vCtx.fillStyle = isNight ? '#fff8cc' : '#fffbe6';
      for (const lp of leadLamps) {
        vCtx.fillRect(Math.round(lp[0] - rDot * 0.5), Math.round(lp[1] - rDot * 0.5), Math.max(1.5, Math.round(rDot)), Math.max(1.5, Math.round(rDot)));
      }
    }

    if (isTail) {
      // Twin Swiss SBB red LED taillights + night/sunset glow & subtle red rear rail reflection
      const tl1 = b.proj(-hl - 0.15, -hw * 0.58, zSkirt + 1.8);
      const tl2 = b.proj(-hl - 0.15, hw * 0.58, zSkirt + 1.8);
      if (isNight || isSunset) {
        fillPoly([
          b.proj(-hl, -hw * 0.8, zSkirt + 1.5),
          b.proj(-hl, hw * 0.8, zSkirt + 1.5),
          b.proj(-hl - 16, hw * 1.4, 0.2),
          b.proj(-hl - 16, -hw * 1.4, 0.2),
        ], isNight ? 'rgba(255, 40, 36, 0.18)' : 'rgba(255, 44, 38, 0.10)');
        vCtx.save();
        vCtx.fillStyle = isNight ? 'rgba(255, 42, 38, 0.36)' : 'rgba(255, 48, 42, 0.22)';
        for (const tp of [tl1, tl2]) {
          vCtx.beginPath();
          vCtx.arc(tp[0], tp[1], rDot * 2.2, 0, Math.PI * 2);
          vCtx.fill();
        }
        vCtx.restore();
      }
      vCtx.fillStyle = (isNight || isSunset) ? '#ff2e2e' : '#e02424';
      vCtx.fillRect(Math.round(tl1[0] - rDot * 0.5), Math.round(tl1[1] - rDot * 0.5), Math.max(1.5, Math.round(rDot)), Math.max(1.5, Math.round(rDot)));
      vCtx.fillRect(Math.round(tl2[0] - rDot * 0.5), Math.round(tl2[1] - rDot * 0.5), Math.max(1.5, Math.round(rDot)), Math.max(1.5, Math.round(rDot)));
    }
  }

  function drawShorelineWaves(shoreline, worldW, worldH, wScale, tSec, mode) {
    // Organic, hand-crafted 90s pixel-art shoreline wave arcs gently rolling INWARD toward the Kilchberg shore!
    // Keeps open Lake Zurich water calm and glassy while soft overlapping wavelets approach the bays & seawalls,
    // break into delicate pixelated foam at the water's edge, and clip cleanly behind piers/boathouses.
    if (!shoreline || shoreline.length < 4) return;

    const isNight = mode === 'night';
    const isSunset = mode === 'sunset';
    const s = scale * wScale;

    // Precompute smooth shoreline wave emitters (~140 evenly spaced coastal stations) once
    if (!drawShorelineWaves._stations || drawShorelineWaves._stations.len !== shoreline.length) {
      // Extra gentle smoothing pass over shoreline coordinates to remove sharp pier corners
      const sm = shoreline.map((p, i) => {
        let su = 0; let sv = 0; let cnt = 0;
        for (let k = -3; k <= 3; k++) {
          const j = Math.max(0, Math.min(shoreline.length - 1, i + k));
          su += shoreline[j][0];
          sv += shoreline[j][1];
          cnt++;
        }
        return [su / cnt, sv / cnt];
      });
      const stations = [];
      for (let i = 0; i < sm.length - 1; i++) {
        const a = sm[i];
        const b = sm[i + 1];
        const du = b[0] - a[0];
        const dv = b[1] - a[1];
        const segLen = Math.hypot(du, dv);
        if (segLen < 1e-5) continue;
        // Skip steep pier-edge jumps so waves never wrap awkwardly around pier sides
        if (Math.abs(dv) > Math.abs(du) * 1.45) continue;
        const tx = du / segLen;
        const ty = dv / segLen;
        // Outward-into-lake normal (SE direction: +x, +y)
        let nx = -ty;
        let ny = tx;
        if (ny < 0) { nx = -nx; ny = -ny; }
        nx = nx * 0.55 + 0.55 * 0.45;
        ny = ny * 0.55 + 0.83 * 0.45;
        const nm = Math.hypot(nx, ny) || 1;
        nx /= nm; ny /= nm;
        const subSteps = Math.max(1, Math.round(segLen / 0.0055));
        for (let st = 0; st < subSteps; st++) {
          const f = (st + 0.5) / subSteps;
          const idx = stations.length;
          const seed = ((idx * 2654435761) >>> 0) / 4294967296;
          stations.push({
            u: a[0] + du * f,
            v: a[1] + dv * f,
            tx,
            ty,
            nx,
            ny,
            seed,
          });
        }
      }
      drawShorelineWaves._stations = { len: shoreline.length, list: stations };
    }
    const stations = drawShorelineWaves._stations.list;

    const troughCol = isNight
      ? 'rgba(8, 22, 48, 0.30)'
      : (isSunset ? 'rgba(38, 30, 56, 0.24)' : 'rgba(12, 58, 78, 0.24)');
    const swellCol = isNight
      ? 'rgba(124, 170, 226, 0.44)'
      : (isSunset ? 'rgba(255, 198, 134, 0.48)' : 'rgba(176, 232, 240, 0.50)');
    const foamCol = isNight
      ? 'rgba(198, 226, 255, 0.66)'
      : (isSunset ? 'rgba(255, 234, 188, 0.72)' : 'rgba(242, 253, 255, 0.78)');

    const cycleSec = 5.6;
    const nWaves = 3;
    const maxDistWorld = 48.0 * wScale; // starts ~12 m offshore
    const minDistWorld = 4.0 * wScale;  // softly laps right at the water's edge

    ctx.save();
    ctx.lineCap = 'round';

    for (let i = 0; i < stations.length; i++) {
      const st = stations[i];
      // Quick viewport reject before running wave loop
      const baseSx = offsetX + st.u * worldW * scale;
      const baseSy = offsetY + st.v * worldH * scale;
      if (baseSx < -90 || baseSx > canvas.width + 90 || baseSy < -90 || baseSy > canvas.height + 90) continue;

      // Tangent vector in screen aspect
      const tanX = st.tx * worldW;
      const tanY = st.ty * worldH;
      const tanM = Math.hypot(tanX, tanY) || 1;
      const ux = tanX / tanM;
      const uy = tanY / tanM;

      for (let w = 0; w < nWaves; w++) {
        // Organic phase offset per coastal station so adjacent wavelets roll in naturally staggered arcs!
        const phaseOff = (w / nWaves) + Math.sin(i * 0.42 + w * 1.9) * 0.08 + (st.seed - 0.5) * 0.07;
        const p = (((tSec / cycleSec) + phaseOff) % 1 + 1) % 1;
        const alpha = p < 0.20 ? (p / 0.20) : (p > 0.80 ? ((1.0 - p) / 0.20) : 1.0);
        if (alpha <= 0.05) continue;

        const eased = 1.0 - Math.pow(1.0 - p, 1.35);
        const dist = maxDistWorld * (1.0 - eased) + minDistWorld * eased;
        const wx = st.u * worldW + st.nx * dist;
        const wy = st.v * worldH + st.ny * dist;

        const isBreaking = p > 0.66;
        const halfLenW = (15.0 + st.seed * 12.0) * (0.65 + 0.35 * Math.sin(p * Math.PI)) * wScale;
        // Subtle inward bow in world coords (center of wavelet curves slightly toward the shore!)
        const bowW = -2.2 * wScale;
        const wx0 = wx - ux * halfLenW;
        const wy0 = wy - uy * halfLenW;
        const wx1 = wx + ux * halfLenW;
        const wy1 = wy + uy * halfLenW;
        const wcx = wx + st.nx * bowW;
        const wcy = wy + st.ny * bowW;

        // Sample 9 points along the quadratic arc and break cleanly whenever any point hits
        // a shore element, seawall, dark rock, moored boat, or wooden pier!
        const subRuns = [];
        let curRun = [];
        const N_SUB = 8;
        for (let k = 0; k <= N_SUB; k++) {
          const t = k / N_SUB;
          const omt = 1 - t;
          const pwx = omt * omt * wx0 + 2 * omt * t * wcx + t * t * wx1;
          const pwy = omt * omt * wy0 + 2 * omt * t * wcy + t * t * wy1;
          let ok = true;
          if (waterMask) {
            const mx = Math.floor((pwx / worldW) * waterW);
            const my = Math.floor((pwy / worldH) * waterH);
            ok = (mx >= 0 && mx < waterW && my >= 0 && my < waterH && waterMask[my * waterW + mx] === 1);
          } else if (depthPixels) {
            const dx = Math.floor((pwx / worldW) * depthW);
            const dy = Math.floor((pwy / worldH) * depthH);
            ok = !(dx >= 0 && dx < depthW && dy >= 0 && dy < depthH && depthPixels[(dy * depthW + dx) * 4 + 2] > 128);
          }
          if (ok) {
            curRun.push([offsetX + pwx * scale, offsetY + pwy * scale]);
          } else {
            if (curRun.length >= 2) subRuns.push(curRun);
            curRun = [];
          }
        }
        if (curRun.length >= 2) subRuns.push(curRun);
        if (subRuns.length === 0) continue;

        const shX = st.nx * 2.1 * s;
        const shY = st.ny * 2.1 * s;
        for (const run of subRuns) {
          // 1. Subtle darker-teal shadow trough just offshore behind the crest
          ctx.globalAlpha = alpha * 0.65;
          ctx.strokeStyle = troughCol;
          ctx.lineWidth = Math.max(1.1, 1.8 * s);
          ctx.beginPath();
          for (let k = 0; k < run.length; k++) {
            if (k === 0) ctx.moveTo(run[k][0] + shX, run[k][1] + shY);
            else ctx.lineTo(run[k][0] + shX, run[k][1] + shY);
          }
          ctx.stroke();

          // 2. Soft curved aqua/foam wave crest gliding smoothly toward shore
          ctx.globalAlpha = alpha * (isBreaking ? 0.88 : 0.68);
          ctx.strokeStyle = isBreaking ? foamCol : swellCol;
          ctx.lineWidth = Math.max(1.0, (isBreaking ? 1.9 : 1.35) * s);
          ctx.beginPath();
          for (let k = 0; k < run.length; k++) {
            if (k === 0) ctx.moveTo(run[k][0], run[k][1]);
            else ctx.lineTo(run[k][0], run[k][1]);
          }
          ctx.stroke();

          // 3. Delicate pixel-art foam sparkle at peak shoreline lap
          if (isBreaking && alpha > 0.35 && run.length >= 3) {
            const mid = run[Math.floor(run.length / 2)];
            const pxSz = Math.max(1.2, 1.5 * s);
            ctx.globalAlpha = alpha * 0.9;
            ctx.fillStyle = foamCol;
            ctx.fillRect(Math.round(mid[0] - pxSz * 1.4), Math.round(mid[1] - pxSz * 0.5), Math.round(pxSz * 2.8), Math.max(1, Math.round(pxSz)));
          }
        }
      }
    }
    ctx.restore();
  }

  function draw3DCyclist(pos, colorIdx, wScale, mode, tSec) {
    // Crisp, pixel-grid-snapped 90s isometric pixel-art cyclist (matches exact 0.25 m/px diorama grid!)
    const b = makeScreenIsoBasis(pos.wx, pos.wy, pos.tx, pos.ty, wScale);
    if (b.cx < -28 || b.cx > canvas.width + 28 || b.cy < -28 || b.cy > canvas.height + 28) return;

    const isNight = mode === 'night';
    const jerseys = ['#d9382e', '#2563eb', '#eab308', '#0d9488', '#ea580c', '#16a34a'];
    const helmets = ['#f4f7fa', '#ef4444', '#facc15', '#38bdf8', '#f4f7fa', '#fb923c'];
    const jerseyHex = jerseys[colorIdx % jerseys.length];
    const helmetHex = helmets[(colorIdx * 3 + 1) % helmets.length];
    const pedal = Math.sin(tSec * 11.0 + colorIdx * 1.7);
    const pSz = Math.max(1.0, b.s); // 1 diorama world pixel on screen

    // Helper: snap crisp pixel block at local (l, w, z) to exact pixel grid
    const pix = (l, w, z, pw, ph, col) => {
      const [x, y] = b.proj(l, w, z);
      vCtx.fillStyle = col;
      vCtx.fillRect(
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

    // 1. Grounded pixel drop shadow
    pix(0.0, 0.4, 0.0, 6.4, 1.6, isNight ? 'rgba(6,10,20,0.52)' : 'rgba(18,24,32,0.34)');

    // 2. Crisp isometric pixel wheels (rear & front: dark tire ring + bright hub pixel)
    for (const wl of [-2.5, 2.6]) {
      pix(wl, 0, 1.25, 2.3, 2.5, tireCol);
      pix(wl, 0, 1.25, 1.0, 1.0, hubCol);
    }

    // 3. Bicycle diamond frame, fork, saddle & handlebars
    pix(-1.1, 0, 2.1, 2.7, 0.85, frameCol); // rear stay / bottom bracket
    pix(0.5, 0, 2.9, 2.9, 0.85, frameCol);  // top tube
    pix(2.0, 0, 2.5, 0.9, 2.3, frameCol);   // front fork
    pix(-1.2, 0, 3.4, 1.4, 0.75, tireCol);  // saddle
    pix(2.1, 0, 3.8, 1.2, 0.8, tireCol);    // handlebars

    // 4. Animated pedaling legs (cycling shorts + calf + shoe)
    const pUp = pedal * 0.65;
    pix(-0.8, 0.15, 3.1, 1.5, 1.4, shortsCol);
    pix(-0.1 + pUp * 0.5, 0.2, 2.0 - pUp * 0.5, 0.95, 1.35, skinCol);
    pix(0.1 + pUp * 0.6, 0.2, 1.1 - pUp * 0.6, 1.1, 0.8, tireCol);

    // 5. Sculpted leaning rider torso (vibrant 2-tone NW-sunlit jersey + outstretched arm gripping handlebars!)
    pix(-0.1, 0, 4.7, 2.3, 2.0, jDark);
    pix(0.0, -0.2, 5.2, 2.0, 1.3, jLit);    // sunlit upper back/shoulder highlight
    pix(1.3, 0.1, 4.4, 1.6, 0.95, jLit);    // upper arm reaching forward
    pix(2.0, 0.1, 3.9, 0.85, 0.85, skinCol); // hand on handlebar

    // 6. Proportional pixel-art face & sleek aerodynamic cycling helmet
    pix(1.1, 0.1, 6.2, 1.25, 1.15, skinCol); // face
    pix(1.0, 0.0, 6.9, 1.85, 1.0, helmCol);  // sleek helmet shell
    pix(1.45, 0.0, 6.5, 1.15, 0.5, tireCol); // sunglasses / helmet visor

    // 7. Crisp white front headlight + light cone & blinking red rear bike light at night/sunset
    if (isNight || mode === 'sunset') {
      if (isNight) {
        fillPoly([
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
          vCtx.save();
          vCtx.fillStyle = 'rgba(255, 46, 46, 0.34)';
          vCtx.beginPath();
          vCtx.arc(rp[0], rp[1], Math.max(2.0, 2.2 * pSz), 0, Math.PI * 2);
          vCtx.fill();
          vCtx.restore();
        }
        pix(-2.7, 0, 2.9, 1.2, 1.2, '#ff2e2e');
      } else {
        pix(-2.7, 0, 2.9, 0.9, 0.9, '#991b1b');
      }
    }
  }

  function draw3DPedestrian(pos, colorIdx, wScale, mode, tSec) {
    // Crisp, pixel-grid-snapped 90s isometric walking villager!
    const b = makeScreenIsoBasis(pos.wx, pos.wy, pos.tx, pos.ty, wScale);
    if (b.cx < -18 || b.cx > canvas.width + 18 || b.cy < -18 || b.cy > canvas.height + 18) return;

    const isNight = mode === 'night';
    const jackets = ['#c53030', '#2b6cb0', '#2f855a', '#d69e2e', '#6b46c1', '#dd6b20', '#cbd5e0', '#2c7a7b'];
    const hairCols = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
    const jacketHex = jackets[colorIdx % jackets.length];
    const hairHex = hairCols[(colorIdx * 2 + 1) % hairCols.length];
    const stride = Math.sin(tSec * 6.8 + colorIdx * 2.3);
    const pSz = Math.max(1.0, b.s);

    const pix = (l, w, z, pw, ph, col) => {
      const [x, y] = b.proj(l, w, z);
      vCtx.fillStyle = col;
      vCtx.fillRect(
        Math.round(x - pw * 0.5 * pSz),
        Math.round(y - ph * 0.5 * pSz),
        Math.max(1, Math.round(pw * pSz)),
        Math.max(1, Math.round(ph * pSz)),
      );
    };

    const pantsCol = shadeHex('#2a3444', 0.92, mode);
    const jLit = shadeHex(jacketHex, 1.10, mode);
    const jDark = shadeHex(jacketHex, 0.78, mode);
    const skinCol = shadeHex('#eabfa0', 1.0, mode);
    const hairCol = shadeHex(hairHex, 0.95, mode);

    // 1. Grounded pixel shadow
    pix(0, 0.3, 0, 2.4, 1.2, isNight ? 'rgba(6,10,20,0.48)' : 'rgba(18,24,32,0.34)');

    // 2. Alternating striding legs
    pix(stride * 0.85, -0.35, 1.3, 0.95, 2.0, pantsCol);
    pix(-stride * 0.85, 0.35, 1.3, 0.95, 2.0, pantsCol);

    // 3. Two-tone shaded jacket torso
    pix(0, 0, 3.6, 1.8, 2.3, jDark);
    pix(0, -0.2, 4.1, 1.5, 1.4, jLit);

    // 4. Proportional pixel head (skin face + hair crown)
    pix(0, 0, 5.4, 1.3, 1.2, skinCol);
    pix(0, 0, 6.0, 1.4, 0.75, hairCol);
  }

  function isWaterUV(u, v) {
    if (!waterMask || waterW <= 0 || waterH <= 0) return true;
    const mx = Math.floor(u * waterW);
    const my = Math.floor(v * waterH);
    if (mx < 0 || mx >= waterW || my < 0 || my >= waterH) return false;
    return waterMask[my * waterW + mx] === 1;
  }

  function getUniqueBusStops(worldW, worldH) {
    if (!animData || !animData.roads) return [];
    if (animData._uniqueBusStops) return animData._uniqueBusStops;
    const masterW = animData.canvas_width || 12331;
    const masterH = animData.canvas_height || 5444;
    const unique = [];
    for (let rIdx = 0; rIdx < animData.roads.length; rIdx++) {
      const rd = animData.roads[rIdx];
      const stops = rd.stops;
      if (!stops || !stops.length) continue;
      const isMain = rd.kind === 'seestrasse';
      for (let sIdx = 0; sIdx < stops.length; sIdx++) {
        const sf = stops[sIdx];
        const pos = samplePathAt(rd.pts, sf, masterW, masterH, 3);
        if (!pos) continue;
        const u = pos.wx / masterW;
        const v = pos.wy / masterH;
        const isoY = 0.55;
        const gx = pos.tx;
        const gy = pos.ty / isoY;
        const gm = Math.hypot(gx, gy) || 1;
        const rx = -gy / gm;
        const ry = (gx / gm) * isoY;
        // Deduplicate shared physical stop platforms within 18 master px
        let matched = null;
        for (let i = 0; i < unique.length; i++) {
          const ex = unique[i];
          if (Math.hypot((ex.u - u) * masterW, (ex.v - v) * masterH) < 18) {
            matched = ex;
            break;
          }
        }
        if (matched) {
          matched.refs.push({ rd, stopIdx: sIdx });
        } else {
          unique.push({
            u,
            v,
            tx: pos.tx,
            ty: pos.ty,
            rx,
            ry,
            d16: pos.d16,
            isMain,
            refs: [{ rd, stopIdx: sIdx }],
            name: (rd.stop_names && rd.stop_names[sIdx]) || '',
          });
        }
      }
    }
    animData._uniqueBusStops = unique;
    return unique;
  }

  function drawAnimations(worldW, worldH, tSec) {
    const wScale = worldW / (animData.canvas_width || 12331);
    const isNight = currentMode === 'night';
    const isSunset = currentMode === 'sunset';

    // Reset per-frame telemetry counters
    depthFrameStats.direct = 0;
    depthFrameStats.fullCull = 0;
    depthFrameStats.partial = 0;
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

    // 1. Gentle Series of Shoreline Waves Rolling Inward Toward the Kilchberg Shore
    if (animData.ambient && animData.ambient.shoreline) {
      drawShorelineWaves(animData.ambient.shoreline, worldW, worldH, wScale, tSec, currentMode);
    }

    // 2. Lake Zurich ZSG Paddle Steamer, Sailboats & Boesch Runabout (depth-masked hulls, wakes, foam, steam & nav lights!)
    for (let sIdx = 0; sIdx < (animData.ships || []).length; sIdx++) {
      const ship = animData.ships[sIdx];
      // Moor/hide recreational craft at night; keep warmly lit dinner-cruise ZSG steamer sailing!
      if (isNight && ship.kind !== 'zsg_steamer') continue;

      let frac;
      let speedRatio = 1.0;
      let isDocked = false;
      if (ship.closed) {
        const cyc = ship.length_m / Math.max(0.5, ship.speed_mps);
        frac = (((tSec / cyc) + (ship.phase || 0)) % 1 + 1) % 1;
      } else {
        const st = evalWithStationStop(tSec, ship.length_m, ship.speed_mps, ship.stop_frac, ship.dwell_sec, ship.phase || 0, 5.0, 6.0);
        frac = st.frac;
        speedRatio = st.speedRatio;
        isDocked = st.isDwelling;
      }
      if (frac < 0 || frac > 1) continue;
      const pos = samplePathAt(ship.pts, frac, worldW, worldH, 3);
      if (!pos) continue;

      livingFrameCounts.ships++;
      const isSteamer = ship.kind === 'zsg_steamer';
      const isMotor = ship.kind === 'motorboat';
      const wakeCount = isSteamer ? 14 : (isMotor ? 10 : 6);
      const wakeStep = ship.closed ? 0.0045 : 0.0026;

      // Water surface V-wake, central prop-wash & bow foam scale smoothly by speedRatio (0 while docked!)
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
            ? ((frac - k * wakeStep) % 1 + 1) % 1
            : frac - k * wakeStep;
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

        // Crisp bow foam flecks right at the waterline (scales smoothly by speedRatio)
        const bowOff = (isSteamer ? 30 : (isMotor ? 10 : 7)) * wScale;
        const bowA = (isNight ? 0.55 : 0.78) * speedRatio;
        const foamCol = isNight
          ? `rgba(176,208,242,${bowA.toFixed(2)})`
          : `rgba(248,254,255,${bowA.toFixed(2)})`;
        drawPixelRectWorld(pos.wx + pos.tx * bowOff, pos.wy + pos.ty * bowOff, 3.6, 1.8, foamCol, wScale);
      }

      // Shimmering warm golden cabin light reflection dancing on dark Lake Zurich water beneath ZSG Steamer at Night!
      if (isNight && isSteamer) {
        for (let r = 0; r < 5; r++) {
          const along = (-16 + r * 8) * wScale;
          for (let d = 1; d <= 3; d++) {
            const rx = pos.wx + pos.tx * along + Math.sin(tSec * 3.8 + r * 1.9 + d * 1.3) * 2.4 * wScale;
            const ry = pos.wy + pos.ty * along + (5 + d * 3.4) * wScale;
            const ra = (0.42 - d * 0.10).toFixed(2);
            drawPixelRectWorld(rx, ry, 4.2, 1.6, `rgba(255,214,112,${ra})`, wScale);
          }
        }
      }

      // Subtle buoyant water bobbing + depth-masked vessel sprite, paddlewheel foam, funnel steam & maritime nav lights
      const bobY = Math.sin(tSec * (isSteamer ? 1.8 : 2.6) + sIdx * 1.9) * (isSteamer ? 0.55 : 0.85) * wScale;
      const angIdx = ((Math.round((Math.atan2(pos.ty, pos.tx) / (Math.PI * 2)) * 32) % 32) + 32) % 32;
      const sp = getVehicleSprite(ship.kind, 0, angIdx, currentMode);
      const shipBounds = isSteamer
        ? { ex: 108 * wScale, eyUp: 92 * wScale, eyDn: 74 * wScale }
        : (isMotor
          ? { ex: 26 * wScale, eyUp: 28 * wScale, eyDn: 22 * wScale }
          : { ex: 34 * wScale, eyUp: 56 * wScale, eyDn: 24 * wScale });

      drawDepthMasked(pos.wx, pos.wy, shipBounds, pos.d16, worldW, worldH, () => {
        const sPx = scale * wScale;
        const nx = -pos.ty * 0.72;
        const ny = pos.tx * 0.52;

        // Animated white side-paddlewheel foam churn on both flanks (halts cleanly to 0 when docked!)
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
              drawPixelRectWorld(fWx, fWy, 2.4 + (1 - prog) * 1.6, 1.5, fCol, wScale);
            }
          }
        }

        // Main isometric ship sprite
        blitWorldSprite(sp, pos.wx, pos.wy + bobY, wScale);

        if (isSteamer) {
          // Gentle funnel steam wisp (idling softer when docked)
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
            drawPixelRectWorld(sWx - sz * 0.5 * wScale, sWy - sz * 0.4 * wScale, sz, sz * 0.72, sCol, wScale);
          }

          // Maritime navigation lights at Sunset & Night (port red, starboard green, masthead & stern)
          if (isSunset || isNight) {
            const navAlpha = isNight ? 0.92 : 0.55;
            const navPts = [
              { s: 18, w: -9.5, z: 19.5, col: '#ff3b3b', glow: 'rgba(255, 59, 59, 0.34)' },   // Port (red)
              { s: 18, w: 9.5, z: 19.5, col: '#22e584', glow: 'rgba(34, 229, 132, 0.34)' },   // Starboard (green)
              { s: 22, w: 0, z: 27.5, col: '#fff3c4', glow: 'rgba(255, 243, 196, 0.34)' },    // Masthead (warm white)
            ];
            if (isNight) {
              navPts.push({ s: -64, w: 0, z: 12.5, col: '#ffe49a', glow: 'rgba(255, 228, 154, 0.30)' }); // Stern
            }
            const dotSz = Math.max(2, Math.round(2.0 * sPx));
            vCtx.save();
            for (const nl of navPts) {
              const lx = offsetX + (pos.wx + (pos.tx * nl.s + nx * nl.w) * wScale) * scale;
              const ly = offsetY + (pos.wy + bobY + (pos.ty * nl.s + ny * nl.w - nl.z) * wScale) * scale;
              vCtx.globalAlpha = navAlpha;
              vCtx.fillStyle = nl.glow;
              vCtx.beginPath();
              vCtx.arc(lx, ly, Math.max(2.6, 4.2 * sPx), 0, Math.PI * 2);
              vCtx.fill();
              vCtx.fillStyle = nl.col;
              vCtx.fillRect(Math.round(lx - dotSz * 0.5), Math.round(ly - dotSz * 0.5), dotSz, dotSz);
            }
            vCtx.restore();
          }
        }
      }, isSteamer ? 6.0 : 4.0);
    }

    // 3. Road Cars, VBZ/ZVV Buses (Line 161 Articulated & Line 165 Regional), Bus-Stop Commuters, Cyclists & Sidewalk Pedestrians
    const roadDrawList = [];
    const dwellingStops = new Set(); // "roadId:stopIdx" currently hosting a dwelling bus
    for (let rIdx = 0; rIdx < (animData.roads || []).length; rIdx++) {
      const rd = animData.roads[rIdx];
      const busCount = rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0);
      const carCount = rd.car_count || 3;

      // 3a. VBZ/ZVV Buses (multi-stop exact schedule + curb lay-by pull-in!)
      for (let bIdx = 0; bIdx < busCount; bIdx++) {
        // At night keep 1 active bus per bus route (vIdx === 0 -> 6 night buses, keeping Follow: Bus live!)
        if (isNight && bIdx > 0) continue;
        const st = evalBusState(rd, bIdx, tSec);
        if (st.frac < 0.001 || st.frac > 0.999) continue;
        if (st.isDwelling && st.stopIdx >= 0) {
          dwellingStops.add(`${rd.id}:${st.stopIdx}`);
        }
        const pullIn = (1.0 - st.speedRatio) * 2.0 * wScale;
        const shiftCurb = (p) => {
          if (!p || pullIn < 0.01) return p;
          const isoY = 0.55;
          const gx = p.tx;
          const gy = p.ty / isoY;
          const gm = Math.hypot(gx, gy) || 1;
          const rx = -gy / gm;
          const ry = (gx / gm) * isoY;
          return { ...p, wx: p.wx + rx * pullIn, wy: p.wy + ry * pullIn };
        };

        const isLine161 = rd.kind === 'seestrasse';
        if (isLine161) {
          const fFront = st.frac;
          const fMidFront = fFront - 10.2 / rd.length_m;
          const fMidRear = fFront - 11.8 / rd.length_m;
          const fRear = fFront - 19.0 / rd.length_m;
          if (fRear >= 0.001) {
            const pFront = shiftCurb(samplePathAt(rd.pts, fFront, worldW, worldH, 3));
            const pMidFront = shiftCurb(samplePathAt(rd.pts, fMidFront, worldW, worldH, 3));
            const pMidRear = shiftCurb(samplePathAt(rd.pts, fMidRear, worldW, worldH, 3));
            const pRear = shiftCurb(samplePathAt(rd.pts, fRear, worldW, worldH, 3));
            if (pFront && pMidFront && pMidRear && pRear && (depthPixels || (!pFront.occ && !pRear.occ))) {
              livingFrameCounts.buses++;
              const midWx = (pFront.wx + pRear.wx) * 0.5;
              const midWy = (pFront.wy + pRear.wy) * 0.5;
              const midD16 = Math.round((pFront.d16 + pRear.d16) * 0.5);
              roadDrawList.push({
                type: 'bus_artic',
                pos: { wx: midWx, wy: midWy, tx: pFront.tx, ty: pFront.ty, d16: midD16 },
                pRear, pMidRear, pMidFront, pFront,
                speedRatio: st.speedRatio,
                isDwelling: st.isDwelling,
              });
              continue;
            }
          }
        }

        const pos = shiftCurb(samplePathAt(rd.pts, st.frac, worldW, worldH, 3));
        if (!pos || (!depthPixels && pos.occ)) continue;
        livingFrameCounts.buses++;
        roadDrawList.push({
          type: 'bus',
          pos,
          routeNum: isLine161 ? '161' : '165',
          speedRatio: st.speedRatio,
          isDwelling: st.isDwelling,
        });
      }

      // 3b. Road Cars, Vans & Rare Swiss Emergency Vehicles (deterministic ~55% night reduction)
      const laneSpeed = Math.max(1.0, rd.speed_mps * (busCount > 0 ? 0.88 : 0.96));
      const cyc = rd.length_m / laneSpeed;
      const maxJitter = Math.min(0.011, 0.24 / Math.max(1, carCount));
      for (let cIdx = 0; cIdx < carCount; cIdx++) {
        const vIdx = busCount + cIdx;
        if (isNight && ((vIdx * 7 + rIdx * 3) % 20) >= 9) continue;
        const jitter = Math.sin(tSec * 0.28 + vIdx * 2.17 + rIdx * 1.3) * maxJitter;
        const frac = ((((tSec / cyc) + (rd.phase || 0) + (cIdx + 0.35) / Math.max(1, carCount) + jitter) % 1) + 1) % 1;
        if (frac < 0.001 || frac > 0.999) continue;
        const pos = samplePathAt(rd.pts, frac, worldW, worldH, 3);
        if (!pos || (!depthPixels && pos.occ)) continue;
        livingFrameCounts.cars++;
        roadDrawList.push({ type: 'car', pos, colorIdx: vIdx + rIdx * 3 });
      }

      // 3c. Cyclists & Sidewalk Pedestrians (never on A3 motorway; zoom LOD culled below scale < 0.35; deterministic night reduction!)
      if (rd.kind !== 'motorway' && scale >= 0.35) {
        const isMain = rd.kind === 'seestrasse';
        const nCyclists = isMain ? 10 : 7;
        const nPeds = isMain ? 18 : 14;
        const bikeCyc = rd.length_m / 4.8;
        const pedCyc = rd.length_m / 1.35;

        for (let bIdx = 0; bIdx < nCyclists; bIdx++) {
          if (isNight && ((bIdx + rIdx) % 5 !== 0)) continue;
          const frac = ((((tSec / bikeCyc) + (rd.phase || 0) * 0.7 + (bIdx + 0.35) / nCyclists) % 1) + 1) % 1;
          if (frac < 0.001 || frac > 0.999) continue;
          const base = samplePathAt(rd.pts, frac, worldW, worldH, 3);
          if (!base || (!depthPixels && base.occ)) continue;
          const isoY = 0.55;
          const gx = base.tx;
          const gy = base.ty / isoY;
          const gm = Math.hypot(gx, gy) || 1;
          const rx = -gy / gm;
          const ry = (gx / gm) * isoY;
          const latPx = (isMain ? 3.0 : 2.0) * wScale;
          livingFrameCounts.cyclists++;
          roadDrawList.push({
            type: 'cyclist',
            pos: { ...base, wx: base.wx + rx * latPx, wy: base.wy + ry * latPx },
            colorIdx: bIdx + rIdx * 5,
          });
        }

        for (let pIdx = 0; pIdx < nPeds; pIdx++) {
          if (isNight && ((pIdx + rIdx) % 4 !== 0)) continue;
          const dir = (pIdx % 2 === 0) ? 1 : -1;
          const rawF = ((dir * (tSec / pedCyc) + (rd.phase || 0) * 1.3 + (pIdx + 0.17) / nPeds) % 1 + 1) % 1;
          if (rawF < 0.001 || rawF > 0.999) continue;
          const base = samplePathAt(rd.pts, rawF, worldW, worldH, 3);
          if (!base || (!depthPixels && base.occ)) continue;
          const isoY = 0.55;
          const gx = base.tx;
          const gy = base.ty / isoY;
          const gm = Math.hypot(gx, gy) || 1;
          const rx = -gy / gm;
          const ry = (gx / gm) * isoY;
          const latPx = (isMain ? 6.0 : 4.6) * wScale;
          livingFrameCounts.roadPeds++;
          roadDrawList.push({
            type: 'ped',
            pos: {
              ...base,
              wx: base.wx + rx * latPx,
              wy: base.wy + ry * latPx,
              tx: base.tx * dir,
              ty: base.ty * dir,
            },
            colorIdx: pIdx + rIdx * 7,
          });
        }
      }
    }

    // 3d. Deduplicated Waiting VBZ/ZVV Bus-Stop Mini-Commuters (skipped when scale < 0.35 for zoom LOD)
    if (scale >= 0.35) {
      const busStops = getUniqueBusStops(worldW, worldH);
      const stopCoats = ['#2563eb', '#d9382e', '#0d9488', '#334155', '#d97706', '#16a34a', '#7c3aed'];
      const stopHairs = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
      for (let i = 0; i < busStops.length; i++) {
        const bs = busStops[i];
        const busHere = bs.refs.some((ref) => dwellingStops.has(`${ref.rd.id}:${ref.stopIdx}`));
        const nWait = isNight ? 1 : (2 + (i % 2));
        const curbBase = (bs.isMain ? 6.8 : 5.4) - (busHere ? 1.5 : 0);
        for (let k = 0; k < nWait; k++) {
          const along = ((k - (nWait - 1) * 0.5) * 4.2 + Math.sin(tSec * 0.45 + i * 1.7 + k) * 0.4) * wScale;
          const lat = (curbBase + (k % 2) * 0.8) * wScale;
          const wx = bs.u * worldW + bs.rx * lat + bs.tx * along;
          const wy = bs.v * worldH + bs.ry * lat + bs.ty * along;
          livingFrameCounts.busStopCommuters++;
          roadDrawList.push({
            type: 'stop_commuter',
            pos: { wx, wy, d16: bs.d16 },
            coat: shadeHex(stopCoats[(i * 3 + k) % stopCoats.length], 1.0, currentMode),
            pants: shadeHex('#243040', 1.0, currentMode),
            hair: stopHairs[(i + k) % stopHairs.length],
            stride: busHere ? tSec * 6.5 + k : tSec * 1.1 + i + k,
            bag: (k === 0 && i % 2 === 0) ? '#334155' : null,
          });
        }
      }
    }

    roadDrawList.sort((a, b) => a.pos.wy - b.pos.wy);
    for (const v of roadDrawList) {
      let bounds;
      let clampUp = 4.0;
      if (v.type === 'bus_artic') {
        const hdx = Math.abs(v.pFront.wx - v.pRear.wx) * 0.5;
        const hdy = Math.abs(v.pFront.wy - v.pRear.wy) * 0.5;
        const nExtra = isNight ? 30 * wScale : 6 * wScale;
        bounds = {
          ex: hdx + 16 * wScale + nExtra,
          eyUp: hdy + 20 * wScale + (isNight ? 20 * wScale : 0),
          eyDn: hdy + 10 * wScale + (isNight ? 20 * wScale : 0),
        };
        clampUp = 4.0;
      } else if (v.type === 'bus') {
        const atx = Math.abs(v.pos.tx);
        const aty = Math.abs(v.pos.ty);
        const nExtra = isNight ? 32 * wScale : 4 * wScale;
        bounds = {
          ex: (atx * 24 + 9) * wScale + nExtra,
          eyUp: (aty * 24 + 16) * wScale + (isNight ? 18 * wScale : 0),
          eyDn: (aty * 24 + 7) * wScale + (isNight ? 18 * wScale : 0),
        };
        clampUp = 4.0;
      } else if (v.type === 'car') {
        const atx = Math.abs(v.pos.tx);
        const aty = Math.abs(v.pos.ty);
        const nExtra = isNight ? 24 * wScale : (isSunset ? 10 * wScale : 2 * wScale);
        bounds = {
          ex: (atx * 12 + 7) * wScale + nExtra,
          eyUp: (aty * 12 + 11) * wScale + (isNight ? 14 * wScale : 0),
          eyDn: (aty * 12 + 6) * wScale + (isNight ? 14 * wScale : 0),
        };
        clampUp = 4.0;
      } else if (v.type === 'cyclist') {
        bounds = {
          ex: (isNight ? 14 : 7) * wScale,
          eyUp: 11 * wScale,
          eyDn: (isNight ? 9 : 4) * wScale,
        };
        clampUp = 2.5;
      } else {
        bounds = { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };
        clampUp = 2.0;
      }

      drawDepthMasked(v.pos.wx, v.pos.wy, bounds, v.pos.d16, worldW, worldH, () => {
        if (v.type === 'bus_artic') {
          draw3DArticulatedBus(v.pRear, v.pMidRear, v.pMidFront, v.pFront, wScale, currentMode, tSec, v.speedRatio, v.isDwelling);
        } else if (v.type === 'bus') {
          draw3DBus(v.pos, wScale, currentMode, tSec, v.speedRatio, v.isDwelling, v.routeNum);
        } else if (v.type === 'car') {
          draw3DCar(v.pos, v.colorIdx, wScale, currentMode, tSec);
        } else if (v.type === 'cyclist') {
          draw3DCyclist(v.pos, v.colorIdx, wScale, currentMode, tSec);
        } else if (v.type === 'stop_commuter') {
          drawMiniPerson(
            offsetX + v.pos.wx * scale,
            offsetY + v.pos.wy * scale,
            scale * wScale * 0.90,
            v.coat, v.pants, v.hair, isNight, v.stride, v.bag,
          );
        } else {
          draw3DPedestrian(v.pos, v.colorIdx, wScale, currentMode, tSec);
        }
      }, clampUp);
    }

    // 4. SBB Seebahn Multi-Carriage Trains (dead-center Bahnhof stop math & articulated 2-point wagons!)
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
        if (pFront && pRear && (depthPixels || (!pFront.occ && !pRear.occ))) {
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
      if (units.length > 0) livingFrameCounts.trains++;
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
        drawDepthMasked(u.midWx, u.midWy, trainBounds, u.midD16, worldW, worldH, () => {
          draw3DTrainUnit(
            u.pRear, u.pFront, tr.kind, u.variant, wScale, currentMode,
            u.nextRear, u.nextFront, tSec, trSt.isDwelling, trSt.dwellProgress,
          );
        }, 5.0);
      }
    }

    // 5. Waving Swiss & Kilchberg Flags, Lindt Hochkamin Steam, Village Chimneys, Dorfbrunnen Fountains & Lake Zurich Gulls
    if (animData.ambient) {
      const waveStep = Math.floor(tSec * 5.0) % 4;
      for (let fIdx = 0; fIdx < (animData.ambient.swiss_flags || []).length; fIdx++) {
        const fl = animData.ambient.swiss_flags[fIdx];
        const fx = fl.uv[0] * worldW;
        const fy = fl.uv[1] * worldH;
        const fPhase = (waveStep + fIdx) % 4;
        // Thin silver flagpole with golden finial ball
        drawPixelRectWorld(fx, fy - 15 * wScale, 1.5, 16, isNight ? '#8a99b2' : '#d8dce2', wScale);
        drawPixelRectWorld(fx - 0.3 * wScale, fy - 16 * wScale, 2.1, 1.6, isNight ? '#c8a852' : '#f2ca52', wScale);
        const segY0 = fy - 14.5 * wScale;
        const dy1 = (fPhase === 1 ? -1 : (fPhase === 3 ? 1 : 0)) * wScale;
        const dy2 = (fPhase === 2 ? -1 : (fPhase === 0 ? 1 : 0)) * wScale;
        const redFlag = isNight ? '#9e2828' : '#d62c28';
        const whiteCross = isNight ? '#cfd6e2' : '#f8f6f0';
        drawPixelRectWorld(fx + 1.5 * wScale, segY0, 3, 6, redFlag, wScale);
        drawPixelRectWorld(fx + 4.2 * wScale, segY0 + dy1, 3.2, 6, redFlag, wScale);
        drawPixelRectWorld(fx + 7.2 * wScale, segY0 + dy2, 2.8, 6, redFlag, wScale);
        drawPixelRectWorld(fx + 4.6 * wScale, segY0 + dy1 + 1.2 * wScale, 1.4, 3.6, whiteCross, wScale);
        drawPixelRectWorld(fx + 3.4 * wScale, segY0 + dy1 + 2.3 * wScale, 3.8, 1.4, whiteCross, wScale);

        // At Bahnhof / Gemeindehaus (fIdx === 3), fly the authentic Kilchberg ZH Municipal Crest Flag beside the Swiss flag!
        if (fIdx === 3) {
          const kx = fx + 13 * wScale;
          const ky = fy + 2 * wScale;
          const kPhase = (waveStep + 2) % 4;
          const kdy1 = (kPhase === 1 ? -1 : (kPhase === 3 ? 1 : 0)) * wScale;
          const kdy2 = (kPhase === 2 ? -1 : (kPhase === 0 ? 1 : 0)) * wScale;
          drawPixelRectWorld(kx, ky - 14 * wScale, 1.5, 15, isNight ? '#8a99b2' : '#d8dce2', wScale);
          const kTop = isNight ? '#9c2c2c' : '#cc2e2a';
          const kGold = isNight ? '#b59238' : '#e8be42';
          drawPixelRectWorld(kx + 1.5 * wScale, ky - 14 * wScale, 3, 3.4, kTop, wScale);
          drawPixelRectWorld(kx + 4.2 * wScale, ky - 14 * wScale + kdy1, 3.2, 3.4, kTop, wScale);
          drawPixelRectWorld(kx + 7.2 * wScale, ky - 14 * wScale + kdy2, 2.8, 3.4, kTop, wScale);
          drawPixelRectWorld(kx + 1.5 * wScale, ky - 10.6 * wScale, 3, 2.6, kGold, wScale);
          drawPixelRectWorld(kx + 4.2 * wScale, ky - 10.6 * wScale + kdy1, 3.2, 2.6, kGold, wScale);
          drawPixelRectWorld(kx + 7.2 * wScale, ky - 10.6 * wScale + kdy2, 2.8, 2.6, kGold, wScale);
          drawPixelRectWorld(kx + 4.8 * wScale, ky - 13.4 * wScale + kdy1, 1.6, 3.8, whiteCross, wScale);
        }
      }

      if (animData.ambient.chimney_steam) {
        // Multi-layered sunlit + shaded 90s pixel steam clouds rising from the 43.6 m Lindt brick Hochkamin!
        const stUv = animData.ambient.chimney_steam.uv;
        const cxWorld = stUv[0] * worldW;
        const cyWorld = stUv[1] * worldH;
        for (let p = 0; p < 10; p++) {
          const age = (((tSec * 0.28 + p / 10) % 1) + 1) % 1;
          const driftX = -age * 34 * wScale + Math.sin(age * 6.5 + p * 1.4) * 3.0 * wScale;
          const riseY = -(3 + age * 46) * wScale;
          const pxWorld = Math.round(cxWorld + driftX);
          const pyWorld = Math.round(cyWorld + riseY);
          const alpha = (1 - age) * (age < 0.12 ? age / 0.12 : 0.72);
          const sz = 2.6 + age * 7.8;
          const shadeCol = isNight
            ? `rgba(110,126,158,${(alpha * 0.48).toFixed(2)})`
            : (isSunset ? `rgba(218,174,162,${(alpha * 0.62).toFixed(2)})` : `rgba(204,210,220,${(alpha * 0.60).toFixed(2)})`);
          const litCol = isNight
            ? `rgba(154,170,204,${(alpha * 0.56).toFixed(2)})`
            : (isSunset ? `rgba(255,226,200,${(alpha * 0.78).toFixed(2)})` : `rgba(248,248,244,${(alpha * 0.78).toFixed(2)})`);
          drawPixelRectWorld(pxWorld - sz * 0.48 * wScale, pyWorld - sz * 0.25 * wScale, sz, sz * 0.68, shadeCol, wScale);
          drawPixelRectWorld(pxWorld - sz * 0.56 * wScale, pyWorld - sz * 0.50 * wScale, sz * 0.82, sz * 0.52, litCol, wScale);
        }
      }

      // Cozy Hillside Village Chimney Smoke Wisps (M3 ambient.village_chimneys, Sunset & Night)
      if ((isSunset || isNight) && (scale * wScale >= 0.22) && animData.ambient.village_chimneys) {
        const chimneys = animData.ambient.village_chimneys;
        for (let ci = 0; ci < chimneys.length; ci++) {
          const c = chimneys[ci];
          const sx = offsetX + c.u * worldW * scale;
          const sy = offsetY + c.v * worldH * scale;
          if (sx < -48 || sx > canvas.width + 48 || sy < -48 || sy > canvas.height + 48) continue;
          const cxW = c.u * worldW;
          const cyW = c.v * worldH;
          const cPh = c.phase || 0;
          for (let p = 0; p < 4; p++) {
            const age = (((tSec * 0.22 + cPh + p / 4) % 1) + 1) % 1;
            const driftX = -age * 14 * wScale + Math.sin(age * 5.2 + p * 1.9 + cPh * 6.28) * 1.6 * wScale;
            const riseY = -(2 + age * 20) * wScale;
            const sz = 1.4 + age * 3.2;
            const alpha = (1 - age) * (age < 0.15 ? age / 0.15 : 1.0) * (isNight ? 0.36 : 0.44);
            const col = isNight
              ? `rgba(170,188,218,${alpha.toFixed(2)})`
              : `rgba(255,222,196,${alpha.toFixed(2)})`;
            drawPixelRectWorld(cxW + driftX - sz * 0.5 * wScale, cyW + riseY - sz * 0.4 * wScale, sz, sz * 0.72, col, wScale);
          }
        }
      }

      // 3 Sparkling Swiss Village Fountains / Dorfbrunnen (M3 ambient.fountains)
      if ((scale * wScale >= 0.30) && animData.ambient.fountains) {
        const fts = animData.ambient.fountains;
        const sPx = scale * wScale;
        ctx.save();
        for (let fi = 0; fi < fts.length; fi++) {
          const ft = fts[fi];
          const sx = offsetX + ft.u * worldW * scale;
          const sy = offsetY + ft.v * worldH * scale;
          if (sx < -32 || sx > canvas.width + 32 || sy < -32 || sy > canvas.height + 32) continue;
          const basinCol = isNight ? '#2d6488' : (isSunset ? '#5aaec4' : '#42b8d8');
          const jetCol = isNight ? '#93c5fd' : (isSunset ? '#ffe4c8' : '#e8fbff');
          const dropCol = isNight ? '#60a5fa' : '#7dd3fc';
          // Basin water surface shimmer
          ctx.fillStyle = basinCol;
          ctx.fillRect(Math.round(sx - 2.2 * sPx), Math.round(sy - 1.1 * sPx), Math.max(3, Math.round(4.5 * sPx)), Math.max(2, Math.round(2.4 * sPx)));
          // Expanding concentric water ripple
          const rPhase = (((tSec * 0.9 + fi * 0.37) % 1) + 1) % 1;
          const rRad = (1.2 + rPhase * 3.2) * sPx;
          ctx.strokeStyle = isNight ? `rgba(147,197,253,${((1 - rPhase) * 0.45).toFixed(2)})` : `rgba(232,251,255,${((1 - rPhase) * 0.65).toFixed(2)})`;
          ctx.lineWidth = Math.max(1.0, 0.9 * sPx);
          ctx.beginPath();
          ctx.ellipse(sx, sy, rRad, rRad * 0.56, 0, 0, Math.PI * 2);
          ctx.stroke();
          // Vertical sparkling pixel water jet + 3 dancing droplet pixels
          const jetH = (3.2 + 0.6 * Math.sin(tSec * 6.5 + fi * 2.1)) * sPx;
          ctx.fillStyle = jetCol;
          ctx.fillRect(Math.round(sx - 0.5 * sPx), Math.round(sy - jetH), Math.max(1, Math.round(1.1 * sPx)), Math.max(2, Math.round(jetH)));
          ctx.fillStyle = dropCol;
          for (let d = 0; d < 3; d++) {
            const dp = (((tSec * 2.4 + fi * 0.4 + d / 3) % 1) + 1) % 1;
            const dx = (d - 1) * (1.2 + dp * 1.4) * sPx;
            const dy = -jetH * (1 - dp * dp) - Math.sin(dp * Math.PI) * 1.4 * sPx;
            const dSz = Math.max(1, Math.round(1.0 * sPx));
            ctx.fillRect(Math.round(sx + dx), Math.round(sy + dy), dSz, dSz);
          }
        }
        ctx.restore();
      }

      // Gliding Lake Zurich Gulls over Bendlikon Bay & Schooren (day & alpenglow, M3 uv + pixel radii schema!)
      if (!isNight && animData.ambient.gulls) {
        const gullCol = isSunset ? '#ffe6cf' : '#f4f6fa';
        const tipCol = isSunset ? '#b49284' : '#8a94a6';
        for (let gIdx = 0; gIdx < animData.ambient.gulls.length; gIdx++) {
          const g = animData.ambient.gulls[gIdx];
          const spd = g.spd != null ? g.spd : (g.speed != null ? g.speed : 0.4);
          const ph = g.ph != null ? g.ph : (g.phase != null ? g.phase : 0);
          const ang = tSec * spd + ph * Math.PI * 2;
          const baseU = Array.isArray(g.uv) ? g.uv[0] : (g.cx != null ? g.cx : 0.55);
          const baseV = Array.isArray(g.uv) ? g.uv[1] : (g.cy != null ? g.cy : 0.62);
          const rxPx = (g.rx > 1) ? g.rx * wScale : (g.rx || 0.004) * worldW;
          const ryPx = (g.ry > 1) ? g.ry * wScale : (g.ry || 0.004) * worldH;
          const gx = baseU * worldW + Math.cos(ang) * rxPx;
          const gy = baseV * worldH + Math.sin(ang) * ryPx;
          if (!Number.isFinite(gx) || !Number.isFinite(gy)) continue;
          livingFrameCounts.gulls++;
          const flap = Math.sin(tSec * 7.5 + gIdx * 1.9);
          const wy = (flap > 0.25 ? -1.4 : (flap < -0.25 ? 1.2 : 0)) * wScale;
          drawPixelRectWorld(gx - 3.0 * wScale, gy + wy, 1.5, 1.2, tipCol, wScale);
          drawPixelRectWorld(gx - 1.6 * wScale, gy + wy * 0.4, 1.8, 1.2, gullCol, wScale);
          drawPixelRectWorld(gx, gy, 1.6, 1.4, gullCol, wScale);
          drawPixelRectWorld(gx + 1.6 * wScale, gy + wy * 0.4, 1.8, 1.2, gullCol, wScale);
          drawPixelRectWorld(gx + 3.0 * wScale, gy + wy, 1.5, 1.2, tipCol, wScale);
        }
      }
    }

    // 5b. Kilchberg Living Details & Dynamic Swiss Atmosphere
    drawKilchbergDetails(worldW, worldH, wScale, tSec, isNight, isSunset);
    drawAtmosphereAndLife(worldW, worldH, wScale, tSec, isNight, isSunset);

    // (Spatial soundscape updates run on their own timer so they keep following the camera while Live is paused.)
  }

  // Deterministic pseudo-random helper for sparkling lake glints & fireflies
  function hash01(n) {
    const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
    return s - Math.floor(s);
  }

  // Precomputed park/meadow anchors for nighttime fireflies (real Kilchberg parks & lake meadows)
  const FIREFLY_GROVES = [
    [0.24, 0.42], [0.27, 0.34], [0.33, 0.48], [0.39, 0.65],
    [0.44, 0.63], [0.51, 0.56], [0.56, 0.53], [0.64, 0.49],
    [0.71, 0.43], [0.77, 0.37], [0.47, 0.41], [0.35, 0.32],
  ];

  // Crisp 90s pixel-grid miniature villager/visitor/commuter sprite (routes through vCtx for depth masking!)
  function drawMiniPerson(sx, sy, s, coatCol, pantsCol, hairCol, isNight, stridePhase, bagCol = null) {
    const p = Math.max(0.75, s);
    const pad = 16 * p;
    if (sx < -pad || sx > canvas.width + pad || sy < -pad || sy > canvas.height + pad) return;
    const rx = Math.round(sx);
    const ry = Math.round(sy);
    const step = Math.round(Math.sin(stridePhase) * 0.85 * p);
    // Grounded shadow
    vCtx.fillStyle = isNight ? 'rgba(6,10,20,0.48)' : 'rgba(18,24,32,0.30)';
    vCtx.fillRect(rx - Math.round(1.4 * p), ry, Math.max(2, Math.round(3.0 * p)), Math.max(1, Math.round(1.1 * p)));
    // Striding legs
    vCtx.fillStyle = pantsCol;
    vCtx.fillRect(rx - Math.round(0.8 * p) + step, ry - Math.round(2.2 * p), Math.max(1, Math.round(0.95 * p)), Math.max(1, Math.round(2.2 * p)));
    vCtx.fillRect(rx + Math.round(0.1 * p) - step, ry - Math.round(2.2 * p), Math.max(1, Math.round(0.95 * p)), Math.max(1, Math.round(2.2 * p)));
    // Jacket torso
    vCtx.fillStyle = coatCol;
    vCtx.fillRect(rx - Math.round(1.0 * p), ry - Math.round(4.6 * p), Math.max(2, Math.round(2.1 * p)), Math.max(2, Math.round(2.5 * p)));
    // Optional Lindt golden-red shopping bag or commuter briefcase!
    if (bagCol) {
      vCtx.fillStyle = bagCol;
      vCtx.fillRect(rx + Math.round(1.0 * p), ry - Math.round(3.2 * p), Math.max(1, Math.round(1.1 * p)), Math.max(1, Math.round(1.5 * p)));
    }
    // Face + hair crown
    vCtx.fillStyle = isNight ? '#a88c72' : '#ecc29c';
    vCtx.fillRect(rx - Math.round(0.7 * p), ry - Math.round(5.9 * p), Math.max(1, Math.round(1.4 * p)), Math.max(1, Math.round(1.3 * p)));
    vCtx.fillStyle = hairCol;
    vCtx.fillRect(rx - Math.round(0.75 * p), ry - Math.round(6.4 * p), Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(0.75 * p)));
  }

  function drawKilchbergDetails(worldW, worldH, wScale, tSec, isNight, isSunset) {
    const s = scale * wScale;
    const toX = (u) => u * worldW * scale + offsetX;
    const toY = (v) => v * worldH * scale + offsetY;
    const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
    // Zoom-invariant world-space UV viewport bounds (NEVER culls pier/landmark pedestrians at ANY zoom level!)
    const padU = Math.max(0.004, 48 / Math.max(1, worldW * scale));
    const padV = Math.max(0.008, 48 / Math.max(1, worldH * scale));
    const visU0 = (-offsetX / Math.max(1, worldW * scale)) - padU;
    const visU1 = ((canvas.width - offsetX) / Math.max(1, worldW * scale)) + padU;
    const visV0 = (-offsetY / Math.max(1, worldH * scale)) - padV;
    const visV1 = ((canvas.height - offsetY) / Math.max(1, worldH * scale)) + padV;
    const boxInView = (u0, v0, u1, v1) => u1 >= visU0 && u0 <= visU1 && v1 >= visV0 && v0 <= visV1;
    const inView = (x, y, padWorld = 60) => {
      const pad = Math.max(60, padWorld * s);
      return x >= -pad && x <= canvas.width + pad && y >= -pad && y <= canvas.height + pad;
    };
    const coats = ['#d9382e', '#2563eb', '#0d9488', '#d97706', '#7c3aed', '#e11d48', '#334155', '#16a34a'];
    const hairs = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
    const walkerBounds = { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };

    ctx.save();

    // =========================================================================
    // 1. REFORMIERTE KIRCHE KILCHBERG — Live Real-Time Swiss Tower Clock + Circling Swifts!
    // =========================================================================
    const rkClock = (vig.reformierte_kirche && vig.reformierte_kirche.clock) || [0.29037, 0.31779];
    const rkSpire = (vig.reformierte_kirche && vig.reformierte_kirche.spire) || [0.29037, 0.30554];
    if (boxInView(rkClock[0] - 0.006, rkSpire[1] - 0.008, rkClock[0] + 0.006, rkClock[1] + 0.007)) {
      const cx = toX(rkClock[0]);
      const cy = toY(rkClock[1]);
      // Real Zurich local time (falls back smoothly when ?t= fixed time is used for deterministic captures)
      let hr, min, sec;
      if (fixedAnimTime !== null) {
        hr = 14; min = 20 + Math.floor(fixedAnimTime / 60); sec = fixedAnimTime % 60;
      } else {
        const now = new Date();
        const zh = new Date(now.toLocaleString('en-US', { timeZone: 'Europe/Zurich' }));
        hr = zh.getHours(); min = zh.getMinutes(); sec = zh.getSeconds();
      }
      const rDial = 6.2 * s;
      if (rDial >= 2.2) {
        ctx.fillStyle = isNight ? '#1c2a42' : '#162030';
        ctx.beginPath();
        ctx.arc(cx, cy, rDial, 0, Math.PI * 2);
        ctx.fill();
        if (isNight) {
          ctx.strokeStyle = 'rgba(255,220,120,0.45)';
          ctx.lineWidth = Math.max(1.0, 1.1 * s);
          ctx.stroke();
        }
        const minAng = ((min + sec / 60) / 60) * Math.PI * 2 - Math.PI * 0.5;
        const hrAng = (((hr % 12) + min / 60) / 12) * Math.PI * 2 - Math.PI * 0.5;
        ctx.strokeStyle = isNight ? '#ffe38a' : '#f4cf58';
        ctx.lineCap = 'round';
        ctx.lineWidth = Math.max(1.2, 1.5 * s);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(hrAng) * rDial * 0.56, cy + Math.sin(hrAng) * rDial * 0.56);
        ctx.stroke();
        ctx.lineWidth = Math.max(1.0, 1.15 * s);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(minAng) * rDial * 0.84, cy + Math.sin(minAng) * rDial * 0.84);
        ctx.stroke();
        ctx.fillStyle = '#fff5cc';
        ctx.fillRect(Math.round(cx - 0.7 * s), Math.round(cy - 0.7 * s), Math.max(1.5, Math.round(1.4 * s)), Math.max(1.5, Math.round(1.4 * s)));
      }

      // 4 graceful dark swifts orbiting the Reformierte Kirche steeple (Midday & Alpenglow!)
      if (!isNight) {
        const spX = toX(rkSpire[0]);
        const spY = toY(rkSpire[1]);
        ctx.fillStyle = isSunset ? '#2e2230' : '#26303d';
        for (let b = 0; b < 4; b++) {
          const ang = tSec * (0.95 + b * 0.13) + b * 1.62;
          const bx = spX + Math.cos(ang) * (16 + b * 5) * s;
          const by = spY + Math.sin(ang) * (7 + b * 2.2) * s;
          const fl = Math.sin(tSec * 12.0 + b * 2.3) > 0 ? -1 : 1;
          const px = Math.max(1, Math.round(1.1 * s));
          ctx.fillRect(Math.round(bx - px * 2), Math.round(by + fl * px * 0.6), px * 2, px);
          ctx.fillRect(Math.round(bx), Math.round(by), px, px);
          ctx.fillRect(Math.round(bx + px), Math.round(by + fl * px * 0.6), px * 2, px);
        }
      }
    }

    // =========================================================================
    // 2. LINDT HOME OF CHOCOLATE — 9m Golden Chocolate Fountain Atrium Shimmer + Depth-Masked Plaza Walkers!
    // =========================================================================
    const lindtAtrium = (vig.lindt_hoc && vig.lindt_hoc.atrium) || [0.37821, 0.64638];
    const lindtPlaza = (vig.lindt_hoc && vig.lindt_hoc.plaza) || [0.37800, 0.65101];
    if (boxInView(lindtAtrium[0] - 0.007, lindtAtrium[1] - 0.005, lindtAtrium[0] + 0.007, lindtPlaza[1] + 0.008)) {
      const shimmer = 0.76 + 0.24 * Math.sin(tSec * 3.4);
      const arcOffsets = [
        [-0.0018, 0.0004], [-0.0007, -0.0001], [0.0004, -0.0002], [0.0016, 0.0000],
      ];
      for (let i = 0; i < arcOffsets.length; i++) {
        const ax = toX(lindtAtrium[0] + arcOffsets[i][0]);
        const ay = toY(lindtAtrium[1] + arcOffsets[i][1]);
        const pGlow = 0.75 + 0.25 * Math.sin(tSec * 4.2 + i * 1.3);
        const rw = Math.max(3, 5.2 * s);
        const rh = Math.max(2, 3.6 * s);
        ctx.fillStyle = isNight
          ? `rgba(255, 206, 94, ${(0.76 * pGlow).toFixed(2)})`
          : (isSunset ? `rgba(255, 204, 102, ${(0.54 * pGlow).toFixed(2)})` : `rgba(255, 214, 118, ${(0.38 * pGlow).toFixed(2)})`);
        ctx.fillRect(Math.round(ax - rw * 0.5), Math.round(ay - rh * 0.5), Math.round(rw), Math.round(rh));
      }

      // 9-meter Golden Chocolate Fountain vertical shimmer visible inside the glass atrium!
      const fx = toX(lindtAtrium[0]);
      const fy = toY(lindtAtrium[1]);
      const colW = Math.max(2, 2.8 * s);
      const colH = Math.max(4, 7.5 * s);
      const fAlpha = isNight ? (0.86 * shimmer) : (isSunset ? (0.70 * shimmer) : 0.38);
      ctx.fillStyle = `rgba(245, 168, 24, ${(fAlpha * 0.85).toFixed(2)})`;
      ctx.fillRect(Math.round(fx - colW * 0.5), Math.round(fy - colH * 0.6), Math.round(colW), Math.round(colH));
      // 3 downward-flowing liquid-gold shimmer highlights inside the fountain column
      for (let k = 0; k < 3; k++) {
        const prog = (((tSec * 1.4 + k / 3) % 1) + 1) % 1;
        const yOff = (prog - 0.55) * 6.5 * s;
        ctx.fillStyle = `rgba(255, 242, 178, ${(fAlpha * (1.0 - Math.abs(prog - 0.5))).toFixed(2)})`;
        ctx.fillRect(Math.round(fx - colW * 0.32), Math.round(fy + yOff), Math.max(1.5, Math.round(colW * 0.65)), Math.max(1.5, Math.round(1.5 * s)));
      }

      if (isNight || isSunset) {
        const gRad = 28 * s;
        const grad = ctx.createRadialGradient(fx, toY(lindtAtrium[1] + 0.0008), 2 * s, fx, toY(lindtAtrium[1] + 0.0034), gRad);
        grad.addColorStop(0, isNight ? `rgba(255, 206, 98, ${(0.38 * shimmer).toFixed(2)})` : `rgba(255, 200, 106, ${(0.24 * shimmer).toFixed(2)})`);
        grad.addColorStop(1, 'rgba(255, 198, 104, 0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.ellipse(fx, toY(lindtAtrium[1] + 0.0034), gRad * 1.28, gRad * 0.74, -0.15, 0, Math.PI * 2);
        ctx.fill();
      }

      // Plaza visitors anchored to M3 lindt_hoc.plaza & depth-masked cleanly behind foreground geometry
      const plazaOffsets = [
        { du0: -0.0022, dv0: 0.0000, du1: 0.0020, dv1: -0.0014, spd: 0.08, ph: 0.1, bag: '#e5b93c' },
        { du0: 0.0022, dv0: 0.0014, du1: -0.0016, dv1: -0.0006, spd: 0.07, ph: 0.45, bag: '#d62c28' },
        { du0: -0.0010, dv0: 0.0024, du1: 0.0014, dv1: -0.0024, spd: 0.06, ph: 0.72, bag: '#e5b93c' },
        { du0: -0.0018, dv0: -0.0016, du1: 0.0010, dv1: 0.0018, spd: 0.055, ph: 0.25, bag: null },
        { du0: 0.0012, dv0: -0.0022, du1: -0.0008, dv1: 0.0010, spd: 0.065, ph: 0.88, bag: '#e5b93c' },
        { du0: -0.0004, dv0: -0.0015, du1: 0.0000, dv1: -0.0010, spd: 0.03, ph: 0.3, bag: '#d62c28' },
        { du0: 0.0003, dv0: -0.0012, du1: 0.0007, dv1: -0.0007, spd: 0.03, ph: 0.6, bag: null },
      ];
      const nVis = isNight ? 2 : (isSunset ? 5 : plazaOffsets.length);
      for (let i = 0; i < nVis; i++) {
        const w = plazaOffsets[i];
        const p = 0.5 + 0.5 * Math.sin(tSec * w.spd * Math.PI * 2 + w.ph * Math.PI * 2);
        const wu = lindtPlaza[0] + w.du0 + (w.du1 - w.du0) * p;
        const wv = lindtPlaza[1] + w.dv0 + (w.dv1 - w.dv0) * p;
        const wx = wu * worldW;
        const wy = wv * worldH;
        const coat = shadeHex(coats[i % coats.length], 1.0, currentMode);
        const pants = shadeHex('#263040', 1.0, currentMode);
        const d16 = evalWalkerD16(wx, wy, 413.9, worldW, worldH, false);
        drawDepthMasked(wx, wy, walkerBounds, d16, worldW, worldH, () => {
          drawMiniPerson(toX(wu), toY(wv), s, coat, pants, hairs[i % hairs.length], isNight, tSec * 7.5 + i * 1.9, w.bag);
        }, 2.0);
      }
    }

    // =========================================================================
    // 3. TC KILCHBERG CLAY TENNIS COURTS — 3 Live Animated Matches on Exact 3D Courts!
    // =========================================================================
    const tcSrc = Array.isArray(vig.tc_kilchberg) && vig.tc_kilchberg.length >= 3
      ? vig.tc_kilchberg
      : [
        { sw: [0.17388, 0.34389], ne: [0.17966, 0.33951], lat: [0.00074, 0.00125] },
        { sw: [0.17697, 0.34873], ne: [0.18262, 0.34423], lat: [0.00076, 0.00123] },
        { sw: [0.16390, 0.35396], ne: [0.16970, 0.34942], lat: [0.00076, 0.00124] },
      ];
    if (!isNight && boxInView(0.156, 0.334, 0.188, 0.362)) {
      const tcMeta = [{ ph: 0.0, freq: 1.55 }, { ph: 1.3, freq: 1.42 }, { ph: 2.1, freq: 1.36 }];
      for (let ci = 0; ci < tcSrc.length; ci++) {
        const c = tcSrc[ci];
        const m = tcMeta[ci % tcMeta.length];
        if (!boxInView(c.sw[0] - 0.003, c.ne[1] - 0.004, c.ne[0] + 0.003, c.sw[1] + 0.004)) continue;

        const cyc = (((tSec * m.freq + m.ph) % 2.0) + 2.0) % 2.0;
        const ballF = cyc < 1.0 ? cyc : (2.0 - cyc);
        const latA = Math.sin(tSec * 0.78 + ci * 2.4) * 0.68;
        const latB = Math.cos(tSec * 0.85 + ci * 1.7) * 0.68;
        const ballLat = latA * (1 - ballF) + latB * ballF;

        const pAx = toX(c.sw[0] + c.lat[0] * latA);
        const pAy = toY(c.sw[1] + c.lat[1] * latA);
        const pBx = toX(c.ne[0] + c.lat[0] * latB);
        const pBy = toY(c.ne[1] + c.lat[1] * latB);
        const whiteKit = isSunset ? '#ffe8d4' : '#f4f7fa';
        const shortCol = ci === 0 ? '#1e3a5f' : (ci === 1 ? '#991b1b' : '#166534');
        drawMiniPerson(pBx, pBy, s * 0.90, whiteKit, shortCol, hairs[ci % hairs.length], false, tSec * 10.0 + 1.0);
        drawMiniPerson(pAx, pAy, s * 0.90, whiteKit, '#1e3a5f', hairs[(ci + 2) % hairs.length], false, tSec * 10.0);

        const bu = c.sw[0] + (c.ne[0] - c.sw[0]) * ballF + c.lat[0] * ballLat;
        const bv = c.sw[1] + (c.ne[1] - c.sw[1]) * ballF + c.lat[1] * ballLat;
        const arcH = Math.sin(ballF * Math.PI) * 8.5 * s;
        const bx = toX(bu);
        const by = toY(bv);
        const bSz = Math.max(1.6, 1.8 * s);
        ctx.fillStyle = 'rgba(28, 18, 12, 0.35)';
        ctx.fillRect(Math.round(bx - bSz * 0.4), Math.round(by), Math.max(1.5, Math.round(bSz * 0.8)), Math.max(1, Math.round(bSz * 0.6)));
        ctx.fillStyle = '#d9ff3b';
        ctx.fillRect(Math.round(bx - bSz * 0.5), Math.round(by - arcH - bSz * 0.5), Math.max(2, Math.round(bSz)), Math.max(2, Math.round(bSz)));
      }
    }

    // =========================================================================
    // 3b. SPORTPLATZ HOCHWEID — Live FC Kilchberg Football Match & Night Floodlights!
    // =========================================================================
    const spVig = vig.sportplatz_hochweid || {
      center: [0.31377, 0.22953], half_l: [0.01364, -0.00936], half_w: [0.00506, 0.00945],
    };
    const fCU = spVig.center[0], fCV = spVig.center[1];
    if (boxInView(fCU - 0.022, fCV - 0.022, fCU + 0.022, fCV + 0.022)) {
      const fLenU = spVig.half_l[0], fLenV = spVig.half_l[1];
      const fLatU = spVig.half_w[0], fLatV = spVig.half_w[1];
      const fieldUV = (lu, lv) => ({
        u: fCU + lu * fLenU + lv * fLatU,
        v: fCV + lu * fLenV + lv * fLatV,
      });

      if (isNight) {
        const masts = [[-0.58, -1.04], [0.58, -1.04], [-0.58, 1.04], [0.58, 1.04]];
        for (let mi = 0; mi < masts.length; mi++) {
          const p = fieldUV(masts[mi][0], masts[mi][1]);
          const gx = toX(p.u);
          const gy = toY(p.v);
          const rad = 52 * s;
          const grad = ctx.createRadialGradient(gx, gy, 2 * s, gx, gy, rad);
          grad.addColorStop(0, 'rgba(255, 240, 195, 0.26)');
          grad.addColorStop(0.55, 'rgba(255, 224, 155, 0.10)');
          grad.addColorStop(1, 'rgba(255, 210, 120, 0)');
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.ellipse(gx, gy, rad * 1.15, rad * 0.68, -0.32, 0, Math.PI * 2);
          ctx.fill();
        }
      } else {
        const ballAng = tSec * 0.42;
        const ballLU = Math.sin(ballAng) * 0.64 + Math.sin(ballAng * 2.3) * 0.16;
        const ballLV = Math.cos(ballAng * 1.35) * 0.56;
        const blueKit = isSunset ? '#2e64b8' : '#2563eb';
        const redKit = isSunset ? '#c83434' : '#dc2626';
        const gkA = isSunset ? '#e6c238' : '#facc15';
        const gkB = isSunset ? '#58c448' : '#4ade80';

        const players = [
          { lu: -0.92, lv: Math.sin(tSec * 1.4) * 0.14, kit: gkA, shorts: '#1e293b', hi: 0 },
          { lu: 0.92, lv: Math.cos(tSec * 1.3) * 0.14, kit: gkB, shorts: '#1e293b', hi: 1 },
          { lu: -0.52 + ballLU * 0.35 + Math.sin(tSec * 0.9) * 0.08, lv: -0.34 + ballLV * 0.28, kit: blueKit, shorts: '#f8fafc', hi: 2 },
          { lu: -0.45 + ballLU * 0.38 + Math.cos(tSec * 1.1) * 0.09, lv: 0.32 + ballLV * 0.30, kit: blueKit, shorts: '#f8fafc', hi: 3 },
          { lu: ballLU * 0.88 - 0.06, lv: ballLV * 0.86 + Math.sin(tSec * 1.6) * 0.07, kit: blueKit, shorts: '#f8fafc', hi: 4 },
          { lu: 0.18 + ballLU * 0.45 + Math.sin(tSec * 1.2 + 1.0) * 0.11, lv: -0.28 + ballLV * 0.36, kit: blueKit, shorts: '#f8fafc', hi: 0 },
          { lu: 0.26 + ballLU * 0.44 + Math.cos(tSec * 1.0 + 2.0) * 0.10, lv: 0.36 + ballLV * 0.32, kit: blueKit, shorts: '#f8fafc', hi: 1 },
          { lu: 0.52 + ballLU * 0.34 + Math.cos(tSec * 0.95) * 0.08, lv: -0.30 + ballLV * 0.28, kit: redKit, shorts: '#f8fafc', hi: 2 },
          { lu: 0.46 + ballLU * 0.36 + Math.sin(tSec * 1.05) * 0.09, lv: 0.30 + ballLV * 0.30, kit: redKit, shorts: '#f8fafc', hi: 3 },
          { lu: ballLU * 0.86 + 0.07, lv: ballLV * 0.84 + Math.cos(tSec * 1.5) * 0.08, kit: redKit, shorts: '#f8fafc', hi: 4 },
          { lu: -0.18 + ballLU * 0.45 + Math.cos(tSec * 1.15 + 1.4) * 0.10, lv: -0.36 + ballLV * 0.34, kit: redKit, shorts: '#f8fafc', hi: 0 },
          { lu: -0.24 + ballLU * 0.42 + Math.sin(tSec * 1.25 + 2.6) * 0.10, lv: 0.28 + ballLV * 0.34, kit: redKit, shorts: '#f8fafc', hi: 1 },
        ];
        const drawList = players.map((pl, idx) => {
          const p = fieldUV(Math.max(-0.94, Math.min(0.94, pl.lu)), Math.max(-0.88, Math.min(0.88, pl.lv)));
          return { x: toX(p.u), y: toY(p.v), pl, idx };
        });
        drawList.sort((a, b) => a.y - b.y);
        for (let di = 0; di < drawList.length; di++) {
          const d = drawList[di];
          drawMiniPerson(d.x, d.y, s * 0.88, d.pl.kit, d.pl.shorts, hairs[d.pl.hi % hairs.length], false, tSec * 9.0 + d.idx * 1.3);
        }

        const bp = fieldUV(ballLU, ballLV);
        const fbx = toX(bp.u);
        const fby = toY(bp.v);
        const bounceH = Math.abs(Math.sin(tSec * 3.4)) * 5.2 * s;
        const fbSz = Math.max(1.8, 2.0 * s);
        ctx.fillStyle = 'rgba(20, 32, 18, 0.36)';
        ctx.fillRect(Math.round(fbx - fbSz * 0.4), Math.round(fby), Math.max(1.5, Math.round(fbSz * 0.9)), Math.max(1, Math.round(fbSz * 0.55)));
        ctx.fillStyle = '#f8fafc';
        ctx.fillRect(Math.round(fbx - fbSz * 0.5), Math.round(fby - bounceH - fbSz * 0.5), Math.max(2, Math.round(fbSz)), Math.max(2, Math.round(fbSz)));
      }
    }

    // =========================================================================
    // 4. SEEBAD KILCHBERG — Pool Swimmers, Pixel-Art Beach Umbrellas, Jetty Bathers & Lake Swimmers!
    // =========================================================================
    const seebadPool = (vig.seebad_kilchberg && vig.seebad_kilchberg.pool) || [0.40901, 0.70921];
    const seebadJetty = (vig.seebad_kilchberg && vig.seebad_kilchberg.jetty) || [[0.4126, 0.71361], [0.4216, 0.7232]];
    if (boxInView(seebadPool[0] - 0.010, seebadPool[1] - 0.012, seebadJetty[1][0] + 0.008, seebadJetty[1][1] + 0.010)) {
      const poolX = toX(seebadPool[0]);
      const poolY = toY(seebadPool[1]);
      if (isNight) {
        if (boxInView(seebadPool[0] - 0.005, seebadPool[1] - 0.006, seebadPool[0] + 0.006, seebadPool[1] + 0.007)) {
          const grad = ctx.createRadialGradient(poolX, poolY, 2 * s, poolX, poolY, 22 * s);
          grad.addColorStop(0, 'rgba(64, 228, 240, 0.34)');
          grad.addColorStop(1, 'rgba(32, 160, 200, 0)');
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.ellipse(poolX, poolY, 22 * s, 14 * s, -0.35, 0, Math.PI * 2);
          ctx.fill();
        }
      } else {
        if (boxInView(seebadPool[0] - 0.004, seebadPool[1] - 0.005, seebadPool[0] + 0.005, seebadPool[1] + 0.006)) {
          const swimCaps = ['#f43f5e', '#facc15', '#ffffff'];
          for (let sw = 0; sw < 3; sw++) {
            const prog = 0.5 + 0.5 * Math.sin(tSec * (0.28 + sw * 0.05) + sw * 2.1);
            const su = seebadPool[0] - 0.0019 + prog * 0.0028 + sw * 0.0005;
            const sv = seebadPool[1] - 0.0023 + (1 - prog) * 0.0018 + sw * 0.0013;
            const sx = toX(su);
            const sy = toY(sv);
            const px = Math.max(1.2, 1.3 * s);
            ctx.fillStyle = 'rgba(240, 252, 255, 0.78)';
            ctx.fillRect(Math.round(sx - px * 1.6), Math.round(sy), Math.max(2, Math.round(px * 3.2)), Math.max(1, Math.round(px * 0.85)));
            ctx.fillStyle = swimCaps[sw];
            ctx.fillRect(Math.round(sx - px * 0.5), Math.round(sy - px * 0.7), Math.max(2, Math.round(px * 1.2)), Math.max(2, Math.round(px * 1.1)));
          }
        }

        if (boxInView(0.401, 0.699, 0.409, 0.706)) {
          const umbrellas = [
            { u: 0.4036, v: 0.7018, c1: '#d9382e', c2: '#f4f6f8', dk: '#8f1d18' },
            { u: 0.4052, v: 0.7010, c1: '#2563eb', c2: '#f4f6f8', dk: '#1a3f94' },
            { u: 0.4063, v: 0.7024, c1: '#eab308', c2: '#fef3c7', dk: '#a16207' },
          ];
          for (const um of umbrellas) {
            const ux = Math.round(toX(um.u));
            const uy = Math.round(toY(um.v));
            const p = Math.max(1.0, s);
            const w = (n) => Math.max(1, Math.round(n * p));
            ctx.fillStyle = 'rgba(16, 28, 22, 0.34)';
            ctx.fillRect(ux - w(2), uy + w(1), w(7), w(2));
            ctx.fillStyle = '#5c4028';
            ctx.fillRect(ux, uy - w(2), w(1), w(3));
            ctx.fillStyle = 'rgba(22, 26, 32, 0.82)';
            ctx.fillRect(ux - w(4), uy - w(4), w(9), w(3));
            ctx.fillRect(ux - w(3), uy - w(5), w(7), w(5));
            ctx.fillStyle = shadeHex(um.dk, 1.0, currentMode);
            ctx.fillRect(ux - w(3), uy - w(2), w(7), w(1.2));
            ctx.fillStyle = shadeHex(um.c1, 1.04, currentMode);
            ctx.fillRect(ux - w(3), uy - w(4), w(7), w(2.2));
            ctx.fillStyle = shadeHex(um.c2, 1.04, currentMode);
            ctx.fillRect(ux - w(1), uy - w(4.5), w(3), w(3.2));
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(ux, uy - w(4.5), w(1), w(1));
          }
        }

        if (boxInView(seebadJetty[0][0] - 0.003, seebadJetty[0][1] - 0.003, seebadJetty[1][0] + 0.004, seebadJetty[1][1] + 0.004)) {
          for (let jb = 0; jb < 4; jb++) {
            const f = 0.14 + 0.76 * (0.5 + 0.5 * Math.sin(tSec * (0.11 + jb * 0.03) + jb * 1.7));
            const ju = seebadJetty[0][0] + (seebadJetty[1][0] - seebadJetty[0][0]) * f;
            const jv = seebadJetty[0][1] + (seebadJetty[1][1] - seebadJetty[0][1]) * f;
            drawMiniPerson(toX(ju), toY(jv), s * 0.92, shadeHex(coats[(jb + 2) % coats.length], 1.0, currentMode), '#2b4c7e', hairs[jb], false, tSec * 6.5 + jb);
          }
        }
        if (boxInView(0.421, 0.721, 0.432, 0.734)) {
          for (let ls = 0; ls < 2; ls++) {
            const ang = tSec * (0.32 + ls * 0.08) + ls * 3.1;
            // Orbit centre verified to keep 360/360 orbit samples inside the eroded waterMask (clear of the jetty)
            const lsu = 0.4275 + Math.cos(ang) * 0.0022;
            const lsv = 0.7272 + Math.sin(ang) * 0.0024;
            if (!isWaterUV(lsu, lsv)) continue;
            const lx = toX(lsu);
            const ly = toY(lsv);
            const px = Math.max(1.2, 1.3 * s);
            ctx.fillStyle = 'rgba(232, 248, 255, 0.68)';
            ctx.fillRect(Math.round(lx - px * 1.8), Math.round(ly), Math.max(2, Math.round(px * 3.6)), Math.max(1, Math.round(px * 0.85)));
            ctx.fillStyle = ls === 0 ? '#fb7185' : '#38bdf8';
            ctx.fillRect(Math.round(lx - px * 0.5), Math.round(ly - px * 0.6), Math.max(2, Math.round(px * 1.2)), Math.max(2, Math.round(px * 1.1)));
          }
        }
      }
    }

    // =========================================================================
    // 5. BENDLIKON ZSG STEAMER PIER (Badweg 1.1) — Gangplank Boarding, Moored Sailboats, Swans, Ducks & SUPs!
    // =========================================================================
    {
      const bpPax = (vig.bendlikon_pier && vig.bendlikon_pier.pax) || [0.58359, 0.57841];
      if (boxInView(bpPax[0] - 0.006, bpPax[1] - 0.006, bpPax[0] + 0.007, bpPax[1] + 0.009)) {
        let shipNear = false;
        let shipDocked = false;
        let dwellProg = 0;
        for (const sh of (animData.ships || [])) {
          if (sh.kind === 'zsg_steamer') {
            const st = evalWithStationStop(tSec, sh.length_m, sh.speed_mps, sh.stop_frac, sh.dwell_sec, sh.phase || 0, 5.0, 6.0);
            if (st.isDwelling) {
              shipDocked = true;
              shipNear = true;
              dwellProg = st.dwellProgress;
            } else if (st.frac >= 0 && Math.abs(st.frac - sh.stop_frac) < 0.04) {
              shipNear = true;
            }
          }
        }

        // Animated wooden gangplank bridging Badweg 1.1 pier edge to MS Helvetia during docking dwell!
        let gpExt = 0;
        if (shipDocked) {
          gpExt = dwellProg < 0.15 ? (dwellProg / 0.15) : (dwellProg > 0.85 ? (1.0 - dwellProg) / 0.15 : 1.0);
          const gpU0 = 0.5846, gpV0 = 0.5805;
          const gpU1 = gpU0 + (0.5856 - gpU0) * gpExt;
          const gpV1 = gpV0 + (0.5844 - gpV0) * gpExt;
          const x0 = toX(gpU0), y0 = toY(gpV0);
          const x1 = toX(gpU1), y1 = toY(gpV1);
          // Wooden deck plank
          ctx.strokeStyle = isNight ? '#5c4228' : '#8c6239';
          ctx.lineWidth = Math.max(2.2, 3.2 * s);
          ctx.lineCap = 'butt';
          ctx.beginPath();
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y1);
          ctx.stroke();
          // Crisp silver-white safety handrails on both sides
          ctx.strokeStyle = isNight ? '#94a3b8' : '#dce2ea';
          ctx.lineWidth = Math.max(0.8, 0.9 * s);
          for (const hOff of [-1.4 * s, 1.4 * s]) {
            ctx.beginPath();
            ctx.moveTo(x0 + hOff, y0 - 1.5 * s);
            ctx.lineTo(x1 + hOff, y1 - 1.5 * s);
            ctx.stroke();
          }
        }

        const pCount = isNight ? 2 : 5;
        for (let i = 0; i < pCount; i++) {
          let pu;
          let pv;
          let stride = shipNear ? tSec * 7.5 + i : tSec * 1.2 + i;
          // Animate 2 passengers walking across the deployed gangplank to board MS Helvetia!
          if (shipDocked && i < 2 && dwellProg >= 0.18 && dwellProg <= 0.82) {
            const bProg = Math.min(1.0, Math.max(0.0, (dwellProg - 0.18 - i * 0.12) / 0.42));
            pu = 0.5844 + (0.5855 - 0.5844) * bProg;
            pv = 0.5801 + (0.5841 - 0.5801) * bProg;
            stride = tSec * 9.0 + i * 1.5;
          } else {
            const shift = shipNear ? 0.0004 : 0;
            pu = bpPax[0] - 0.00175 + i * 0.00088 + Math.sin(tSec * 0.4 + i * 1.7) * 0.00022 + shift;
            pv = bpPax[1] + 0.00082 - i * 0.00042 + Math.cos(tSec * 0.35 + i * 2.1) * 0.00016 + shift;
          }
          const wx = pu * worldW;
          const wy = pv * worldH;
          const d16 = evalWalkerD16(wx, wy, 407.2, worldW, worldH, true);
          drawDepthMasked(wx, wy, walkerBounds, d16, worldW, worldH, () => {
            drawMiniPerson(
              toX(pu), toY(pv), s * 0.96,
              shadeHex(coats[(i + 1) % coats.length], 1.0, currentMode),
              shadeHex('#243040', 1.0, currentMode),
              hairs[i % hairs.length],
              isNight,
              stride,
              i === 1 ? '#b45309' : null,
            );
          }, 2.0);
        }
      }

      // 5 Verified Open-Water Moored Sailboats with Gentle Bobbing, Swaying Masts & Night Anchor Lights!
      const mooredBoats = [
        { u: 0.5758, v: 0.5835, pen: '#d9382e' }, // Bendlikon SW
        { u: 0.5935, v: 0.5675, pen: '#2563eb' }, // Bendlikon NE
        { u: 0.4435, v: 0.6995, pen: '#d9382e' }, // Schooren NE
        { u: 0.4145, v: 0.7315, pen: '#2563eb' }, // Schooren SW 1
        { u: 0.4045, v: 0.7395, pen: '#eab308' }, // Schooren SW 2
      ];
      for (let idx = 0; idx < mooredBoats.length; idx++) {
        const mb = mooredBoats[idx];
        if (!isWaterUV(mb.u, mb.v)) continue;
        const bx = toX(mb.u);
        const by = toY(mb.v);
        if (!inView(bx, by, 32)) continue;
        const bobPx = Math.sin(tSec * (2.1 + idx * 0.23) + idx * 1.7) * 0.75 * s;
        const swayPx = Math.sin(tSec * (1.7 + idx * 0.19) + idx * 2.3) * 1.15 * s;
        const p = Math.max(0.85, s);
        const hy = by + bobPx;

        // Subtle water ripple oval underneath moored hull
        ctx.strokeStyle = isNight ? 'rgba(130, 175, 224, 0.26)' : 'rgba(226, 246, 255, 0.42)';
        ctx.lineWidth = Math.max(0.8, 0.9 * p);
        ctx.beginPath();
        ctx.ellipse(bx, by + 1.8 * p, 6.4 * p, 2.3 * p, -0.15, 0, Math.PI * 2);
        ctx.stroke();

        // Crisp pixel-grid white sailboat hull + dark cockpit recess
        ctx.fillStyle = shadeHex('#2c3a48', 0.9, currentMode);
        ctx.fillRect(Math.round(bx - 5.4 * p), Math.round(hy - 0.8 * p), Math.max(4, Math.round(10.8 * p)), Math.max(2, Math.round(3.6 * p)));
        ctx.fillStyle = shadeHex('#eef2f6', 1.04, currentMode);
        ctx.fillRect(Math.round(bx - 5.0 * p), Math.round(hy - 1.4 * p), Math.max(4, Math.round(10.0 * p)), Math.max(2, Math.round(3.0 * p)));
        ctx.fillStyle = shadeHex('#26384c', 0.95, currentMode);
        ctx.fillRect(Math.round(bx - 2.4 * p), Math.round(hy - 0.8 * p), Math.max(2, Math.round(4.4 * p)), Math.max(1.5, Math.round(1.6 * p)));

        // Tall swaying silver mast + tiny fluttering pennant
        const mastTopX = bx + swayPx;
        const mastTopY = hy - 18.0 * p;
        ctx.strokeStyle = shadeHex('#cbd5e1', 1.0, currentMode);
        ctx.lineWidth = Math.max(1.0, 1.05 * p);
        ctx.beginPath();
        ctx.moveTo(bx, hy - 1.2 * p);
        ctx.lineTo(mastTopX, mastTopY);
        ctx.stroke();
        // Furled boom
        ctx.strokeStyle = shadeHex('#f8fafc', 1.0, currentMode);
        ctx.lineWidth = Math.max(1.0, 1.2 * p);
        ctx.beginPath();
        ctx.moveTo(bx + swayPx * 0.25, hy - 5.0 * p);
        ctx.lineTo(bx - 4.8 * p + swayPx * 0.25, hy - 4.2 * p);
        ctx.stroke();
        // Tiny fluttering masthead pennant
        const flutter = Math.sin(tSec * 6.0 + idx * 1.9) * 0.9 * p;
        ctx.fillStyle = shadeHex(mb.pen, 1.05, currentMode);
        ctx.fillRect(Math.round(mastTopX), Math.round(mastTopY + flutter * 0.4), Math.max(2, Math.round(3.2 * p)), Math.max(1, Math.round(1.2 * p)));

        // Warm masthead anchor light + water reflection dot at night!
        if (isNight) {
          const aSz = Math.max(1.5, 1.6 * p);
          ctx.fillStyle = 'rgba(255, 232, 163, 0.32)';
          ctx.beginPath();
          ctx.arc(mastTopX, mastTopY, Math.max(2.2, 2.8 * p), 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#ffe8a3';
          ctx.fillRect(Math.round(mastTopX - aSz * 0.5), Math.round(mastTopY - aSz * 0.5), Math.round(aSz), Math.round(aSz));
          ctx.fillStyle = 'rgba(255, 224, 140, 0.36)';
          ctx.fillRect(Math.round(bx + swayPx * 0.3 - aSz * 0.5), Math.round(by + 4.0 * p), Math.round(aSz), Math.max(1, Math.round(1.0 * p)));
        }
      }

      // 5 Graceful White Lake Zurich Mute Swans (100% waterMask-verified open-water coordinates!)
      const swanLoops = [
        { cu: 0.5960, cv: 0.5915, ru: 0.0042, rv: 0.0036, spd: 0.14, ph: 0.0  },
        { cu: 0.6005, cv: 0.5955, ru: 0.0038, rv: 0.0033, spd: 0.14, ph: 0.35 },
        { cu: 0.4400, cv: 0.7285, ru: 0.0036, rv: 0.0032, spd: 0.16, ph: 1.4  },
        { cu: 0.4440, cv: 0.7315, ru: 0.0034, rv: 0.0030, spd: 0.16, ph: 1.85 },
        { cu: 0.6960, cv: 0.5370, ru: 0.0040, rv: 0.0034, spd: 0.13, ph: 3.1  },
      ];
      for (const sw of swanLoops) {
        const ang = tSec * sw.spd + sw.ph;
        const su = sw.cu + Math.cos(ang) * sw.ru;
        const sv = sw.cv + Math.sin(ang) * sw.rv;
        if (!isWaterUV(su, sv)) continue;
        livingFrameCounts.swans++;
        const sx = toX(su);
        const sy = toY(sv);
        if (!inView(sx, sy, 24)) continue;
        const dir = -Math.sin(ang) >= 0 ? 1 : -1;
        const px = Math.max(1.0, 1.15 * s);
        ctx.fillStyle = isNight ? 'rgba(130,170,210,0.28)' : 'rgba(234,248,255,0.48)';
        ctx.fillRect(Math.round(sx - dir * 3.0 * px), Math.round(sy + 0.4 * px), Math.max(2, Math.round(2.6 * px)), Math.max(1, Math.round(0.9 * px)));
        ctx.fillStyle = isNight ? '#b8c8dc' : (isSunset ? '#fff0de' : '#ffffff');
        ctx.fillRect(Math.round(sx - 1.6 * px), Math.round(sy - 0.6 * px), Math.max(2, Math.round(3.2 * px)), Math.max(1.5, Math.round(1.6 * px)));
        ctx.fillRect(Math.round(sx + dir * 1.1 * px), Math.round(sy - 2.2 * px), Math.max(1, Math.round(1.1 * px)), Math.max(2, Math.round(2.0 * px)));
        ctx.fillStyle = '#f97316';
        ctx.fillRect(Math.round(sx + dir * 2.0 * px), Math.round(sy - 1.9 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.7 * px)));
      }

      // 3 Lakeside Mallard Duck Pairs (Drake + Hen, day & sunset, 100% waterMask-verified!)
      if (!isNight) {
        const duckPairs = [
          { cu: 0.5160, cv: 0.6540, ru: 0.0028, rv: 0.0024, spd: 0.18, ph: 0.4 },
          { cu: 0.6380, cv: 0.5650, ru: 0.0026, rv: 0.0022, spd: 0.16, ph: 2.2 },
          { cu: 0.7700, cv: 0.4700, ru: 0.0030, rv: 0.0025, spd: 0.15, ph: 4.1 },
        ];
        for (const dp of duckPairs) {
          for (let mate = 0; mate < 2; mate++) {
            const ang = tSec * dp.spd + dp.ph - mate * 0.28;
            const du = dp.cu + Math.cos(ang) * dp.ru;
            const dv = dp.cv + Math.sin(ang) * dp.rv;
            if (!isWaterUV(du, dv)) continue;
            livingFrameCounts.ducks++;
            const dx = toX(du);
            const dy = toY(dv);
            if (!inView(dx, dy, 18)) continue;
            const dir = -Math.sin(ang) >= 0 ? 1 : -1;
            const px = Math.max(0.9, 1.0 * s);
            // Tiny water ripple behind duck
            ctx.fillStyle = 'rgba(232, 248, 255, 0.42)';
            ctx.fillRect(Math.round(dx - dir * 2.2 * px), Math.round(dy + 0.3 * px), Math.max(1.5, Math.round(2.0 * px)), Math.max(1, Math.round(0.7 * px)));
            if (mate === 0) {
              // Leading drake: grey-brown body + white neck ring + emerald-green head
              ctx.fillStyle = shadeHex('#78716c', 1.0, currentMode);
              ctx.fillRect(Math.round(dx - 1.2 * px), Math.round(dy - 0.5 * px), Math.max(2, Math.round(2.5 * px)), Math.max(1.2, Math.round(1.3 * px)));
              ctx.fillStyle = '#f8fafc';
              ctx.fillRect(Math.round(dx + dir * 0.8 * px), Math.round(dy - 1.0 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.6 * px)));
              ctx.fillStyle = '#15803d';
              ctx.fillRect(Math.round(dx + dir * 0.9 * px), Math.round(dy - 1.8 * px), Math.max(1, Math.round(1.0 * px)), Math.max(1, Math.round(1.0 * px)));
            } else {
              // Trailing hen: warm mottled brown
              ctx.fillStyle = shadeHex('#8c6a4a', 1.0, currentMode);
              ctx.fillRect(Math.round(dx - 1.1 * px), Math.round(dy - 0.5 * px), Math.max(2, Math.round(2.3 * px)), Math.max(1.2, Math.round(1.2 * px)));
              ctx.fillStyle = shadeHex('#6f5238', 1.0, currentMode);
              ctx.fillRect(Math.round(dx + dir * 0.8 * px), Math.round(dy - 1.5 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.9 * px)));
            }
          }
        }
      }

      // 2 Stand-Up Paddleboarders (SUPs) moving at realistic slow speed (~1.57–1.72 m/s),
      // strictly on open water, rotated along travel axis with clean return-leg heading & wake flip!
      if (!isNight) {
        const sups = [
          { u0: 0.566, v0: 0.610, u1: 0.629, v1: 0.566, spd: 0.0024, ph: 0.15, board: '#38bdf8', shirt: '#f43f5e' },
          { u0: 0.446, v0: 0.730, u1: 0.506, v1: 0.675, spd: 0.0021, ph: 0.62, board: '#fbbf24', shirt: '#0d9488' },
        ];
        for (let i = 0; i < sups.length; i++) {
          const sp = sups[i];
          const phase = tSec * sp.spd * Math.PI * 2 + sp.ph * Math.PI * 2;
          const p = 0.5 + 0.5 * Math.sin(phase);
          const cosP = Math.cos(phase);
          const headingSign = cosP >= 0 ? 1 : -1; // +1 = SW->NE, -1 = NE->SW
          const speedMag = Math.abs(cosP);
          const su = sp.u0 + (sp.u1 - sp.u0) * p;
          const sv = sp.v0 + (sp.v1 - sp.v0) * p;
          if (!isWaterUV(su, sv)) continue;
          livingFrameCounts.sups++;
          const sx = toX(su);
          const sy = toY(sv);
          if (!inView(sx, sy, 30)) continue;

          // Unit travel vector in screen pixels, flipped cleanly on return leg!
          const rawDx = (sp.u1 - sp.u0) * worldW * scale;
          const rawDy = (sp.v1 - sp.v0) * worldH * scale;
          const len = Math.hypot(rawDx, rawDy) || 1;
          const tx = (rawDx / len) * headingSign;
          const ty = (rawDy / len) * headingSign;
          const ang = Math.atan2(ty, tx);
          const px = Math.max(1.0, 1.15 * s);

          // Trailing water wake strictly behind the board along (-tx, -ty), fading gently at turnarounds
          if (speedMag > 0.08) {
            const wakeA = (0.44 * speedMag).toFixed(2);
            ctx.fillStyle = `rgba(232,248,255,${wakeA})`;
            for (let k = 0; k < 2; k++) {
              const dist = (5.2 + k * 2.4) * px;
              const wx = sx - tx * dist;
              const wy = sy - ty * dist;
              const wLen = (2.8 - k * 0.7) * px;
              ctx.fillRect(Math.round(wx - wLen * 0.5), Math.round(wy - 0.5 * px), Math.max(2, Math.round(wLen)), Math.max(1, Math.round(1.0 * px)));
            }
          }

          // SUP board rotated cleanly along diagonal travel axis (pointed nose at +4.2*px, square tail at -3.8*px)
          ctx.save();
          ctx.translate(sx, sy);
          ctx.rotate(ang);
          ctx.fillStyle = shadeHex(sp.board, 1.0, currentMode);
          ctx.beginPath();
          ctx.moveTo(-3.8 * px, -0.95 * px);
          ctx.lineTo(2.4 * px, -0.95 * px);
          ctx.lineTo(4.2 * px, 0);
          ctx.lineTo(2.4 * px, 0.95 * px);
          ctx.lineTo(-3.8 * px, 0.95 * px);
          ctx.closePath();
          ctx.fill();
          ctx.restore();

          // Upright standing paddler + paddle blade sweeping cleanly along the travel axis
          drawMiniPerson(sx, sy - 0.5 * px, s * 0.88, shadeHex(sp.shirt, 1.0, currentMode), '#1e293b', hairs[i], false, 0);
          const stroke = Math.sin(tSec * 1.35 + i * 2.1);
          ctx.strokeStyle = '#334155';
          ctx.lineWidth = Math.max(1.0, 0.9 * s);
          ctx.beginPath();
          ctx.moveTo(sx + tx * 0.5 * px, sy - 4.0 * px);
          ctx.lineTo(sx + tx * (0.9 + stroke * 1.6) * px, sy + ty * (0.9 + stroke * 1.6) * px + 1.0 * px);
          ctx.stroke();
        }
      }
    }

    // =========================================================================
    // 5b. GOLDEN-HOUR SUNSET JOGGERS (Seestrasse Lakefront Promenade) & WARM CAFE/TERRACE GLOW!
    // =========================================================================
    if (isSunset && animData && animData.roads && scale >= 0.35) {
      const seeRd = animData.roads.find((r) => r.id === 'seestrasse_sb');
      if (seeRd && seeRd.pts && seeRd.pts.length > 10) {
        const joggers = [
          { f0: 0.36, f1: 0.52, spd: 0.0085, ph: 0.1, shirt: '#f97316' },
          { f0: 0.56, f1: 0.72, spd: 0.0078, ph: 0.55, shirt: '#38bdf8' },
          { f0: 0.42, f1: 0.60, spd: 0.0082, ph: 0.82, shirt: '#a3e635' },
        ];
        for (let ji = 0; ji < joggers.length; ji++) {
          const jg = joggers[ji];
          const jp = 0.5 + 0.5 * Math.sin(tSec * jg.spd * Math.PI * 2 + jg.ph * Math.PI * 2);
          const f = jg.f0 + (jg.f1 - jg.f0) * jp;
          const pos = samplePathAt(seeRd.pts, f, worldW, worldH, 3);
          if (!pos) continue;
          const isoY = 0.55;
          const gx = pos.tx;
          const gy = pos.ty / isoY;
          const gm = Math.hypot(gx, gy) || 1;
          const rx = -gy / gm;
          const ry = (gx / gm) * isoY;
          // Offset lakeward onto promenade sidewalk so joggers never overlap cars
          const jWx = pos.wx + rx * 5.6 * wScale;
          const jWy = pos.wy + ry * 5.6 * wScale;
          drawDepthMasked(jWx, jWy, walkerBounds, pos.d16, worldW, worldH, () => {
            drawMiniPerson(
              offsetX + jWx * scale,
              offsetY + jWy * scale,
              s * 0.92,
              shadeHex(jg.shirt, 1.06, currentMode),
              '#1e293b',
              hairs[ji % hairs.length],
              false,
              tSec * 12.5 + ji * 1.7,
            );
          }, 2.0);
        }
      }
    }

    if (isSunset || isNight) {
      const cfCenter = (vig.cf_meyer_haus && vig.cf_meyer_haus.center) || [0.48102, 0.42361];
      const terraces = [
        { u: 0.5818, v: 0.5768, r: 16 },            // Bendlikon Pier lakeside terrace
        { u: 0.4068, v: 0.7072, r: 15 },            // Seebad bathhouse pavilion terrace
        { u: cfCenter[0], v: cfCenter[1], r: 17 },  // C.F. Meyer-Haus garden terrace
      ];
      for (let ti = 0; ti < terraces.length; ti++) {
        const tc = terraces[ti];
        const tx = toX(tc.u);
        const ty = toY(tc.v);
        if (!inView(tx, ty, 36)) continue;
        const rad = tc.r * s;
        const grad = ctx.createRadialGradient(tx, ty, 1.5 * s, tx, ty, rad);
        grad.addColorStop(0, isNight ? 'rgba(255, 198, 112, 0.30)' : 'rgba(255, 198, 112, 0.24)');
        grad.addColorStop(0.55, isNight ? 'rgba(255, 184, 96, 0.12)' : 'rgba(255, 184, 96, 0.09)');
        grad.addColorStop(1, 'rgba(255, 180, 88, 0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.ellipse(tx, ty, rad * 1.15, rad * 0.72, 0, 0, Math.PI * 2);
        ctx.fill();
        // Cozy sunset patio visitors strolling near warm terrace lanterns
        if (isSunset && scale >= 0.45) {
          for (let g = 0; g < 2; g++) {
            const gu = tc.u + (g - 0.5) * 0.0011 + Math.sin(tSec * 0.3 + ti + g * 2.1) * 0.0002;
            const gv = tc.v + (g === 0 ? 0.0003 : -0.0002);
            drawMiniPerson(toX(gu), toY(gv), s * 0.86, shadeHex(coats[(ti * 2 + g) % coats.length], 1.0, currentMode), '#243040', hairs[(ti + g) % hairs.length], false, tSec * 1.4 + g);
          }
        }
      }
    }

    // =========================================================================
    // 6. BAHNHOF KILCHBERG — Depth-Masked Platform Commuters, Footbridge Walkers & Warm Platform Lamps!
    // =========================================================================
    const bhVig = vig.bahnhof_kilchberg || {
      plat_sw: [0.55049, 0.50304],
      plat_ne: [0.56449, 0.49558],
      footbridge: [[0.56281, 0.49120], [0.56679, 0.49719]],
    };
    const platSw = bhVig.plat_sw || [0.55049, 0.50304];
    const platNe = bhVig.plat_ne || [0.56449, 0.49558];
    const bhFb = bhVig.footbridge || [[0.56281, 0.49120], [0.56679, 0.49719]];
    if (boxInView(platSw[0] - 0.005, Math.min(platNe[1], bhFb[0][1]) - 0.004, Math.max(platNe[0], bhFb[1][0]) + 0.005, platSw[1] + 0.006)) {
      if (isNight || isSunset) {
        for (let l = 0; l < 5; l++) {
          const f = l / 4;
          const lu = platSw[0] + f * (platNe[0] - platSw[0]);
          const lv = platSw[1] + f * (platNe[1] - platSw[1]);
          const lx = toX(lu);
          const ly = toY(lv);
          if (!inView(lx, ly, 36)) continue;
          const gr = 14 * s;
          const grad = ctx.createRadialGradient(lx, ly, 1 * s, lx, ly, gr);
          grad.addColorStop(0, isNight ? 'rgba(255, 224, 146, 0.36)' : 'rgba(255, 214, 140, 0.18)');
          grad.addColorStop(1, 'rgba(255, 214, 140, 0)');
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(lx, ly, gr, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      // 8 commuters standing cleanly on the NW & SE Bahnhof Kilchberg platforms (depth-masked!)
      const nComm = isNight ? 4 : 8;
      const dPlatU = platNe[0] - platSw[0];
      const dPlatV = platNe[1] - platSw[1];
      for (let c = 0; c < nComm; c++) {
        const isSE = c % 2 === 1;
        const baseF = 0.12 + (c / nComm) * 0.78 + Math.sin(tSec * 0.25 + c * 1.9) * 0.04;
        const cu = (isSE ? platSw[0] + 0.0013 : platSw[0] - 0.0003) + baseF * dPlatU;
        const cv = (isSE ? platSw[1] + 0.0020 : platSw[1] + 0.0002) + baseF * dPlatV;
        const wx = cu * worldW;
        const wy = cv * worldH;
        const d16 = evalWalkerD16(wx, wy, 424.6, worldW, worldH, false);
        drawDepthMasked(wx, wy, walkerBounds, d16, worldW, worldH, () => {
          drawMiniPerson(
            toX(cu), toY(cv), s * 0.92,
            shadeHex(coats[(c + 3) % coats.length], 1.0, currentMode),
            shadeHex('#1e293b', 1.0, currentMode),
            hairs[c % hairs.length],
            isNight,
            tSec * 3.0 + c * 1.5,
            c % 3 === 0 ? '#334155' : null,
          );
        }, 2.0);
      }
      // 2 pedestrians crossing the elevated Bahnhof Kilchberg pedestrian footbridge (onElevatedDeck=true!)
      for (let fb = 0; fb < 2; fb++) {
        const pf = 0.5 + 0.5 * Math.sin(tSec * (0.14 + fb * 0.04) + fb * 2.5);
        const fu = bhFb[0][0] + (bhFb[1][0] - bhFb[0][0]) * pf;
        const fv = bhFb[0][1] + (bhFb[1][1] - bhFb[0][1]) * pf;
        const wx = fu * worldW;
        const wy = fv * worldH;
        const d16 = evalWalkerD16(wx, wy, 428.0, worldW, worldH, true);
        drawDepthMasked(wx, wy, walkerBounds, d16, worldW, worldH, () => {
          drawMiniPerson(toX(fu), toY(fv), s * 0.9, shadeHex(coats[fb + 4], 1.0, currentMode), '#27303f', hairs[fb + 1], isNight, tSec * 7.5 + fb);
        }, 2.0);
      }
    }

    // =========================================================================
    // 7. COZY NIGHTTIME STREETLAMP GLOWS ALONG ALL 3 MAIN ARTERIES (Cached!)
    // =========================================================================
    if (isNight && animData && animData.roads) {
      if (!drawKilchbergDetails._lampRoads || drawKilchbergDetails._lampRoadsSrc !== animData) {
        drawKilchbergDetails._lampRoadsSrc = animData;
        drawKilchbergDetails._lampRoads = animData.roads.filter(
          (r) => r.id === 'seestrasse_sb' || r.id === 'dorfstrasse_viaduct_up' || r.id === 'alte_landstrasse_eb',
        );
      }
      const lampRoads = drawKilchbergDetails._lampRoads;
      for (const rd of lampRoads) {
        const pts = rd.pts || [];
        const step = rd.id === 'seestrasse_sb' ? 28 : 26;
        for (let i = 10; i < pts.length - 10; i += step) {
          const sx = toX(pts[i][0]);
          const sy = toY(pts[i][1]);
          if (!inView(sx, sy, 24)) continue;
          const lr = Math.max(6, 12.5 * s);
          const grad = ctx.createRadialGradient(sx, sy, 0.5, sx, sy, lr);
          grad.addColorStop(0, 'rgba(255, 214, 128, 0.30)');
          grad.addColorStop(0.55, 'rgba(255, 190, 96, 0.11)');
          grad.addColorStop(1, 'rgba(255, 180, 80, 0)');
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.ellipse(sx, sy, lr * 1.15, lr * 0.72, 0, 0, Math.PI * 2);
          ctx.fill();
          if (s >= 0.8) {
            const gSz = Math.max(1.5, Math.round(1.5 * s));
            ctx.fillStyle = 'rgba(255, 236, 176, 0.86)';
            ctx.fillRect(Math.round(sx - gSz * 0.5), Math.round(sy - 3.5 * s), gSz, gSz);
          }
        }
      }
    }

    ctx.restore();
  }

  function drawAtmosphereAndLife(worldW, worldH, wScale, tSec, isNight, isSunset) {
    const s = scale * wScale;
    const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
    ctx.save();

    // A. Open-Lake Sun / Moon Water Glints (strictly clipped to eroded pure waterMask!)
    if (waterMask && waterW > 0 && waterH > 0) {
      const glintCol = isNight ? '#cddcf4' : (isSunset ? '#ffe2a8' : '#f4fbff');
      const px = Math.max(1.2, 1.5 * s);
      for (let i = 0; i < 96; i++) {
        const gu = 0.42 + hash01(i * 3.1 + 1) * 0.56;
        const gv = 0.34 + hash01(i * 5.7 + 2) * 0.62;
        if (!isWaterUV(gu, gv)) continue;
        const sx = gu * worldW * scale + offsetX;
        const sy = gv * worldH * scale + offsetY;
        if (sx < -8 || sx > canvas.width + 8 || sy < -8 || sy > canvas.height + 8) continue;
        const pulse = Math.sin(tSec * (1.8 + hash01(i * 9.3) * 2.2) + i * 2.41);
        if (pulse < 0.52) continue;
        const a = ((pulse - 0.52) / 0.48) * (isNight ? 0.44 : (isSunset ? 0.74 : 0.64));
        ctx.globalAlpha = a;
        ctx.fillStyle = glintCol;
        const rx = Math.round(sx);
        const ry = Math.round(sy);
        ctx.fillRect(rx - Math.round(px), ry, Math.max(2, Math.round(px * 2.4)), Math.max(1, Math.round(px * 0.75)));
        if (pulse > 0.82) {
          ctx.fillRect(rx, ry - Math.round(px * 0.6), Math.max(1, Math.round(px * 0.8)), Math.max(2, Math.round(px * 2.0)));
        }
      }
    }

    // A2. Animated Moonlit Water Shimmer Band across Lake Zurich (Night only, strictly waterMask-clipped!)
    if (isNight && waterMask && waterW > 0 && waterH > 0) {
      ctx.globalAlpha = 1.0;
      for (let i = 0; i < 32; i++) {
        const f = i / 31;
        const spread = (hash01(i * 13.7 + 5) - 0.5) * 0.042;
        const mu = 0.74 - f * 0.18 + spread + Math.sin(tSec * 1.4 + i * 1.7) * 0.0025;
        const mv = 0.54 + f * 0.24 + (hash01(i * 7.3 + 9) - 0.5) * 0.012;
        if (!isWaterUV(mu, mv)) continue;
        const sx = mu * worldW * scale + offsetX;
        const sy = mv * worldH * scale + offsetY;
        if (sx < -24 || sx > canvas.width + 24 || sy < -10 || sy > canvas.height + 10) continue;
        const pulse = 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(tSec * 2.1 + i * 2.3), 2.0);
        const wPx = Math.max(3, Math.round((5.5 + hash01(i * 4.1) * 7.0) * s));
        const hPx = Math.max(1, Math.round(1.3 * s));
        ctx.globalAlpha = pulse * 0.54;
        ctx.fillStyle = (i % 3 === 0) ? '#dbeafe' : '#93c5fd';
        ctx.fillRect(Math.round(sx - wPx * 0.5), Math.round(sy), wPx, hPx);
      }
    }

    // B. Sub-Pixel-Exact Harbor Navigation Beacons at Bendlikon ZSG Steamer Pier & Schooren Seebad Pier (Alpenglow & Night)
    ctx.globalAlpha = 1.0;
    if (isNight || isSunset) {
      const bpBeacon = (vig.bendlikon_pier && vig.bendlikon_pier.beacon) || [0.58700, 0.57838];
      const sbBeacon = (vig.seebad_kilchberg && vig.seebad_kilchberg.beacon) || [0.42221, 0.72359];
      const piers = [
        { u: bpBeacon[0], v: bpBeacon[1], col: '#ffb84d', glow: 'rgba(255,184,77,0.32)', freq: 1.4 },
        { u: sbBeacon[0], v: sbBeacon[1], col: '#6ee7b7', glow: 'rgba(110,231,183,0.30)', freq: 1.9 },
      ];
      for (const p of piers) {
        const sx = p.u * worldW * scale + offsetX;
        const sy = p.v * worldH * scale + offsetY;
        if (sx < -32 || sx > canvas.width + 32 || sy < -32 || sy > canvas.height + 32) continue;
        const blink = 0.45 + 0.55 * Math.pow(0.5 + 0.5 * Math.sin(tSec * p.freq), 2.5);
        const r = Math.max(3.5, 5.5 * s);
        ctx.globalAlpha = (isNight ? 0.85 : 0.48) * blink;
        ctx.fillStyle = p.glow;
        ctx.beginPath();
        ctx.arc(sx, sy, r * 1.9, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = (isNight ? 0.98 : 0.68) * blink;
        ctx.fillStyle = p.col;
        const dot = Math.max(2, Math.round(2.2 * s));
        ctx.fillRect(Math.round(sx - dot * 0.5), Math.round(sy - dot * 0.5), dot, dot);
        if (isNight) {
          for (let k = 1; k <= 4; k++) {
            const waveX = Math.sin(tSec * 3.1 + k * 1.7) * 1.4 * s;
            ctx.globalAlpha = (0.38 - k * 0.07) * blink;
            ctx.fillRect(Math.round(sx + waveX - dot * 0.5), Math.round(sy + k * 2.8 * s), dot, Math.max(1, Math.round(1.2 * s)));
          }
        }
      }
    }

    // C. Dual-Track Bahnhof Kilchberg SBB Typ L/N Railway Signals (Independent Northbound & Southbound 3-Aspect Masts!)
    ctx.globalAlpha = 1.0;
    {
      const bhVig = vig.bahnhof_kilchberg || {};
      const nbAnchor = bhVig.signal || [0.56849, 0.49218];
      const platSw = bhVig.plat_sw || [0.55049, 0.50304];
      const sbAnchor = [platSw[0] - 0.0045, platSw[1] + 0.0012];
      const trackSignals = [
        { trId: 'sbb_ic_north', u: nbAnchor[0], v: nbAnchor[1] }, // Gleis 1 East (Northbound)
        { trId: 'sbb_s8_south', u: sbAnchor[0], v: sbAnchor[1] }, // Gleis 2 West (Southbound)
      ];
      for (const sig of trackSignals) {
        const sx = sig.u * worldW * scale + offsetX;
        const sy = sig.v * worldH * scale + offsetY;
        if (sx <= -24 || sx >= canvas.width + 24 || sy <= -24 || sy >= canvas.height + 24) continue;
        const tr = (animData.trains || []).find((t) => t.id === sig.trId);
        let aspect = 'green'; // Fahrbegriff 1 (clear)
        if (tr) {
          const st = evalTrainState(tr, tSec);
          const mf = st.midFrac;
          if (st.isDwelling || (mf >= tr.stop_frac - 0.035 && mf <= tr.stop_frac + 0.085)) {
            aspect = 'red'; // Halt
          } else if (mf > tr.stop_frac + 0.085 && mf <= tr.stop_frac + 0.135) {
            aspect = 'amber'; // Fahrbegriff 2 (caution)
          }
        }
        const sigCol = aspect === 'red' ? '#ff3b3b' : (aspect === 'amber' ? '#fbbf24' : '#22e584');
        const sigGlow = aspect === 'red' ? 'rgba(255,59,59,0.34)' : (aspect === 'amber' ? 'rgba(251,191,36,0.32)' : 'rgba(34,229,132,0.30)');
        const lensOffY = aspect === 'green' ? -1.4 * s : (aspect === 'amber' ? 0 : 1.4 * s);
        const dot = Math.max(1.8, 1.8 * s);

        // Dark SBB steel mast & vertical Typ L/N signal hood
        ctx.globalAlpha = 0.88;
        ctx.fillStyle = isNight ? '#475569' : '#1e293b';
        ctx.fillRect(Math.round(sx - 0.5 * s), Math.round(sy + 1.5 * s), Math.max(1, Math.round(1.0 * s)), Math.max(3, Math.round(5.0 * s)));
        const hoodW = Math.max(2.6, 2.4 * s);
        const hoodH = Math.max(4.6, 4.8 * s);
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(Math.round(sx - hoodW * 0.5), Math.round(sy - hoodH * 0.5), Math.round(hoodW), Math.round(hoodH));
        ctx.strokeStyle = isNight ? '#64748b' : '#cbd5e1';
        ctx.lineWidth = Math.max(0.6, 0.5 * s);
        ctx.strokeRect(Math.round(sx - hoodW * 0.5), Math.round(sy - hoodH * 0.5), Math.round(hoodW), Math.round(hoodH));

        const ly = sy + lensOffY;
        if (isNight || isSunset) {
          ctx.globalAlpha = isNight ? 0.86 : 0.48;
          ctx.fillStyle = sigGlow;
          ctx.beginPath();
          ctx.arc(sx, ly, dot * 2.6, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.globalAlpha = isNight ? 0.98 : 0.90;
        ctx.fillStyle = sigCol;
        ctx.fillRect(Math.round(sx - dot * 0.5), Math.round(ly - dot * 0.5), Math.max(2, Math.round(dot)), Math.max(2, Math.round(dot)));
      }
    }

    // D. Swiss Church Bell Acoustic Ripples (canonical tSec % 52 < 20, anchored to M3 belfries!)
    ctx.globalAlpha = 1.0;
    if (!isNight) {
      const bellCycle = ((tSec % 52) + 52) % 52;
      if (bellCycle < 20) {
        const bellEnv = bellCycle < 2.2 ? (bellCycle / 2.2) : (bellCycle > 17.0 ? (20 - bellCycle) / 3.0 : 1.0);
        const spires = [
          (vig.reformierte_kirche && vig.reformierte_kirche.belfry) || [0.29037, 0.31203],
          (vig.st_elisabeth && vig.st_elisabeth.belfry) || [0.41165, 0.32675],
        ];
        ctx.strokeStyle = isSunset ? '#ffd89b' : '#fff3c4';
        ctx.lineWidth = Math.max(1.0, 1.2 * s);
        for (let si = 0; si < spires.length; si++) {
          const sx = spires[si][0] * worldW * scale + offsetX;
          const sy = spires[si][1] * worldH * scale + offsetY;
          if (sx < -80 || sx > canvas.width + 80 || sy < -80 || sy > canvas.height + 80) continue;
          for (let rIdx = 0; rIdx < 2; rIdx++) {
            const phase = (((tSec * 0.48 + rIdx * 0.5 + si * 0.25) % 1) + 1) % 1;
            const rad = (5 + phase * 26) * s;
            ctx.globalAlpha = (1 - phase) * 0.32 * bellEnv;
            ctx.beginPath();
            ctx.ellipse(sx, sy, rad, rad * 0.62, 0, 0, Math.PI * 2);
            ctx.stroke();
          }
        }
      }
    }

    // E. Nighttime Park Fireflies (gentle warm-gold pixel glints drifting through Kilchberg's parks!)
    ctx.globalAlpha = 1.0;
    if (isNight) {
      const dot = Math.max(1.5, 1.4 * s);
      for (let i = 0; i < 36; i++) {
        const g = FIREFLY_GROVES[i % FIREFLY_GROVES.length];
        const baseU = g[0] + (hash01(i * 4.3 + 7) - 0.5) * 0.045;
        const baseV = g[1] + (hash01(i * 6.1 + 3) - 0.5) * 0.045;
        const fu = baseU + Math.sin(tSec * 0.35 + i * 2.1) * 0.0045;
        const fv = baseV + Math.cos(tSec * 0.42 + i * 1.7) * 0.0038;
        const sx = fu * worldW * scale + offsetX;
        const sy = fv * worldH * scale + offsetY;
        if (sx < -10 || sx > canvas.width + 10 || sy < -10 || sy > canvas.height + 10) continue;
        const glow = Math.pow(0.5 + 0.5 * Math.sin(tSec * (1.5 + hash01(i * 2.9) * 1.6) + i * 3.7), 3.0);
        if (glow < 0.15) continue;
        ctx.globalAlpha = glow * 0.84;
        ctx.fillStyle = '#ffe57f';
        ctx.fillRect(Math.round(sx), Math.round(sy), Math.max(1.5, Math.round(dot)), Math.max(1.5, Math.round(dot)));
      }
    }

    // E2. 2 Graceful Soaring Red Kites (Rotmilan) circling Kilchberg's wooded ridges (Day & Alpenglow only!)
    ctx.globalAlpha = 1.0;
    if (!isNight) {
      const redKites = [
        { cu: 0.655, cv: 0.285, ru: 0.024, rv: 0.014, spd: 0.16, ph: 0.2 }, // Sanatorium Kilchberg wooded ridge
        { cu: 0.315, cv: 0.305, ru: 0.022, rv: 0.013, spd: 0.14, ph: 3.6 }, // Reformierte Kirche / Dorf wooded ridge
      ];
      for (let ki = 0; ki < redKites.length; ki++) {
        const rk = redKites[ki];
        const ang = tSec * rk.spd + rk.ph;
        const ku = rk.cu + Math.cos(ang) * rk.ru;
        const kv = rk.cv + Math.sin(ang) * rk.rv;
        livingFrameCounts.redKites++;
        const sx = ku * worldW * scale + offsetX;
        const sy = kv * worldH * scale + offsetY;
        if (sx < -36 || sx > canvas.width + 36 || sy < -36 || sy > canvas.height + 36) continue;
        const dx = -Math.sin(ang) * rk.ru * worldW;
        const dy = Math.cos(ang) * rk.rv * worldH;
        const flightAng = Math.atan2(dy, dx);
        const wingBeat = Math.sin(tSec * 2.2 + ki * 2.5) > 0.82 ? Math.sin(tSec * 12.0 + ki) * 1.2 : 0;
        const p = Math.max(0.85, s);

        // Subtle sunlit ground shadow beneath the soaring raptor
        ctx.save();
        ctx.translate(sx + 8 * p, sy + 14 * p);
        ctx.rotate(flightAng);
        ctx.fillStyle = 'rgba(18, 26, 22, 0.14)';
        ctx.beginPath();
        ctx.moveTo(4.0 * p, 0);
        ctx.lineTo(-0.5 * p, -6.5 * p);
        ctx.lineTo(-2.5 * p, -1.5 * p);
        ctx.lineTo(-5.5 * p, 0);
        ctx.lineTo(-2.5 * p, 1.5 * p);
        ctx.lineTo(-0.5 * p, 6.5 * p);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // Crisp Rotmilan silhouette: rufous-chestnut angled wings, pale wing windows, dark wingtips & forked tail!
        ctx.save();
        ctx.translate(sx, sy);
        ctx.rotate(flightAng);
        const span = (6.8 + wingBeat * 0.4) * p;
        // Chestnut-rufous wings
        ctx.fillStyle = isSunset ? '#b24b2c' : '#9a3b22';
        ctx.beginPath();
        ctx.moveTo(3.6 * p, 0);
        ctx.lineTo(0.8 * p, -span);
        ctx.lineTo(-2.0 * p, -span * 0.72);
        ctx.lineTo(-1.8 * p, 0);
        ctx.lineTo(-2.0 * p, span * 0.72);
        ctx.lineTo(0.8 * p, span);
        ctx.closePath();
        ctx.fill();
        // Signature forked reddish tail
        ctx.fillStyle = isSunset ? '#c95830' : '#b44524';
        ctx.beginPath();
        ctx.moveTo(-1.4 * p, -0.8 * p);
        ctx.lineTo(-5.6 * p, -2.0 * p);
        ctx.lineTo(-4.0 * p, 0);
        ctx.lineTo(-5.6 * p, 2.0 * p);
        ctx.lineTo(-1.4 * p, 0.8 * p);
        ctx.closePath();
        ctx.fill();
        // Pale primary wing-window patches + dark fingered wingtips
        ctx.fillStyle = isSunset ? '#f6e0c8' : '#e8d5c0';
        ctx.fillRect(Math.round(-0.4 * p), Math.round(-span * 0.65), Math.max(1.2, Math.round(1.4 * p)), Math.max(1.2, Math.round(1.8 * p)));
        ctx.fillRect(Math.round(-0.4 * p), Math.round(span * 0.45), Math.max(1.2, Math.round(1.4 * p)), Math.max(1.2, Math.round(1.8 * p)));
        ctx.fillStyle = '#1e1b18';
        ctx.fillRect(Math.round(-0.8 * p), Math.round(-span - 0.4 * p), Math.max(1.2, Math.round(1.6 * p)), Math.max(1.2, Math.round(1.6 * p)));
        ctx.fillRect(Math.round(-0.8 * p), Math.round(span - 1.2 * p), Math.max(1.2, Math.round(1.6 * p)), Math.max(1.2, Math.round(1.6 * p)));
        ctx.restore();
      }
    }

    // F. Soft Drifting Swiss Cloud Shadows (Midday & Alpenglow — gentle SW->NE atmospheric motion!)
    ctx.globalAlpha = 1.0;
    if (!isNight) {
      const cloudCol = isSunset ? 'rgba(34, 24, 52, 0.062)' : 'rgba(22, 38, 66, 0.052)';
      ctx.fillStyle = cloudCol;
      for (let c = 0; c < 6; c++) {
        const cu = (((tSec * 0.0042 + c * 0.19 + hash01(c * 11.3) * 0.08) % 1.35) + 1.35) % 1.35 - 0.18;
        const cv = 0.16 + (c % 3) * 0.24 + Math.sin(tSec * 0.05 + c) * 0.03 - cu * 0.14;
        const sx = cu * worldW * scale + offsetX;
        const sy = cv * worldH * scale + offsetY;
        const rx = (340 + (c % 3) * 140) * scale * wScale;
        const ry = rx * 0.42;
        if (sx + rx < 0 || sx - rx > canvas.width || sy + ry < 0 || sy - ry > canvas.height) continue;
        ctx.beginPath();
        ctx.ellipse(sx, sy, rx, ry, -0.32, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    ctx.restore();
  }

  // ---- SPATIAL KILCHBERG SOUNDSCAPE ENGINE (Real Field Recordings + Web Audio Spatial Mixer) ----
  // Mixes authentic Swiss/European field recordings (SBB train, ZVV bus, road cars, songbirds,
  // night crickets, Lake Zurich boat & shoreline waves) with real-time viewport visibility,
  // zoom-sensitive inverse-square distance falloff, air-absorption lowpass & stereo panning!
  let soundEnabled = false;
  let audioCtx = null;
  let audioMasterGain = null;
  let soundLoading = false;
  let soundReady = false;
  let lastAudioUpdateMs = 0;
  const soundChannels = {};

  const SOUND_TRACKS = {
    lake_waves:   { file: 'lake_waves.mp3',   baseGain: 0.085, maxHz: 3200 },
    birds:        { file: 'birds.mp3',        baseGain: 0.11,  maxHz: 4600 },
    crickets:     { file: 'crickets.mp3',     baseGain: 0.10,  maxHz: 4800 },
    train:        { file: 'train.mp3',        baseGain: 0.26,  maxHz: 4200 },
    traffic:      { file: 'traffic.mp3',      baseGain: 0.12,  maxHz: 3200 }, // A3 motorway passing-by traffic
    town_traffic: { file: 'town_traffic.mp3', baseGain: 0.30,  maxHz: 2000 }, // Warm European town car buzz/hum
    bus:          { file: 'bus.mp3',          baseGain: 0.14,  maxHz: 2400 },
    boat:         { file: 'boat.mp3',         baseGain: 0.18,  maxHz: 3000 },
    bells:        { file: 'bells.mp3',        baseGain: 0.22,  maxHz: 3400 },
  };
  const SOUND_MASTER_LEVEL = 0.48;

  // Layer mixer: per-group user trim (0..1.5) on top of the spatial engine; master scales the whole mix.
  const MIX_GROUPS = {
    lake_waves: 'lake', birds: 'nature', crickets: 'nature',
    traffic: 'traffic', town_traffic: 'traffic', bus: 'traffic',
    train: 'rail', boat: 'water', bells: 'bells',
  };
  const mixLevels = { master: 1, lake: 1, nature: 1, traffic: 1, rail: 1, water: 1, bells: 1 };
  // Live per-channel target gains (post spatial engine & mixer) exposed via window.__dioramaDebug.audioGains
  const audioGainReport = {};
  Object.keys(SOUND_TRACKS).forEach((k) => { audioGainReport[k] = 0; });
  let audioSuspendTimer = null;

  function masterTarget() {
    return soundEnabled ? SOUND_MASTER_LEVEL * mixLevels.master : 0.0001;
  }

  function suspendAudioSoon() {
    if (audioSuspendTimer) clearTimeout(audioSuspendTimer);
    audioSuspendTimer = setTimeout(() => {
      audioSuspendTimer = null;
      if (!soundEnabled && audioCtx && audioCtx.state === 'running') {
        audioCtx.suspend().catch(() => {});
      }
    }, 110);
  }

  function setSoundEnabled(on) {
    soundEnabled = !!on;
    const btn = document.getElementById('btn-toggle-sound');
    if (btn && !soundLoading) {
      btn.textContent = soundEnabled ? 'Sound: On' : 'Sound: Off';
    }
    if (btn) {
      btn.classList.toggle('active', soundEnabled);
      btn.setAttribute('aria-pressed', soundEnabled ? 'true' : 'false');
    }
    if (soundEnabled) {
      if (audioSuspendTimer) { clearTimeout(audioSuspendTimer); audioSuspendTimer = null; }
      if (!soundReady) {
        initSoundscape();
      } else if (audioCtx && audioMasterGain) {
        audioCtx.resume().catch(() => {});
        audioMasterGain.gain.cancelScheduledValues(audioCtx.currentTime);
        audioMasterGain.gain.setTargetAtTime(masterTarget(), audioCtx.currentTime, 0.25);
        lastAudioUpdateMs = 0;
        const { width, height } = getWorldSize();
        updateSoundscape(width, height, getAnimTimeSec());
      }
    } else if (audioCtx && audioMasterGain) {
      audioMasterGain.gain.cancelScheduledValues(audioCtx.currentTime);
      audioMasterGain.gain.setTargetAtTime(0.0001, audioCtx.currentTime, 0.03);
      suspendAudioSoon();
    }
  }

  async function initSoundscape() {
    if (soundReady || soundLoading) return;
    soundLoading = true;
    const btn = document.getElementById('btn-toggle-sound');
    if (btn) btn.textContent = 'Sound: Loading…';
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      audioCtx = new AC();
      if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
      const comp = audioCtx.createDynamicsCompressor();
      comp.threshold.value = -18;
      comp.knee.value = 20;
      comp.ratio.value = 3.0;
      comp.attack.value = 0.02;
      comp.release.value = 0.28;

      audioMasterGain = audioCtx.createGain();
      audioMasterGain.gain.value = 0.0001;
      comp.connect(audioMasterGain);
      audioMasterGain.connect(audioCtx.destination);

      const entries = Object.entries(SOUND_TRACKS);
      await Promise.all(entries.map(async ([key, cfg]) => {
        try {
          const resp = await fetch(`assets/audio/${cfg.file}?v=${ASSET_VER}`);
          if (!resp.ok) return;
          const arrBuf = await resp.arrayBuffer();
          const audioBuf = await audioCtx.decodeAudioData(arrBuf);
          const src = audioCtx.createBufferSource();
          src.buffer = audioBuf;
          src.loop = true;

          const lpf = audioCtx.createBiquadFilter();
          lpf.type = 'lowpass';
          lpf.frequency.value = 1200;
          lpf.Q.value = 0.50;

          const panner = audioCtx.createStereoPanner ? audioCtx.createStereoPanner() : null;
          const gain = audioCtx.createGain();
          gain.gain.value = 0.0001;

          src.connect(lpf);
          if (panner) {
            lpf.connect(panner);
            panner.connect(gain);
          } else {
            lpf.connect(gain);
          }
          gain.connect(comp);
          src.start(0, Math.random() * Math.max(0.5, audioBuf.duration * 0.7));
          soundChannels[key] = { src, lpf, panner, gain, cfg };
        } catch (err) {
          // Gracefully skip any track that fails to decode
        }
      }));
      soundReady = true;
    } catch (err) {
      soundEnabled = false;
    } finally {
      soundLoading = false;
      if (btn) {
        btn.textContent = soundEnabled ? 'Sound: On' : 'Sound: Off';
        btn.classList.toggle('active', soundEnabled);
        btn.setAttribute('aria-pressed', soundEnabled ? 'true' : 'false');
      }
      if (soundReady && audioMasterGain) {
        const now = audioCtx.currentTime;
        audioMasterGain.gain.setTargetAtTime(masterTarget(), now, soundEnabled ? 0.25 : 0.03);
        if (soundEnabled) {
          if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
          lastAudioUpdateMs = 0;
        } else {
          suspendAudioSoon();
        }
      }
    }
  }

  function computeSpatialFactor(u, v, u0, u1, v0, v1, uC, halfVisU, zoomNorm, maxOffscreenRange) {
    // True isotropic distance outside visible viewport (canvas aspect 5444/12331 ≈ 0.44)
    const dxOut = u < u0 ? (u0 - u) : (u > u1 ? (u - u1) : 0);
    const dyOut = v < v0 ? (v0 - v) : (v > v1 ? (v - v1) : 0);
    const dOut = Math.hypot(dxOut, dyOut * 0.44);
    const inView = dOut === 0;

    // Hard acoustic horizon: beyond maxOffscreenRange (shrinking as you zoom in!), sound drops cleanly to 0!
    const effRange = maxOffscreenRange / (0.65 + zoomNorm * 0.85);
    if (!inView && dOut >= effRange) {
      return { level: 0, brightness: 0.05, pan: 0, inView: false, dOut };
    }

    // Stereo pan relative to viewport horizontal center
    const pan = Math.max(-0.85, Math.min(0.85, (u - uC) / Math.max(0.035, halfVisU * 1.1)));

    // Smooth cubic falloff outside visible screen so background sounds are strongly dampened!
    const normD = inView ? 0 : (dOut / effRange);
    const offFalloff = inView ? 1.0 : Math.pow(1.0 - normD, 2.8) * 0.24;
    // Gentle distance-to-center emphasis when inside the screen
    const centerDist = Math.hypot(u - uC, (v - (v0 + v1) * 0.5) * 0.44) / Math.max(0.05, halfVisU * 1.4);
    const inFocus = 0.72 + 0.28 * Math.max(0, 1.0 - centerDist);

    // Zoomed-out overview stays soft & distant; zoomed-in visible sources become clearer & warmer
    const level = inView
      ? (0.34 + 0.66 * Math.min(1.0, zoomNorm / 1.5)) * inFocus
      : offFalloff;
    const brightness = inView
      ? (0.24 + 0.76 * Math.min(1.0, zoomNorm / 1.6))
      : Math.max(0.05, 0.26 * (1.0 - normD));

    return { level: Math.max(0, Math.min(1, level)), brightness, pan, inView, dOut };
  }

  function applyChannelSpatial(key, level, brightness, pan) {
    const ch = soundChannels[key];
    const cfg = SOUND_TRACKS[key];
    const trim = mixLevels[MIX_GROUPS[key]] != null ? mixLevels[MIX_GROUPS[key]] : 1;
    const targetGain = Math.max(0.0001, level * cfg.baseGain * trim);
    audioGainReport[key] = targetGain;
    if (!ch || !audioCtx) return;
    const now = audioCtx.currentTime;
    const targetHz = 340 + brightness * (ch.cfg.maxHz - 340);
    ch.gain.gain.setTargetAtTime(targetGain, now, 0.16);
    ch.lpf.frequency.setTargetAtTime(targetHz, now, 0.18);
    if (ch.panner) {
      ch.panner.pan.setTargetAtTime(Math.max(-0.85, Math.min(0.85, pan)), now, 0.14);
    }
  }

  function updateSoundscape(worldW, worldH, tSec) {
    if (!soundReady || !audioCtx || !animData || !soundEnabled) return;
    const nowMs = performance.now();
    if (nowMs - lastAudioUpdateMs < 60) return;
    lastAudioUpdateMs = nowMs;

    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }

    // Current visible viewport in normalized [0..1] world coordinates
    const u0 = (-offsetX) / (worldW * scale);
    const u1 = (canvas.width - offsetX) / (worldW * scale);
    const v0 = (-offsetY) / (worldH * scale);
    const v1 = (canvas.height - offsetY) / (worldH * scale);
    const uC = (u0 + u1) * 0.5;
    const halfVisU = Math.max(0.02, (u1 - u0) * 0.5);
    const zoomNorm = Math.max(0.15, Math.min(4.0, scale / dpr));
    const isNight = currentMode === 'night';
    const isSunset = currentMode === 'sunset';

    // 1. Swiss SBB Trains (carries moderately across the village; hushes when dwelling at Bahnhof Kilchberg!)
    let bestTrain = { level: 0, brightness: 0.08, pan: 0 };
    for (const tr of (animData.trains || [])) {
      const st = evalTrainState(tr, tSec);
      if (st.headFrac < 0.01 || st.headFrac > 1.12) continue;
      const isMoving = !st.isDwelling && st.speedRatio > 0.05;
      const midF = Math.max(0.01, Math.min(0.99, st.midFrac));
      const pos = samplePathAt(tr.pts, midF, worldW, worldH, 2);
      if (!pos) continue;
      const sp = computeSpatialFactor(pos.wx / worldW, pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.14);
      const lvl = sp.level * (isMoving ? (0.35 + 0.65 * st.speedRatio) : 0.12);
      if (lvl > bestTrain.level) {
        bestTrain = { level: lvl, brightness: sp.brightness * (isMoving ? 1.0 : 0.4), pan: sp.pan };
      }
    }
    applyChannelSpatial('train', bestTrain.level, bestTrain.brightness, bestTrain.pan);

    // 2. ZVV Buses, 3a. A3 Motorway Passing-By Traffic & 3b. Town Street Buzzing Cars (per-vehicle spatialized!)
    let bestBus = { level: 0, brightness: 0.08, pan: 0 };
    let bestMwCar = { level: 0, brightness: 0.08, pan: 0 };
    let mwSumLvl = 0;
    let mwPanSum = 0;
    let bestTownCar = { level: 0, brightness: 0.08, pan: 0 };
    let townSumLvl = 0;
    let townPanSum = 0;
    for (let rIdx = 0; rIdx < (animData.roads || []).length; rIdx++) {
      const rd = animData.roads[rIdx];
      const isMotorway = rd.kind === 'motorway';
      const busCount = rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0);
      const carCount = rd.car_count || 3;

      for (let bIdx = 0; bIdx < busCount; bIdx++) {
        if (isNight && bIdx > 0) continue;
        const st = evalBusState(rd, bIdx, tSec);
        if (st.frac < 0.001 || st.frac > 0.999) continue;
        const pos = samplePathAt(rd.pts, st.frac, worldW, worldH, 2);
        if (!pos) continue;
        const sp = computeSpatialFactor(pos.wx / worldW, pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.075);
        const busLvl = sp.level * (st.isDwelling ? 0.35 : (0.5 + 0.5 * st.speedRatio));
        if (busLvl > bestBus.level) bestBus = { level: busLvl, brightness: sp.brightness, pan: sp.pan };
      }

      const laneSpeed = Math.max(1.0, rd.speed_mps * (busCount > 0 ? 0.88 : 0.96));
      const cyc = rd.length_m / laneSpeed;
      const maxJitter = Math.min(0.011, 0.24 / Math.max(1, carCount));
      for (let cIdx = 0; cIdx < carCount; cIdx++) {
        const vIdx = busCount + cIdx;
        if (isNight && ((vIdx * 7 + rIdx * 3) % 20) >= 9) continue;
        const jitter = Math.sin(tSec * 0.28 + vIdx * 2.17 + rIdx * 1.3) * maxJitter;
        const frac = ((((tSec / cyc) + (rd.phase || 0) + (cIdx + 0.35) / Math.max(1, carCount) + jitter) % 1) + 1) % 1;
        if (frac < 0.001 || frac > 0.999) continue;
        const pos = samplePathAt(rd.pts, frac, worldW, worldH, 2);
        if (!pos) continue;
        const sp = computeSpatialFactor(
          pos.wx / worldW, pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm,
          isMotorway ? 0.062 : 0.085,
        );
        if (sp.level <= 0.002) continue;
        if (isMotorway) {
          const cl = sp.level * 0.90;
          mwSumLvl += cl * cl;
          mwPanSum += sp.pan * cl;
          if (cl > bestMwCar.level) bestMwCar = { level: cl, brightness: sp.brightness, pan: sp.pan };
        } else {
          const cl = sp.level * 0.95;
          townSumLvl += cl * cl;
          townPanSum += sp.pan * cl;
          if (cl > bestTownCar.level) bestTownCar = { level: cl, brightness: sp.brightness, pan: sp.pan };
        }
      }
    }
    const nightTrafficMul = isNight ? 0.55 : 1.0;
    applyChannelSpatial('bus', bestBus.level * nightTrafficMul, bestBus.brightness, bestBus.pan);
    const mwFinalLvl = Math.min(1.0, Math.sqrt(mwSumLvl)) * nightTrafficMul;
    const mwPan = bestMwCar.level > 0.001 ? (mwPanSum / Math.max(0.001, Math.sqrt(mwSumLvl))) : 0;
    applyChannelSpatial('traffic', mwFinalLvl, bestMwCar.brightness, mwPan);
    const townFinalLvl = Math.min(1.0, Math.sqrt(townSumLvl)) * nightTrafficMul;
    const townPan = bestTownCar.level > 0.001 ? (townPanSum / Math.max(0.001, Math.sqrt(townSumLvl))) : 0;
    applyChannelSpatial('town_traffic', townFinalLvl, bestTownCar.brightness, townPan);

    // 4. Lake Zurich ZSG Steamer Boat (localized to the boat on the lake)
    let bestBoat = { level: 0, brightness: 0.08, pan: 0 };
    for (const ship of (animData.ships || [])) {
      if (isNight && ship.kind !== 'zsg_steamer') continue;
      let frac;
      let isDocked = false;
      if (ship.closed) {
        frac = (((tSec / (ship.length_m / Math.max(0.5, ship.speed_mps))) + (ship.phase || 0)) % 1 + 1) % 1;
      } else {
        const st = evalWithStationStop(tSec, ship.length_m, ship.speed_mps, ship.stop_frac, ship.dwell_sec, ship.phase || 0, 5.0, 6.0);
        frac = st.frac;
        isDocked = st.isDwelling;
      }
      if (frac < 0 || frac > 1) continue;
      const pos = samplePathAt(ship.pts, frac, worldW, worldH, 2);
      if (!pos) continue;
      const sp = computeSpatialFactor(pos.wx / worldW, pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.09);
      const mul = (ship.kind === 'zsg_steamer' ? (isDocked ? 0.35 : 1.0) : 0.28);
      if (sp.level * mul > bestBoat.level) {
        bestBoat = { level: sp.level * mul, brightness: sp.brightness, pan: sp.pan };
      }
    }
    applyChannelSpatial('boat', bestBoat.level, bestBoat.brightness, bestBoat.pan);

    // 5. Lake Zurich Shoreline Waves (STRICT tight shoreline range: completely silent once you move away from the lake!)
    let bestWave = { level: 0, brightness: 0.08, pan: 0 };
    const shore = (animData.ambient && animData.ambient.shoreline) || [];
    for (let i = 0; i < shore.length; i++) {
      const sp = computeSpatialFactor(shore[i][0], shore[i][1], u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.042);
      if (sp.level > bestWave.level) bestWave = sp;
    }
    // Overview hush: from the zoomed-out Fit view the whole lake edge is "in view" but far away, so waves
    // must stay a barely-there murmur and only swell as the camera comes down to the water's edge.
    const waveZoomGate = Math.min(1, Math.max(0.04, (zoomNorm - 0.2) / 0.8));
    const wavePulse = 0.85 + 0.15 * Math.sin(tSec * (Math.PI * 2 / 5.6));
    applyChannelSpatial('lake_waves', bestWave.level * wavePulse * waveZoomGate, bestWave.brightness, bestWave.pan);

    // 6. Virtual Songbird Tree Perches (14 real wooded groves & parks with gentle intermittent singing!)
    const treeBirdPerches = [
      [0.29, 0.34, 0.0], [0.35, 0.43, 0.17], [0.41, 0.36, 0.33], [0.47, 0.46, 0.51],
      [0.52, 0.39, 0.68], [0.58, 0.43, 0.82], [0.64, 0.35, 0.11], [0.71, 0.33, 0.44],
      [0.37, 0.58, 0.25], [0.44, 0.55, 0.62], [0.54, 0.52, 0.77], [0.62, 0.48, 0.08],
      [0.26, 0.45, 0.39], [0.76, 0.28, 0.58],
    ];
    let bestBird = { level: 0, brightness: 0.08, pan: 0 };
    let bestCricket = { level: 0, brightness: 0.08, pan: 0 };
    for (const [tu, tv, ph] of treeBirdPerches) {
      const sp = computeSpatialFactor(tu, tv, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.050);
      if (sp.level <= 0.002) continue;
      // Gentle natural intermittent singing cadence per tree (sings softly, then rests)
      const singCycle = Math.sin(tSec * 0.22 + ph * Math.PI * 2);
      const singEnv = singCycle > -0.15 ? Math.min(1.0, (singCycle + 0.15) * 1.15) : 0.12;
      const bLvl = sp.level * singEnv;
      if (bLvl > bestBird.level) bestBird = { level: bLvl, brightness: sp.brightness, pan: sp.pan };
      if (sp.level > bestCricket.level) bestCricket = sp;
    }
    const birdMul = isNight ? 0.0 : (isSunset ? 0.55 : 1.0);
    const cricketMul = isNight ? 1.0 : (isSunset ? 0.30 : 0.0);
    applyChannelSpatial('birds', bestBird.level * birdMul, bestBird.brightness, bestBird.pan);
    applyChannelSpatial('crickets', bestCricket.level * cricketMul, bestCricket.brightness, bestCricket.pan);

    // 7. Authentic Swiss Church Bells (Reformierte Kirche Kilchberg & Katholische Kirche St. Elisabeth!)
    // Rings gently in a warm 20-second peal every 52 seconds, carrying softly across the hillside village.
    const bellCycle = (tSec + 12.0) % 52.0;
    let bellEnv = 0;
    if (bellCycle < 20.0) {
      bellEnv = bellCycle < 2.2 ? (bellCycle / 2.2) : (bellCycle > 17.0 ? ((20.0 - bellCycle) / 3.0) : 1.0);
    }
    let bestBell = { level: 0, brightness: 0.08, pan: 0 };
    if (bellEnv > 0.01 && !isNight) {
      const churches = [
        [0.29272, 0.3162], // Reformierte Kirche Kilchberg (550.5 m spire)
        [0.40667, 0.3425], // Katholische Kirche St. Elisabeth
      ];
      for (const [cu, cv] of churches) {
        const sp = computeSpatialFactor(cu, cv, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.28);
        const lvl = sp.level * bellEnv * (isSunset ? 1.0 : 0.85);
        if (lvl > bestBell.level) bestBell = { level: lvl, brightness: sp.brightness, pan: sp.pan };
      }
    }
    applyChannelSpatial('bells', bestBell.level, bestBell.brightness, bestBell.pan);
  }

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
        requestAnimationFrame(animLoop);
      }
      if (cssScale() < 1.5) {
        animateCamera(2.0 * dpr, getCenterUV().u, getCenterUV().v, 360, true);
      }
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
    if (followTarget === 'train' && (animData.trains || []).length) {
      // Prefer double-deck SBB S8 (sbb_s8_south); fall back to any other active train during its 6s offscreen buffer
      const primary = animData.trains.find((t) => t.id === 'sbb_s8_south') || animData.trains[0];
      const ordered = primary ? [primary, ...animData.trains.filter((t) => t !== primary)] : animData.trains;
      for (const tr of ordered) {
        const st = evalTrainState(tr, tSec);
        if (st.midFrac > 0.04 && st.midFrac < 0.96) {
          targetPos = samplePathAt(tr.pts, st.midFrac, worldW, worldH, 2);
          if (targetPos) break;
        }
      }
      if (!targetPos && primary) {
        const st = evalTrainState(primary, tSec);
        const clamped = Math.max(0.02, Math.min(0.98, st.midFrac >= 0 ? st.midFrac : (primary.stop_frac || 0.5)));
        targetPos = samplePathAt(primary.pts, clamped, worldW, worldH, 2);
      }
    } else if (followTarget === 'boat' && (animData.ships || []).length) {
      // Follow the flagship ZSG Lake Zurich paddle steamer (MS Helvetia)!
      const b = animData.ships.find((x) => x.id === 'zsg_ms_helvetia' || x.kind === 'zsg_steamer') || animData.ships[0];
      if (b) {
        const cyc = b.length_m / Math.max(0.5, b.speed_mps);
        const f = b.closed
          ? (((tSec / cyc) + (b.phase || 0)) % 1 + 1) % 1
          : evalWithStationStop(tSec, b.length_m, b.speed_mps, b.stop_frac, b.dwell_sec || 0, b.phase || 0, 5.0, 6.0).frac;
        targetPos = samplePathAt(b.pts, Math.max(0.02, Math.min(0.98, f >= 0 ? f : 0.02)), worldW, worldH, 2);
      }
    } else if (followTarget === 'bus' && (animData.roads || []).length) {
      // Follow VBZ/ZVV bus riding the curved Dorfstrasse horseshoe viaduct!
      const rd = animData.roads.find((r) => r.id === 'dorfstrasse_viaduct_up')
        || animData.roads.find((r) => r.has_bus || (r.bus_count || 0) > 0);
      if (rd) {
        const busCount = rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0);
        const st0 = evalBusState(rd, 0, tSec);
        let f = st0.frac;
        if ((f < 0.01 || f > 0.99) && currentMode !== 'night' && busCount > 1) {
          const st1 = evalBusState(rd, 1, tSec);
          if (st1.frac >= 0.01 && st1.frac <= 0.99) f = st1.frac;
        }
        targetPos = samplePathAt(rd.pts, Math.max(0.01, Math.min(0.99, f >= 0 ? f : 0.01)), worldW, worldH, 2);
      }
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
  function animLoop(nowMs) {
    if (showAnimations && animData && !document.hidden) {
      if (nowMs - lastAnimPaint >= 33 && !drawScheduled) {
        lastAnimPaint = nowMs;
        if (followTarget) updateFollowCamera(getAnimTimeSec(), false);
        draw();
      }
      requestAnimationFrame(animLoop);
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
        requestAnimationFrame(animLoop);
      } else {
        scheduleDraw();
      }
    });
  }

  const btnToggleSound = document.getElementById('btn-toggle-sound');
  if (btnToggleSound) {
    btnToggleSound.setAttribute('aria-pressed', 'false');
    btnToggleSound.addEventListener('click', () => setSoundEnabled(!soundEnabled));
  }

  // Spatial audio follows the camera on its own clock, so panning/zooming/switching presets keeps the
  // mix alive even while the animation loop is paused (Live: Off).
  setInterval(() => {
    if (!soundEnabled || !soundReady || document.hidden) return;
    const { width, height } = getWorldSize();
    updateSoundscape(width, height, getAnimTimeSec());
  }, 90);

  document.addEventListener('visibilitychange', () => {
    if (audioCtx && audioMasterGain && soundEnabled) {
      const target = document.hidden ? 0.0001 : masterTarget();
      audioMasterGain.gain.setTargetAtTime(target, audioCtx.currentTime, 0.15);
    }
    if (!document.hidden && showAnimations && animData) {
      requestAnimationFrame(animLoop);
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

  const urlParams = new URLSearchParams(window.location.search);
  const fixedAnimTime = urlParams.has('t') && Number.isFinite(parseFloat(urlParams.get('t')))
    ? parseFloat(urlParams.get('t'))
    : null;
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

  function loadDepthMap() {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        try {
          const dc = document.createElement('canvas');
          dc.width = img.naturalWidth;
          dc.height = img.naturalHeight;
          const dctx = dc.getContext('2d', { willReadFrequently: true });
          dctx.drawImage(img, 0, 0);
          depthPixels = dctx.getImageData(0, 0, dc.width, dc.height).data;
          depthW = dc.width;
          depthH = dc.height;
        } catch (err) {
          depthPixels = null;
        }
        resolve();
      };
      img.onerror = () => resolve();
      img.src = `assets/kilchberg_depth.png?v=${ASSET_VER}`;
    });
  }

  function buildWaterMask() {
    const dayImg = overviewImages.day;
    if (!dayImg || !dayImg.naturalWidth) return;
    try {
      // 1/4 master resolution (~3082x1361 -> 0.5 m/px water mask) with 1px erosion
      // so shoreline waves stop cleanly before touching any seawall, rock, boat, or pier!
      const mw = Math.floor(dayImg.naturalWidth / 2);
      const mh = Math.floor(dayImg.naturalHeight / 2);
      const wc = document.createElement('canvas');
      wc.width = mw;
      wc.height = mh;
      const wctx = wc.getContext('2d', { willReadFrequently: true });
      wctx.drawImage(dayImg, 0, 0, mw, mh);
      const px = wctx.getImageData(0, 0, mw, mh).data;
      const raw = new Uint8Array(mw * mh);
      for (let y = 0; y < mh; y++) {
        const dy = depthPixels ? Math.min(depthH - 1, Math.floor((y / mh) * depthH)) : 0;
        const dRow = dy * depthW;
        for (let x = 0; x < mw; x++) {
          const i = (y * mw + x) * 4;
          const r = px[i];
          const g = px[i + 1];
          const b = px[i + 2];
          // True Lake Zurich water hue (teal/aqua/deep blue — excludes grey seawalls, dark rocks/boats, green grass!)
          if (b > r + 10 && g > r + 6 && b > 66 && r < 126) {
            if (depthPixels) {
              const dx = Math.min(depthW - 1, Math.floor((x / mw) * depthW));
              if (depthPixels[(dRow + dx) * 4 + 2] > 128) continue;
            }
            raw[y * mw + x] = 1;
          }
        }
      }
      // 3x3 erosion (1px margin) so wave stroke width never spills onto adjacent rocks, boats, or seawalls
      const eroded = new Uint8Array(mw * mh);
      for (let y = 1; y < mh - 1; y++) {
        const row = y * mw;
        for (let x = 1; x < mw - 1; x++) {
          const idx = row + x;
          if (
            raw[idx] && raw[idx - 1] && raw[idx + 1]
            && raw[idx - mw] && raw[idx + mw]
            && raw[idx - mw - 1] && raw[idx - mw + 1]
            && raw[idx + mw - 1] && raw[idx + mw + 1]
          ) {
            eroded[idx] = 1;
          }
        }
      }
      waterMask = eroded;
      waterW = mw;
      waterH = mh;
    } catch (err) {
      waterMask = null;
    }
  }

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

  // ---- Audio layer mixer popover (Master + 6 layer trims)
  const btnMixer = document.getElementById('btn-audio-mixer');
  const mixerPop = document.getElementById('mixer-popover');
  if (btnMixer && mixerPop) {
    btnMixer.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = mixerPop.classList.toggle('hidden') === false;
      btnMixer.classList.toggle('active', open);
      btnMixer.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    mixerPop.addEventListener('click', (e) => e.stopPropagation());
    document.addEventListener('click', () => {
      if (!mixerPop.classList.contains('hidden')) {
        mixerPop.classList.add('hidden');
        btnMixer.classList.remove('active');
        btnMixer.setAttribute('aria-expanded', 'false');
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !mixerPop.classList.contains('hidden')) {
        mixerPop.classList.add('hidden');
        btnMixer.classList.remove('active');
        btnMixer.setAttribute('aria-expanded', 'false');
        btnMixer.focus();
      }
    });
    mixerPop.querySelectorAll('input[type="range"][data-mix]').forEach((slider) => {
      slider.addEventListener('input', () => {
        const key = slider.dataset.mix;
        mixLevels[key] = Math.max(0, Math.min(1.5, Number(slider.value) / 100));
        const out = slider.parentElement && slider.parentElement.querySelector('output');
        if (out) out.textContent = `${Math.round(mixLevels[key] * 100)}%`;
        if (key === 'master' && audioCtx && audioMasterGain) {
          audioMasterGain.gain.setTargetAtTime(masterTarget(), audioCtx.currentTime, 0.08);
        }
        lastAudioUpdateMs = 0;
        if (soundEnabled && soundReady) {
          const { width, height } = getWorldSize();
          updateSoundscape(width, height, getAnimTimeSec());
        }
      });
    });
  }

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
    loadDepthMap(),
    fetch(`data/kilchberg_interactive.json?v=${ASSET_VER}`).then((r) => r.json()).catch(() => null),
    fetch(`data/kilchberg_animations.json?v=${ASSET_VER}`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]).then(([_, __, ___, ____, loadedMeta, loadedAnim]) => {
    meta = loadedMeta;
    animData = loadedAnim;
    buildWaterMask();
    populateSidebar();
    resizeViewport();
    const qZoom = parseFloat(urlParams.get('zoom'));
    const qU = parseFloat(urlParams.get('u'));
    const qV = parseFloat(urlParams.get('v'));
    if (Number.isFinite(qZoom) && qZoom > 0) {
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
      requestAnimationFrame(animLoop);
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
      const { width, height } = getWorldSize();
      const { u: cu, v: cv } = getCenterUV();
      return {
        mode: currentMode,
        scale: scale / dpr,
        u: cu,
        v: cv,
        dpr,
        fps: renderStamps.length,
        audioEnabled: soundEnabled,
        audioState: audioCtx ? audioCtx.state : 'uninitialized',
        audioGains: { ...audioGainReport },
        activeLandmark: activeLandmarkId,
        selectedBuilding: selectedBuilding ? selectedBuilding.id : null,
        searchResultCount,
        animTime: getAnimTimeSec(),
        followTarget,
        showAnimations,
        waterMaskReady: !!(waterMask && waterW > 0 && waterH > 0),
        depthStats: { ...depthFrameStats },
        livingCounts: { ...livingFrameCounts },
      };
    },
  });
})();
