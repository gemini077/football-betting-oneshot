#!/usr/bin/env python3
"""Run one owner-authorized deterministic pre-match analysis.

DeepSeek is a synthesis layer. It never authorizes execution, changes the
bankroll, or creates a locked bet. Generated output is passed through the
existing report gate and is always published as a non-final analysis draft.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-pro"
MODEL_VERSION = "v0.17.0"
AUTO_INPUT_ROOT = ROOT / "data" / "analysis_inputs" / "automated"
WORKSPACE_PATH = ROOT / "data" / "match_workspace" / "latest.json"
DEEP_FALLBACK_ROOT = ROOT / "data" / "source_cache" / "deep_fallback"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_request(value: dict) -> dict:
    date_value = str(value.get("business_date") or value.get("date") or "").strip()
    match_id = str(value.get("match_id") or "").strip()
    match = str(value.get("match") or "").strip()
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", date_value):
        raise ValueError("business_date must use YYYY-MM-DD")
    if match_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", match_id):
        raise ValueError("match_id contains unsupported characters")
    if not match or len(match) > 120 or any(char in match for char in "\r\n\0"):
        raise ValueError("match is missing or invalid")
    return {"business_date": date_value, "match_id": match_id, "match": match}


def request_from_event(path: Path) -> dict:
    event = load_json(path)
    if isinstance(event.get("issue"), dict):
        body = str(event["issue"].get("body") or "")
        fields = {}
        for key in ("match_id", "business_date", "match"):
            found = re.search(rf"(?mi)^{key}\s*:\s*(.+?)\s*$", body)
            fields[key] = found.group(1).strip() if found else ""
        return validate_request(fields)
    inputs = event.get("inputs") or {}
    return validate_request(inputs)


def prune(value: Any, depth: int = 0) -> Any:
    """Bound API context while retaining structured evidence."""
    if depth >= 9:
        return "[depth-limited]"
    if isinstance(value, dict):
        return {str(key): prune(item, depth + 1) for key, item in list(value.items())[:100]}
    if isinstance(value, list):
        return [prune(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:1600]
    return value


def selected_workspace_match(request: dict) -> dict:
    if not WORKSPACE_PATH.exists():
        return {}
    try:
        workspace = load_json(WORKSPACE_PATH)
    except (OSError, json.JSONDecodeError):
        return {}
    requested_id = str(request.get("match_id") or "")
    requested_name = re.sub(r"\s+", "", str(request.get("match") or "")).casefold()
    for match in workspace.get("matches") or []:
        if not isinstance(match, dict):
            continue
        match_name = re.sub(r"\s+", "", f"{match.get('home', '')}vs{match.get('away', '')}").casefold()
        if (requested_id and str(match.get("id") or "") == requested_id) or match_name == requested_name:
            return prune(match)
    return {}


def fetch_date_for_request(request: dict) -> str:
    """Use the Sporttery business date, including after-midnight kickoffs."""
    return request["business_date"]


def fetch_match_selector(request: dict) -> str:
    """Prefer the immutable Sporttery match ID over display-name aliases."""
    return str(request.get("match_id") or request.get("match") or "").strip()


def devig_three_way(odds: dict) -> dict | None:
    keys = ("home", "draw", "away")
    try:
        prices = {key: float(odds[key]) for key in keys}
    except (KeyError, TypeError, ValueError):
        return None
    if any(price <= 1 for price in prices.values()):
        return None
    raw = {key: 1 / price for key, price in prices.items()}
    overround = sum(raw.values())
    context = {
        "prices": prices,
        "overround": round(overround, 6),
        "payout_rate": round(1 / overround, 6),
        "fair_probabilities": {key: round(raw[key] / overround, 6) for key in keys},
        "role": "official_market_baseline_only_not_model_probability",
    }
    return context


def analysis_context(manifest_path: Path, request: dict) -> dict:
    manifest = load_json(manifest_path)
    sources = {}
    for name, metadata in (manifest.get("sources") or {}).items():
        sources[name] = prune(metadata)
        paths = []
        if isinstance(metadata, dict) and metadata.get("file"):
            paths.append(metadata["file"])
        if isinstance(metadata, dict):
            paths.extend(item.get("file") for item in metadata.get("matches", []) if item.get("file"))
        loaded = []
        for relative in paths[:5]:
            path = ROOT / str(relative)
            if path.exists():
                loaded.append(prune(load_json(path)))
        if loaded:
            sources[name] = {"metadata": sources[name], "snapshots": loaded}
    deep_source = sources.get("500_deep") or {}
    deep_snapshots = deep_source.get("snapshots") if isinstance(deep_source, dict) else []
    usable_deep = any(
        (snapshot.get("ouzhi") or {}).get("bookmakers") and (snapshot.get("shuju") or {}).get("recent_form")
        for snapshot in (deep_snapshots or []) if isinstance(snapshot, dict)
    )
    if not usable_deep:
        metadata = deep_source.get("metadata") if isinstance(deep_source, dict) else deep_source
        matches = (metadata or {}).get("matches") if isinstance(metadata, dict) else []
        shuju_id = next((row.get("shuju_id") for row in (matches or []) if row.get("shuju_id")), None)
        fallback = DEEP_FALLBACK_ROOT / f"{shuju_id}.json" if shuju_id else None
        if fallback and fallback.exists():
            sources["500_deep"] = {
                "metadata": {
                    **(metadata or {}), "fallback_snapshot_used": True,
                    "fallback_reason": "cloud_source_blocked",
                    "fallback_file": fallback.relative_to(ROOT).as_posix(),
                },
                "snapshots": [prune(load_json(fallback))],
            }
    workspace_match = selected_workspace_match(request)
    context = {
        "request": request,
        "selected_workspace_match": workspace_match,
        "official_market_baseline": devig_three_way(workspace_match.get("spf") or {}),
        "manifest": prune(manifest),
        "source_snapshots": sources,
        "hard_rules": {
            "scope": "90分钟含伤停，不含加时点球",
            "no_fabrication": True,
            "missing_data_must_be_disclosed": True,
            "execution_authorized": False,
            "lock_state_changed": False,
            "bankroll_state_changed": False,
        },
    }
    from prematch_fundamentals import collect_prematch_fundamentals
    deep_source = (sources.get("500_deep") or {}).get("snapshots") or []
    context["prematch_fundamentals"] = collect_prematch_fundamentals(
        workspace_match,
        deep_source[0] if deep_source and isinstance(deep_source[0], dict) else {},
    )
    from automatic_model_core import build_automatic_model
    context["deterministic_core"] = build_automatic_model(context)
    return context


SYSTEM_PROMPT = """你是 Football Betting OneShot 的辅助分析层。deterministic_core 已由固定公式完成概率、lambda、总进球、BTTS和比分计算；你只能解释它，绝对不得改写、替换或自行生成这些数值。只使用给定 JSON 证据，禁止联网假装、禁止补造伤停、首发、xG、赔率或概率。缺失就明确写缺失。输出必须是单个 JSON 对象，不要 Markdown。

