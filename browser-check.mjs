// 临时浏览器验收脚本（面试验收用，非项目运行代码）——仅连接已启动的 Edge CDP
import { writeFileSync, mkdirSync } from 'node:fs';
import { setTimeout as sleep } from 'node:timers/promises';

const PORT = 9222;
const OUT = process.argv[2] || 'screenshots';
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

let mid = 0;
const pending = new Map();
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
    const text = (msg.params.args || []).map(a => (a.value ?? a.description ?? '')).join(' ');
    consoleErrors.push(text);
  }
  if (msg.method === 'Runtime.exceptionThrown') {
    consoleErrors.push('exception: ' + (msg.params.exceptionDetails?.text || msg.params.exceptionDetails?.exception?.description || ''));
  }
  if (msg.method === 'Network.loadingFailed') {
    failedRequests.push(msg.params.errorText + (msg.params.blockedReason ? ' (' + msg.params.blockedReason + ')' : ''));
  }
};

function send(method, params = {}) {
  return new Promise((resolve) => {
    const id = ++mid;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function evalJS(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return { val: r.result?.result?.value, err: r.result?.exceptionDetails?.text };
}

async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.result.data, 'base64'));
  console.log('[shot]', name);
}

async function resize(w, h) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await sleep(700);
}

await send('Page.enable');
await send('Runtime.enable');
await send('Network.enable');

await send('Page.navigate', { url: 'http://localhost:5173/' });
await sleep(4000);

await resize(1440, 900);
await shot('01-home-initial-desktop');

const nav = await evalJS(`[...document.querySelectorAll('.nav-link')].map(b => b.textContent.trim())`);
console.log('[nav]', JSON.stringify(nav.val));

const cards = await evalJS(`[...document.querySelectorAll('.quick-card .quick-title')].map(b => b.textContent.trim())`);
console.log('[cards]', JSON.stringify(cards.val));

const heroTitle = await evalJS(`document.querySelector('.hero-title')?.textContent.replace(/\\s+/g,' ').trim()`);
console.log('[hero-title]', heroTitle.val);

// 点击第一个快捷场景，触发真实分析
await evalJS(`document.querySelector('.quick-card').click()`);

let appeared = false;
for (let i = 0; i < 120; i++) {
  await sleep(1000);
  const r = await evalJS(`!!document.querySelector('.home-result-section')`);
  if (r.val === true) { appeared = true; break; }
}
console.log('[result-appeared]', appeared);

if (appeared) {
  await sleep(1500);
  await shot('02-home-result');
  const status = await evalJS(`document.querySelector('.home-result-section .result-status-row')?.textContent.replace(/\\s+/g,' ').trim()`);
  console.log('[result-status]', status.val);
  const steps = await evalJS(`[...document.querySelectorAll('.process-step')].map(li => ({ n: li.querySelector('.process-index')?.textContent.trim(), title: li.querySelector('.process-title span')?.textContent.trim(), st: li.querySelector('.process-title .el-tag')?.textContent.trim(), summary: li.querySelector('.process-summary')?.textContent.trim(), dur: li.querySelector('.process-duration')?.textContent.trim() }))`);
  console.log('[process-steps]', JSON.stringify(steps.val, null, 2));
  const core = await evalJS(`document.querySelector('.core-conclusion')?.textContent.trim().slice(0, 140)`);
  console.log('[core]', core.val);
} else {
  // 分析未出现，读取错误提示
  const err = await evalJS(`document.querySelector('.hero-error')?.textContent.trim()`);
  console.log('[hero-error]', err.val);
}

await resize(420, 900);
await shot('03-home-narrow');
await resize(1440, 900);

for (const [key, label] of [['data', '数据分析'], ['agent', 'AI Agent'], ['report', '智能报告'], ['kb', '知识库']]) {
  await evalJS(`[...document.querySelectorAll('.nav-link')].find(b => b.textContent.trim() === '${label}')?.click()`);
  await sleep(1600);
  const title = await evalJS(`document.querySelector('.page-title')?.textContent.trim()`);
  console.log(`[view:${key}]`, title.val);
}

console.log('[console-errors]', JSON.stringify(consoleErrors));
console.log('[failed-requests]', JSON.stringify(failedRequests));

process.exit(0);
