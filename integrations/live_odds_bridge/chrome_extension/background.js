"use strict";

const TARGET_HOST = "user-pc-new.hl99yjjpf.com";
const DEFAULT_ENDPOINT = "http://127.0.0.1:8765/v1/events";

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
        const url = serviceUrl(settings.endpoint, "/v1/ev-profile");
        url.searchParams.set("match_id", String(message.matchId));
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
  return false;
});
