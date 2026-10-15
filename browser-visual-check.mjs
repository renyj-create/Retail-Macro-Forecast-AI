// 临时：首页视觉/交互验收（深色 Hero、textarea、场景卡片、折叠 Demo）
import { writeFileSync, mkdirSync } from 'node:fs';
import { setTimeout as sleep } from 'node:timers/promises';

const PORT = 9222;
const OUT = 'screenshots';
mkdirSync(OUT, { recursive: true });
const consoleErrors = [];
const failedRequests = [];

async function waitTarget() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const page = list.find(t => t.type === 'page');
      if (page) return page;
    } catch {}
    await sleep(500);
  }
  throw new Error('CDP not ready');
}

const page = await waitTarget();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let mid = 0; const pending = new Map();
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') consoleErrors.push((msg.params.args || []).map(a => a.value ?? a.description ?? '').join(' '));
  if (msg.method === 'Runtime.exceptionThrown') consoleErrors.push('exception: ' + (msg.params.exceptionDetails?.text || ''));
  if (msg.method === 'Network.loadingFailed') failedRequests.push(msg.params.errorText);
};
function send(m, p = {}) { return new Promise(res => { const id = ++mid; pending.set(id, res); ws.send(JSON.stringify({ id, method: m, params: p })); }); }
async function evalJS(expr) { const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); return r.result?.result?.value; }
async function shot(name) { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.result.data, 'base64')); console.log('[shot]', name); }
async function resize(w, h) { await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false }); await sleep(700); }

await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
await send('Page.navigate', { url: 'http://localhost:5173/' });
await sleep(3500);
await resize(1440, 900);

const heroTitle = await evalJS(`document.querySelector('.hero-title')?.textContent.replace(/\\s+/g,' ').trim()`);
const heroDesc = await evalJS(`document.querySelector('.hero-desc')?.textContent.trim()`);
const inputTag = await evalJS(`document.querySelector('.hero-input')?.tagName`);
const placeholder = await evalJS(`document.querySelector('.hero-input')?.getAttribute('placeholder')`);
const cards = await evalJS(`[...document.querySelectorAll('.quick-card .quick-title')].map(b => b.textContent.trim())`);
const demoActive = await evalJS(`document.querySelector('.demo-collapse .el-collapse-item')?.classList.contains('is-active')`);
const heroBg = await evalJS(`getComputedStyle(document.querySelector('.hero')).backgroundImage.slice(0, 40)`);

console.log('[hero-title]', heroTitle);
console.log('[hero-desc]', heroDesc);
console.log('[input-tag]', inputTag, '| placeholder=', placeholder);
console.log('[cards]', JSON.stringify(cards));
console.log('[demo-collapsed]', demoActive === false ? '是（已折叠）' : '否（展开）');
console.log('[hero-bg]', heroBg);

await shot('04-home-hero-dark');

// 点击第一个场景卡片，验证输入框被填充且进入加载
await evalJS(`document.querySelectorAll('.quick-card')[0].click()`);
await sleep(1200);
const filled = await evalJS(`document.querySelector('.hero-input')?.value`);
const btnLoading = await evalJS(`document.querySelector('.hero-submit')?.classList.contains('is-loading')`);
console.log('[after-click] input-filled=', JSON.stringify(filled), '| btn-loading=', btnLoading);

await resize(420, 900);
await shot('05-home-hero-narrow');
await resize(1440, 900);

console.log('[console-errors]', JSON.stringify(consoleErrors));
console.log('[failed-requests]', JSON.stringify(failedRequests));
process.exit(0);
