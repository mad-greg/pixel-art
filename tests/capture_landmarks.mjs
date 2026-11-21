/**
 * Visual review helper: screenshots landmarks at live zoom via the CDP harness.
 * ids may be 'uv:<u>:<v>' for free positions. usage: node tests/capture_landmarks.mjs <outDir> <zoom> <mode> [id1,id2,...] [width] [height]
 */
import fs from 'node:fs';
import path from 'node:path';
import { BrowserHarness, sleep } from './lib/cdp_harness.mjs';

const [outDir, zoom = '3', mode = 'day', ids = '', w = '960', h = '640'] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const all = JSON.parse(fs.readFileSync(new URL('../docs/data/kilchberg_interactive.json', import.meta.url))).landmarks.map((l) => l.id);
const list = ids ? ids.split(',') : all;
const hn = new BrowserHarness();
await hn.start();
try {
  for (const id of list) {
    const tab = await hn.openTab(id.startsWith('uv:') ? `/?u=${id.split(':')[1]}&v=${id.split(':')[2]}&zoom=${zoom}&mode=${mode}` : `/?landmark=${id}&zoom=${zoom}&mode=${mode}`, { width: +w, height: +h, dpr: 1 });
    await tab.waitForCameraSettled();
    await sleep(1800);
    const r = await tab.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(outDir, `${id.replace(/:/g, '_')}_${mode}_${zoom}x.png`), Buffer.from(r.data, 'base64'));
    await hn.closeTab(tab);
  }
} finally {
  await hn.close();
}
