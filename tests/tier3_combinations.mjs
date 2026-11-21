/**
 * Tier 3 (Node CDP): 10 Pairwise Cross-Feature Combination Suites (T3.01 - T3.10).
 */

import {
  ANIM_PAUSED_EXPR,
  SEARCH_RESULT_SELECTOR,
  analyzeVehicleRoofOpacity,
  assert,
  diffCanvasSamples,
  readGainValue,
  runNodeSuite,
  sleep,
  waitForSoundActive,
} from './lib/cdp_harness.mjs';

async function findSearchSelector(tab) {
  return tab.evaluate(`(() => {
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
}

async function captureShareUrl(tab) {
  // Install non-invasive clipboard capture before clicking Share button
  await tab.evaluate(`(() => {
    window.__e2eCapturedUrl = null;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        const orig = navigator.clipboard.writeText.bind(navigator.clipboard);
        navigator.clipboard.writeText = (txt) => {
          window.__e2eCapturedUrl = String(txt);
          return Promise.resolve();
        };
      } else {
        Object.defineProperty(navigator, 'clipboard', {
          configurable: true,
          value: { writeText: (txt) => { window.__e2eCapturedUrl = String(txt); return Promise.resolve(); } },
        });
      }
    } catch {}
  })()`);

  const sharePt = await tab.evaluate(`(() => {
    const btns = [...document.querySelectorAll('button, a')];
    const share = btns.find((b) => {
      const blob = ((b.id || '') + ' ' + (b.title || '') + ' ' + (b.getAttribute('aria-label') || '') + ' ' + (b.textContent || '')).toLowerCase();
      return /share|permalink|copy\\s*link|copy\\s*url/.test(blob) && b.getBoundingClientRect().width > 0;
    });
    if (!share) return null;
    const r = share.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  })()`);

  if (!sharePt) return null;
  await tab.clickPoint(sharePt.x, sharePt.y);
  await sleep(180);

  return tab.evaluate(`(() => {
    if (window.__e2eCapturedUrl) return window.__e2eCapturedUrl;
    if (window.location.search && window.location.search.includes('mode=')) return window.location.href;
    return null;
  })()`);
}

async function runTests(harness, test) {
  // ── T3.01: Lighting x Diurnal Living World (reuse single incognito context via same-tab navigate) ──
  await test('T3.01', 'Lighting x Diurnal Living World (day/sunset/night + animated motion)', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2&u=0.52&v=0.55&t=10', {
      width: 1280,
      height: 800,
      dpr: 1,
      waitReady: true,
    });
    let sDay10, sDay15, sSunset, sNight;
    let bodyDay, bodySunset, bodyNight;
    try {
      await sleep(200);
      bodyDay = await tab.evaluate(`document.body.dataset.mode`);
      sDay10 = await tab.captureCanvasSample('#diorama-canvas', 96, 54);

      await tab.navigate('/?mode=day&zoom=2&u=0.52&v=0.55&t=15', { waitReady: true });
      await sleep(200);
      sDay15 = await tab.captureCanvasSample('#diorama-canvas', 96, 54);

      await tab.navigate('/?mode=sunset&zoom=2&u=0.52&v=0.55&t=10', { waitReady: true });
      await sleep(200);
      bodySunset = await tab.evaluate(`document.body.dataset.mode`);
      sSunset = await tab.captureCanvasSample('#diorama-canvas', 96, 54);

      await tab.navigate('/?mode=night&zoom=2&u=0.52&v=0.55&t=10', { waitReady: true });
      await sleep(200);
      bodyNight = await tab.evaluate(`document.body.dataset.mode`);
      sNight = await tab.captureCanvasSample('#diorama-canvas', 96, 54);
    } finally {
      await harness.closeTab(tab);
    }

    const motionDay = diffCanvasSamples(sDay10, sDay15);
    assert(
      motionDay.maxDiff >= 10,
      `Living-world did not animate between ?t=10 and ?t=15 in day mode (maxDiff=${motionDay.maxDiff})`,
    );
    assert(
      sDay10.meanLuma > sSunset.meanLuma + 4 && sSunset.meanLuma > sNight.meanLuma + 4,
      `Preset canvas luminance not strictly ordered: day=${sDay10.meanLuma.toFixed(1)}, sunset=${sSunset.meanLuma.toFixed(1)}, night=${sNight.meanLuma.toFixed(1)}`,
    );
    assert(
      bodyDay === 'day' && bodySunset === 'sunset' && bodyNight === 'night',
      `body[data-mode] not synced across URL modes: day='${bodyDay}', sunset='${bodySunset}', night='${bodyNight}' (Contract #5)`,
    );
  });

  // ── T3.02: Zoom/Tiles x Depth Occlusion x Follow Camera (Train/Boat/Bus) ──
  await test('T3.02', 'Zoom/Tiles x Follow Camera (Train, Boat, Bus) streams tiles & tracks motion', async () => {
    const tab = await harness.openTab('/', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      tab.resetNetworkCounters();
      const labels = [];
      let bestMotionDiff = 0;
      let bestUvShift = 0;
      let checkedZoomedTarget = false;

      for (let i = 0; i < 4; i++) {
        await tab.clickSelector('#btn-follow');
        await sleep(160);
        const txt = await tab.evaluate(`document.getElementById('btn-follow')?.textContent?.trim() || ''`);
        labels.push(txt);
        if (/train|boat|bus/i.test(txt)) {
          // Wait briefly for F24 zoom ease-in to reach >= 1.4
          await tab.waitFor(
            `(() => {
              const d = typeof window.__dioramaDebug === 'function' ? window.__dioramaDebug() : window.__dioramaDebug;
              return Boolean(d && typeof d.scale === 'number' && d.scale >= 1.4);
            })()`,
            { timeoutMs: 800, intervalMs: 80 },
          );
          const dbg1 = await tab.getDebug();
          assert(
            dbg1 && typeof dbg1.scale === 'number' && dbg1.scale >= 1.4,
            `Follow '${txt}' expected zoomed scale >= 1.4, got ${dbg1?.scale} (Contract #5)`,
          );
          checkedZoomedTarget = true;

          // Measure motion across Follow targets (Train, Boat, Bus) so Bahnhof dwell never causes a flake
          if (bestMotionDiff < 8 && bestUvShift < 0.0005) {
            const f1 = await tab.captureCanvasSample('#diorama-canvas', 64, 36);
            await sleep(420);
            const f2 = await tab.captureCanvasSample('#diorama-canvas', 64, 36);
            const dbg2 = await tab.getDebug();
            const d = diffCanvasSamples(f1, f2);
            if (d.maxDiff > bestMotionDiff) bestMotionDiff = d.maxDiff;
            if (dbg2 && typeof dbg2.u === 'number' && typeof dbg2.v === 'number') {
              const uvShift = Math.hypot(dbg2.u - dbg1.u, dbg2.v - dbg1.v);
              if (uvShift > bestUvShift) bestUvShift = uvShift;
            }
          }
        }
      }

      assert(checkedZoomedTarget, `Follow cycle never entered Train/Boat/Bus: [${labels.join(', ')}]`);
      assert(
        bestMotionDiff >= 8 || bestUvShift >= 0.0005,
        `Follow Camera (Train/Boat/Bus) produced no live motion delta (bestMaxDiff=${bestMotionDiff}, bestUvShift=${bestUvShift.toFixed(5)})`,
      );
      assert(tab.tileResponses.length >= 1, `Follow Camera did not trigger HTTP 200 tile streaming (count=${tab.tileResponses.length})`);
      assert(labels.some((l) => /train/i.test(l)), `Follow cycle missing Train state: [${labels.join(', ')}]`);
      assert(labels.some((l) => /boat/i.test(l)), `Follow cycle missing Boat state: [${labels.join(', ')}]`);
      assert(labels.some((l) => /bus/i.test(l)), `Follow cycle missing Bus state (F20): [${labels.join(', ')}]`);
      assert(tab.exceptions.length === 0, `Follow Camera threw JS exception: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T3.03: Search x Building Inspector x Detail Plate "Fly Here" ──
  await test('T3.03', 'Search x Building Inspector x Detail Plate "Fly Here" end-to-end flow', async () => {
    const tab = await harness.openTab('/?t=10', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      const searchSel = await findSearchSelector(tab);
      assert(searchSel !== null, 'Address search input not found (F25)');

      await tab.typeText(searchSel, 'Schoorenstrasse 1');
      await sleep(200);
      const dbgSearch = await tab.getDebug();
      assert(
        dbgSearch && dbgSearch.searchResultCount >= 1,
        `Search for "Schoorenstrasse 1" returned ${dbgSearch?.searchResultCount} results`,
      );

      // Select first visible search result item or press Enter
      const clickedRes = await tab.evaluate(`(() => {
        const items = [...document.querySelectorAll(${JSON.stringify(SEARCH_RESULT_SELECTOR)})];
        const vis = items.find((el) => el.getBoundingClientRect().height > 0);
        if (!vis) return null;
        const r = vis.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })()`);
      if (clickedRes) {
        await tab.clickPoint(clickedRes.x, clickedRes.y);
      } else {
        await tab.pressKey('Enter', 'Enter', 13);
      }
      await tab.waitForCameraSettled();

      const inspTitle = await tab.evaluate(`document.getElementById('insp-title')?.textContent?.trim() || ''`);
      assert(
        /schoorenstrasse|lindt/i.test(inspTitle),
        `Selecting search result did not update inspector to Schoorenstrasse/Lindt (got '${inspTitle}')`,
      );

      // Open 2nd detail plate (Reformierte Kirche) and click "Fly Here"
      await tab.clickSelector('#crop-gallery .crop-thumb:nth-child(2)');
      await tab.waitFor(`!document.getElementById('modal-overlay')?.classList.contains('hidden')`, { timeoutMs: 2500 });
      await sleep(180);

      const flyPt = await tab.evaluate(`(() => {
        const box = document.getElementById('modal-overlay');
        const btn = [...box.querySelectorAll('button')].find((b) => /fly\\s*here/i.test(b.textContent || '') || /fly/i.test(b.id || ''));
        if (!btn) return null;
        const r = btn.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })()`);
      assert(flyPt !== null, 'Detail-plate modal missing "Fly Here" button (F25)');
      await tab.clickPoint(flyPt.x, flyPt.y);
      await tab.waitForCameraSettled();

      const modalClosed = await tab.evaluate(`document.getElementById('modal-overlay')?.classList.contains('hidden')`);
      assert(modalClosed, 'Clicking "Fly Here" did not close detail-plate modal');
      const dbgFly = await tab.getDebug();
      assert(dbgFly && dbgFly.activeLandmark, 'Clicking "Fly Here" did not update activeLandmark');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T3.04: Lighting x Spatial Audio (Day birds vs Night crickets, shore waves, bells) ──
  await test('T3.04', 'Lighting x Spatial Audio (Day birds > crickets, Night crickets > birds, bells)', async () => {
    const tab = await harness.openTab('/?mode=day', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      await tab.clickSelector('#btn-toggle-sound');
      const soundOn = await waitForSoundActive(tab, 6000);
      assert(soundOn, 'Sound failed to unlock via trusted click');

      const dbgInit = await tab.getDebug();
      assert(dbgInit && dbgInit.audioGains, 'window.__dioramaDebug.audioGains unavailable (Contract #5 / F26)');

      // Fly to Reformierte Kirche (2nd landmark, wooded village ridge + church bells) at 2x
      await tab.clickSelector('#landmark-list .lm-item:nth-child(2)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(350);
      const dayGains = (await tab.getDebug()).audioGains;
      const dayBirds = readGainValue(dayGains, 'birds');
      const dayCrickets = readGainValue(dayGains, 'crickets');
      const dayBells = readGainValue(dayGains, 'bells');
      assert(
        dayBirds > dayCrickets,
        `Day over wooded village expected birds > crickets, got birds=${dayBirds?.toFixed(4)}, crickets=${dayCrickets?.toFixed(4)}`,
      );
      assert(Number.isFinite(dayBells), 'Church bells channel missing/NaN');

      // Switch to Night -> crickets > birds
      await tab.clickSelector('#btn-mode-night');
      await sleep(550);
      const nightGains = (await tab.getDebug()).audioGains;
      const nightBirds = readGainValue(nightGains, 'birds');
      const nightCrickets = readGainValue(nightGains, 'crickets');
      assert(
        nightCrickets > nightBirds,
        `Night over village expected crickets > birds, got crickets=${nightCrickets?.toFixed(4)}, birds=${nightBirds?.toFixed(4)}`,
      );

      // Fly to shoreline (Schooren Seebad) at 2x -> waves higher than inland church ridge
      const inlandWaves = readGainValue(nightGains, 'lake_waves');
      await tab.clickSelector('#landmark-list .lm-item:nth-child(5)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(350);
      const shoreWaves = readGainValue((await tab.getDebug()).audioGains, 'lake_waves');
      assert(
        shoreWaves > Math.max((Number.isFinite(inlandWaves) ? inlandWaves : 0) * 2.5, 0.005),
        `Shore waves (${shoreWaves.toFixed(4)}) did not exceed inland ridge (${inlandWaves.toFixed(4)}) by >2.5x`,
      );
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T3.05: URL Deep-Link x Deterministic ?t= Rendering & Permalink Round-Trip ──
  await test('T3.05', 'URL Deep-Link x Deterministic ?t= rendering & Share Permalink round-trip', async () => {
    const urlA = '/?mode=sunset&zoom=2&u=0.52&v=0.55&t=10';
    const tab1 = await harness.openTab(urlA, { width: 1280, height: 800, dpr: 1, waitReady: true });
    let s1a, s1b, s15, shareUrl;
    try {
      await sleep(220);
      s1a = await tab1.captureCanvasSample('#diorama-canvas', 96, 54);
      await sleep(220);
      s1b = await tab1.captureCanvasSample('#diorama-canvas', 96, 54);
      shareUrl = await captureShareUrl(tab1);

      // Reuse same context to confirm ?t=10 vs ?t=15 differs deterministically at the same viewpoint
      await tab1.navigate('/?mode=sunset&zoom=2&u=0.52&v=0.55&t=15', { waitReady: true });
      await sleep(200);
      s15 = await tab1.captureCanvasSample('#diorama-canvas', 96, 54);
    } finally {
      await harness.closeTab(tab1);
    }

    const detDiff = diffCanvasSamples(s1a, s1b);
    assert(
      detDiff.meanAbsDiff < 1.0,
      `Fixed ?t=10 frame drifted across captures (meanAbsDiff=${detDiff.meanAbsDiff.toFixed(2)})`,
    );

    const diff10vs15 = diffCanvasSamples(s1a, s15);
    assert(
      diff10vs15.maxDiff >= 4,
      `Expected canvas motion delta between ?t=10 and ?t=15 (maxDiff=${diff10vs15.maxDiff})`,
    );

    assert(shareUrl && shareUrl.includes('mode='), `Share Permalink did not produce deep-link URL (got '${shareUrl}'; F25)`);

    // Open generated permalink in fresh incognito tab and assert state restores
    const parsed = new URL(shareUrl, harness.baseUrl);
    const rel = parsed.pathname + parsed.search;
    const tab2 = await harness.openTab(rel, { width: 1280, height: 800, dpr: 1, waitReady: true });
    try {
      const dbg = await tab2.getDebug();
      assert(dbg && dbg.mode === 'sunset', `Permalink tab mode expected 'sunset', got '${dbg?.mode}'`);
      assert(Math.abs(dbg.scale - 2.0) < 0.35, `Permalink tab scale expected ~2.0, got ${dbg.scale}`);
      assert(Math.abs(dbg.u - 0.52) < 0.06 && Math.abs(dbg.v - 0.55) < 0.06, `Permalink tab (u,v) mismatch: (${dbg.u}, ${dbg.v})`);
    } finally {
      await harness.closeTab(tab2);
    }
  });

  // ── T3.06: Cinema / Sidebar Collapse x Viewport Resize / Minimap Sync ──
  await test('T3.06', 'Cinema / Sidebar Collapse x Viewport Resize / Minimap Sync', async () => {
    const tab = await harness.openTab('/?t=10', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      const initVpW = await tab.evaluate(`document.getElementById('viewport').getBoundingClientRect().width`);

      // Collapse sidebar via toggle button or 'i'
      const toggleSel = await tab.evaluate(`(() => {
        const sels = [
          'button[aria-label*="sidebar" i]',
          'button[aria-label*="inspector" i]',
          'button[aria-label*="panel" i]',
          'button[title*="sidebar" i]',
          'button[title*="inspector" i]',
          '[id*="sidebar" i][id*="toggle" i]',
          '#btn-toggle-sidebar',
        ];
        for (const s of sels) {
          const el = document.querySelector(s);
          if (el && el.getBoundingClientRect().width > 0) return s;
        }
        return null;
      })()`);
      if (toggleSel) await tab.clickSelector(toggleSel);
      else {
        await tab.evaluate(`document.getElementById('viewport')?.focus()`);
        await tab.pressKey('i', 'KeyI', 73);
      }
      await sleep(200);
      const collapsedVpW = await tab.evaluate(`document.getElementById('viewport').getBoundingClientRect().width`);
      assert(collapsedVpW >= initVpW + 100, `Sidebar did not collapse before resize (${initVpW} -> ${collapsedVpW}; F22)`);

      // Resize viewport to 1024x700 DPR=2
      await tab.resize(1024, 700, 2, false);
      const resized = await tab.evaluate(`(() => {
        const vp = document.getElementById('viewport').getBoundingClientRect();
        const hud = document.getElementById('hud-coords').getBoundingClientRect();
        const dc = document.getElementById('diorama-canvas');
        return { vpBottom: vp.bottom, hudBottom: hud.bottom, dcW: dc.width, vpW: vp.width };
      })()`);
      assert(resized.vpBottom <= 701 && resized.hudBottom <= 701, `Clipping after resize to 1024x700: vp=${resized.vpBottom}, hud=${resized.hudBottom}`);

      // Enter & exit Cinema Mode
      await tab.pressKey('h', 'KeyH', 72);
      await sleep(160);
      assert(await tab.evaluate(`document.body.classList.contains('cinema-mode')`), 'Cinema Mode did not activate');
      await tab.pressKey('Escape', 'Escape', 27);
      await sleep(160);
      assert(!(await tab.evaluate(`document.body.classList.contains('cinema-mode')`)), 'Cinema Mode did not exit on Escape');

      // Verify both main canvas & minimap canvas remain painted & error-free
      const mainSample = await tab.captureCanvasSample('#diorama-canvas', 48, 27);
      const mmSample = await tab.captureCanvasSample('#minimap-canvas', 32, 16);
      assert(mainSample && mainSample.meanLuma > 5, 'Main canvas blank after resize + Cinema cycle');
      assert(mmSample && mmSample.meanLuma > 5, 'Minimap canvas blank after resize + Cinema cycle');
      assert(tab.exceptions.length === 0, `Exceptions during resize/cinema combo: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T3.07: Cross-tab deterministic fixed-timestep ?t=10 identity vs ?t=15 ──
  await test('T3.07', 'Deterministic fixed-timestep ?t=10 identity (canvas + simStats) across fresh tabs vs ?t=15', async () => {
    const url10 = '/?mode=day&zoom=2&u=0.52&v=0.55&t=10';
    const url15 = '/?mode=day&zoom=2&u=0.52&v=0.55&t=15';

    let sA = null;
    let simA = null;
    const tabA = await harness.openTab(url10, { width: 1280, height: 800, dpr: 1, waitReady: true });
    try {
      await sleep(220);
      sA = await tabA.captureCanvasSample('#diorama-canvas', 96, 54);
      simA = (await tabA.getDebug())?.simStats;
    } finally {
      await harness.closeTab(tabA);
    }

    const tabB = await harness.openTab(url10, { width: 1280, height: 800, dpr: 1, waitReady: true });
    try {
      await sleep(220);
      const sB = await tabB.captureCanvasSample('#diorama-canvas', 96, 54);
      const simB = (await tabB.getDebug())?.simStats;

      await tabB.navigate(url15, { waitReady: true });
      await sleep(220);
      const s15 = await tabB.captureCanvasSample('#diorama-canvas', 96, 54);
      const sim15 = (await tabB.getDebug())?.simStats;

      assert(simA && simB && sim15, 'window.__dioramaDebug.simStats missing across deterministic ?t= snapshots (v8.0 Contract #3)');

      const sameDiff = diffCanvasSamples(sA, sB);
      assert(
        sameDiff.meanAbsDiff < 1.0,
        `Non-deterministic ?t=10 canvas across fresh tabs: meanAbsDiff=${sameDiff.meanAbsDiff.toFixed(3)} >= 1.0`,
      );

      for (const k of ['vehicles', 'brakingCount', 'yieldingCount', 'pedestrians', 'boardingCount', 'activeTrips']) {
        assert(
          simA[k] === simB[k],
          `Non-deterministic simStats.${k} across fresh ?t=10 tabs: ${simA[k]} !== ${simB[k]}`,
        );
      }
      assert(
        Math.abs(simA.bellPhase - simB.bellPhase) < 1e-6,
        `Non-deterministic simStats.bellPhase across fresh ?t=10 tabs: ${simA.bellPhase} vs ${simB.bellPhase}`,
      );

      const motionDiff = diffCanvasSamples(sA, s15);
      assert(
        motionDiff.maxDiff >= 10,
        `Expected visible motion between ?t=10 and ?t=15, got maxDiff=${motionDiff.maxDiff}`,
      );
      assert(
        Math.abs(sim15.bellPhase - simA.bellPhase) > 0.01,
        `Expected bellPhase to advance between ?t=10 (${simA.bellPhase}) and ?t=15 (${sim15.bellPhase})`,
      );
      assert(tabB.exceptions.length === 0, `Exceptions during determinism test: ${tabB.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tabB);
    }
  });

  // ── T3.08: Diurnal activity shift across day / sunset / night ──
  await test('T3.08', 'Diurnal activity shift across Midday (day), Alpenglow (sunset), and Night (night)', async () => {
    const tab = await harness.openTab('/?mode=day&t=10', { width: 1280, height: 800, dpr: 1, waitReady: true });
    try {
      await sleep(200);
      const simDay = (await tab.getDebug())?.simStats;
      assert(simDay && typeof simDay === 'object', 'window.__dioramaDebug.simStats missing in day mode (v8.0 Contract #3)');

      await tab.navigate('/?mode=sunset&t=10', { waitReady: true });
      await sleep(200);
      const simSunset = (await tab.getDebug())?.simStats;
      assert(simSunset && typeof simSunset === 'object', 'window.__dioramaDebug.simStats missing in sunset mode');

      await tab.navigate('/?mode=night&t=10', { waitReady: true });
      await sleep(200);
      const simNight = (await tab.getDebug())?.simStats;
      assert(simNight && typeof simNight === 'object', 'window.__dioramaDebug.simStats missing in night mode');

      assert(
        simNight.vehicles < simDay.vehicles,
        `Expected night vehicles (${simNight.vehicles}) < day vehicles (${simDay.vehicles})`,
      );
      assert(
        simNight.pedestrians < simDay.pedestrians,
        `Expected night pedestrians (${simNight.pedestrians}) < day pedestrians (${simDay.pedestrians})`,
      );
      assert(simNight.vehicles >= 5, `Expected night village to remain alive with >=5 vehicles, got ${simNight.vehicles}`);
      assert(simNight.pedestrians >= 2, `Expected night village to remain alive with >=2 pedestrians, got ${simNight.pedestrians}`);
      assert(
        simSunset.vehicles > simNight.vehicles,
        `Expected sunset vehicles (${simSunset.vehicles}) > night vehicles (${simNight.vehicles})`,
      );
      assert(
        simSunset.pedestrians > simNight.pedestrians,
        `Expected sunset pedestrians (${simSunset.pedestrians}) > night pedestrians (${simNight.pedestrians})`,
      );
      assert(tab.exceptions.length === 0, `Exceptions during diurnal shift: ${tab.exceptions.join('; ')}`);
      assert(tab.consoleErrors.length === 0, `console.error during diurnal shift: ${tab.consoleErrors.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T3.09: Train & Bus 2x roof opacity + active foreground depth occlusion ──
  await test('T3.09', 'Train & Bus 2x roof opacity (no perforated cutouts) + active foreground depth occlusion', async () => {
    const tab = await harness.openTab('/?mode=day&t=10', { width: 1280, height: 800, dpr: 1, waitReady: true });
    try {
      const targets = [
        { kind: 'train', times: [14, 26], minVehPx: 120 },
        { kind: 'bus', times: [14, 26], minVehPx: 40 },
      ];

      for (const { kind, times, minVehPx } of targets) {
        let best = null;
        for (const t of times) {
          await tab.navigate(`/?mode=day&zoom=2&follow=${kind}&t=${t}`, { waitReady: true });
          await sleep(260);
          const dbgOn = await tab.getDebug();
          assert(dbgOn && dbgOn.followTarget === kind, `Expected followTarget='${kind}', got '${dbgOn?.followTarget}'`);
          assert(dbgOn.scale >= 1.8, `Expected zoom >= 1.8x for follow=${kind}, got ${dbgOn.scale}`);
          const dStats = dbgOn.depthStats || {};
          assert(
            (dStats.direct || 0) + (dStats.partial || 0) > 0,
            `Expected active depth-masked rendering for follow=${kind}, got depthStats=${JSON.stringify(dStats)}`,
          );

          const roiOn = await tab.captureCanvasRegion('#diorama-canvas', { cxFrac: 0.5, cyFrac: 0.5, boxW: 120, boxH: 80 });
          await tab.clickSelector('#btn-toggle-anim');
          await sleep(140);
          const roiOff = await tab.captureCanvasRegion('#diorama-canvas', { cxFrac: 0.5, cyFrac: 0.5, boxW: 120, boxH: 80 });
          await tab.clickSelector('#btn-toggle-anim');
          await sleep(100);

          const m = analyzeVehicleRoofOpacity(roiOn, roiOff, 14);
          if (!best || m.vehPixels > best.vehPixels) {
            best = { ...m, t };
          }
        }

        assert(
          best && best.vehPixels >= minVehPx,
          `Followed ${kind} rendered too few pixels at 2x zoom: vehPixels=${best?.vehPixels} < ${minVehPx}`,
        );
        assert(
          best.holeFrac < 0.06,
          `Perforated roof opacity cutouts on ${kind} at t=${best.t}: holeFrac=${(best.holeFrac * 100).toFixed(2)}% (interiorHoles=${best.interiorHoles}, vehPixels=${best.vehPixels})`,
        );
      }

      // Verify foreground building/tree depth occlusion is still genuinely active at overview
      await tab.navigate('/?mode=day&t=10', { waitReady: true });
      await sleep(220);
      const dbgFit = await tab.getDebug();
      const fitDepth = dbgFit?.depthStats || {};
      assert(
        (fitDepth.partial || 0) + (fitDepth.fullCull || 0) > 0,
        `Foreground depth occlusion appears disabled at overview: depthStats=${JSON.stringify(fitDepth)}`,
      );
      assert(tab.exceptions.length === 0, `Exceptions during roof opacity test: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T3.10: Church bell audio/visual phase sync + Live: Off audio updates ──
  await test('T3.10', 'Church bell audio/visual phase sync (bellPhase <-> audioGains.bells) + Live: Off audio', async () => {
    const tab = await harness.openTab('/?mode=day&t=10', { width: 1280, height: 800, dpr: 2, waitReady: true });
    try {
      await tab.clickSelector('#btn-toggle-sound');
      assert(await waitForSoundActive(tab, 6000), 'Audio failed to unlock at ?t=10');

      // Fly to Reformierte Kirche (landmark #2) and zoom 2x
      await tab.clickSelector('#landmark-list .lm-item:nth-child(2)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(300);

      const dbg10 = await tab.getDebug();
      assert(
        dbg10?.simStats && typeof dbg10.simStats.bellPhase === 'number' && dbg10.simStats.bellPhase >= 0 && dbg10.simStats.bellPhase < 1,
        `window.__dioramaDebug.simStats.bellPhase missing or invalid at ?t=10 (v8.0 Contract #3)`,
      );
      const phase10 = dbg10.simStats.bellPhase;
      const bells10 = readGainValue(dbg10.audioGains, 'bells');
      assert(
        Number.isFinite(bells10) && bells10 > 0.01,
        `Expected church bells audio active during ringing window ?t=10 (bellPhase=${phase10.toFixed(3)}), got audioGains.bells=${bells10}`,
      );

      // Navigate to silent half of 52s cycle (?t=35)
      await tab.navigate('/?mode=day&t=35', { waitReady: true });
      await tab.clickSelector('#btn-toggle-sound');
      assert(await waitForSoundActive(tab, 6000), 'Audio failed to unlock at ?t=35');
      await tab.clickSelector('#landmark-list .lm-item:nth-child(2)');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(300);

      const dbg35 = await tab.getDebug();
      assert(
        dbg35?.simStats && typeof dbg35.simStats.bellPhase === 'number',
        'simStats.bellPhase missing at ?t=35',
      );
      const phase35 = dbg35.simStats.bellPhase;
      const bells35 = readGainValue(dbg35.audioGains, 'bells');
      assert(
        Math.abs(phase35 - phase10) > 0.1,
        `bellPhase did not advance between ?t=10 (${phase10.toFixed(3)}) and ?t=35 (${phase35.toFixed(3)})`,
      );
      assert(
        bells35 < bells10 * 0.25,
        `Expected church bells quiet at ?t=35 (${bells35.toFixed(4)}) vs ringing ?t=10 (${bells10.toFixed(4)})`,
      );

      // Pause animations (Live: Off) and verify spatial audio still updates on mode switch
      await tab.clickSelector('#btn-toggle-anim');
      await sleep(160);
      assert(Boolean(await tab.evaluate(ANIM_PAUSED_EXPR)), 'Animations did not pause on #btn-toggle-anim');

      const beforePause = await tab.getDebug();
      const birdsDay = readGainValue(beforePause.audioGains, 'birds');
      const cricketsDay = readGainValue(beforePause.audioGains, 'crickets');

      await tab.clickSelector('#btn-mode-night');
      await sleep(450);
      const afterNight = await tab.getDebug();
      const birdsNight = readGainValue(afterNight.audioGains, 'birds');
      const cricketsNight = readGainValue(afterNight.audioGains, 'crickets');

      const delta = Math.abs(birdsNight - birdsDay) + Math.abs(cricketsNight - cricketsDay);
      assert(
        delta > 0.003,
        `Spatial audio did not update while Live: Off (birds ${birdsDay.toFixed(4)}->${birdsNight.toFixed(4)}, crickets ${cricketsDay.toFixed(4)}->${cricketsNight.toFixed(4)})`,
      );
      assert(tab.exceptions.length === 0, `Exceptions during bell sync test: ${tab.exceptions.join('; ')}`);
    } finally {
      await harness.closeTab(tab);
    }
  });
}

runNodeSuite({
  tier: 3,
  suiteName: 'tier3_combinations',
  runTests,
});
