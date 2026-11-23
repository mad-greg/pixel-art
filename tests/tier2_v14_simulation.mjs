/**
 * Tier 2 (Node CDP): Kilchberg v14 Moving/Living Layer Simulation Suite (T2.V14.01–T2.V14.08).
 *
 * Opaque-box verification of PROJECT.md Features F1–F14 via documented public contracts:
 *   - T2.V14.01: Glitch-free double-track train passing & opaque train roofs (F5, F6)
 *   - T2.V14.02: Zero vehicle-vehicle & vehicle-pedestrian collisions + active traffic motion (F4, F7, F8)
 *   - T2.V14.03: Realistic Tennis rally physics (F10)
 *   - T2.V14.04: Realistic Soccer player speed & ball kinematics (F11)
 *   - T2.V14.05: Collision-free maritime vessels & slow SUPs (F12, F13)
 *   - T2.V14.06: Modular Spec Injection API (__dioramaDebug.specs) (F1, F2, F9)
 *   - T2.V14.07: Real-Time Kilchberg Clock & Deterministic Override (F3, F14)
 *   - T2.V14.08: Guardrails & 60fps Budget (F13, F14)
 */

import {
  analyzeVehicleRoofOpacity,
  assert,
  diffCanvasSamples,
  readGainValue,
  runNodeSuite,
  sleep,
  waitForSoundActive,
} from './lib/cdp_harness.mjs';

function rectsOverlap(a, b) {
  if (!a || !b) return false;
  return a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1;
}

