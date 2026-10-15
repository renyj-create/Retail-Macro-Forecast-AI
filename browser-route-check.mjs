// 浏览器意图路由回归验收：点击四个快捷场景并核对工具执行明细。
import { setTimeout as sleep } from 'node:timers/promises';

const PORT = 9222;
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

await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');

const cards = [
  { id: 'sales-anomaly', label: '销售异常分析', expect: ['数据查询', '趋势预测'], forbid: ['流失预测'] },
  { id: 'sales-forecast', label: '趋势预测', expect: ['数据查询', '趋势预测'], forbid: ['流失预测'] },
  { id: 'customer-churn', label: '客户流失分析', expect: ['流失预测'], forbid: ['数据查询', '趋势预测'] },
  { id: 'business-report', label: '经营报告生成', expect: ['数据查询', '趋势预测', '流失预测'], forbid: [] },
];

let failures = 0;
for (let i = 0; i < cards.length; i++) {
  await send('Page.navigate', { url: 'http://localhost:5173/' });
  await sleep(3000);
  const selector = `[data-testid="quick-scenario-${cards[i].id}"]`;
  const found = await evalJS(`!!document.querySelector(${JSON.stringify(selector)})`);
  if (!found) { console.log(`[${cards[i].label}] selector=${selector} FAIL(not found)`); failures++; continue; }
  await evalJS(`document.querySelector(${JSON.stringify(selector)}).click()`);
  let appeared = false;
  for (let j = 0; j < 120; j++) {
    await sleep(1000);
    const state = await evalJS(`({ result: !!document.querySelector('[data-testid="home-analysis-result"]'), error: !!document.querySelector('[data-testid="home-analysis-error"]') })`);
    if (state?.result) { appeared = true; break; }
    if (state?.error) break;
  }
  const intent = await evalJS(`document.querySelector('.home-result-section .intent-chip')?.textContent.trim()`);
  const steps = await evalJS(`[...document.querySelectorAll('.process-step .process-title span')].map(s=>s.textContent.trim())`);
  const error = await evalJS(`document.querySelector('[data-testid="home-analysis-error"]')?.textContent.trim()`);
  console.log(`[${cards[i].label}] appeared=${appeared} intent=${intent} error=${error || ''}`);
  if (!appeared) failures++;
  console.log('   steps=', JSON.stringify(steps));
  for (const t of cards[i].expect) { const ok = (steps || []).includes(t); console.log(`   expect 含「${t}」:`, ok ? 'OK' : 'FAIL'); if (!ok) failures++; }
  for (const t of cards[i].forbid) { const ok = !(steps || []).includes(t); console.log(`   forbid 含「${t}」:`, ok ? 'OK' : 'FAIL(不应出现)'); if (!ok) failures++; }
}

console.log('[console-errors]', JSON.stringify(consoleErrors));
console.log('[failed-requests]', JSON.stringify(failedRequests));
if (consoleErrors.length || failedRequests.length) failures++;
console.log('[route-check]', failures ? `FAIL (${failures} failure(s))` : 'PASS');
ws.close();
process.exitCode = failures ? 1 : 0;
