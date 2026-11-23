/**
 * Tier 2 (Node CDP): v13.0 Modular Living Layer Registry, Determinism, Diurnal Adaptation,
 * Inspectables & Audio Integration, 60fps Frame Budget & Dynamic Extensibility (T2.V13.L01–T2.V13.L06).
 */

import {
  assert,
  diffCanvasSamples,
  readGainValue,
  runNodeSuite,
  sleep,
  waitForSoundActive,
} from './lib/cdp_harness.mjs';

const EXPECTED_AUDIO_CHANNELS = [
  'lake_waves',
  'birds',
  'crickets',
  'traffic',
  'town_traffic',
  'train',
  'bus',
  'boat',
  'bells',
];

const RAW_ID_RE = /^[a-z0-9]+_[a-z0-9_]+$/;
const RAW_ROAD_FRAGMENT_RE = /(_road_|_seg_|_node_|dorfstrasse_viaduct|seestrasse_|alte_landstrasse|a3_motorway)/i;

async function dispatchFastDrag(tab, startX, startY, totalDx, totalDy, steps = 6, stepMs = 12) {
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

async function waitForTilesReady(tab, timeoutMs = 2500) {
  await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });
  await tab.waitFor(
    `(() => {
      const d = window.__dioramaDebug;
      return Boolean(d && (!d.frameStats || d.frameStats.tileInflight === 0));
    })()`,
    { timeoutMs, intervalMs: 80 },
  );
  await sleep(220);
}

function assertCleanTab(tab, label) {
  assert(
    tab.exceptions.length === 0,
    `${label}: JS exceptions detected: ${tab.exceptions.join('; ')}`,
  );
  assert(
    tab.consoleErrors.length === 0,
    `${label}: console.error detected: ${tab.consoleErrors.join('; ')}`,
  );
  assert(
    tab.localHttpErrors.length === 0,
    `${label}: local HTTP >=400 errors: ${tab.localHttpErrors.map((e) => `${e.status} ${e.url}`).join('; ')}`,
  );
  assert(
    tab.localLoadFailures.length === 0,
    `${label}: local load failures: ${tab.localLoadFailures.map((e) => `${e.errorText} ${e.url}`).join('; ')}`,
  );
}

