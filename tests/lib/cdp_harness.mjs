/**
 * Zero-dependency Node 24 Chrome DevTools Protocol (CDP) E2E harness for /usr/bin/chromium.
 *
 * - Serves docs/ over an ephemeral 127.0.0.1:0 static HTTP server with proper MIME types.
 * - Launches ONE shared headless Chromium process per suite without --autoplay-policy overrides,
 *   discovering its debugging endpoint via <userDataDir>/DevToolsActivePort (stderr fallback).
 * - Creates isolated incognito tabs via Target.createBrowserContext({ disposeOnDetach: true })
 *   multiplexed over a single browser WebSocket (flatten: true).
 * - Provides real trusted Input.dispatchMouseEvent / Input.dispatchKeyEvent helpers,
 *   offline font CDN blocking, same-origin error tracking, fast canvas sampling, and strict teardown.
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
export const REPO_ROOT = path.resolve(__dirname, '..', '..');
export const DOCS_DIR = path.join(REPO_ROOT, 'docs');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webp': 'image/webp',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.mp3': 'audio/mpeg',
  '.ico': 'image/x-icon',
};

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function assert(cond, msg) {
  if (!cond) {
    throw new AssertionError(msg || 'Assertion failed');
  }
}

export class AssertionError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AssertionError';
  }
}

/**
 * Ephemeral static HTTP server for docs/ with safe error handling and instant shutdown.
 */
async function startStaticServer(rootDir) {
  const sockets = new Set();
  const server = http.createServer((req, res) => {
    res.on('error', () => {});
    const rawUrl = (req.url || '/').split('?')[0];
    let relPath;
    try {
      relPath = decodeURIComponent(rawUrl);
    } catch {
      res.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Bad Request');
      return;
    }
    if (relPath === '/' || relPath === '') relPath = '/index.html';
    const safePath = path.normalize(relPath).replace(/^(\.\.(\/|\\|$))+/, '');
    const fullPath = path.join(rootDir, safePath);

    if (!fullPath.startsWith(rootDir)) {
      res.writeHead(403);
      res.end('Forbidden');
      return;
    }

    fs.stat(fullPath, (err, stat) => {
      if (err || !stat.isFile()) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('Not Found');
        return;
      }
      const ext = path.extname(fullPath).toLowerCase();
      const mime = MIME_TYPES[ext] || 'application/octet-stream';
      res.writeHead(200, {
        'Content-Type': mime,
        'Content-Length': stat.size,
        'Cache-Control': 'no-cache',
      });
      const stream = fs.createReadStream(fullPath);
      stream.on('error', () => {
        if (!res.writableEnded) res.destroy();
      });
      res.on('close', () => {
        if (!stream.destroyed) stream.destroy();
      });
      stream.pipe(res);
    });
  });

  server.on('connection', (sock) => {
    sockets.add(sock);
    sock.on('close', () => sockets.delete(sock));
    sock.on('error', () => {});
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });

  const addr = server.address();
  const baseUrl = `http://127.0.0.1:${addr.port}`;

  function destroySync() {
    for (const sock of sockets) {
      try { sock.destroy(); } catch {}
    }
    sockets.clear();
    try { server.close(); } catch {}
  }

  async function close() {
    for (const sock of sockets) {
      try { sock.destroy(); } catch {}
    }
    sockets.clear();
    await new Promise((resolve) => server.close(() => resolve()));
  }

  return { server, baseUrl, port: addr.port, close, destroySync };
}

/**
 * Low-level multiplexed CDP WebSocket client.
 */
