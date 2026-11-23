/**
 * Spatial Kilchberg Soundscape Engine (9-channel Web Audio spatial mixer).
 *
 * Preserves all 9 field recordings, 7 mixer groups, shore-strict lake_waves,
 * continuous updates when Live: Off, and couples train, bus, traffic, boat,
 * and church bells (canonical schedule.js evalBellState) to live simulation state.
 * Zero Math.random() usage.
 */

import {
  evalBellState,
  evalBusScheduleState,
  evalShipState,
  evalTrainState,
  samplePathAt,
} from './sim/schedule.js';

export const SOUND_TRACKS = {
  lake_waves:   { file: 'lake_waves.mp3',   baseGain: 0.085, maxHz: 3200 },
  birds:        { file: 'birds.mp3',        baseGain: 0.11,  maxHz: 4600 },
  crickets:     { file: 'crickets.mp3',     baseGain: 0.10,  maxHz: 4800 },
  train:        { file: 'train.mp3',        baseGain: 0.26,  maxHz: 4200 },
  traffic:      { file: 'traffic.mp3',      baseGain: 0.12,  maxHz: 3200 },
  town_traffic: { file: 'town_traffic.mp3', baseGain: 0.30,  maxHz: 2000 },
  bus:          { file: 'bus.mp3',          baseGain: 0.14,  maxHz: 2400 },
  boat:         { file: 'boat.mp3',         baseGain: 0.18,  maxHz: 3000 },
  bells:        { file: 'bells.mp3',        baseGain: 0.22,  maxHz: 3400 },
};

const SOUND_MASTER_LEVEL = 0.48;

const MIX_GROUPS = {
  lake_waves: 'lake',
  birds: 'nature',
  crickets: 'nature',
  traffic: 'traffic',
  town_traffic: 'traffic',
  bus: 'traffic',
  train: 'rail',
  boat: 'water',
  bells: 'bells',
};

const TREE_BIRD_PERCHES = [
  [0.29, 0.34, 0.0], [0.35, 0.43, 0.17], [0.41, 0.36, 0.33], [0.47, 0.46, 0.51],
  [0.52, 0.39, 0.68], [0.58, 0.43, 0.82], [0.64, 0.35, 0.11], [0.71, 0.33, 0.44],
  [0.37, 0.58, 0.25], [0.44, 0.55, 0.62], [0.54, 0.52, 0.77], [0.62, 0.48, 0.08],
  [0.26, 0.45, 0.39], [0.76, 0.28, 0.58],
];

