import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const base = "D:/MyProject/football-betting-oneshot";
const runtimePath = `${base}/05_RUNTIME_STATE.json`;
const queuePath = `${base}/data/postmatch_automation/queue.json`;
const outputRoot = `${base}/data/postmatch_dashboard`;

function esc(value) {
  return String(value ?? "—").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function text(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return String(value);
}

function tableRows(sheet, headerRow = 3, maxRows = 203, maxCols = 23) {
  const headers = sheet.getRangeByIndexes(headerRow - 1, 0, 1, maxCols).values[0].map((value, index) => text(value) === "—" ? `col_${index + 1}` : text(value));
  const values = sheet.getRangeByIndexes(headerRow, 0, maxRows - headerRow, maxCols).values;
  return values.filter((row) => text(row[0]) !== "—").map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index]])));
}

function findKey(row, includes) {
  return Object.keys(row).find((key) => includes.every((part) => key.includes(part)));
}

function value(row, includes) {
  const key = findKey(row, includes);
  return key ? row[key] : null;
}

function badgeClass(raw) {
  const value = text(raw);
  if (/(不可计入|不可核验)/.test(value)) return "neutral";
  if (/^(半红|半黑|走水)/.test(value) || /(观察|局部)/.test(value)) return "warn";
  if (/^否/.test(value) || /(黑|错误|未中)/.test(value)) return "bad";
  if (/^是/.test(value) || /(红|命中|正确|已启用)/.test(value)) return "good";
  return "neutral";
}

function table(rows, columns) {
  const head = columns.map((column) => `<th>${esc(column.label)}</th>`).join("");
  const body = rows.map((row) => {
    const search = Object.values(row).map(text).join(" ").toLowerCase();
    return `<tr data-search="${esc(search)}">${columns.map((column) => `<td>${esc(text(column.get(row)))}</td>`).join("")}</tr>`;
  }).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${columns.length}" class="empty">暂无记录</td></tr>`}</tbody></table></div>`;
}

function signalCards(rows) {
  return rows.slice().reverse().map((row) => {
    const id = value(row, ["MatchID"]) || row.MatchID;
    const pair = value(row, ["赛事", "对阵"]) || value(row, ["对阵"]);
    const preScore = value(row, ["赛前", "比分"]);
    const actualScore = value(row, ["实际", "90"]);
    const primaryHit = value(row, ["主维度", "命中"]);
    const scoreHit = value(row, ["比分", "命中"]);
    const primary = value(row, ["赛前", "主维度"]);
    const classification = value(row, ["红黑"]);
    const summary = value(row, ["复盘", "摘要"]);
    const search = Object.values(row).map(text).join(" ").toLowerCase();
    return `<article class="match-card" data-search="${esc(search)}"><div class="card-head"><span>${esc(text(id))}</span><h3>${esc(text(pair))}</h3><b class="${badgeClass(primaryHit)}">主维度严格结算 ${esc(text(primaryHit))}</b></div><div class="score-strip"><span>赛前唯一比分 <strong>${esc(text(preScore))}</strong></span><span>90分钟 <strong>${esc(text(actualScore))}</strong></span><b class="${badgeClass(scoreHit)}">唯一比分精确命中 ${esc(text(scoreHit))}</b></div><p><label>赛前唯一主维度</label>${esc(text(primary))}</p><p class="summary">${esc(text(summary))}</p><div class="card-foot"><b class="${badgeClass(classification)}">${esc(text(classification))}</b></div></article>`;
  }).join("");
}