class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.nextId = 1;
    this.pending = new Map();
    this.sessionListeners = new Map(); // sessionId (or '') -> Map<method, Set<fn>>
  }

  async connect(timeoutMs = 10000) {
    await new Promise((resolve, reject) => {
      const ws = new WebSocket(this.wsUrl);
      this.ws = ws;
      const timer = setTimeout(() => {
        try { ws.close(); } catch {}
        reject(new Error(`CDP WebSocket connect timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      ws.addEventListener('open', () => {
        clearTimeout(timer);
        resolve();
      });
      ws.addEventListener('error', (ev) => {
        clearTimeout(timer);
        reject(new Error(`CDP WebSocket error: ${ev?.message || 'connection failed'}`));
      });
      ws.addEventListener('close', () => {
        for (const [id, entry] of this.pending.entries()) {
          clearTimeout(entry.timer);
          entry.reject(new Error(`CDP WebSocket closed while awaiting id=${id}`));
        }
        this.pending.clear();
      });
      ws.addEventListener('message', (ev) => {
        let msg;
        try {
          msg = JSON.parse(typeof ev.data === 'string' ? ev.data : String(ev.data));
        } catch {
          return;
        }
        if (msg.id !== undefined) {
          const entry = this.pending.get(msg.id);
          if (entry) {
            this.pending.delete(msg.id);
            clearTimeout(entry.timer);
            if (msg.error) {
              entry.reject(new Error(`CDP ${entry.method} failed: ${msg.error.message || JSON.stringify(msg.error)}`));
            } else {
              entry.resolve(msg.result || {});
            }
          }
          return;
        }
        if (msg.method) {
          const sid = msg.sessionId || '';
          const map = this.sessionListeners.get(sid);
          if (map) {
            const set = map.get(msg.method);
            if (set) {
              for (const fn of [...set]) {
                try { fn(msg.params || {}); } catch {}
              }
            }
          }
        }
      });
    });
  }

  send(method, params = {}, sessionId = undefined, timeoutMs = 15000) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error(`CDP send(${method}) called while WebSocket is not open`));
    }
    const id = this.nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP ${method} timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer, method });
      try {
        this.ws.send(JSON.stringify(payload));
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(err);
      }
    });
  }

  on(sessionId, method, fn) {
    const sid = sessionId || '';
    let map = this.sessionListeners.get(sid);
    if (!map) {
      map = new Map();
      this.sessionListeners.set(sid, map);
    }
    let set = map.get(method);
    if (!set) {
      set = new Set();
      map.set(method, set);
    }
    set.add(fn);
    return () => set.delete(fn);
  }

  clearSessionListeners(sessionId) {
    this.sessionListeners.delete(sessionId || '');
  }

  close() {
    if (this.ws) {
      try { this.ws.close(); } catch {}
      this.ws = null;
    }
    this.sessionListeners.clear();
  }
}

/**
 * Isolated incognito browser tab driven via CDP sessionId.
 */
export class CDPTab {
  constructor(harness, { browserContextId, targetId, sessionId }) {
    this.harness = harness;
    this.cdp = harness.cdp;
    this.baseUrl = harness.baseUrl;
    this.browserContextId = browserContextId;
    this.targetId = targetId;
    this.sessionId = sessionId;
    this.closed = false;

    this.requestUrls = new Map();
    this.responses = [];
    this.localHttpErrors = [];
    this.localLoadFailures = [];
    this.exceptions = [];
    this.consoleErrors = [];
    this.tileResponses = [];
    this.audioResponses = [];
  }

  send(method, params = {}, timeoutMs = 15000) {
    return this.cdp.send(method, params, this.sessionId, timeoutMs);
  }

  on(method, fn) {
    return this.cdp.on(this.sessionId, method, fn);
  }

  _installTelemetry() {
    this.on('Network.requestWillBeSent', (p) => {
      if (p.requestId && p.request?.url) {
        this.requestUrls.set(p.requestId, p.request.url);
      }
    });

    this.on('Network.responseReceived', (p) => {
      const url = p.response?.url || this.requestUrls.get(p.requestId) || '';
      const status = p.response?.status ?? 0;
      const isLocal = url.startsWith(this.baseUrl);
      const rec = { url, status, isLocal };
      this.responses.push(rec);

      if (isLocal) {
        const pathname = new URL(url).pathname;
        if (status >= 400 && pathname !== '/favicon.ico') {
          this.localHttpErrors.push(rec);
        }
        if (status === 200 && pathname.includes('/assets/tiles/') && pathname.endsWith('.webp')) {
          this.tileResponses.push(rec);
        }
        if (status === 200 && pathname.includes('/assets/audio/') && pathname.endsWith('.mp3')) {
          this.audioResponses.push(rec);
        }
      }
    });

    this.on('Network.loadingFailed', (p) => {
      const url = this.requestUrls.get(p.requestId) || '';
      if (!url.startsWith(this.baseUrl)) return;
      if (p.blockedReason === 'inspector') return;
      if (p.canceled) return;
      const pathname = new URL(url).pathname;
      if (pathname === '/favicon.ico') return;
      this.localLoadFailures.push({
        url,
        errorText: p.errorText || 'unknown',
        blockedReason: p.blockedReason || '',
      });
    });

    this.on('Runtime.exceptionThrown', (p) => {
      const ex = p.exceptionDetails || {};
      const desc = ex.exception?.description || ex.text || 'Uncaught exception';
      this.exceptions.push(String(desc).split('\n')[0]);
    });

    this.on('Runtime.consoleAPICalled', (p) => {
      if (p.type === 'error') {
        const txt = (p.args || [])
          .map((a) => (a.value !== undefined ? String(a.value) : a.description || a.type))
          .join(' ');
        // Ignore font CDN errors if any slipped through
        if (txt.includes('fonts.googleapis.com') || txt.includes('fonts.gstatic.com')) return;
        this.consoleErrors.push(txt || 'console.error');
      }
    });
  }

  resetNetworkCounters() {
    this.tileResponses.length = 0;
    this.audioResponses.length = 0;
  }

  async evaluate(expression, timeoutMs = 15000) {
    const res = await this.send(
      'Runtime.evaluate',
      {
        expression,
        awaitPromise: true,
        returnByValue: true,
      },
      timeoutMs,
    );
    if (res.exceptionDetails) {
      const desc =
        res.exceptionDetails.exception?.description ||
        res.exceptionDetails.text ||
        'Runtime.evaluate exception';
      throw new Error(`Page eval error: ${String(desc).split('\n')[0]}`);
    }
    return res.result ? res.result.value : undefined;
  }

  async getDebug() {
    return this.evaluate(
      `(() => {
        if (typeof window.__dioramaDebug === 'function') return window.__dioramaDebug();
        if (window.__dioramaDebug && typeof window.__dioramaDebug === 'object') {
          return JSON.parse(JSON.stringify(window.__dioramaDebug));
        }
        return null;
      })()`,
    );
  }

  async waitFor(expression, { timeoutMs = 4000, intervalMs = 60 } = {}) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const val = await this.evaluate(expression);
      if (val) return val;
      await sleep(intervalMs);
    }
    return null;
  }

  async waitForDioramaReady(timeoutMs = 15000) {
    const ready = await this.waitFor(
      `(() => {
        const items = document.querySelectorAll('#landmark-list .lm-item');
        if (items.length < 10) return false;
        const c = document.getElementById('diorama-canvas');
        if (!c || c.width < 10 || c.height < 10) return false;
        try {
          const ctx = c.getContext('2d');
          if (!ctx) return false;
          const cx = Math.floor(c.width * 0.5);
          const cy = Math.floor(c.height * 0.5);
          const d = ctx.getImageData(cx, cy, 4, 4).data;
          let sum = 0;
          for (let i = 0; i < d.length; i += 4) sum += d[i] + d[i+1] + d[i+2];
          return sum > 0;
        } catch {
          return false;
        }
      })()`,
      { timeoutMs, intervalMs: 120 },
    );
    if (!ready) {
      throw new Error(`Diorama did not reach ready state within ${timeoutMs}ms`);
    }
    await sleep(80);
  }

  /**
   * Navigate this existing incognito tab to a new relative URL, awaiting Page.loadEventFired
   * and optional diorama ready check (reuses browser HTTP cache for fast multi-view checks).
   */
  async navigate(relUrl, { waitReady = true, readyTimeoutMs = 15000, loadTimeoutMs = 20000 } = {}) {
    const fullUrl = relUrl.startsWith('http')
      ? relUrl
      : `${this.baseUrl}${relUrl.startsWith('/') ? '' : '/'}${relUrl}`;

    let timer = null;
    let off = () => {};
    const loadPromise = new Promise((resolve, reject) => {
      timer = setTimeout(() => {
        off();
        reject(new Error(`Page.loadEventFired timed out for ${fullUrl}`));
      }, loadTimeoutMs);
      off = this.on('Page.loadEventFired', () => {
        clearTimeout(timer);
        timer = null;
        off();
        resolve();
      });
    });

    try {
      await this.send('Page.navigate', { url: fullUrl }, loadTimeoutMs);
      await loadPromise;
    } finally {
      if (timer) clearTimeout(timer);
      off();
    }

    if (waitReady) {
      await this.waitForDioramaReady(readyTimeoutMs);
    }
  }

  /**
   * Wait until F24 cubic ease-out camera kinematics (u, v, scale) settle for `settleMs`.
   * Falls back cleanly after ~350 ms when window.__dioramaDebug is absent (v6.2).
   */
  async waitForCameraSettled({ maxWaitMs = 950, settleMs = 140, pollMs = 70 } = {}) {
    const t0 = Date.now();
    // Allow initial animation frame to kick off camera flight/easing
    await sleep(70);
    let prev = await this.getDebug();
    if (
      !prev ||
      typeof prev.u !== 'number' ||
      typeof prev.v !== 'number' ||
      typeof prev.scale !== 'number'
    ) {
      await sleep(280);
      return null;
    }

    let stableSince = null;
    const deadline = t0 + maxWaitMs;
    while (Date.now() < deadline) {
      await sleep(pollMs);
      const cur = await this.getDebug();
      if (!cur || typeof cur.u !== 'number' || typeof cur.v !== 'number' || typeof cur.scale !== 'number') {
        return cur;
      }
      const du = Math.abs(cur.u - prev.u);
      const dv = Math.abs(cur.v - prev.v);
      const ds = Math.abs(cur.scale - prev.scale);
      const now = Date.now();
      if (du < 0.0008 && dv < 0.0008 && ds < 0.015) {
        if (stableSince === null) stableSince = now;
        if (now - stableSince >= settleMs) {
          return cur;
        }
      } else {
        stableSince = null;
      }
      prev = cur;
    }
    return prev;
  }

  async clickPoint(x, y, { button = 'left', clickCount = 1 } = {}) {
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none' });
    await this.send('Input.dispatchMouseEvent', {
      type: 'mousePressed',
      x,
      y,
      button,
      clickCount,
      buttons: 1,
    });
    await this.send('Input.dispatchMouseEvent', {
      type: 'mouseReleased',
      x,
      y,
      button,
      clickCount,
      buttons: 0,
    });
  }

  async dblClickPoint(x, y) {
    await this.clickPoint(x, y, { clickCount: 1 });
    await sleep(30);
    await this.clickPoint(x, y, { clickCount: 2 });
  }

  async clickSelector(selector) {
    const pt = await this.evaluate(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null;
      try { el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' }); } catch {}
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return { hidden: true };
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    })()`);
    if (!pt) throw new AssertionError(`Element not found for click: ${selector}`);
    if (pt.hidden) throw new AssertionError(`Element has zero size / is hidden: ${selector}`);
    await this.clickPoint(pt.x, pt.y);
    return pt;
  }

  async typeText(selector, text) {
    await this.clickSelector(selector);
    await this.evaluate(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return;
      el.focus();
      el.value = '';
      el.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    if (text.length > 0) {
      await this.send('Input.insertText', { text });
      await this.evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return;
        if (el.value !== ${JSON.stringify(text)}) el.value = ${JSON.stringify(text)};
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      })()`);
    }
  }

  async pressKey(key, code, windowsVirtualKeyCode, modifiers = 0) {
    await this.send('Input.dispatchKeyEvent', {
      type: 'rawKeyDown',
      key,
      code,
      windowsVirtualKeyCode,
      nativeVirtualKeyCode: windowsVirtualKeyCode,
      modifiers,
    });
    if (key.length === 1) {
      await this.send('Input.dispatchKeyEvent', {
        type: 'char',
        text: key,
        unmodifiedText: key,
        key,
        code,
        windowsVirtualKeyCode,
        modifiers,
      });
    }
    await this.send('Input.dispatchKeyEvent', {
      type: 'keyUp',
      key,
      code,
      windowsVirtualKeyCode,
      nativeVirtualKeyCode: windowsVirtualKeyCode,
      modifiers,
    });
  }

  async wheelAt(x, y, deltaY) {
    await this.send('Input.dispatchMouseEvent', {
      type: 'mouseWheel',
      x,
      y,
      deltaX: 0,
      deltaY,
    });
  }

  async resize(width, height, dpr = 2, mobile = false) {
    await this.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: dpr,
      mobile,
    });
    await sleep(160);
  }

  /**
   * Fast downsampled RGBA canvas probe (~5-15ms) for luminance & pixel diff verification.
   */
  async captureCanvasSample(selector = '#diorama-canvas', gridW = 64, gridH = 36) {
    return this.evaluate(`(() => {
      const src = document.querySelector(${JSON.stringify(selector)});
      if (!src || src.width < 2 || src.height < 2) return null;
      const tmp = document.createElement('canvas');
      tmp.width = ${gridW};
      tmp.height = ${gridH};
      const ctx = tmp.getContext('2d');
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(src, 0, 0, ${gridW}, ${gridH});
      const data = ctx.getImageData(0, 0, ${gridW}, ${gridH}).data;
      const pixels = [];
      let sumR = 0, sumG = 0, sumB = 0, sumL = 0;
      const n = ${gridW * gridH};
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i], g = data[i + 1], b = data[i + 2];
        pixels.push(r, g, b);
        sumR += r; sumG += g; sumB += b;
        sumL += 0.2126 * r + 0.7152 * g + 0.0722 * b;
      }
      return {
        width: src.width,
        height: src.height,
        gridW: ${gridW},
        gridH: ${gridH},
        meanR: sumR / n,
        meanG: sumG / n,
        meanB: sumB / n,
        meanLuma: sumL / n,
        pixels,
      };
    })()`);
  }

  /**
   * Native-pixel ROI capture around (cxFrac, cyFrac) of canvas (no downsampling).
   * Used for opaque-box vehicle roof opacity & perforation checks at 2x zoom.
   */
  async captureCanvasRegion(selector = '#diorama-canvas', { cxFrac = 0.5, cyFrac = 0.5, boxW = 120, boxH = 80 } = {}) {
    return this.evaluate(`(() => {
      const src = document.querySelector(${JSON.stringify(selector)});
      if (!src || src.width < 16 || src.height < 16) return null;
      const w = Math.min(${boxW}, src.width);
      const h = Math.min(${boxH}, src.height);
      const x0 = Math.max(0, Math.min(src.width - w, Math.round(src.width * ${cxFrac} - w / 2)));
      const y0 = Math.max(0, Math.min(src.height - h, Math.round(src.height * ${cyFrac} - h / 2)));
      const ctx = src.getContext('2d');
      const data = ctx.getImageData(x0, y0, w, h).data;
      const pixels = new Array(w * h * 3);
      for (let i = 0, j = 0; i < data.length; i += 4, j += 3) {
        pixels[j] = data[i];
        pixels[j + 1] = data[i + 1];
        pixels[j + 2] = data[i + 2];
      }
      return { width: w, height: h, pixels };
    })()`);
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    this.cdp.clearSessionListeners(this.sessionId);
    try {
      await this.cdp.send('Target.closeTarget', { targetId: this.targetId }, undefined, 4000);
    } catch {}
    try {
      await this.cdp.send('Target.disposeBrowserContext', { browserContextId: this.browserContextId }, undefined, 4000);
    } catch {}
  }
}

export function diffCanvasSamples(s1, s2) {
  if (!s1 || !s2 || !s1.pixels || !s2.pixels || s1.pixels.length !== s2.pixels.length) {
    return { meanAbsDiff: 0, changedFrac: 0, maxDiff: 0 };
  }
  const p1 = s1.pixels;
  const p2 = s2.pixels;
  const nPix = p1.length / 3;
  let sumAbs = 0;
  let changed = 0;
  let maxDiff = 0;
  for (let i = 0; i < p1.length; i += 3) {
    const dr = Math.abs(p1[i] - p2[i]);
    const dg = Math.abs(p1[i + 1] - p2[i + 1]);
    const db = Math.abs(p1[i + 2] - p2[i + 2]);
    const m = Math.max(dr, dg, db);
    sumAbs += (dr + dg + db) / 3;
    if (m > 4) changed++;
    if (m > maxDiff) maxDiff = m;
  }
  return {
    meanAbsDiff: sumAbs / nPix,
    changedFrac: changed / nPix,
    maxDiff,
  };
}

/**
 * Opaque-box vehicle roof opacity & interior perforation analyzer.
 * Compares native-pixel ROIs captured with Live: On vs Live: Off at the exact
 * same camera pose. Narrow 2-4px wire/catenary cutouts punching background
 * grass through a train or bus roof show up as narrow gaps bridged on opposite
 * sides (<=4px left+right OR <=4px up+down) by rendered vehicle pixels, while
 * clean solid roofs and >=9px solid foreground building occluders yield 0%.
 */
export function analyzeVehicleRoofOpacity(roiOn, roiOff, diffThresh = 14) {
  if (
    !roiOn ||
    !roiOff ||
    !roiOn.pixels ||
    !roiOff.pixels ||
    roiOn.width !== roiOff.width ||
    roiOn.height !== roiOff.height ||
    roiOn.pixels.length !== roiOff.pixels.length
  ) {
    return { vehPixels: 0, interiorHoles: 0, holeFrac: 1.0 };
  }
  const w = roiOn.width;
  const h = roiOn.height;
  const pOn = roiOn.pixels;
  const pOff = roiOff.pixels;
  const isVeh = new Uint8Array(w * h);
  let vehPixels = 0;

  for (let idx = 0, j = 0; idx < w * h; idx++, j += 3) {
    const dr = Math.abs(pOn[j] - pOff[j]);
    const dg = Math.abs(pOn[j + 1] - pOff[j + 1]);
    const db = Math.abs(pOn[j + 2] - pOff[j + 2]);
    if (Math.max(dr, dg, db) > diffThresh) {
      isVeh[idx] = 1;
      vehPixels++;
    }
  }

  let interiorHoles = 0;
  for (let y = 1; y < h - 1; y++) {
    const rowOff = y * w;
    for (let x = 1; x < w - 1; x++) {
      if (isVeh[rowOff + x]) continue;
      let hasLeft = false;
      for (let dx = 1; dx <= 4 && x - dx >= 0; dx++) {
        if (isVeh[rowOff + x - dx]) {
          hasLeft = true;
          break;
        }
      }
      let hasRight = false;
      if (hasLeft) {
        for (let dx = 1; dx <= 4 && x + dx < w; dx++) {
          if (isVeh[rowOff + x + dx]) {
            hasRight = true;
            break;
          }
        }
      }
      if (hasLeft && hasRight) {
        interiorHoles++;
        continue;
      }
      let hasUp = false;
      for (let dy = 1; dy <= 4 && y - dy >= 0; dy++) {
        if (isVeh[(y - dy) * w + x]) {
          hasUp = true;
          break;
        }
      }
      if (!hasUp) continue;
      let hasDown = false;
      for (let dy = 1; dy <= 4 && y + dy < h; dy++) {
        if (isVeh[(y + dy) * w + x]) {
          hasDown = true;
          break;
        }
      }
      if (hasDown) interiorHoles++;
    }
  }

  return {
    vehPixels,
    interiorHoles,
    holeFrac: interiorHoles / Math.max(1, vehPixels + interiorHoles),
  };
}

export const SEARCH_RESULT_SELECTOR = [
  '[class*="search-result" i] button',
  '[class*="search-result" i] li',
  '[id*="search-result" i] button',
  '[id*="search-result" i] li',
  '[class*="search-item" i]',
  '[class*="search-list" i] button',
  '[class*="search-dropdown" i] button',
  '[id*="search" i] li',
  '[role="option"]',
].join(', ');

export function readGainValue(gains, key) {
  if (!gains || typeof gains !== 'object') return NaN;
  const v = gains[key];
  if (typeof v === 'number') return v;
  if (v && typeof v === 'object' && typeof v.gain === 'number') return v.gain;
  return NaN;
}

export function parseZoomReadout(text) {
  const s = String(text || '').trim();
  if (!s) return null;
  if (/1\s*:\s*1/.test(s)) return 1.0;
  const mPct = s.match(/([0-9]+(?:\.[0-9]+)?)\s*%/);
  if (mPct) return parseFloat(mPct[1]) / 100.0;
  const mMul = s.match(/([0-9]+(?:\.[0-9]+)?)\s*[x×]/i);
  if (mMul) return parseFloat(mMul[1]);
  return null;
}

export const SOUND_ACTIVE_EXPR = `(() => {
  const btn = document.getElementById('btn-toggle-sound');
  const txt = (btn?.textContent || '').trim();
  if (/loading/i.test(txt)) return false;
  const dbg = typeof window.__dioramaDebug === 'function' ? window.__dioramaDebug() : window.__dioramaDebug;
  if (dbg && typeof dbg.audioEnabled === 'boolean') {
    return dbg.audioEnabled === true && dbg.audioState === 'running';
  }
  return Boolean(
    btn?.classList.contains('active') ||
    btn?.getAttribute('aria-pressed') === 'true' ||
    /sound:\\s*on|\\bon\\b/i.test(txt)
  );
})()`;

export const SOUND_INACTIVE_EXPR = `(() => {
  const btn = document.getElementById('btn-toggle-sound');
  const txt = (btn?.textContent || '').trim();
  const dbg = typeof window.__dioramaDebug === 'function' ? window.__dioramaDebug() : window.__dioramaDebug;
  if (dbg && typeof dbg.audioEnabled === 'boolean') return dbg.audioEnabled === false;
  return Boolean(
    /sound:\\s*off|\\boff\\b|muted/i.test(txt) ||
    btn?.getAttribute('aria-pressed') === 'false' ||
    (btn && !btn.classList.contains('active') && !/\\bon\\b/i.test(txt))
  );
})()`;

export const ANIM_PAUSED_EXPR = `(() => {
  const btn = document.getElementById('btn-toggle-anim');
  const txt = (btn?.textContent || '').trim();
  return Boolean(
    /\\boff\\b|pause/i.test(txt) ||
    btn?.getAttribute('aria-pressed') === 'false' ||
    (btn && !btn.classList.contains('active') && !/\\bon\\b/i.test(txt))
  );
})()`;

export async function waitForSoundActive(tab, timeoutMs = 6000, { minMp3Count = 0 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const active = Boolean(await tab.evaluate(SOUND_ACTIVE_EXPR));
    if (active) {
      if (minMp3Count <= 0) return true;
      const uniq = new Set(tab.audioResponses.map((r) => new URL(r.url).pathname)).size;
      if (uniq >= minMp3Count) return true;
    }
    await sleep(90);
  }
  return Boolean(await tab.evaluate(SOUND_ACTIVE_EXPR));
}

export async function findMixerButtonPoint(tab) {
  return tab.evaluate(`(() => {
    const sels = [
      'button[id*="mixer" i]',
      'button[aria-label*="mixer" i]',
      'button[title*="mixer" i]',
      'button[class*="mixer" i]',
      'button[aria-label*="audio" i]:not(#btn-toggle-sound)',
      'button[title*="audio" i]:not(#btn-toggle-sound)',
      'button[aria-label*="sound" i]:not(#btn-toggle-sound)',
      'button[title*="sound" i]:not(#btn-toggle-sound)',
    ];
    for (const s of sels) {
      for (const el of document.querySelectorAll(s)) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden') {
          return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }
      }
    }
    return null;
  })()`);
}

/**
 * Shared headless Chromium + static HTTP server manager.
 */
export class BrowserHarness {
  constructor() {
    this.httpServer = null;
    this.baseUrl = '';
    this.userDataDir = '';
    this.proc = null;
    this.cdp = null;
    this.tabs = new Set();
    this.closed = false;
    this._closePromise = null;
    this._terminating = false;
    this._sigHandler = null;
  }

  async start() {
    this.httpServer = await startStaticServer(DOCS_DIR);
    this.baseUrl = this.httpServer.baseUrl;
    this.userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kilchberg_e2e_chrome_'));

    // Register fast signal teardown BEFORE spawning Chromium so early timeouts never leak temp dirs
    this._sigHandler = (sig) => {
      const sigNum = sig === 'SIGINT' ? 2 : 15;
      this.forceClose().finally(() => {
        process.exit(128 + sigNum);
      });
    };
    process.once('SIGINT', this._sigHandler);
    process.once('SIGTERM', this._sigHandler);

    const args = [
      '--headless=new',
      '--no-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--disable-extensions',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-background-networking',
      '--disable-sync',
      '--remote-debugging-port=0',
      `--user-data-dir=${this.userDataDir}`,
      'about:blank',
    ];

    // Keep Chromium inside Node's process group (NO detached: true) so run_e2e.py's
    // os.killpg(pgid, SIGTERM/SIGKILL) terminates Node and Chromium atomically on timeout.
    this.proc = spawn('/usr/bin/chromium', args, {
      stdio: ['ignore', 'ignore', 'pipe'],
    });

    let stderrWsUrl = null;
    let stderrBuf = '';
    this.proc.stderr.on('data', (chunk) => {
      const s = chunk.toString('utf8');
      stderrBuf += s;
      if (!stderrWsUrl) {
        const m = stderrBuf.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (m) stderrWsUrl = m[1];
      }
    });

    const wsUrl = await this._discoverWsEndpoint(() => stderrWsUrl, 15000);
    this.cdp = new CDPClient(wsUrl);
    await this.cdp.connect(10000);
  }

  async _discoverWsEndpoint(getStderrUrl, timeoutMs) {
    const portFile = path.join(this.userDataDir, 'DevToolsActivePort');
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (this.proc.exitCode !== null) {
        throw new Error(`Chromium exited prematurely with code ${this.proc.exitCode}`);
      }
      try {
        if (fs.existsSync(portFile)) {
          const content = fs.readFileSync(portFile, 'utf8').trim();
          const lines = content.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
          if (lines.length >= 2 && /^\d+$/.test(lines[0]) && lines[1].startsWith('/')) {
            return `ws://127.0.0.1:${lines[0]}${lines[1]}`;
          }
        }
      } catch {}
      const fallback = getStderrUrl();
      if (fallback) return fallback;
      await sleep(25);
    }
    throw new Error(`Timed out waiting for Chromium DevToolsActivePort (${timeoutMs}ms)`);
  }

  async openTab(relUrl = '/', opts = {}) {
    const {
      width = 1280,
      height = 800,
      dpr = 2,
      mobile = false,
      blockFonts = true,
      waitReady = true,
      readyTimeoutMs = 15000,
      loadTimeoutMs = 20000,
    } = opts;

    let browserContextId = null;
    let targetId = null;
    let tab = null;

    try {
      ({ browserContextId } = await this.cdp.send('Target.createBrowserContext', {
        disposeOnDetach: true,
      }));
      ({ targetId } = await this.cdp.send('Target.createTarget', {
        url: 'about:blank',
        browserContextId,
      }));
      const { sessionId } = await this.cdp.send('Target.attachToTarget', {
        targetId,
        flatten: true,
      });

      tab = new CDPTab(this, { browserContextId, targetId, sessionId });
      this.tabs.add(tab);
      tab._installTelemetry();

      await tab.send('Page.enable');
      await tab.send('Runtime.enable');
      await tab.send('Network.enable');
      await tab.send('Emulation.setDeviceMetricsOverride', {
        width,
        height,
        deviceScaleFactor: dpr,
        mobile,
      });
      if (blockFonts) {
        await tab.send('Network.setBlockedURLs', {
          urls: ['*fonts.googleapis.com*', '*fonts.gstatic.com*'],
        });
      }

      await tab.navigate(relUrl, { waitReady, readyTimeoutMs, loadTimeoutMs });
      return tab;
    } catch (err) {
      if (tab) {
        this.tabs.delete(tab);
        try { await tab.close(); } catch {}
      } else {
        if (targetId && this.cdp) {
          try { await this.cdp.send('Target.closeTarget', { targetId }, undefined, 2000); } catch {}
        }
        if (browserContextId && this.cdp) {
          try { await this.cdp.send('Target.disposeBrowserContext', { browserContextId }, undefined, 2000); } catch {}
        }
      }
      throw err;
    }
  }

  async closeTab(tab) {
    if (!tab) return;
    this.tabs.delete(tab);
    await tab.close();
  }

  _removeUserDataDirSync() {
    if (!this.userDataDir) return;
    const dir = this.userDataDir;
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {}
    if (!fs.existsSync(dir)) {
      this.userDataDir = '';
    }
  }

  /**
   * Fast signal teardown path invoked on SIGTERM/SIGINT:
   * immediately SIGKILL Chromium, close WS & HTTP server, wait briefly for exit,
   * and synchronously remove userDataDir well inside run_e2e.py's 2s grace window.
   */
  forceClose() {
    this._terminating = true;
    this.closed = true;
    if (this._sigHandler) {
      process.off('SIGINT', this._sigHandler);
      process.off('SIGTERM', this._sigHandler);
      this._sigHandler = null;
    }

    const doForce = async () => {
      this.tabs.clear();
      if (this.cdp) {
        try { this.cdp.close(); } catch {}
        this.cdp = null;
      }
      if (this.httpServer) {
        try { this.httpServer.destroySync(); } catch {}
        this.httpServer = null;
      }
      const proc = this.proc;
      this.proc = null;
      if (proc && proc.exitCode === null) {
        try { proc.kill('SIGKILL'); } catch {}
        await new Promise((resolve) => {
          if (proc.exitCode !== null) return resolve();
          const t = setTimeout(resolve, 250);
          proc.once('exit', () => {
            clearTimeout(t);
            resolve();
          });
        });
      }
      this._removeUserDataDirSync();
      if (this.userDataDir) {
        await sleep(30);
        this._removeUserDataDirSync();
      }
    };

    this._closePromise = doForce();
    return this._closePromise;
  }

  close() {
    if (this._closePromise) return this._closePromise;
    this.closed = true;
    this._closePromise = this._doClose();
    return this._closePromise;
  }

  async _doClose() {
    if (this._sigHandler) {
      process.off('SIGINT', this._sigHandler);
      process.off('SIGTERM', this._sigHandler);
      this._sigHandler = null;
    }

    for (const tab of [...this.tabs]) {
      try { await tab.close(); } catch {}
    }
    this.tabs.clear();

    if (this.cdp) {
      try { await this.cdp.send('Browser.close', {}, undefined, 2000); } catch {}
      this.cdp.close();
      this.cdp = null;
    }

    if (this.proc) {
      const proc = this.proc;
      const waitExit = (ms) =>
        new Promise((resolve) => {
          if (proc.exitCode !== null) return resolve(true);
          const timer = setTimeout(() => resolve(false), ms);
          proc.once('exit', () => {
            clearTimeout(timer);
            resolve(true);
          });
        });

      const exitedGracefully = await waitExit(1200);
      if (!exitedGracefully && proc.exitCode === null) {
        try { proc.kill('SIGTERM'); } catch {}
        const exitedTerm = await waitExit(1000);
        if (!exitedTerm && proc.exitCode === null) {
          try { proc.kill('SIGKILL'); } catch {}
          await waitExit(500);
        }
      }
      this.proc = null;
    }

    this._removeUserDataDirSync();

    if (this.httpServer) {
      try { await this.httpServer.close(); } catch {}
      this.httpServer = null;
    }
  }
}

