(() => {
  const canvas = document.getElementById('diorama-canvas');
  const ctx = canvas.getContext('2d');
  const viewport = document.getElementById('viewport');
  const pinsLayer = document.getElementById('pins-layer');
  const loupeCanvas = document.getElementById('loupe-canvas');
  const loupeCtx = loupeCanvas.getContext('2d');

  const CROPS = [
    { file: '01_lindt_home_of_chocolate.webp', label: 'Lindt Home of Chocolate' },
    { file: '02_reformierte_kirche_dorf.webp', label: 'Reformierte Kirche & Graves' },
    { file: '03_bendlikon_harbor_pier.webp', label: 'Bendlikon Pier & Sailboats' },
    { file: '04_bahnhof_kilchberg_weinberg.webp', label: 'Bahnhof & Vineyards' },
    { file: '05_schooren_seebad.webp', label: 'Schooren & Seebad' },
    { file: '06_sanatorium_ridge.webp', label: 'Sanatorium Kilchberg' },
  ];

  const images = {};
  let currentMode = 'day';
  let meta = null;
  let scale = 0.35;
  let offsetX = 0;
  let offsetY = 0;
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let showPins = true;
  let showLoupe = false;
  let lastMouse = { x: 0, y: 0 };

  function loadModeImage(mode) {
    if (images[mode]) return Promise.resolve(images[mode]);
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        images[mode] = img;
        resolve(img);
      };
      img.src = `assets/diorama_${mode}.webp`;
    });
  }

  function resizeViewport() {
    const rect = viewport.getBoundingClientRect();
    canvas.width = Math.max(1, Math.floor(rect.width));
    canvas.height = Math.max(1, Math.floor(rect.height));
    draw();
  }

  function fitToScreen() {
    const img = images[currentMode];
    if (!img) return;
    const pad = 20;
    const sx = (canvas.width - pad * 2) / img.width;
    const sy = (canvas.height - pad * 2) / img.height;
    scale = Math.min(sx, sy);
    offsetX = Math.round((canvas.width - img.width * scale) * 0.5);
    offsetY = Math.round((canvas.height - img.height * scale) * 0.5);
    updateZoomReadout();
    draw();
  }

  function zoomAt(factor, cx, cy, exactScale = null) {
    const img = images[currentMode];
    if (!img) return;
    const prevScale = scale;
    scale = exactScale !== null ? exactScale : Math.min(8.0, Math.max(0.15, scale * factor));
    // Snap close to integer pixel multiples (1x, 2x, 3x, 4x) for razor-sharp pixel art!
    for (const intS of [1, 2, 3, 4, 6]) {
      if (Math.abs(scale - intS) < 0.06) scale = intS;
    }
    const wx = (cx - offsetX) / prevScale;
    const wy = (cy - offsetY) / prevScale;
    offsetX = Math.round(cx - wx * scale);
    offsetY = Math.round(cy - wy * scale);
    updateZoomReadout();
    draw();
  }

  function updateZoomReadout() {
    const el = document.getElementById('zoom-readout');
    el.textContent = scale >= 0.95 ? `${scale.toFixed(scale % 1 === 0 ? 0 : 1)}×` : `${Math.round(scale * 100)}%`;
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const img = images[currentMode];
    if (!img) return;
    ctx.imageSmoothingEnabled = scale < 0.85;
    ctx.drawImage(
      img,
      Math.round(offsetX),
      Math.round(offsetY),
      Math.round(img.width * scale),
      Math.round(img.height * scale)
    );
    updatePins(img);
    if (showLoupe) drawLoupe(img);
  }

  function updatePins(img) {
    if (!meta || !showPins) {
      pinsLayer.innerHTML = '';
      return;
    }
    if (pinsLayer.children.length !== meta.landmarks.length) {
      pinsLayer.innerHTML = '';
      meta.landmarks.forEach((lm, idx) => {
        const btn = document.createElement('button');
        btn.className = 'lm-pin';
        btn.textContent = `${idx + 1}. ${lm.name.split('&')[0].trim()}`;
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          flyToLandmark(lm);
        });
        pinsLayer.appendChild(btn);
      });
    }
    meta.landmarks.forEach((lm, idx) => {
      const pin = pinsLayer.children[idx];
      const sx = offsetX + lm.uv[0] * img.width * scale;
      const sy = offsetY + lm.uv[1] * img.height * scale;
      pin.style.left = `${sx}px`;
      pin.style.top = `${sy}px`;
      pin.style.display = (sx < -80 || sx > canvas.width + 80 || sy < -40 || sy > canvas.height + 40) ? 'none' : 'block';
    });
  }

  function drawLoupe(img) {
    const mag = 6;
    const srcSpan = Math.floor(loupeCanvas.width / mag);
    const ix = Math.floor((lastMouse.x - offsetX) / scale);
    const iy = Math.floor((lastMouse.y - offsetY) / scale);
    loupeCtx.fillStyle = '#0f1520';
    loupeCtx.fillRect(0, 0, loupeCanvas.width, loupeCanvas.height);
    loupeCtx.imageSmoothingEnabled = false;
    loupeCtx.drawImage(
      img,
      ix - Math.floor(srcSpan / 2),
      iy - Math.floor(srcSpan / 2),
      srcSpan,
      srcSpan,
      0,
      0,
      loupeCanvas.width,
      loupeCanvas.height
    );
    // Subtle 1px pixel grid overlay at 6x
    loupeCtx.strokeStyle = 'rgba(255,255,255,0.08)';
    loupeCtx.lineWidth = 1;
    for (let p = 0; p < loupeCanvas.width; p += mag) {
      loupeCtx.beginPath();
      loupeCtx.moveTo(p, 0);
      loupeCtx.lineTo(p, loupeCanvas.height);
      loupeCtx.stroke();
      loupeCtx.beginPath();
      loupeCtx.moveTo(0, p);
      loupeCtx.lineTo(loupeCanvas.width, p);
      loupeCtx.stroke();
    }
    const lx = Math.min(canvas.width - 230, Math.max(14, lastMouse.x + 22));
    const ly = Math.min(canvas.height - 230, Math.max(14, lastMouse.y - 110));
    loupeCanvas.style.left = `${lx}px`;
    loupeCanvas.style.top = `${ly}px`;
  }

  function flyToLandmark(lm) {
    const img = images[currentMode];
    if (!img) return;
    scale = 2.0;
    offsetX = Math.round(canvas.width * 0.5 - lm.uv[0] * img.width * scale);
    offsetY = Math.round(canvas.height * 0.5 - lm.uv[1] * img.height * scale);
    updateZoomReadout();
    draw();
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
    const img = images[currentMode];
    if (!img || !meta) return;
    const rect = viewport.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;
    const u = (mx - offsetX) / (img.width * scale);
    const v = (my - offsetY) / (img.height * scale);
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
      card.innerHTML = `<img src="assets/${c.file}" alt="${c.label}" loading="lazy" /><span>${c.label}</span>`;
      card.addEventListener('click', () => {
        document.getElementById('modal-title').textContent = `${c.label} — 0.30 m/px 3D Isometric Pixel Art`;
        document.getElementById('modal-img').src = `assets/${c.file}`;
        document.getElementById('modal-overlay').classList.remove('hidden');
      });
      gal.appendChild(card);
    });
  }

  // Event bindings
  viewport.addEventListener('mousedown', (e) => {
    isDragging = true;
    dragStartX = e.clientX - offsetX;
    dragStartY = e.clientY - offsetY;
  });
  window.addEventListener('mousemove', (e) => {
    const rect = viewport.getBoundingClientRect();
    lastMouse = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    if (isDragging) {
      offsetX = e.clientX - dragStartX;
      offsetY = e.clientY - dragStartY;
      draw();
    } else if (showLoupe) {
      draw();
    }
  });
  window.addEventListener('mouseup', () => { isDragging = false; });
  viewport.addEventListener('click', (e) => hitTestBuilding(e.clientX, e.clientY));

  viewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const factor = e.deltaY < 0 ? 1.22 : 1 / 1.22;
    zoomAt(factor, e.clientX - rect.left, e.clientY - rect.top);
  }, { passive: false });

  document.querySelectorAll('.seg-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      document.querySelectorAll('.seg-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.mode;
      await loadModeImage(currentMode);
      draw();
    });
  });

  document.getElementById('btn-zoom-in').addEventListener('click', () => zoomAt(1.35, canvas.width / 2, canvas.height / 2));
  document.getElementById('btn-zoom-out').addEventListener('click', () => zoomAt(1 / 1.35, canvas.width / 2, canvas.height / 2));
  document.getElementById('btn-zoom-1x').addEventListener('click', () => zoomAt(1, canvas.width / 2, canvas.height / 2, 1.0));
  document.getElementById('btn-zoom-2x').addEventListener('click', () => zoomAt(1, canvas.width / 2, canvas.height / 2, 2.0));
  document.getElementById('btn-zoom-fit').addEventListener('click', fitToScreen);

  document.getElementById('btn-toggle-pins').addEventListener('click', (e) => {
    showPins = !showPins;
    e.currentTarget.classList.toggle('active', showPins);
    draw();
  });
  document.getElementById('btn-toggle-loupe').addEventListener('click', (e) => {
    showLoupe = !showLoupe;
    e.currentTarget.classList.toggle('active', showLoupe);
    loupeCanvas.classList.toggle('hidden', !showLoupe);
    draw();
  });
  document.getElementById('btn-close-modal').addEventListener('click', () => {
    document.getElementById('modal-overlay').classList.add('hidden');
  });
  document.getElementById('modal-overlay').addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') e.currentTarget.classList.add('hidden');
  });
  window.addEventListener('resize', resizeViewport);

  // Boot
  Promise.all([
    loadModeImage('day'),
    fetch('data/kilchberg_interactive.json').then((r) => r.json()).catch(() => null),
  ]).then(([_, loadedMeta]) => {
    meta = loadedMeta;
    populateSidebar();
    resizeViewport();
    fitToScreen();
    // Preload sunset & night in background
    loadModeImage('sunset');
    loadModeImage('night');
  });
})();