async function waitForTilesReady(tab, timeoutMs = 3000) {
  await tab.waitForCameraSettled({ maxWaitMs: 950, settleMs: 140, pollMs: 60 });
  await tab.waitFor(
    `(() => {
      const d = window.__dioramaDebug;
      return Boolean(d && (!d.frameStats || d.frameStats.tileInflight === 0));
    })()`,
    { timeoutMs, intervalMs: 80 },
  );
  await sleep(180);
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
  // ── T2.V14.01: Glitch-free double-track train passing & opaque train roofs ──
  await test('T2.V14.01', 'Glitch-free double-track train passing (railTelemetry, pre-rail board, opaque roofs)', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2&landmark=bahnhof_stockengut&t=10', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      const sampleTimes = [10, 22, 34, 46];
      let maxActiveTrains = 0;

      for (const t of sampleTimes) {
        if (t !== 10) {
          await tab.navigate(`/?mode=day&zoom=2&landmark=bahnhof_stockengut&t=${t}`, { waitReady: true });
        }
        await waitForTilesReady(tab);
        const dbg = await tab.getDebug();
        assert(dbg && typeof dbg === 'object', `t=${t}: window.__dioramaDebug missing`);

        const rt = dbg.railTelemetry;
        assert(
          rt && typeof rt === 'object' && !Array.isArray(rt),
          `t=${t}: window.__dioramaDebug.railTelemetry missing or not an object (got ${typeof rt})`,
        );
        assert(
          typeof rt.activeTrains === 'number' && Number.isFinite(rt.activeTrains) && rt.activeTrains >= 0,
          `t=${t}: railTelemetry.activeTrains must be a finite number >= 0, got ${rt.activeTrains}`,
        );
        assert(
          typeof rt.passingNow === 'boolean',
          `t=${t}: railTelemetry.passingNow must be boolean, got ${typeof rt.passingNow} (${JSON.stringify(rt.passingNow)})`,
        );
        assert(
          typeof rt.trackInterleaveViolations === 'number' && rt.trackInterleaveViolations === 0,
          `t=${t}: railTelemetry.trackInterleaveViolations must be 0, got ${rt.trackInterleaveViolations}`,
        );
        if (rt.activeTrains > maxActiveTrains) maxActiveTrains = rt.activeTrains;

        // Verify trains & landmarks plugins remain active (Bahnhof NW board/clock in pre_rail behind trains)
        const lr = dbg.livingRegistry;
        assert(
          lr && Array.isArray(lr.enabledPlugins) && lr.enabledPlugins.includes('trains') && lr.enabledPlugins.includes('landmarks'),
          `t=${t}: Expected both 'trains' and 'landmarks' plugins enabled in livingRegistry`,
        );
      }

      assert(
        maxActiveTrains >= 1,
        `Expected at least 1 active SBB train across Bahnhof samples [10,22,34,46], got maxActiveTrains=${maxActiveTrains}`,
      );

      // Verify opaque train roofs when zoomed on a followed train (matching v8-v13 guardrail)
      let bestRoof = null;
      for (const t of [22, 35, 10]) {
        await tab.navigate(`/?mode=day&zoom=2&follow=train&t=${t}`, { waitReady: true });
        await waitForTilesReady(tab);
        const dbgTrain = await tab.getDebug();
        assert(
          dbgTrain && dbgTrain.followTarget === 'train',
          `t=${t}: Expected followTarget='train', got '${dbgTrain?.followTarget}'`,
        );
        const dStats = dbgTrain.depthStats || {};
        assert(
          (dStats.direct || 0) + (dStats.partial || 0) > 0,
          `t=${t}: Expected active depth-masked rendering for train, got depthStats=${JSON.stringify(dStats)}`,
        );
        assert(
          dbgTrain.railTelemetry && dbgTrain.railTelemetry.trackInterleaveViolations === 0,
          `t=${t}: railTelemetry.trackInterleaveViolations non-zero during follow=train: ${JSON.stringify(dbgTrain.railTelemetry)}`,
        );

        const roiOn = await tab.captureCanvasRegion('#diorama-canvas', { cxFrac: 0.5, cyFrac: 0.5, boxW: 120, boxH: 80 });
        await tab.clickSelector('#btn-toggle-anim');
        await sleep(140);
        const roiOff = await tab.captureCanvasRegion('#diorama-canvas', { cxFrac: 0.5, cyFrac: 0.5, boxW: 120, boxH: 80 });
        await tab.clickSelector('#btn-toggle-anim');
        await sleep(100);

        const m = analyzeVehicleRoofOpacity(roiOn, roiOff, 14);
        const mOk = m.vehPixels >= 120;
        const bestOk = bestRoof && bestRoof.vehPixels >= 120;
        if (
          !bestRoof ||
          (mOk && (!bestOk || m.holeFrac < bestRoof.holeFrac || (m.holeFrac === bestRoof.holeFrac && m.vehPixels > bestRoof.vehPixels))) ||
          (!bestOk && !mOk && m.vehPixels > bestRoof.vehPixels)
        ) {
          bestRoof = { ...m, t };
        }
      }

      assert(
        bestRoof && bestRoof.vehPixels >= 120,
        `Followed train rendered too few pixels at 2x zoom: vehPixels=${bestRoof?.vehPixels} < 120`,
      );
      assert(
        bestRoof.holeFrac < 0.06,
        `Perforated train roof opacity cutouts at t=${bestRoof.t}: holeFrac=${(bestRoof.holeFrac * 100).toFixed(2)}% (interiorHoles=${bestRoof.interiorHoles}, vehPixels=${bestRoof.vehPixels})`,
      );

      assertCleanTab(tab, 'T2.V14.01');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T2.V14.02: Zero vehicle-vehicle & vehicle-pedestrian collisions + active motion ──
  await test('T2.V14.02', 'Zero vehicle-vehicle & vehicle-pedestrian collisions across ?t= samples with active traffic motion', async () => {
    const tab = await harness.openTab('/?mode=day&t=10', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      const sampleTimes = [10, 22, 34, 46];
      for (const t of sampleTimes) {
        if (t !== 10) {
          await tab.navigate(`/?mode=day&t=${t}`, { waitReady: true });
        }
        await sleep(220);
        const dbg = await tab.getDebug();
        assert(dbg && dbg.simStats && typeof dbg.simStats === 'object', `t=${t}: window.__dioramaDebug.simStats missing`);
        const s = dbg.simStats;

        assert(
          typeof s.vehicles === 'number' && s.vehicles >= 40,
          `t=${t}: Expected active daytime traffic (vehicles >= 40), got ${s.vehicles}`,
        );
        assert(
          typeof s.overlapCount === 'number' && s.overlapCount === 0,
          `t=${t}: simStats.overlapCount must be 0, got ${s.overlapCount}`,
        );
        assert(
          typeof s.clippingCount === 'number' && s.clippingCount === 0,
          `t=${t}: simStats.clippingCount must be 0, got ${s.clippingCount}`,
        );
        assert(
          typeof s.pedVehicleOverlapCount === 'number' && s.pedVehicleOverlapCount === 0,
          `t=${t}: simStats.pedVehicleOverlapCount must be a number === 0, got ${JSON.stringify(s.pedVehicleOverlapCount)}`,
        );
        assert(
          typeof s.cyclistVehicleOverlapCount === 'number' && s.cyclistVehicleOverlapCount === 0,
          `t=${t}: simStats.cyclistVehicleOverlapCount must be a number === 0, got ${JSON.stringify(s.cyclistVehicleOverlapCount)}`,
        );
      }

      // Verify realistic cruising speed (no 0.36 m/s crawl or gridlock): follow a live bus across t=22 -> t=34 (12 s)
      await tab.navigate('/?mode=day&zoom=2&follow=bus&t=22', { waitReady: true });
      await sleep(220);
      const bus22 = await tab.getDebug();

      await tab.navigate('/?mode=day&zoom=2&follow=bus&t=34', { waitReady: true });
      await sleep(220);
      const bus34 = await tab.getDebug();

      assert(
        bus22 && bus22.followTarget === 'bus' && bus34 && bus34.followTarget === 'bus',
        `Expected followTarget='bus' for both samples, got bus22='${bus22?.followTarget}', bus34='${bus34?.followTarget}'`,
      );
      assert(
        Number.isFinite(bus22.u) && Number.isFinite(bus22.v) && Number.isFinite(bus34.u) && Number.isFinite(bus34.v),
        `Expected finite bus coordinates, got bus22=(${bus22.u}, ${bus22.v}), bus34=(${bus34.u}, ${bus34.v})`,
      );

      const dist = Math.hypot(bus34.u - bus22.u, bus34.v - bus22.v);
      assert(
        Number.isFinite(dist) && dist > 0.006,
        `Traffic appears gridlocked or crawling: followed bus UV displacement between t=22 and t=34 was ${dist.toFixed(6)} (need > 0.006)`,
      );

      assertCleanTab(tab, 'T2.V14.02');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T2.V14.03: Realistic Tennis rally physics ──
  await test('T2.V14.03', 'Realistic Tennis rally physics (4+ courts, 1.0–2.4 s shots, clay court bounces)', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2&landmark=villa_spinnergut_tc', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      // Guard against real-world Zurich night hours suppressing outdoor tennis play
      await tab.evaluate(`(() => {
        const clk = window.__dioramaDebug && window.__dioramaDebug.clock;
        if (clk && typeof clk.setMode === 'function' && typeof clk.setManualMinutes === 'function') {
          clk.setMode('manual');
          clk.setManualMinutes(14 * 60);
        }
      })()`);

      // Poll up to 3500 ms for at least 1 clay-court bounce when sportsTelemetry is exposed
      const hasSportsTelemetry = await tab.evaluate(
        `Boolean(window.__dioramaDebug && window.__dioramaDebug.sportsTelemetry && typeof window.__dioramaDebug.sportsTelemetry === 'object')`,
      );
      if (hasSportsTelemetry) {
        try {
          await tab.waitFor(
            `(() => {
              const st = window.__dioramaDebug && window.__dioramaDebug.sportsTelemetry;
              return Boolean(st && typeof st.tennisBouncesObserved === 'number' && st.tennisBouncesObserved >= 1);
            })()`,
            { timeoutMs: 3500, intervalMs: 100 },
          );
        } catch {
          // Fall through to exact structured assertions below
        }
      }

      const dbg = await tab.getDebug();
      assert(dbg && typeof dbg === 'object', 'window.__dioramaDebug missing');

      const st = dbg.sportsTelemetry;
      assert(
        st && typeof st === 'object' && !Array.isArray(st),
        `window.__dioramaDebug.sportsTelemetry missing or not an object (got ${typeof st})`,
      );
      assert(
        typeof st.tennisCourts === 'number' && st.tennisCourts >= 4,
        `sportsTelemetry.tennisCourts must be >= 4, got ${st.tennisCourts}`,
      );
      assert(
        typeof st.minTennisShotSec === 'number' && Number.isFinite(st.minTennisShotSec) && st.minTennisShotSec >= 1.0,
        `sportsTelemetry.minTennisShotSec must be >= 1.0 s (no 0.65 s ping-pong), got ${st.minTennisShotSec}`,
      );
      assert(
        typeof st.maxTennisShotSec === 'number' && Number.isFinite(st.maxTennisShotSec) && st.maxTennisShotSec <= 2.4,
        `sportsTelemetry.maxTennisShotSec must be <= 2.4 s, got ${st.maxTennisShotSec}`,
      );
      assert(
        st.minTennisShotSec <= st.maxTennisShotSec,
        `sportsTelemetry minTennisShotSec (${st.minTennisShotSec}) > maxTennisShotSec (${st.maxTennisShotSec})`,
      );
      assert(
        typeof st.tennisBouncesObserved === 'number' &&
          Number.isFinite(st.tennisBouncesObserved) &&
          st.tennisBouncesObserved >= 1,
        `sportsTelemetry.tennisBouncesObserved must be finite >= 1, got ${st.tennisBouncesObserved}`,
      );

      assertCleanTab(tab, 'T2.V14.03');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T2.V14.04: Realistic Soccer player speed & ball kinematics ──
  await test('T2.V14.04', 'Realistic Soccer player speed (<= 7.0 m/s) & possession/pass/shot ball kinematics', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2&landmark=hallenbad_hochweid', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      // Guard against real-world Zurich night hours suppressing outdoor soccer play
      await tab.evaluate(`(() => {
        const clk = window.__dioramaDebug && window.__dioramaDebug.clock;
        if (clk && typeof clk.setMode === 'function' && typeof clk.setManualMinutes === 'function') {
          clk.setMode('manual');
          clk.setManualMinutes(14 * 60);
        }
      })()`);
      await sleep(1200);
      const dbg = await tab.getDebug();
      assert(dbg && typeof dbg === 'object', 'window.__dioramaDebug missing');

      const st = dbg.sportsTelemetry;
      assert(
        st && typeof st === 'object' && !Array.isArray(st),
        `window.__dioramaDebug.sportsTelemetry missing or not an object (got ${typeof st})`,
      );
      assert(
        typeof st.soccerPitches === 'number' && st.soccerPitches >= 3,
        `sportsTelemetry.soccerPitches must be >= 3, got ${st.soccerPitches}`,
      );
      assert(
        typeof st.maxSoccerPlayerMps === 'number' &&
          Number.isFinite(st.maxSoccerPlayerMps) &&
          st.maxSoccerPlayerMps > 0 &&
          st.maxSoccerPlayerMps <= 7.0,
        `sportsTelemetry.maxSoccerPlayerMps must be in (0, 7.0] m/s, got ${st.maxSoccerPlayerMps}`,
      );
      assert(
        Array.isArray(st.ballModes) && st.ballModes.length >= 1,
        `sportsTelemetry.ballModes must be a non-empty array of ball states, got ${JSON.stringify(st.ballModes)}`,
      );
      for (const mode of st.ballModes) {
        assert(
          typeof mode === 'string' && mode.trim().length > 0,
          `sportsTelemetry.ballModes contains invalid mode entry: ${JSON.stringify(mode)}`,
        );
      }

      // Verify soccer pitches exit GOAL_CELEBRATION cleanly without permanent infinite-lock
      await tab.navigate('/?mode=day&zoom=2&landmark=hallenbad_hochweid&t=22', { waitReady: true });
      await sleep(220);
      const dbg22 = await tab.getDebug();
      const modes22 = dbg22?.sportsTelemetry?.ballModes || [];
      const activePlay22 = modes22.filter((m) => m !== 'GOAL_CELEBRATION');
      assert(
        activePlay22.length >= Math.max(1, modes22.length - 1),
        `Soccer pitches appear stuck in GOAL_CELEBRATION at t=22: ${JSON.stringify(modes22)}`,
      );

      await tab.navigate('/?mode=day&zoom=2&landmark=hallenbad_hochweid&t=26', { waitReady: true });
      await sleep(220);
      const dbg26 = await tab.getDebug();
      const modes26 = dbg26?.sportsTelemetry?.ballModes || [];
      assert(
        !(modes22.every((m) => m === 'GOAL_CELEBRATION') && modes26.every((m) => m === 'GOAL_CELEBRATION')),
        `All soccer pitches permanently locked in GOAL_CELEBRATION between t=22 and t=26`,
      );

      assertCleanTab(tab, 'T2.V14.04');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T2.V14.05: Collision-free maritime vessels & slow SUPs ──
  await test('T2.V14.05', 'Collision-free maritime vessels (COLREGs clearance > 0), slow SUPs (<= 2.0 m/s) & zero night SUPs', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2&landmark=bendlikon_pier&t=10', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      const sampleTimes = [10, 22, 34, 46];
      for (const t of sampleTimes) {
        if (t !== 10) {
          await tab.navigate(`/?mode=day&zoom=2&landmark=bendlikon_pier&t=${t}`, { waitReady: true });
        }
        await sleep(220);
        const dbg = await tab.getDebug();
        assert(dbg && typeof dbg === 'object', `t=${t}: window.__dioramaDebug missing`);

        const vt = dbg.vesselTelemetry;
        assert(
          vt && typeof vt === 'object' && !Array.isArray(vt),
          `t=${t}: window.__dioramaDebug.vesselTelemetry missing or not an object (got ${typeof vt})`,
        );
        assert(
          typeof vt.activeVessels === 'number' && vt.activeVessels >= 3,
          `t=${t}: vesselTelemetry.activeVessels must be >= 3, got ${vt.activeVessels}`,
        );
        assert(
          typeof vt.collisionCount === 'number' && vt.collisionCount === 0,
          `t=${t}: vesselTelemetry.collisionCount must be 0, got ${vt.collisionCount}`,
        );
        assert(
          typeof vt.minPairwiseClearanceM === 'number' &&
            Number.isFinite(vt.minPairwiseClearanceM) &&
            vt.minPairwiseClearanceM > 0,
          `t=${t}: vesselTelemetry.minPairwiseClearanceM must be finite > 0, got ${vt.minPairwiseClearanceM}`,
        );
        assert(
          typeof vt.maxSupSpeedMps === 'number' &&
            Number.isFinite(vt.maxSupSpeedMps) &&
            vt.maxSupSpeedMps > 0 &&
            vt.maxSupSpeedMps <= 2.0,
          `t=${t}: vesselTelemetry.maxSupSpeedMps must be in (0, 2.0] m/s, got ${vt.maxSupSpeedMps}`,
        );
      }

      // Verify zero SUPs at night
      await tab.navigate('/?mode=night&t=10', { waitReady: true });
      await sleep(220);
      const dbgNight = await tab.getDebug();
      assert(
        dbgNight?.livingCounts && dbgNight.livingCounts.sups === 0,
        `Expected night livingCounts.sups === 0, got ${dbgNight?.livingCounts?.sups}`,
      );

      assertCleanTab(tab, 'T2.V14.05');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T2.V14.06: Modular Spec Injection API (__dioramaDebug.specs) ──
  await test('T2.V14.06', 'Modular Spec Injection API registers, ticks, validates & removes custom InhabitantSpec and BusRouteSpec', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await sleep(200);
      const apiCheck = await tab.evaluate(`(() => {
        const specs = window.__dioramaDebug && window.__dioramaDebug.specs;
        if (!specs || typeof specs !== 'object') {
          return { ok: false, reason: 'window.__dioramaDebug.specs missing' };
        }
        const fns = [
          'getSummary',
          'registerInhabitant',
          'removeInhabitant',
          'registerBusRoute',
          'removeBusRoute',
          'registerRailService',
          'registerVessel',
        ];
        const missing = fns.filter((k) => typeof specs[k] !== 'function');
        return { ok: missing.length === 0, missing, base: typeof specs.getSummary === 'function' ? specs.getSummary() : null };
      })()`);

      assert(
        apiCheck.ok,
        apiCheck.reason || `window.__dioramaDebug.specs missing required methods: ${apiCheck.missing.join(', ')}`,
      );
      assert(
        apiCheck.base && typeof apiCheck.base.inhabitants === 'number' && typeof apiCheck.base.bus === 'number',
        `specs.getSummary() must return numeric inhabitants & bus counts, got ${JSON.stringify(apiCheck.base)}`,
      );

      const res = await tab.evaluate(`(async () => {
        const specs = window.__dioramaDebug.specs;
        const base = specs.getSummary();

        const existingInhab = typeof specs.getInhabitants === 'function' ? specs.getInhabitants()[0] : null;
        const customInhabitant = existingInhab
          ? Object.assign(JSON.parse(JSON.stringify(existingInhab)), {
              id: '__test_v14_inhabitant__',
              name: 'V14 Test Resident',
            })
          : {
              id: '__test_v14_inhabitant__',
              name: 'V14 Test Resident',
              home: { uv: [0.44, 0.42], poiId: 'poi_bahnhof' },
              workplace: { poiId: 'poi_lindt' },
              appearance: { coat: '#2b5d8f', pants: '#333', hair: '#4a3520' },
              routine: [
                { startMin: 0, endMin: 450, activity: 'home', targetPoi: 'poi_bahnhof', transport: 'walk' },
                { startMin: 450, endMin: 1080, activity: 'work', targetPoi: 'poi_lindt', transport: 'walk' },
                { startMin: 1080, endMin: 1440, activity: 'home', targetPoi: 'poi_bahnhof', transport: 'walk' },
              ],
            };

        const existingBus = typeof specs.getBusRoutes === 'function' ? specs.getBusRoutes()[0] : null;
        const customBus = existingBus
          ? Object.assign(JSON.parse(JSON.stringify(existingBus)), {
              id: '__test_v14_bus_route__',
              line: '999',
            })
          : {
              id: '__test_v14_bus_route__',
              line: '999',
              operator: 'ZVV',
              vehicleType: 'bus_rigid',
              corridorSegments: [
                { roadId: 'seestrasse_sb', fromFrac: 0.0, toFrac: 1.0 },
                { roadId: 'seestrasse_nb', fromFrac: 0.0, toFrac: 1.0 },
              ],
              stops: [
                { stopId: 'stop_test_1', roadId: 'seestrasse_sb', frac: 0.35, name: 'Test Bendlikon', dwellSec: 4 },
              ],
              timetable: { minutesPastHour: [10, 40], peakHeadwayMin: 15, offPeakHeadwayMin: 30, nightActive: false },
            };

        specs.registerInhabitant(customInhabitant);
        specs.registerBusRoute(customBus);

        for (let i = 0; i < 4; i++) {
          await new Promise((r) => requestAnimationFrame(r));
        }
        const afterReg = specs.getSummary();

        specs.removeInhabitant('__test_v14_inhabitant__');
        specs.removeBusRoute('__test_v14_bus_route__');

        for (let i = 0; i < 2; i++) {
          await new Promise((r) => requestAnimationFrame(r));
        }
        const afterRem = specs.getSummary();

        let badInhabThrew = false;
        try {
          specs.registerInhabitant({});
        } catch (err) {
          badInhabThrew = err instanceof Error;
        }

        let badBusThrew = false;
        try {
          specs.registerBusRoute({});
        } catch (err) {
          badBusThrew = err instanceof Error;
        }

        return { base, afterReg, afterRem, badInhabThrew, badBusThrew };
      })()`);

      assert(
        res.afterReg.inhabitants === res.base.inhabitants + 1,
        `Expected specs.getSummary().inhabitants=${res.base.inhabitants + 1} after registerInhabitant, got ${res.afterReg.inhabitants}`,
      );
      assert(
        res.afterReg.bus === res.base.bus + 1,
        `Expected specs.getSummary().bus=${res.base.bus + 1} after registerBusRoute, got ${res.afterReg.bus}`,
      );
      assert(
        res.afterRem.inhabitants === res.base.inhabitants,
        `Expected specs.getSummary().inhabitants to return to ${res.base.inhabitants} after removeInhabitant, got ${res.afterRem.inhabitants}`,
      );
      assert(
        res.afterRem.bus === res.base.bus,
        `Expected specs.getSummary().bus to return to ${res.base.bus} after removeBusRoute, got ${res.afterRem.bus}`,
      );
      assert(
        res.badInhabThrew === true,
        'specs.registerInhabitant({}) (missing id) did not throw an Error',
      );
      assert(
        res.badBusThrew === true,
        'specs.registerBusRoute({}) (missing id) did not throw an Error',
      );

      assertCleanTab(tab, 'T2.V14.06');
    } finally {
      await harness.closeTab(tab);
    }
  });

  // ── T2.V14.07: Real-Time Kilchberg Clock & Deterministic Override ──
  await test('T2.V14.07', 'Real-Time Kilchberg Clock (Europe/Zurich, HUD desktop/mobile/cinema) & deterministic ?t=10 override', async () => {
    const findClockHudExpr = `(() => {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const explicitSels = [
        '#kilchberg-clock',
        '#hud-clock',
        '#clock-hud',
        '#clock-pill',
        '[data-clock-hud]',
        '.clock-hud',
        '.hud-clock',
        '.kilchberg-clock',
      ];
      let el = null;
      for (const s of explicitSels) {
        const cand = document.querySelector(s);
        if (cand) { el = cand; break; }
      }
      if (!el) {
        const uiEls = Array.from(document.querySelectorAll('.viewport-ui'));
        el = uiEls.find((node) => {
          const txt = (node.textContent || '').trim();
          return /\\b\\d{2}:\\d{2}\\b/.test(txt) && /(CET|CEST|Kilchberg|Live|Zurich)/i.test(txt);
        }) || null;
      }
      if (!el) return { found: false, vw, vh };
      const st = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const getRect = (sel) => {
        const n = document.querySelector(sel);
        if (!n) return null;
        const s = getComputedStyle(n);
        if (s.display === 'none' || s.visibility === 'hidden') return null;
        const b = n.getBoundingClientRect();
        return { left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height };
      };
      const topbar = document.querySelector('.topbar') || document.getElementById('topbar');
      return {
        found: true,
        id: el.id || '',
        className: el.className || '',
        hasViewportUiClass: el.classList.contains('viewport-ui'),
        display: st.display,
        visibility: st.visibility,
        opacity: st.opacity,
        text: (el.textContent || '').trim(),
        rect: { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height },
        hudCoords: getRect('#hud-coords'),
        navOverlay: getRect('.nav-overlay'),
        topbarScrollW: topbar ? topbar.scrollWidth : 0,
        topbarClientW: topbar ? topbar.clientWidth : 0,
        vw,
        vh,
      };
    })()`;

    // Part A: Live page (no ?t=) on desktop 1280x800
    const deskTab = await harness.openTab('/', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await sleep(240);
      const dbg = await deskTab.getDebug();
      assert(dbg && typeof dbg === 'object', 'Live desktop: window.__dioramaDebug missing');

      const clk = dbg.clock;
      assert(
        clk && typeof clk === 'object' && !Array.isArray(clk),
        `Live desktop: window.__dioramaDebug.clock missing or not an object (got ${typeof clk})`,
      );
      assert(
        clk.clockMode === 'live',
        `Live desktop: clock.clockMode must be 'live' on /, got ${JSON.stringify(clk.clockMode)}`,
      );
      assert(
        clk.tzLabel === 'CET' || clk.tzLabel === 'CEST',
        `clock.tzLabel must be 'CET' or 'CEST', got ${JSON.stringify(clk.tzLabel)}`,
      );
      assert(
        typeof clk.hours === 'number' && Number.isInteger(clk.hours) && clk.hours >= 0 && clk.hours <= 23,
        `clock.hours must be an integer in 0..23, got ${clk.hours}`,
      );
      assert(
        typeof clk.minutes === 'number' && Number.isInteger(clk.minutes) && clk.minutes >= 0 && clk.minutes <= 59,
        `clock.minutes must be an integer in 0..59, got ${clk.minutes}`,
      );
      assert(
        typeof clk.solarElevationDeg === 'number' &&
          Number.isFinite(clk.solarElevationDeg) &&
          clk.solarElevationDeg >= -90 &&
          clk.solarElevationDeg <= 90,
        `clock.solarElevationDeg must be finite in [-90, 90], got ${clk.solarElevationDeg}`,
      );
      assert(
        typeof clk.formattedHHMM === 'string' && /^\d{2}:\d{2}$/.test(clk.formattedHHMM),
        `clock.formattedHHMM must match /^\\d{2}:\\d{2}$/, got ${JSON.stringify(clk.formattedHHMM)}`,
      );
      assert(
        clk.diurnalActivity && typeof clk.diurnalActivity === 'object',
        'clock.diurnalActivity missing',
      );
      for (const k of ['commuterFactor', 'trafficFactor', 'pedestrianFactor', 'leisureFactor', 'nightFactor']) {
        const v = clk.diurnalActivity[k];
        assert(
          typeof v === 'number' && Number.isFinite(v),
          `clock.diurnalActivity.${k} must be a finite number, got ${v}`,
        );
      }

      const hudDesk = await deskTab.evaluate(findClockHudExpr);
      assert(hudDesk.found, 'Top-right Kilchberg clock HUD element not found in DOM on desktop');
      assert(
        hudDesk.display !== 'none' && hudDesk.visibility !== 'hidden' && hudDesk.rect.width > 20 && hudDesk.rect.height > 12,
        `Desktop clock HUD is not visible: ${JSON.stringify(hudDesk.rect)} display=${hudDesk.display}`,
      );
      assert(
        hudDesk.rect.left >= 0 &&
          hudDesk.rect.top >= 0 &&
          hudDesk.rect.right <= hudDesk.vw + 1 &&
          hudDesk.rect.bottom <= hudDesk.vh + 1,
        `Desktop clock HUD clips outside 1280x800 viewport: ${JSON.stringify(hudDesk.rect)}`,
      );
      assert(
        !rectsOverlap(hudDesk.rect, hudDesk.hudCoords),
        `Desktop clock HUD overlaps #hud-coords: clock=${JSON.stringify(hudDesk.rect)} coords=${JSON.stringify(hudDesk.hudCoords)}`,
      );
      assert(
        !rectsOverlap(hudDesk.rect, hudDesk.navOverlay),
        `Desktop clock HUD overlaps .nav-overlay: clock=${JSON.stringify(hudDesk.rect)} nav=${JSON.stringify(hudDesk.navOverlay)}`,
      );

      // Verify Cinema mode hides the clock HUD cleanly
      await deskTab.clickSelector('#btn-cinema');
      await sleep(160);
      const hudCinema = await deskTab.evaluate(findClockHudExpr);
      const hiddenInCinema =
        !hudCinema.found ||
        hudCinema.display === 'none' ||
        hudCinema.visibility === 'hidden' ||
        Number(hudCinema.opacity) === 0 ||
        hudCinema.rect.width === 0;
      assert(
        hiddenInCinema,
        `Clock HUD remained visible in Cinema mode (hasViewportUiClass=${hudDesk.hasViewportUiClass}, display=${hudCinema.display}, visibility=${hudCinema.visibility}, opacity=${hudCinema.opacity})`,
      );

      assertCleanTab(deskTab, 'T2.V14.07(desktop)');
    } finally {
      await harness.closeTab(deskTab);
    }

    // Part B: Mobile 390x844 layout safety
    const mobTab = await harness.openTab('/', {
      width: 390,
      height: 844,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await sleep(220);
      const hudMob = await mobTab.evaluate(findClockHudExpr);
      assert(hudMob.found, 'Kilchberg clock HUD element not found on mobile 390x844');
      assert(
        hudMob.topbarScrollW <= hudMob.topbarClientW + 1,
        `Mobile 390x844 .topbar overflows horizontally: scrollWidth=${hudMob.topbarScrollW} > clientWidth=${hudMob.topbarClientW}`,
      );
      assert(
        hudMob.rect.left >= 0 &&
          hudMob.rect.top >= 0 &&
          hudMob.rect.right <= hudMob.vw + 1 &&
          hudMob.rect.bottom <= hudMob.vh + 1,
        `Mobile 390x844 clock HUD clips outside viewport: ${JSON.stringify(hudMob.rect)}`,
      );
      assertCleanTab(mobTab, 'T2.V14.07(mobile)');
    } finally {
      await harness.closeTab(mobTab);
    }

    // Part C: Deterministic override /?t=10 (no &mode=) locks to 'day' and produces byte-identical frames
    const captureDet = async (label) => {
      const tab = await harness.openTab('/?t=10', {
        width: 1280,
        height: 800,
        dpr: 2,
        blockFonts: true,
        waitReady: true,
      });
      try {
        await waitForTilesReady(tab);
        const dbg = await tab.getDebug();
        const bodyMode = await tab.evaluate('document.body.dataset.mode');
        const sample = await tab.captureCanvasSample('#diorama-canvas', 160, 100);
        assertCleanTab(tab, label);
        return { dbg, bodyMode, sample };
      } finally {
        await harness.closeTab(tab);
      }
    };

    const det1 = await captureDet('T2.V14.07(det#1)');
    const det2 = await captureDet('T2.V14.07(det#2)');

    assert(
      det1.dbg?.clock?.clockMode === 'deterministic',
      `/?t=10 must set clock.clockMode === 'deterministic', got ${JSON.stringify(det1.dbg?.clock?.clockMode)}`,
    );
    assert(
      det1.dbg?.clock?.effectivePreset === 'day',
      `/?t=10 without &mode= must lock clock.effectivePreset === 'day', got ${JSON.stringify(det1.dbg?.clock?.effectivePreset)}`,
    );
    assert(
      det1.bodyMode === 'day' && det2.bodyMode === 'day',
      `/?t=10 without &mode= must lock body[data-mode="day"], got '${det1.bodyMode}' / '${det2.bodyMode}'`,
    );
    const diff = diffCanvasSamples(det1.sample, det2.sample);
    assert(
      diff.maxDiff === 0,
      `/?t=10 without &mode= was not byte-identical across two loads: maxDiff=${diff.maxDiff}, changedFrac=${diff.changedFrac}`,
    );
  });

  // ── T2.V14.08: Guardrails & 60fps Budget ──
  await test('T2.V14.08', 'Guardrails (zero paragliders, shore-strict inland lake_waves <= 0.05) & 60fps living budget (< 50ms)', async () => {
    const tab = await harness.openTab('/?mode=day&zoom=2&landmark=bendlikon_pier', {
      width: 1280,
      height: 800,
      dpr: 2,
      blockFonts: true,
      waitReady: true,
    });
    try {
      await sleep(280);
      const dbg = await tab.getDebug();
      assert(dbg && typeof dbg === 'object', 'window.__dioramaDebug missing');

      const lr = dbg.livingRegistry;
      assert(lr && typeof lr === 'object', 'window.__dioramaDebug.livingRegistry missing');
      assert(
        typeof lr.updateMs === 'number' && Number.isFinite(lr.updateMs) && lr.updateMs >= 0 && lr.updateMs < 50,
        `livingRegistry.updateMs out of 60fps budget [0, 50): ${lr.updateMs}`,
      );
      assert(
        typeof lr.drawMs === 'number' && Number.isFinite(lr.drawMs) && lr.drawMs >= 0 && lr.drawMs < 50,
        `livingRegistry.drawMs out of 60fps budget [0, 50): ${lr.drawMs}`,
      );

      // Also verify 60fps budget at default Fit zoom (/?mode=day) where all ~90 vehicles are in viewport
      await tab.navigate('/?mode=day', { waitReady: true });
      await sleep(320);
      const dbgFit = await tab.getDebug();
      const lrFit = dbgFit?.livingRegistry;
      assert(lrFit && typeof lrFit === 'object', 'Fit-zoom window.__dioramaDebug.livingRegistry missing');
      assert(
        typeof lrFit.updateMs === 'number' && Number.isFinite(lrFit.updateMs) && lrFit.updateMs >= 0 && lrFit.updateMs < 50,
        `Fit-zoom livingRegistry.updateMs out of 60fps budget [0, 50): ${lrFit.updateMs}`,
      );
      assert(
        typeof lrFit.drawMs === 'number' && Number.isFinite(lrFit.drawMs) && lrFit.drawMs >= 0 && lrFit.drawMs < 50,
        `Fit-zoom livingRegistry.drawMs out of 60fps budget [0, 50): ${lrFit.drawMs}`,
      );

      // Return to Bendlikon Pier for guardrail checks
      await tab.navigate('/?mode=day&zoom=2&landmark=bendlikon_pier', { waitReady: true });
      await sleep(240);

      // Guardrail: zero paragliders
      const lc = dbg.livingCounts || {};
      assert(
        lc.paragliders === undefined || lc.paragliders === 0,
        `Forbidden paragliders detected in livingCounts: paragliders=${lc.paragliders}`,
      );

      // Guardrail: shore-strict lake_waves (inland far from Lake Zurich <= 0.05)
      await tab.clickSelector('#btn-toggle-sound');
      const unlocked = await waitForSoundActive(tab, 6000);
      assert(unlocked, 'Trusted click on #btn-toggle-sound failed to unlock spatial audio');

      const clickedInland = await tab.evaluate(`(() => {
        const items = Array.from(document.querySelectorAll('#landmark-list .lm-item'));
        const target = items.find((el) => /sanatorium|stockengut|hochweid|kirche/i.test(el.textContent || '')) || items[1];
        if (!target) return false;
        target.click();
        return true;
      })()`);
      assert(clickedInland, 'Could not find inland landmark in #landmark-list');
      await tab.waitForCameraSettled();
      await tab.clickSelector('#btn-zoom-2x');
      await tab.waitForCameraSettled();
      await sleep(380);

      const dbgInland = await tab.getDebug();
      assert(dbgInland?.audioGains && typeof dbgInland.audioGains === 'object', 'audioGains missing at inland view');
      const gInlandWaves = readGainValue(dbgInland.audioGains, 'lake_waves');
      assert(
        Number.isFinite(gInlandWaves) && gInlandWaves >= 0 && gInlandWaves <= 0.05,
        `Shore-strict lake_waves violated inland (expected <= 0.05), got ${gInlandWaves}`,
      );

      assertCleanTab(tab, 'T2.V14.08');
    } finally {
      await harness.closeTab(tab);
    }
  });
}

runNodeSuite({
  tier: 2,
  suiteName: 'tier2_v14_simulation',
  runTests,
});
