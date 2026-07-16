#!/usr/bin/env python3
"""Best-effort structured pre-match facts for unattended GitHub runs."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary"
BEIJING = timezone(timedelta(hours=8))


def _load_json(url: str, opener=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "FootballBettingOneShot/0.14"})
    with opener(request, timeout=18) as response:
        return json.loads(response.read().decode("utf-8"))


def _kickoff_utc(workspace: dict) -> datetime | None:
    raw = str(workspace.get("kickoff") or "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=BEIJING)
    return value.astimezone(timezone.utc)


def _event_datetime(event: dict) -> datetime | None:
    raw = str(event.get("date") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recent_form_items(deep: dict) -> list[dict]:
    form = ((deep.get("shuju") or {}).get("recent_form") or {}) if isinstance(deep, dict) else {}
    labels = (
        ("home_overall", "主队近10场"),
        ("home_home", "主队近10个主场"),
        ("away_overall", "客队近10场"),
        ("away_away", "客队近10个客场"),
    )
    items = []
    for key, label in labels:
        row = form.get(key) or {}
        if not row.get("matches"):
            continue
        items.append({
            "label": label,
            "value": (
                f"{row.get('wins', 0)}胜{row.get('draws', 0)}平{row.get('losses', 0)}负，"
                f"进{row.get('goals_for', 0)}球/失{row.get('goals_against', 0)}球"
            ),
            "source": "500.com赛前数据快照",
        })
    return items


def _previous_meeting(summary: dict, home_team_id: str, away_team_id: str) -> dict | None:
    candidates = []
    for block in summary.get("lastFiveGames") or []:
        for event in block.get("events") or []:
            ids = {str(event.get("homeTeamId") or ""), str(event.get("awayTeamId") or "")}
            if {home_team_id, away_team_id} == ids and event.get("score"):
                candidates.append(event)
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.get("gameDate") or ""))


def _espn_form_row(summary: dict, team_id: str, venue: str | None = None) -> dict:
    """Convert ESPN's last-five block into team-perspective aggregate form."""
    block = next(
        (
            item for item in summary.get("lastFiveGames") or []
            if str((item.get("team") or {}).get("id") or "") == str(team_id)
        ),
        {},
    )
    events = []
    for event in block.get("events") or []:
        is_home = str(event.get("homeTeamId") or "") == str(team_id)
        is_away = str(event.get("awayTeamId") or "") == str(team_id)
        if not (is_home or is_away):
            continue
        if venue == "home" and not is_home:
            continue
        if venue == "away" and not is_away:
            continue
        try:
            home_score = int(event.get("homeTeamScore"))
            away_score = int(event.get("awayTeamScore"))
        except (TypeError, ValueError):
            continue
        goals_for, goals_against = (home_score, away_score) if is_home else (away_score, home_score)
        events.append((event, goals_for, goals_against))
    if not events:
        return {}
    wins = sum(goals_for > goals_against for _, goals_for, goals_against in events)
    draws = sum(goals_for == goals_against for _, goals_for, goals_against in events)
    losses = len(events) - wins - draws
    dates = sorted(str(event.get("gameDate") or "")[:10] for event, _, _ in events if event.get("gameDate"))
    return {
        "matches": len(events),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": sum(goals_for for _, goals_for, _ in events),
        "goals_against": sum(goals_against for _, _, goals_against in events),
        "sample_start": dates[0] if dates else None,
        "sample_end": dates[-1] if dates else None,
        "source": "ESPN lastFiveGames",
    }


def _espn_recent_form(summary: dict, home_team_id: str, away_team_id: str) -> dict:
    return {
        "home_overall": _espn_form_row(summary, home_team_id),
        "home_home": _espn_form_row(summary, home_team_id, "home"),
        "away_overall": _espn_form_row(summary, away_team_id),
        "away_away": _espn_form_row(summary, away_team_id, "away"),
    }


