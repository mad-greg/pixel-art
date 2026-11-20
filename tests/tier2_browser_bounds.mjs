/**
 * Tier 2 (Node CDP): FA3 Layout, Retina DPR, Zoom, Search & Malformed URL Bounds (6 tests)
 *                  + FA4 Spatial Audio Boundary & Attenuation Invariants (5 tests).
 */

import {
  ANIM_PAUSED_EXPR,
  SOUND_INACTIVE_EXPR,
  assert,
  parseZoomReadout,
  readGainValue,
  runNodeSuite,
  sleep,
  waitForSoundActive,
} from './lib/cdp_harness.mjs';

function rectsOverlap(a, b) {
  if (!a || !b) return false;
  return a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1;
}

async function runTests(harness, test) {
  // ── Tab 1: Desktop 1280x800 DPR=2 layout, Retina, extreme zoom, empty search ──
  const desktop = await harness.openTab('/?t=10', {
    width: 1280,
    height: 800,
    dpr: 2,
    blockFonts: true,
    waitReady: true,
  });

  try {
    await test('T2.FA3.01', 'Desktop 1280x800 DPR=2 zero bottom/right clipping & zero HUD overlap', async () => {
      const m = await desktop.evaluate(`(() => {
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const sels = ['#topbar', '.workspace', '#viewport', '#hud-coords', '.nav-overlay', '#minimap-box', '.dpad', '#sidebar'];
        const rects = {};
        for (const s of sels) {
          const el = document.querySelector(s);
          if (!el) continue;
          const st = getComputedStyle(el);
          if (st.display === 'none' || st.visibility === 'hidden') continue;
          const r = el.getBoundingClientRect();
          rects[s] = { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
        }
        return { vw, vh, rects };
      })()`);

      const clipped = [];
      for (const [sel, r] of Object.entries(m.rects)) {
        if (r.bottom > m.vh + 1) clipped.push(`${sel} bottom=${r.bottom.toFixed(0)} > ${m.vh}`);
        if (r.right > m.vw + 1) clipped.push(`${sel} right=${r.right.toFixed(0)} > ${m.vw}`);
      }
      assert(clipped.length === 0, `Desktop 1280x800 viewport clipping detected (F22): ${clipped.join('; ')}`);

      const hud = m.rects['#hud-coords'];
      const nav = m.rects['.nav-overlay'];
      const dpad = m.rects['.dpad'];
      assert(!rectsOverlap(hud, dpad), `#hud-coords overlaps .dpad (hud.right=${hud?.right?.toFixed(0)}, dpad.left=${dpad?.left?.toFixed(0)}; F22)`);
      assert(!rectsOverlap(hud, nav), `#hud-coords overlaps .nav-overlay (F22)`);
    });

    await test('T2.FA3.02', 'Retina HiDPI DPR=2 canvas & minimap backing store scaling', async () => {
      const dims = await desktop.evaluate(`(() => {
        const vp = document.getElementById('viewport').getBoundingClientRect();
        const dc = document.getElementById('diorama-canvas');
        const mmBox = document.getElementById('minimap-box').getBoundingClientRect();
        const mm = document.getElementById('minimap-canvas');
        return {
          dpr: window.devicePixelRatio,
          vpW: vp.width,
          dcW: dc.width,
          mmCssW: mm.getBoundingClientRect().width || mmBox.width,
          mmW: mm.width,
        };
      })()`);

      assert(dims.dpr === 2, `Expected window.devicePixelRatio === 2, got ${dims.dpr}`);
      assert(
        dims.dcW >= Math.floor(dims.vpW * 1.95),
        `#diorama-canvas not HiDPI-scaled at DPR=2: width=${dims.dcW} vs CSS ${dims.vpW.toFixed(0)} (F23)`,
      );
      assert(
        dims.mmW >= Math.floor(dims.mmCssW * 1.95),
        `#minimap-canvas not HiDPI-scaled at DPR=2: width=${dims.mmW} vs CSS ${dims.mmCssW.toFixed(0)} (F23)`,
      );

      const dbg = await desktop.getDebug();
      assert(dbg && dbg.dpr === 2, `window.__dioramaDebug.dpr expected 2, got ${dbg?.dpr}`);
    });

    await test('T2.FA3.04', 'Extreme zoom bounds (Fit -> 8x -> Fit) stay clamped & error-free', async () => {
      const prevExc = desktop.exceptions.length;
      await desktop.clickSelector('#btn-zoom-4x');
      await desktop.waitForCameraSettled();
      for (let i = 0; i < 4; i++) {
        await desktop.clickSelector('#btn-zoom-in');
        await sleep(60);
      }
      await desktop.waitForCameraSettled();
      const sampleHigh = await desktop.captureCanvasSample();
      assert(sampleHigh && sampleHigh.meanLuma > 3, 'Canvas went blank at extreme high zoom');

      const dbgHigh = await desktop.getDebug();
      const highReadout = await desktop.evaluate(`document.getElementById('zoom-readout')?.textContent?.trim() || ''`);
      const highScale =
        dbgHigh && typeof dbgHigh.scale === 'number' && Number.isFinite(dbgHigh.scale)
          ? dbgHigh.scale
          : parseZoomReadout(highReadout);
      assert(
        typeof highScale === 'number' && Number.isFinite(highScale) && highScale >= 4.0 && highScale <= 16.0,
        `Extreme zoom scale expected in [4.0, 16.0], got ${highScale} (readout='${highReadout}', dbg=${dbgHigh?.scale})`,
      );

      await desktop.clickSelector('#btn-zoom-fit');
      await desktop.waitForCameraSettled();
      const sampleFit = await desktop.captureCanvasSample();
      assert(sampleFit && sampleFit.meanLuma > 5, 'Canvas went blank after returning to Fit');

      const dbgFit = await desktop.getDebug();
      const fitReadout = await desktop.evaluate(`document.getElementById('zoom-readout')?.textContent?.trim() || ''`);
      const fitScale =
        dbgFit && typeof dbgFit.scale === 'number' && Number.isFinite(dbgFit.scale)
          ? dbgFit.scale
          : parseZoomReadout(fitReadout);
      assert(
        typeof fitScale === 'number' && Number.isFinite(fitScale) && fitScale > 0 && fitScale < 1.0,
        `Returning to Fit did not zoom out to scale < 1.0 (got ${fitScale}, readout='${fitReadout}', dbg=${dbgFit?.scale})`,
      );
      assert(desktop.exceptions.length === prevExc, `JS exceptions during extreme zoom: ${desktop.exceptions.slice(prevExc).join('; ')}`);
    });

    await test('T2.FA3.05', 'Empty & no-match address search handled gracefully with 0 results', async () => {
      const sel = await desktop.evaluate(`(() => {
        const sels = [
          'input[type="search"]',
          'input[placeholder*="search" i]',
          'input[placeholder*="address" i]',
          'input[aria-label*="search" i]',
          '#search-input',
        ];
        for (const s of sels) {
          const el = document.querySelector(s);
          if (el && el.getBoundingClientRect().width > 0) return s;
        }
        return null;
      })()`);
      assert(sel !== null, 'Address search input not found (F25)');

      const prevExc = desktop.exceptions.length;
      await desktop.typeText(sel, '');
      await sleep(100);
      await desktop.typeText(sel, 'ZZZ_NONEXISTENT_9999');
      await sleep(140);
      const dbg = await desktop.getDebug();
      assert(dbg && dbg.searchResultCount === 0, `Expected searchResultCount === 0 for nonsense query, got ${dbg?.searchResultCount}`);
      assert(desktop.exceptions.length === prevExc, `No-match search threw JS error: ${desktop.exceptions.slice(prevExc).join('; ')}`);
      await desktop.typeText(sel, '');
    });
  } finally {
    await harness.closeTab(desktop);
  }

  // ── Tab 2: Mobile 390x844 DPR=2 layout bounds ──
  const mobile = await harness.openTab('/?t=10', {
    width: 390,
    height: 844,
    dpr: 2,
    mobile: true,
    blockFonts: true,
    waitReady: true,
  });

  try {
    await test('T2.FA3.03', 'Mobile 390x844 DPR=2 zero bottom/right viewport clipping', async () => {
      const m = await mobile.evaluate(`(() => {
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const sels = ['#topbar', '.workspace', '#viewport', '#hud-coords', '.nav-overlay', '#sidebar'];
        const rects = {};
        for (const s of sels) {
          const el = document.querySelector(s);
          if (!el) continue;
          const st = getComputedStyle(el);
          if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') continue;
          const r = el.getBoundingClientRect();
          // Skip intentionally off-screen collapsed drawers
          if (r.width <= 4 || r.height <= 4 || r.left >= vw - 1) continue;
          rects[s] = { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
        }
        return { vw, vh, rects };
      })()`);

      const clipped = [];
      for (const [sel, r] of Object.entries(m.rects)) {
        if (r.bottom > m.vh + 1) clipped.push(`${sel} bottom=${r.bottom.toFixed(0)} > ${m.vh}`);
        if (r.right > m.vw + 1) clipped.push(`${sel} right=${r.right.toFixed(0)} > ${m.vw}`);
      }
      assert(clipped.length === 0, `Mobile 390x844 layout clipping detected (F22): ${clipped.join('; ')}`);
    });
  } finally {
    await harness.closeTab(mobile);
  }

  // ── Tab 3: Malformed URL parameters fallback ──
  const malformed = await harness.openTab('/?mode=bogus&zoom=-5&u=abc&v=99&t=NaN&follow=ufo', {
    width: 1280,
    height: 800,
    dpr: 2,
    blockFonts: true,
    waitReady: true,
  });

  try {
    await test('T2.FA3.06', 'Malformed URL parameters fallback cleanly with zero JS errors', async () => {
      assert(malformed.exceptions.length === 0, `Malformed URL threw JS exceptions: ${malformed.exceptions.join('; ')}`);
      assert(malformed.consoleErrors.length === 0, `Malformed URL logged console.error: ${malformed.consoleErrors.join('; ')}`);
      const sample = await malformed.captureCanvasSample();
      assert(sample && sample.meanLuma > 5, 'Canvas blank after malformed URL boot');

      const uiState = await malformed.evaluate(`({
        activeMode: document.querySelector('.seg-btn.active')?.dataset?.mode || null,
        bodyMode: document.body.dataset.mode || null,
      })`);
      assert(uiState.activeMode === 'day', `Expected fallback active mode 'day' after malformed URL, got '${uiState.activeMode}'`);
      assert(uiState.bodyMode === 'day', `Expected document.body.dataset.mode === 'day' after malformed URL, got '${uiState.bodyMode}' (Contract #5)`);

      const dbg = await malformed.getDebug();
      assert(dbg && typeof dbg === 'object', 'window.__dioramaDebug missing to verify malformed URL fallback state (Contract #5)');
      assert(dbg.mode === 'day', `Invalid fallback debug.mode: expected 'day', got '${dbg.mode}'`);
      assert(typeof dbg.scale === 'number' && Number.isFinite(dbg.scale) && dbg.scale > 0, `Invalid fallback scale: ${dbg.scale}`);
      assert(Number.isFinite(dbg.u) && dbg.u >= 0 && dbg.u <= 1, `Invalid fallback u: ${dbg.u}`);
      assert(Number.isFinite(dbg.v) && dbg.v >= 0 && dbg.v <= 1, `Invalid fallback v: ${dbg.v}`);
    });
  } finally {
    await harness.closeTab(malformed);
  }

  // ── Tab 4: Spatial Audio boundary & attenuation invariants (FA4: 5 tests) ──
  const audio = await harness.openTab('/?mode=day', {
    width: 1280,
    height: 800,
    dpr: 2,
    blockFonts: true,
    waitReady: true,
  });

  try {
    let audioUnlocked = false;
    async function ensureAudioUnlocked() {
      if (audioUnlocked) return;
      await audio.clickSelector('#btn-toggle-sound');
      const ok = await waitForSoundActive(audio, 6000);
      assert(ok, 'Trusted click on #btn-toggle-sound failed to unlock spatial audio');
      audioUnlocked = true;
    }

    let gShoreCached = null;

    await test('T2.FA4.01', 'Shore-strict lake_waves attenuation at overview Fit vs zoomed near-shore', async () => {
      await ensureAudioUnlocked();
      const dbg0 = await audio.getDebug();
      assert(dbg0 && dbg0.audioGains, 'window.__dioramaDebug.audioGains unavailable (Contract #5 / F26)');

      await audio.clickSelector('#btn-zoom-fit');
      await audio.waitForCameraSettled();
      await sleep(300);
      const dbgFit = await audio.getDebug();
      const gOverview = readGainValue(dbgFit?.audioGains, 'lake_waves');
      assert(Number.isFinite(gOverview), `lake_waves gain at Fit not finite: ${gOverview}`);

      // Fly to Schooren Seebad (5th landmark, right on Lake Zurich shoreline) and zoom to 2x
      await audio.clickSelector('#landmark-list .lm-item:nth-child(5)');
      await audio.waitForCameraSettled();
      await audio.clickSelector('#btn-zoom-2x');
      await audio.waitForCameraSettled();
      await sleep(350);
      const dbgShore = await audio.getDebug();
      const gShore = readGainValue(dbgShore?.audioGains, 'lake_waves');
      gShoreCached = gShore;

      assert(gShore > 0.005, `Expected audible near-shore lake_waves (>0.005), got ${gShore.toFixed(4)}`);
      assert(
        gShore > gOverview * 2.5,
        `Lake waves not attenuated at overview Fit: gShore=${gShore.toFixed(4)} vs gOverview=${gOverview.toFixed(4)} (need >2.5x; Guardrail #7 / F26)`,
      );
    });

    await test('T2.FA4.02', 'Near-shore vs inland ridge lake_waves spatial drop-off (>3x)', async () => {
      await ensureAudioUnlocked();
      const dbgCheck = await audio.getDebug();
      assert(dbgCheck && dbgCheck.audioGains, 'window.__dioramaDebug.audioGains unavailable (Contract #5 / F26)');

      let gShore = gShoreCached;
      if (gShore === null) {
        await audio.clickSelector('#landmark-list .lm-item:nth-child(5)');
        await audio.waitForCameraSettled();
        await audio.clickSelector('#btn-zoom-2x');
        await audio.waitForCameraSettled();
        await sleep(350);
        gShore = readGainValue((await audio.getDebug())?.audioGains, 'lake_waves');
      }

      // Fly inland to Sanatorium Ridge (6th landmark, far uphill from lake) at 2x
      await audio.clickSelector('#landmark-list .lm-item:nth-child(6)');
      await audio.waitForCameraSettled();
      await audio.clickSelector('#btn-zoom-2x');
      await audio.waitForCameraSettled();
      await sleep(350);
      const gInland = readGainValue((await audio.getDebug())?.audioGains, 'lake_waves');

      assert(Number.isFinite(gInland), `Inland lake_waves gain not finite: ${gInland}`);
      assert(
        gShore > Math.max(gInland * 3.0, 0.005),
        `Shore vs inland wave drop-off insufficient: gShore=${gShore.toFixed(4)}, gInland=${gInland.toFixed(4)} (F26)`,
      );
    });

    await test('T2.FA4.03', 'Paused animations (Live: Off) still update spatial audio gains', async () => {
      await ensureAudioUnlocked();
      const dbgCheck = await audio.getDebug();
      assert(dbgCheck && dbgCheck.audioGains, 'window.__dioramaDebug.audioGains unavailable (F26)');

      // Explicitly position camera at wooded Reformierte Kirche (2nd landmark) at 2x in Day mode
      // (zero cross-test state coupling from T2.FA4.02)
      await audio.clickSelector('#btn-mode-day');
      await audio.clickSelector('#landmark-list .lm-item:nth-child(2)');
      await audio.waitForCameraSettled();
      await audio.clickSelector('#btn-zoom-2x');
      await audio.waitForCameraSettled();
      await sleep(300);

      // Pause animations via #btn-toggle-anim
      await audio.clickSelector('#btn-toggle-anim');
      await sleep(160);
      const animPaused = await audio.evaluate(ANIM_PAUSED_EXPR);
      const animLabel = await audio.evaluate(`document.getElementById('btn-toggle-anim')?.textContent?.trim()`);
      assert(animPaused, `Expected animations paused after clicking #btn-toggle-anim (text='${animLabel}')`);

      const before = (await audio.getDebug()).audioGains;
      const beforeBirds = readGainValue(before, 'birds');
      const beforeCrickets = readGainValue(before, 'crickets');

      // Switch to Night while paused -> crickets must rise and birds must drop!
      await audio.clickSelector('#btn-mode-night');
      await sleep(500);
      const after = (await audio.getDebug()).audioGains;
      const afterBirds = readGainValue(after, 'birds');
      const afterCrickets = readGainValue(after, 'crickets');

      // Restore day & Live: On
      await audio.clickSelector('#btn-mode-day');
      await audio.clickSelector('#btn-toggle-anim');
      await sleep(150);

      const deltaCrickets = Math.abs((Number.isFinite(afterCrickets) ? afterCrickets : 0) - (Number.isFinite(beforeCrickets) ? beforeCrickets : 0));
      const deltaBirds = Math.abs((Number.isFinite(afterBirds) ? afterBirds : 0) - (Number.isFinite(beforeBirds) ? beforeBirds : 0));
      assert(
        deltaCrickets > 0.003 || deltaBirds > 0.003,
        `Spatial audio froze when animations paused (before birds=${beforeBirds?.toFixed(4)}/crickets=${beforeCrickets?.toFixed(4)}, after=${afterBirds?.toFixed(4)}/${afterCrickets?.toFixed(4)}; F26)`,
      );
    });

    await test('T2.FA4.04', 'Muting audio via #btn-toggle-sound suspends AudioContext', async () => {
      await ensureAudioUnlocked();
      const dbgBefore = await audio.getDebug();
      assert(dbgBefore && typeof dbgBefore === 'object', 'window.__dioramaDebug unavailable to verify AudioContext.state (F26)');

      await audio.clickSelector('#btn-toggle-sound');
      await sleep(220);
      audioUnlocked = false;
      const dbgMuted = await audio.getDebug();
      assert(dbgMuted.audioEnabled === false, `Expected audioEnabled === false after mute, got ${dbgMuted.audioEnabled}`);
      assert(
        dbgMuted.audioState === 'suspended',
        `Expected AudioContext.state === 'suspended' when muted, got '${dbgMuted.audioState}' (F26)`,
      );
    });

    await test('T2.FA4.05', 'Rapid sound toggle stress (On -> Off -> On) leaves AudioContext running cleanly', async () => {
      const prevExc = audio.exceptions.length;
      const prevErr = audio.consoleErrors.length;

      // Ensure starting from muted/inactive state
      const isOff = await audio.evaluate(SOUND_INACTIVE_EXPR);
      if (!isOff) {
        await audio.clickSelector('#btn-toggle-sound');
        await sleep(140);
      }

      // On -> Off -> On
      await audio.clickSelector('#btn-toggle-sound');
      await sleep(160);
      await audio.clickSelector('#btn-toggle-sound');
      await sleep(160);
      await audio.clickSelector('#btn-toggle-sound');

      const backOn = await waitForSoundActive(audio, 4500);
      assert(backOn, 'Sound button did not return to active/On after rapid toggle stress');
      assert(audio.exceptions.length === prevExc, `Rapid toggle threw JS exception: ${audio.exceptions.slice(prevExc).join('; ')}`);
      assert(audio.consoleErrors.length === prevErr, `Rapid toggle logged console.error: ${audio.consoleErrors.slice(prevErr).join('; ')}`);

      const dbg = await audio.getDebug();
      assert(dbg && dbg.audioEnabled === true && dbg.audioState === 'running', `After rapid toggle expected running AudioContext, got enabled=${dbg?.audioEnabled}, state=${dbg?.audioState}`);
    });
  } finally {
    await harness.closeTab(audio);
  }
}

runNodeSuite({
  tier: 2,
  suiteName: 'tier2_browser_bounds',
  runTests,
});
