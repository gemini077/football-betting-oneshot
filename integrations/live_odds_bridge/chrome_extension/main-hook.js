(() => {
  "use strict";

  if (window.__FBOS_LIVE_ODDS_MAIN_HOOK__) return;
  window.__FBOS_LIVE_ODDS_MAIN_HOOK__ = true;

  const EVENT_NAME = "fbos-live-odds-bridge";
  const MARKET_HINT = /(odds?|market|match|mid|score|sport|tournament|handicap|over|under|home|away|playId|mhn|man|mcg)/i;
  const SENSITIVE_KEY = /(pass(word|wd)?|pwd|token|secret|cookie|authorization|auth|session|account|username|user_name|user_?info|user_?id|uid|phone|mobile|email|bank|balance|wallet|credit|withdraw|deposit|realname|identity|id_card|otp|captcha)/i;
  const MAX_STRING = 20000;
  const MAX_API_STRING = 1200000;
  const MAX_ITEMS = 400;
  const MATCH_API_PATHS = new Set([
    "/v1/w/matchDetail/getMatchDetailPB",
    "/v1/w/matchDetail/getMatchOddsInfo1PB",
    "/v1/w/matchDetail/getMatchOddsInfo2PB",
    "/v1/w/structureMatchBaseInfoByMids",
    "/v1/w/structureMatchBaseInfoByMidsPB"
  ]);

  function safeUrl(value) {
    try {
      const parsed = new URL(String(value), location.href);
      return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
    } catch {
      return "unavailable";
    }
  }

  function sanitize(value, depth = 0, maxString = MAX_STRING) {
    if (depth > 11) return "[DEPTH_LIMIT]";
    if (value === null || value === undefined || typeof value === "boolean" || typeof value === "number") {
      return value ?? null;
    }
    if (typeof value === "string") {
      return value
        .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "[REDACTED_BEARER]")
        .replace(/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g, "[REDACTED_JWT]")
        .slice(0, maxString);
    }
    if (Array.isArray(value)) return value.slice(0, MAX_ITEMS).map((item) => sanitize(item, depth + 1, maxString));
    if (value instanceof ArrayBuffer) return { binary: true, byte_length: value.byteLength };
    if (ArrayBuffer.isView(value)) return { binary: true, byte_length: value.byteLength };
    if (typeof value === "object") {
      const cleaned = {};
      for (const [rawKey, item] of Object.entries(value).slice(0, MAX_ITEMS)) {
        const key = String(rawKey).slice(0, 160);
        if (SENSITIVE_KEY.test(key)) continue;
        cleaned[key] = sanitize(item, depth + 1, maxString);
      }
      return cleaned;
    }
    return String(value).slice(0, 2000);
  }

  function normalizePayload(payload, maxString = MAX_STRING) {
    if (typeof payload !== "string") return sanitize(payload, 0, maxString);
    try {
      return sanitize(JSON.parse(payload), 0, maxString);
    } catch {
      return sanitize(payload, 0, maxString);
    }
  }

  function looksLikeMarket(payload) {
    try {
      const sample = typeof payload === "string" ? payload : JSON.stringify(payload);
      return MARKET_HINT.test(sample.slice(0, 120000));
    } catch {
      return false;
    }
  }

  function isExplicitlyOutbound(payload) {
    if (!payload || typeof payload !== "object" || payload.cmd !== "js_code") return false;
    const data = payload.data;
    if (!data || typeof data !== "object" || !Array.isArray(data.param)) return false;
    if (data.fun === "window.postMessage") {
      return data.param.some((item) => item && typeof item === "object" && item.cmd === "WS_MSG_SEND");
    }
    return data.fun === "wslog.send_msg" && data.param.includes("WS---S:");
  }

  function emit(sourceType, payload, transportMeta = {}) {
    if (isExplicitlyOutbound(payload)) return;
    const clean = normalizePayload(payload, sourceType === "api_response" ? MAX_API_STRING : MAX_STRING);
    if (sourceType !== "api_response" && !looksLikeMarket(clean)) return;
    document.dispatchEvent(new CustomEvent(EVENT_NAME, {
      detail: {
        source_type: sourceType,
        transport_meta: sanitize(transportMeta),
        payload: clean
      }
    }));
  }

  function allowedMatchApi(value) {
    try {
      const parsed = new URL(String(value), location.href);
      if (parsed.protocol !== "https:") return null;
      for (const endpoint of MATCH_API_PATHS) {
        if (parsed.pathname === endpoint || parsed.pathname.endsWith(endpoint)) return endpoint;
      }
      return null;
    } catch {
      return null;
    }
  }

  const NativeFetch = window.fetch;
  if (typeof NativeFetch === "function") {
    window.fetch = async function (...args) {
      const response = await NativeFetch.apply(this, args);
      const requestValue = args[0] instanceof Request ? args[0].url : args[0];
      const requestPath = allowedMatchApi(requestValue);
      if (requestPath) {
        response.clone().json().then((body) => {
          emit("api_response", body, { transport: "fetch", request_path: requestPath });
        }).catch(() => {});
      }
      return response;
    };
  }

  const NativeXhrOpen = XMLHttpRequest.prototype.open;
  const XHR_CAPTURE_HANDLER = Symbol("fbos-xhr-capture-handler");
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    if (this[XHR_CAPTURE_HANDLER]) {
      this.removeEventListener("loadend", this[XHR_CAPTURE_HANDLER]);
      delete this[XHR_CAPTURE_HANDLER];
    }
    const requestPath = allowedMatchApi(url);
    const result = NativeXhrOpen.call(this, method, url, ...rest);
    if (requestPath) {
      const handler = () => {
        if (this.status < 200 || this.status >= 300) return;
        let body = null;
        try {
          if (this.responseType === "json") body = this.response;
          else if (!this.responseType || this.responseType === "text") body = JSON.parse(this.responseText);
        } catch {
          return;
        }
        emit("api_response", body, {
          transport: "xmlhttprequest",
          request_path: requestPath,
          status: this.status
        });
      };
      this[XHR_CAPTURE_HANDLER] = handler;
      this.addEventListener("loadend", handler, { once: true });
    }
    return result;
  };

  const NativeWorker = window.Worker;
  if (typeof NativeWorker === "function") {
    window.Worker = new Proxy(NativeWorker, {
      construct(Target, args, NewTarget) {
        const worker = Reflect.construct(Target, args, NewTarget);
        const workerUrl = safeUrl(args[0]);
        worker.addEventListener("message", (event) => {
          emit("worker_message", event.data, { worker_url: workerUrl });
        });
        return worker;
      }
    });
  }

  const NativeSharedWorker = window.SharedWorker;
  if (typeof NativeSharedWorker === "function") {
    window.SharedWorker = new Proxy(NativeSharedWorker, {
      construct(Target, args, NewTarget) {
        const worker = Reflect.construct(Target, args, NewTarget);
        const workerUrl = safeUrl(args[0]);
        worker.port?.addEventListener("message", (event) => {
          emit("shared_worker_message", event.data, { worker_url: workerUrl });
        });
        worker.port?.start?.();
        return worker;
      }
    });
  }

  const NativeWebSocket = window.WebSocket;
  if (typeof NativeWebSocket === "function") {
    window.WebSocket = new Proxy(NativeWebSocket, {
      construct(Target, args, NewTarget) {
        const socket = Reflect.construct(Target, args, NewTarget);
        const socketUrl = safeUrl(args[0]);
        socket.addEventListener("message", (event) => {
          if (typeof event.data === "string") {
            emit("websocket_message", event.data, { websocket_url: socketUrl });
          } else if (event.data instanceof Blob && event.data.size <= 1000000) {
            event.data.text().then((text) => {
              emit("websocket_message", text, { websocket_url: socketUrl, blob_size: event.data.size });
            }).catch(() => {});
          }
        });
        return socket;
      }
    });
  }
})();
