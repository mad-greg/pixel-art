/**
 * Tier 1 (Node CDP): FA3 Interactive Web App Feature Coverage (14 tests)
 *                  + FA4 Live Spatial Audio Feature Coverage (3 tests).
 */

import {
  assert,
  diffCanvasSamples,
  findMixerButtonPoint,
  parseZoomReadout,
  readGainValue,
  runNodeSuite,
  sleep,
  waitForSoundActive,
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

async function runTests(harness, test) {
  // ── Tab 1: Desktop 1280x800 DPR=2 for FA3 interactive feature checks ──
  const tab = await harness.openTab('/?t=10', {
    width: 1280,
    height: 800,
    dpr: 2,
    blockFonts: true,
    waitReady: true,
  });

  try {
    await test('T1.FA3.01', 'Clean desktop boot with zero JS/console/local-404 errors', async () => {
      assert(tab.exceptions.length === 0, `Uncaught JS exceptions: ${tab.exceptions.join('; ')}`);
      assert(tab.consoleErrors.length === 0, `console.error entries: ${tab.consoleErrors.join('; ')}`);
      assert(
        tab.localHttpErrors.length === 0,
        `Local HTTP >=400 errors: ${tab.localHttpErrors.map((e) => `${e.status} ${e.url}`).join('; ')}`,
      );
      assert(
        tab.localLoadFailures.length === 0,
        `Local load failures: ${tab.localLoadFailures.map((e) => `${e.errorText} ${e.url}`).join('; ')}`,
      );
      const sample = await tab.captureCanvasSample();
      assert(sample && sample.meanLuma > 5, `Canvas appears blank (meanLuma=${sample?.meanLuma})`);
    });

    await test('T1.FA3.02', 'Lighting presets update body[data-mode], buttons & canvas', async () => {
      const modes = [
        { id: '#btn-mode-day', mode: 'day' },
        { id: '#btn-mode-sunset', mode: 'sunset' },
        { id: '#btn-mode-night', mode: 'night' },
      ];
      const samples = {};
      const bodyModes = {};

      for (const m of modes) {
        await tab.clickSelector(m.id);
        await sleep(260);
        const state = await tab.evaluate(`({
          bodyMode: document.body.dataset.mode,
          activeBtn: document.querySelector('.seg-btn.active')?.dataset?.mode || null,
        })`);
        assert(
          state.activeBtn === m.mode,
          `Expected active .seg-btn '${m.mode}', got '${state.activeBtn}'`,
        );
        bodyModes[m.mode] = state.bodyMode;
        samples[m.mode] = await tab.captureCanvasSample();
      }

      // Restore day
      await tab.clickSelector('#btn-mode-day');
      await sleep(220);

      const dSunset = diffCanvasSamples(samples.day, samples.sunset);
      const dNight = diffCanvasSamples(samples.day, samples.night);
      assert(dSunset.meanAbsDiff > 3.0, `Day vs Sunset canvas diff too small (${dSunset.meanAbsDiff.toFixed(2)})`);
      assert(dNight.meanAbsDiff > 5.0, `Day vs Night canvas diff too small (${dNight.meanAbsDiff.toFixed(2)})`);

      for (const m of modes) {
        assert(
          bodyModes[m.mode] === m.mode,
          `document.body.dataset.mode expected '${m.mode}', got '${bodyModes[m.mode]}' (Contract #5)`,
        );
      }
    });

    await test('T1.FA3.03', 'Zoom presets (Fit, 1:1, 2x, 4x) update readout & stream tiles', async () => {
      tab.resetNetworkCounters();
      await tab.clickSelector('#btn-zoom-1x');
      await tab.waitForCameraSettled();
      const r1x = await tab.evaluate(`document.getElementById('zoom-readout')?.textContent?.trim() || ''`);

      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(160);
      const r2x = await tab.evaluate(`document.getElementById('zoom-readout')?.textContent?.trim() || ''`);
      const tilesAt2x = tab.tileResponses.length;

      await tab.clickSelector('#btn-zoom-4x');
      await tab.waitForCameraSettled();
      const r4x = await tab.evaluate(`document.getElementById('zoom-readout')?.textContent?.trim() || ''`);

      await tab.clickSelector('#btn-zoom-fit');
      await tab.waitForCameraSettled();
      const rFit = await tab.evaluate(`document.getElementById('zoom-readout')?.textContent?.trim() || ''`);

      assert(r1x && r2x && r4x && rFit, `Zoom readout empty: Fit='${rFit}', 1x='${r1x}', 2x='${r2x}', 4x='${r4x}'`);
      assert(r1x !== rFit, `Zoom readout did not change between Fit ('${rFit}') and 1:1 ('${r1x}')`);
      assert(r2x !== r1x && r4x !== r2x, `Zoom readouts not distinct: 1x='${r1x}', 2x='${r2x}', 4x='${r4x}'`);
      const nFit = parseZoomReadout(rFit);
      const n1x = parseZoomReadout(r1x);
      const n2x = parseZoomReadout(r2x);
      const n4x = parseZoomReadout(r4x);
      if (n1x !== null && n2x !== null && n4x !== null) {
        assert(
          n1x < n2x && n2x < n4x,
          `Zoom readout not monotonically increasing across 1:1/2x/4x: 1x='${r1x}'(${n1x}), 2x='${r2x}'(${n2x}), 4x='${r4x}'(${n4x})`,
        );
        if (nFit !== null) {
          assert(nFit < n1x, `Fit zoom readout (${nFit}) not < 1:1 (${n1x})`);
        }
      }
      assert(tilesAt2x >= 1, `Expected HTTP 200 tile streaming at 2x zoom, observed ${tilesAt2x} tiles`);
    });

    await test('T1.FA3.04', 'Landmarks render (>=10); clicking .lm-item flies & activates state', async () => {
      const count = await tab.evaluate(`document.querySelectorAll('#landmark-list .lm-item').length`);
      assert(count >= 10, `Expected >= 10 landmarks in #landmark-list, got ${count}`);

      const before = await tab.captureCanvasSample();
      await tab.clickSelector('#landmark-list .lm-item:nth-child(2)');
      await tab.waitForCameraSettled();
      const after = await tab.captureCanvasSample();
      const diff = diffCanvasSamples(before, after);
      assert(diff.meanAbsDiff > 2.0, `Clicking landmark #2 did not move viewport (diff=${diff.meanAbsDiff.toFixed(2)})`);

      const isActive = await tab.evaluate(`(() => {
        const el = document.querySelector('#landmark-list .lm-item:nth-child(2)');
        return Boolean(el && (el.classList.contains('active') || el.getAttribute('aria-current') === 'true'));
      })()`);
      assert(isActive, 'Clicked .lm-item did not gain .active or aria-current="true" (F25)');

      const dbg = await tab.getDebug();
      assert(dbg && dbg.activeLandmark, `window.__dioramaDebug.activeLandmark missing after landmark click`);
    });

    await test('T1.FA3.05', 'Building click updates inspector & sets selectedBuilding', async () => {
      // Navigate to Lindt HoC (1st landmark) & wait for F24 camera settle before clicking
      await tab.clickSelector('#landmark-list .lm-item:nth-child(1)');
      await tab.waitForCameraSettled();

      const titleBeforeClick = await tab.evaluate(`document.getElementById('insp-title')?.textContent?.trim() || ''`);
      const vp = await tab.evaluate(`(() => {
        const r = document.getElementById('viewport').getBoundingClientRect();
        return { x: r.left + r.width * 0.5, y: r.top + r.height * 0.5 };
      })()`);

      let title = titleBeforeClick;
      let dbg = null;
      const offsets = [
        [0, 0],
        [-30, -20],
        [35, 25],
        [-50, 30],
        [45, -35],
        [0, 40],
      ];
      for (const [dx, dy] of offsets) {
        await tab.clickPoint(vp.x + dx, vp.y + dy);
        await sleep(120);
        title = await tab.evaluate(`document.getElementById('insp-title')?.textContent?.trim() || ''`);
        dbg = await tab.getDebug();
        const hasSelBldg = dbg && dbg.selectedBuilding !== null && dbg.selectedBuilding !== undefined;
        const titleChanged = Boolean(title && !title.includes('Municipality of Kilchberg') && title !== titleBeforeClick);
        if (hasSelBldg || titleChanged) break;
      }

      const specs = await tab.evaluate(`document.getElementById('insp-specs')?.textContent?.trim() || ''`);
      assert(
        title && !title.includes('Municipality of Kilchberg'),
        `Clicking building on canvas did not update #insp-title (still '${title}')`,
      );
      assert(specs.length > 20, '#insp-specs empty after building click');
      assert(
        dbg && dbg.selectedBuilding !== null && dbg.selectedBuilding !== undefined,
        `window.__dioramaDebug.selectedBuilding not set after building click (title='${title}', before='${titleBeforeClick}', dbg=${dbg ? 'present' : 'null'})`,
      );
    });

    await test('T1.FA3.06', 'Instant address search across Kilchberg buildings & landmarks', async () => {
      const sel = await tab.evaluate(`(() => {
        const candidates = [
          'input[type="search"]',
          'input[placeholder*="search" i]',
          'input[placeholder*="address" i]',
          'input[aria-label*="search" i]',
          '#search-input',
        ];
        for (const s of candidates) {
          const el = document.querySelector(s);
          if (el) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return s;
          }
        }
        return null;
      })()`);
      assert(sel !== null, 'Instant address search input not found in UI (F25)');

      await tab.typeText(sel, 'Seestrasse');
      await sleep(180);
      const dbg1 = await tab.getDebug();
      assert(
        dbg1 && typeof dbg1.searchResultCount === 'number' && dbg1.searchResultCount > 0,
        `Expected searchResultCount > 0 for "Seestrasse", got ${dbg1?.searchResultCount}`,
      );

      await tab.typeText(sel, 'Schoorenstrasse 1');
      await sleep(180);
      const dbg2 = await tab.getDebug();
      assert(
        dbg2 && typeof dbg2.searchResultCount === 'number' && dbg2.searchResultCount >= 1,
        `Expected searchResultCount >= 1 for "Schoorenstrasse 1", got ${dbg2?.searchResultCount}`,
      );

      // Clear search box
      await tab.typeText(sel, '');
      await sleep(100);
    });

    await test('T1.FA3.07', 'Detail-plate modal opens, renders, has 1:1/2x/4x/Fit & Fly Here, closes on Esc', async () => {
      await tab.clickSelector('#crop-gallery .crop-thumb:first-child');
      const opened = await tab.waitFor(
        `(() => {
          const ov = document.getElementById('modal-overlay');
          if (!ov || ov.classList.contains('hidden')) return false;
          const c = document.getElementById('modal-canvas');
          if (!c || c.width < 10 || c.height < 10) return false;
          const ctx = c.getContext('2d');
          const d = ctx.getImageData(Math.floor(c.width / 2), Math.floor(c.height / 2), 2, 2).data;
          return (d[0] + d[1] + d[2]) > 0;
        })()`,
        { timeoutMs: 3000, intervalMs: 60 },
      );
      assert(Boolean(opened), 'Detail-plate modal (#modal-overlay) did not open & render canvas');

      const controls = await tab.evaluate(`(() => {
        const box = document.getElementById('modal-overlay');
        const btns = [...box.querySelectorAll('button')];
        const texts = btns.map((b) => (b.textContent || '').trim());
        const has1x = texts.some((t) => /1:1/i.test(t));
        const has2x = texts.some((t) => /2[x×]/i.test(t));
        const has4x = texts.some((t) => /4[x×]/i.test(t));
        const hasFit = texts.some((t) => /^fit$/i.test(t));
        const hasFlyHere = btns.some((b) => /fly\\s*here/i.test(b.textContent || '') || /fly/i.test(b.id || ''));
        return { has1x, has2x, has4x, hasFit, hasFlyHere, texts };
      })()`);

      await tab.pressKey('Escape', 'Escape', 27);
      await sleep(140);
      const closed = await tab.evaluate(`document.getElementById('modal-overlay')?.classList.contains('hidden')`);
      assert(closed, 'Modal did not close on Escape key');

      assert(controls.has1x && controls.has2x && controls.hasFit, `Missing standard modal zoom buttons: ${controls.texts.join(', ')}`);
      assert(controls.has4x, `Detail-plate modal missing 4x zoom button (F25): found [${controls.texts.join(', ')}]`);
      assert(controls.hasFlyHere, `Detail-plate modal missing "Fly Here" button (F25): found [${controls.texts.join(', ')}]`);
    });

    await test('T1.FA3.08', 'Cinema Mode hides chrome on H and restores on Escape', async () => {
      const before = await tab.evaluate(`({
        vpW: document.getElementById('viewport').getBoundingClientRect().width,
        sbW: document.getElementById('sidebar').getBoundingClientRect().width,
      })`);
      await tab.evaluate(`document.activeElement?.blur?.(); document.getElementById('viewport')?.focus?.();`);
      await tab.pressKey('h', 'KeyH', 72);
      await sleep(180);

      const onState = await tab.evaluate(`(() => {
        const sb = document.getElementById('sidebar');
        const sbRect = sb.getBoundingClientRect();
        const sbDisplay = getComputedStyle(sb).display;
        return {
          cinema: document.body.classList.contains('cinema-mode'),
          topbarH: document.getElementById('topbar').getBoundingClientRect().height,
          sbHidden: sbDisplay === 'none' || sbRect.width <= 2,
          sbW: sbRect.width,
          vpW: document.getElementById('viewport').getBoundingClientRect().width,
          exitVis: getComputedStyle(document.getElementById('btn-exit-cinema')).display !== 'none',
        };
      })()`);
      assert(onState.cinema, 'body.cinema-mode not added when pressing H');
      assert(onState.topbarH <= 2, `Topbar still visible in Cinema Mode (height=${onState.topbarH})`);
      assert(onState.sbHidden, `Sidebar still visible in Cinema Mode (width=${onState.sbW})`);
      assert(
        onState.vpW > before.vpW + 50,
        `Viewport did not widen in Cinema Mode (${before.vpW.toFixed(0)} -> ${onState.vpW.toFixed(0)})`,
      );
      assert(onState.exitVis, '#btn-exit-cinema not visible in Cinema Mode');

      await tab.pressKey('Escape', 'Escape', 27);
      await sleep(180);
      const offState = await tab.evaluate(`(() => {
        const sb = document.getElementById('sidebar');
        const sbRect = sb.getBoundingClientRect();
        return {
          cinema: document.body.classList.contains('cinema-mode'),
          topbarH: document.getElementById('topbar').getBoundingClientRect().height,
          sbRestored: getComputedStyle(sb).display !== 'none' && sbRect.width > 100,
          sbW: sbRect.width,
        };
      })()`);
      assert(!offState.cinema, 'body.cinema-mode not removed on Escape');
      assert(offState.topbarH > 20, `Topbar not restored after exiting Cinema Mode (height=${offState.topbarH})`);
      assert(offState.sbRestored, `Sidebar not restored after exiting Cinema Mode (width=${offState.sbW})`);
    });

    await test('T1.FA3.09', 'Collapsible sidebar collapses #sidebar & expands #viewport', async () => {
      const before = await tab.evaluate(`({
        vpW: document.getElementById('viewport').getBoundingClientRect().width,
        sbW: document.getElementById('sidebar').getBoundingClientRect().width,
      })`);

      // Try explicit toggle button first, then keyboard shortcut 'i'
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
          if (el) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return s;
          }
        }
        return null;
      })()`);

      if (toggleSel) {
        await tab.clickSelector(toggleSel);
      } else {
        // Focus viewport and press 'i'
        await tab.evaluate(`document.getElementById('viewport')?.focus()`);
        await tab.pressKey('i', 'KeyI', 73);
      }
      await sleep(220);

      const after = await tab.evaluate(`(() => {
        const sb = document.getElementById('sidebar');
        const sbRect = sb.getBoundingClientRect();
        const sbStyle = getComputedStyle(sb);
        const collapsed = sbStyle.display === 'none' || sbRect.width <= 4 || sbRect.left >= window.innerWidth - 2;
        return {
          vpW: document.getElementById('viewport').getBoundingClientRect().width,
          sbW: sbRect.width,
          collapsed,
        };
      })()`);

      // Restore if collapsed
      if (after.collapsed) {
        if (toggleSel) await tab.clickSelector(toggleSel);
        else await tab.pressKey('i', 'KeyI', 73);
        await sleep(160);
      }

      assert(after.collapsed, `Sidebar did not collapse (sbW=${before.sbW} -> ${after.sbW}; F22)`);
      assert(
        after.vpW >= before.vpW + 100,
        `Viewport did not expand when sidebar collapsed (vpW=${before.vpW} -> ${after.vpW}; F22)`,
      );
    });

    await test('T1.FA3.10', 'Swiss compass rose & dynamic metric scale bar scale with zoom', async () => {
      await tab.clickSelector('#btn-zoom-fit');
      await sleep(180);

      const hud = await tab.evaluate(`(() => {
        const compass = document.querySelector('[id*="compass" i], [class*="compass" i], [aria-label*="compass" i]');
        const compassVis = Boolean(compass && compass.getBoundingClientRect().width > 8 && getComputedStyle(compass).display !== 'none');

        const scaleEl = document.querySelector('[id*="scale-bar" i], [class*="scale-bar" i], [id*="scalebar" i], [aria-label*="scale" i], [id*="scale" i]:not(script)');
        const scaleVis = Boolean(scaleEl && scaleEl.getBoundingClientRect().width > 8 && getComputedStyle(scaleEl).display !== 'none');
        const scaleTextFit = scaleEl ? (scaleEl.textContent || '').trim() : '';
        return { compassVis, scaleVis, scaleTextFit };
      })()`);

      assert(hud.compassVis, 'Swiss cartographic compass rose not visible in viewport (F25)');
      assert(hud.scaleVis, 'Dynamic metric scale bar not visible in viewport (F25)');
      assert(/\d+\s*(m|km)\b/i.test(hud.scaleTextFit), `Scale bar text missing metric unit: '${hud.scaleTextFit}'`);

      await tab.clickSelector('#btn-zoom-2x');
      await sleep(200);
      const scaleText2x = await tab.evaluate(`(() => {
        const el = document.querySelector('[id*="scale-bar" i], [class*="scale-bar" i], [id*="scalebar" i], [aria-label*="scale" i], [id*="scale" i]:not(script)');
        return el ? (el.textContent || '').trim() : '';
      })()`);

      assert(
        scaleText2x !== hud.scaleTextFit,
        `Scale bar label did not update between Fit ('${hud.scaleTextFit}') and 2x ('${scaleText2x}')`,
      );
    });

    await test('T1.FA3.11', 'Share Permalink & Postcard PNG export controls present & error-free', async () => {
      const found = await tab.evaluate(`(() => {
        const btns = [...document.querySelectorAll('button, a')];
        const share = btns.find((b) => {
          const blob = ((b.id || '') + ' ' + (b.title || '') + ' ' + (b.getAttribute('aria-label') || '') + ' ' + (b.textContent || '')).toLowerCase();
          return /share|permalink|copy\\s*link|copy\\s*url/.test(blob) && b.getBoundingClientRect().width > 0;
        });
        const postcard = btns.find((b) => {
          const blob = ((b.id || '') + ' ' + (b.title || '') + ' ' + (b.getAttribute('aria-label') || '') + ' ' + (b.textContent || '')).toLowerCase();
          return /postcard|export|snapshot|png/.test(blob) && b.getBoundingClientRect().width > 0;
        });
        return {
          hasShare: Boolean(share),
          shareRect: share ? share.getBoundingClientRect().toJSON() : null,
          hasPostcard: Boolean(postcard),
        };
      })()`);

      assert(found.hasShare, 'Share Permalink control not found in UI (F25)');
      assert(found.hasPostcard, 'Postcard PNG export control not found in UI (F25)');

      const prevExc = tab.exceptions.length;
      const prevErr = tab.consoleErrors.length;
      await tab.clickPoint(found.shareRect.left + found.shareRect.width / 2, found.shareRect.top + found.shareRect.height / 2);
      await sleep(120);
      assert(tab.exceptions.length === prevExc, `Share click threw exception: ${tab.exceptions.slice(prevExc).join('; ')}`);
      assert(tab.consoleErrors.length === prevErr, `Share click logged console.error: ${tab.consoleErrors.slice(prevErr).join('; ')}`);
    });

    await test('T1.FA3.12', 'window.__dioramaDebug exposes all 13 Contract #5 keys with valid types', async () => {
      const dbg = await tab.getDebug();
      assert(dbg && typeof dbg === 'object', 'window.__dioramaDebug is missing or not an object (Contract #5)');
      const missing = REQUIRED_DEBUG_KEYS.filter((k) => !(k in dbg));
      assert(missing.length === 0, `window.__dioramaDebug missing keys: ${missing.join(', ')}`);
      assert(['day', 'sunset', 'night'].includes(dbg.mode), `Invalid debug.mode: ${dbg.mode}`);
      assert(typeof dbg.scale === 'number' && dbg.scale > 0, `Invalid debug.scale: ${dbg.scale}`);
      assert(typeof dbg.u === 'number' && typeof dbg.v === 'number', `Invalid debug u/v: ${dbg.u}, ${dbg.v}`);
      assert(typeof dbg.dpr === 'number' && dbg.dpr >= 1, `Invalid debug.dpr: ${dbg.dpr}`);
      assert(typeof dbg.audioEnabled === 'boolean', `Invalid debug.audioEnabled: ${dbg.audioEnabled}`);
      assert(typeof dbg.searchResultCount === 'number', `Invalid debug.searchResultCount: ${dbg.searchResultCount}`);
    });

    await test('T1.FA3.13', 'window.__dioramaDebug.simStats exposes v8.0 simulation telemetry with valid numeric fields', async () => {
      const dbg = await tab.getDebug();
      assert(dbg && typeof dbg === 'object', 'window.__dioramaDebug is missing or not an object (Contract #5)');
      const missingContract5 = REQUIRED_DEBUG_KEYS.filter((k) => !(k in dbg));
      assert(missingContract5.length === 0, `window.__dioramaDebug missing Contract #5 keys: ${missingContract5.join(', ')}`);
      assert(dbg.livingCounts && typeof dbg.livingCounts === 'object', 'window.__dioramaDebug.livingCounts missing');
      assert(dbg.depthStats && typeof dbg.depthStats === 'object', 'window.__dioramaDebug.depthStats missing');

      const sim = dbg.simStats;
      assert(sim && typeof sim === 'object', 'window.__dioramaDebug.simStats missing (v8.0 Contract #3)');

      const reqSimKeys = ['vehicles', 'brakingCount', 'yieldingCount', 'pedestrians', 'boardingCount', 'activeTrips', 'bellPhase'];
      const missingSim = reqSimKeys.filter((k) => typeof sim[k] !== 'number' || !Number.isFinite(sim[k]));
      assert(missingSim.length === 0, `simStats missing finite numeric keys: ${missingSim.join(', ')}`);

      assert(sim.vehicles > 0, `Expected simStats.vehicles > 0, got ${sim.vehicles}`);
      assert(sim.pedestrians > 0, `Expected simStats.pedestrians > 0, got ${sim.pedestrians}`);
      assert(sim.activeTrips > 0, `Expected simStats.activeTrips > 0, got ${sim.activeTrips}`);
      assert(sim.brakingCount >= 0 && sim.brakingCount <= sim.vehicles, `Invalid simStats.brakingCount=${sim.brakingCount} (vehicles=${sim.vehicles})`);
      assert(sim.yieldingCount >= 0 && sim.yieldingCount <= sim.vehicles, `Invalid simStats.yieldingCount=${sim.yieldingCount} (vehicles=${sim.vehicles})`);
      assert(sim.boardingCount >= 0, `Invalid simStats.boardingCount=${sim.boardingCount}`);
      assert(sim.bellPhase >= 0 && sim.bellPhase < 1, `Invalid simStats.bellPhase=${sim.bellPhase} (expected [0, 1))`);

      assert(tab.localHttpErrors.length === 0, `Local HTTP errors (ES module 404s): ${tab.localHttpErrors.map((e) => `${e.status} ${e.url}`).join('; ')}`);
      assert(tab.localLoadFailures.length === 0, `Local load failures: ${tab.localLoadFailures.map((e) => `${e.errorText} ${e.url}`).join('; ')}`);
      assert(tab.exceptions.length === 0, `Runtime JS exceptions: ${tab.exceptions.join('; ')}`);
    });

    await test('T1.FA3.14', 'v9.0 sidebar renders >=16 stops with dynamic count tag & >=10 detail plates (07..10 modal opens cleanly)', async () => {
      const snap = await tab.evaluate(`(() => {
        const lmCount = document.querySelectorAll('#landmark-list .lm-item').length;
        const stopTag = (document.querySelector('.tour-section .mono-tag')?.textContent || '').trim();
        const cropCount = document.querySelectorAll('#crop-gallery .crop-thumb').length;
        const cropSrcs = Array.from(document.querySelectorAll('#crop-gallery .crop-thumb img')).map(
          (img) => img.getAttribute('src') || '',
        );
        return { lmCount, stopTag, cropCount, cropSrcs };
      })()`);

      // Preconditions first: fail cleanly on v8.0 with AssertionError (zero selector/timeout errors)
      assert(snap.lmCount >= 16, `Expected >= 16 landmarks in #landmark-list (v9.0), got ${snap.lmCount}`);
      assert(
        new RegExp(`^${snap.lmCount}\\s+STOPS$`, 'i').test(snap.stopTag),
        `Expected dynamic stop-count tag '${snap.lmCount} STOPS', got '${snap.stopTag}'`,
      );
      assert(snap.cropCount >= 10, `Expected >= 10 detail plates in #crop-gallery (v9.0), got ${snap.cropCount}`);

      const expectedPlates = [
        '01_lindt_home_of_chocolate.webp',
        '02_reformierte_kirche_dorf.webp',
        '03_bendlikon_harbor_pier.webp',
        '04_bahnhof_kilchberg_weinberg.webp',
        '05_schooren_seebad.webp',
        '06_sanatorium_ridge.webp',
        '07_st_elisabeth_church.webp',
        '08_cf_meyer_haus.webp',
        '09_gemeindehaus_alte_landstrasse.webp',
        '10_stockengut_ridge_farm.webp',
      ];
      for (let i = 0; i < expectedPlates.length; i++) {
        const src = snap.cropSrcs[i] || '';
        assert(
          src.includes(expectedPlates[i]),
          `Plate index ${i} expected '${expectedPlates[i]}', got '${src}'`,
        );
      }

      const prevExc = tab.exceptions.length;
      const prevErr = tab.consoleErrors.length;
      const prevHttp = tab.localHttpErrors.length;
      const prevLoad = tab.localLoadFailures.length;

      await tab.clickSelector('#crop-gallery .crop-thumb:nth-child(7)');
      const modalReady = await tab.waitFor(
        `(() => {
          const ov = document.getElementById('modal-overlay');
          const cv = document.getElementById('modal-canvas');
          if (!ov || ov.classList.contains('hidden') || !cv || cv.width < 10 || cv.height < 10) return false;
          const ctx = cv.getContext('2d');
          const p = ctx.getImageData(Math.floor(cv.width / 2), Math.floor(cv.height / 2), 1, 1).data;
          return (p[0] + p[1] + p[2]) > 0;
        })()`,
        { timeoutMs: 3000, intervalMs: 60 },
      );
      assert(modalReady, 'New v9.0 detail plate #7 modal failed to open or render pixels on #modal-canvas');

      const modalTitle = await tab.evaluate(`(document.getElementById('modal-title')?.textContent || '').trim()`);
      assert(modalTitle.length > 0, 'Plate #7 modal #modal-title is empty');

      await tab.pressKey('Escape', 'Escape', 27);
      await sleep(140);
      const modalClosed = await tab.evaluate(
        `Boolean(document.getElementById('modal-overlay')?.classList.contains('hidden'))`,
      );
      assert(modalClosed, 'Plate #7 modal did not close on Escape');

      assert(tab.exceptions.length === prevExc, `New JS exceptions on plate #7 modal: ${tab.exceptions.slice(prevExc).join('; ')}`);
      assert(tab.consoleErrors.length === prevErr, `New console errors on plate #7 modal: ${tab.consoleErrors.slice(prevErr).join('; ')}`);
      assert(tab.localHttpErrors.length === prevHttp, `New HTTP errors on plate #7 modal: ${tab.localHttpErrors.slice(prevHttp).map((e) => `${e.status} ${e.url}`).join('; ')}`);
      assert(tab.localLoadFailures.length === prevLoad, `New load failures on plate #7 modal: ${tab.localLoadFailures.slice(prevLoad).map((e) => `${e.errorText} ${e.url}`).join('; ')}`);
    });
  } finally {
    await harness.closeTab(tab);
  }

  // ── Tab 2: Fresh Desktop tab for FA4 live spatial audio checks ──
  const audioTab = await harness.openTab('/', {
    width: 1280,
    height: 800,
    dpr: 2,
    blockFonts: true,
    waitReady: true,
  });

  try {
    await test('T1.FA4.03', 'Trusted click on #btn-toggle-sound unlocks AudioContext & decodes 9/9 MP3s', async () => {
      audioTab.resetNetworkCounters();
      await audioTab.clickSelector('#btn-toggle-sound');

      // Wait for sound toggle active state + 9/9 MP3 loads
      const soundOn = await waitForSoundActive(audioTab, 6000, { minMp3Count: 9 });
      const btnText = await audioTab.evaluate(`document.getElementById('btn-toggle-sound')?.textContent?.trim()`);
      assert(soundOn, `Sound toggle did not activate after trusted click (text='${btnText}')`);

      const uniqueAudio = new Set(audioTab.audioResponses.map((r) => new URL(r.url).pathname));
      assert(uniqueAudio.size >= 9, `Expected 9/9 MP3 HTTP 200 loads, got ${uniqueAudio.size}`);
      assert(audioTab.exceptions.length === 0, `JS exceptions during audio unlock: ${audioTab.exceptions.join('; ')}`);
      assert(audioTab.consoleErrors.length === 0, `console.error during audio unlock: ${audioTab.consoleErrors.join('; ')}`);

      const dbg = await audioTab.getDebug();
      assert(dbg && typeof dbg === 'object', 'Audio loaded 9/9 MP3s, but window.__dioramaDebug missing to verify AudioContext state');
      assert(dbg.audioEnabled === true, `Expected debug.audioEnabled === true, got ${dbg.audioEnabled}`);
      assert(dbg.audioState === 'running', `Expected AudioContext state === 'running' after trusted click, got '${dbg.audioState}'`);
    });

    await test('T1.FA4.04', 'window.__dioramaDebug.audioGains exposes live spatial audio channels', async () => {
      const dbg = await audioTab.getDebug();
      assert(dbg && dbg.audioGains && typeof dbg.audioGains === 'object', 'window.__dioramaDebug.audioGains missing (Contract #5)');
      const gains = dbg.audioGains;
      const requiredChannels = ['lake_waves', 'birds', 'crickets', 'traffic', 'town_traffic', 'train', 'bells'];
      const missing = requiredChannels.filter((ch) => !Number.isFinite(readGainValue(gains, ch)));
      assert(missing.length === 0, `audioGains missing finite numeric channels: ${missing.join(', ')}`);
    });

    await test('T1.FA4.05', 'Collapsible audio layer mixer popover opens with >=4 channel sliders', async () => {
      const mixerPt = await findMixerButtonPoint(audioTab);
      assert(mixerPt !== null, 'Audio layer mixer popover trigger button not found (F26)');

      await audioTab.clickPoint(mixerPt.x, mixerPt.y);
      await sleep(160);

      const sliderCount = await audioTab.evaluate(`(() => {
        const sliders = [...document.querySelectorAll('input[type="range"]')];
        return sliders.filter((s) => s.getBoundingClientRect().width > 0).length;
      })()`);
      assert(sliderCount >= 4, `Expected >=4 visible audio mixer sliders (input[type="range"]), got ${sliderCount} (F26)`);
    });
  } finally {
    await harness.closeTab(audioTab);
  }
}

runNodeSuite({
  tier: 1,
  suiteName: 'tier1_browser_features',
  runTests,
});