async function runTests(harness, test) {
  // ── T2.V13.L01: Modular Living Registry & Plugin Lifecycle ──
  await test('T2.V13.L01', 'Modular Living Registry exposes >=10 unique plugins & valid lifecycle telemetry', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2&t=10', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await sleep(240);
      const dbg = await tab.getDebug();
      assert(dbg && typeof dbg === 'object', 'window.__dioramaDebug missing');

      const lr = dbg.livingRegistry;
      assert(
        lr && typeof lr === 'object' && !Array.isArray(lr),
        `window.__dioramaDebug.livingRegistry missing or not an object (got ${typeof lr})`,
      );
      assert(
        typeof lr.pluginCount === 'number' && Number.isInteger(lr.pluginCount) && lr.pluginCount >= 10,
        `livingRegistry.pluginCount must be an integer >= 10, got ${lr.pluginCount}`,
      );
      assert(
        Array.isArray(lr.pluginIds) && lr.pluginIds.length === lr.pluginCount,
        `livingRegistry.pluginIds must be an array of length ${lr.pluginCount}, got ${JSON.stringify(lr.pluginIds)}`,
      );
      const uniqueIds = new Set();
      for (const id of lr.pluginIds) {
        assert(
          typeof id === 'string' && id.trim().length > 0,
          `livingRegistry.pluginIds contains invalid entry: ${JSON.stringify(id)}`,
        );
        uniqueIds.add(id);
      }
      assert(
        uniqueIds.size === lr.pluginIds.length,
        `livingRegistry.pluginIds contains duplicate IDs: ${lr.pluginIds.join(', ')}`,
      );

      assert(
        Array.isArray(lr.enabledPlugins) && lr.enabledPlugins.length >= 10,
        `livingRegistry.enabledPlugins must have length >= 10, got ${Array.isArray(lr.enabledPlugins) ? lr.enabledPlugins.length : typeof lr.enabledPlugins}`,
      );
      for (const eid of lr.enabledPlugins) {
        assert(
          uniqueIds.has(eid),
          `livingRegistry.enabledPlugins contains unregistered plugin id '${eid}'`,
        );
      }

      assert(
        typeof lr.updateMs === 'number' && Number.isFinite(lr.updateMs) && lr.updateMs >= 0,
        `livingRegistry.updateMs must be finite >= 0, got ${lr.updateMs}`,
      );
      assert(
        typeof lr.drawMs === 'number' && Number.isFinite(lr.drawMs) && lr.drawMs >= 0,
        `livingRegistry.drawMs must be finite >= 0, got ${lr.drawMs}`,
      );
      assert(
        typeof lr.drawablesCount === 'number' && Number.isInteger(lr.drawablesCount) && lr.drawablesCount > 0,
        `livingRegistry.drawablesCount must be an integer > 0, got ${lr.drawablesCount}`,
      );
      assert(
        typeof lr.inspectablesCount === 'number' && Number.isInteger(lr.inspectablesCount) && lr.inspectablesCount > 0,
        `livingRegistry.inspectablesCount must be an integer > 0, got ${lr.inspectablesCount}`,
      );

      assert(
        lr.perPluginCounts && typeof lr.perPluginCounts === 'object' && !Array.isArray(lr.perPluginCounts),
        `livingRegistry.perPluginCounts must be a plain object, got ${typeof lr.perPluginCounts}`,
      );
      const countEntries = Object.entries(lr.perPluginCounts);
      assert(
        countEntries.length > 0,
        'livingRegistry.perPluginCounts must be non-empty',
      );
      for (const [id, val] of countEntries) {
        assert(
          uniqueIds.has(id),
          `livingRegistry.perPluginCounts contains unregistered plugin ID '${id}'`,
        );
        if (typeof val === 'number') {
          assert(
            Number.isInteger(val) && val >= 0,
            `livingRegistry.perPluginCounts['${id}'] numeric count must be a non-negative integer, got ${val}`,
          );
        } else {
          assert(
            val !== null && typeof val === 'object' && !Array.isArray(val),
            `livingRegistry.perPluginCounts['${id}'] must be a non-negative integer or plain object of counts, got ${JSON.stringify(val)}`,
          );
          for (const [subKey, subVal] of Object.entries(val)) {
            assert(
              typeof subVal === 'number' && Number.isFinite(subVal) && subVal >= 0,
              `livingRegistry.perPluginCounts['${id}']['${subKey}'] must be a finite non-negative number, got ${subVal}`,
            );
          }
        }
      }

      assertCleanTab(tab, 'T2.V13.L01');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T2.V13.L02: Deterministic ?t= Across All Living Plugins ──
  await test('T2.V13.L02', 'Deterministic ?t=10 produces byte-identical canvas & perPluginCounts; ?t=15 advances cleanly', async () => {
    const captureAt = async (tVal, label) => {
      const tab = await harness.openTab(`/?mode=day&zoom=2&landmark=bendlikon_pier&t=${tVal}`, {
        width: 1280,
        height: 800,
        dpr: 2,
        blockFonts: true,
        waitReady: true,
      });
      try {
        await waitForTilesReady(tab);
        const sample = await tab.captureCanvasSample('#diorama-canvas', 160, 100);
        const dbg = await tab.getDebug();
        assertCleanTab(tab, label);
        return { sample, dbg };
      } finally {
        await harness.closeTab(tab);
      }
    };

    const run1 = await captureAt(10, 'T2.V13.L02(t=10 #1)');
    const run2 = await captureAt(10, 'T2.V13.L02(t=10 #2)');

    assert(run1.sample && run1.sample.meanLuma > 5, 'Canvas blank on first ?t=10 capture');
    assert(run2.sample && run2.sample.meanLuma > 5, 'Canvas blank on second ?t=10 capture');
    assert(
      run1.dbg?.livingRegistry && run2.dbg?.livingRegistry,
      'window.__dioramaDebug.livingRegistry missing during determinism check',
    );

    const diffSame = diffCanvasSamples(run1.sample, run2.sample);
    assert(
      diffSame.maxDiff === 0,
      `Non-deterministic ?t=10 canvas across living plugins: maxDiff=${diffSame.maxDiff}, changedFrac=${diffSame.changedFrac}, meanAbsDiff=${diffSame.meanAbsDiff}`,
    );

    const counts1 = JSON.stringify(run1.dbg.livingRegistry.perPluginCounts);
    const counts2 = JSON.stringify(run2.dbg.livingRegistry.perPluginCounts);
    assert(
      counts1 === counts2,
      `Non-deterministic livingRegistry.perPluginCounts at ?t=10: ${counts1} vs ${counts2}`,
    );

    for (const k of ['vehicles', 'pedestrians', 'activeTrips', 'bellPhase']) {
      assert(
        run1.dbg.simStats?.[k] === run2.dbg.simStats?.[k],
        `Non-deterministic simStats.${k} at ?t=10: ${run1.dbg.simStats?.[k]} vs ${run2.dbg.simStats?.[k]}`,
      );
    }

    const run3 = await captureAt(15, 'T2.V13.L02(t=15)');
    assert(run3.sample && run3.sample.meanLuma > 5, 'Canvas blank on ?t=15 capture');
    const diffLater = diffCanvasSamples(run1.sample, run3.sample);
    assert(
      diffLater.maxDiff > 0 && diffLater.changedFrac > 0,
      `Canvas did not advance between ?t=10 and ?t=15 (maxDiff=${diffLater.maxDiff}, changedFrac=${diffLater.changedFrac}, meanAbsDiff=${diffLater.meanAbsDiff})`,
    );
  });

  // ── T2.V13.L03: Diurnal Living Adaptation (day / sunset / night) ──
  await test('T2.V13.L03', 'Diurnal living adaptation across day, sunset & night modes (SUPs, traffic, pedestrians, active plugins)', async () => {
    const readMode = async (mode) => {
      const tab = await harness.openTab(`/?mode=${mode}&t=10`, {
        width: 1280,
        height: 800,
        dpr: 2,
        blockFonts: true,
        waitReady: true,
      });
      try {
        await sleep(260);
        const dbg = await tab.getDebug();
        assertCleanTab(tab, `T2.V13.L03(${mode})`);
        return dbg;
      } finally {
        await harness.closeTab(tab);
      }
    };

    const dayDbg = await readMode('day');
    const sunsetDbg = await readMode('sunset');
    const nightDbg = await readMode('night');

    for (const [m, d] of [['day', dayDbg], ['sunset', sunsetDbg], ['night', nightDbg]]) {
      assert(d && d.mode === m, `Expected mode='${m}', got '${d?.mode}'`);
      assert(
        d.livingRegistry && d.livingRegistry.pluginCount >= 10 && d.livingRegistry.drawablesCount > 0,
        `${m}: livingRegistry missing or inactive (pluginCount=${d.livingRegistry?.pluginCount}, drawablesCount=${d.livingRegistry?.drawablesCount})`,
      );
      assert(d.simStats && typeof d.simStats === 'object', `${m}: simStats missing`);
      assert(d.livingCounts && typeof d.livingCounts === 'object', `${m}: livingCounts missing`);
    }

    // Daytime SUPs & active outdoor life
    assert(
      dayDbg.livingCounts.sups >= 2,
      `Expected daytime livingCounts.sups >= 2, got ${dayDbg.livingCounts.sups}`,
    );

    // Night calm: zero SUPs, strict pedestrian diurnal ordering, calm traffic, active warm night plugins
    assert(
      nightDbg.livingCounts.sups === 0,
      `Expected night livingCounts.sups === 0, got ${nightDbg.livingCounts.sups}`,
    );
    assert(
      nightDbg.simStats.pedestrians >= 2,
      `Expected night simStats.pedestrians >= 2, got ${nightDbg.simStats.pedestrians}`,
    );
    assert(
      nightDbg.simStats.pedestrians < sunsetDbg.simStats.pedestrians &&
        sunsetDbg.simStats.pedestrians < dayDbg.simStats.pedestrians,
      `Expected night < sunset < day pedestrians, got night=${nightDbg.simStats.pedestrians}, sunset=${sunsetDbg.simStats.pedestrians}, day=${dayDbg.simStats.pedestrians}`,
    );
    assert(
      nightDbg.simStats.vehicles <= dayDbg.simStats.vehicles,
      `Expected night vehicles <= day vehicles, got night=${nightDbg.simStats.vehicles}, day=${dayDbg.simStats.vehicles}`,
    );
    assert(
      Array.isArray(nightDbg.livingRegistry.enabledPlugins) && nightDbg.livingRegistry.enabledPlugins.length >= 10,
      `Expected active night plugins >= 10, got ${nightDbg.livingRegistry.enabledPlugins?.length}`,
    );
  });

  // ── T2.V13.L04: Living Inspectables & Audio Signals Integration ──
  await test('T2.V13.L04', 'Living inspectables show human-readable titles (zero raw snake_case IDs) & shore-strict audioGains', async () => {
    // Part A: Inspectables count at Bendlikon Pier + interactive click inspection of live train & bus
    const pierTab = await harness.openTab('/?mode=day&zoom=2&landmark=bendlikon_pier&t=10', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await sleep(220);
      const dbg = await pierTab.getDebug();
      assert(
        dbg?.livingRegistry && Number.isInteger(dbg.livingRegistry.inspectablesCount) && dbg.livingRegistry.inspectablesCount > 0,
        `Expected livingRegistry.inspectablesCount > 0 at Bendlikon Pier, got ${dbg?.livingRegistry?.inspectablesCount}`,
      );
      assertCleanTab(pierTab, 'T2.V13.L04(pier)');
    } finally {
      await harness.closeTab(pierTab);
    }

    for (const followKind of ['train', 'bus']) {
      const fTab = await harness.openTab(`/?mode=day&zoom=2&follow=${followKind}&t=22`, {
        width: 1280,
        height: 800,
        dpr: 2,
        blockFonts: true,
        waitReady: true,
      });
      try {
        await sleep(240);
        const vp = await fTab.evaluate(`(() => {
          const r = document.getElementById('viewport').getBoundingClientRect();
          return { x: r.left + r.width * 0.5, y: r.top + r.height * 0.5 };
        })()`);
        await fTab.clickPoint(vp.x, vp.y);
        await sleep(180);
        const insp = await fTab.evaluate(`(() => ({
          title: (document.getElementById('insp-title')?.textContent || '').trim(),
          sub: (document.getElementById('insp-sub')?.textContent || '').trim(),
          selectedBuilding: window.__dioramaDebug ? window.__dioramaDebug.selectedBuilding : null,
          selectedEntity: window.__dioramaDebug ? window.__dioramaDebug.selectedEntity : null,
        }))()`);
        assert(
          typeof insp.selectedEntity === 'string' && insp.selectedEntity.length > 0,
          `Clicking followed living '${followKind}' did not hit an inspectable entity (selectedEntity=${JSON.stringify(insp.selectedEntity)})`,
        );
        assert(
          insp.title.length > 0,
          `Inspecting living '${followKind}' left #insp-title empty`,
        );
        assert(
          !RAW_ID_RE.test(insp.title) && !RAW_ROAD_FRAGMENT_RE.test(insp.title),
          `Raw snake_case ID leaked into inspector title for '${followKind}': "${insp.title}"`,
        );
        assert(
          !RAW_ID_RE.test(insp.sub) && !RAW_ROAD_FRAGMENT_RE.test(insp.sub),
          `Raw snake_case ID leaked into inspector subtitle for '${followKind}': "${insp.sub}"`,
        );
        assertCleanTab(fTab, `T2.V13.L04(follow=${followKind})`);
      } finally {
        await harness.closeTab(fTab);
      }
    }

    // Part B: Spatial audio signals integration & shore-strictness with living plugins active
    const audioTab = await harness.openTab('/?mode=day&zoom=2&landmark=bendlikon_pier', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await audioTab.clickSelector('#btn-toggle-sound');
      const unlocked = await waitForSoundActive(audioTab, 6000);
      assert(unlocked, 'Trusted click on #btn-toggle-sound failed to unlock spatial audio');
      await audioTab.waitForCameraSettled();
      await sleep(360);

      const dbgShore = await audioTab.getDebug();
      assert(
        dbgShore?.livingRegistry && dbgShore.livingRegistry.pluginCount >= 10,
        'livingRegistry missing while spatial audio is active',
      );
      assert(
        dbgShore.audioGains && typeof dbgShore.audioGains === 'object',
        'window.__dioramaDebug.audioGains missing',
      );

      for (const ch of EXPECTED_AUDIO_CHANNELS) {
        const g = readGainValue(dbgShore.audioGains, ch);
        assert(
          Number.isFinite(g) && g >= 0 && g <= 1,
          `audioGains['${ch}'] must be finite in [0, 1], got ${g}`,
        );
      }

      const gShore = readGainValue(dbgShore.audioGains, 'lake_waves');
      assert(
        gShore > 0.005,
        `Expected audible near-shore lake_waves at bendlikon_pier (>0.005), got ${gShore.toFixed(4)}`,
      );

      // Fly inland to Sanatorium Kilchberg ridge (landmark #6) at 2x zoom
      const clickedInland = await audioTab.evaluate(`(() => {
        const items = Array.from(document.querySelectorAll('#landmark-list .lm-item'));
        const target = items.find((el) => /sanatorium/i.test(el.textContent || '')) || items[5];
        if (!target) return false;
        target.click();
        return true;
      })()`);
      assert(clickedInland, 'Could not find Sanatorium Ridge landmark in #landmark-list');
      await audioTab.waitForCameraSettled();
      await audioTab.clickSelector('#btn-zoom-2x');
      await audioTab.waitForCameraSettled();
      await sleep(380);

      const dbgInland = await audioTab.getDebug();
      const gInland = readGainValue(dbgInland?.audioGains, 'lake_waves');
      assert(
        Number.isFinite(gInland) && gInland >= 0 && gInland <= 1,
        `Inland lake_waves gain not finite in [0, 1]: ${gInland}`,
      );
      assert(
        gShore > gInland * 2.5,
        `Shore-strict lake_waves violated with living plugins active: gShore=${gShore.toFixed(4)} vs gInland=${gInland.toFixed(4)} (need >2.5x)`,
      );

      assertCleanTab(audioTab, 'T2.V13.L04(audio)');
    } finally {
      await harness.closeTab(audioTab);
    }
  });

  // ── T2.V13.L05: 60fps Frame Budget & Zero-Jank Under Pan/Zoom ──
  await test('T2.V13.L05', '60fps frame budget, bounded tileCacheSize & zero rAF multiplication under pan/zoom and Live Off/On', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2&landmark=bahnhof_stockengut', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });

      // Multi-tile smooth pan & wheel zoom interactions
      const vp = await tab.evaluate(`(() => {
        const r = document.getElementById('viewport').getBoundingClientRect();
        return {
          x: r.left + r.width * 0.72,
          y: r.top + r.height * 0.65,
          cx: r.left + r.width * 0.5,
          cy: r.top + r.height * 0.5,
        };
      })()`);

      for (let i = 0; i < 4; i++) {
        await dispatchFastDrag(tab, vp.x, vp.y, -420, -180, 6, 12);
        await sleep(120);
      }
      await tab.send('Input.dispatchMouseEvent', {
        type: 'mouseWheel',
        x: vp.cx,
        y: vp.cy,
        deltaX: 0,
        deltaY: -180,
      });
      await sleep(180);
      await tab.send('Input.dispatchMouseEvent', {
        type: 'mouseWheel',
        x: vp.cx,
        y: vp.cy,
        deltaX: 0,
        deltaY: 180,
      });
      await waitForTilesReady(tab);

      const dbg = await tab.getDebug();
      assert(dbg?.frameStats && typeof dbg.frameStats === 'object', 'window.__dioramaDebug.frameStats missing');
      assert(
        dbg.frameStats.rafActive === true,
        `Expected frameStats.rafActive === true in live mode, got ${dbg.frameStats.rafActive}`,
      );
      assert(
        dbg.frameStats.tileCacheSize <= 128,
        `frameStats.tileCacheSize=${dbg.frameStats.tileCacheSize} exceeded LRU cap of 128`,
      );

      const lr = dbg.livingRegistry;
      assert(lr && typeof lr === 'object', 'window.__dioramaDebug.livingRegistry missing after pan/zoom');
      assert(
        typeof lr.updateMs === 'number' && Number.isFinite(lr.updateMs) && lr.updateMs >= 0 && lr.updateMs < 50,
        `livingRegistry.updateMs out of budget [0, 50): ${lr.updateMs}`,
      );
      assert(
        typeof lr.drawMs === 'number' && Number.isFinite(lr.drawMs) && lr.drawMs >= 0 && lr.drawMs < 50,
        `livingRegistry.drawMs out of budget [0, 50): ${lr.drawMs}`,
      );

      // Toggle Live Off -> On repeatedly (same pattern as T4.08) and verify zero rAF multiplication
      await tab.evaluate(`(() => {
        const orig = window.requestAnimationFrame.bind(window);
        window.__v13RafCount = 0;
        window.requestAnimationFrame = (cb) => {
          window.__v13RafCount++;
          return orig(cb);
        };
      })()`);
      await tab.evaluate('window.__v13RafCount = 0');
      await sleep(400);
      const baseCount = await tab.evaluate('window.__v13RafCount');
      assert(baseCount > 0, `Expected active baseline rAF loop, got ${baseCount}`);

      for (let i = 0; i < 8; i++) {
        await tab.clickSelector('#btn-toggle-anim');
        await sleep(20);
      }
      await sleep(120);
      await tab.evaluate('window.__v13RafCount = 0');
      await sleep(400);
      const afterCount = await tab.evaluate('window.__v13RafCount');
      const maxAllowed = Math.max(Math.ceil(baseCount * 1.8), 40);
      assert(
        afterCount <= maxAllowed,
        `rAF loop multiplied after Live Off/On toggles: baseline=${baseCount}/400ms, after=${afterCount}/400ms (max ${maxAllowed})`,
      );

      const dbgAfter = await tab.getDebug();
      assert(
        dbgAfter?.frameStats?.rafActive === true,
        `Expected frameStats.rafActive === true after Live Off/On round-trip, got ${dbgAfter?.frameStats?.rafActive}`,
      );

      assertCleanTab(tab, 'T2.V13.L05');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T2.V13.L06: Dynamic Plugin Extensibility Contract ──
  await test('T2.V13.L06', 'Dynamic plugin register/unregister/setEnabled contract executes lifecycle hooks & cleans up cleanly', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await sleep(200);
      const checkApi = await tab.evaluate(`(() => {
        const lr = window.__dioramaDebug && window.__dioramaDebug.livingRegistry;
        if (!lr) return { ok: false, reason: 'livingRegistry missing' };
        return {
          ok: true,
          hasRegister: typeof lr.register === 'function',
          hasUnregister: typeof lr.unregister === 'function',
          hasSetEnabled: typeof lr.setEnabled === 'function',
          baseCount: lr.pluginCount,
          hasProbe: Array.isArray(lr.pluginIds) && lr.pluginIds.includes('__test_ext_probe__'),
        };
      })()`);

      assert(checkApi.ok, `livingRegistry unavailable: ${checkApi.reason}`);
      assert(checkApi.hasRegister, 'livingRegistry.register must be a function');
      assert(checkApi.hasUnregister, 'livingRegistry.unregister must be a function');
      assert(checkApi.hasSetEnabled, 'livingRegistry.setEnabled must be a function');
      assert(!checkApi.hasProbe, 'Probe plugin __test_ext_probe__ already registered before test');

      const regRes = await tab.evaluate(`(async () => {
        const lr = window.__dioramaDebug.livingRegistry;
        const probe = { initCalls: 0, updateCalls: 0, drawablesCalls: 0, drawCalls: 0 };
        window.__v13ExtProbe = probe;
        lr.register({
          id: '__test_ext_probe__',
          name: 'Test Ext Probe',
          category: 'test',
          layers: ['overlay'],
          priority: 99,
          init() { probe.initCalls++; },
          update() { probe.updateCalls++; },
          getDrawables() {
            probe.drawablesCalls++;
            return [{
              layer: 'overlay',
              sortY: 0,
              draw() { probe.drawCalls++; },
            }];
          },
          getInspectables() { return []; },
          getAudioSignals() { return []; },
        });

        // Allow several rAF ticks for update & getDrawables to execute
        for (let i = 0; i < 4; i++) {
          await new Promise((r) => requestAnimationFrame(r));
        }

        const lrAfterReg = window.__dioramaDebug.livingRegistry;
        const regSnap = {
          pluginCount: lrAfterReg.pluginCount,
          hasProbe: Array.isArray(lrAfterReg.pluginIds) && lrAfterReg.pluginIds.includes('__test_ext_probe__'),
          probe: { ...probe },
        };

        lrAfterReg.unregister('__test_ext_probe__');
        await new Promise((r) => requestAnimationFrame(r));

        const lrAfterUnreg = window.__dioramaDebug.livingRegistry;
        const unregSnap = {
          pluginCount: lrAfterUnreg.pluginCount,
          hasProbe: Array.isArray(lrAfterUnreg.pluginIds) && lrAfterUnreg.pluginIds.includes('__test_ext_probe__'),
        };
        delete window.__v13ExtProbe;
        return { regSnap, unregSnap };
      })()`);

      assert(
        regRes.regSnap.pluginCount === checkApi.baseCount + 1,
        `Expected pluginCount=${checkApi.baseCount + 1} after register, got ${regRes.regSnap.pluginCount}`,
      );
      assert(
        regRes.regSnap.hasProbe === true,
        'Registered plugin __test_ext_probe__ missing from livingRegistry.pluginIds',
      );
      assert(
        regRes.regSnap.probe.initCalls >= 1,
        `Mock plugin init() did not execute (initCalls=${regRes.regSnap.probe.initCalls})`,
      );
      assert(
        regRes.regSnap.probe.updateCalls >= 1,
        `Mock plugin update() did not execute on subsequent ticks (updateCalls=${regRes.regSnap.probe.updateCalls})`,
      );
      assert(
        regRes.regSnap.probe.drawablesCalls >= 1,
        `Mock plugin getDrawables() did not execute on subsequent ticks (drawablesCalls=${regRes.regSnap.probe.drawablesCalls})`,
      );
      assert(
        regRes.regSnap.probe.drawCalls >= 1,
        `Mock plugin drawable draw() did not execute on subsequent ticks (drawCalls=${regRes.regSnap.probe.drawCalls})`,
      );

      assert(
        regRes.unregSnap.pluginCount === checkApi.baseCount,
        `Expected pluginCount to return to baseline ${checkApi.baseCount} after unregister, got ${regRes.unregSnap.pluginCount}`,
      );
      assert(
        regRes.unregSnap.hasProbe === false,
        'Plugin __test_ext_probe__ still present in livingRegistry.pluginIds after unregister',
      );

      assertCleanTab(tab, 'T2.V13.L06');
    } finally {
      await harness.closeTab(tab);
    }
  });
}

runNodeSuite({
  tier: 2,
  suiteName: 'tier2_v13_living',
  runTests,
});