function buildHtml({ workbookRel, generatedAt, runtime, queue, locks, signals, timeline, roots }) {
  const settled = locks.filter((row) => /(红|黑|走水|半红|半黑)/.test(text(value(row, ["注单", "状态"]))));
  const targetRows = signals.filter((row) => /杰尔|新圣徒|法国/.test(Object.values(row).map(text).join(" ")));
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>赛后复盘工作台</title><style>:root{--bg:#0b111a;--panel:#111b29;--panel2:#172338;--line:#2b3b52;--text:#eef5ff;--muted:#9cadc2;--good:#35d08f;--bad:#ff6474;--warn:#f3bc55;--blue:#69a7ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#121a29,#0b111a);color:var(--text);font:14px/1.55 "Microsoft YaHei",system-ui,sans-serif}.shell{max-width:1480px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;margin-bottom:20px}h1{margin:0;font-size:32px}.muted,label{color:var(--muted)}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:16px}.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}.kpi b{display:block;font-size:24px}.toolbar{position:sticky;top:0;display:flex;gap:8px;background:#0b111add;padding:10px 0;backdrop-filter:blur(10px)}button,input{border:1px solid var(--line);background:#121d2c;color:var(--text);border-radius:9px;padding:9px 12px}button.active{border-color:var(--blue);color:var(--blue)}input{flex:1}.view{display:none}.view.active{display:block}.match-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.match-card,.table-wrap{background:var(--panel);border:1px solid var(--line);border-radius:12px}.match-card{padding:16px}.card-head,.score-strip,.card-foot{display:flex;gap:10px;align-items:center;justify-content:space-between}.card-head h3{margin:0;flex:1;font-size:16px}.score-strip{background:#0c1420;border-radius:9px;padding:10px;margin:12px 0}.summary{color:#d8e2f2}b.good{color:var(--good)}b.bad{color:var(--bad)}b.warn{color:var(--warn)}b.neutral{color:var(--muted)}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:980px}th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:var(--panel2);color:#d8e6f9;position:sticky;top:0}.empty{text-align:center;color:var(--muted);padding:28px}footer{margin-top:18px;color:var(--muted);border-top:1px solid var(--line);padding-top:14px}@media(max-width:900px){.shell{padding:16px}header{display:block}.kpis{grid-template-columns:repeat(2,1fr)}.match-grid{grid-template-columns:1fr}.toolbar{flex-wrap:wrap}input{min-width:100%}}</style></head><body><main class="shell"><header><div><div class="muted">FOOTBALL BETTING ONESHOT · POSTMATCH</div><h1>赛后复盘工作台</h1><p class="muted">90分钟赛果口径；加时与点球单独记录；未锁单不制造盈亏。</p></div><div class="muted">生成：${esc(generatedAt)}<br>来源：${esc(workbookRel)}</div></header><section class="kpis"><div class="kpi"><span>复盘记录</span><b>${signals.length}</b></div><div class="kpi"><span>本次目标记录</span><b>${targetRows.length}</b></div><div class="kpi"><span>已结注单</span><b>${settled.length}</b></div><div class="kpi"><span>待核验队列</span><b>${(queue.pending || []).length}</b></div><div class="kpi"><span>余额</span><b>¥${Number(runtime.bankroll?.current_balance || 0).toFixed(2)}</b></div></section><nav class="toolbar"><button class="tab active" data-view="signals">比赛复盘</button><button class="tab" data-view="locks">注单结算</button><button class="tab" data-view="timeline">盘口时间轴</button><button class="tab" data-view="roots">根因修正</button><input id="search" placeholder="搜索球队、MatchID、比分、分类"></nav><section id="signals" class="view active"><div class="match-grid">${signalCards(signals)}</div></section><section id="locks" class="view">${table(locks, [{ label: "注单ID", get: (r) => value(r, ["注单ID"]) }, { label: "比赛", get: (r) => value(r, ["比赛"]) || value(r, ["对阵"]) }, { label: "玩法", get: (r) => value(r, ["玩法"]) }, { label: "方向", get: (r) => value(r, ["方向"]) }, { label: "赛果", get: (r) => value(r, ["赛果"]) }, { label: "状态", get: (r) => value(r, ["状态"]) }, { label: "回收", get: (r) => value(r, ["回收"]) }])}</section><section id="timeline" class="view">${table(timeline, [{ label: "记录ID", get: (r) => value(r, ["记录ID"]) }, { label: "比赛", get: (r) => value(r, ["比赛"]) || value(r, ["对阵"]) }, { label: "倒计时", get: (r) => value(r, ["倒计时"]) }, { label: "终盘变化", get: (r) => value(r, ["变化"]) }, { label: "最终验证", get: (r) => value(r, ["最终"]) }, { label: "完整度", get: (r) => value(r, ["完整"]) }])}</section><section id="roots" class="view">${table(roots, [{ label: "比赛场次", get: (r) => value(r, ["比赛"]) || value(r, ["场次"]) }, { label: "决策审计", get: (r) => value(r, ["决策"]) }, { label: "反事实", get: (r) => value(r, ["反事实"]) }, { label: "是否修改", get: (r) => value(r, ["修改"]) }, { label: "建议", get: (r) => value(r, ["建议"]) }, { label: "结论", get: (r) => value(r, ["结论"]) }, { label: "优先级", get: (r) => value(r, ["优先级"]) }])}</section><footer>本 HTML 由最新 Excel 工作簿只读生成，不修改锁单、余额或执行状态。</footer></main><script>const tabs=[...document.querySelectorAll('.tab')],views=[...document.querySelectorAll('.view')],search=document.querySelector('#search');tabs.forEach(b=>b.onclick=()=>{tabs.forEach(x=>x.classList.toggle('active',x===b));views.forEach(v=>v.classList.toggle('active',v.id===b.dataset.view));filter();});function filter(){const q=search.value.trim().toLowerCase();document.querySelectorAll('.view.active [data-search]').forEach(el=>{el.style.display=el.dataset.search.includes(q)?'':'none';});}search.addEventListener('input',filter);</script></body></html>`;
}

const runtime = JSON.parse(await fs.readFile(runtimePath, "utf8"));
const queue = JSON.parse(await fs.readFile(queuePath, "utf8").catch(() => "{}"));
const workbookRel = runtime.latest_review_workbook;
const workbookPath = path.isAbsolute(workbookRel) ? workbookRel : path.join(base, workbookRel);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const sheets = workbook.worksheets.items;
const locks = tableRows(sheets[1], 3, 203, 22);
const signals = tableRows(sheets[2], 3, 203, 22);
const timeline = tableRows(sheets[3], 3, 203, 13);
const roots = tableRows(sheets[5], 3, 203, 10);
const now = new Date();
const stamp = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(now).replaceAll("-", "").replace(" ", "_").replaceAll(":", "");
const snapshotDir = `${outputRoot}/${stamp}`;
await fs.mkdir(snapshotDir, { recursive: true });
const generatedAt = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium" }).format(now);
const content = buildHtml({ workbookRel, generatedAt, runtime, queue, locks, signals, timeline, roots });
await fs.writeFile(`${snapshotDir}/index.html`, content, "utf8");
await fs.copyFile(`${snapshotDir}/index.html`, `${outputRoot}/latest.html`);
await fs.writeFile(`${snapshotDir}/manifest.json`, JSON.stringify({ schema_version: "1.0", generated_at: generatedAt, source_workbook: workbookRel, snapshot: path.relative(base, `${snapshotDir}/index.html`).replaceAll("\\", "/"), latest: "data/postmatch_dashboard/latest.html" }, null, 2) + "\n", "utf8");
console.log(JSON.stringify({ snapshot: `${snapshotDir}/index.html`, latest: `${outputRoot}/latest.html`, source_workbook: workbookRel }));