/**
 * Parse --result-json and --verbose CLI flags for Node E2E suites.
 */
export function parseSuiteCli(argv = process.argv.slice(2)) {
  let resultJson = null;
  let verbose = false;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--result-json' && i + 1 < argv.length) {
      resultJson = argv[++i];
    } else if (argv[i] === '--verbose' || argv[i] === '-v') {
      verbose = true;
    }
  }
  return { resultJson, verbose };
}

/**
 * Execute a list of async test cases against a shared BrowserHarness and emit structured JSON.
 */
export async function runNodeSuite({ tier, suiteName, runTests }) {
  const { resultJson, verbose } = parseSuiteCli();
  const harness = new BrowserHarness();
  const results = [];
  const tSuite0 = performance.now();

  async function test(id, name, fn) {
    const t0 = performance.now();
    try {
      await fn();
      const dur = Math.round((performance.now() - t0) * 10) / 10;
      results.push({ id, name, status: 'PASS', duration_ms: dur, message: '' });
      if (verbose) console.log(`  [PASS] ${id.padEnd(10)} ${name} (${Math.round(dur)} ms)`);
    } catch (err) {
      const dur = Math.round((performance.now() - t0) * 10) / 10;
      const isAssert = err instanceof AssertionError || err?.name === 'AssertionError';
      const status = isAssert ? 'FAIL' : 'ERROR';
      const msg = String(err?.message || err || 'Unknown error').split('\n')[0];
      results.push({ id, name, status, duration_ms: dur, message: msg });
      if (verbose) console.log(`  [${status.padEnd(4)}] ${id.padEnd(10)} ${name} (${Math.round(dur)} ms) — ${msg}`);
    }
  }

  let runnerError = '';
  try {
    await harness.start();
    await runTests(harness, test);
  } catch (err) {
    runnerError = String(err?.message || err || 'Harness startup failure').split('\n')[0];
    results.push({
      id: `T${tier}.HARNESS`,
      name: 'browser_harness_error',
      status: 'ERROR',
      duration_ms: 0,
      message: runnerError,
    });
  } finally {
    await harness.close();
  }

  // If terminated by SIGTERM/SIGINT, let _sigHandler finish exiting with 128 + sig
  if (harness._terminating) return;

  const elapsedMs = Math.round((performance.now() - tSuite0) * 10) / 10;
  const payload = {
    tier,
    suite: suiteName,
    elapsed_ms: elapsedMs,
    runner_error: runnerError,
    tests: results,
  };

  if (resultJson) {
    fs.mkdirSync(path.dirname(resultJson), { recursive: true });
    fs.writeFileSync(resultJson, JSON.stringify(payload, null, 2), 'utf8');
  } else {
    for (const r of results) {
      const suffix = r.message && r.status !== 'PASS' ? ` -> ${r.message}` : '';
      console.log(`[${r.status.padEnd(4)}] ${r.id.padEnd(10)} ${r.name} (${Math.round(r.duration_ms)} ms)${suffix}`);
    }
  }

  const failed = results.filter((r) => r.status !== 'PASS').length;
  process.exit(failed === 0 && results.length > 0 && !runnerError ? 0 : 1);
}
