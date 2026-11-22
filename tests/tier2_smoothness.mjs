/**
 * Tier 2 (Node CDP): v12 60fps Camera Kinematics, Sub-50ms Interpolation,
 * Compositor-Only Pin Positioning & Frame-Pacing Telemetry (T2.SM.01–T2.SM.05).
 */

import fs from 'node:fs';
import path from 'node:path';
import {
  DOCS_DIR,
  assert,
  diffCanvasSamples,
  runNodeSuite,
  sleep,
} from './lib/cdp_harness.mjs';

const REQUIRED_DEBUG_KEYS = [
  'mode',
  'scale',
  'u',
  'v',
  'dpr',
  'animTime',
  'fps',
  'audioEnabled',
  'audioState',
  'audioGains',
  'activeLandmark',
  'selectedBuilding',
  'searchResultCount',
];

function loadMasterDims() {
  const manifestPath = path.join(DOCS_DIR, 'assets', 'tiles', 'day', 'manifest.json');
  const m = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  return {
    masterW: Number(m.width),
    masterH: Number(m.height),
  };
}

function worldUVUnderPoint(dbg, cx, cy, canvasRect, masterW, masterH) {
  const dxCss = cx - (canvasRect.left + canvasRect.width * 0.5);
  const dyCss = cy - (canvasRect.top + canvasRect.height * 0.5);
  return {
    u: dbg.u + dxCss / (masterW * dbg.scale),
    v: dbg.v + dyCss / (masterH * dbg.scale),
  };
}

async function dispatchFastDrag(tab, startX, startY, totalDx, totalDy, steps = 7, stepMs = 12) {
  await tab.send('Input.dispatchMouseEvent', {
    type: 'mouseMoved',
    x: startX,
    y: startY,
    button: 'none',
    buttons: 0,
  });
  await tab.send('Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x: startX,
    y: startY,
    button: 'left',
    buttons: 1,
    clickCount: 1,
  });

  let curX = startX;
  let curY = startY;
  for (let i = 1; i < steps; i++) {
    curX = startX + (totalDx * i) / steps;
    curY = startY + (totalDy * i) / steps;
    await sleep(stepMs);
    await tab.send('Input.dispatchMouseEvent', {
      type: 'mouseMoved',
      x: curX,
      y: curY,
      button: 'left',
      buttons: 1,
    });
  }

  // Pipeline the final mouseMoved and mouseReleased with zero sleep gap so Chromium
  // dispatches pointermove -> pointerup back-to-back (< 2 ms << GLIDE_RELEASE_MAX_GAP_MS).
  curX = startX + totalDx;
  curY = startY + totalDy;
  await sleep(stepMs);
  await Promise.all([
    tab.send('Input.dispatchMouseEvent', {
      type: 'mouseMoved',
      x: curX,
      y: curY,
      button: 'left',
      buttons: 1,
    }),
    tab.send('Input.dispatchMouseEvent', {
      type: 'mouseReleased',
      x: curX,
      y: curY,
      button: 'left',
      buttons: 0,
      clickCount: 1,
    }),
  ]);
}

