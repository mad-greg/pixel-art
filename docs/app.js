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

  const ASSET_VER = '3.1';

  // Overview images & optional ultra-high-res 0.25 m/px tile pyramids per lighting mode
  const overviewImages = {};
  const tileManifests = {};   // mode -> { width, height, tileSize, cols, rows, mpp } | null
  const tileCache = {};       // "mode:c:r" -> HTMLImageElement | 'loading' | 'error'

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
    canvas.width = Math.max(1, Math.floor(rect.width));
    canvas.height = Math.max(1, Math.floor(rect.height));
    draw();
  }

  function fitToScreen() {
    const { width, height } = getWorldSize();
    if (!width || !height) return;
    const pad = 20;
    const sx = (canvas.width - pad * 2) / width;
    const sy = (canvas.height - pad * 2) / height;
    scale = Math.min(sx, sy);
    offsetX = Math.round((canvas.width - width * scale) * 0.5);
    offsetY = Math.round((canvas.height - height * scale) * 0.5);
    updateZoomReadout();
    scheduleDraw();
  }

  function zoomAt(factor, cx, cy, exactScale = null) {
    const { width, height } = getWorldSize();
    if (!width || !height) return;
    const minScale = Math.min(0.06, (canvas.width * 0.5) / width);
    const maxScale = 8.0; // Up to 8x magnification of native 25 cm pixels!
    const prevScale = scale;
    scale = exactScale !== null
      ? Math.min(maxScale, Math.max(minScale, exactScale))
      : Math.min(maxScale, Math.max(minScale, scale * factor));

    const wx = (cx - offsetX) / prevScale;
    const wy = (cy - offsetY) / prevScale;
    offsetX = cx - wx * scale;
    offsetY = cy - wy * scale;
    clampOffsets();
    updateZoomReadout();
    scheduleDraw();
  }

  function panBy(dx, dy) {
    offsetX += dx;
    offsetY += dy;
    clampOffsets();
    scheduleDraw();
  }

  function updateZoomReadout() {
    const el = document.getElementById('zoom-readout');
    if (!el) return;
    if (scale >= 0.98) {
      const rounded = Math.abs(scale - Math.round(scale)) < 0.03 ? Math.round(scale) : scale.toFixed(2);
      el.textContent = `${rounded}× px`;
    } else {
      el.textContent = `${Math.round(scale * 100)}%`;
    }
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

    updatePins(width, height);
    drawMinimap(ov, width, height);
    if (showLoupe) drawLoupe(ov, width, height, tiled, mf);
  }

  function updatePins(worldW, worldH) {
    if (!meta || !showPins) {
      pinsLayer.innerHTML = '';
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
      const sx = offsetX + lm.uv[0] * worldW * scale;
      const sy = offsetY + lm.uv[1] * worldH * scale;
      pin.style.left = `${sx}px`;
      pin.style.top = `${sy}px`;
      pin.style.display = (sx < -100 || sx > canvas.width + 100 || sy < -40 || sy > canvas.height + 50) ? 'none' : 'block';
    });
  }

  function drawMinimap(ov, worldW, worldH) {
    if (!minimapCtx || !ov) return;
    const mw = minimapCanvas.width;
    const mh = minimapCanvas.height;
    minimapCtx.fillStyle = '#101724';
    minimapCtx.fillRect(0, 0, mw, mh);
    minimapCtx.imageSmoothingEnabled = true;
    minimapCtx.drawImage(ov, 0, 0, mw, mh);

    // Viewport indicator box
    const vx0 = (-offsetX / (worldW * scale)) * mw;
    const vy0 = (-offsetY / (worldH * scale)) * mh;
    const vw = (canvas.width / (worldW * scale)) * mw;
    const vh = (canvas.height / (worldH * scale)) * mh;

    minimapCtx.strokeStyle = '#e2b45b';
    minimapCtx.lineWidth = 1.6;
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
    const lx = Math.min(canvas.width - lw - 16, Math.max(14, lastMouse.x + 22));
    const ly = Math.min(canvas.height - lh - 16, Math.max(14, lastMouse.y - lw * 0.5));
    loupeCanvas.style.left = `${lx}px`;
    loupeCanvas.style.top = `${ly}px`;
  }

  function flyToLandmark(lm, targetZoom = null) {
    const { width, height, tiled } = getWorldSize();
    if (!width || !height) return;
    // Zoom closely so individual windows, roof tiles, trees & boats are crisp!
    scale = targetZoom !== null ? targetZoom : (tiled ? 1.5 : 2.2);
    offsetX = Math.round(canvas.width * 0.5 - lm.uv[0] * width * scale);
    offsetY = Math.round(canvas.height * 0.5 - lm.uv[1] * height * scale);
    clampOffsets();
    updateZoomReadout();
    scheduleDraw();
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

  function hitTestBuilding(clientX, clientY) {
    if (!meta) return;
    const { width, height } = getWorldSize();
    const rect = viewport.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;
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
    if (best) {
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
    }
  }

  // ---------------------------------------------------------------------------
  // Bulletproof Unified Pointer Pan + Multi-Touch Pinch Zoom + Minimap Drag
  // ---------------------------------------------------------------------------
  const activePointers = new Map();
  let gestureMovedDist = 0;
  let downTarget = null;

  viewport.addEventListener('contextmenu', (e) => e.preventDefault());

  viewport.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.viewport-ui')) return;
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
    lastMouse = { x: e.clientX - rect.left, y: e.clientY - rect.top };

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
      panBy(dx, dy);
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
      offsetX += newMidX - prevMidX;
      offsetY += newMidY - prevMidY;
      zoomAt(newDist / prevDist, newMidX - rect.left, newMidY - rect.top);
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
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;

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
      panBy(-dx, -dy);
    } else {
      const clampedDy = Math.max(-160, Math.min(160, dy));
      const factor = Math.exp(-clampedDy * 0.0028);
      zoomAt(factor, cx, cy);
    }
  }, { passive: false });

  // Interactive Minimap click & drag to pan anywhere immediately!
  let minimapDragging = false;
  function panFromMinimap(clientX, clientY) {
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

  // On-screen D-Pad buttons
  document.querySelectorAll('.dpad-btn[data-dx]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      panBy(Number(btn.dataset.dx), Number(btn.dataset.dy));
    });
  });
  document.getElementById('btn-dpad-fit').addEventListener('click', (e) => {
    e.stopPropagation();
    fitToScreen();
  });

  // Keyboard Pan (Arrows / WASD) & Zoom (+ / - / 0)
  window.addEventListener('keydown', (e) => {
    if (!document.getElementById('modal-overlay').classList.contains('hidden')) {
      if (e.key === 'Escape') document.getElementById('modal-overlay').classList.add('hidden');
      return;
    }
    const step = e.shiftKey ? 320 : 140;
    if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') { e.preventDefault(); panBy(step, 0); }
    else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') { e.preventDefault(); panBy(-step, 0); }
    else if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W') { e.preventDefault(); panBy(0, step); }
    else if (e.key === 'ArrowDown' || e.key === 's' || e.key === 'S') { e.preventDefault(); panBy(0, -step); }
    else if (e.key === '=' || e.key === '+') { e.preventDefault(); zoomAt(1.35, canvas.width / 2, canvas.height / 2); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomAt(1 / 1.35, canvas.width / 2, canvas.height / 2); }
    else if (e.key === '0') { e.preventDefault(); fitToScreen(); }
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
    modalCanvas.width = Math.floor(rect.width);
    modalCanvas.height = Math.floor(rect.height);
    modalCtx.fillStyle = '#0f1520';
    modalCtx.fillRect(0, 0, modalCanvas.width, modalCanvas.height);
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

  function openCropModal(c) {
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
  document.getElementById('btn-modal-fit').addEventListener('click', () => fitModal(null));
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
      const relZoom = (prevWorld.width * scale) / canvas.width;

      document.querySelectorAll('.seg-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.mode;
      await Promise.all([loadModeOverview(currentMode), loadTileManifest(currentMode)]);

      const nextWorld = getWorldSize();
      scale = (relZoom * canvas.width) / nextWorld.width;
      offsetX = canvas.width * 0.5 - centerU * nextWorld.width * scale;
      offsetY = canvas.height * 0.5 - centerV * nextWorld.height * scale;
      updateZoomReadout();
      scheduleDraw();
    });
  });

  document.getElementById('btn-zoom-in').addEventListener('click', () => zoomAt(1.4, canvas.width / 2, canvas.height / 2));
  document.getElementById('btn-zoom-out').addEventListener('click', () => zoomAt(1 / 1.4, canvas.width / 2, canvas.height / 2));
  document.getElementById('btn-zoom-1x').addEventListener('click', () => zoomAt(1, canvas.width / 2, canvas.height / 2, 1.0));
  document.getElementById('btn-zoom-2x').addEventListener('click', () => zoomAt(1, canvas.width / 2, canvas.height / 2, 2.0));
  document.getElementById('btn-zoom-4x').addEventListener('click', () => zoomAt(1, canvas.width / 2, canvas.height / 2, 4.0));
  document.getElementById('btn-zoom-fit').addEventListener('click', fitToScreen);

  // ---------------------------------------------------------------------------
  // 90s Isometric Pixel-Art Moving Elements Engine (Trains, Cars, Ships, Steam & Flags)
  // ---------------------------------------------------------------------------
  const spriteCache = {};
  const CAR_PALETTES = [
    { roof: [208, 62, 54], side: [164, 42, 38], front: [186, 52, 46] },   // Swiss crimson
    { roof: [76, 114, 168], side: [52, 82, 128], front: [64, 98, 148] },  // Zürichsee cobalt
    { roof: [204, 206, 210], side: [154, 158, 166], front: [178, 182, 188] }, // Silver metallic
    { roof: [68, 122, 84], side: [46, 88, 58], front: [58, 104, 72] },    // Alpine forest green
    { roof: [212, 178, 92], side: [168, 136, 64], front: [190, 158, 78] }, // Warm ochre-gold
    { roof: [82, 86, 96], side: [54, 58, 66], front: [68, 72, 82] },      // Anthracite charcoal
  ];

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

  function drawLinePx(buf, x0, y0, x1, y1, rgb, alpha = 255) {
    let ix0 = Math.round(x0), iy0 = Math.round(y0);
    const ix1 = Math.round(x1), iy1 = Math.round(y1);
    const dx = Math.abs(ix1 - ix0), dy = Math.abs(iy1 - iy0);
    const sx = ix0 < ix1 ? 1 : -1, sy = iy0 < iy1 ? 1 : -1;
    let err = dx - dy;
    for (let guard = 0; guard < 256; guard++) {
      setPx(buf, ix0, iy0, rgb, alpha);
      if (ix0 === ix1 && iy0 === iy1) break;
      const e2 = err * 2;
      if (e2 > -dy) { err -= dy; ix0 += sx; }
      if (e2 < dx) { err += dx; iy0 += sy; }
    }
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
    const cabGlass = isNight ? [120, 148, 184] : [30, 44, 66];
    const winAlpha = isNight ? 254 : 255;

    let buf;
    if (type === 'car') {
      buf = createPixelBuffer(38, 34);
      const cx = 19, cy = 19;
      const pal = CAR_PALETTES[variant % CAR_PALETTES.length];
      const B = makeIsoBasis(cx, cy, tx, ty);
      // Ground shadow + lower chassis
      drawIsoBox(buf, cx, cy, tx, ty, 9.2, 4.2, 3.6, 0.8, pal, true, B);
      // Dark wheel arches along visible side
      const vs = B.visSide * 4.25;
      for (const ws of [-5.5, 5.5]) {
        const wp = B.pt(ws, vs, 1.0);
        setPx(buf, wp[0], wp[1], [28, 32, 38], 255);
        setPx(buf, wp[0] + 1, wp[1], [28, 32, 38], 255);
      }
      // Slightly set-back cabin with dark windshield & rear glass
      const cab = makeIsoBasis(cx - B.fx * 1.0, cy - B.fy * 1.0, tx, ty);
      drawIsoBox(buf, cx, cy, tx, ty, 4.8, 3.5, 3.2, 4.4, {
        roof: pal.roof,
        side: winCol,
        front: cabGlass,
        emissive: isNight,
      }, false, cab);
      // Crisp twin headlights & red taillights
      for (const wy of [-2.4, 2.4]) {
        const hl = B.pt(9.4, wy, 2.4);
        setPx(buf, hl[0], hl[1], [255, 248, 198], 254);
        const tl = B.pt(-9.4, wy, 2.4);
        setPx(buf, tl[0], tl[1], [236, 46, 40], 254);
      }
      applySelOutAndShade(buf, mode);
      spriteCache[key] = { canvas: buf.c, cx, cy };
      return spriteCache[key];
    }

    if (type === 'bus') {
      buf = createPixelBuffer(72, 58);
      const cx = 36, cy = 33;
      const B = makeIsoBasis(cx, cy, tx, ty);
      // ZVV Zurich white & cobalt-blue bus
      drawIsoBox(buf, cx, cy, tx, ty, 22.5, 5.2, 4.2, 1.0, {
        roof: [46, 98, 182], side: [36, 82, 162], front: [44, 92, 174],
      }, true, B);
      drawIsoBox(buf, cx, cy, tx, ty, 22.5, 5.2, 7.0, 5.2, {
        roof: [236, 238, 240], side: [218, 222, 226], front: [228, 230, 234],
      }, false, B);
      // Roof AC pod
      drawIsoBox(buf, cx, cy, tx, ty, 8.5, 3.2, 1.8, 12.2, {
        roof: [208, 212, 218], side: [182, 188, 196], front: [194, 198, 206],
      }, false, B);
      // Dark wheel wells
      const vs = B.visSide * 5.25;
      for (const ws of [-13.5, 13.5]) {
        fillPolyPx(buf, [
          B.pt(ws - 2.2, vs, 0.5), B.pt(ws + 2.2, vs, 0.5),
          B.pt(ws + 2.2, vs, 3.0), B.pt(ws - 2.2, vs, 3.0),
        ], [26, 30, 36], 255);
      }
      // Panoramic passenger windows along visible side
      for (let s = -17.5; s <= 17.5; s += 5.4) {
        fillPolyPx(buf, [
          B.pt(s - 2.0, vs, 6.2), B.pt(s + 2.0, vs, 6.2),
          B.pt(s + 2.0, vs, 10.6), B.pt(s - 2.0, vs, 10.6),
        ], winCol, winAlpha);
      }
      // Front panoramic windshield if front end is visible
      if (B.visEnd > 0) {
        fillPolyPx(buf, [
          B.pt(22.6, -4.2, 5.8), B.pt(22.6, 4.2, 5.8),
          B.pt(22.6, 4.2, 10.8), B.pt(22.6, -4.2, 10.8),
        ], cabGlass, 255);
      }
      for (const wy of [-3.2, 3.2]) {
        const hl = B.pt(22.8, wy, 3.0);
        setPx(buf, hl[0], hl[1], [255, 248, 198], 254);
        const tl = B.pt(-22.8, wy, 3.0);
        setPx(buf, tl[0], tl[1], [236, 46, 40], 254);
      }
      applySelOutAndShade(buf, mode);
      spriteCache[key] = { canvas: buf.c, cx, cy };
      return spriteCache[key];
    }

    if (type === 'sbb_dpz' || type === 'sbb_ic') {
      // Master-crafted SBB RABe 511 KISS (sbb_dpz) & SBB IC 2000 (sbb_ic) double-deck trains
      // variant: 0 = Lead Cab Car, 1 = Middle Coach, 2 = Tail Cab Car
      buf = createPixelBuffer(128, 96);
      const cx = 64, cy = 58;
      const B = makeIsoBasis(cx, cy, tx, ty);
      const isLead = variant === 0;
      const isTail = variant === 2;
      const isDpz = type === 'sbb_dpz';
      const HLEN = 38.0; // 19.0 m at 0.25 m/px -> zero gaps at 19.5 m step with gangways!
      const HWID = 5.6;
      const vs = B.visSide * (HWID + 0.08);

      // 1. Dark rail shadow & underframe skirt + two bogies with steel wheel dots
      drawIsoBox(buf, cx, cy, tx, ty, HLEN - 1.5, HWID - 0.5, 2.4, 0.2, {
        roof: [40, 44, 52], side: [34, 38, 46], front: [36, 40, 48],
      }, true, B);
      for (const bs of [-25.0, 25.0]) {
        // Steel bogie frame & 2 axle wheels
        for (const ws of [-4.2, 4.2]) {
          const wp = B.pt(bs + ws, vs, 1.2);
          setPx(buf, wp[0], wp[1], [118, 126, 138], 255);
          setPx(buf, wp[0], wp[1] + 1, [74, 80, 90], 255);
        }
      }

      // 2. Articulated dark rubber gangway bellows at coupled ends (bridges coaches seamlessly!)
      const drawGangway = (endSign) => {
        const g0 = endSign * (HLEN - 1.0);
        const g1 = endSign * (HLEN + 3.2);
        const sMin = Math.min(g0, g1), sMax = Math.max(g0, g1);
        const gMid = (sMin + sMax) * 0.5;
        const gB = makeIsoBasis(cx + B.fx * gMid, cy + B.fy * gMid, tx, ty);
        drawIsoBox(buf, cx, cy, tx, ty, (sMax - sMin) * 0.5, HWID - 1.3, 12.6, 2.6, {
          roof: [46, 50, 58], side: [38, 42, 50], front: [42, 46, 54],
        }, false, gB);
      };
      if (!isLead) drawGangway(1);
      if (!isTail) drawGangway(-1);

      // 3. Main double-deck carbody shell (sleek SBB white/light-silver with dark roof)
      const bodyLen = (isLead || isTail) ? HLEN - 3.0 : HLEN;
      const bodyShift = isLead ? -3.0 : (isTail ? 3.0 : 0.0);
      const bodyB = makeIsoBasis(cx + B.fx * bodyShift, cy + B.fy * bodyShift, tx, ty);
      const shellPal = isDpz
        ? { roof: [112, 118, 128], side: [232, 234, 236], front: [212, 214, 218] }
        : { roof: [104, 110, 120], side: [236, 236, 232], front: [214, 214, 210] };
      drawIsoBox(buf, cx, cy, tx, ty, bodyLen, HWID, 14.2, 2.4, shellPal, false, bodyB);

      // 4. SBB Livery Bands, Anthracite Window Stripes, Bold SBB Red Doors & Dual-Deck Windows!
      const sStart = isTail ? -HLEN + 7.5 : -HLEN + 1.5;
      const sEnd = isLead ? HLEN - 7.5 : HLEN - 1.5;

      // Upper & lower dark anthracite window ribbon (iconic SBB KISS / IC 2000 look!)
      const bandColor = isDpz ? [44, 52, 66] : [36, 40, 48];
      fillPolyPx(buf, [
        B.pt(sStart, vs, 3.8), B.pt(sEnd, vs, 3.8),
        B.pt(sEnd, vs, 7.4), B.pt(sStart, vs, 7.4),
      ], bandColor, 255);
      fillPolyPx(buf, [
        B.pt(sStart, vs, 10.0), B.pt(sEnd, vs, 10.0),
        B.pt(sEnd, vs, 14.0), B.pt(sStart, vs, 14.0),
      ], bandColor, 255);

      // ZVV cobalt-blue lower accent stripe on S-Bahn DPZ / KISS, or yellow 1st-class band on IC 2000
      if (isDpz) {
        fillPolyPx(buf, [
          B.pt(sStart, vs, 2.5), B.pt(sEnd, vs, 2.5),
          B.pt(sEnd, vs, 3.8), B.pt(sStart, vs, 3.8),
        ], [36, 86, 168], 255);
      } else {
        // Yellow 1st-class band above upper windows on lead/IC coach
        fillPolyPx(buf, [
          B.pt(sStart, vs, 14.1), B.pt(sEnd, vs, 14.1),
          B.pt(sEnd, vs, 15.1), B.pt(sStart, vs, 15.1),
        ], [234, 194, 42], 255);
      }

      // Bold SBB red double-leaf entry doors near coach thirds
      const doorPositions = isLead ? [-24.5, 16.5] : (isTail ? [-16.5, 24.5] : [-25.5, 25.5]);
      for (const ds of doorPositions) {
        fillPolyPx(buf, [
          B.pt(ds - 3.2, vs, 2.6), B.pt(ds + 3.2, vs, 2.6),
          B.pt(ds + 3.2, vs, 13.8), B.pt(ds - 3.2, vs, 13.8),
        ], [206, 40, 38], 255);
        // Narrow door window
        fillPolyPx(buf, [
          B.pt(ds - 1.3, vs, 6.2), B.pt(ds + 1.3, vs, 6.2),
          B.pt(ds + 1.3, vs, 11.4), B.pt(ds - 1.3, vs, 11.4),
        ], winCol, winAlpha);
      }

      // Individual glowing dual-deck passenger windows between doors
      for (let s = sStart + 3.0; s <= sEnd - 3.0; s += 5.4) {
        if (doorPositions.some(ds => Math.abs(s - ds) < 4.8)) continue;
        // Lower deck window
        fillPolyPx(buf, [
          B.pt(s - 1.8, vs, 4.3), B.pt(s + 1.8, vs, 4.3),
          B.pt(s + 1.8, vs, 7.0), B.pt(s - 1.8, vs, 7.0),
        ], winCol, winAlpha);
        // Upper deck window
        fillPolyPx(buf, [
          B.pt(s - 1.8, vs, 10.5), B.pt(s + 1.8, vs, 10.5),
          B.pt(s + 1.8, vs, 13.5), B.pt(s - 1.8, vs, 13.5),
        ], winCol, winAlpha);
      }

      // 5. Aerodynamic Sloped SBB Red Cab Nose (Lead +1 or Tail -1)
      if (isLead || isTail) {
        const dir = isLead ? 1 : -1;
        const nBase = dir * (HLEN - 6.0);
        const nTip = dir * (HLEN + 4.0);
        const nTop = dir * (HLEN - 1.0);
        // Red aerodynamic nose side wedge
        fillPolyPx(buf, [
          B.pt(nBase, vs, 2.4), B.pt(nTip, vs * 0.72, 3.0),
          B.pt(nTip, vs * 0.72, 7.6), B.pt(nTop, vs * 0.88, 15.8),
          B.pt(nBase, vs, 16.6),
        ], [196, 38, 36], 255);
        // Sloped nose front face & panoramic dark cab windshield
        fillPolyPx(buf, [
          B.pt(nTip, -HWID * 0.72, 3.0), B.pt(nTip, HWID * 0.72, 3.0),
          B.pt(nTip, HWID * 0.72, 7.6), B.pt(nTip, -HWID * 0.72, 7.6),
        ], [216, 44, 40], 255);
        fillPolyPx(buf, [
          B.pt(nTip, -HWID * 0.72, 7.6), B.pt(nTip, HWID * 0.72, 7.6),
          B.pt(nTop, HWID * 0.88, 15.4), B.pt(nTop, -HWID * 0.88, 15.4),
        ], cabGlass, 255);
        // Red nose crown merging into roof
        fillPolyPx(buf, [
          B.pt(nTop, -HWID * 0.88, 15.4), B.pt(nTop, HWID * 0.88, 15.4),
          B.pt(nBase, HWID, 16.6), B.pt(nBase, -HWID, 16.6),
        ], [186, 38, 36], 255);

        // Iconic Swiss 3-point LED headlights (lead) or twin red taillights (tail)
        const lampCol = isLead ? [255, 250, 206] : [242, 46, 42];
        for (const wy of [-2.8, 2.8]) {
          const lp = B.pt(nTip + dir * 0.5, wy, 4.6);
          setPx(buf, lp[0], lp[1], lampCol, 254);
          setPx(buf, lp[0] + (isLead ? 0 : 0), lp[1] + 1, lampCol, 254);
        }
        if (isLead) {
          const topLamp = B.pt(nTop + dir * 0.4, 0, 14.6);
          setPx(buf, topLamp[0], topLamp[1], [255, 250, 210], 254);
        }
      }

      // 6. Roof HVAC pods & Detailed Silver Scissor Pantograph on Lead/Tail Cab Cars
      drawIsoBox(buf, cx, cy, tx, ty, 11.0, 3.2, 1.4, 16.6, {
        roof: [148, 154, 164], side: [122, 128, 138], front: [134, 140, 150],
      }, false, bodyB);
      if (isLead || isTail) {
        const pCenter = isLead ? -14.0 : 14.0;
        const pBaseA = B.pt(pCenter - 5.0, 0, 17.6);
        const pBaseB = B.pt(pCenter + 5.0, 0, 17.6);
        const pKnee = B.pt(pCenter + (isLead ? -7.5 : 7.5), 0, 20.6);
        const pHeadL = B.pt(pCenter, -3.6, 23.2);
        const pHeadR = B.pt(pCenter, 3.6, 23.2);
        const pHeadM = B.pt(pCenter, 0, 23.2);
        // Red ceramic roof insulators
        setPx(buf, pBaseA[0], pBaseA[1], [198, 54, 48], 255);
        setPx(buf, pBaseB[0], pBaseB[1], [198, 54, 48], 255);
        // Silver articulated Z-arm pantograph & carbon collector bar
        drawLinePx(buf, pBaseB[0], pBaseB[1], pKnee[0], pKnee[1], [204, 212, 222], 255);
        drawLinePx(buf, pKnee[0], pKnee[1], pHeadM[0], pHeadM[1], [224, 230, 238], 255);
        drawLinePx(buf, pHeadL[0], pHeadL[1], pHeadR[0], pHeadR[1], [164, 172, 184], 255);
      }

      applySelOutAndShade(buf, mode);
      spriteCache[key] = { canvas: buf.c, cx, cy };
      return spriteCache[key];
    }

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

      // Main & upper white passenger salon decks
      const salon1 = drawIsoBox(buf, cx - tx * 6, cy - ty * 6, tx, ty, 46.0, 10.2, 8.0, 4.5, {
        roof: [232, 230, 224], side: [216, 214, 208], front: [224, 222, 216],
      }, false);
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

  function evalWithStationStop(tSec, lengthM, speedMps, stopFrac, dwellSec, phase) {
    const travelSec = lengthM / Math.max(0.5, speedMps);
    const pause = dwellSec || 0;
    const cycleSec = travelSec + pause + 6.0; // 6s offscreen buffer between runs
    const localT = ((tSec + phase * cycleSec) % cycleSec + cycleSec) % cycleSec;
    if (localT > travelSec + pause) return -1;

    if (!stopFrac || pause <= 0) {
      return localT / travelSec;
    }
    const tStop = stopFrac * travelSec;
    const decelWin = Math.min(5.0, tStop * 0.35);
    const accelWin = Math.min(5.0, (travelSec - tStop) * 0.35);

    if (localT < tStop - decelWin) {
      return localT / travelSec;
    }
    if (localT < tStop) {
      // Smooth deceleration into station/pier
      const u = (localT - (tStop - decelWin)) / decelWin;
      const eased = u - 0.5 * u * u; // derivative goes 1 -> 0, integral = 0.5
      return (tStop - decelWin + eased * decelWin * 2.0 * 0.5) / travelSec + ((1 - u) * 0) ;
    }
    if (localT <= tStop + pause) {
      return stopFrac - (0.5 * decelWin) / travelSec;
    }
    const afterT = localT - pause;
    if (afterT < tStop + accelWin) {
      const u = (afterT - tStop) / accelWin;
      const s0 = stopFrac - (0.5 * decelWin) / travelSec;
      const s1 = (tStop + accelWin) / travelSec;
      return s0 + (s1 - s0) * (u * u * (3 - 2 * u));
    }
    return afterT / travelSec;
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
    return { wx, wy, tx: dx, ty: dy, occ };
  }

  function blitWorldSprite(sp, wx, wy, wScale) {
    const drawScale = scale * wScale;
    const sx = Math.round(offsetX + (wx - sp.cx * wScale) * scale);
    const sy = Math.round(offsetY + (wy - sp.cy * wScale) * scale);
    const sw = Math.max(2, Math.round(sp.canvas.width * drawScale));
    const sh = Math.max(2, Math.round(sp.canvas.height * drawScale));
    if (sx + sw < -20 || sx > canvas.width + 20 || sy + sh < -20 || sy > canvas.height + 20) return;
    ctx.imageSmoothingEnabled = drawScale < 0.65;
    ctx.drawImage(sp.canvas, sx, sy, sw, sh);
  }

  function drawPixelRectWorld(wx, wy, pw, ph, fillStyle, wScale) {
    const sx = Math.round(offsetX + wx * scale);
    const sy = Math.round(offsetY + wy * scale);
    if (sx < -20 || sx > canvas.width + 20 || sy < -20 || sy > canvas.height + 20) return;
    const sw = Math.max(1, Math.round(pw * wScale * scale));
    const sh = Math.max(1, Math.round(ph * wScale * scale));
    ctx.fillStyle = fillStyle;
    ctx.fillRect(sx, sy, sw, sh);
  }

  // ---- CONTINUOUS 3D NW-SUN SHADED VEHICLE RENDERER (Trains, ZVV Buses, Cars) ----
  // Renders crisp, grounded, smoothly curving 3D isometric vehicles directly in screen space
  // with NW directional sun shading (matching diorama lighting) & ZERO discrete angle snapping!
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

  function fillPoly(pts, fill, stroke = null, lw = 1) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lw;
      ctx.stroke();
    }
  }

  function draw3DCar(pos, colorIdx, wScale, mode) {
    const b = makeScreenIsoBasis(pos.wx, pos.wy, pos.tx, pos.ty, wScale);
    if (b.cx < -40 || b.cx > canvas.width + 40 || b.cy < -40 || b.cy > canvas.height + 40) return;

    // Distinct, readable Swiss car palette (clearly pops against cool grey asphalt!)
    const palette = ['#d63830', '#f4f6f9', '#2b6cb0', '#e6a825', '#2f855a', '#c9d2dc', '#805ad5', '#dd6b20'];
    const baseHex = palette[colorIdx % palette.length];
    const isNight = mode === 'night';

    // Crisp 1:1 miniature scale — unmistakably readable while staying cleanly inside village lanes
    const hl = 9.2;  // half-length
    const hw = 4.2;  // half-width
    const zBot = 1.2;
    const zBelt = 4.4;
    const zRoof = 7.2;

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

    // Side body wall + cabin greenhouse side
    const sideShade = b.dirShade(0, sideSign);
    fillPoly([
      b.proj(-hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBot),
      b.proj(hl, sideSign * hw, zBelt),
      b.proj(-hl, sideSign * hw, zBelt),
    ], shadeHex(baseHex, sideShade * 0.92, mode), outlineCol, lw);

    // Side dark tinted windows
    fillPoly([
      b.proj(-hl * 0.56, sideSign * hw * 0.92, zBelt),
      b.proj(hl * 0.46, sideSign * hw * 0.92, zBelt),
      b.proj(hl * 0.26, sideSign * hw * 0.82, zRoof),
      b.proj(-hl * 0.42, sideSign * hw * 0.82, zRoof),
    ], isNight ? '#334d6e' : '#26384c', outlineCol, lw * 0.8);

    // Visible front or rear bumper face
    const endShade = b.dirShade(endSign, 0);
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

    // Windshield & rear glass
    fillPoly([
      b.proj(hl * 0.54, -hw * 0.84, zBelt + 0.1),
      b.proj(hl * 0.54, hw * 0.84, zBelt + 0.1),
      b.proj(hl * 0.28, hw * 0.78, zRoof),
      b.proj(hl * 0.28, -hw * 0.78, zRoof),
    ], isNight ? '#446387' : '#354f68');

    // Sunlit top roof panel
    fillPoly([
      b.proj(-hl * 0.44, -hw * 0.78, zRoof),
      b.proj(hl * 0.28, -hw * 0.78, zRoof),
      b.proj(hl * 0.28, hw * 0.78, zRoof),
      b.proj(-hl * 0.44, hw * 0.78, zRoof),
    ], shadeHex(baseHex, 1.15, mode), outlineCol, lw * 0.8);

    // Headlights (warm beams at night!) & red taillights
    const hl1 = b.proj(hl + 0.3, -hw * 0.62, zBot + 1.6);
    const hl2 = b.proj(hl + 0.3, hw * 0.62, zBot + 1.6);
    const tl1 = b.proj(-hl - 0.3, -hw * 0.62, zBot + 1.8);
    const tl2 = b.proj(-hl - 0.3, hw * 0.62, zBot + 1.8);
    const rDot = Math.max(1.2, 1.6 * b.s);
    if (isNight) {
      // Soft glowing headlight cone on road
      fillPoly([
        hl1, hl2,
        b.proj(hl + 22, hw * 2.2, 0.2),
        b.proj(hl + 22, -hw * 2.2, 0.2),
      ], 'rgba(255,244,186,0.22)');
    }
    ctx.fillStyle = isNight ? '#fff8c8' : '#fffbe0';
    ctx.fillRect(hl1[0] - rDot * 0.5, hl1[1] - rDot * 0.5, rDot, rDot);
    ctx.fillRect(hl2[0] - rDot * 0.5, hl2[1] - rDot * 0.5, rDot, rDot);
    ctx.fillStyle = isNight ? '#ff3b30' : '#d62828';
    ctx.fillRect(tl1[0] - rDot * 0.5, tl1[1] - rDot * 0.5, rDot, rDot);
    ctx.fillRect(tl2[0] - rDot * 0.5, tl2[1] - rDot * 0.5, rDot, rDot);
  }

  function draw3DBus(pos, wScale, mode) {
    // Iconic Zurich ZVV / VBZ blue-and-white bus (Lines 161 & 165 through Kilchberg!)
    const b = makeScreenIsoBasis(pos.wx, pos.wy, pos.tx, pos.ty, wScale);
    if (b.cx < -60 || b.cx > canvas.width + 60 || b.cy < -60 || b.cy > canvas.height + 60) return;

    const isNight = mode === 'night';
    const hl = 22.0; // ~12 m ZVV city bus
    const hw = 6.0;
    const zBot = 1.4;
    const zBlue = 5.4;
    const zWinBot = 6.2;
    const zWinTop = 10.6;
    const zRoof = 12.2;

    // Grounded SE shadow
    const shOff = [3.6 * b.s, 2.8 * b.s];
    fillPoly([
      b.proj(hl + 1.5, -hw - 1.0, 0),
      b.proj(hl + 1.5, hw + 1.0, 0),
      b.proj(-hl - 1.5, hw + 1.0, 0),
      b.proj(-hl - 1.5, -hw - 1.0, 0),
    ].map(([x, y]) => [x + shOff[0], y + shOff[1]]), isNight ? 'rgba(6,10,20,0.65)' : 'rgba(18,24,32,0.46)');

    const sideSign = b.ry >= 0 ? 1 : -1;
    const frontVis = b.ty >= 0;
    const endSign = frontVis ? 1 : -1;
    const outlineCol = isNight ? 'rgba(10,16,28,0.88)' : 'rgba(24,30,40,0.78)';
    const lw = Math.max(0.8, Math.min(1.5, b.s * 0.5));

    // Side wall: ZVV Cobalt Blue lower skirt + Crisp White upper body + Continuous dark/lit windows
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

    // Side window ribbon with crisp vertical pillars
    fillPoly([
      b.proj(-hl + 1.8, sideSign * (hw + 0.05), zWinBot),
      b.proj(hl - 1.4, sideSign * (hw + 0.05), zWinBot),
      b.proj(hl - 1.4, sideSign * (hw + 0.05), zWinTop),
      b.proj(-hl + 1.8, sideSign * (hw + 0.05), zWinTop),
    ], isNight ? '#ffd978' : '#243a52');

    // End face (front windshield or rear panel)
    const endShade = b.dirShade(endSign, 0);
    fillPoly([
      b.proj(endSign * hl, -hw, zBot),
      b.proj(endSign * hl, hw, zBot),
      b.proj(endSign * hl, hw, zBlue),
      b.proj(endSign * hl, -hw, zBlue),
    ], shadeHex('#0d5ea6', endShade, mode), outlineCol, lw);
    fillPoly([
      b.proj(endSign * hl, -hw, zBlue),
      b.proj(endSign * hl, hw, zBlue),
      b.proj(endSign * hl, hw, zRoof),
      b.proj(endSign * hl, -hw, zRoof),
    ], shadeHex('#f2f5f8', endShade, mode), outlineCol, lw);

    if (frontVis) {
      fillPoly([
        b.proj(hl + 0.06, -hw * 0.85, zWinBot - 0.4),
        b.proj(hl + 0.06, hw * 0.85, zWinBot - 0.4),
        b.proj(hl + 0.06, hw * 0.85, zWinTop + 0.4),
        b.proj(hl + 0.06, -hw * 0.85, zWinTop + 0.4),
      ], isNight ? '#58789c' : '#243a52');
    }

    // Crisp sunlit white roof with rooftop HVAC pod + ZVV blue accent stripe
    fillPoly([
      b.proj(-hl, -hw, zRoof),
      b.proj(hl, -hw, zRoof),
      b.proj(hl, hw, zRoof),
      b.proj(-hl, hw, zRoof),
    ], shadeHex('#ffffff', 1.05, mode), outlineCol, lw);

    // Rooftop AC unit (adds unmistakable 3D miniature detail!)
    fillPoly([
      b.proj(-7.5, -hw * 0.58, zRoof + 1.4),
      b.proj(6.5, -hw * 0.58, zRoof + 1.4),
      b.proj(6.5, hw * 0.58, zRoof + 1.4),
      b.proj(-7.5, hw * 0.58, zRoof + 1.4),
    ], shadeHex('#cfd7e0', 1.0, mode), outlineCol, lw * 0.7);

    // Headlight glow at night
    if (isNight) {
      fillPoly([
        b.proj(hl, -hw * 0.7, zBot + 1.5),
        b.proj(hl, hw * 0.7, zBot + 1.5),
        b.proj(hl + 30, hw * 2.6, 0.2),
        b.proj(hl + 30, -hw * 2.6, 0.2),
      ], 'rgba(255,244,186,0.25)');
    }
  }

  function draw3DTrainUnit(pos, kind, variant, wScale, mode, nextPos) {
    // Museum-grade continuous 3D SBB RABe 511 KISS Double-Decker & SBB Re 460 IC
    // Rounded 3-facet sunlit roof, directional NW-sun walls, double-deck tinted windows,
    // red SBB doors, overhead pantograph, and articulated dark rubber gangway bellows!
    const b = makeScreenIsoBasis(pos.wx, pos.wy, pos.tx, pos.ty, wScale);
    if (b.cx < -120 || b.cx > canvas.width + 120 || b.cy < -120 || b.cy > canvas.height + 120) return;

    const isNight = mode === 'night';
    const isKISS = kind === 'sbb_kiss';
    const isLead = variant === 0;
    const isTail = variant === 2;

    const hl = 34.5; // ~17.5 m coach body (pairs with 19.5 m pitch for 2 m articulated gangway!)
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
      b.proj(hl + 2.0, -hw - 1.2, 0),
      b.proj(hl + 2.0, hw + 1.2, 0),
      b.proj(-hl - 2.0, hw + 1.2, 0),
      b.proj(-hl - 2.0, -hw - 1.2, 0),
    ].map(([x, y]) => [x + shOff[0], y + shOff[1]]), isNight ? 'rgba(6,10,20,0.68)' : 'rgba(20,24,32,0.48)');

    // 2. Articulated dark rubber gangway bellows connecting directly to next coach!
    if (nextPos) {
      const bNext = makeScreenIsoBasis(nextPos.wx, nextPos.wy, nextPos.tx, nextPos.ty, wScale);
      const gw = hw * 0.72;
      fillPoly([
        b.proj(-hl + 1.0, sideSign * gw, zSkirt),
        bNext.proj(hl - 1.0, sideSign * gw, zSkirt),
        bNext.proj(hl - 1.0, sideSign * gw, zEave - 0.6),
        b.proj(-hl + 1.0, sideSign * gw, zEave - 0.6),
      ], shadeHex('#2c323b', 0.85, mode), outlineCol, lw * 0.8);
      fillPoly([
        b.proj(-hl + 1.0, -gw, zEave - 0.6),
        bNext.proj(hl - 1.0, -gw, zEave - 0.6),
        bNext.proj(hl - 1.0, gw, zEave - 0.6),
        b.proj(-hl + 1.0, gw, zEave - 0.6),
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
    if (isKISS) {
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
      for (const dPos of [-20.5, 16.5]) {
        fillPoly([
          b.proj(dPos, sideSign * (hw + 0.12), zSkirt),
          b.proj(dPos + 4.2, sideSign * (hw + 0.12), zSkirt),
          b.proj(dPos + 4.2, sideSign * (hw + 0.12), zSkirt + 5.2),
          b.proj(dPos, sideSign * (hw + 0.12), zSkirt + 5.2),
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
      for (const dPos of [-30.0, 26.0]) {
        fillPoly([
          b.proj(dPos, sideSign * (hw + 0.12), zSkirt),
          b.proj(dPos + 4.0, sideSign * (hw + 0.12), zSkirt),
          b.proj(dPos + 4.0, sideSign * (hw + 0.12), zEave - 1.8),
          b.proj(dPos, sideSign * (hw + 0.12), zEave - 1.8),
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
    // Left roof bevel
    fillPoly([
      b.proj(tailL, -hw, zEave),
      b.proj(noseL, -hw, zEave),
      b.proj(noseL - 0.8, -rw, zCrown),
      b.proj(tailL + 0.8, -rw, zCrown),
    ], shadeHex('#d4dce5', nwBevelShade, mode));
    // Right roof bevel
    fillPoly([
      b.proj(tailL, hw, zEave),
      b.proj(noseL, hw, zEave),
      b.proj(noseL - 0.8, rw, zCrown),
      b.proj(tailL + 0.8, rw, zCrown),
    ], shadeHex('#c4ceda', seBevelShade, mode));
    // Sunlit top roof crown (always the brightest surface on the train -> true 3D volume!)
    fillPoly([
      b.proj(tailL + 0.8, -rw, zCrown),
      b.proj(noseL - 0.8, -rw, zCrown),
      b.proj(noseL - 0.8, rw, zCrown),
      b.proj(tailL + 0.8, rw, zCrown),
    ], shadeHex('#e8eef5', 1.06, mode), outlineCol, lw * 0.75);

    // Rooftop HVAC pods & pantograph on lead/mid coaches
    for (const podL of [-14, 10]) {
      fillPoly([
        b.proj(podL - 4.5, -rw * 0.72, zCrown + 1.1),
        b.proj(podL + 4.5, -rw * 0.72, zCrown + 1.1),
        b.proj(podL + 4.5, rw * 0.72, zCrown + 1.1),
        b.proj(podL - 4.5, rw * 0.72, zCrown + 1.1),
      ], shadeHex('#bcc6d2', 0.98, mode), outlineCol, lw * 0.6);
    }
    if (isLead) {
      // Crisp overhead pantograph bar
      const p0 = b.proj(-22, -rw * 0.9, zCrown + 3.4);
      const p1 = b.proj(-22, rw * 0.9, zCrown + 3.4);
      ctx.strokeStyle = isNight ? '#96a8c0' : '#4a5462';
      ctx.lineWidth = Math.max(1.0, b.s * 0.7);
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]);
      ctx.lineTo(p1[0], p1[1]);
      ctx.stroke();

      // Swiss triple-headlight glow at night
      if (isNight) {
        fillPoly([
          b.proj(hl, -hw * 0.75, zSkirt + 2.0),
          b.proj(hl, hw * 0.75, zSkirt + 2.0),
          b.proj(hl + 52, hw * 3.4, 0.2),
          b.proj(hl + 52, -hw * 3.4, 0.2),
        ], 'rgba(255,244,186,0.28)');
      }
    }
  }

  function drawAnimations(worldW, worldH, tSec) {
    const wScale = worldW / (animData.canvas_width || 12331);
    const isNight = currentMode === 'night';
    const isSunset = currentMode === 'sunset';

    // 1. Subtle Lake Zurich Pixel Water Glints
    if (animData.ambient && animData.ambient.lake_glints) {
      const glintCol = isNight ? 'rgba(156,188,236,0.55)' : (isSunset ? 'rgba(255,204,132,0.68)' : 'rgba(226,244,252,0.65)');
      for (let i = 0; i < animData.ambient.lake_glints.length; i++) {
        const g = animData.ambient.lake_glints[i];
        const wave = Math.sin(tSec * 2.1 + g[2] * 31.4);
        if (wave > 0.72) {
          const wx = Math.round(g[0] * worldW);
          const wy = Math.round(g[1] * worldH);
          const wPx = wave > 0.90 ? 4 : 2;
          drawPixelRectWorld(wx, wy, wPx, 1.4, glintCol, wScale);
        }
      }
    }

    // 2. Lake Zurich ZSG Steamer & Sailboats (with crisp pixel V-wakes!)
    for (const ship of (animData.ships || [])) {
      let frac;
      if (ship.closed) {
        const cyc = ship.length_m / Math.max(0.5, ship.speed_mps);
        frac = (((tSec / cyc) + (ship.phase || 0)) % 1 + 1) % 1;
      } else {
        frac = evalWithStationStop(tSec, ship.length_m, ship.speed_mps, ship.stop_frac, ship.dwell_sec, ship.phase || 0);
      }
      if (frac < 0 || frac > 1) continue;
      const pos = samplePathAt(ship.pts, frac, worldW, worldH, 3);
      if (!pos) continue;

      // Pixel water wake ripples behind moving vessels
      const wakeCount = ship.kind === 'zsg_steamer' ? 6 : 3;
      const wakeColor = isNight ? 'rgba(130,168,210,0.38)' : 'rgba(224,242,246,0.52)';
      for (let k = 1; k <= wakeCount; k++) {
        const fWake = ship.closed
          ? ((frac - k * 0.012) % 1 + 1) % 1
          : frac - k * 0.008;
        if (fWake <= 0 || fWake >= 1) continue;
        const pw = samplePathAt(ship.pts, fWake, worldW, worldH, 3);
        if (!pw) continue;
        const spread = (ship.kind === 'zsg_steamer' ? 9 : 4) + k * 3.2;
        const nx = -pw.ty * spread * wScale;
        const ny = pw.tx * spread * 0.55 * wScale;
        drawPixelRectWorld(pw.wx + nx, pw.wy + ny, 3, 2, wakeColor, wScale);
        drawPixelRectWorld(pw.wx - nx, pw.wy - ny, 3, 2, wakeColor, wScale);
      }

      const angIdx = ((Math.round((Math.atan2(pos.ty, pos.tx) / (Math.PI * 2)) * 32) % 32) + 32) % 32;
      const sp = getVehicleSprite(ship.kind, 0, angIdx, currentMode);
      blitWorldSprite(sp, pos.wx, pos.wy, wScale);
    }

    // 3. Road Cars & ZVV Lakefront/Viaduct Buses (continuous 3D shaded & sorted back-to-front!)
    const roadDrawList = [];
    for (let rIdx = 0; rIdx < (animData.roads || []).length; rIdx++) {
      const rd = animData.roads[rIdx];
      const cyc = rd.length_m / Math.max(1.0, rd.speed_mps);
      const busCount = rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0);
      const carCount = rd.car_count || 3;
      const totalVehicles = carCount + busCount;
      for (let vIdx = 0; vIdx < totalVehicles; vIdx++) {
        const isBus = vIdx < busCount;
        const vSpeedMul = isBus ? 0.84 : (0.93 + ((vIdx * 7 + rIdx * 3) % 5) * 0.04);
        const frac = ((((tSec * vSpeedMul) / cyc) + (rd.phase || 0) + vIdx / totalVehicles) % 1 + 1) % 1;
        if (frac < 0.012 || frac > 0.988) continue;
        const pos = samplePathAt(rd.pts, frac, worldW, worldH, 3);
        if (!pos || pos.occ) continue;
        roadDrawList.push({ isBus, pos, colorIdx: vIdx + rIdx * 3 });
      }
    }
    roadDrawList.sort((a, b) => a.pos.wy - b.pos.wy);
    for (const v of roadDrawList) {
      if (v.isBus) {
        draw3DBus(v.pos, wScale, currentMode);
      } else {
        draw3DCar(v.pos, v.colorIdx, wScale, currentMode);
      }
    }

    // 4. SBB Seebahn Multi-Carriage Trains (continuous 3D shaded, smoothly curving, articulated!)
    for (const tr of (animData.trains || [])) {
      const headFrac = evalWithStationStop(tSec, tr.length_m, tr.speed_mps, tr.stop_frac, tr.dwell_sec, tr.phase || 0);
      if (headFrac < 0 || headFrac > 1.08) continue;
      const coachStepFrac = 19.5 / tr.length_m;
      const nCars = tr.carriages || 4;
      const units = [];
      for (let cIdx = 0; cIdx < nCars; cIdx++) {
        const cFrac = headFrac - cIdx * coachStepFrac;
        if (cFrac < 0.005 || cFrac > 0.995) continue;
        // Wide-chord tangent (tanWin=6) guarantees every coach follows the exact same smooth curve!
        const pos = samplePathAt(tr.pts, cFrac, worldW, worldH, 6);
        if (pos && !pos.occ) {
          const variant = cIdx === 0 ? 0 : (cIdx === nCars - 1 ? 2 : 1);
          const nextFrac = headFrac - (cIdx + 1) * coachStepFrac;
          const nextPos = (cIdx < nCars - 1 && nextFrac > 0.005 && nextFrac < 0.995)
            ? samplePathAt(tr.pts, nextFrac, worldW, worldH, 6)
            : null;
          units.push({ cIdx, variant, pos, nextPos: (nextPos && !nextPos.occ) ? nextPos : null });
        }
      }
      units.sort((a, b) => a.pos.wy - b.pos.wy);
      for (const u of units) {
        draw3DTrainUnit(u.pos, tr.kind, u.variant, wScale, currentMode, u.nextPos);
      }
    }

    // 5. Waving Swiss Flags, Lindt 43.6 m Hochkamin Rising Pixel Steam & Gliding Lake Zurich Gulls
    if (animData.ambient) {
      const waveStep = Math.floor(tSec * 5.0) % 4;
      for (let fIdx = 0; fIdx < (animData.ambient.swiss_flags || []).length; fIdx++) {
        const fl = animData.ambient.swiss_flags[fIdx];
        const fx = fl.uv[0] * worldW;
        const fy = fl.uv[1] * worldH;
        const fPhase = (waveStep + fIdx) % 4;
        // Thin silver flagpole
        drawPixelRectWorld(fx, fy - 14 * wScale, 1.5, 15, isNight ? '#8a99b2' : '#d8dce2', wScale);
        // 3 waving segments of red Swiss flag + white cross
        const segY0 = fy - 14 * wScale;
        const dy1 = (fPhase === 1 ? -1 : (fPhase === 3 ? 1 : 0)) * wScale;
        const dy2 = (fPhase === 2 ? -1 : (fPhase === 0 ? 1 : 0)) * wScale;
        const redFlag = isNight ? '#9e2828' : '#d62c28';
        const whiteCross = isNight ? '#cfd6e2' : '#f8f6f0';
        drawPixelRectWorld(fx + 1.5 * wScale, segY0, 3, 6, redFlag, wScale);
        drawPixelRectWorld(fx + 4.2 * wScale, segY0 + dy1, 3.2, 6, redFlag, wScale);
        drawPixelRectWorld(fx + 7.2 * wScale, segY0 + dy2, 2.8, 6, redFlag, wScale);
        drawPixelRectWorld(fx + 4.6 * wScale, segY0 + dy1 + 1.2 * wScale, 1.4, 3.6, whiteCross, wScale);
        drawPixelRectWorld(fx + 3.4 * wScale, segY0 + dy1 + 2.3 * wScale, 3.8, 1.4, whiteCross, wScale);
      }

      if (animData.ambient.chimney_steam) {
        const stUv = animData.ambient.chimney_steam.uv;
        const cxWorld = stUv[0] * worldW;
        const cyWorld = stUv[1] * worldH;
        for (let p = 0; p < 7; p++) {
          const age = ((tSec * 0.34 + p / 7) % 1);
          const pxWorld = Math.round(cxWorld - age * 26 * wScale + Math.sin(age * 7.0 + p) * 2.5 * wScale);
          const pyWorld = Math.round(cyWorld - (3 + age * 38) * wScale);
          const alpha = (1 - age) * (age < 0.15 ? age / 0.15 : 0.62);
          const sz = 2.5 + age * 6.5;
          const puffCol = isNight
            ? `rgba(148,164,196,${(alpha * 0.55).toFixed(2)})`
            : (isSunset ? `rgba(248,214,196,${(alpha * 0.72).toFixed(2)})` : `rgba(242,240,236,${(alpha * 0.72).toFixed(2)})`);
          drawPixelRectWorld(pxWorld - sz * 0.5 * wScale, pyWorld - sz * 0.4 * wScale, sz, sz * 0.75, puffCol, wScale);
        }
      }

      // Gliding Lake Zurich Gulls over Bendlikon Bay & Schooren (day & alpenglow)
      if (!isNight && animData.ambient.gulls) {
        const gullCol = isSunset ? '#ffe6cf' : '#f4f6fa';
        const tipCol = isSunset ? '#b49284' : '#8a94a6';
        for (let gIdx = 0; gIdx < animData.ambient.gulls.length; gIdx++) {
          const g = animData.ambient.gulls[gIdx];
          const ang = tSec * (g.speed || 0.25) + (g.phase || 0) * Math.PI * 2;
          const gx = (g.cx + Math.cos(ang) * g.rx) * worldW;
          const gy = (g.cy + Math.sin(ang) * g.ry) * worldH;
          const flap = Math.sin(tSec * 7.5 + gIdx * 1.9);
          const wy = (flap > 0.25 ? -1.4 : (flap < -0.25 ? 1.2 : 0)) * wScale;
          // Crisp 5px pixel V-wing gull
          drawPixelRectWorld(gx - 3.0 * wScale, gy + wy, 1.5, 1.2, tipCol, wScale);
          drawPixelRectWorld(gx - 1.6 * wScale, gy + wy * 0.4, 1.8, 1.2, gullCol, wScale);
          drawPixelRectWorld(gx, gy, 1.6, 1.4, gullCol, wScale);
          drawPixelRectWorld(gx + 1.6 * wScale, gy + wy * 0.4, 1.8, 1.2, gullCol, wScale);
          drawPixelRectWorld(gx + 3.0 * wScale, gy + wy, 1.5, 1.2, tipCol, wScale);
        }
      }
    }
  }

  let lastAnimPaint = 0;
  function animLoop(nowMs) {
    if (showAnimations && animData && !document.hidden) {
      if (nowMs - lastAnimPaint >= 33 && !drawScheduled) {
        lastAnimPaint = nowMs;
        draw();
      }
      requestAnimationFrame(animLoop);
    }
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

  document.addEventListener('visibilitychange', () => {
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

  const urlParams = new URLSearchParams(window.location.search);
  const fixedAnimTime = urlParams.has('t') && !Number.isNaN(parseFloat(urlParams.get('t')))
    ? parseFloat(urlParams.get('t'))
    : null;
  if (urlParams.get('pins') === '0') {
    showPins = false;
    const btnPins = document.getElementById('btn-toggle-pins');
    if (btnPins) btnPins.classList.remove('active');
  }
  const initMode = ['day', 'sunset', 'night'].includes(urlParams.get('mode')) ? urlParams.get('mode') : 'day';
  if (initMode !== 'day') {
    currentMode = initMode;
    document.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === currentMode));
  }

  // Boot
  Promise.all([
    loadModeOverview(currentMode),
    loadTileManifest(currentMode),
    fetch(`data/kilchberg_interactive.json?v=${ASSET_VER}`).then((r) => r.json()).catch(() => null),
    fetch(`data/kilchberg_animations.json?v=${ASSET_VER}`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]).then(([_, __, loadedMeta, loadedAnim]) => {
    meta = loadedMeta;
    animData = loadedAnim;
    populateSidebar();
    resizeViewport();
    const qZoom = parseFloat(urlParams.get('zoom'));
    const qU = parseFloat(urlParams.get('u'));
    const qV = parseFloat(urlParams.get('v'));
    if (!Number.isNaN(qZoom) && qZoom > 0) {
      const { width, height } = getWorldSize();
      const cu = !Number.isNaN(qU) ? qU : 0.5;
      const cv = !Number.isNaN(qV) ? qV : 0.5;
      scale = qZoom;
      offsetX = canvas.width * 0.5 - cu * width * scale;
      offsetY = canvas.height * 0.5 - cv * height * scale;
      updateZoomReadout();
      draw();
    } else {
      fitToScreen();
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
})();