selected_workspace_match 是用户在主页明确选择的体彩在售场次，里面的 spf/rqspf、开赛时间和赛事名称属于有效证据；即使其他抓取源失败，也必须使用这些官方赔率做去水市场基线分析，不得声称“无任何赔率”。official_market_baseline 只能叫市场基线，不能冒充模型概率。

必须输出这些顶层字段：report, match, data_quality, fundamentals, model, decisions, betting, evidence_chain。
decisions 必须包含 unique_primary_dimension、unique_score、mathematical_first、market_first、maximum_error_points（至少1项）、value_judgement、final_state。
model 若证据足够可包含 lambda_home、lambda_away、probabilities(home/draw/away)、expected_goals、btts、score_probabilities；证据不足则使用 null/空数组，不得猜数。
betting.candidates 必须为空数组，betting.state 必须为空仓且未锁单。报告是辅助草稿，不是最终执行版。所有结论用中文。"""


def call_deepseek(context: dict, api_key: str, model: str = DEFAULT_MODEL, opener=urllib.request.urlopen) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "请分析以下赛前证据并输出 json：\n" + json.dumps(context, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "max_tokens": 900,
        "stream": False,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    last_error = None
    for attempt in range(2):
        try:
            with opener(request, timeout=120) as response:
                envelope = json.loads(response.read().decode("utf-8"))
            content = envelope["choices"][0]["message"]["content"]
            return json.loads(content)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as error:
            last_error = error
            if isinstance(error, urllib.error.HTTPError) and error.code not in (429, 500, 502, 503, 504):
                break
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"DeepSeek request failed: {last_error}")


def normalize_analysis(raw: dict, request: dict, model_name: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("DeepSeek output must be a JSON object")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    report_value = raw.get("report")
    report = report_value if isinstance(report_value, dict) else {}
    if isinstance(report_value, str) and report_value.strip():
        report["ai_summary"] = report_value.strip()
    raw["report"] = report
    report.update({
        "model_name": "Football Betting OneShot",
        "model_version": MODEL_VERSION,
        "report_type": "DeepSeek辅助赛前分析（基础内核审计后发布）",
        "analysis_timestamp": now,
        "final_execution_version": False,
        "ai_provider": "DeepSeek",
        "ai_model": model_name,
    })
    match = raw.get("match") if isinstance(raw.get("match"), dict) else {}
    raw["match"] = match
    match["business_date"] = request["business_date"]
    match.setdefault("match_id", request.get("match_id"))
    if " vs " in request["match"]:
        home, away = request["match"].split(" vs ", 1)
        match.setdefault("home", home.strip())
        match.setdefault("away", away.strip())

    decisions = raw.get("decisions") if isinstance(raw.get("decisions"), dict) else {}
    raw["decisions"] = decisions
    required_text = (
        "unique_primary_dimension", "unique_score", "mathematical_first",
        "market_first", "value_judgement",
    )
    invalid_tokens = {"", "none", "null", "n/a", "na", "-999", "insufficient_data", "no_data"}
    for key in required_text:
        value = decisions.get(key)
        text = str(value).strip() if isinstance(value, (str, int, float)) else ""
        decisions[key] = "数据不足，暂不形成结论" if text.casefold() in invalid_tokens else text
    score_text = decisions.get("unique_score") or ""
    if not re.fullmatch(r"\d+\s*[-:]\s*\d+", score_text):
        decisions["unique_score"] = "数据不足，暂不形成结论"
    errors = decisions.get("maximum_error_points")
    cleaned_errors = []
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                if str(item.get("type") or "").upper() == "NO_DATA":
                    cleaned_errors.append("输入数据不足，无法形成模型结论")
                else:
                    cleaned_errors.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
            else:
                text = str(item).strip()
                cleaned_errors.append("输入数据不足，无法形成模型结论" if "NO_DATA" in text.upper() else text)
    decisions["maximum_error_points"] = [item for item in cleaned_errors if item] or ["自动分析可能受缺失首发、伤停或盘口时间轴影响"]
    decisions["final_state"] = "空仓｜DeepSeek辅助分析已生成，等待模型与价格复核｜未锁单"

    model = raw.get("model") if isinstance(raw.get("model"), dict) else {}
    raw["model"] = model
    probabilities = model.get("probabilities")
    valid_probabilities = isinstance(probabilities, dict) and all(
        isinstance(probabilities.get(key), (int, float)) and 0 <= probabilities[key] <= 1
        for key in ("home", "draw", "away")
    ) and abs(sum(probabilities[key] for key in ("home", "draw", "away")) - 1) <= 0.02
    if not valid_probabilities:
        model["probabilities"] = None
        model["lambda_home"] = None
        model["lambda_away"] = None
        model["expected_goals"] = None
        model["score_probabilities"] = []
    btts = model.get("btts") if isinstance(model.get("btts"), dict) else {}
    btts["judgement"] = str(btts.get("judgement") or "数据不足，暂不判断")
    model["btts"] = btts
    for key in ("score_probabilities", "total_goals_buckets"):
        value = model.get(key)
        model[key] = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    model["status"] = str(model.get("status") or "DeepSeek辅助综合；未替代本地概率校准")

    if not isinstance(raw.get("data_quality"), dict):
        raw["data_quality"] = {
            "status": "待复核",
            "missing": [],
            "notes": ["由 DeepSeek 基于抓取快照生成，缺口须在报告中显式披露"],
        }
    quality = raw["data_quality"]
    for key in ("missing", "notes"):
        value = quality.get(key)
        quality[key] = [str(item) for item in value] if isinstance(value, list) else []
    if not isinstance(raw.get("fundamentals"), dict):
        raw["fundamentals"] = {"status": "待复核", "items": []}
    fundamental_items = raw["fundamentals"].get("items")
    raw["fundamentals"]["items"] = [item for item in fundamental_items if isinstance(item, dict)] if isinstance(fundamental_items, list) else []
    if not isinstance(raw.get("evidence_chain"), list):
        raw["evidence_chain"] = []
    raw["evidence_chain"] = [item for item in raw["evidence_chain"] if isinstance(item, dict)]

    betting = raw.get("betting") if isinstance(raw.get("betting"), dict) else {}
    raw["betting"] = betting
    betting["candidates"] = []
    betting["state"] = "空仓｜未锁单"
    betting["execution_authorized"] = False
    betting["lock_state_changed"] = False
    betting["bankroll_state_changed"] = False
    betting["price_audit"] = []
    betting.pop("open_bets", None)
    raw["automation"] = {"provider": "DeepSeek", "model": model_name, "generated_at": now, "owner_authorized_request": True}
    return raw


def attach_workspace_evidence(analysis: dict, context: dict) -> dict:
    workspace = context.get("selected_workspace_match") or {}
    baseline = context.get("official_market_baseline")
    if not workspace:
        return analysis
    match = analysis.setdefault("match", {})
    for target, source in (
        ("match_id", "id"), ("match_num", "match_num"), ("home", "home"),
        ("away", "away"), ("competition", "league"), ("league", "league"),
        ("kickoff_local", "kickoff"), ("business_date", "business_date"),
    ):
        if workspace.get(source) not in (None, ""):
            match[target] = workspace[source]
    market = analysis.setdefault("market", {})
    market["official_spf"] = workspace.get("spf") or None
    market["official_rqspf"] = workspace.get("rqspf") or None
    market["official_market_baseline"] = baseline
    checked_facts = context.get("prematch_fundamentals") or {}
    fundamentals = analysis.setdefault("fundamentals", {})
    if checked_facts:
        fundamentals["status"] = checked_facts.get("status")
        fundamentals["items"] = checked_facts.get("items") or []
        fundamentals["sources"] = checked_facts.get("sources") or []
        fundamentals["recent_form"] = checked_facts.get("recent_form") or {}
        fundamentals["form_source"] = checked_facts.get("form_source")
        fundamentals["checked_at"] = checked_facts.get("checked_at")
    official_spf = workspace.get("spf") or {}
    for row in (analysis.get("betting") or {}).get("price_audit") or []:
        outcome = "home" if row.get("market") == "SPF主胜" else "draw" if row.get("market") == "SPF平局" else "away" if row.get("market") == "SPF客胜" else None
        if not outcome:
            continue
        try:
            odds = float(official_spf[outcome])
            probability = float(row.get("model_probability"))
        except (KeyError, TypeError, ValueError):
            continue
        row["odds"] = odds
        row["ev"] = round(probability * odds - 1, 6)
        row["price_source"] = "竞彩赛前SPF"
    quality = analysis.setdefault("data_quality", {})
    notes = quality.setdefault("notes", [])
    if baseline:
        note = "已从所选主页场次注入体彩胜平负赔率，并计算去水市场基线；该基线不是模型概率。"
        if note not in notes:
            notes.append(note)
        if str(quality.get("overall") or "").upper() == "ALL_SOURCES_MISSING":
            quality["overall"] = "OFFICIAL_MARKET_ONLY"
        quality["status"] = "仅市场基线" if analysis.get("model", {}).get("probabilities") is None else quality.get("status", "部分完整")
    decisions = analysis.setdefault("decisions", {})
    if baseline and decisions.get("market_first") == "数据不足，暂不形成结论":
        probabilities = baseline["fair_probabilities"]
        decisions["market_first"] = (
            f"体彩去水市场基线：主胜{probabilities['home']:.1%}、"
            f"平局{probabilities['draw']:.1%}、客胜{probabilities['away']:.1%}；仅作定价基准。"
        )
    if baseline and decisions.get("unique_primary_dimension") == "数据不足，暂不形成结论":
        decisions["unique_primary_dimension"] = "数据不足，仅保留体彩去水市场基线"
    return analysis


def apply_deterministic_core(analysis: dict, context: dict) -> dict:
    """Keep calculations deterministic; the LLM may only narrate them."""
    core = context.get("deterministic_core") or {}
    if not core.get("model"):
        return analysis
    analysis["model"] = core["model"]
    analysis["decisions"] = core["decisions"]
    if core.get("live_ev_profiles"):
        analysis["live_ev_profiles"] = core["live_ev_profiles"]
    quality = analysis.setdefault("data_quality", {})
    quality.update(core.get("data_quality") or {})
    fundamentals = analysis.setdefault("fundamentals", {})
    core_fundamentals = core.get("fundamentals") or {}
    fundamentals["structured_form"] = core_fundamentals
    if core_fundamentals.get("items"):
        fundamentals["items"] = core_fundamentals["items"]
        fundamentals["status"] = core_fundamentals.get("status")
        fundamentals["sources"] = core_fundamentals.get("sources") or []
    betting = analysis.setdefault("betting", {})
    betting["price_audit"] = core.get("price_audit") or []
    calibration = (core.get("model") or {}).get("calibration") or {}
    market = calibration.get("market_probabilities") or {}
    fundamentals = core.get("fundamentals") or {}
    decisions = analysis.get("decisions") or {}
    form = fundamentals.get("recent_form") or {}
    home_home = form.get("home_home") or {}
    away_away = form.get("away_away") or {}
    home_name = (context.get("selected_workspace_match") or {}).get("home") or "主队"
    away_name = (context.get("selected_workspace_match") or {}).get("away") or "客队"
    analysis["evidence_chain"] = [
        {
            "title": "足球维度",
            "items": [
                f"{home_name}近10个主场{home_home.get('wins', '—')}胜{home_home.get('draws', '—')}平{home_home.get('losses', '—')}负，{away_name}近10个客场{away_away.get('wins', '—')}胜{away_away.get('draws', '—')}平{away_away.get('losses', '—')}负",
                f"近期主客场攻防推导λ：{home_name}{calibration.get('form_lambda_home', 0):.2f}，{away_name}{calibration.get('form_lambda_away', 0):.2f}",
                decisions.get("match_story") or "比赛剧本等待完整数据。",
            ],
        },
        {
            "title": "市场维度",
            "items": [
                f"去水共识：主胜{market.get('home', 0):.1%}、平局{market.get('draw', 0):.1%}、客胜{market.get('away', 0):.1%}",
                f"大小球中轴：{calibration.get('market_total_line_median') if calibration.get('market_total_line_median') is not None else '未取得'}；市场占40%校准权重，不替代模型。",
                decisions.get("market_conflict") or "模型与市场暂未形成可解释分歧。",
            ],
        },
        {
            "title": "执行维度",
            "items": [
                "每个玩法分别展示当前价、模型概率、EV与最低可接受赔率；低于门槛一律不过线。",
                "执行价额外要求8%安全边际；模型包含市场校准，因此正EV只是价格复核信号。",
                decisions.get("score_vs_outcome_explanation") or "唯一比分只按单格概率解释。",
            ],
        },
        {
            "title": "模型与临场核验",
            "items": [
                f"公开事实核验状态：{fundamentals.get('status') or '待核验'}。",
                "确认首发、关键伤停、天气或盘口换线与假设冲突时，必须重算而非沿用旧报告。",
            ],
        },
    ]
    return analysis


def deterministic_analysis(context: dict, request: dict) -> dict:
    """Build the complete publishable payload without an LLM round-trip."""
    analysis = normalize_analysis({}, request, "fixed-python-core")
    analysis = apply_deterministic_core(analysis, context)
    analysis = attach_workspace_evidence(analysis, context)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    analysis["report"].update({
        "model_name": "Football Betting OneShot",
        "model_version": MODEL_VERSION,
        "report_type": "确定性赛前分析",
        "analysis_timestamp": now,
        "ai_provider": None,
        "ai_model": None,
    })
    analysis["automation"] = {
        "provider": "fixed-python-core", "generated_at": now,
        "owner_authorized_request": True, "llm_used": False,
    }
    analysis["decisions"]["final_state"] = "空仓｜未锁单"
    analysis["betting"].update({
        "state": "空仓｜未锁单", "execution_authorized": False,
        "lock_state_changed": False, "bankroll_state_changed": False,
    })
    return analysis


def has_minimum_analysis_evidence(context: dict) -> bool:
    if context.get("official_market_baseline"):
        return True
    for source in (context.get("source_snapshots") or {}).values():
        if isinstance(source, dict) and source.get("snapshots"):
            return True
    return False


def run_json_command(command: list[str], allow_failure: bool = False, timeout: int = 180) -> dict:
    try:
        completed = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(command)}") from error
    if completed.returncode and not allow_failure:
        raise RuntimeError(completed.stderr or completed.stdout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        # Some fetchers print progress before their final JSON envelope.
        for match in reversed(list(re.finditer(r"(?m)^\s*\{", completed.stdout))):
            try:
                return json.loads(completed.stdout[match.start():])
            except json.JSONDecodeError:
                continue
        error = json.JSONDecodeError("no JSON envelope found", completed.stdout, 0)
        raise RuntimeError(f"Command did not return JSON: {' '.join(command)}\n{completed.stdout}\n{completed.stderr}") from error


def report_manifest(manifest_path: Path, context: dict) -> Path:
    """Point rendering at the exact verified fallback consumed by the model."""
    deep = (context.get("source_snapshots") or {}).get("500_deep") or {}
    metadata = deep.get("metadata") if isinstance(deep, dict) else {}
    fallback_file = (metadata or {}).get("fallback_file")
    if not fallback_file:
        return manifest_path
    manifest = load_json(manifest_path)
    source = manifest.setdefault("sources", {}).setdefault("500_deep", {})
    existing = (source.get("matches") or [{}])[0]
    source.update({"status": "VERIFIED_LOCAL_FALLBACK", "success": True, "match_count": 1})
    source["matches"] = [{**existing, "file": fallback_file, "all_pages_ok": True, "fallback_snapshot_used": True}]
    output = manifest_path.with_name(manifest_path.stem + "_analysis.json")
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def mark_initial_market_checkpoint(context: dict, now: datetime | None = None) -> dict | None:
    """Prevent the monitor from immediately repeating the just-fetched snapshot."""
    from prematch_market_monitor import STATE_PATH, checkpoint_meta, due_stage
    match = context.get("selected_workspace_match") or {}
    match_id = str(match.get("id") or "")
    now = now or datetime.now().astimezone()
    stage = due_stage(match, now) if match_id else None
    if not stage:
        return None
    metadata = checkpoint_meta(match, now, stage)
    try:
        state = load_json(STATE_PATH) if STATE_PATH.exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    state.setdefault(match_id, {})[stage] = metadata
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)
    return metadata


def run_pipeline(request: dict, api_key: str = "", model_name: str = DEFAULT_MODEL, *, use_llm: bool = False) -> dict:
    from decision_evolution import append_record, attach_evolution
    print("[phase 1/5] fetching match evidence", file=sys.stderr, flush=True)
    fetch_date = fetch_date_for_request(request)
    fetch = run_json_command([
        sys.executable, "scripts/fetch_football_data.py",
        "--date", fetch_date, "--match", fetch_match_selector(request),
        "--deep", "--no-cache",
    ], allow_failure=True, timeout=240)
    manifest_path = Path(fetch["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    if not manifest_path.exists():
        raise RuntimeError("Fetch completed without a manifest")

    context = analysis_context(manifest_path, request)
    if not has_minimum_analysis_evidence(context):
        raise RuntimeError("Analysis aborted: no official odds or matched source evidence; no report was published")
    if use_llm and api_key:
        print("[phase 2/5] optional compact DeepSeek narration", file=sys.stderr, flush=True)
        raw = call_deepseek(context, api_key, model_name)
        analysis = normalize_analysis(raw, request, model_name)
        analysis = apply_deterministic_core(analysis, context)
        analysis = attach_workspace_evidence(analysis, context)
    else:
        print("[phase 2/5] deterministic core (no LLM tokens)", file=sys.stderr, flush=True)
        analysis = deterministic_analysis(context, request)
    initial_checkpoint = mark_initial_market_checkpoint(context)
    if not initial_checkpoint:
        initial_checkpoint = {
            "stage": "INITIAL",
            "captured_at": datetime.now().astimezone().isoformat(),
            "initial_capture": True,
        }
    match_id = str((context.get("selected_workspace_match") or {}).get("id") or request.get("match_id") or "")
    analysis, evolution_record = attach_evolution(analysis, match_id, initial_checkpoint)
    if initial_checkpoint:
        analysis.setdefault("report", {})["market_checkpoint"] = initial_checkpoint
        analysis.setdefault("automation", {})["market_refresh"] = {
            **initial_checkpoint,
            "initial_capture": True,
            "model_recalculated": True,
            "execution_authorized": False,
            "lock_state_changed": False,
            "bankroll_state_changed": False,
        }
    AUTO_INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", request.get("match_id") or "match")
    output = AUTO_INPUT_ROOT / f"{stamp}_{safe_id}.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False, suffix=".tmp") as handle:
        json.dump(analysis, handle, ensure_ascii=False, indent=2)
        temporary = Path(handle.name)
    temporary.replace(output)

    print("[phase 4/5] generating report", file=sys.stderr, flush=True)
    render_manifest = report_manifest(manifest_path, context)
    report = run_json_command([
        sys.executable, "scripts/generate_analysis_report.py",
        "--fetch-manifest", str(render_manifest), "--analysis-json", str(output),
    ])
    append_record(evolution_record)
    print("[phase 5/5] rebuilding homepage", file=sys.stderr, flush=True)
    run_json_command([sys.executable, "scripts/match_workspace.py", "--date", request["business_date"]])
    subprocess.run([sys.executable, "scripts/build_public_site.py"], cwd=ROOT, check=True)
    return {"request": request, "manifest": str(manifest_path), "analysis_input": str(output), **report}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one DeepSeek-assisted Football Betting OneShot analysis")
    parser.add_argument("--event", type=Path, help="GitHub event JSON")
    parser.add_argument("--date")
    parser.add_argument("--match")
    parser.add_argument("--match-id", default="")
    args = parser.parse_args()
    request = request_from_event(args.event) if args.event else validate_request({
        "business_date": args.date, "match": args.match, "match_id": args.match_id,
    })
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    model_name = os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
    use_llm = os.environ.get("FBOS_USE_LLM", "0").strip() == "1"
    print(json.dumps(run_pipeline(request, api_key, model_name, use_llm=use_llm), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
