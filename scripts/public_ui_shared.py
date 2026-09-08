"""Shared presentation primitives for the public static FBOS pages."""

from __future__ import annotations

import html
from typing import Any


PUBLIC_UI_CSS = r"""
:root {
  --shell-bg: #07111A;
  --workspace-bg: #F7F7F5;
  --surface: #FFFFFF;
  --surface-subtle: #FAFAF8;
  --text: #121417;
  --ink: var(--text);
  --muted: #626870;
  --quiet: #8B9198;
  --line: #E6E7E4;
  --accent: #FF6A00;
  --accent-soft: #FFF1E8;
  --home: #1F5EA8;
  --draw: #A9ADB2;
  --away: #E23B3B;
  --warning: #B75C00;
  --warning-soft: #FFF4E8;
  --danger: #B42318;
  --danger-soft: #FFF1F0;
  --verified: #18794E;
  --max: 1240px;
}
* { box-sizing: border-box; }
html { background: var(--shell-bg); scroll-behavior: smooth; }
body {
  min-width: 0;
  margin: 0;
  background: var(--workspace-bg);
  color: var(--text);
  font: 14px/1.5 Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; }
button { font: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }
button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
[hidden] { display: none !important; }
.app-shell { display: grid; grid-template-columns: 184px minmax(0, 1fr); min-height: 100vh; }
.side-rail {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  padding: 30px 18px 22px;
  background: var(--shell-bg);
  color: #F5F7F8;
}
.rail-brand { display: block; text-decoration: none; }
.rail-mark { display: block; font-size: 25px; font-weight: 750; letter-spacing: -.06em; }
.rail-caption { display: block; margin-top: 3px; color: #A9B3BB; font-size: 10px; line-height: 1.4; letter-spacing: .12em; text-transform: uppercase; }
.rail-nav { display: grid; gap: 5px; margin-top: 54px; }
.nav-item { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; min-height: 44px; padding: 11px 10px; border-left: 2px solid transparent; color: #A9B3BB; font-size: 13px; text-decoration: none; }
.nav-item small { color: #65727C; font-size: 9px; letter-spacing: .06em; text-transform: uppercase; }
.nav-item:hover, .nav-item.active { border-left-color: var(--accent); background: rgba(255,255,255,.06); color: #FFFFFF; }
.nav-item.active small { color: #F6A26D; }
.rail-footer { margin-top: auto; padding: 14px 10px 0; border-top: 1px solid rgba(255,255,255,.12); color: #7F8B94; font-size: 10px; }
.rail-footer strong { display: block; color: #D7DDE1; font-size: 11px; font-weight: 650; }
.rail-footer span { display: block; margin-top: 4px; }
.workspace { min-width: 0; background: var(--workspace-bg); }
.mobile-topbar { display: none; }
.team-badge {
  display: inline-grid;
  flex: 0 0 28px;
  place-items: center;
  width: 28px;
  height: 28px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--surface-subtle);
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  text-transform: uppercase;
}
.team-badge img { display: block; width: 100%; height: 100%; object-fit: contain; }
.team-badge-fallback { background: #F0F1EF; }
@media (max-width: 980px) {
  .app-shell { grid-template-columns: 156px minmax(0, 1fr); }
  .side-rail { padding-left: 14px; padding-right: 14px; }
}
@media (max-width: 820px) {
  .app-shell { display: block; }
  .side-rail { display: none; }
  .mobile-topbar { display: flex; align-items: center; justify-content: space-between; min-height: 56px; padding: 0 16px; background: var(--shell-bg); color: #F5F7F8; }
  .mobile-topbar a { font-weight: 750; letter-spacing: -.05em; text-decoration: none; }
  .mobile-topbar span { color: #B7C0C7; font-size: 12px; }
}
@media (max-width: 360px) {
  .mobile-topbar { padding-left: 12px; padding-right: 12px; }
}
"""


def _asset_value(source: Any) -> str:
    if isinstance(source, dict):
        source = source.get("src") or source.get("url") or source.get("path")
    return str(source or "").strip()


def _is_renderable_asset(source: str) -> bool:
    lowered = source.lower()
    return bool(source) and not lowered.startswith(("data:", "javascript:", "blob:"))


def team_initial(name: Any) -> str:
    text = str(name or "").strip()
    for character in text:
        if character.isalnum() or "\u4e00" <= character <= "\u9fff":
            return character.upper()
    return "?"


def render_team_badge(name: Any, source: Any = None, *, side: str = "team") -> str:
    """Render an existing crest source or a neutral deterministic initial."""

    label = html.escape(str(name or "").strip() or f"{side}徽章", quote=True)
    asset = _asset_value(source)
    if _is_renderable_asset(asset):
        return (
            f'<span class="team-badge" data-crest-kind="existing" aria-label="{label}队徽">'
            f'<img src="{html.escape(asset, quote=True)}" alt="" loading="lazy"></span>'
        )
    return (
        f'<span class="team-badge team-badge-fallback" data-crest-kind="fallback" '
        f'aria-label="{label}队徽暂未提供">{html.escape(team_initial(name))}</span>'
    )


def render_public_document(
    *,
    title: str,
    css: str,
    content_html: str,
    dashboard_href: str,
    history_href: str | None,
    mobile_label: str,
    body_class: str = "",
    body_suffix: str = "",
) -> str:
    """Wrap page content with the one shared rail, mobile bar, and theme."""

    dashboard_href_html = html.escape(dashboard_href, quote=True)
    history_html = ""
    if history_href:
        history_html = (
            f'<a class="nav-item" href="{html.escape(history_href, quote=True)}">'
            '<span>历史验证</span><small>History</small></a>'
        )
    title_html = html.escape(title, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_html}</title>
<style>{PUBLIC_UI_CSS}{css}</style>
</head>
<body class="{html.escape(body_class, quote=True)}">
<div class="app-shell">
<aside class="side-rail">
  <a class="rail-brand" href="{dashboard_href_html}"><span class="rail-mark">FBOS</span><span class="rail-caption">Football Prediction<br>Intelligence</span></a>
  <nav class="rail-nav" aria-label="主导航">
    <a class="nav-item active" href="{dashboard_href_html}" aria-current="page"><span>今日比赛</span><small>Matches</small></a>
    {history_html}
  </nav>
  <div class="rail-footer"><strong>赛前分析</strong><span>只展示能改变当前判断的内容。</span></div>
</aside>
<main class="workspace">
<div class="mobile-topbar"><a href="{dashboard_href_html}">FBOS</a><span>{html.escape(mobile_label)}</span></div>
{content_html}
</main>
</div>
{body_suffix}
</body>
</html>"""
