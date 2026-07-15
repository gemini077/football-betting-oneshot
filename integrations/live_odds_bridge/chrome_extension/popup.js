"use strict";

const enabled = document.getElementById("enabled");
const captureStatus = document.getElementById("captureStatus");
const overlayEnabled = document.getElementById("overlayEnabled");
const overlayStatus = document.getElementById("overlayStatus");
const healthButton = document.getElementById("health");
const healthStatus = document.getElementById("healthStatus");

function render(settings) {
  enabled.checked = Boolean(settings.enabled);
  if (!settings.enabled) {
    captureStatus.textContent = "尚未启用";
    captureStatus.className = "status";
    return;
  }
  if (settings.lastError) {
    captureStatus.textContent = `最近错误：${settings.lastError}`;
    captureStatus.className = "status bad";
    return;
  }
  captureStatus.textContent = settings.lastSuccessAt
    ? `最近写入：${new Date(settings.lastSuccessAt).toLocaleTimeString()}｜已存 ${settings.storedCount || 0}`
    : "已启用，请刷新滚球页面";
  captureStatus.className = settings.lastSuccessAt ? "status ok" : "status";
}

function renderOverlay(settings) {
  overlayEnabled.checked = settings.overlayEnabled !== false;
  overlayStatus.textContent = overlayEnabled.checked ? "已显示在比赛详情页" : "已隐藏，可随时重新打开";
  overlayStatus.className = overlayEnabled.checked ? "status ok" : "status";
}

chrome.storage.local.get({ enabled: false, overlayEnabled: true }, (settings) => {
  render(settings);
  renderOverlay(settings);
});

enabled.addEventListener("change", async () => {
  await chrome.storage.local.set({
    enabled: enabled.checked,
    lastError: null,
    storedCount: 0,
    droppedCount: 0
  });
  render(await chrome.storage.local.get({ enabled: false }));
});

overlayEnabled.addEventListener("change", async () => {
  await chrome.storage.local.set({ overlayEnabled: overlayEnabled.checked });
  renderOverlay(await chrome.storage.local.get({ overlayEnabled: true }));
});

healthButton.addEventListener("click", () => {
  healthStatus.textContent = "检查中…";
  healthStatus.className = "status";
  chrome.runtime.sendMessage({ type: "FBOS_BRIDGE_HEALTH" }, (result) => {
    if (chrome.runtime.lastError || !result?.ok) {
      healthStatus.textContent = `未连接：${chrome.runtime.lastError?.message || result?.error || "本地服务无响应"}`;
      healthStatus.className = "status bad";
      return;
    }
    healthStatus.textContent = `已连接｜存储 ${result.health.stored || 0} 条｜影子模式`;
    healthStatus.className = "status ok";
  });
});
