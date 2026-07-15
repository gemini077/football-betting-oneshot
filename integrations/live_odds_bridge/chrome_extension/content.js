(() => {
  "use strict";

  const EVENT_NAME = "fbos-live-odds-bridge";
  const MESSAGE_TYPE = "FBOS_BRIDGE_EVENT";
  const TARGET_HOST = "user-pc-new.hl99yjjpf.com";
  let enabled = false;
  let contextValid = true;
  let sequence = 0;
  const sessionId = `${Date.now()}-${crypto.randomUUID?.() || Math.random().toString(16).slice(2)}`;

  chrome.storage.local.get({ enabled: false }, (settings) => {
    enabled = Boolean(settings.enabled);
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === "local" && changes.enabled) {
      enabled = Boolean(changes.enabled.newValue);
    }
  });

  function pageAllowed() {
    return location.protocol === "https:" && location.hostname === TARGET_HOST;
  }

  function send(sourceType, payload, transportMeta = {}) {
    if (!contextValid || !enabled || !pageAllowed()) return;
    sequence += 1;
    try {
      const pending = chrome.runtime.sendMessage({
        type: MESSAGE_TYPE,
        event: {
          schema_version: "1.0",
          captured_at: new Date().toISOString(),
          source_type: sourceType,
          page_url: location.href,
          page_title: document.title,
          session_id: sessionId,
          sequence,
          transport_meta: transportMeta,
          payload
        }
      });
      if (pending && typeof pending.catch === "function") {
        pending.catch(disableInvalidContext);
      }
    } catch (_error) {
      disableInvalidContext();
    }
  }

  function disableInvalidContext() {
    contextValid = false;
    enabled = false;
    document.removeEventListener(EVENT_NAME, handleBridgeEvent);
  }

  function handleBridgeEvent(event) {
    const detail = event.detail;
    if (!detail || typeof detail !== "object") return;
    send(detail.source_type, detail.payload, detail.transport_meta || {});
  }

  document.addEventListener(EVENT_NAME, handleBridgeEvent);

})();
