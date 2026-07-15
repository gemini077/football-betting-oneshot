#!/usr/bin/env python3
"""Convert the latest post-match Excel workbook into a self-contained HTML dashboard."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


BASE_DIR = Path(__file__).resolve().parents[1]
RUNTIME_PATH = BASE_DIR / "05_RUNTIME_STATE.json"
QUEUE_PATH = BASE_DIR / "data" / "postmatch_automation" / "queue.json"
OUTPUT_ROOT = BASE_DIR / "data" / "postmatch_dashboard"
SHANGHAI = timezone(timedelta(hours=8))


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def latest_workbook(runtime: dict[str, Any], explicit: Path | None) -> Path:
    if explicit:
        return explicit if explicit.is_absolute() else BASE_DIR / explicit
    configured = runtime.get("latest_review_workbook")
    if configured:
        candidate = BASE_DIR / configured
        if candidate.exists():
            return candidate
    candidates = sorted((BASE_DIR / "data" / "postmatch_reviews").glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("No post-match workbook found")
    return candidates[0]


def table_rows(ws, header_row: int, max_rows: int = 200) -> list[dict[str, Any]]:
    headers = [ws.cell(header_row, col).value for col in range(1, ws.max_column + 1)]
    rows: list[dict[str, Any]] = []
    for row_index in range(header_row + 1, min(ws.max_row, header_row + max_rows) + 1):
        first = ws.cell(row_index, 1).value
        if first in (None, ""):
            continue
        row: dict[str, Any] = {}
        for col, header_value in enumerate(headers, 1):
            key = str(header_value) if header_value not in (None, "") else f"col_{col}"
            value = ws.cell(row_index, col).value
            if isinstance(value, datetime):
                value = value.isoformat()
            row[key] = value
        rows.append(row)
    return rows


def text(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def esc(value: Any) -> str:
    return html.escape(text(value))


def money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def calculate_kpis(locks: list[dict[str, Any]], signals: list[dict[str, Any]], runtime: dict[str, Any]) -> dict[str, Any]:
    settled = [row for row in locks if text(row.get("注单状态")) in {"红", "黑", "走水", "半红", "半黑"}]
    stake = sum(money(row.get("下注金额")) for row in settled)
    returned = sum(money(row.get("实际回收金额")) for row in settled)
    hits = sum(1 if row.get("注单状态") == "红" else 0.5 if row.get("注单状态") == "半红" else 0 for row in settled)
    bankroll = runtime.get("bankroll", {})
    return {
        "reviews": len(signals),
        "locked": len(settled),
        "hit_rate": (hits / len(settled) * 100) if settled else None,
        "stake": stake,
        "returned": returned,
        "profit": returned - stake,
        "roi": ((returned - stake) / stake * 100) if stake else None,
        "balance": money(bankroll.get("current_balance")),
    }


def badge_class(value: Any) -> str:
    value = text(value)
    if "不可计入" in value or "不可核验" in value:
        return "neutral"
    if value.startswith(("半红", "半黑", "走水")) or value in {"观察", "局部正确"}:
        return "warn"
    if value.startswith("否") or value in {"黑", "逻辑错误"} or "未中" in value:
        return "bad"
    if value.startswith("是") or value in {"红", "逻辑正确", "已启用"} or "命中" in value:
        return "good"
    return "neutral"


def signal_cards(signals: list[dict[str, Any]]) -> str:
    cards = []
    for row in reversed(signals):
        search = " ".join(text(v) for v in row.values()).casefold()
        cards.append(
            f'''<article class="match-card" data-search="{html.escape(search, quote=True)}" data-hit="{esc(row.get('主维度是否命中'))}">
              <div class="card-head"><span class="match-id">{esc(row.get('MatchID'))}</span><h3>{esc(row.get('赛事与对阵'))}</h3><span class="badge {badge_class(row.get('主维度是否命中'))}">主维度严格结算 {esc(row.get('主维度是否命中'))}</span></div>
              <div class="score-strip"><span>赛前唯一比分 <b>{esc(row.get('赛前唯一首推比分'))}</b></span><span>实际90分钟 <b>{esc(row.get('实际90分钟比分'))}</b></span><span class="badge {badge_class(row.get('比分是否命中'))}">唯一比分精确命中 {esc(row.get('比分是否命中'))}</span></div>
              <div class="detail-grid">
                <div><label>赛前主维度</label><p>{esc(row.get('赛前首推主维度'))}</p></div>
                <div><label>亚盘方向</label><p>{esc(row.get('赛前亚盘方向'))}</p></div>
                <div><label>大小球</label><p>{esc(row.get('赛前大小球方向'))}</p></div>
                <div><label>BTTS</label><p>{esc(row.get('赛前BTTS判断'))}</p></div>
              </div>
              <p class="summary">{esc(row.get('复盘摘要'))}</p>
              <div class="card-foot"><span class="badge {badge_class(row.get('红黑与模型逻辑分类'))}">{esc(row.get('红黑与模型逻辑分类'))}</span><span>最大错点：{esc(row.get('最大错点类型'))}</span></div>
            </article>'''
        )
    return "\n".join(cards)


def data_table(rows: list[dict[str, Any]], columns: list[str], table_id: str) -> str:
    headers = "".join(f"<th>{esc(column)}</th>" for column in columns)
    body = []
    for row in rows:
        search = " ".join(text(row.get(column)) for column in columns).casefold()
        cells = "".join(f"<td>{esc(row.get(column))}</td>" for column in columns)
        body.append(f'<tr data-search="{html.escape(search, quote=True)}">{cells}</tr>')
    return f'<div class="table-wrap"><table id="{table_id}"><thead><tr>{headers}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def render_html(workbook_path: Path, runtime: dict[str, Any], queue: dict[str, Any], generated_at: datetime) -> str:
    wb = load_workbook(workbook_path, data_only=True, read_only=False)
    locks = table_rows(wb["01_锁单与结算明细"], 3)
    signals = table_rows(wb["02_赛前信号与赛果归因"], 3)
    timeline = table_rows(wb["03_时间轴与盘口验证"], 3)
    roots = table_rows(wb["05_根因决策树与修正池"], 3)
    kpis = calculate_kpis(locks, signals, runtime)
    pending = len(queue.get("pending", []))
    waiting = queue.get("counts", {}).get("waiting_for_finish", 0)
    hit_rate = "—" if kpis["hit_rate"] is None else f'{kpis["hit_rate"]:.1f}%'
    roi = "—" if kpis["roi"] is None else f'{kpis["roi"]:.1f}%'
    lock_table = data_table(locks, ["注单ID", "比赛ID与对阵", "主维度玩法", "投注方向", "下注赔率", "下注金额", "赛果", "注单状态", "实际回收金额", "模型逻辑分类", "备注"], "locks-table")
    timeline_table = data_table(timeline, ["记录ID", "比赛ID与对阵", "开赛倒计时", "锁单窗口合规性", "初盘定位", "终盘定位（临场15min）", "终盘对比初盘变化", "最终赛果验证", "数据完整度"], "timeline-table")
    root_table = data_table(roots, ["比赛场次", "决策节点审计", "反事实推演", "赛前可识别性", "是否修改模型", "具体修改建议", "收敛结论", "最大错点类型", "生效状态", "优先级"], "root-table")
    source_name = esc(workbook_path.name)
    updated = generated_at.strftime("%Y-%m-%d %H:%M:%S")
    model_version = esc(runtime.get("model_version"))
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Football Betting OneShot｜赛后复盘工作台</title>
<style>
:root{{--bg:#090d18;--panel:#11182a;--panel2:#161f35;--line:#293653;--text:#edf2ff;--muted:#94a3be;--accent:#7c3aed;--accent2:#ec4899;--good:#21c77a;--bad:#fb5b68;--warn:#f4b942;--blue:#46a5ff}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 12% 0,#22153f 0,transparent 32%),radial-gradient(circle at 90% 10%,#182f52 0,transparent 28%),var(--bg);color:var(--text);font:14px/1.55 "Microsoft YaHei",system-ui,sans-serif}}
.shell{{max-width:1500px;margin:auto;padding:28px}} .hero{{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin-bottom:22px}} .eyebrow{{color:#c4b5fd;font-weight:700;letter-spacing:.12em}} h1{{font-size:34px;margin:6px 0}} .hero p{{margin:0;color:var(--muted)}} .sync{{min-width:280px;background:#0e1526;border:1px solid var(--line);border-radius:16px;padding:15px 18px}} .sync strong{{display:block;color:var(--good);font-size:16px}} .kpis{{display:grid;grid-template-columns:repeat(7,minmax(120px,1fr));gap:12px;margin-bottom:20px}} .kpi{{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:16px}} .kpi span{{color:var(--muted);font-size:12px}} .kpi b{{display:block;font-size:23px;margin-top:5px}} .toolbar{{position:sticky;top:0;z-index:9;background:rgba(9,13,24,.88);backdrop-filter:blur(12px);display:flex;gap:10px;padding:12px 0}} button,.filter,input{{border:1px solid var(--line);background:#11192b;color:var(--text);border-radius:10px;padding:10px 13px}} button{{cursor:pointer}} button.active{{background:linear-gradient(90deg,var(--accent),var(--accent2));border-color:transparent}} input{{flex:1;min-width:220px}} .view{{display:none}} .view.active{{display:block}} .match-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}} .match-card{{background:linear-gradient(150deg,#151e34,#0f1626);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 14px 40px rgba(0,0,0,.16)}} .card-head{{display:flex;align-items:center;gap:10px}} .card-head h3{{font-size:17px;margin:0;flex:1}} .match-id{{font-weight:800;color:#c4b5fd}} .score-strip{{display:flex;gap:18px;background:#0b1120;border-radius:12px;padding:12px;margin:14px 0}} .score-strip b{{font-size:17px}} .detail-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}} .detail-grid div{{border-left:2px solid #3b4b6c;padding-left:9px}} label{{color:var(--muted);font-size:11px}} p{{margin:3px 0}} .summary{{color:#c8d1e5;margin:15px 0}} .card-foot{{display:flex;justify-content:space-between;gap:10px;color:var(--muted)}} .badge{{display:inline-flex;align-items:center;padding:3px 9px;border-radius:999px;font-size:12px;white-space:nowrap}} .badge.good{{background:#123b2c;color:#62e4a6}} .badge.bad{{background:#451d27;color:#ff8c98}} .badge.warn{{background:#453717;color:#ffd36e}} .badge.neutral{{background:#25324a;color:#c1cbe0}} .table-wrap{{overflow:auto;background:#0f1626;border:1px solid var(--line);border-radius:16px}} table{{border-collapse:collapse;width:100%;min-width:1100px}} th{{position:sticky;top:0;background:#1b2540;color:#cbd5e9;text-align:left;padding:12px;border-bottom:1px solid var(--line);font-size:12px}} td{{padding:11px 12px;border-bottom:1px solid #222e48;vertical-align:top;max-width:320px}} tr:hover td{{background:#141e33}} .section-head{{display:flex;justify-content:space-between;align-items:center;margin:10px 0 14px}} .section-head h2{{margin:0}} .empty{{display:none;padding:35px;text-align:center;color:var(--muted)}} footer{{color:var(--muted);margin-top:22px;padding:15px 0;border-top:1px solid var(--line)}}
@media(max-width:1050px){{.kpis{{grid-template-columns:repeat(3,1fr)}}.match-grid{{grid-template-columns:1fr}}.detail-grid{{grid-template-columns:repeat(2,1fr)}}}} @media(max-width:650px){{.shell{{padding:16px}}.hero{{display:block}}.sync{{margin-top:14px}}.kpis{{grid-template-columns:repeat(2,1fr)}}.toolbar{{flex-wrap:wrap}}.score-strip{{flex-wrap:wrap}}}}
</style></head><body><main class="shell">
<header class="hero"><div><div class="eyebrow">FOOTBALL BETTING ONESHOT · {model_version}</div><h1>赛后复盘工作台</h1><p>90分钟赛果口径｜记录ID递增｜赛前冻结、赛后归因</p></div><div class="sync"><strong>● 自动复盘已接入</strong><span>待核验 {pending} 场 · 等待结束 {waiting} 场</span><br><small>页面生成：{updated}</small></div></header>
<section class="kpis"><div class="kpi"><span>有效复盘</span><b>{kpis['reviews']}</b></div><div class="kpi"><span>已结注单</span><b>{kpis['locked']}</b></div><div class="kpi"><span>注单命中率</span><b>{hit_rate}</b></div><div class="kpi"><span>累计投注</span><b>¥{kpis['stake']:.2f}</b></div><div class="kpi"><span>净盈亏</span><b>¥{kpis['profit']:.2f}</b></div><div class="kpi"><span>ROI</span><b>{roi}</b></div><div class="kpi"><span>当前余额</span><b>¥{kpis['balance']:.2f}</b></div></section>
<nav class="toolbar"><button class="tab active" data-view="signals">比赛复盘</button><button class="tab" data-view="locks">注单结算</button><button class="tab" data-view="timeline">盘口时间轴</button><button class="tab" data-view="roots">根因与修正</button><input id="search" placeholder="搜索球队、记录ID、玩法或错点…"><select id="hit-filter" class="filter"><option value="">全部命中状态</option><option>是</option><option>否</option></select></nav>
<section id="signals" class="view active"><div class="section-head"><h2>赛前信号与赛果归因</h2><span>{len(signals)} 场</span></div><div class="match-grid">{signal_cards(signals)}</div></section>
<section id="locks" class="view"><div class="section-head"><h2>锁单与结算明细</h2><span>{len(locks)} 单</span></div>{lock_table}</section>
<section id="timeline" class="view"><div class="section-head"><h2>时间轴与盘口有效性</h2><span>{len(timeline)} 条</span></div>{timeline_table}</section>
<section id="roots" class="view"><div class="section-head"><h2>根因决策树与修正池</h2><span>{len(roots)} 条</span></div>{root_table}</section>
<div id="empty" class="empty">没有符合筛选条件的记录</div><footer>数据源：{source_name}｜本页为Excel的只读可视化，不改变锁单、账户余额或执行状态。</footer>
</main><script>
const tabs=[...document.querySelectorAll('.tab')], views=[...document.querySelectorAll('.view')], search=document.querySelector('#search'), hit=document.querySelector('#hit-filter'), empty=document.querySelector('#empty');
tabs.forEach(b=>b.onclick=()=>{{tabs.forEach(x=>x.classList.toggle('active',x===b));views.forEach(v=>v.classList.toggle('active',v.id===b.dataset.view));applyFilter();}});
function applyFilter(){{const q=search.value.trim().toLowerCase(), active=document.querySelector('.view.active');let shown=0;active.querySelectorAll('[data-search]').forEach(el=>{{const ok=el.dataset.search.includes(q)&&(!hit.value||active.id!=='signals'||el.dataset.hit===hit.value);el.style.display=ok?'':'none';if(ok)shown++;}});empty.style.display=shown?'none':'block';}}
search.addEventListener('input',applyFilter);hit.addEventListener('change',applyFilter);
</script></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    runtime = load_json(RUNTIME_PATH, {})
    queue = load_json(QUEUE_PATH, {})
    workbook = latest_workbook(runtime, args.workbook)
    if not workbook.exists():
        raise SystemExit(f"Workbook not found: {workbook}")
    now = datetime.now(SHANGHAI)
    run_id = now.strftime("%Y%m%d_%H%M%S")
    output_root = args.output_root if args.output_root.is_absolute() else BASE_DIR / args.output_root
    snapshot_dir = output_root / run_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    content = render_html(workbook, runtime, queue, now)
    snapshot = snapshot_dir / "index.html"
    snapshot.write_text(content, encoding="utf-8")
    latest = output_root / "latest.html"
    shutil.copyfile(snapshot, latest)
    metadata = {
        "schema_version": "1.0",
        "generated_at": now.isoformat(),
        "source_workbook": workbook.relative_to(BASE_DIR).as_posix(),
        "snapshot": snapshot.relative_to(BASE_DIR).as_posix(),
        "latest": latest.relative_to(BASE_DIR).as_posix(),
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