def collect_prematch_fundamentals(workspace: dict, deep: dict, opener=urllib.request.urlopen) -> dict:
    """Return checked facts. Missing upstream fields are described as checked, not silently guessed."""
    deep_form = ((deep.get("shuju") or {}).get("recent_form") or {}) if isinstance(deep, dict) else {}
    items = _recent_form_items(deep)
    result = {
        "status": "已核验近期攻防；等待联网赛前源",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
        "sources": [],
        "recent_form": deep_form,
        "form_source": "500.com赛前数据快照" if deep_form else None,
    }
    kickoff = _kickoff_utc(workspace)
    if kickoff is None:
        return result
    query = urllib.parse.urlencode({"dates": kickoff.strftime("%Y%m%d"), "limit": 1000})
    try:
        scoreboard = _load_json(f"{ESPN_SCOREBOARD}?{query}", opener)
    except Exception as error:  # network failure remains explicit and cannot alter model values
        result["status"] = "近期攻防已核验；赛前联网源暂时不可用"
        result["items"].append({"label": "赛前联网核验", "value": f"本次请求失败：{type(error).__name__}；未据此猜测首发或伤停"})
        return result

    matches = []
    for event in scoreboard.get("events") or []:
        event_time = _event_datetime(event)
        if event_time and abs((event_time - kickoff).total_seconds()) <= 120:
            matches.append(event)
    if len(matches) != 1:
        result["status"] = "近期攻防已核验；未能唯一匹配外部赛程"
        result["items"].append({"label": "外部赛程", "value": f"已按开赛时间核验，候选{len(matches)}场，未强行匹配"})
        return result

    event = matches[0]
    event_id = str(event.get("id") or "")
    source_url = f"https://www.espn.com/soccer/match/_/gameId/{event_id}"
    try:
        summary = _load_json(f"{ESPN_SUMMARY}?{urllib.parse.urlencode({'event': event_id})}", opener)
    except Exception as error:
        result["status"] = "外部赛程已匹配；详细赛前信息请求失败"
        result["items"].append({"label": "外部赛程", "value": str(event.get("name") or "已匹配"), "source_url": source_url})
        result["items"].append({"label": "详细信息", "value": f"请求失败：{type(error).__name__}"})
        result["sources"].append(source_url)
        return result

    competition = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    home = next((row for row in competitors if row.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((row for row in competitors if row.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})
    home_id = str((home.get("team") or {}).get("id") or "")
    away_id = str((away.get("team") or {}).get("id") or "")
    result["items"].append({"label": "赛程交叉核验", "value": str(event.get("name") or "已匹配"), "source_url": source_url})

    if not deep_form and home_id and away_id:
        espn_form = _espn_recent_form(summary, home_id, away_id)
        if (espn_form.get("home_overall") or {}).get("matches") and (espn_form.get("away_overall") or {}).get("matches"):
            result["recent_form"] = espn_form
            result["form_source"] = "ESPN近5场赛事样本（含可获得的同赛事历史，非完整联赛近况）"
            for key, label in (("home_overall", "主队 ESPN 近5场"), ("away_overall", "客队 ESPN 近5场")):
                row = espn_form.get(key) or {}
                result["items"].append({
                    "label": label,
                    "value": (
                        f"{row.get('wins', 0)}胜{row.get('draws', 0)}平{row.get('losses', 0)}负，"
                        f"进{row.get('goals_for', 0)}球/失{row.get('goals_against', 0)}球；"
                        f"样本期{row.get('sample_start') or '—'}至{row.get('sample_end') or '—'}"
                    ),
                    "source": "ESPN lastFiveGames",
                    "source_url": source_url,
                })

    previous = _previous_meeting(summary, home_id, away_id)
    if previous:
        result["items"].append({
            "label": "最近直接交锋",
            "value": f"{previous.get('score')}（{previous.get('competitionName') or '同赛事'}，{str(previous.get('gameDate') or '')[:10]}）",
            "source_url": ((previous.get("links") or [{}])[0]).get("href") or source_url,
        })

    game_info = summary.get("gameInfo") or {}
    venue = game_info.get("venue") or competition.get("venue") or {}
    address = venue.get("address") or {}
    venue_text = " · ".join(filter(None, [venue.get("fullName") or venue.get("shortName"), address.get("city"), address.get("country")]))
    result["items"].append({"label": "比赛场地", "value": venue_text or "上游赛前页尚未发布（已联网检查）", "source_url": source_url})

    rosters = summary.get("rosters") or []
    roster_count = sum(len(row.get("roster") or []) for row in rosters)
    lineup_value = f"已发布，共{roster_count}名球员" if roster_count else "尚未发布（已联网检查，临近开赛自动任务会重查）"
    result["items"].append({"label": "确认首发", "value": lineup_value, "source_url": source_url})

    injuries = summary.get("injuries") or []
    injury_count = sum(len(row.get("injuries") or row.get("items") or []) for row in injuries) if isinstance(injuries, list) else 0
    injury_value = f"结构化伤停{injury_count}人" if injury_count else "赛前页未返回结构化伤停名单；不等同于无人伤停"
    result["items"].append({"label": "伤停核验", "value": injury_value, "source_url": source_url})

    weather = game_info.get("weather") or competition.get("weather") or {}
    weather_text = weather.get("displayValue") or weather.get("conditionId") or weather.get("temperature")
    result["items"].append({"label": "天气", "value": str(weather_text) if weather_text else "上游赛前页尚未发布（已联网检查）", "source_url": source_url})
    result["status"] = "赛程、交锋、场地、首发发布状态、伤停发布状态与天气发布状态已联网核验"
    result["sources"].append(source_url)
    return result