async function runTests(harness, test) {
  const { masterW, masterH } = loadMasterDims();

  // ── Shared desktop tab (1280x800@2x); at most one dpr=2 tab is ever open at a time ──
  let tab = await harness.openTab('/?mode=day&zoom=2&u=0.50&v=0.50', {
    width: 1280,
    height: 800,
    dpr: 2,
    blockFonts: true,
    waitReady: true,
  });

  try {
    await test('T2.SM.01', 'Inertial pan glide continues after pointerup & settles within <950ms', async () => {
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });
      const vp = await tab.evaluate(`(() => {
        const r = document.getElementById('viewport').getBoundingClientRect();
        return { left: r.left, top: r.top, width: r.width, height: r.height };
      })()`);
      assert(vp && vp.width > 200 && vp.height > 200, 'Invalid #viewport dimensions');

      const startX = vp.left + vp.width * 0.62;
      const startY = vp.top + vp.height * 0.60;
      const before = await tab.getDebug();
      assert(before && typeof before.u === 'number' && typeof before.v === 'number', 'window.__dioramaDebug u/v missing');

      // Capture exact release-instant camera coordinates synchronously on pointerup
      // (eliminates CDP round-trip latency before post-release exponential decay).
      await tab.evaluate(`(() => {
        window.__sm01Release = null;
        window.addEventListener('pointerup', () => {
          const d = window.__dioramaDebug;
          if (d && typeof d.u === 'number' && typeof d.v === 'number') {
            window.__sm01Release = { u: d.u, v: d.v, t: performance.now() };
          }
        }, { once: true, capture: true });
      })()`);

      // Crisp fast flick drag (left/up pointer motion pans camera toward larger u/v)
      await dispatchFastDrag(tab, startX, startY, -320, -180, 5, 10);

      const fallbackRelease = await tab.getDebug();

      // Sample ~120ms later to confirm active inertial coasting in the drag direction
      await sleep(120);
      const sample1 = await tab.getDebug();

      // Assert bounded settle within < 950 ms
      const tSettle0 = Date.now();
      const settled = await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });
      const settleElapsed = Date.now() - tSettle0;

      const releaseSnap = (await tab.evaluate(`(() => {
        const r = window.__sm01Release;
        delete window.__sm01Release;
        return r;
      })()`)) || fallbackRelease;

      const dragDu = releaseSnap.u - before.u;
      const dragDv = releaseSnap.v - before.v;
      const dragDist = Math.hypot(dragDu, dragDv);
      assert(
        dragDist > 0.002,
        `Fast drag did not pan camera meaningfully (dragDist=${dragDist.toFixed(6)})`,
      );

      const sample1CoastDu = sample1.u - releaseSnap.u;
      const sample1CoastDv = sample1.v - releaseSnap.v;
      const sample1CoastDist = Math.hypot(sample1CoastDu, sample1CoastDv);
      const sample1Dot = sample1CoastDu * dragDu + sample1CoastDv * dragDv;
      assert(
        sample1CoastDist > 0.0005,
        `Camera stopped dead after pointerup with no inertial pan glide at 120ms (coastDist=${sample1CoastDist.toFixed(6)} <= 0.0005; du=${sample1CoastDu.toFixed(6)}, dv=${sample1CoastDv.toFixed(6)})`,
      );
      assert(
        sample1Dot > 0,
        `Inertial coast direction at 120ms opposed drag vector (dot=${sample1Dot.toExponential(2)}, drag=(${dragDu.toFixed(5)},${dragDv.toFixed(5)}), coast=(${sample1CoastDu.toFixed(5)},${sample1CoastDv.toFixed(5)}))`,
      );

      const coastDu = settled.u - releaseSnap.u;
      const coastDv = settled.v - releaseSnap.v;
      const coastDist = Math.hypot(coastDu, coastDv);
      const dot = coastDu * dragDu + coastDv * dragDv;
      assert(
        coastDist > 0.0005,
        `Settled camera showed no inertial pan glide after pointerup (coastDist=${coastDist.toFixed(6)} <= 0.0005; du=${coastDu.toFixed(6)}, dv=${coastDv.toFixed(6)})`,
      );
      assert(
        dot > 0,
        `Settled inertial coast direction opposed drag vector (dot=${dot.toExponential(2)}, drag=(${dragDu.toFixed(5)},${dragDv.toFixed(5)}), coast=(${coastDu.toFixed(5)},${coastDv.toFixed(5)}))`,
      );

      assert(
        settleElapsed < 1100,
        `Camera inertial settle exceeded budget (${settleElapsed} ms)`,
      );

      await sleep(120);
      const afterRest = await tab.getDebug();
      const residual = Math.hypot(afterRest.u - settled.u, afterRest.v - settled.v);
      assert(
        residual < 0.0008,
        `Camera still drifting after waitForCameraSettled() (residual=${residual.toFixed(6)} >= 0.0008)`,
      );
    });

    await test('T2.SM.02', 'Focal-point-locked smooth wheel zoom interpolates across frames with <0.0025 UV drift', async () => {
      await tab.navigate('/?mode=day&zoom=1&u=0.50&v=0.50', { waitReady: true });
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });

      const canvasRect = await tab.evaluate(`(() => {
        const r = document.getElementById('diorama-canvas').getBoundingClientRect();
        return { left: r.left, top: r.top, width: r.width, height: r.height };
      })()`);
      assert(canvasRect && canvasRect.width > 200 && canvasRect.height > 200, 'Invalid #diorama-canvas rect');

      // Off-center focal point (~25% from left, ~30% from top)
      const cx = canvasRect.left + canvasRect.width * 0.25;
      const cy = canvasRect.top + canvasRect.height * 0.30;

      const before = await tab.getDebug();
      const uv0 = worldUVUnderPoint(before, cx, cy, canvasRect, masterW, masterH);

      // Start an in-page rAF sampler to capture every rendered frame cleanly during wheel zoom
      await tab.evaluate(`(() => {
        window.__smZoomSamples = [];
        window.__smZoomActive = true;
        const tick = () => {
          if (!window.__smZoomActive) return;
          const d = window.__dioramaDebug;
          if (d && typeof d.scale === 'number') {
            window.__smZoomSamples.push({ t: performance.now(), scale: d.scale, u: d.u, v: d.v });
          }
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      })()`);

      await tab.wheelAt(cx, cy, -240);
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });

      const samples = await tab.evaluate(`(() => {
        window.__smZoomActive = false;
        const out = window.__smZoomSamples || [];
        delete window.__smZoomSamples;
        return out;
      })()`);
      const after = await tab.getDebug();

      assert(
        after.scale > before.scale * 1.12,
        `Wheel zoom (-240) did not zoom in meaningfully (scale ${before.scale.toFixed(3)} -> ${after.scale.toFixed(3)})`,
      );

      // Verify smooth multi-frame scale interpolation (at least 2 distinct intermediate scales)
      const span = after.scale - before.scale;
      const lo = before.scale + span * 0.02;
      const hi = after.scale - span * 0.02;
      const intermediates = [];
      for (const s of samples) {
        if (s.scale > lo && s.scale < hi) {
          if (intermediates.length === 0 || Math.abs(s.scale - intermediates[intermediates.length - 1]) > 1e-4) {
            intermediates.push(s.scale);
          }
        }
      }
      assert(
        intermediates.length >= 2,
        `Wheel zoom snapped instead of smoothly interpolating across frames (found ${intermediates.length} intermediate scales between ${before.scale.toFixed(3)} and ${after.scale.toFixed(3)} across ${samples.length} rAF samples)`,
      );

      // Verify focal-point world UV invariance throughout animation & after settle
      let maxDriftU = 0;
      let maxDriftV = 0;
      const allChecks = [...samples, after];
      for (const s of allChecks) {
        const uv = worldUVUnderPoint(s, cx, cy, canvasRect, masterW, masterH);
        maxDriftU = Math.max(maxDriftU, Math.abs(uv.u - uv0.u));
        maxDriftV = Math.max(maxDriftV, Math.abs(uv.v - uv0.v));
      }
      assert(
        maxDriftU < 0.0025 && maxDriftV < 0.0025,
        `Focal-point world UV drifted during wheel zoom (maxDriftU=${maxDriftU.toFixed(5)}, maxDriftV=${maxDriftV.toFixed(5)}, limit=0.0025)`,
      );
    });

    await test('T2.SM.03', 'Sub-50ms pedestrian/vehicle interpolation active & ?t=10 determinism preserved', async () => {
      // Part A: Deterministic intra-50ms-bucket visual canvas motion (t=10.005 vs t=10.040).
      // Both timestamps lie inside the exact same 50 ms FIXED_DT (20 Hz) bucket:
      //   Math.floor(10.005 * 20) === 200 === Math.floor(10.040 * 20)
      const tA = 10.005;
      const tB = 10.040;
      assert(
        Math.floor(tA * 20) === Math.floor(tB * 20),
        `Test timestamps ${tA} and ${tB} must lie in the same 50ms bucket`,
      );

      await tab.navigate(`/?mode=day&zoom=2&u=0.52&v=0.55&t=${tA}`, { waitReady: true });
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });
      await sleep(180);
      const dbgA = await tab.getDebug();
      assert(dbgA && dbgA.showAnimations === true, 'Animations not active at t=10.005 for T2.SM.03');
      assert(
        dbgA.simStats && dbgA.simStats.pedestrians > 0 && dbgA.simStats.vehicles > 0,
        `Expected active pedestrians & vehicles, got ${JSON.stringify(dbgA.simStats)}`,
      );
      const snapA = await tab.captureCanvasSample('#diorama-canvas', 160, 100);

      await tab.navigate(`/?mode=day&zoom=2&u=0.52&v=0.55&t=${tB}`, { waitReady: true });
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });
      await sleep(180);
      const snapB = await tab.captureCanvasSample('#diorama-canvas', 160, 100);

      const intraDiff = diffCanvasSamples(snapA, snapB);
      assert(
        intraDiff.maxDiff > 0 && intraDiff.changedFrac > 0,
        `Rendered canvas did not visibly advance inside the same 50ms bucket (t=${tA} vs t=${tB}: maxDiff=${intraDiff.maxDiff}, changedFrac=${intraDiff.changedFrac.toFixed(5)})`,
      );

      // Part B: Direct sub-50ms pedestrian AND vehicle interpolation verification in-page.
      // Use t1=2.005, t2=2.040 (both inside bucket 40, 5x fewer fixed steps than t=10.005)
      // so the evaluation stays well below CDP's 15s timeout even under heavy parallel CPU load.
      const simT1 = 2.005;
      const simT2 = 2.040;
      assert(
        Math.floor(simT1 * 20) === Math.floor(simT2 * 20),
        `Part B timestamps ${simT1} and ${simT2} must lie in the same 50ms bucket`,
      );

      const simInterp = await tab.evaluate(`(async () => {
        const [{ createPedestrianSim }, { createTrafficSim }] = await Promise.all([
          import('./js/sim/pedestrians.js'),
          import('./js/sim/traffic.js'),
        ]);
        const animRes = await fetch('./data/kilchberg_animations.json');
        if (!animRes.ok) throw new Error('Failed to fetch kilchberg_animations.json: ' + animRes.status);
        const animData = await animRes.json();

        const masterW = ${masterW};
        const masterH = ${masterH};
        const t1 = ${simT1};
        const t2 = ${simT2};

        const pedSim = createPedestrianSim(animData);
        const trafficSim = createTrafficSim(animData);
        trafficSim.setCrosswalkOverrideMode(true);

        const pedStep1 = pedSim.updateToTime(t1, 'day', null);
        trafficSim.setExternalPedestrianStats(pedStep1.stats);
        trafficSim.updateToTime(t1, 'day', pedStep1.occupiedCrosswalks);
        const peds1 = pedSim.getInspectablePedestrians(masterW, masterH);
        const draw1 = trafficSim.getDrawableVehicles(masterW, masterH, 1.0);
        const vehs1 = [...(draw1.cars || []), ...(draw1.buses || [])];

        const pedStep2 = pedSim.updateToTime(t2, 'day', null);
        trafficSim.setExternalPedestrianStats(pedStep2.stats);
        trafficSim.updateToTime(t2, 'day', pedStep2.occupiedCrosswalks);
        const peds2 = pedSim.getInspectablePedestrians(masterW, masterH);
        const draw2 = trafficSim.getDrawableVehicles(masterW, masterH, 1.0);
        const vehs2 = [...(draw2.cars || []), ...(draw2.buses || [])];

        const p1Map = new Map(peds1.map((p) => [p.id, p]));
        let pedMoved = 0;
        for (const p2 of peds2) {
          const p1 = p1Map.get(p2.id);
          if (!p1) continue;
          if (Math.hypot(p2.u - p1.u, p2.v - p1.v) > 1e-7) pedMoved++;
        }

        const v1Map = new Map(vehs1.map((v) => [v.id, v]));
        let vehMoved = 0;
        for (const v2 of vehs2) {
          const v1 = v1Map.get(v2.id);
          if (!v1 || !v1.pos || !v2.pos) continue;
          if (Math.hypot(v2.pos.wx - v1.pos.wx, v2.pos.wy - v1.pos.wy) > 1e-4) vehMoved++;
        }

        return {
          bucket1: Math.floor(t1 * 20),
          bucket2: Math.floor(t2 * 20),
          pedTotal: peds2.length,
          pedMoved,
          vehTotal: vehs2.length,
          vehMoved,
        };
      })()`);

      assert(
        simInterp && simInterp.bucket1 === simInterp.bucket2,
        `Sub-50ms sim check buckets diverged: ${JSON.stringify(simInterp)}`,
      );
      assert(
        simInterp.pedMoved >= 5,
        `Pedestrians did not interpolate inside the same 50ms bucket (pedMoved=${simInterp.pedMoved}/${simInterp.pedTotal}; expected >= 5)`,
      );
      assert(
        simInterp.vehMoved >= 5,
        `Vehicles did not interpolate inside the same 50ms bucket (vehMoved=${simInterp.vehMoved}/${simInterp.vehTotal}; expected >= 5)`,
      );

      // Part C: Verify deterministic ?t=10 rendering remains byte-identical across two fresh loads.
      // Close main tab first and open detTab1 -> detTab2 strictly sequentially so at most ONE
      // dpr=2 software-rendered tab is ever open at a time.
      if (tab) {
        await harness.closeTab(tab);
        tab = null;
      }

      let snap1;
      const detTab1 = await harness.openTab('/?mode=day&zoom=2&u=0.52&v=0.55&t=10', {
        width: 1280,
        height: 800,
        dpr: 2,
        blockFonts: true,
        waitReady: true,
      });
      try {
        await detTab1.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });
        await sleep(250);
        snap1 = await detTab1.captureCanvasSample('#diorama-canvas', 96, 54);
      } finally {
        await harness.closeTab(detTab1);
      }

      let snap2;
      const detTab2 = await harness.openTab('/?mode=day&zoom=2&u=0.52&v=0.55&t=10', {
        width: 1280,
        height: 800,
        dpr: 2,
        blockFonts: true,
        waitReady: true,
      });
      try {
        await detTab2.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });
        await sleep(250);
        snap2 = await detTab2.captureCanvasSample('#diorama-canvas', 96, 54);
      } finally {
        await harness.closeTab(detTab2);
      }

      const diff = diffCanvasSamples(snap1, snap2);
      assert(
        diff.maxDiff === 0,
        `Deterministic ?t=10 canvas snapshots diverged (maxDiff=${diff.maxDiff}, meanAbsDiff=${diff.meanAbsDiff.toFixed(3)})`,
      );
    });

    await test('T2.SM.04', 'Compositor-only .lm-pin CSS transform positioning (no left/top mutation during pan)', async () => {
      if (!tab) {
        tab = await harness.openTab('/?mode=day&zoom=0.12&u=0.52&v=0.52', {
          width: 1280,
          height: 800,
          dpr: 2,
          blockFonts: true,
          waitReady: true,
        });
      } else {
        await tab.navigate('/?mode=day&zoom=0.12&u=0.52&v=0.52', { waitReady: true });
      }
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });

      const prevExc = tab.exceptions.length;
      const prevErr = tab.consoleErrors.length;
      const prevHttp = tab.localHttpErrors.length;

      const readPins = `(() => {
        const pins = Array.from(document.querySelectorAll('#pins-layer .lm-pin'));
        const out = [];
        for (const el of pins) {
          const st = getComputedStyle(el);
          if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) continue;
          const r = el.getBoundingClientRect();
          if (r.width <= 0 || r.height <= 0) continue;
          out.push({
            id: el.dataset.lmIdx || el.dataset.lmId || el.textContent.trim().slice(0, 24),
            inlineLeft: el.style.left || '',
            inlineTop: el.style.top || '',
            transform: st.transform || 'none',
          });
        }
        return out;
      })()`;

      const pinsBefore = await tab.evaluate(readPins);
      assert(pinsBefore.length >= 3, `Expected >= 3 visible .lm-pin elements at zoom=0.12, found ${pinsBefore.length}`);

      // Pan the map
      const vp = await tab.evaluate(`(() => {
        const r = document.getElementById('viewport').getBoundingClientRect();
        return { cx: r.left + r.width * 0.55, cy: r.top + r.height * 0.55 };
      })()`);
      await dispatchFastDrag(tab, vp.cx, vp.cy, -180, -100, 6, 16);
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });

      const pinsAfter = await tab.evaluate(readPins);
      assert(pinsAfter.length >= 1, 'No visible .lm-pin elements after pan');

      const beforeById = new Map(pinsBefore.map((p) => [p.id, p]));
      const nonMatrix = [];
      const layoutMutated = [];
      let transformMoved = 0;

      for (const p of pinsAfter) {
        if (!/^matrix(3d)?\(/.test(p.transform)) {
          nonMatrix.push(`${p.id}(transform=${p.transform})`);
        }
        const leftIsNonZero = p.inlineLeft !== '' && p.inlineLeft !== '0px' && p.inlineLeft !== '0';
        const topIsNonZero = p.inlineTop !== '' && p.inlineTop !== '0px' && p.inlineTop !== '0';
        const prev = beforeById.get(p.id);
        const leftChanged = prev && prev.inlineLeft !== p.inlineLeft;
        const topChanged = prev && prev.inlineTop !== p.inlineTop;
        if (leftIsNonZero || topIsNonZero || leftChanged || topChanged) {
          layoutMutated.push(`${p.id}(left='${p.inlineLeft}',top='${p.inlineTop}')`);
        }
        if (prev && prev.transform !== p.transform) {
          transformMoved++;
        }
      }

      assert(
        nonMatrix.length === 0,
        `Visible .lm-pin elements not positioned via CSS transform matrix: ${nonMatrix.slice(0, 5).join(', ')}`,
      );
      assert(
        layoutMutated.length === 0,
        `Visible .lm-pin elements mutated style.left/top (layout thrash instead of compositor transform): ${layoutMutated.slice(0, 5).join(', ')}`,
      );
      assert(
        transformMoved >= 1,
        `No visible .lm-pin updated its computed CSS transform matrix after pan`,
      );

      const sample = await tab.captureCanvasSample();
      assert(sample && sample.meanLuma > 5, `Canvas went blank after pan (meanLuma=${sample?.meanLuma})`);
      assert(tab.exceptions.length === prevExc, `JS exceptions during pin pan: ${tab.exceptions.slice(prevExc).join('; ')}`);
      assert(tab.consoleErrors.length === prevErr, `Console errors during pin pan: ${tab.consoleErrors.slice(prevErr).join('; ')}`);
      assert(tab.localHttpErrors.length === prevHttp, `HTTP >=400 errors during pin pan: ${tab.localHttpErrors.slice(prevHttp).map((e) => `${e.status} ${e.url}`).join('; ')}`);
    });

    await test('T2.SM.05', 'Frame-pacing telemetry (frameStats) & non-stalling multi-tile pan at zoom=2', async () => {
      await tab.navigate('/?mode=day&zoom=2&u=0.35&v=0.40', { waitReady: true });
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });

      const prevExc = tab.exceptions.length;
      const prevErr = tab.consoleErrors.length;
      const prevHttp = tab.localHttpErrors.length;
      const prevFail = tab.localLoadFailures.length;

      const dbg0 = await tab.getDebug();
      assert(dbg0 && typeof dbg0 === 'object', 'window.__dioramaDebug missing');

      // Preserve all 13 existing Contract #5 keys
      const missingKeys = REQUIRED_DEBUG_KEYS.filter((k) => !(k in dbg0));
      assert(
        missingKeys.length === 0,
        `window.__dioramaDebug missing existing Contract #5 keys: ${missingKeys.join(', ')}`,
      );

      // Verify additive frameStats object
      const fs0 = dbg0.frameStats;
      assert(
        fs0 && typeof fs0 === 'object',
        'window.__dioramaDebug.frameStats missing (required v12 frame-pacing telemetry)',
      );
      for (const k of ['fps', 'p95FrameMs', 'tileInflight', 'tileCacheSize']) {
        assert(
          typeof fs0[k] === 'number' && Number.isFinite(fs0[k]) && fs0[k] >= 0,
          `frameStats.${k} must be a finite non-negative number, got ${fs0[k]}`,
        );
      }
      assert(
        typeof fs0.rafActive === 'boolean',
        `frameStats.rafActive must be boolean, got ${typeof fs0.rafActive} (${fs0.rafActive})`,
      );

      // Pan across 4+ tiles at zoom=2: 6 drags of (-580, -240) CSS px = 1883 direct master px
      // (mathematically guarantees >= 1500 master px even with zero inertial coasting).
      const vp = await tab.evaluate(`(() => {
        const r = document.getElementById('viewport').getBoundingClientRect();
        return { x: r.left + r.width * 0.78, y: r.top + r.height * 0.70 };
      })()`);

      for (let i = 0; i < 6; i++) {
        await dispatchFastDrag(tab, vp.x, vp.y, -580, -240, 6, 12);
        await sleep(140);
      }
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });

      // Wait up to 2000ms for inflight tile requests to drain cleanly to 0
      const drained = await tab.waitFor(
        `(() => {
          const d = window.__dioramaDebug;
          return Boolean(d && d.frameStats && d.frameStats.tileInflight === 0);
        })()`,
        { timeoutMs: 2000, intervalMs: 80 },
      );

      const dbg1 = await tab.getDebug();
      const fs1 = dbg1.frameStats;
      const worldMovedPx = Math.hypot((dbg1.u - dbg0.u) * masterW, (dbg1.v - dbg0.v) * masterH);

      assert(
        worldMovedPx >= 1500,
        `Multi-tile pan moved only ${worldMovedPx.toFixed(0)} master px (expected >= 1500 px across 4+ tiles)`,
      );
      assert(
        fs1.tileCacheSize <= 128,
        `frameStats.tileCacheSize=${fs1.tileCacheSize} exceeded LRU cap of 128`,
      );
      assert(
        drained && fs1.tileInflight === 0,
        `frameStats.tileInflight did not drain to 0 after pan settle (got ${fs1.tileInflight})`,
      );
      assert(
        typeof fs1.rafActive === 'boolean' &&
          Number.isFinite(fs1.fps) && fs1.fps >= 0 &&
          Number.isFinite(fs1.p95FrameMs) && fs1.p95FrameMs >= 0,
        `Invalid post-pan frameStats: ${JSON.stringify(fs1)}`,
      );

      assert(tab.exceptions.length === prevExc, `JS exceptions during multi-tile pan: ${tab.exceptions.slice(prevExc).join('; ')}`);
      assert(tab.consoleErrors.length === prevErr, `Console errors during multi-tile pan: ${tab.consoleErrors.slice(prevErr).join('; ')}`);
      assert(tab.localHttpErrors.length === prevHttp, `HTTP >=400 errors during multi-tile pan: ${tab.localHttpErrors.slice(prevHttp).map((e) => `${e.status} ${e.url}`).join('; ')}`);
      assert(tab.localLoadFailures.length === prevFail, `Local load failures during multi-tile pan: ${tab.localLoadFailures.slice(prevFail).map((e) => `${e.errorText} ${e.url}`).join('; ')}`);
    });
  } finally {
    if (tab) await harness.closeTab(tab);
  }
}

runNodeSuite({
  tier: 2,
  suiteName: 'tier2_smoothness',
  runTests,
});
