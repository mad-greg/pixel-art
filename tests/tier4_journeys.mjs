/**
 * Tier 4 (Node CDP): 7 Real-World End-User Application Journeys (T4.01 - T4.07).
 */

import {
  SEARCH_RESULT_SELECTOR,
  assert,
  diffCanvasSamples,
  findMixerButtonPoint,
  readGainValue,
  runNodeSuite,
  sleep,
  waitForSoundActive,
} from './lib/cdp_harness.mjs';

async function runTests(harness, test) {
  // ── T4.01: Journey 1 — First-Time Visitor Full Tour ──
  await test('T4.01', 'Journey 1: First-time visitor tour (Midday -> Alpenglow -> Night -> Cinema -> Postcard)', async () => {
    const tab = await harness.openTab('/?t=10', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      assert(tab.exceptions.length === 0, `Boot JS exceptions: ${tab.exceptions.join('; ')}`);
      assert(tab.consoleErrors.length === 0, `Boot console.error: ${tab.consoleErrors.join('; ')}`);
      assert(tab.localHttpErrors.length === 0, `Boot local 404/500: ${tab.localHttpErrors.map((e) => e.url).join('; ')}`);

      // Clean non-clipped layout check
      const clip = await tab.evaluate(`(() => {
        const vh = window.innerHeight;
        const els = ['#topbar', '.workspace', '#viewport', '#hud-coords', '.nav-overlay', '#sidebar'];
        const bad = [];
        for (const s of els) {
          const el = document.querySelector(s);
          if (!el) continue;
          const r = el.getBoundingClientRect();
          if (r.bottom > vh + 1) bad.push(s + '=' + Math.round(r.bottom));
        }
        return bad;
      })()`);
      assert(clip.length === 0, `First-time desktop layout clipped below 800px: ${clip.join(', ')}`);

      // Switch Midday -> Alpenglow -> Night
      const samples = {};
      for (const [id, mode] of [
        ['#btn-mode-day', 'day'],
        ['#btn-mode-sunset', 'sunset'],
        ['#btn-mode-night', 'night'],
      ]) {
        await tab.clickSelector(id);
        await sleep(260);
        const bm = await tab.evaluate(`document.body.dataset.mode`);
        assert(bm === mode, `Expected body[data-mode]="${mode}", got "${bm}"`);
        samples[mode] = await tab.captureCanvasSample();
      }
      assert(
        samples.day.meanLuma > samples.sunset.meanLuma && samples.sunset.meanLuma > samples.night.meanLuma,
        `Tour preset luminance order invalid: day=${samples.day.meanLuma.toFixed(1)}, sunset=${samples.sunset.meanLuma.toFixed(1)}, night=${samples.night.meanLuma.toFixed(1)}`,
      );

      // Enter & exit Cinema Mode
      await tab.pressKey('h', 'KeyH', 72);
      await sleep(160);
      assert(await tab.evaluate(`document.body.classList.contains('cinema-mode')`), 'Cinema Mode failed to activate on H');
      await tab.pressKey('Escape', 'Escape', 27);
      await sleep(160);
      assert(!(await tab.evaluate(`document.body.classList.contains('cinema-mode')`)), 'Cinema Mode failed to exit on Esc');

      // Locate & click Postcard PNG export button
      const postcardPt = await tab.evaluate(`(() => {
        const btn = [...document.querySelectorAll('button, a')].find((b) => {
          const blob = ((b.id || '') + ' ' + (b.title || '') + ' ' + (b.getAttribute('aria-label') || '') + ' ' + (b.textContent || '')).toLowerCase();
          return /postcard|export|snapshot|png/.test(blob) && b.getBoundingClientRect().width > 0;
        });
        if (!btn) return null;
        const r = btn.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })()`);
      assert(postcardPt !== null, 'Postcard PNG export control missing (F25)');
      await tab.clickPoint(postcardPt.x, postcardPt.y);
      await sleep(160);
      assert(tab.exceptions.length === 0, `Postcard export threw JS exception: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T4.02: Journey 2 — Lindt HoC & Schooren Seebad Deep-Zoom Inspection ──
  await test('T4.02', 'Journey 2: Lindt HoC 2x tiles + 0.22m/px plate + Schooren Seebad water/SUP motion', async () => {
    const tab = await harness.openTab('/?mode=day&t=10', { width: 1280, height: 800, dpr: 2, waitReady: true });
    let s10, s16;
    try {
      tab.resetNetworkCounters();
      // Fly to Lindt Home of Chocolate (1st landmark) & zoom 2x
      await tab.clickSelector('#landmark-list .lm-item:nth-child(1)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(160);
      assert(tab.tileResponses.length >= 1, `Expected 0.25m/px tile HTTP 200 streaming at Lindt 2x, got ${tab.tileResponses.length}`);

      // Open 01_lindt_home_of_chocolate.webp detail plate
      await tab.clickSelector('#crop-gallery .crop-thumb:first-child');
      const modalReady = await tab.waitFor(
        `!document.getElementById('modal-overlay')?.classList.contains('hidden') && document.getElementById('modal-canvas')?.width > 50`,
        { timeoutMs: 2500 },
      );
      assert(Boolean(modalReady), 'Lindt 0.22 m/px detail-plate modal did not open');

      const modalInfo = await tab.evaluate(`(() => {
        const btns = [...document.querySelectorAll('#modal-overlay button')];
        return {
          has4x: btns.some((b) => /4[x×]/i.test(b.textContent || '')),
          hasFlyHere: btns.some((b) => /fly\\s*here/i.test(b.textContent || '') || /fly/i.test(b.id || '')),
        };
      })()`);
      assert(modalInfo.has4x, 'Lindt detail-plate modal missing 4x zoom button (F25)');
      assert(modalInfo.hasFlyHere, 'Lindt detail-plate modal missing "Fly Here" button (F25)');

      await tab.pressKey('Escape', 'Escape', 27);
      await sleep(140);

      // Reuse same incognito context via same-tab navigate to verify water/SUP motion at Schooren Seebad
      await tab.navigate('/?mode=day&zoom=2&u=0.41&v=0.70&t=10', { waitReady: true });
      await sleep(200);
      s10 = await tab.captureCanvasSample('#diorama-canvas', 96, 54);

      await tab.navigate('/?mode=day&zoom=2&u=0.41&v=0.70&t=16', { waitReady: true });
      await sleep(200);
      s16 = await tab.captureCanvasSample('#diorama-canvas', 96, 54);
      assert(tab.exceptions.length === 0, `Schooren Seebad render threw exception: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }

    const diff = diffCanvasSamples(s10, s16);
    assert(diff.maxDiff >= 8, `No water/SUP animation motion detected at Schooren Seebad between t=10 and t=16 (maxDiff=${diff.maxDiff})`);
  });

  // ── T4.03: Journey 3 — Commuter Transit Showcase (Train -> Boat -> Bus) ──
  await test('T4.03', 'Journey 3: Commuter transit showcase (SBB Train, ZSG Steamer, ZVV Bus Follow)', async () => {
    const tab = await harness.openTab('/', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      // Inspect Bahnhof Kilchberg (4th landmark)
      await tab.clickSelector('#landmark-list .lm-item:nth-child(4)');
      await tab.waitForCameraSettled();
      tab.resetNetworkCounters();

      const seenModes = new Set();
      for (let i = 0; i < 4; i++) {
        await tab.clickSelector('#btn-follow');
        await sleep(160);
        const label = await tab.evaluate(`document.getElementById('btn-follow')?.textContent?.trim() || ''`);
        if (/train/i.test(label)) seenModes.add('train');
        if (/boat/i.test(label)) seenModes.add('boat');
        if (/bus/i.test(label)) seenModes.add('bus');

        if (/train|boat|bus/i.test(label)) {
          await tab.waitFor(
            `(() => {
              const d = typeof window.__dioramaDebug === 'function' ? window.__dioramaDebug() : window.__dioramaDebug;
              return Boolean(d && typeof d.scale === 'number' && d.scale >= 1.4);
            })()`,
            { timeoutMs: 800, intervalMs: 80 },
          );
          const dbg = await tab.getDebug();
          assert(dbg && dbg.scale >= 1.4, `Follow mode '${label}' expected zoomed scale >= 1.4, got ${dbg?.scale}`);
        }
      }

      assert(seenModes.has('train'), 'Transit showcase missing Follow: Train');
      assert(seenModes.has('boat'), 'Transit showcase missing Follow: Boat');
      assert(seenModes.has('bus'), 'Transit showcase missing Follow: Bus (F20)');
      assert(tab.tileResponses.length >= 1, `Expected tile streaming during Follow tour, got ${tab.tileResponses.length}`);
      assert(tab.exceptions.length === 0, `Transit showcase threw JS exception: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T4.04: Journey 4 — Kilchberg Resident Address Lookup & Share Permalink ──
  await test('T4.04', 'Journey 4: Resident address lookup -> inspect -> share permalink -> fresh tab restore', async () => {
    const tab = await harness.openTab('/?mode=day&t=10', { width: 1280, height: 800, dpr: 2, waitReady: true });
    let capturedUrl = null;
    let savedState = null;

    try {
      const searchSel = await tab.evaluate(`(() => {
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
      assert(searchSel !== null, 'Resident address search input not found (F25)');

      await tab.typeText(searchSel, 'Schoorenstrasse 1');
      await sleep(200);
      const dbgSearch = await tab.getDebug();
      assert(dbgSearch && dbgSearch.searchResultCount >= 1, `Expected >=1 result for "Schoorenstrasse 1", got ${dbgSearch?.searchResultCount}`);

      const resPt = await tab.evaluate(`(() => {
        const items = [...document.querySelectorAll(${JSON.stringify(SEARCH_RESULT_SELECTOR)})];
        const vis = items.find((el) => el.getBoundingClientRect().height > 0);
        if (!vis) return null;
        const r = vis.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })()`);
      if (resPt) await tab.clickPoint(resPt.x, resPt.y);
      else await tab.pressKey('Enter', 'Enter', 13);
      await tab.waitForCameraSettled();

      const title = await tab.evaluate(`document.getElementById('insp-title')?.textContent?.trim() || ''`);
      assert(/schoorenstrasse|lindt/i.test(title), `Inspector did not show searched address (got '${title}')`);
      savedState = await tab.getDebug();
      assert(savedState && savedState.selectedBuilding !== null, 'selectedBuilding not set after address selection');

      // Capture Share Permalink
      await tab.evaluate(`(() => {
        window.__e2eShareUrl = null;
        try {
          Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: { writeText: (txt) => { window.__e2eShareUrl = String(txt); return Promise.resolve(); } },
          });
        } catch {}
      })()`);

      const sharePt = await tab.evaluate(`(() => {
        const btn = [...document.querySelectorAll('button, a')].find((b) => {
          const blob = ((b.id || '') + ' ' + (b.title || '') + ' ' + (b.getAttribute('aria-label') || '') + ' ' + (b.textContent || '')).toLowerCase();
          return /share|permalink|copy\\s*link|copy\\s*url/.test(blob) && b.getBoundingClientRect().width > 0;
        });
        if (!btn) return null;
        const r = btn.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })()`);
      assert(sharePt !== null, 'Share Permalink button missing (F25)');
      await tab.clickPoint(sharePt.x, sharePt.y);
      await sleep(160);
      capturedUrl = await tab.evaluate(`window.__e2eShareUrl || (window.location.search.includes('zoom=') ? window.location.href : null)`);
    } finally {
      await harness.closeTab(tab);
    }

    assert(capturedUrl && capturedUrl.includes('zoom='), `Share Permalink did not yield a valid URL (got '${capturedUrl}')`);
    const uObj = new URL(capturedUrl, harness.baseUrl);
    const tab2 = await harness.openTab(uObj.pathname + uObj.search, { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      const restored = await tab2.getDebug();
      assert(restored && restored.mode === savedState.mode, `Restored mode mismatch: ${restored?.mode} vs ${savedState.mode}`);
      assert(Math.abs(restored.u - savedState.u) < 0.06 && Math.abs(restored.v - savedState.v) < 0.06, 'Restored (u, v) viewport mismatch');
    } finally {
      await harness.closeTab(tab2);
    }
  });

  // ── T4.05: Journey 5 — Spatial Soundscape Walk ──
  await test('T4.05', 'Journey 5: Spatial soundscape walk (Shore -> Ridge -> Night -> Mixer -> Mute)', async () => {
    const tab = await harness.openTab('/?mode=day', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      tab.resetNetworkCounters();
      await tab.clickSelector('#btn-toggle-sound');
      const ok = await waitForSoundActive(tab, 6000, { minMp3Count: 9 });
      assert(ok, 'Trusted click failed to unlock sound');
      const mp3Count = new Set(tab.audioResponses.map((r) => new URL(r.url).pathname)).size;
      assert(mp3Count >= 9, `Expected 9/9 MP3s decoded, saw ${mp3Count}`);

      const dbgFit = await tab.getDebug();
      assert(dbgFit && dbgFit.audioState === 'running' && dbgFit.audioGains, 'AudioContext running telemetry / audioGains missing (F26)');
      const gOverview = readGainValue(dbgFit.audioGains, 'lake_waves');

      // Walk to shore (Schooren Seebad, 2x)
      await tab.clickSelector('#landmark-list .lm-item:nth-child(5)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(350);
      const gShore = readGainValue((await tab.getDebug()).audioGains, 'lake_waves');
      assert(
        gShore > Math.max((Number.isFinite(gOverview) ? gOverview : 0) * 2.5, 0.005),
        `Shore waves (${gShore.toFixed(4)}) not >2.5x overview (${gOverview.toFixed(4)})`,
      );

      // Walk uphill to wooded ridge (Reformierte Kirche, 2x)
      await tab.clickSelector('#landmark-list .lm-item:nth-child(2)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(350);
      const ridgeDay = (await tab.getDebug()).audioGains;
      const ridgeBirds = readGainValue(ridgeDay, 'birds');
      assert(ridgeBirds > 0.005, `Expected uphill tree birds > 0.005, got ${ridgeBirds}`);
      assert(
        Number.isFinite(readGainValue(ridgeDay, 'traffic')) &&
          Number.isFinite(readGainValue(ridgeDay, 'town_traffic')),
        'Traffic channels missing',
      );

      // Switch to Night -> crickets > birds
      await tab.clickSelector('#btn-mode-night');
      await sleep(500);
      const ridgeNight = (await tab.getDebug()).audioGains;
      const nightCrickets = readGainValue(ridgeNight, 'crickets');
      const nightBirds = readGainValue(ridgeNight, 'birds');
      assert(nightCrickets > nightBirds, `Night crickets (${nightCrickets}) not > birds (${nightBirds})`);

      // Open mixer popover & check sliders
      const mixerPt = await findMixerButtonPoint(tab);
      assert(mixerPt !== null, 'Audio layer mixer popover button missing (F26)');
      await tab.clickPoint(mixerPt.x, mixerPt.y);
      await sleep(160);
      const sliders = await tab.evaluate(`[...document.querySelectorAll('input[type="range"]')].filter((s) => s.getBoundingClientRect().width > 0).length`);
      assert(sliders >= 4, `Expected >=4 mixer sliders, got ${sliders}`);

      // Mute & verify suspended AudioContext
      await tab.clickSelector('#btn-toggle-sound');
      await sleep(200);
      const muted = await tab.getDebug();
      assert(muted.audioEnabled === false && muted.audioState === 'suspended', `Expected suspended AudioContext after mute, got ${muted.audioState}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T4.06: Journey 6 — Mobile Portrait Explorer (390x844 DPR=2) ──
  await test('T4.06', 'Journey 6: Mobile portrait explorer (390x844 zero clipping, modes & landmark tour)', async () => {
    const tab = await harness.openTab('/?t=10', {
      width: 390,
      height: 844,
      dpr: 2,
      mobile: true,
      waitReady: true,
    });
    try {
      assert(tab.exceptions.length === 0, `Mobile boot JS exceptions: ${tab.exceptions.join('; ')}`);
      assert(tab.consoleErrors.length === 0, `Mobile boot console.error: ${tab.consoleErrors.join('; ')}`);
      assert(tab.localHttpErrors.length === 0, `Mobile boot local 404/500: ${tab.localHttpErrors.map((e) => e.url).join('; ')}`);

      // Zero clipping on visible containers
      const clip = await tab.evaluate(`(() => {
        const vw = window.innerWidth, vh = window.innerHeight;
        const bad = [];
        for (const s of ['#topbar', '.workspace', '#viewport', '#hud-coords', '.nav-overlay', '#sidebar']) {
          const el = document.querySelector(s);
          if (!el) continue;
          const st = getComputedStyle(el);
          if (st.display === 'none' || st.visibility === 'hidden') continue;
          const r = el.getBoundingClientRect();
          if (r.width <= 4 || r.height <= 4 || r.left >= vw - 1) continue;
          if (r.bottom > vh + 1) bad.push(s + '.bottom=' + Math.round(r.bottom));
          if (r.right > vw + 1) bad.push(s + '.right=' + Math.round(r.right));
        }
        return bad;
      })()`);
      assert(clip.length === 0, `Mobile 390x844 viewport clipping: ${clip.join(', ')}`);

      // Switch presets day -> sunset -> night
      const sDay = await tab.captureCanvasSample();
      await tab.clickSelector('#btn-mode-sunset');
      await sleep(220);
      const bmSun = await tab.evaluate(`document.body.dataset.mode`);
      await tab.clickSelector('#btn-mode-night');
      await sleep(220);
      const bmNight = await tab.evaluate(`document.body.dataset.mode`);
      const sNight = await tab.captureCanvasSample();
      assert(bmSun === 'sunset' && bmNight === 'night', `Mobile body[data-mode] not updated: sunset='${bmSun}', night='${bmNight}'`);
      assert(diffCanvasSamples(sDay, sNight).meanAbsDiff > 4.0, 'Mobile mode switch did not update canvas');

      // Select a landmark (open sidebar drawer first if collapsed on mobile)
      const lmVis = await tab.evaluate(`(() => {
        const el = document.querySelector('#landmark-list .lm-item:nth-child(1)');
        if (!el) return false;
        const r = el.getBoundingClientRect();
        return r.width > 10 && r.height > 10 && r.left < window.innerWidth && r.top < window.innerHeight;
      })()`);
      if (!lmVis) {
        const toggleSel = await tab.evaluate(`(() => {
          const sels = [
            'button[aria-label*="sidebar" i]',
            'button[aria-label*="inspector" i]',
            'button[aria-label*="drawer" i]',
            'button[aria-label*="panel" i]',
            'button[title*="sidebar" i]',
            'button[title*="drawer" i]',
            'button[id*="drawer" i]',
            '#btn-toggle-sidebar',
          ];
          for (const s of sels) {
            const el = document.querySelector(s);
            if (el && el.getBoundingClientRect().width > 0) return s;
          }
          return null;
        })()`);
        if (toggleSel) {
          await tab.clickSelector(toggleSel);
          await sleep(200);
        }
      }
      await tab.clickSelector('#landmark-list .lm-item:nth-child(1)');
      await tab.waitForCameraSettled();
      assert(tab.exceptions.length === 0, `Mobile landmark tour threw exception: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T4.07: Journey 7 — Living Kilchberg Commuter & Village Life ──
  await test('T4.07', 'Journey 7: Living Kilchberg commuter & village life (Bahnhof, Bus dwell, Pier/Lindt/Seebad & trip readout)', async () => {
    const tab = await harness.openTab('/?mode=day', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      // Step 1: Bahnhof Kilchberg & Follow Train
      tab.resetNetworkCounters();
      await tab.clickSelector('#landmark-list .lm-item:nth-child(4)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(160);

      const dbg1 = await tab.getDebug();
      assert(dbg1?.simStats && typeof dbg1.simStats === 'object', 'window.__dioramaDebug.simStats missing at Bahnhof (v8.0 Contract #3)');
      assert(dbg1.simStats.activeTrips > 0, `Expected activeTrips > 0 at Bahnhof, got ${dbg1.simStats.activeTrips}`);
      assert(dbg1.simStats.pedestrians > 0, `Expected pedestrians > 0 at Bahnhof, got ${dbg1.simStats.pedestrians}`);
      assert(dbg1.simStats.vehicles > 0, `Expected vehicles > 0 at Bahnhof, got ${dbg1.simStats.vehicles}`);

      let followTrainOk = false;
      for (let i = 0; i < 6; i++) {
        const d = await tab.getDebug();
        if (d?.followTarget === 'train') {
          followTrainOk = true;
          break;
        }
        await tab.clickSelector('#btn-follow');
        await sleep(160);
      }
      assert(followTrainOk, 'Could not cycle #btn-follow to Follow: Train');
      await sleep(300);
      const dbgTrain = await tab.getDebug();
      assert(dbgTrain.scale >= 1.4, `Expected zoom >= 1.4x during Follow: Train, got ${dbgTrain.scale}`);
      assert(tab.tileResponses.length >= 1, `Expected >=1 tile load across Bahnhof 2x + Follow: Train, got ${tab.tileResponses.length}`);
      const trainSample = await tab.captureCanvasSample('#diorama-canvas', 48, 27);
      assert(trainSample && trainSample.meanLuma > 5, 'Canvas blank during Follow: Train');

      // Step 2: Follow Bus (stop dwell & queueing/braking)
      let followBusOk = false;
      for (let i = 0; i < 6; i++) {
        const d = await tab.getDebug();
        if (d?.followTarget === 'bus') {
          followBusOk = true;
          break;
        }
        await tab.clickSelector('#btn-follow');
        await sleep(160);
      }
      assert(followBusOk, 'Could not cycle #btn-follow to Follow: Bus');
      const dbgBusInit = await tab.getDebug();
      assert(dbgBusInit.scale >= 1.4, `Expected zoom >= 1.4x during Follow: Bus, got ${dbgBusInit.scale}`);

      for (let s = 0; s < 3; s++) {
        await sleep(360);
        const d = await tab.getDebug();
        assert(d?.simStats && d.simStats.vehicles > 0, `Invalid simStats.vehicles during Follow: Bus sample ${s}`);
        assert(
          d.simStats.brakingCount >= 0 && d.simStats.brakingCount <= d.simStats.vehicles,
          `Invalid simStats.brakingCount=${d.simStats.brakingCount} during Follow: Bus sample ${s}`,
        );
      }

      // Cycle Follow back to Off
      for (let i = 0; i < 6; i++) {
        const d = await tab.getDebug();
        if (!d?.followTarget) break;
        await tab.clickSelector('#btn-follow');
        await sleep(140);
      }

      // Step 3: Bendlikon Pier, Lindt HoC & Schooren Seebad living activity
      await tab.clickSelector('#landmark-list .lm-item:nth-child(3)');
      await tab.waitForCameraSettled();
      const pierSample = await tab.captureCanvasSample('#diorama-canvas', 48, 27);
      const dbgPier = await tab.getDebug();
      assert(pierSample && pierSample.meanLuma > 5, 'Canvas blank at Bendlikon Pier');
      assert(dbgPier?.simStats?.activeTrips > 0, 'Expected activeTrips > 0 at Bendlikon Pier');

      await tab.clickSelector('#landmark-list .lm-item:nth-child(1)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      const lindtSample = await tab.captureCanvasSample('#diorama-canvas', 48, 27);
      const dbgLindt = await tab.getDebug();
      assert(lindtSample && lindtSample.meanLuma > 5, 'Canvas blank at Lindt HoC');
      assert(dbgLindt?.simStats?.pedestrians > 0, 'Expected pedestrians > 0 at Lindt HoC');

      await tab.clickSelector('#landmark-list .lm-item:nth-child(5)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(160);
      const dbgSeebad = await tab.getDebug();
      assert(dbgSeebad?.waterMaskReady === true, `Expected waterMaskReady === true at Seebad, got ${dbgSeebad?.waterMaskReady}`);
      assert(
        dbgSeebad?.livingCounts?.sups >= 2,
        `Expected livingCounts.sups >= 2 at Schooren Seebad, got ${dbgSeebad?.livingCounts?.sups}`,
      );

      // Step 4: Entity trip inspection & zero layout regression
      const preInsp = await tab.evaluate(`(() => ({
        title: (document.getElementById('insp-title')?.textContent || '').trim(),
        cardText: (document.getElementById('inspector-card')?.textContent || '').trim(),
      }))()`);
      for (let i = 0; i < 6; i++) {
        const d = await tab.getDebug();
        if (d?.followTarget === 'train') break;
        await tab.clickSelector('#btn-follow');
        await sleep(140);
      }
      await sleep(200);
      const vpCenter = await tab.evaluate(`(() => {
        const r = document.getElementById('viewport').getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })()`);
      await tab.clickPoint(vpCenter.x, vpCenter.y);
      await sleep(160);

      const layoutCheck = await tab.evaluate(`(() => {
        const title = (document.getElementById('insp-title')?.textContent || '').trim();
        const cardText = (document.getElementById('inspector-card')?.textContent || '').trim();
        const tripEls = Array.from(document.querySelectorAll('[id*="trip" i], [class*="trip" i], [data-trip]'))
          .filter((el) => {
            const st = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0;
          })
          .map((el) => (el.textContent || '').trim())
          .filter(Boolean);
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const sels = ['#topbar', '.workspace', '#viewport', '#hud-coords', '.nav-overlay', '#sidebar'];
        const clipped = [];
        for (const s of sels) {
          const el = document.querySelector(s);
          if (!el) continue;
          const r = el.getBoundingClientRect();
          if (r.bottom > vh + 1) clipped.push(s + '.bottom=' + Math.round(r.bottom));
          if (r.right > vw + 1) clipped.push(s + '.right=' + Math.round(r.right));
        }
        return { title, cardText, tripBadge: tripEls.join(' | '), clipped };
      })()`);
      assert(layoutCheck.title.length > 0, 'Inspector title #insp-title empty after entity trip inspection');
      const tripUpdated =
        layoutCheck.title !== preInsp.title ||
        layoutCheck.cardText !== preInsp.cardText ||
        layoutCheck.tripBadge.length > 0;
      assert(
        tripUpdated,
        `Entity trip inspection did not update inspector or show a trip readout (still stuck on "${preInsp.title}")`,
      );
      assert(layoutCheck.clipped.length === 0, `Layout clipping detected in Journey 7: ${layoutCheck.clipped.join(', ')}`);
      assert(tab.exceptions.length === 0, `Exceptions in Journey 7: ${tab.exceptions.join('; ')}`);
      assert(tab.consoleErrors.length === 0, `console.error in Journey 7: ${tab.consoleErrors.join('; ')}`);
      assert(tab.localHttpErrors.length === 0, `Local HTTP errors in Journey 7: ${tab.localHttpErrors.map((e) => `${e.status} ${e.url}`).join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T4.08: RAF Loop Non-Leak Across Repeated Live: Off -> On Toggles ──
  await test('T4.08', 'Hardening: repeated Live Off/On toggles never multiply requestAnimationFrame loops', async () => {
    const tab = await harness.openTab('/', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      await sleep(200);
      await tab.evaluate(`(() => {
        const orig = window.requestAnimationFrame.bind(window);
        window.__rafCount = 0;
        window.requestAnimationFrame = (cb) => {
          window.__rafCount++;
          return orig(cb);
        };
      })()`);
      await tab.evaluate('window.__rafCount = 0');
      await sleep(400);
      const baseCount = await tab.evaluate('window.__rafCount');
      assert(baseCount > 0, `Expected active baseline RAF loop, got ${baseCount}`);

      // Toggle Live Off -> On 6 times rapidly (12 clicks)
      for (let i = 0; i < 12; i++) {
        await tab.clickSelector('#btn-toggle-anim');
        await sleep(15);
      }
      await sleep(100);
      await tab.evaluate('window.__rafCount = 0');
      await sleep(400);
      const afterCount = await tab.evaluate('window.__rafCount');
      const maxAllowed = Math.max(Math.ceil(baseCount * 1.8), 40);
      assert(
        afterCount <= maxAllowed,
        `RAF loop multiplied after Live Off/On toggles: baseline=${baseCount}/400ms, after=${afterCount}/400ms (max ${maxAllowed})`,
      );
      assert(tab.exceptions.length === 0, `Exceptions in T4.08: ${tab.exceptions.join('; ')}`);
      assert(tab.consoleErrors.length === 0, `console.error in T4.08: ${tab.consoleErrors.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T4.09: Negative & Extreme ?t= Timestamp Clamping & Frame Stability ──
  await test('T4.09', 'Hardening: negative (?t=-5) and extreme (?t=1e16) timestamps stay finite and fast', async () => {
    for (const q of ['/?t=-5', '/?t=1e16']) {
      const tab = await harness.openTab(q, { width: 1280, height: 800, dpr: 2, waitReady: true });
      try {
        const probe = await tab.evaluate(`(async () => {
          const d = window.__dioramaDebug;
          // Settle 2 warmup RAF frames so initial depth-map decode / tile composite finishes cleanly
          await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
          const t0 = performance.now();
          await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
          const twoFrameMs = performance.now() - t0;
          return {
            animTime: d ? d.animTime : null,
            simStats: d ? d.simStats : null,
            twoFrameMs,
          };
        })()`);
        assert(Number.isFinite(probe.animTime) && probe.animTime >= 0 && probe.animTime <= 1e9,
          `${q}: animTime out of clamped range [0, 1e9]: ${probe.animTime}`);
        assert(probe.simStats && Number.isFinite(probe.simStats.vehicles) && probe.simStats.vehicles > 0,
          `${q}: invalid simStats.vehicles: ${JSON.stringify(probe.simStats)}`);
        assert(probe.twoFrameMs < 800,
          `${q}: frame stall detected (2 RAF frames took ${probe.twoFrameMs.toFixed(1)} ms)`);
        assert(tab.exceptions.length === 0, `${q} exceptions: ${tab.exceptions.join('; ')}`);
        assert(tab.consoleErrors.length === 0, `${q} console.error: ${tab.consoleErrors.join('; ')}`);
      } finally {
        await harness.closeTab(tab);
      }
    }
  });

  // ── T4.10: Warmup Crosswalk Non-Freeze Across ?t=22, 35, 48 ──
  await test('T4.10', 'Hardening: ZVV buses advance cleanly across cold ?t=22, 35, 48 loads without crosswalk warmup freeze', async () => {
    const positions = [];
    for (const tVal of [22, 35, 48]) {
      const tab = await harness.openTab(`/?mode=day&zoom=2&follow=bus&t=${tVal}`, {
        width: 1280,
        height: 800,
        dpr: 2,
        waitReady: true,
      });
      try {
        await sleep(160);
        const uv = await tab.evaluate('(() => ({ u: window.__dioramaDebug.u, v: window.__dioramaDebug.v }))()');
        assert(Number.isFinite(uv.u) && Number.isFinite(uv.v), `Invalid bus follow UV at t=${tVal}: ${JSON.stringify(uv)}`);
        positions.push({ tVal, ...uv });
        assert(tab.exceptions.length === 0, `t=${tVal} exceptions: ${tab.exceptions.join('; ')}`);
      } finally {
        await harness.closeTab(tab);
      }
    }
    const d1 = Math.hypot(positions[1].u - positions[0].u, positions[1].v - positions[0].v);
    const d2 = Math.hypot(positions[2].u - positions[1].u, positions[2].v - positions[1].v);
    assert(
      d1 > 0.002 && d2 > 0.002,
      `Followed ZVV bus appears frozen across ?t=22/35/48: d(22->35)=${d1.toFixed(5)}, d(35->48)=${d2.toFixed(5)}, pos=${JSON.stringify(positions)}`,
    );
  });

  // ── T4.11: Follow: Train 2x Center Click & Human-Readable Road Inspector Titles ──
  await test('T4.11', 'Hardening: Follow: Train 2x center click selects SBB train & bus/car titles hide raw snake_case road IDs', async () => {
    // 1. Follow: Train center click at 2x must hit the SBB train (not a background house)
    const trainTab = await harness.openTab('/?mode=day&zoom=2&follow=train&t=22', {
      width: 1280,
      height: 800,
      dpr: 2,
      waitReady: true,
    });
    try {
      await sleep(220);
      const vp = await trainTab.evaluate(`(() => {
        const r = document.getElementById('viewport').getBoundingClientRect();
        return { x: r.left + r.width * 0.5, y: r.top + r.height * 0.5 };
      })()`);
      await trainTab.clickPoint(vp.x, vp.y);
      await sleep(180);
      const res = await trainTab.evaluate(`(() => ({
        title: (document.getElementById('insp-title') || {}).textContent || '',
        selectedBuilding: window.__dioramaDebug ? window.__dioramaDebug.selectedBuilding : null,
      }))()`);
      assert(
        /SBB\s+(S8|S24|IC)/i.test(res.title) && res.selectedBuilding === null,
        `Follow: Train center click at 2x missed train: title="${res.title}", selectedBuilding=${res.selectedBuilding}`,
      );
      assert(trainTab.exceptions.length === 0, `T4.11 train exceptions: ${trainTab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(trainTab);
    }

    // 2. Follow: Bus center click at 2x must show human-readable road name (no raw snake_case IDs)
    const busTab = await harness.openTab('/?mode=day&zoom=2&follow=bus&t=22', {
      width: 1280,
      height: 800,
      dpr: 2,
      waitReady: true,
    });
    try {
      await sleep(220);
      const vp = await busTab.evaluate(`(() => {
        const r = document.getElementById('viewport').getBoundingClientRect();
        return { x: r.left + r.width * 0.5, y: r.top + r.height * 0.5 };
      })()`);
      await busTab.clickPoint(vp.x, vp.y);
      await sleep(180);
      const title = await busTab.evaluate(`(document.getElementById('insp-title') || {}).textContent || ''`);
      assert(/ZVV\s+Bus/i.test(title), `Follow: Bus center click did not select ZVV bus: title="${title}"`);
      assert(
        !/(dorfstrasse_viaduct|seestrasse_|alte_landstrasse|a3_motorway)/i.test(title),
        `Raw snake_case road ID leaked into inspector title: "${title}"`,
      );
      assert(busTab.exceptions.length === 0, `T4.11 bus exceptions: ${busTab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(busTab);
    }
  });

  // ── T4.12: Mobile 390x844 .topbar Zero Horizontal Overflow ──
  await test('T4.12', 'Hardening: mobile 390x844 .topbar has zero horizontal overflow (scrollWidth <= clientWidth)', async () => {
    const tab = await harness.openTab('/?t=10', { width: 390, height: 844, dpr: 2, waitReady: true });
    try {
      await sleep(180);
      const m0 = await tab.evaluate(`(() => {
        const tb = document.getElementById('topbar');
        const tr = tb.getBoundingClientRect();
        return {
          tbScrollW: tb.scrollWidth,
          tbClientW: tb.clientWidth,
          tbLeft: Math.round(tr.left),
          tbRight: Math.round(tr.right),
          docScrollW: document.documentElement.scrollWidth,
          innerW: window.innerWidth,
        };
      })()`);
      assert(
        m0.tbScrollW <= m0.tbClientW,
        `Mobile .topbar horizontal overflow: scrollWidth=${m0.tbScrollW} > clientWidth=${m0.tbClientW}`,
      );
      assert(
        m0.docScrollW <= m0.innerW,
        `Mobile document horizontal overflow: scrollWidth=${m0.docScrollW} > innerWidth=${m0.innerW}`,
      );
      assert(m0.tbLeft === 0 && m0.tbRight <= m0.innerW + 1, `Mobile .topbar misaligned: ${JSON.stringify(m0)}`);

      // Open sidebar drawer and verify no horizontal shift
      await tab.clickSelector('#btn-toggle-sidebar');
      await sleep(220);
      const m1 = await tab.evaluate(`(() => {
        const tb = document.getElementById('topbar');
        const tr = tb.getBoundingClientRect();
        return { tbScrollW: tb.scrollWidth, tbClientW: tb.clientWidth, tbLeft: Math.round(tr.left) };
      })()`);
      assert(m1.tbScrollW <= m1.tbClientW && m1.tbLeft === 0,
        `Mobile .topbar shifted/overflowed after opening drawer: ${JSON.stringify(m1)}`);
      assert(tab.exceptions.length === 0, `T4.12 exceptions: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });
}

runNodeSuite({
  tier: 4,
  suiteName: 'tier4_journeys',
  runTests,
});
