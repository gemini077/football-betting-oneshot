"use strict";

const TARGET_HOST = "user-pc-new.hl99yjjpf.com";
const DEFAULT_ENDPOINT = "http://127.0.0.1:8765/v1/events";
const REMOTE_PROFILE_ROOT = "https://gemini077.github.io/football-betting-oneshot/live_ev_profiles/current";

async function loadSettings() {
  return chrome.storage.local.get({
    enabled: false,
    overlayEnabled: true,
    endpoint: DEFAULT_ENDPOINT,
    lastSuccessAt: null,
    lastError: null,
    storedCount: 0,
    droppedCount: 0
  });
}

function serviceUrl(endpoint, path) {
  const url = new URL(endpoint || DEFAULT_ENDPOINT);
  url.pathname = path;
  url.search = "";
  return url;
}

async function fetchServiceJson(path, options = {}) {
  const settings = await loadSettings();
  const response = await fetch(serviceUrl(settings.endpoint, path), {
    cache: "no-store",
    ...options
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

async function updateStatus(patch) {
  await chrome.storage.local.set(patch);
}

function normalizedTeamName(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[\s\-_.·'’()（）]/g, "");
}

function sameTeamPair(profile, homeName, awayName) {
  const expectedHome = normalizedTeamName(homeName);
  const expectedAway = normalizedTeamName(awayName);
  const actualHome = normalizedTeamName(profile?.match?.home);
  const actualAway = normalizedTeamName(profile?.match?.away);
  if (!expectedHome || !expectedAway || !actualHome || !actualAway) return false;
  const homeMatches = actualHome === expectedHome || actualHome.includes(expectedHome) || expectedHome.includes(actualHome);
  const awayMatches = actualAway === expectedAway || actualAway.includes(expectedAway) || expectedAway.includes(actualAway);
  return homeMatches && awayMatches;
}

function profileTimestamp(profile) {
  const value = Date.parse(profile?.published_at || profile?.analysis_timestamp || "");
  return Number.isFinite(value) ? value : 0;
}

async function fetchRemoteJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) return null;
  return response.json().catch(() => null);
}

async function fetchRemoteProfile(matchId, homeName, awayName) {
  const exact = await fetchRemoteJson(`${REMOTE_PROFILE_ROOT}/${encodeURIComponent(String(matchId))}.json`);
  if (exact?.match) return { ...exact, sync_source: "github-pages" };
  if (!homeName || !awayName) return null;
  const index = await fetchRemoteJson(`${REMOTE_PROFILE_ROOT}/index.json`);
  const matched = (index?.profiles || [])
    .filter((profile) => sameTeamPair(profile, homeName, awayName))
    .sort((left, right) => profileTimestamp(right) - profileTimestamp(left))[0];
  return matched ? { ...matched, sync_source: "github-pages-team-match" } : null;
}

async function loadNewestAnalysisProfile(settings, message) {
  let localResult = null;
  try {
    const url = serviceUrl(settings.endpoint, "/v1/ev-profile");
    url.searchParams.set("match_id", String(message.matchId));
    const response = await fetch(url, { cache: "no-store" });
    const result = await response.json().catch(() => ({}));
    if (response.ok && result?.found && result?.profile) {
      localResult = { ...result.profile, sync_source: "local-bridge" };
    }
  } catch {
    localResult = null;
  }
  const remoteResult = await fetchRemoteProfile(message.matchId, message.homeName, message.awayName).catch(() => null);
  const profile = !localResult ? remoteResult
    : !remoteResult ? localResult
      : profileTimestamp(remoteResult) >= profileTimestamp(localResult) ? remoteResult : localResult;
  return profile
    ? { found: true, profile, sync_source: profile.sync_source }
    : { found: false, profile: null, sync_source: null };
}

async function forwardEvent(event) {
  const settings = await loadSettings();
  if (!settings.enabled) return { ok: false, skipped: "disabled" };
  let page;
  try {
    page = new URL(event.page_url);
  } catch {
    await updateStatus({ lastError: "页面URL无效" });
    return { ok: false, skipped: "invalid_page_url" };
  }
  if (page.protocol !== "https:" || page.hostname !== TARGET_HOST) {
    await updateStatus({ lastError: "页面不在允许域名内" });
    return { ok: false, skipped: "page_not_allowed" };
  }
  try {
    const response = await fetch(settings.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
      cache: "no-store"
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    await updateStatus({
      lastSuccessAt: new Date().toISOString(),
      lastError: null,
      storedCount: Number(settings.storedCount || 0) + (result.stored ? 1 : 0)
    });
    return result;
  } catch (error) {
    await updateStatus({
      lastError: String(error.message || error),
      droppedCount: Number(settings.droppedCount || 0) + 1
    });
    return { ok: false, error: String(error.message || error) };
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "FBOS_BRIDGE_EVENT" && message.event) {
    forwardEvent(message.event).then(sendResponse);
    return true;
  }
  if (message?.type === "FBOS_BRIDGE_HEALTH") {
    loadSettings().then(async (settings) => {
      try {
        const healthUrl = new URL(settings.endpoint);
        healthUrl.pathname = "/v1/health";
        healthUrl.search = "";
        const response = await fetch(healthUrl, { cache: "no-store" });
        sendResponse({ ok: response.ok, health: await response.json() });
      } catch (error) {
        sendResponse({ ok: false, error: String(error.message || error) });
      }
    });
    return true;
  }
  if (message?.type === "FBOS_BRIDGE_LATEST" && message.matchId) {
    loadSettings().then(async (settings) => {
      try {
        const url = serviceUrl(settings.endpoint, "/v1/latest");
        url.searchParams.set("match_id", String(message.matchId));
        url.searchParams.set("active_only", "true");
        const response = await fetch(url, { cache: "no-store" });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
        sendResponse({ ok: true, data: result });
      } catch (error) {
        sendResponse({ ok: false, error: String(error.message || error) });
      }
    });
    return true;
  }
  if (message?.type === "FBOS_EV_REPRICE" && message.request) {
    fetchServiceJson("/v1/reprice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(message.request)
    }).then(
      (result) => sendResponse({ ok: true, data: result }),
      (error) => sendResponse({ ok: false, error: String(error.message || error) })
    );
    return true;
  }
  if (message?.type === "FBOS_MODEL_STATE") {
    fetchServiceJson("/v1/model-state").then(
      (result) => sendResponse({ ok: true, data: result }),
      (error) => sendResponse({ ok: false, error: String(error.message || error) })
    );
    return true;
  }
  if (message?.type === "FBOS_EV_PROFILE" && message.matchId) {
    loadSettings().then(async (settings) => {
      try {
        const result = await loadNewestAnalysisProfile(settings, message);
        sendResponse({ ok: true, data: result });
      } catch (error) {
        sendResponse({ ok: false, error: String(error.message || error) });
      }
    });
    return true;
  }
  return false;
});
