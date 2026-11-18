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
    { file: '04_bahnhof_kilchberg_weinberg.webp', label: 'Bahnhof & Vineyards', lmId: 'bahnhof_stockengut' },
    { file: '05_schooren_seebad.webp', label: 'Schooren & Seebad', lmId: 'schooren_seebad' },
    { file: '06_sanatorium_ridge.webp', label: 'Sanatorium Kilchberg', lmId: 'sanatorium_ridge' },
  ];

  const ASSET_VER = '2.5';

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

    // 1. Always draw fast overview image underneath (zero blank flashes while streaming HD tiles)
    if (ov) {
      const ovRatio = width / ov.width;
      ctx.imageSmoothingEnabled = (scale * ovRatio) < 0.92;
      ctx.drawImage(ov, destX, destY, destW, destH);
    }

    // 2. Stream ultra-crisp 0.25 m/px lossless WebP tiles whenever zoomed past overview density!
    let tilesLoaded = 0;
    let tilesVisible = 0;
    const ovWidth = ov ? ov.width : 0;
    const needTiles = tiled && mf && (!ov || (width * scale) > ovWidth * 0.92);

    if (needTiles) {
      const ts = mf.tileSize;
      const c0 = Math.max(0, Math.floor((-offsetX / scale) / ts));
      const c1 = Math.min(mf.cols - 1, Math.floor(((canvas.width - offsetX) / scale) / ts));
      const r0 = Math.max(0, Math.floor((-offsetY / scale) / ts));
      const r1 = Math.min(mf.rows - 1, Math.floor(((canvas.height - offsetY) / scale) / ts));

      ctx.imageSmoothingEnabled = scale < 0.92;
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
      drawAnimations(width, height, performance.now() * 0.001);
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

  function drawIsoBox(buf, cx, cy, tx, ty, halfLen, halfWid, heightPx, zBase, colors, drawShadow = true) {
    // Isometric ground cross-axis compressed vertically by sin(30°)=0.55
    const nx = -ty * 0.72;
    const ny = tx * 0.52;
    const pt = (s, w, z) => [
      cx + tx * s + nx * w,
      cy + ty * s + ny * w - z,
    ];

    if (drawShadow) {
      fillPolyPx(buf, [
        pt(-halfLen - 1, -halfWid - 1, -1),
        pt(halfLen + 1, -halfWid - 1, -1),
        pt(halfLen + 1, halfWid + 1, -1),
        pt(-halfLen - 1, halfWid + 1, -1),
      ], [16, 20, 28], 110);
    }

    const z0 = zBase;
    const z1 = zBase + heightPx;
    // Determine which side & end faces point toward the viewer (+Y on screen)
    const visSide = ny >= 0 ? 1 : -1;
    const visEnd = ty >= 0 ? 1 : -1;

    // Side wall
    fillPolyPx(buf, [
      pt(-halfLen, visSide * halfWid, z0),
      pt(halfLen, visSide * halfWid, z0),
      pt(halfLen, visSide * halfWid, z1),
      pt(-halfLen, visSide * halfWid, z1),
    ], colors.side, colors.emissive ? 254 : 255);

    // Front or rear end wall
    fillPolyPx(buf, [
      pt(visEnd * halfLen, -halfWid, z0),
      pt(visEnd * halfLen, halfWid, z0),
      pt(visEnd * halfLen, halfWid, z1),
      pt(visEnd * halfLen, -halfWid, z1),
    ], colors.front, colors.emissive ? 254 : 255);

    // Roof
    fillPolyPx(buf, [
      pt(-halfLen, -halfWid, z1),
      pt(halfLen, -halfWid, z1),
      pt(halfLen, halfWid, z1),
      pt(-halfLen, halfWid, z1),
    ], colors.roof, colors.emissive ? 254 : 255);

    return { pt, visSide, visEnd };
  }

  function getVehicleSprite(type, variant, angleIdx, mode) {
    const key = `${type}:${variant}:${angleIdx}:${mode}`;
    if (spriteCache[key]) return spriteCache[key];

    const ang = (angleIdx / 32) * Math.PI * 2;
    const tx = Math.cos(ang);
    const ty = Math.sin(ang);
    const isNight = mode === 'night';
    const winCol = isNight ? [255, 218, 118] : [48, 66, 90];
    const winAlpha = isNight ? 254 : 255;

    let buf;
    if (type === 'car') {
      buf = createPixelBuffer(34, 30);
      const cx = 17, cy = 17;
      const pal = CAR_PALETTES[variant % CAR_PALETTES.length];
      const lower = drawIsoBox(buf, cx, cy, tx, ty, 8.5, 4.0, 3.5, 0, pal, true);
      drawIsoBox(buf, cx - tx * 0.8, cy - ty * 0.8, tx, ty, 4.6, 3.4, 3.0, 3.5, {
        roof: pal.roof,
        side: winCol,
        front: winCol,
        emissive: isNight,
      }, false);
      // Headlights & taillights
      const hlL = lower.pt(8.8, -2.4, 2.0);
      const hlR = lower.pt(8.8, 2.4, 2.0);
      setPx(buf, hlL[0], hlL[1], [255, 244, 188], 254);
      setPx(buf, hlR[0], hlR[1], [255, 244, 188], 254);
      const tlL = lower.pt(-8.8, -2.4, 2.0);
      const tlR = lower.pt(-8.8, 2.4, 2.0);
      setPx(buf, tlL[0], tlL[1], [232, 48, 42], 254);
      setPx(buf, tlR[0], tlR[1], [232, 48, 42], 254);
      applySelOutAndShade(buf, mode);
      spriteCache[key] = { canvas: buf.c, cx, cy };
      return spriteCache[key];
    }

    if (type === 'bus') {
      buf = createPixelBuffer(64, 52);
      const cx = 32, cy = 29;
      // ZVV white & cobalt-blue lakefront bus
      drawIsoBox(buf, cx, cy, tx, ty, 21.0, 4.8, 4.2, 0, {
        roof: [46, 98, 178], side: [38, 84, 158], front: [44, 92, 168],
      }, true);
      const upper = drawIsoBox(buf, cx, cy, tx, ty, 21.0, 4.8, 6.4, 4.2, {
        roof: [232, 234, 236], side: [216, 218, 222], front: [224, 226, 230],
      }, false);
      // Passenger windows along visible side
      for (let s = -16; s <= 15; s += 5.2) {
        fillPolyPx(buf, [
          upper.pt(s - 1.8, upper.visSide * 4.9, 5.4),
          upper.pt(s + 1.8, upper.visSide * 4.9, 5.4),
          upper.pt(s + 1.8, upper.visSide * 4.9, 9.0),
          upper.pt(s - 1.8, upper.visSide * 4.9, 9.0),
        ], winCol, winAlpha);
      }
      const hl = upper.pt(21.3, 0, 2.5);
      setPx(buf, hl[0], hl[1], [255, 246, 192], 254);
      applySelOutAndShade(buf, mode);
      spriteCache[key] = { canvas: buf.c, cx, cy };
      return spriteCache[key];
    }

    if (type === 'sbb_dpz' || type === 'sbb_ic') {
      buf = createPixelBuffer(104, 84);
      const cx = 52, cy = 48;
      const isLoco = variant === 0;
      const isDpz = type === 'sbb_dpz';
      const baseColors = isLoco
        ? { roof: [76, 80, 88], side: [188, 44, 38], front: [204, 48, 42] }
        : (isDpz
          ? { roof: [78, 84, 94], side: [44, 78, 146], front: [208, 210, 214] }
          : { roof: [92, 96, 104], side: [222, 222, 218], front: [198, 200, 204] });

      const body = drawIsoBox(buf, cx, cy, tx, ty, 33.0, 5.4, 15.0, 0, baseColors, true);
      if (!isLoco) {
        // White horizontal stripe on DPZ or red doors on coaches
        const vs = body.visSide * 5.5;
        if (isDpz) {
          fillPolyPx(buf, [
            body.pt(-32, vs, 6.2), body.pt(32, vs, 6.2),
            body.pt(32, vs, 9.0), body.pt(-32, vs, 9.0),
          ], [228, 228, 224], 255);
        }
        // SBB red entry doors near bogies
        for (const ds of [-23.0, 23.0]) {
          fillPolyPx(buf, [
            body.pt(ds - 2.2, vs, 1.5), body.pt(ds + 2.2, vs, 1.5),
            body.pt(ds + 2.2, vs, 11.5), body.pt(ds - 2.2, vs, 11.5),
          ], [198, 46, 40], 255);
        }
        // Upper & lower deck pixel windows!
        const zRows = isDpz ? [[2.8, 5.6], [9.8, 13.0]] : [[6.8, 11.2]];
        for (const [za, zb] of zRows) {
          for (let s = -17.5; s <= 17.5; s += 5.0) {
            fillPolyPx(buf, [
              body.pt(s - 1.7, vs, za), body.pt(s + 1.7, vs, za),
              body.pt(s + 1.7, vs, zb), body.pt(s - 1.7, vs, zb),
            ], winCol, winAlpha);
          }
        }
      } else {
        // Locomotive cab windshield & twin Swiss headlights
        const hl1 = body.pt(33.4, -2.5, 4.0);
        const hl2 = body.pt(33.4, 2.5, 4.0);
        setPx(buf, hl1[0], hl1[1], [255, 248, 200], 254);
        setPx(buf, hl2[0], hl2[1], [255, 248, 200], 254);
        // Silver roof pantograph
        const p0 = body.pt(-10, 0, 15.5);
        const p1 = body.pt(-4, 0, 19.5);
        const p2 = body.pt(2, 0, 15.5);
        setPx(buf, p0[0], p0[1], [196, 202, 210], 255);
        setPx(buf, p1[0], p1[1], [216, 220, 228], 255);
        setPx(buf, p2[0], p2[1], [196, 202, 210], 255);
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

  function samplePathAt(pts, frac, worldW, worldH) {
    const n = pts.length;
    if (n < 2 || frac < 0 || frac > 1) return null;
    const fIdx = frac * (n - 1);
    const i0 = Math.min(n - 2, Math.max(0, Math.floor(fIdx)));
    const t = fIdx - i0;
    const p0 = pts[i0];
    const p1 = pts[i0 + 1];
    const wx = (p0[0] + (p1[0] - p0[0]) * t) * worldW;
    const wy = (p0[1] + (p1[1] - p0[1]) * t) * worldH;

    // Smooth tangent across +-2 samples
    const ia = Math.max(0, i0 - 2);
    const ib = Math.min(n - 1, i0 + 3);
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
      const pos = samplePathAt(ship.pts, frac, worldW, worldH);
      if (!pos) continue;

      // Pixel water wake ripples behind moving vessels
      const wakeCount = ship.kind === 'zsg_steamer' ? 6 : 3;
      const wakeColor = isNight ? 'rgba(130,168,210,0.38)' : 'rgba(224,242,246,0.52)';
      for (let k = 1; k <= wakeCount; k++) {
        const fWake = ship.closed
          ? ((frac - k * 0.012) % 1 + 1) % 1
          : frac - k * 0.008;
        if (fWake <= 0 || fWake >= 1) continue;
        const pw = samplePathAt(ship.pts, fWake, worldW, worldH);
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

    // 3. Road Cars & ZVV Lakefront Buses (respecting exact 3D foreground building/tree occlusion!)
    for (let rIdx = 0; rIdx < (animData.roads || []).length; rIdx++) {
      const rd = animData.roads[rIdx];
      const cyc = rd.length_m / Math.max(1.0, rd.speed_mps);
      const totalVehicles = (rd.car_count || 3) + (rd.has_bus ? 1 : 0);
      for (let vIdx = 0; vIdx < totalVehicles; vIdx++) {
        const isBus = rd.has_bus && vIdx === 0;
        const vSpeedMul = isBus ? 0.82 : (0.92 + ((vIdx * 7 + rIdx * 3) % 5) * 0.045);
        const frac = ((((tSec * vSpeedMul) / cyc) + (rd.phase || 0) + vIdx / totalVehicles) % 1 + 1) % 1;
        if (frac < 0.015 || frac > 0.985) continue;
        const pos = samplePathAt(rd.pts, frac, worldW, worldH);
        if (!pos || pos.occ) continue;
        const angIdx = ((Math.round((Math.atan2(pos.ty, pos.tx) / (Math.PI * 2)) * 32) % 32) + 32) % 32;
        const sp = isBus
          ? getVehicleSprite('bus', 0, angIdx, currentMode)
          : getVehicleSprite('car', vIdx + rIdx * 3, angIdx, currentMode);
        blitWorldSprite(sp, pos.wx, pos.wy, wScale);
      }
    }

    // 4. SBB Seebahn Multi-Carriage Trains (decelerating & dwelling at Bahnhof Kilchberg!)
    for (const tr of (animData.trains || [])) {
      const headFrac = evalWithStationStop(tSec, tr.length_m, tr.speed_mps, tr.stop_frac, tr.dwell_sec, tr.phase || 0);
      if (headFrac < 0 || headFrac > 1.08) continue;
      const coachStepFrac = 20.5 / tr.length_m; // 20.5 m per SBB coach + coupler
      const nCars = tr.carriages || 4;
      // Draw from rear coach to locomotive in back-to-front screen Y order
      const units = [];
      for (let cIdx = 0; cIdx < nCars; cIdx++) {
        const cFrac = headFrac - cIdx * coachStepFrac;
        if (cFrac < 0.005 || cFrac > 0.995) continue;
        const pos = samplePathAt(tr.pts, cFrac, worldW, worldH);
        if (pos && !pos.occ) {
          units.push({ cIdx, pos });
        }
      }
      units.sort((a, b) => a.pos.wy - b.pos.wy);
      for (const u of units) {
        const angIdx = ((Math.round((Math.atan2(u.pos.ty, u.pos.tx) / (Math.PI * 2)) * 32) % 32) + 32) % 32;
        const sp = getVehicleSprite(tr.kind, u.cIdx === 0 ? 0 : 1, angIdx, currentMode);
        blitWorldSprite(sp, u.pos.wx, u.pos.wy, wScale);
      }
    }

    // 5. Waving Swiss Flags & Lindt 43.6 m Hochkamin Rising Pixel Steam
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

  // Boot
  Promise.all([
    loadModeOverview('day'),
    loadTileManifest('day'),
    fetch(`data/kilchberg_interactive.json?v=${ASSET_VER}`).then((r) => r.json()).catch(() => null),
    fetch(`data/kilchberg_animations.json?v=${ASSET_VER}`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]).then(([_, __, loadedMeta, loadedAnim]) => {
    meta = loadedMeta;
    animData = loadedAnim;
    populateSidebar();
    resizeViewport();
    fitToScreen();
    if (showAnimations && animData) {
      requestAnimationFrame(animLoop);
    }
    // Preload sunset & night overviews + manifests
    loadModeOverview('sunset');
    loadTileManifest('sunset');
    loadModeOverview('night');
    loadTileManifest('night');
  });
})();
