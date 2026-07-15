#!/usr/bin/env python3
"""Run one owner-authorized DeepSeek-assisted pre-match analysis.

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
MODEL_VERSION = "v0.13.1"
AUTO_INPUT_ROOT = ROOT / "data" / "analysis_inputs" / "automated"


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
    return {
        "request": request,
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


SYSTEM_PROMPT = """你是 Football Betting OneShot 的辅助分析层。只使用给定 JSON 证据，禁止联网假装、禁止补造伤停、首发、xG、赔率或概率。缺失就明确写缺失。输出必须是单个 JSON 对象，不要 Markdown。

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
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "stream": False,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    last_error = None
    for attempt in range(3):
        try:
            with opener(request, timeout=180) as response:
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
    for key in required_text:
        decisions[key] = str(decisions.get(key) or "数据不足，暂不形成结论")
    errors = decisions.get("maximum_error_points")
    decisions["maximum_error_points"] = [str(item) for item in errors] if isinstance(errors, list) and errors else ["自动分析可能受缺失首发、伤停或盘口时间轴影响"]
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
    model["status"] = str(model.get("status") or "DeepSeek辅助综合；未替代本地概率校准")

    if not isinstance(raw.get("data_quality"), dict):
        raw["data_quality"] = {
            "status": "待复核",
            "missing": [],
            "notes": ["由 DeepSeek 基于抓取快照生成，缺口须在报告中显式披露"],
        }
    if not isinstance(raw.get("fundamentals"), dict):
        raw["fundamentals"] = {"status": "待复核", "items": []}
    if not isinstance(raw.get("evidence_chain"), list):
        raw["evidence_chain"] = []

    betting = raw.get("betting") if isinstance(raw.get("betting"), dict) else {}
    raw["betting"] = betting
    betting["candidates"] = []
    betting["state"] = "空仓｜未锁单"
    betting["execution_authorized"] = False
    betting["lock_state_changed"] = False
    betting["bankroll_state_changed"] = False
    betting.pop("open_bets", None)
    raw["automation"] = {"provider": "DeepSeek", "model": model_name, "generated_at": now, "owner_authorized_request": True}
    return raw


def run_json_command(command: list[str], allow_failure: bool = False) -> dict:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8")
    if completed.returncode and not allow_failure:
        raise RuntimeError(completed.stderr or completed.stdout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Command did not return JSON: {' '.join(command)}\n{completed.stdout}\n{completed.stderr}") from error


def run_pipeline(request: dict, api_key: str, model_name: str) -> dict:
    fetch = run_json_command([
        sys.executable, "scripts/fetch_football_data.py",
        "--date", request["business_date"], "--match", request["match"],
        "--deep", "--no-cache",
    ], allow_failure=True)
    manifest_path = Path(fetch["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    if not manifest_path.exists():
        raise RuntimeError("Fetch completed without a manifest")

    raw = call_deepseek(analysis_context(manifest_path, request), api_key, model_name)
    analysis = normalize_analysis(raw, request, model_name)
    AUTO_INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", request.get("match_id") or "match")
    output = AUTO_INPUT_ROOT / f"{stamp}_{safe_id}.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False, suffix=".tmp") as handle:
        json.dump(analysis, handle, ensure_ascii=False, indent=2)
        temporary = Path(handle.name)
    temporary.replace(output)

    report = run_json_command([
        sys.executable, "scripts/generate_analysis_report.py",
        "--fetch-manifest", str(manifest_path), "--analysis-json", str(output),
    ])
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
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")
    model_name = os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
    print(json.dumps(run_pipeline(request, api_key, model_name), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
