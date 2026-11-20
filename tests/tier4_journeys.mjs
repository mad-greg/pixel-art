/**
 * Tier 4 (Node CDP): 6 Real-World End-User Application Journeys (T4.01 - T4.06).
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
}

runNodeSuite({
  tier: 4,
  suiteName: 'tier4_journeys',
  runTests,
});
