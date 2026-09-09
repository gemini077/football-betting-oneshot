"""Shared presentation primitives for the public static FBOS pages."""

from __future__ import annotations

import html
from typing import Any


PUBLIC_UI_CSS = r"""
:root {
  --shell: #05111C;
  --shell-2: #0B1723;
  --page: #F6F7F9;
  --card: #FFFFFF;
  --card-soft: #FBFCFD;
  --surface: var(--card);
  --surface-subtle: var(--card-soft);
  --ink: #12161C;
  --text: var(--ink);
  --muted: #66707B;
  --quiet: #98A0AA;
  --line: #E7E9ED;
  --line-2: #D9DDE3;
  --orange: #FF6A00;
  --accent: var(--orange);
  --orange-soft: #FFF2E9;
  --accent-soft: var(--orange-soft);
  --blue: #104AA6;
  --home: var(--blue);
  --blue-2: #0D3F8F;
  --draw: #B9BCC2;
  --red: #F32232;
  --away: var(--red);
  --green: #0A8E43;
  --green-2: #0B6F38;
  --verified: #18794E;
  --purple: #7A35B9;
  --warning: #A85C00;
  --warning-soft: #FFF4E8;
  --danger: #B42318;
  --danger-soft: #FFF1F0;
  --radius: 14px;
  --shadow: 0 18px 55px rgba(0,0,0,.17);
  --card-shadow: 0 1px 0 rgba(0,0,0,.015);
  --max: 1240px;
  --ui-text-scale: 1;
  --type-body: calc(14px * var(--ui-text-scale));
  --type-section: calc(16px * var(--ui-text-scale));
  --type-support: calc(12px * var(--ui-text-scale));
  --type-meta: calc(11px * var(--ui-text-scale));
  --type-label: calc(12px * var(--ui-text-scale));
  --type-display: calc(22px * var(--ui-text-scale));
  --matrix-type: calc(10px * var(--ui-text-scale));
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background: linear-gradient(180deg,#020D16,#07131D); color: var(--ink); }
body { font-size: var(--type-body); line-height: 1.45; font-family: Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; -webkit-font-smoothing: antialiased; }
a { color: inherit; }
button { font: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }
button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid var(--orange); outline-offset: 3px; }
[hidden] { display: none !important; }

/* R4 shared shell: OneShot rail, warm rounded workspace, quiet editorial chrome. */
.app-shell { display: grid; grid-template-columns: 178px minmax(0,1fr); min-height: 100vh; padding: 0 16px 16px 0; }
.side-rail { min-height: 100vh; padding: 24px 12px 16px; color: #FFF; display: flex; flex-direction: column; }
.rail-brand { display: block; padding: 2px 8px; color: #FFF; text-decoration: none; }
.rail-brand-row { display: flex; align-items: center; gap: 10px; }
.rail-logo { position: relative; width: 35px; height: 35px; flex: none; }
.rail-logo .outer { position: absolute; inset: 3px; border: 3px solid var(--orange); border-radius: 50%; }
.rail-logo .inner { position: absolute; inset: 11px; border: 3px solid #FFF; border-radius: 50%; }
.rail-logo::before, .rail-logo::after { content: ""; position: absolute; background: var(--orange); border-radius: 2px; }
.rail-logo::before { left: 16px; top: 0; width: 3px; height: 8px; box-shadow: 0 27px 0 var(--orange); }
.rail-logo::after { left: 0; top: 16px; width: 8px; height: 3px; box-shadow: 27px 0 0 var(--orange); }
.rail-mark { font-size: 20px; font-weight: 780; letter-spacing: -.045em; }
.rail-caption { display: block; margin: 21px 8px 17px; color: #D7DCE1; font-size: var(--type-meta); line-height: 1.45; }
.rail-nav { display: grid; gap: 4px; }
.nav-item { position: relative; display: flex; align-items: center; gap: 10px; min-height: 49px; padding: 9px 10px 9px 13px; border-radius: 10px; color: #F4F6F8; font-size: var(--type-support); text-decoration: none; }
.nav-item:hover { background: rgba(255,255,255,.045); }
.nav-item.active { background: #121E29; }
.nav-item.active::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 2px; border-radius: 99px; background: var(--orange); }
.nav-icon { width: 20px; height: 20px; flex: none; color: #F3F5F7; }
.nav-item.active .nav-icon { color: var(--orange); }
.nav-copy strong, .nav-copy span { display: block; }
.nav-copy strong { font-size: var(--type-support); font-weight: 680; }
.nav-copy span { margin-top: 2px; color: #B8C0C8; font-size: var(--type-meta); }
.rail-footer { margin-top: auto; }
.rail-card { padding: 14px 13px; border: 1px solid rgba(255,255,255,.075); border-radius: 10px; background: linear-gradient(180deg,#111D28,#0D1924); color: #DFE4E8; }
.rail-card strong { font-size: var(--type-support); }
.rail-card p { margin: 7px 0 0; font-size: var(--type-meta); line-height: 1.55; }
.workspace { min-width: 0; padding-top: 10px; }
.page { min-height: calc(100vh - 26px); overflow: hidden; border-radius: 18px; background: var(--page); box-shadow: var(--shadow); }
.topbar { display: flex; align-items: center; justify-content: space-between; min-height: 54px; padding: 0 19px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,.45); }
.crumbs, .utility { display: flex; align-items: center; }
.crumbs { gap: 11px; font-size: var(--type-support); }
.crumbs .back { font-size: 21px; line-height: 1; }
.utility { gap: 14px; font-size: var(--type-support); }
.content { width: 100%; max-width: var(--max); margin-inline: auto; padding: 12px 14px 16px; }
.mobile-topbar { display: none; }

/* R4 match hero and signature data panels are shared by Dashboard and Detail. */
.hero { display: grid; grid-template-columns: minmax(0,1fr) 205px minmax(0,1fr); align-items: center; min-height: 112px; padding: 16px 22px; border: 1px solid var(--line); border-radius: 12px; background: #FFF; box-shadow: var(--card-shadow); }
.team { display: flex; align-items: center; gap: 16px; min-width: 0; }
.team.right { justify-content: flex-end; text-align: left; }
.team.right .team-copy { text-align: left; }
.team h1 { margin: 0; font-size: var(--type-display); font-weight: 760; letter-spacing: -.04em; overflow-wrap: anywhere; }
.team-meta { margin-top: 5px; color: #30353B; font-size: var(--type-meta); }
.kick { text-align: center; }
.kick small, .kick span { display: block; }
.kick small { color: #282D33; font-size: var(--type-meta); }
.kick strong { display: block; margin: 4px 0 3px; font-size: 27px; line-height: 1; font-weight: 760; letter-spacing: -.03em; }
.kick span { color: #34393E; font-size: var(--type-meta); }
.tabs { display: flex; gap: 36px; margin-top: 6px; padding: 0 20px; border-bottom: 1px solid var(--line); }
.tab { position: relative; display: inline-flex; align-items: center; min-height: 44px; padding: 8px 0; color: #242A30; font-size: var(--type-support); text-decoration: none; }
.tab.active { font-weight: 700; }
.tab.active::after { content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: var(--orange); }
.panel { min-width: 0; padding: 15px 16px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); box-shadow: var(--card-shadow); }
.panel h2 { margin: 0 0 14px; font-size: var(--type-section); font-weight: 720; letter-spacing: -.022em; }
.info-i { display: inline-grid; place-items: center; width: 18px; height: 18px; margin-left: 4px; border: 1px solid #525A63; border-radius: 50%; font-size: var(--type-meta); font-style: normal; vertical-align: 1px; }
.prob-cells { display: grid; grid-template-columns: repeat(3,1fr); }
.prob-cell { padding: 11px 9px 12px; border-right: 1px solid var(--line); text-align: center; }
.prob-cell:last-child { border-right: 0; }
.prob-cell span, .prob-cell strong, .prob-cell em { display: block; }
.prob-cell span { font-size: var(--type-meta); }
.prob-cell strong { margin-top: 9px; font-size: 24px; line-height: 1; font-weight: 760; font-variant-numeric: tabular-nums; }
.prob-cell em { width: max-content; margin: 8px auto 0; padding: 4px 12px; border-radius: 99px; background: #F1F2F4; color: #20252B; font-size: var(--type-meta); font-style: normal; }
.home-t { color: var(--blue); }
.away-t { color: var(--red); }
.probbar { display: flex; height: 8px; margin: 15px 1px 0; overflow: hidden; border-radius: 99px; background: #EEE; }
.probbar span { display: block; min-width: 2px; height: 100%; }
.probbar span:nth-child(1) { background: var(--blue); }
.probbar span:nth-child(2) { background: var(--draw); }
.probbar span:nth-child(3) { background: var(--red); }
.prob-caption { margin-top: 12px; color: #4C535B; font-size: var(--type-meta); text-align: center; }
.score-title-row { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.score-title-row small { color: var(--muted); font-size: var(--type-meta); }
.score-grid { width: 100%; border-collapse: separate; border-spacing: 2px; font-size: var(--matrix-type); font-variant-numeric: tabular-nums; text-align: center; }
.score-grid th { padding: 2px; font-weight: 700; }
.score-grid td { padding: 6px 2px; background: #F1F6F0; }
.score-grid td.hi1 { background: #92BC93; font-weight: 760; }
.score-grid td.hi2 { background: #B7D0B7; }
.score-grid td.hi3 { background: #D4E3D2; }
.score-legend { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 10px; color: #5E666E; font-size: var(--type-meta); }
.legend-grad { width: 104px; height: 7px; border-radius: 99px; background: linear-gradient(90deg,#EEF5ED,#8FBE8F,#2F8D49); }
.top3line { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--line); color: #454C53; font-size: var(--type-support); }
.take-list { display: grid; gap: 8px; }
.take-row { display: grid; grid-template-columns: 24px minmax(0,1fr) auto; gap: 8px; align-items: start; }
.take-icon { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; background: var(--blue); color: #FFF; font-size: 9px; font-weight: 800; }
.take-icon.green { background: var(--green); }
.take-icon.orange { background: var(--orange); }
.take-icon.purple { background: var(--purple); }
.take-copy strong, .take-copy span { display: block; }
.take-copy strong { font-size: var(--type-support); }
.take-copy span { margin-top: 2px; color: #56606A; font-size: var(--type-meta); line-height: 1.42; }
.take-val { color: var(--green-2); font-size: var(--type-meta); font-weight: 760; }
.panel-link { display: flex; align-items: center; justify-content: space-between; margin: 11px -16px -14px; padding: 10px 16px; border-top: 1px solid var(--line); font-size: var(--type-meta); }
.grid3 { display: grid; grid-template-columns: 1.03fr 1.05fr .92fr; gap: 9px; margin-top: 10px; }
.grid3.second { grid-template-columns: 1.03fr 1.05fr .92fr; }
.bars { display: grid; grid-template-columns: repeat(5,1fr); gap: 10px; align-items: end; height: 129px; padding: 8px 6px 0; }
.bar-item { text-align: center; }
.bar-value { font-size: var(--type-meta); }
.bar-col { display: flex; align-items: end; justify-content: center; height: 78px; margin: 4px auto 7px; }
.bar-col span { width: 19px; border-radius: 3px 3px 0 0; background: var(--blue); }
.bar-col.aux span { background: #83B8DF; }
.bar-label { font-size: var(--type-support); }
.subtle-note { margin-top: 8px; color: #7B838C; font-size: var(--type-meta); }
.compare-head { display: flex; gap: 18px; margin-bottom: 7px; color: #4B535A; font-size: var(--type-meta); }
.compare-head span::before { content: ""; display: inline-block; width: 12px; height: 8px; margin-right: 5px; border-radius: 2px; background: var(--blue); vertical-align: -1px; }
.compare-head span:last-child::before { background: #BFC2C6; }
.compare-grid { display: grid; grid-template-columns: 66px repeat(3,1fr); gap: 6px 8px; align-items: end; font-size: var(--type-meta); }
.mini-bars { display: flex; align-items: end; justify-content: center; gap: 7px; height: 53px; }
.mini-bars span { width: 18px; border-radius: 3px 3px 0 0; }
.mini-bars .m { background: var(--blue); }
.mini-bars .k { background: #BFC2C6; }
.delta { font-size: var(--type-meta); font-weight: 760; text-align: center; }
.delta.pos { color: var(--green); }
.delta.neg { color: var(--red); }
.evidence-list { display: grid; }
.evidence-row { display: grid; grid-template-columns: 25px minmax(0,1fr); gap: 8px; padding: 8px 0; border-top: 1px solid var(--line); }
.evidence-row:first-child { border-top: 0; }
.evidence-glyph { display: grid; place-items: center; width: 25px; height: 25px; border: 1px solid #27303A; border-radius: 50%; font-size: var(--type-meta); font-weight: 700; }
.evidence-row strong, .evidence-row span { display: block; }
.evidence-row strong { font-size: var(--type-support); }
.evidence-row span { margin-top: 2px; color: #5C646D; font-size: var(--type-meta); line-height: 1.42; }
.trust-strip { display: grid; grid-template-columns: repeat(5,1fr); margin-top: 10px; border: 1px solid var(--line); border-radius: 12px; background: #FFF; }
.trust-item { display: grid; grid-template-columns: 25px minmax(0,1fr); gap: 8px; padding: 11px 12px; border-right: 1px solid var(--line); }
.trust-item:last-child { border-right: 0; }
.trust-ico { display: grid; place-items: center; width: 25px; height: 25px; border: 1px solid #CDD2D7; border-radius: 50%; color: #222A31; font-size: var(--type-meta); }
.trust-item strong, .trust-item span { display: block; }
.trust-item strong { font-size: var(--type-meta); }
.trust-item span { margin-top: 4px; color: #5F6870; font-size: var(--type-meta); line-height: 1.48; }
.footer-principles { margin: 12px 14px 0; padding: 10px 16px 11px; border: 1px solid rgba(255,255,255,.13); border-radius: 11px; background: #07131E; color: #FFF; }
.principle-title { color: var(--orange); font-size: var(--type-meta); font-weight: 760; }
.principles { display: grid; grid-template-columns: repeat(5,1fr); margin-top: 8px; }
.principle { display: grid; grid-template-columns: 28px minmax(0,1fr); gap: 9px; padding: 0 15px; border-right: 1px solid rgba(255,255,255,.13); }
.principle:first-child { padding-left: 0; }
.principle:last-child { border-right: 0; }
.principle-icon { display: grid; place-items: center; width: 25px; height: 25px; border: 1px solid rgba(255,255,255,.5); border-radius: 50%; font-size: 10px; }
.principle strong, .principle span { display: block; }
.principle strong { font-size: var(--type-meta); }
.principle span { margin-top: 2px; color: #C7CED5; font-size: var(--type-meta); }
.copyright { display: flex; gap: 26px; padding: 10px 16px 12px; color: #7F8993; font-size: var(--type-meta); }
.closed-beta-notice { margin-top: 12px; padding: 10px 14px; border-left: 2px solid var(--line); background: transparent; color: var(--quiet); font-size: var(--type-support); }
.closed-beta-notice strong, .closed-beta-notice span { display: block; margin-top: 3px; }
.closed-beta-notice strong { color: var(--muted); font-size: var(--type-support); }
.dashboard-trust { border-top: 0; }
.matchup-side { min-width: 0; }
.matchup-name { min-width: 0; overflow-wrap: anywhere; }
.matchup-vs { color: var(--quiet); font-size: var(--type-meta); font-weight: 800; letter-spacing: .14em; text-align: center; text-transform: uppercase; }
.team-badge { display: inline-grid; flex: 0 0 28px; place-items: center; width: 28px; height: 28px; overflow: hidden; border: 0; border-radius: 0; background: transparent; color: var(--muted); font-size: 11px; font-weight: 800; line-height: 1; text-transform: uppercase; }
.team-badge img { display: block; width: 100%; height: 100%; object-fit: contain; }
.team-badge[data-crest-kind="fallback"], .team-badge-fallback { border: 1px solid var(--line-2); border-radius: 8px; background: #F0F1EF; }
.hero .team-badge { flex-basis: 68px; width: 68px; height: 68px; border: 0; border-radius: 0; background: transparent; font-size: 17px; }
.hero .team-badge[data-crest-kind="fallback"] { border: 1px solid var(--line-2); border-radius: 10px; background: #F0F1EF; }
.team.right .team-badge { order: 2; }
.beginner-help { margin-top: 12px; }
.beginner-help-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.beginner-help-heading h2 { margin-bottom: 0; }
.beginner-help-heading > span { color: var(--muted); font-size: var(--type-meta); }
.beginner-help-list { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 1px; margin: 14px 0 0; padding: 0; list-style: none; border: 1px solid var(--line); background: var(--line); }
.beginner-help-item { min-width: 0; padding: 12px; background: var(--card-soft); }
.beginner-help-item strong, .beginner-help-item span { display: block; }
.beginner-help-item strong { font-size: var(--type-support); }
.beginner-help-item span { margin-top: 6px; color: var(--muted); font-size: var(--type-meta); line-height: 1.5; }
.mobile-bottom { display: none; }

@media (max-width: 980px) {
  .app-shell { grid-template-columns: 156px minmax(0,1fr); }
  .side-rail { padding-left: 14px; padding-right: 14px; }
}
@media (max-width: 820px) {
  :root { --type-section: calc(15px * var(--ui-text-scale)); }
  body { background: #FFF; }
  .app-shell { display: block; padding: 0; }
  .side-rail { display: none; }
  .workspace { padding: 0; }
  .page { min-height: 100vh; border-radius: 0; box-shadow: none; background: #FFF; }
  .topbar { display: none; }
  .mobile-topbar { display: flex; align-items: center; justify-content: space-between; min-height: 46px; padding: 0 13px; border-bottom: 1px solid var(--line); background: #FFF; color: var(--ink); }
  .mobile-topbar strong { min-width: 0; overflow: hidden; font-size: var(--type-support); letter-spacing: -.02em; text-overflow: ellipsis; white-space: nowrap; }
  .mobile-topbar a { display: inline-grid; place-items: center; flex: 0 0 44px; width: 44px; min-width: 44px; height: 44px; min-height: 44px; color: var(--ink); font-size: 20px; line-height: 1; text-decoration: none; }
  .mobile-topbar span { color: var(--muted); font-size: 18px; line-height: 1; }
  .content { padding: 0 14px 18px; }
  .hero { grid-template-columns: 1fr 76px 1fr; min-height: 83px; padding: 10px 2px; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; box-shadow: none; }
  .team { gap: 7px; }
  .hero .team-badge { flex-basis: 40px; width: 40px; height: 40px; border-width: 1px; font-size: 11px; }
  .team h1 { font-size: var(--type-body); }
  .team-meta { margin-top: 2px; font-size: var(--type-meta); }
  .kick small { font-size: var(--type-meta); }
  .kick strong { margin: 2px 0; font-size: var(--type-display); }
  .kick span { font-size: var(--type-meta); }
  .tabs { gap: 22px; margin: 0; padding: 0 1px; overflow: auto; white-space: nowrap; }
  .tab { padding: 8px 0; font-size: var(--type-support); }
  .grid3 { display: block; margin-top: 0; }
  .panel { padding: 14px 0; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; box-shadow: none; }
  .panel h2 { margin-bottom: 11px; font-size: var(--type-section); }
  .prob-cell { padding: 7px 4px; }
  .prob-cell span { font-size: var(--type-meta); }
  .prob-cell strong { font-size: 19px; }
  .prob-cell em { display: none; }
  .probbar { height: 6px; margin-top: 11px; }
  .prob-caption { display: none; }
  .score-grid { font-size: calc(9px * var(--ui-text-scale)); border-spacing: 1px; }
  .score-grid td { padding: 4px 1px; }
  .score-legend { display: none; }
  .top3line { font-size: var(--type-support); }
  .take-row { grid-template-columns: 20px minmax(0,1fr) auto; }
  .take-icon { width: 19px; height: 19px; }
  .take-copy strong { font-size: var(--type-support); }
  .take-copy span { font-size: var(--type-meta); }
  .take-val { font-size: var(--type-meta); }
  .grid3.second { display: block; }
  .bars { height: 100px; }
  .bar-col { height: 56px; }
  .compare-grid { grid-template-columns: 56px repeat(3,1fr); }
  .evidence-row strong { font-size: var(--type-support); }
  .evidence-row span { font-size: var(--type-meta); }
  .trust-strip, .footer-principles, .copyright { display: none; }
  .beginner-help-list { display: block; }
  .beginner-help-item { padding: 10px 0; border-top: 1px solid var(--line); }
  .beginner-help-item:first-child { border-top: 0; }
  .mobile-bottom { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); position: fixed; z-index: 20; left: 0; right: 0; bottom: 0; min-height: 60px; padding: 6px 4px 5px; border-top: 1px solid var(--line); background: rgba(255,255,255,.985); backdrop-filter: blur(10px); }
  .bottom-item { display: grid; place-items: center; min-height: 44px; padding: 7px 4px; color: #171B20; font-size: var(--type-meta); text-align: center; text-decoration: none; }
  .bottom-item svg { display: block; width: 17px; height: 17px; margin: 0 auto 3px; }
  .bottom-item.active { color: var(--orange); }
}
@media (max-width: 360px) {
  .content { padding-left: 12px; padding-right: 12px; }
  .hero { grid-template-columns: 1fr 70px 1fr; }
  .team h1 { font-size: var(--type-body); }
  .kick strong { font-size: var(--type-display); }
  .prob-cell strong { font-size: 18px; }
  .score-grid { font-size: calc(9px * var(--ui-text-scale)); }
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


def render_team_badge(
    name: Any,
    source: Any = None,
    *,
    side: str = "team",
    variant: str = "",
) -> str:
    """Render an existing crest source or a neutral deterministic initial."""

    label = html.escape(str(name or "").strip() or f"{side}\u961f\u5fbd", quote=True)
    asset = _asset_value(source)
    classes = "team-badge" + (f" {variant}" if variant else "")
    if _is_renderable_asset(asset):
        return (
            f'<span class="{classes}" data-crest-kind="existing" aria-label="{label}\u961f\u5fbd">'
            f'<img src="{html.escape(asset, quote=True)}" alt="" loading="lazy"></span>'
        )
    return (
        f'<span class="{classes} team-badge-fallback" data-crest-kind="fallback" '
        f'aria-label="{label}\u961f\u5fbd\u6682\u672a\u63d0\u4f9b">{html.escape(team_initial(name))}</span>'
    )


def render_beginner_help(section_id: str = "beginner-help") -> str:
    """Render the short, non-technical guide linked by the public shell."""

    safe_id = html.escape(section_id, quote=True)
    return (
        f'<section id="{safe_id}" class="beginner-help panel" aria-labelledby="{safe_id}-title">'
        f'<div class="beginner-help-heading"><div><div class="section-kicker">\u5feb\u901f\u8bfb\u6cd5</div>'
        f'<h2 id="{safe_id}-title">\u600e\u4e48\u770b</h2></div><span>\u5148\u8bfb\u8fd9\u56db\u9879</span></div>'
        '<ul class="beginner-help-list">'
        '<li class="beginner-help-item"><strong>\u80dc / \u5e73 / \u8d1f\u6982\u7387</strong>'
        '<span>\u4e09\u79cd\u8d5b\u679c\u5404\u81ea\u5360\u591a\u5c11\u6982\u7387\uff1b\u6570\u5b57\u7ea6\u4e3a 100%\uff0c\u4e0d\u662f\u786e\u5b9a\u7ed3\u679c\u3002</span></li>'
        '<li class="beginner-help-item"><strong>\u6700\u53ef\u80fd\u6bd4\u5206</strong>'
        '<span>\u6bd4\u5206\u5206\u5e03\u4e2d\u5355\u4e2a\u6982\u7387\u6700\u9ad8\u7684\u7ed3\u679c\uff1b\u5b83\u4ecd\u7136\u53ea\u662f\u4e00\u79cd\u53ef\u80fd\u3002</span></li>'
        '<li class="beginner-help-item"><strong>\u9996\u9009\u65b9\u5411</strong>'
        '<span>\u6839\u636e\u5f53\u524d\u53ef\u7528\u7684\u8d5b\u524d\u4fe1\u606f\u9009\u51fa\u4e3b\u8981\u65b9\u5411\uff1b\u6ca1\u6709\u6e05\u6670\u4f18\u52bf\u65f6\u4f1a\u663e\u793a\u6682\u65e0\u9996\u9009\u3002</span></li>'
        '<li class="beginner-help-item"><strong>\u4ec5\u4f9b\u89c2\u5bdf / \u6682\u65e0\u9996\u9009</strong>'
        '<span>\u8868\u793a\u8be5\u73a9\u6cd5\u7684\u8bb0\u5f55\u6216\u8d28\u91cf\u8fd8\u4e0d\u6ee1\u8db3\u6b63\u5f0f\u5224\u65ad\uff1b\u4e0d\u628a\u4fdd\u7559\u7684\u6570\u503c\u5f53\u4f5c\u5efa\u8bae\u3002</span></li>'
        '</ul></section>'
    )


def render_public_document(
    *,
    title: str,
    css: str,
    content_html: str,
    dashboard_href: str,
    history_href: str | None,
    sources_href: str | None = None,
    help_href: str | None = None,
    mobile_label: str,
    body_class: str = "",
    body_suffix: str = "",
    mobile_variant: str = "dashboard",
) -> str:
    """Wrap page content with the one shared rail, mobile bar, and theme."""

    dashboard_href_html = html.escape(dashboard_href, quote=True)
    history_target = html.escape(history_href or dashboard_href, quote=True)
    mobile_label_html = html.escape(mobile_label, quote=True)
    sources_target = html.escape(sources_href or dashboard_href, quote=True)
    help_target = html.escape(help_href or dashboard_href, quote=True)
    nav_items = (
        f'<a class="nav-item active" href="{dashboard_href_html}" aria-current="page">'
        '<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">'
        '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/>'
        f'</svg><span class="nav-copy"><strong>\u6bd4\u8d5b</strong><span>\u4eca\u65e5\u6bd4\u8d5b</span></span></a>'
        f'<a class="nav-item" href="{history_target}">'
        '<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">'
        '<path d="M4 19V5M9 19v-8M14 19V9M19 19V3"/>'
        f'</svg><span class="nav-copy"><strong>\u5386\u53f2\u9a8c\u8bc1</strong><span>\u8d5b\u540e\u8bb0\u5f55</span></span></a>'
        f'<a class="nav-item" href="{sources_target}">'
        '<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">'
        '<circle cx="12" cy="12" r="9"/><path d="M12 10v6M12 7h.01"/>'
        f'</svg><span class="nav-copy"><strong>\u6570\u636e\u4e0e\u65b9\u6cd5</strong><span>\u6a21\u578b\u4e0e\u6765\u6e90</span></span></a>'
        f'<a class="nav-item" href="{help_target}">'
        '<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">'
        '<path d="M12 3l2.8 5.7L21 9.6l-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2 7.5 14 3 9.6l6.2-.9z"/>'
        f'</svg><span class="nav-copy"><strong>\u600e\u4e48\u770b</strong><span>\u6982\u7387\u8bf4\u660e</span></span></a>'
    )
    if mobile_variant == "detail":
        mobile_lead = f'<a href="{dashboard_href_html}" aria-label="\u8fd4\u56de\u4eca\u65e5\u6bd4\u8d5b">\u2190</a>'
        mobile_markup = f"{mobile_lead}<strong>{mobile_label_html}</strong>"
    else:
        mobile_lead = f'<strong>{mobile_label_html}</strong>'
        mobile_markup = mobile_lead
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
  <a class="rail-brand" href="{dashboard_href_html}"><span class="rail-brand-row"><span class="rail-logo"><span class="outer"></span><span class="inner"></span></span><span class="rail-mark">OneShot</span></span><span class="rail-caption">Football Prediction Intelligence</span></a>
  <nav class="rail-nav" aria-label="\u4e3b\u5bfc\u822a">
    {nav_items}
  </nav>
  <div class="rail-footer"><div class="rail-card"><strong>OneShot Beta</strong><p>\u4e0d\u5356\u786e\u5b9a\u7b54\u6848\u3002<br>\u628a\u6982\u7387\u3001\u6bd4\u5206\u7a7a\u95f4\u4e0e\u8d5b\u524d\u4f9d\u636e\u653e\u5728\u4e00\u8d77\u770b\u3002</p></div></div>
</aside>
<main class="workspace">
<div class="mobile-topbar">{mobile_markup}</div>
{content_html}
</main>
</div>
<nav class="mobile-bottom" aria-label="\u79fb\u52a8\u7aef\u4e3b\u5bfc\u822a"><a class="bottom-item active" href="{dashboard_href_html}">\u6bd4\u8d5b</a><a class="bottom-item" href="{history_target}">\u5386\u53f2</a><a class="bottom-item" href="{sources_target}">\u6570\u636e</a><a class="bottom-item" href="{help_target}">\u600e\u4e48\u770b</a></nav>
{body_suffix}
</body>
</html>"""