export function createAudioEngine({
  assetVer = '13.0',
  getCamera,
  getMode,
  getWorldSize,
  getAnimData,
  getTrafficSim,
  getLivingAudioSignals,
  getAnimTimeSec,
}) {
  let soundEnabled = false;
  let audioCtx = null;
  let audioMasterGain = null;
  let soundLoading = false;
  let soundReady = false;
  let lastAudioUpdateMs = 0;
  let audioSuspendTimer = null;
  let clockTimer = null;
  const soundChannels = {};

  const mixLevels = { master: 1, lake: 1, nature: 1, traffic: 1, rail: 1, water: 1, bells: 1 };
  const audioGainReport = {};
  Object.keys(SOUND_TRACKS).forEach((k) => { audioGainReport[k] = 0; });

  function masterTarget() {
    return soundEnabled ? SOUND_MASTER_LEVEL * mixLevels.master : 0.0001;
  }

  function suspendAudioSoon() {
    if (audioSuspendTimer) clearTimeout(audioSuspendTimer);
    audioSuspendTimer = setTimeout(() => {
      audioSuspendTimer = null;
      if (!soundEnabled && audioCtx && audioCtx.state === 'running') {
        audioCtx.suspend().catch(() => {});
      }
    }, 110);
  }

  function computeSpatialFactor(u, v, u0, u1, v0, v1, uC, halfVisU, zoomNorm, maxOffscreenRange) {
    const dxOut = u < u0 ? (u0 - u) : (u > u1 ? (u - u1) : 0);
    const dyOut = v < v0 ? (v0 - v) : (v > v1 ? (v - v1) : 0);
    const dOut = Math.hypot(dxOut, dyOut * 0.44);
    const inView = dOut === 0;

    const effRange = maxOffscreenRange / (0.65 + zoomNorm * 0.85);
    if (!inView && dOut >= effRange) {
      return { level: 0, brightness: 0.05, pan: 0, inView: false, dOut };
    }

    const pan = Math.max(-0.85, Math.min(0.85, (u - uC) / Math.max(0.035, halfVisU * 1.1)));
    const normD = inView ? 0 : (dOut / effRange);
    const offFalloff = inView ? 1.0 : Math.pow(1.0 - normD, 2.8) * 0.24;
    const centerDist = Math.hypot(u - uC, (v - (v0 + v1) * 0.5) * 0.44) / Math.max(0.05, halfVisU * 1.4);
    const inFocus = 0.72 + 0.28 * Math.max(0, 1.0 - centerDist);

    const level = inView
      ? (0.34 + 0.66 * Math.min(1.0, zoomNorm / 1.5)) * inFocus
      : offFalloff;
    const brightness = inView
      ? (0.24 + 0.76 * Math.min(1.0, zoomNorm / 1.6))
      : Math.max(0.05, 0.26 * (1.0 - normD));

    return { level: Math.max(0, Math.min(1, level)), brightness, pan, inView, dOut };
  }

  function applyChannelSpatial(key, level, brightness, pan) {
    const ch = soundChannels[key];
    const cfg = SOUND_TRACKS[key];
    const trim = mixLevels[MIX_GROUPS[key]] != null ? mixLevels[MIX_GROUPS[key]] : 1;
    const targetGain = Math.max(0.0001, level * cfg.baseGain * trim);
    audioGainReport[key] = targetGain;
    if (!ch || !audioCtx) return;
    const now = audioCtx.currentTime;
    const targetHz = 340 + brightness * (ch.cfg.maxHz - 340);
    ch.gain.gain.setTargetAtTime(targetGain, now, 0.16);
    ch.lpf.frequency.setTargetAtTime(targetHz, now, 0.18);
    if (ch.panner) {
      ch.panner.pan.setTargetAtTime(Math.max(-0.85, Math.min(0.85, pan)), now, 0.14);
    }
  }

  function update(force = false) {
    const animData = getAnimData();
    if (!soundReady || !audioCtx || !animData || !soundEnabled) return;
    const nowMs = performance.now();
    if (!force && nowMs - lastAudioUpdateMs < 60) return;
    lastAudioUpdateMs = nowMs;

    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }

    const { width: worldW, height: worldH } = getWorldSize();
    if (!worldW || !worldH) return;
    const cam = getCamera();
    const { scale, offsetX, offsetY, width: canvasW, height: canvasH, dpr } = cam;
    const tSec = getAnimTimeSec();
    const mode = getMode();

    const u0 = (-offsetX) / (worldW * scale);
    const u1 = (canvasW - offsetX) / (worldW * scale);
    const v0 = (-offsetY) / (worldH * scale);
    const v1 = (canvasH - offsetY) / (worldH * scale);
    const uC = (u0 + u1) * 0.5;
    const halfVisU = Math.max(0.02, (u1 - u0) * 0.5);
    const mppMaster = (animData && typeof animData.mpp === 'number') ? animData.mpp : 0.25;
    const wScale = (worldW / (animData.canvas_width || 12331)) * (0.25 / mppMaster);
    const zoomNorm = Math.max(0.15, Math.min(4.0, (scale * wScale) / Math.max(1, dpr)));
    const isNight = mode === 'night';
    const isSunset = mode === 'sunset';

    // 1. SBB Trains (hushes when dwelling at Bahnhof Kilchberg)
    let bestTrain = { level: 0, brightness: 0.08, pan: 0 };
    for (const tr of (animData.trains || [])) {
      const st = evalTrainState(tr, tSec);
      if (st.headFrac < 0.01 || st.headFrac > 1.12) continue;
      const isMoving = !st.isDwelling && st.speedRatio > 0.05;
      const midF = Math.max(0.01, Math.min(0.99, st.midFrac));
      const pos = samplePathAt(tr.pts, midF, worldW, worldH, 2);
      if (!pos) continue;
      const sp = computeSpatialFactor(pos.wx / worldW, pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.14);
      const lvl = sp.level * (isMoving ? (0.35 + 0.65 * st.speedRatio) : 0.12);
      if (lvl > bestTrain.level) {
        bestTrain = { level: lvl, brightness: sp.brightness * (isMoving ? 1.0 : 0.4), pan: sp.pan };
      }
    }
    applyChannelSpatial('train', bestTrain.level, bestTrain.brightness, bestTrain.pan);

    // 2. ZVV Buses, 3a. A3 Motorway Traffic & 3b. Town Street Traffic (coupled to live IDM trafficSim!)
    let bestBus = { level: 0, brightness: 0.08, pan: 0 };
    let bestMwCar = { level: 0, brightness: 0.08, pan: 0 };
    let mwSumLvl = 0;
    let mwPanSum = 0;
    let bestTownCar = { level: 0, brightness: 0.08, pan: 0 };
    let townSumLvl = 0;
    let townPanSum = 0;

    const trafficSim = getTrafficSim ? getTrafficSim() : null;
    if (trafficSim) {
      if (force) {
        trafficSim.updateToTime(tSec, mode);
      }
      const drawables = trafficSim.getDrawableVehicles(worldW, worldH, wScale);
      for (const b of drawables.buses) {
        if (!b.pos) continue;
        const sp = computeSpatialFactor(b.pos.wx / worldW, b.pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.075);
        const busLvl = sp.level * (b.isDwelling ? 0.35 : (0.5 + 0.5 * (b.speedRatio != null ? b.speedRatio : 1.0)));
        if (busLvl > bestBus.level) bestBus = { level: busLvl, brightness: sp.brightness, pan: sp.pan };
      }
      for (const c of drawables.cars) {
        if (!c.pos) continue;
        const isMotorway = !!(c.id && c.id.includes('motorway'));
        const sp = computeSpatialFactor(
          c.pos.wx / worldW,
          c.pos.wy / worldH,
          u0, u1, v0, v1, uC, halfVisU, zoomNorm,
          isMotorway ? 0.062 : 0.085,
        );
        if (sp.level <= 0.002) continue;
        const spdMul = 0.55 + 0.45 * (c.signals && c.signals.speedRatio != null ? c.signals.speedRatio : 1.0);
        if (isMotorway) {
          const cl = sp.level * 0.90 * spdMul;
          mwSumLvl += cl * cl;
          mwPanSum += sp.pan * cl;
          if (cl > bestMwCar.level) bestMwCar = { level: cl, brightness: sp.brightness, pan: sp.pan };
        } else {
          const cl = sp.level * 0.95 * spdMul;
          townSumLvl += cl * cl;
          townPanSum += sp.pan * cl;
          if (cl > bestTownCar.level) bestTownCar = { level: cl, brightness: sp.brightness, pan: sp.pan };
        }
      }
    } else {
      for (let rIdx = 0; rIdx < (animData.roads || []).length; rIdx++) {
        const rd = animData.roads[rIdx];
        const isMotorway = rd.kind === 'motorway';
        const busCount = rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0);
        const carCount = rd.car_count || 3;

        for (let bIdx = 0; bIdx < busCount; bIdx++) {
          if (isNight && bIdx > 0) continue;
          const st = evalBusScheduleState(rd, bIdx, tSec);
          if (st.frac < 0.001 || st.frac > 0.999) continue;
          const pos = samplePathAt(rd.pts, st.frac, worldW, worldH, 2);
          if (!pos) continue;
          const sp = computeSpatialFactor(pos.wx / worldW, pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.075);
          const busLvl = sp.level * (st.isDwelling ? 0.35 : (0.5 + 0.5 * st.speedRatio));
          if (busLvl > bestBus.level) bestBus = { level: busLvl, brightness: sp.brightness, pan: sp.pan };
        }

        const laneSpeed = Math.max(1.0, rd.speed_mps * (busCount > 0 ? 0.88 : 0.96));
        const cyc = rd.length_m / laneSpeed;
        const maxJitter = Math.min(0.011, 0.24 / Math.max(1, carCount));
        for (let cIdx = 0; cIdx < carCount; cIdx++) {
          const vIdx = busCount + cIdx;
          if (isNight && ((vIdx * 7 + rIdx * 3) % 20) >= 9) continue;
          const jitter = Math.sin(tSec * 0.28 + vIdx * 2.17 + rIdx * 1.3) * maxJitter;
          const frac = ((((tSec / cyc) + (rd.phase || 0) + (cIdx + 0.35) / Math.max(1, carCount) + jitter) % 1) + 1) % 1;
          if (frac < 0.001 || frac > 0.999) continue;
          const pos = samplePathAt(rd.pts, frac, worldW, worldH, 2);
          if (!pos) continue;
          const sp = computeSpatialFactor(
            pos.wx / worldW, pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm,
            isMotorway ? 0.062 : 0.085,
          );
          if (sp.level <= 0.002) continue;
          if (isMotorway) {
            const cl = sp.level * 0.90;
            mwSumLvl += cl * cl;
            mwPanSum += sp.pan * cl;
            if (cl > bestMwCar.level) bestMwCar = { level: cl, brightness: sp.brightness, pan: sp.pan };
          } else {
            const cl = sp.level * 0.95;
            townSumLvl += cl * cl;
            townPanSum += sp.pan * cl;
            if (cl > bestTownCar.level) bestTownCar = { level: cl, brightness: sp.brightness, pan: sp.pan };
          }
        }
      }
    }

    const nightTrafficMul = isNight ? 0.55 : 1.0;
    applyChannelSpatial('bus', bestBus.level * nightTrafficMul, bestBus.brightness, bestBus.pan);
    const mwFinalLvl = Math.min(1.0, Math.sqrt(mwSumLvl)) * nightTrafficMul;
    const mwPan = bestMwCar.level > 0.001 ? (mwPanSum / Math.max(0.001, Math.sqrt(mwSumLvl))) : 0;
    applyChannelSpatial('traffic', mwFinalLvl, bestMwCar.brightness, mwPan);
    const townFinalLvl = Math.min(1.0, Math.sqrt(townSumLvl)) * nightTrafficMul;
    const townPan = bestTownCar.level > 0.001 ? (townPanSum / Math.max(0.001, Math.sqrt(townSumLvl))) : 0;
    applyChannelSpatial('town_traffic', townFinalLvl, bestTownCar.brightness, townPan);

    // 4. Lake Zurich ZSG Steamer & Boats
    let bestBoat = { level: 0, brightness: 0.08, pan: 0 };
    for (const ship of (animData.ships || [])) {
      const st = evalShipState(ship, tSec, mode);
      if (!st.visible || st.frac < 0 || st.frac > 1) continue;
      const pos = samplePathAt(ship.pts, st.frac, worldW, worldH, 2);
      if (!pos) continue;
      const sp = computeSpatialFactor(pos.wx / worldW, pos.wy / worldH, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.09);
      const mul = ship.kind === 'zsg_steamer' ? (st.isDocked ? 0.35 : 1.0) : 0.28;
      if (sp.level * mul > bestBoat.level) {
        bestBoat = { level: sp.level * mul, brightness: sp.brightness, pan: sp.pan };
      }
    }
    applyChannelSpatial('boat', bestBoat.level, bestBoat.brightness, bestBoat.pan);

    // 5. Lake Zurich Shoreline Waves (shore-strict: silent inland & soft in overview)
    let bestWave = { level: 0, brightness: 0.08, pan: 0 };
    const shore = (animData.ambient && animData.ambient.shoreline) || [];
    for (let i = 0; i < shore.length; i++) {
      const sp = computeSpatialFactor(shore[i][0], shore[i][1], u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.042);
      if (sp.level > bestWave.level) bestWave = sp;
    }
    const waveZoomGate = Math.min(1, Math.max(0.04, (zoomNorm - 0.2) / 0.8));
    const wavePulse = 0.85 + 0.15 * Math.sin(tSec * (Math.PI * 2 / 5.6));
    applyChannelSpatial('lake_waves', bestWave.level * wavePulse * waveZoomGate, bestWave.brightness, bestWave.pan);

    // 6. Virtual Songbird Tree Perches & Night Crickets
    let bestBird = { level: 0, brightness: 0.08, pan: 0 };
    let bestCricket = { level: 0, brightness: 0.08, pan: 0 };
    for (const [tu, tv, ph] of TREE_BIRD_PERCHES) {
      const sp = computeSpatialFactor(tu, tv, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.050);
      if (sp.level <= 0.002) continue;
      const singCycle = Math.sin(tSec * 0.22 + ph * Math.PI * 2);
      const singEnv = singCycle > -0.15 ? Math.min(1.0, (singCycle + 0.15) * 1.15) : 0.12;
      const bLvl = sp.level * singEnv;
      if (bLvl > bestBird.level) bestBird = { level: bLvl, brightness: sp.brightness, pan: sp.pan };
      if (sp.level > bestCricket.level) bestCricket = sp;
    }
    const birdMul = isNight ? 0.0 : (isSunset ? 0.55 : 1.0);
    const cricketMul = isNight ? 1.0 : (isSunset ? 0.30 : 0.0);
    applyChannelSpatial('birds', bestBird.level * birdMul, bestBird.brightness, bestBird.pan);
    applyChannelSpatial('crickets', bestCricket.level * cricketMul, bestCricket.brightness, bestCricket.pan);

    // 7. Authentic Swiss Church Bells (exact unison with schedule.js evalBellState & vignettes.js)
    const bellAudioSt = evalBellState(tSec, mode);
    const bellEnv = bellAudioSt.envelope;
    let bestBell = { level: 0, brightness: 0.08, pan: 0 };
    if (bellEnv > 0.01 && !isNight) {
      const vig = (animData.ambient && animData.ambient.vignettes) || {};
      const churches = [
        (vig.reformierte_kirche && vig.reformierte_kirche.belfry) || [0.29272, 0.3162],
        (vig.st_elisabeth && vig.st_elisabeth.belfry) || [0.40667, 0.3425],
      ];
      for (const [cu, cv] of churches) {
        const sp = computeSpatialFactor(cu, cv, u0, u1, v0, v1, uC, halfVisU, zoomNorm, 0.28);
        const lvl = sp.level * bellEnv * (isSunset ? 1.0 : 0.85);
        if (lvl > bestBell.level) bestBell = { level: lvl, brightness: sp.brightness, pan: sp.pan };
      }
    }
    const livingSignals = (typeof getLivingAudioSignals === 'function')
      ? (getLivingAudioSignals(worldW, worldH, tSec, mode) || [])
      : [];

    if (livingSignals.length > 0) {
      const CHANNEL_MAX_RANGE = {
        train: 0.14,
        bus: 0.075,
        traffic: 0.062,
        town_traffic: 0.085,
        boat: 0.09,
        lake_waves: 0.042,
        birds: 0.050,
        crickets: 0.050,
        bells: 0.28,
      };
      for (let i = 0; i < livingSignals.length; i++) {
        const sig = livingSignals[i];
        if (!sig || !SOUND_TRACKS[sig.channel]) continue;
        if (!Number.isFinite(sig.u) || !Number.isFinite(sig.v) || !Number.isFinite(sig.weight) || sig.weight <= 0) continue;
        const maxRange = CHANNEL_MAX_RANGE[sig.channel] || 0.08;
        const range = Math.min(maxRange, Number.isFinite(sig.offscreenRange) ? sig.offscreenRange : maxRange);
        const sp = computeSpatialFactor(sig.u, sig.v, u0, u1, v0, v1, uC, halfVisU, zoomNorm, range);
        if (sp.level <= 0.002) continue;
        const bMul = Number.isFinite(sig.brightnessMul) ? sig.brightnessMul : 1.0;
        const lvl = sp.level * Math.min(1.0, sig.weight);
        if (sig.channel === 'train' && lvl > bestTrain.level) {
          bestTrain = { level: lvl, brightness: sp.brightness * bMul, pan: sp.pan };
        } else if (sig.channel === 'bus' && lvl > bestBus.level) {
          bestBus = { level: lvl, brightness: sp.brightness * bMul, pan: sp.pan };
        } else if (sig.channel === 'boat' && lvl > bestBoat.level) {
          bestBoat = { level: lvl, brightness: sp.brightness * bMul, pan: sp.pan };
        } else if (sig.channel === 'lake_waves' && lvl > bestWave.level) {
          bestWave = { level: lvl, brightness: sp.brightness * bMul, pan: sp.pan };
        } else if (sig.channel === 'birds' && lvl > bestBird.level) {
          bestBird = { level: lvl, brightness: sp.brightness * bMul, pan: sp.pan };
        } else if (sig.channel === 'crickets' && lvl > bestCricket.level) {
          bestCricket = { level: lvl, brightness: sp.brightness * bMul, pan: sp.pan };
        } else if (sig.channel === 'bells' && !isNight && lvl > bestBell.level) {
          bestBell = { level: lvl, brightness: sp.brightness * bMul, pan: sp.pan };
        }
      }
      applyChannelSpatial('train', bestTrain.level, bestTrain.brightness, bestTrain.pan);
      applyChannelSpatial('bus', bestBus.level * nightTrafficMul, bestBus.brightness, bestBus.pan);
      applyChannelSpatial('boat', bestBoat.level, bestBoat.brightness, bestBoat.pan);
      applyChannelSpatial('lake_waves', bestWave.level * wavePulse * waveZoomGate, bestWave.brightness, bestWave.pan);
      applyChannelSpatial('birds', bestBird.level * birdMul, bestBird.brightness, bestBird.pan);
      applyChannelSpatial('crickets', bestCricket.level * cricketMul, bestCricket.brightness, bestCricket.pan);
      applyChannelSpatial('bells', bestBell.level, bestBell.brightness, bestBell.pan);
    } else {
      applyChannelSpatial('bells', bestBell.level, bestBell.brightness, bestBell.pan);
    }
  }

  async function initSoundscape() {
    if (soundReady || soundLoading) return;
    soundLoading = true;
    const btn = document.getElementById('btn-toggle-sound');
    if (btn) btn.textContent = 'Sound: Loading…';
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      audioCtx = new AC();
      if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
      const comp = audioCtx.createDynamicsCompressor();
      comp.threshold.value = -18;
      comp.knee.value = 20;
      comp.ratio.value = 3.0;
      comp.attack.value = 0.02;
      comp.release.value = 0.28;

      audioMasterGain = audioCtx.createGain();
      audioMasterGain.gain.value = 0.0001;
      comp.connect(audioMasterGain);
      audioMasterGain.connect(audioCtx.destination);

      const entries = Object.entries(SOUND_TRACKS);
      await Promise.all(entries.map(async ([key, cfg], idx) => {
        try {
          const resp = await fetch(`assets/audio/${cfg.file}?v=${assetVer}`);
          if (!resp.ok) return;
          const arrBuf = await resp.arrayBuffer();
          const audioBuf = await audioCtx.decodeAudioData(arrBuf);
          const src = audioCtx.createBufferSource();
          src.buffer = audioBuf;
          src.loop = true;

          const lpf = audioCtx.createBiquadFilter();
          lpf.type = 'lowpass';
          lpf.frequency.value = 1200;
          lpf.Q.value = 0.50;

          const panner = audioCtx.createStereoPanner ? audioCtx.createStereoPanner() : null;
          const gain = audioCtx.createGain();
          gain.gain.value = 0.0001;

          src.connect(lpf);
          if (panner) {
            lpf.connect(panner);
            panner.connect(gain);
          } else {
            lpf.connect(gain);
          }
          gain.connect(comp);
          const startOffset = ((idx * 0.13) % 0.7) * Math.max(0.5, audioBuf.duration);
          src.start(0, startOffset);
          soundChannels[key] = { src, lpf, panner, gain, cfg };
        } catch (_err) {
          // Gracefully skip any track that fails to decode
        }
      }));
      soundReady = true;
    } catch (_err) {
      soundEnabled = false;
    } finally {
      soundLoading = false;
      if (btn) {
        btn.textContent = soundEnabled ? 'Sound: On' : 'Sound: Off';
        btn.classList.toggle('active', soundEnabled);
        btn.setAttribute('aria-pressed', soundEnabled ? 'true' : 'false');
      }
      if (soundReady && audioMasterGain) {
        const now = audioCtx.currentTime;
        audioMasterGain.gain.setTargetAtTime(masterTarget(), now, soundEnabled ? 0.25 : 0.03);
        if (soundEnabled) {
          if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
          lastAudioUpdateMs = 0;
          update(true);
        } else {
          suspendAudioSoon();
        }
      }
    }
  }

  function setEnabled(on) {
    soundEnabled = !!on;
    const btn = document.getElementById('btn-toggle-sound');
    if (btn && !soundLoading) {
      btn.textContent = soundEnabled ? 'Sound: On' : 'Sound: Off';
    }
    if (btn) {
      btn.classList.toggle('active', soundEnabled);
      btn.setAttribute('aria-pressed', soundEnabled ? 'true' : 'false');
    }
    if (soundEnabled) {
      if (audioSuspendTimer) { clearTimeout(audioSuspendTimer); audioSuspendTimer = null; }
      if (!soundReady) {
        initSoundscape();
      } else if (audioCtx && audioMasterGain) {
        audioCtx.resume().catch(() => {});
        audioMasterGain.gain.cancelScheduledValues(audioCtx.currentTime);
        audioMasterGain.gain.setTargetAtTime(masterTarget(), audioCtx.currentTime, 0.25);
        lastAudioUpdateMs = 0;
        update(true);
      }
    } else if (audioCtx && audioMasterGain) {
      audioMasterGain.gain.cancelScheduledValues(audioCtx.currentTime);
      audioMasterGain.gain.setTargetAtTime(0.0001, audioCtx.currentTime, 0.03);
      suspendAudioSoon();
    }
  }

  function forceUpdate() {
    lastAudioUpdateMs = 0;
    if (soundEnabled && soundReady) {
      update(true);
    }
  }

  function handleVisibilityChange(hidden) {
    if (audioCtx && audioMasterGain && soundEnabled) {
      const target = hidden ? 0.0001 : masterTarget();
      audioMasterGain.gain.setTargetAtTime(target, audioCtx.currentTime, 0.15);
    }
  }

  function bindUI() {
    const btnToggleSound = document.getElementById('btn-toggle-sound');
    if (btnToggleSound) {
      btnToggleSound.setAttribute('aria-pressed', 'false');
      btnToggleSound.addEventListener('click', () => setEnabled(!soundEnabled));
    }

    const btnMixer = document.getElementById('btn-audio-mixer');
    const mixerPop = document.getElementById('mixer-popover');
    if (btnMixer && mixerPop) {
      btnMixer.addEventListener('click', (e) => {
        e.stopPropagation();
        const open = mixerPop.classList.toggle('hidden') === false;
        btnMixer.classList.toggle('active', open);
        btnMixer.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      mixerPop.addEventListener('click', (e) => e.stopPropagation());
      document.addEventListener('click', () => {
        if (!mixerPop.classList.contains('hidden')) {
          mixerPop.classList.add('hidden');
          btnMixer.classList.remove('active');
          btnMixer.setAttribute('aria-expanded', 'false');
        }
      });
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !mixerPop.classList.contains('hidden')) {
          mixerPop.classList.add('hidden');
          btnMixer.classList.remove('active');
          btnMixer.setAttribute('aria-expanded', 'false');
          btnMixer.focus();
        }
      });
      mixerPop.querySelectorAll('input[type="range"][data-mix]').forEach((slider) => {
        slider.addEventListener('input', () => {
          const key = slider.dataset.mix;
          mixLevels[key] = Math.max(0, Math.min(1.5, Number(slider.value) / 100));
          const out = slider.parentElement && slider.parentElement.querySelector('output');
          if (out) out.textContent = `${Math.round(mixLevels[key] * 100)}%`;
          if (key === 'master' && audioCtx && audioMasterGain) {
            audioMasterGain.gain.setTargetAtTime(masterTarget(), audioCtx.currentTime, 0.08);
          }
          forceUpdate();
        });
      });
    }
  }

  function startClock() {
    if (clockTimer) return;
    // Spatial audio follows the camera on its own clock so Live: Off keeps updating on pan/zoom/mode-switch
    clockTimer = setInterval(() => {
      if (!soundEnabled || !soundReady || document.hidden) return;
      update(false);
    }, 90);
  }

  return {
    setEnabled,
    isEnabled: () => soundEnabled,
    isReady: () => soundReady,
    getStateName: () => (audioCtx ? audioCtx.state : 'uninitialized'),
    getGainReport: () => ({ ...audioGainReport }),
    forceUpdate,
    update,
    handleVisibilityChange,
    bindUI,
    startClock,
  };
}
