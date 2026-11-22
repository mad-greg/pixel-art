/**
 * Async off-main-thread ImageBitmap tile pyramid streamer for the Kilchberg diorama.
 *
 * Features:
 *   - Off-main-thread decode: fetch() -> blob() -> createImageBitmap(blob) with HTMLImageElement.decode() fallback
 *   - Bounded concurrency (MAX_INFLIGHT = 8) + AbortController for stale off-viewport tiles
 *   - Viewport-center priority queue + LRU eviction (MAX_CACHED_TILES = 128) calling bmp.close()
 *   - Target-zoom LOD prefetch on frame 1 (bounded strictly to target viewport; 0 L2 tiles at Fit for T2.FA3.11)
 *   - Velocity-gated heavy decode (renderQuick during fast flicks)
 *   - +0.5 px seam overlap, adaptive imageSmoothingQuality, and 120 ms crossfade (bypassed when fixedAnimTime !== null)
 *   - Reads all tile grid dimensions dynamically from manifest.json
 */

export function createTileManager(opts = {}) {
  const assetVer = opts.assetVer || '12.0';
  const MAX_INFLIGHT = opts.maxInflight || 8;
  const MAX_CACHED_TILES = opts.maxCached || 128;
  const CROSSFADE_MS = opts.crossfadeMs != null ? opts.crossfadeMs : 120;
  const QUICK_SPEED_PX_SEC = opts.quickSpeedPxPerSec || 1800;
  const onTileReady = opts.onTileReady || null;

  let activeMode = 'day';
  const manifests = Object.create(null); // mode -> manifest | null

  // LRU cache: key -> { bmp, width, height, readyAtMs }
  const cache = new Map();
  // Active fetches: key -> { controller, mode, priority }
  const inflight = new Map();
  // Pending queue: key -> { key, url, mode, priority }
  const queue = new Map();
  // Permanent 404/error keys so we don't spin
  const errorKeys = new Set();
  // Keys needed in the current frame (protected from LRU eviction)
  const visibleKeys = new Set();

  let decodedCount = 0;

  function setMode(mode) {
    if (activeMode === mode) return;
    activeMode = mode;
    // Abort any in-flight fetches from the previous mode and clear stale queue entries
    for (const [key, item] of inflight.entries()) {
      if (item.mode !== activeMode) {
        try { item.controller.abort(); } catch (_) {}
        inflight.delete(key);
      }
    }
    for (const [key, item] of queue.entries()) {
      if (item.mode !== activeMode) {
        queue.delete(key);
      }
    }
  }

  function setManifest(mode, manifest) {
    manifests[mode] = manifest || null;
  }

  function closeEntry(entry) {
    if (entry && entry.bmp && typeof entry.bmp.close === 'function') {
      try { entry.bmp.close(); } catch (_) {}
    }
  }

  function evictLRU() {
    if (cache.size <= MAX_CACHED_TILES) return;
    for (const [key, entry] of cache.entries()) {
      if (cache.size <= MAX_CACHED_TILES) break;
      if (!visibleKeys.has(key)) {
        closeEntry(entry);
        cache.delete(key);
      }
    }
  }

  function clearAll() {
    for (const item of inflight.values()) {
      try { item.controller.abort(); } catch (_) {}
    }
    inflight.clear();
    queue.clear();
    for (const entry of cache.values()) {
      closeEntry(entry);
    }
    cache.clear();
    errorKeys.clear();
    visibleKeys.clear();
  }

  async function fetchAndDecode(url, signal) {
    const resp = await fetch(url, { signal });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    if (signal && signal.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    if (typeof createImageBitmap === 'function') {
      return await createImageBitmap(blob);
    }
    // Fallback for environments without createImageBitmap
    const objUrl = URL.createObjectURL(blob);
    try {
      const img = new Image();
      img.src = objUrl;
      if (typeof img.decode === 'function') {
        await img.decode();
      } else {
        await new Promise((res, rej) => {
          img.onload = res;
          img.onerror = rej;
        });
      }
      return img;
    } finally {
      URL.revokeObjectURL(objUrl);
    }
  }

  function drainQueue() {
    if (inflight.size >= MAX_INFLIGHT || queue.size === 0) return;

    // Pick lowest-priority-number (highest urgency) items first
    const candidates = Array.from(queue.values());
    candidates.sort((a, b) => a.priority - b.priority);

    for (let i = 0; i < candidates.length && inflight.size < MAX_INFLIGHT; i++) {
      const req = candidates[i];
      queue.delete(req.key);
      if (cache.has(req.key) || inflight.has(req.key) || errorKeys.has(req.key)) continue;

      const controller = new AbortController();
      inflight.set(req.key, { controller, mode: req.mode, priority: req.priority });

      fetchAndDecode(req.url, controller.signal)
        .then((bmp) => {
          const cur = inflight.get(req.key);
          if (cur && cur.controller === controller) inflight.delete(req.key);
          if (controller.signal.aborted) {
            if (bmp && typeof bmp.close === 'function') {
              try { bmp.close(); } catch (_) {}
            }
            drainQueue();
            return;
          }
          const existing = cache.get(req.key);
          if (existing) {
            closeEntry(existing);
            cache.delete(req.key);
          }
          cache.set(req.key, {
            bmp,
            width: bmp.width || bmp.naturalWidth || 1024,
            height: bmp.height || bmp.naturalHeight || 1024,
            readyAtMs: performance.now(),
          });
          decodedCount++;
          evictLRU();
          if (onTileReady) onTileReady(req.key);
          drainQueue();
        })
        .catch((err) => {
          const cur = inflight.get(req.key);
          if (cur && cur.controller === controller) inflight.delete(req.key);
          if (!controller.signal.aborted && (!err || err.name !== 'AbortError')) {
            errorKeys.add(req.key);
          }
          drainQueue();
        });
    }
  }

  function requestTile(mode, level, col, row, subPath, priority) {
    const key = `${mode}:${level}:${col}_${row}`;
    visibleKeys.add(key);

    const cached = cache.get(key);
    if (cached) {
      // Touch LRU
      cache.delete(key);
      cache.set(key, cached);
      return cached;
    }
    if (errorKeys.has(key)) return null;

    if (inflight.has(key)) {
      const inf = inflight.get(key);
      if (priority < inf.priority) inf.priority = priority;
      return null;
    }

    const relPath = subPath ? `${mode}/${subPath}/${col}_${row}.webp` : `${mode}/${col}_${row}.webp`;
    const url = `assets/tiles/${relPath}?v=${assetVer}`;
    const existingQ = queue.get(key);
    if (!existingQ || priority < existingQ.priority) {
      queue.set(key, { key, url, mode, priority });
    }
    return null;
  }

  function getTileImage(mode, level, col, row, subPath = '') {
    const entry = requestTile(mode, level, col, row, subPath, 0);
    drainQueue();
    return entry ? entry.bmp : null;
  }

  function drawSingleTile(ctx, entry, tx0, ty0, tw, th, snapInt, alpha) {
    const prevAlpha = ctx.globalAlpha;
    if (alpha < 0.999) ctx.globalAlpha = prevAlpha * alpha;
    if (snapInt) {
      const rx0 = Math.round(tx0);
      const ry0 = Math.round(ty0);
      const rx1 = Math.round(tx0 + tw);
      const ry1 = Math.round(ty0 + th);
      ctx.drawImage(entry.bmp, rx0, ry0, rx1 - rx0, ry1 - ry0);
    } else {
      // +0.5 px overlap eliminates fractional-zoom hairline tile seams
      ctx.drawImage(entry.bmp, tx0, ty0, tw + 0.5, th + 0.5);
    }
    if (alpha < 0.999) ctx.globalAlpha = prevAlpha;
  }

  function drawTiles(ctx, view, drawOpts = {}) {
    const mode = drawOpts.mode || activeMode;
    const mf = manifests[mode];
    const {
      width: canvasW,
      height: canvasH,
      offsetX,
      offsetY,
      scale,
      targetScale,
      worldW,
      worldH,
      overview,
      moving = false,
      speedPxPerSec = 0,
      vx = 0,
      vy = 0,
      fixedAnimTime = null,
      nowMs = performance.now(),
    } = view;

    visibleKeys.clear();

    const ovWidth = overview ? overview.width : 0;
    const z1 = (mf && mf.z1 && mf.z1.width && mf.z1.height && mf.z1.cols && mf.z1.rows) ? mf.z1 : null;
    const tiled = !!(mf && mf.width && mf.height && mf.cols && mf.rows);

    const needTiles = tiled && (!overview || (worldW * scale) > ovWidth * 0.98);
    const useZ1 = !!(needTiles && z1 && (worldW * scale) <= z1.width * 1.05);

    // Target-zoom LOD prefetch on frame 1 when zooming in
    const effTargetScale = targetScale || scale;
    const targetNeedTiles = tiled && (!overview || (worldW * effTargetScale) > ovWidth * 0.98);
    const targetUseZ1 = !!(targetNeedTiles && z1 && (worldW * effTargetScale) <= z1.width * 1.05);
    const renderQuick = speedPxPerSec > QUICK_SPEED_PX_SEC;

    // Snap cleanly ONLY when stationary at exact integer pixel zooms (1x/2x/4x)
    const snapInt = !moving && scale >= 0.95 && Math.abs(scale - Math.round(scale)) < 0.02;

    let tilesLoaded = 0;
    let tilesVisible = 0;
    let crossfading = false;
    let tileLevel = 'overview';
    let activeMpp = mf ? mf.mpp : null;

    if (needTiles && useZ1) {
      tileLevel = 'z1';
      activeMpp = z1.mpp || (mf && mf.mpp ? mf.mpp * (mf.width / z1.width) : 0.22);
      const z1ts = z1.tileSize || 1024;
      const z1Path = z1.path || 'z1';
      const scaleX = worldW / z1.width;
      const scaleY = worldH / z1.height;
      const c0 = Math.max(0, Math.floor((-offsetX / (scale * scaleX)) / z1ts));
      const c1 = Math.min(z1.cols - 1, Math.floor(((canvasW - offsetX) / (scale * scaleX)) / z1ts));
      const r0 = Math.max(0, Math.floor((-offsetY / (scale * scaleY)) / z1ts));
      const r1 = Math.min(z1.rows - 1, Math.floor(((canvasH - offsetY) / (scale * scaleY)) / z1ts));
      const midC = (c0 + c1) * 0.5;
      const midR = (r0 + r1) * 0.5;

      ctx.imageSmoothingEnabled = moving || (scale * scaleX) < 0.95;
      ctx.imageSmoothingQuality = moving ? 'low' : 'high';

      for (let r = r0; r <= r1; r++) {
        for (let c = c0; c <= c1; c++) {
          tilesVisible++;
          const dist = Math.hypot(c - midC, r - midR);
          const entry = requestTile(mode, 'z1', c, r, z1Path, dist);
          if (entry) {
            tilesLoaded++;
            const tx0 = offsetX + c * z1ts * scaleX * scale;
            const ty0 = offsetY + r * z1ts * scaleY * scale;
            const tw = entry.width * scaleX * scale;
            const th = entry.height * scaleY * scale;
            const alpha = (fixedAnimTime !== null || CROSSFADE_MS <= 0)
              ? 1
              : Math.min(1, Math.max(0, (nowMs - entry.readyAtMs) / CROSSFADE_MS));
            if (alpha < 0.999) crossfading = true;
            drawSingleTile(ctx, entry, tx0, ty0, tw, th, false, alpha);
          }
        }
      }
    } else if (needTiles) {
      tileLevel = 'l2';
      activeMpp = mf.mpp;
      const ts = mf.tileSize;
      const c0 = Math.max(0, Math.floor((-offsetX / scale) / ts));
      const c1 = Math.min(mf.cols - 1, Math.floor(((canvasW - offsetX) / scale) / ts));
      const r0 = Math.max(0, Math.floor((-offsetY / scale) / ts));
      const r1 = Math.min(mf.rows - 1, Math.floor(((canvasH - offsetY) / scale) / ts));
      const midC = (c0 + c1) * 0.5;
      const midR = (r0 + r1) * 0.5;

      const l2List = [];
      let anyMissing = false;
      for (let r = r0; r <= r1; r++) {
        for (let c = c0; c <= c1; c++) {
          tilesVisible++;
          const dist = Math.hypot(c - midC, r - midR);
          // During fast flicks (renderQuick), still paint already-cached tiles, defer new L2 fetches
          const key = `${mode}:l2:${c}_${r}`;
          let entry = cache.get(key);
          if (entry) {
            visibleKeys.add(key);
            cache.delete(key);
            cache.set(key, entry);
          } else if (!renderQuick) {
            entry = requestTile(mode, 'l2', c, r, '', dist);
          }
          if (entry) {
            tilesLoaded++;
            l2List.push({ c, r, entry });
          } else {
            anyMissing = true;
          }
        }
      }

      // Progressive fallback: if any L2 tile is still decoding/deferred, paint cached z1 tiles underneath
      if (anyMissing && z1) {
        const z1ts = z1.tileSize || 1024;
        const scaleX = worldW / z1.width;
        const scaleY = worldH / z1.height;
        const zc0 = Math.max(0, Math.floor((-offsetX / (scale * scaleX)) / z1ts));
        const zc1 = Math.min(z1.cols - 1, Math.floor(((canvasW - offsetX) / (scale * scaleX)) / z1ts));
        const zr0 = Math.max(0, Math.floor((-offsetY / (scale * scaleY)) / z1ts));
        const zr1 = Math.min(z1.rows - 1, Math.floor(((canvasH - offsetY) / (scale * scaleY)) / z1ts));
        ctx.imageSmoothingEnabled = moving || (scale * scaleX) < 0.95;
        ctx.imageSmoothingQuality = moving ? 'low' : 'high';
        for (let r = zr0; r <= zr1; r++) {
          for (let c = zc0; c <= zc1; c++) {
            const zKey = `${mode}:z1:${c}_${r}`;
            const zEntry = cache.get(zKey);
            if (zEntry) {
              visibleKeys.add(zKey);
              const tx0 = offsetX + c * z1ts * scaleX * scale;
              const ty0 = offsetY + r * z1ts * scaleY * scale;
              const tw = zEntry.width * scaleX * scale;
              const th = zEntry.height * scaleY * scale;
              drawSingleTile(ctx, zEntry, tx0, ty0, tw, th, false, 1);
            }
          }
        }
      }

      ctx.imageSmoothingEnabled = moving || scale < 0.95;
      ctx.imageSmoothingQuality = moving ? 'low' : 'high';
      for (let i = 0; i < l2List.length; i++) {
        const { c, r, entry } = l2List[i];
        const tx0 = offsetX + c * ts * scale;
        const ty0 = offsetY + r * ts * scale;
        const tw = entry.width * scale;
        const th = entry.height * scale;
        const alpha = (fixedAnimTime !== null || CROSSFADE_MS <= 0)
          ? 1
          : Math.min(1, Math.max(0, (nowMs - entry.readyAtMs) / CROSSFADE_MS));
        if (alpha < 0.999) crossfading = true;
        drawSingleTile(ctx, entry, tx0, ty0, tw, th, snapInt, alpha);
      }

      // Bounded velocity-directed prefetch (only when moving moderately, <= 4 tiles ahead)
      if (!renderQuick && speedPxPerSec > 40 && speedPxPerSec <= QUICK_SPEED_PX_SEC) {
        // Camera offset moves opposite to viewport movement in world space
        const stepC = vx < -30 ? 1 : (vx > 30 ? -1 : 0);
        const stepR = vy < -30 ? 1 : (vy > 30 ? -1 : 0);
        let prefetched = 0;
        if (stepC !== 0) {
          const pc = stepC > 0 ? c1 + 1 : c0 - 1;
          if (pc >= 0 && pc < mf.cols) {
            for (let r = r0; r <= r1 && prefetched < 4; r++) {
              requestTile(mode, 'l2', pc, r, '', 1000 + Math.abs(r - midR));
              prefetched++;
            }
          }
        }
        if (stepR !== 0 && prefetched < 4) {
          const pr = stepR > 0 ? r1 + 1 : r0 - 1;
          if (pr >= 0 && pr < mf.rows) {
            for (let c = c0; c <= c1 && prefetched < 4; c++) {
              requestTile(mode, 'l2', c, pr, '', 1000 + Math.abs(c - midC));
              prefetched++;
            }
          }
        }
      }
    }

    // Target-zoom LOD prefetch on frame 1 when zooming in (strictly bounded to target viewport; NEVER at Fit!)
    if (!renderQuick && targetNeedTiles && effTargetScale > scale * 1.08) {
      // Compute the target viewport around the current viewport centre at effTargetScale
      const cwx = (canvasW * 0.5 - offsetX) / Math.max(1e-6, scale);
      const cwy = (canvasH * 0.5 - offsetY) / Math.max(1e-6, scale);
      const tOffX = canvasW * 0.5 - cwx * effTargetScale;
      const tOffY = canvasH * 0.5 - cwy * effTargetScale;

      if (targetUseZ1 && z1) {
        const z1ts = z1.tileSize || 1024;
        const z1Path = z1.path || 'z1';
        const scaleX = worldW / z1.width;
        const scaleY = worldH / z1.height;
        const tc0 = Math.max(0, Math.floor((-tOffX / (effTargetScale * scaleX)) / z1ts));
        const tc1 = Math.min(z1.cols - 1, Math.floor(((canvasW - tOffX) / (effTargetScale * scaleX)) / z1ts));
        const tr0 = Math.max(0, Math.floor((-tOffY / (effTargetScale * scaleY)) / z1ts));
        const tr1 = Math.min(z1.rows - 1, Math.floor(((canvasH - tOffY) / (effTargetScale * scaleY)) / z1ts));
        if ((tc1 - tc0 + 1) * (tr1 - tr0 + 1) <= 16) {
          for (let r = tr0; r <= tr1; r++) {
            for (let c = tc0; c <= tc1; c++) {
              requestTile(mode, 'z1', c, r, z1Path, 500 + Math.hypot(c - (tc0 + tc1) * 0.5, r - (tr0 + tr1) * 0.5));
            }
          }
        }
      } else if (!targetUseZ1) {
        const ts = mf.tileSize;
        const tc0 = Math.max(0, Math.floor((-tOffX / effTargetScale) / ts));
        const tc1 = Math.min(mf.cols - 1, Math.floor(((canvasW - tOffX) / effTargetScale) / ts));
        const tr0 = Math.max(0, Math.floor((-tOffY / effTargetScale) / ts));
        const tr1 = Math.min(mf.rows - 1, Math.floor(((canvasH - tOffY) / effTargetScale) / ts));
        // Strictly cap target prefetch so Fit -> 1:1 stays well within T2.FA3.11 (1..48 L2 tiles)
        if ((tc1 - tc0 + 1) * (tr1 - tr0 + 1) <= 16) {
          for (let r = tr0; r <= tr1; r++) {
            for (let c = tc0; c <= tc1; c++) {
              requestTile(mode, 'l2', c, r, '', 500 + Math.hypot(c - (tc0 + tc1) * 0.5, r - (tr0 + tr1) * 0.5));
            }
          }
        }
      }
    }

    // Prune stale queued tiles no longer in the viewport or prefetch set
    for (const key of queue.keys()) {
      if (!visibleKeys.has(key)) {
        queue.delete(key);
      }
    }

    // Abort stale off-viewport in-flight requests if urgent tiles are waiting
    if (queue.size > 0) {
      for (const [key, item] of inflight.entries()) {
        if (!visibleKeys.has(key)) {
          try { item.controller.abort(); } catch (_) {}
          inflight.delete(key);
        }
      }
    }

    drainQueue();
    evictLRU();

    return {
      needTiles,
      useZ1,
      tileLevel,
      activeMpp,
      tilesLoaded,
      tilesVisible,
      crossfading,
    };
  }

  function getStats() {
    return {
      cacheSize: cache.size,
      inflight: inflight.size,
      queued: queue.size,
      decodedCount,
    };
  }

  return {
    setMode,
    setManifest,
    drawTiles,
    getTileImage,
    getStats,
    clearAll,
  };
}
