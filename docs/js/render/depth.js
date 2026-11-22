/**
 * 16-bit 3D Z-buffer depth map loader, eroded Lake Zurich water mask,
 * elevated-deck walker depth snapping, and height-aware per-pixel occlusion masking.
 *
 * Preserves all Milestone M1 depth invariants verbatim:
 *   - depthSlopeVert = depthSlopeGround / 3.0
 *   - guarded maxVertPx = Math.max(0, Number.isFinite(extraVertPx) ? extraVertPx : 0)
 *   - unimodal evalRowD16(dyW) mirrored identically in the 3-way fast-path pre-check
 *   - per-class extraVertPx: trains 7.5, buses 6.5, ships 6.0, cars 3.0, cyclists/walkers 2.0
 */

export function createDepthManager() {
  let animData = null;
  let depthPixels = null; // Uint8ClampedArray (R/G = 16-bit scene depth, B = 255 if 3D occluder)
  let depthW = 0;
  let depthH = 0;
  let waterMask = null;   // Uint8Array (1 = eroded pure open water, 0 = shore/rock/boat/pier/land)
  let waterW = 0;
  let waterH = 0;

  const vehScratch = document.createElement('canvas');
  vehScratch.width = 320;
  vehScratch.height = 240;
  const vehScratchCtx = vehScratch.getContext('2d', { willReadFrequently: true });

  const depthFrameStats = { direct: 0, fullCull: 0, partial: 0 };

  function setAnimData(data) {
    animData = data || null;
  }

  function hasDepthMap() {
    return !!(depthPixels && depthW > 0 && depthH > 0);
  }

  function isWaterMaskReady() {
    return !!(waterMask && waterW > 0 && waterH > 0);
  }

  function isWaterUV(u, v) {
    if (!waterMask || waterW <= 0 || waterH <= 0) return true;
    const mx = Math.floor(u * waterW);
    const my = Math.floor(v * waterH);
    if (mx < 0 || mx >= waterW || my < 0 || my >= waterH) return false;
    return waterMask[my * waterW + mx] === 1;
  }

  function loadDepthMap(assetVer = '10.0') {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        try {
          const dc = document.createElement('canvas');
          dc.width = img.naturalWidth;
          dc.height = img.naturalHeight;
          const dctx = dc.getContext('2d', { willReadFrequently: true });
          dctx.drawImage(img, 0, 0);
          depthPixels = dctx.getImageData(0, 0, dc.width, dc.height).data;
          depthW = dc.width;
          depthH = dc.height;
        } catch (_err) {
          depthPixels = null;
          depthW = 0;
          depthH = 0;
        }
        resolve();
      };
      img.onerror = () => resolve();
      img.src = `assets/kilchberg_depth.png?v=${assetVer}`;
    });
  }

  function buildWaterMask(dayImg) {
    if (!dayImg || !dayImg.naturalWidth) return;
    try {
      const mw = Math.floor(dayImg.naturalWidth / 2);
      const mh = Math.floor(dayImg.naturalHeight / 2);
      const wc = document.createElement('canvas');
      wc.width = mw;
      wc.height = mh;
      const wctx = wc.getContext('2d', { willReadFrequently: true });
      wctx.drawImage(dayImg, 0, 0, mw, mh);
      const px = wctx.getImageData(0, 0, mw, mh).data;
      const raw = new Uint8Array(mw * mh);
      for (let y = 0; y < mh; y++) {
        const dy = depthPixels ? Math.min(depthH - 1, Math.floor((y / mh) * depthH)) : 0;
        const dRow = dy * depthW;
        for (let x = 0; x < mw; x++) {
          const i = (y * mw + x) * 4;
          const r = px[i];
          const g = px[i + 1];
          const b = px[i + 2];
          if (b > r + 10 && g > r + 6 && b > 66 && r < 126) {
            if (depthPixels) {
              const dx = Math.min(depthW - 1, Math.floor((x / mw) * depthW));
              if (depthPixels[(dRow + dx) * 4 + 2] > 128) continue;
            }
            raw[y * mw + x] = 1;
          }
        }
      }
      const eroded = new Uint8Array(mw * mh);
      for (let y = 1; y < mh - 1; y++) {
        const row = y * mw;
        for (let x = 1; x < mw - 1; x++) {
          const idx = row + x;
          if (
            raw[idx] && raw[idx - 1] && raw[idx + 1]
            && raw[idx - mw] && raw[idx + mw]
            && raw[idx - mw - 1] && raw[idx - mw + 1]
            && raw[idx + mw - 1] && raw[idx + mw + 1]
          ) {
            eroded[idx] = 1;
          }
        }
      }
      waterMask = eroded;
      waterW = mw;
      waterH = mh;
    } catch (_err) {
      waterMask = null;
      waterW = 0;
      waterH = 0;
    }
  }

  function getDepthConstants() {
    const depthMin = (animData && typeof animData.depth_min === 'number') ? animData.depth_min : -2400.0;
    const depthMax = (animData && typeof animData.depth_max === 'number') ? animData.depth_max : 2400.0;
    const mppMaster = (animData && typeof animData.mpp === 'number') ? animData.mpp : 0.25;
    const u16PerM = 65535.0 / Math.max(1.0, depthMax - depthMin);
    const depthSlopeGround = mppMaster * Math.sqrt(3) * u16PerM;
    const depthSlopeVert = depthSlopeGround / 3.0;
    const shiftY = (animData && Number.isFinite(animData.shift_y))
      ? animData.shift_y
      : (2927.412592 * (0.25 / mppMaster));
    const c0 = (0 - depthMin) * u16PerM + depthSlopeGround * shiftY;
    const slopeZ = 2.0 * 1.16 * u16PerM;
    return { depthMin, depthMax, mppMaster, u16PerM, depthSlopeGround, depthSlopeVert, c0, slopeZ };
  }

  function evalWalkerD16(wx, wy, zGnd, worldW, worldH, onElevatedDeck = false) {
    const dc = getDepthConstants();
    const masterH = (animData && animData.canvas_height) ? animData.canvas_height : 10888;
    const wyMaster = wy * (masterH / Math.max(1, worldH));
    let d16 = Math.round(dc.c0 - dc.depthSlopeGround * wyMaster - dc.slopeZ * (zGnd - 348.0) - 10);
    if (onElevatedDeck && depthPixels && depthW > 0 && depthH > 0) {
      const dx = Math.min(depthW - 1, Math.max(0, Math.floor((wx / Math.max(1, worldW)) * depthW)));
      const dy = Math.min(depthH - 1, Math.max(0, Math.floor((wy / Math.max(1, worldH)) * depthH)));
      const DECK_BAND = 60;
      const DECK_MARGIN = 28;
      const ref = d16;
      let deckMin = Infinity;
      for (let oy = -8; oy <= 1; oy++) {
        const yy = dy + oy;
        if (yy < 0 || yy >= depthH) continue;
        for (let ox = -3; ox <= 3; ox++) {
          const xx = dx + ox;
          if (xx < 0 || xx >= depthW) continue;
          const di = (yy * depthW + xx) * 4;
          if (depthPixels[di + 2] > 128) {
            const deckD16 = (depthPixels[di] << 8) | depthPixels[di + 1];
            if (Math.abs(deckD16 - ref) <= DECK_BAND && deckD16 < deckMin) deckMin = deckD16;
          }
        }
      }
      if (deckMin !== Infinity) d16 = Math.min(d16, deckMin - DECK_MARGIN);
    }
    return d16;
  }

  function resetDepthStats() {
    depthFrameStats.direct = 0;
    depthFrameStats.fullCull = 0;
    depthFrameStats.partial = 0;
  }

  function getDepthStats() {
    return { ...depthFrameStats };
  }

  function drawDepthMasked(ctx, cam, wx, wy, boundsOrPadW, vehD16, worldW, worldH, drawFn, extraVertPx = 4.0) {
    let ex, eyUp, eyDn;
    if (typeof boundsOrPadW === 'object' && boundsOrPadW !== null) {
      ex = boundsOrPadW.ex;
      eyUp = boundsOrPadW.eyUp;
      eyDn = boundsOrPadW.eyDn;
    } else {
      ex = eyUp = eyDn = boundsOrPadW;
    }

    const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
    const cx = offsetX + wx * scale;
    const cy = offsetY + wy * scale;
    const padPx = Math.max(1, Math.min(4, Math.ceil(2 * scale)));
    const padX = Math.ceil(ex * scale) + padPx;
    const padUp = Math.ceil(eyUp * scale) + padPx;
    const padDn = Math.ceil(eyDn * scale) + padPx;
    if (cx + padX < 0 || cx - padX > canvasW || cy + padDn < 0 || cy - padUp > canvasH) return;

    if (!depthPixels || !vehD16 || depthW <= 0 || depthH <= 0) {
      depthFrameStats.direct++;
      drawFn(ctx);
      return;
    }

    const x0 = Math.max(0, Math.floor(cx - padX));
    const y0 = Math.max(0, Math.floor(cy - padUp));
    const x1 = Math.min(canvasW, Math.ceil(cx + padX));
    const y1 = Math.min(canvasH, Math.ceil(cy + padDn));
    const bw = x1 - x0;
    const bh = y1 - y0;
    if (bw <= 0 || bh <= 0) return;

    const dc = getDepthConstants();
    const depthSlopeGround = dc.depthSlopeGround;
    const depthSlopeVert = dc.depthSlopeVert;
    const masterW = (animData && animData.canvas_width) ? animData.canvas_width : 24661;
    const wScaleInv = masterW / Math.max(1, worldW);
    const invWorldScaleX = depthW / (worldW * scale);
    const invWorldScaleY = depthH / (worldH * scale);

    // Row-wise conservative 3-way pre-check over depthPixels before touching vehScratch or getImageData().
    // dyW >= 0 (down along ground toward camera): closer by depthSlopeGround.
    // dyW < 0 (up vertically on vehicle roof): closer by depthSlopeVert, capped at excess height extraVertPx * resFactor.
    const resFactor = 0.25 / dc.mppMaster;
    const maxVertPx = Math.max(0, Number.isFinite(extraVertPx) ? extraVertPx : 0) * resFactor;
    const evalRowD16 = (dyW) => (
      dyW >= 0
        ? vehD16 - dyW * depthSlopeGround
        : vehD16 - Math.min(-dyW, maxVertPx) * depthSlopeVert
    );

    const rawDx0 = Math.floor((x0 - offsetX) * invWorldScaleX);
    const rawDx1 = Math.floor((x1 - 0.5 - offsetX) * invWorldScaleX);
    const rawDy0 = Math.floor((y0 - offsetY) * invWorldScaleY);
    const rawDy1 = Math.floor((y1 - 0.5 - offsetY) * invWorldScaleY);
    const dx0 = Math.max(0, rawDx0);
    const dx1 = Math.min(depthW - 1, rawDx1);
    const dy0 = Math.max(0, rawDy0);
    const dy1 = Math.min(depthH - 1, rawDy1);

    if (dx0 > dx1 || dy0 > dy1) {
      depthFrameStats.direct++;
      drawFn(ctx);
      return;
    }

    {
      let anyFrontOcc = false;
      let anyClear = (rawDx0 < 0 || rawDx1 >= depthW || rawDy0 < 0 || rawDy1 >= depthH);
      const invDepthHWorld = worldH / depthH;
      for (let dy = dy0; dy <= dy1; dy++) {
        const wyTop = dy * invDepthHWorld;
        const wyBot = (dy + 1) * invDepthHWorld;
        const rawTop = (wyTop - wy) * wScaleInv;
        const rawBot = (wyBot - wy) * wScaleInv;
        const dTop = evalRowD16(rawTop);
        const dBot = evalRowD16(rawBot);
        const rowMinD16 = Math.min(dTop, dBot);
        const rowMaxD16 = (rawTop <= 0 && rawBot >= 0) ? vehD16 : Math.max(dTop, dBot);
        const rowOff = dy * depthW;
        for (let dx = dx0; dx <= dx1; dx++) {
          const di = (rowOff + dx) * 4;
          if (depthPixels[di + 2] > 128) {
            const sd = (depthPixels[di] << 8) | depthPixels[di + 1];
            if (sd < rowMaxD16) anyFrontOcc = true;
            if (sd >= rowMinD16) anyClear = true;
          } else {
            anyClear = true;
          }
          if (anyFrontOcc && anyClear) break;
        }
        if (anyFrontOcc && anyClear) break;
      }
      if (!anyFrontOcc) {
        depthFrameStats.direct++;
        drawFn(ctx);
        return;
      }
      if (!anyClear) {
        depthFrameStats.fullCull++;
        return;
      }
    }

    // Genuine partial occlusion: render to vehScratch (never silently drops at 5x-8x zoom)
    depthFrameStats.partial++;
    const MAX_SCRATCH = 2048;
    const scratchScale = Math.min(1.0, MAX_SCRATCH / Math.max(bw, bh));
    const sw = Math.min(MAX_SCRATCH, Math.max(1, Math.ceil(bw * scratchScale)));
    const sh = Math.min(MAX_SCRATCH, Math.max(1, Math.ceil(bh * scratchScale)));
    if (sw > vehScratch.width) vehScratch.width = Math.min(MAX_SCRATCH, sw + 32);
    if (sh > vehScratch.height) vehScratch.height = Math.min(MAX_SCRATCH, sh + 32);

    vehScratchCtx.clearRect(0, 0, sw, sh);
    vehScratchCtx.save();
    if (scratchScale < 1.0) vehScratchCtx.scale(scratchScale, scratchScale);
    vehScratchCtx.translate(-x0, -y0);
    drawFn(vehScratchCtx);
    vehScratchCtx.restore();

    const imgData = vehScratchCtx.getImageData(0, 0, sw, sh);
    const d = imgData.data;
    const invScale = 1 / scale;
    const invScratch = 1 / scratchScale;
    let anyVisible = false;

    for (let ly = 0; ly < sh; ly++) {
      const sy = y0 + (ly + 0.5) * invScratch;
      const dy = Math.floor((sy - offsetY) * invWorldScaleY);
      const wyPix = (sy - offsetY) * invScale;
      const dyW = (wyPix - wy) * wScaleInv;
      const rowD16 = evalRowD16(dyW);
      const validY = dy >= 0 && dy < depthH;
      const rowOff = dy * depthW;
      const pRow = ly * sw * 4;
      for (let lx = 0; lx < sw; lx++) {
        const p = pRow + lx * 4;
        if (d[p + 3] === 0) continue;
        if (validY) {
          const sx = x0 + (lx + 0.5) * invScratch;
          const dx = Math.floor((sx - offsetX) * invWorldScaleX);
          if (dx >= 0 && dx < depthW) {
            const di = (rowOff + dx) * 4;
            if (depthPixels[di + 2] > 128) {
              const sceneD16 = (depthPixels[di] << 8) | depthPixels[di + 1];
              if (rowD16 > sceneD16) {
                d[p + 3] = 0;
                continue;
              }
            }
          }
        }
        anyVisible = true;
      }
    }
    if (anyVisible) {
      vehScratchCtx.putImageData(imgData, 0, 0);
      if (scratchScale < 1.0) {
        ctx.save();
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(vehScratch, 0, 0, sw, sh, x0, y0, bw, bh);
        ctx.restore();
      } else {
        ctx.drawImage(vehScratch, 0, 0, sw, sh, x0, y0, bw, bh);
      }
    }
  }

  function isOccludedAt(wx, wy, d16, worldW, worldH) {
    if (!depthPixels || depthW <= 0 || depthH <= 0 || !Number.isFinite(d16)) return false;
    const dx = Math.min(depthW - 1, Math.max(0, Math.floor((wx / Math.max(1, worldW)) * depthW)));
    const dy = Math.min(depthH - 1, Math.max(0, Math.floor((wy / Math.max(1, worldH)) * depthH)));
    const di = (dy * depthW + dx) * 4;
    if (depthPixels[di + 2] <= 128) return false;
    const sceneD16 = (depthPixels[di] << 8) | depthPixels[di + 1];
    return d16 > sceneD16 + 8;
  }

  return {
    setAnimData,
    loadDepthMap,
    buildWaterMask,
    hasDepthMap,
    isWaterMaskReady,
    isWaterUV,
    getDepthConstants,
    evalWalkerD16,
    isOccludedAt,
    resetDepthStats,
    getDepthStats,
    drawDepthMasked,
  };
}
