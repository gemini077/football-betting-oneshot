(() => {
  "use strict";

  if (window.__FBOS_EV_OVERLAY_CONTENT__) return;
  window.__FBOS_EV_OVERLAY_CONTENT__ = true;

  const TARGET_HOST = "user-pc-new.hl99yjjpf.com";
  const HOST_ID = "fbos-ev-overlay-host";
  const QUOTE_REFRESH_MS = 8000;
  const REPRICE_MS = 1000;
  const PROFILE_REFRESH_MS = 5000;
  const PROFILE_PREFIX = "fbosOverlayProfile:";
  let contextValid = true;
  let host = null;
  let shadow = null;
  let ui = {};
  let latestPayload = null;
  let verifiedQuotes = [];
  let currentMatchId = null;
  let quoteTimer = null;
  let repriceTimer = null;
  let routeTimer = null;
  let profileTimer = null;
  let quoteBusy = false;
  let repriceBusy = false;
  let profileBusy = false;
  let saveTimer = null;
  let currentRemoteProfile = null;

  const STATUS_COPY = {
    candidate_price_pass: ["价格通过 · 候选", "good"],
    price_insufficient: ["价格不足 · 空仓", "bad"],
    quote_stale: ["报价过期 · 等待新价", "warn"],
    odds_unverified: ["赔率尺度未核验", "warn"],
    quote_inactive: ["盘口已暂停", "warn"],
    contract_not_found: ["当前合约未找到", "warn"],
    contract_ambiguous: ["盘口身份不唯一", "warn"],
    shadow_only_validation: ["影子计算 · 未确认概率", "warn"],
    probability_provenance_unconfirmed: ["影子计算 · 概率来源未确认", "warn"],
    probability_uncertainty_missing: ["缺少保守概率", "warn"],
    unsupported_settlement: ["结算类型暂不支持", "warn"],
    in_play_probability_not_supported: ["赛中概率未验证 · 禁止投注", "bad"],
    exposure_limit: ["暴露上限 · 空仓", "bad"],
  };

  function matchIdFromUrl() {
    const match = location.href.match(/#\/details\/(\d+)/i);
    return match ? match[1] : null;
  }

  function sendMessage(message) {
    return new Promise((resolve, reject) => {
      if (!contextValid) return reject(new Error("扩展上下文已失效，请重新加载扩展并刷新页面"));
      try {
        chrome.runtime.sendMessage(message, (response) => {
          const error = chrome.runtime.lastError;
          if (error) {
            contextValid = false;
            reject(new Error(error.message));
            return;
          }
          resolve(response);
        });
      } catch (error) {
        contextValid = false;
        reject(error);
      }
    });
  }

  function storageGet(defaults) {
    return new Promise((resolve) => chrome.storage.local.get(defaults, resolve));
  }

  function storageSet(values) {
    return new Promise((resolve) => chrome.storage.local.set(values, resolve));
  }

  function createTemplate() {
    const wrapper = document.createElement("div");
    wrapper.className = "panel";
    wrapper.innerHTML = `
      <header class="header" id="dragHandle">
        <span class="live-dot" id="liveDot" aria-hidden="true"></span>
        <div class="brand">
          <div class="brand-line"><strong>Football Betting OneShot</strong></div>
          <small id="modelLine">实时EV · 只读候选层</small>
        </div>
        <button class="icon-button" id="collapse" type="button" aria-label="收起悬浮窗">—</button>
        <button class="icon-button" id="close" type="button" aria-label="隐藏悬浮窗">×</button>
      </header>
      <main class="body">
        <section class="match-card">
          <div class="match-name" id="matchName">等待比赛数据</div>
          <div class="match-meta"><span id="matchMeta">—</span><span id="quoteCount">0个已核验报价</span></div>
        </section>

        <section class="section" aria-labelledby="contractTitle">
          <div class="section-title"><strong id="contractTitle">盘口合约</strong><span class="badge" id="contractType">未选择</span></div>
          <div class="field"><label for="market">玩法类别</label><select id="market"></select></div>
          <div class="matrix-head contract-matrix-head"><span>盘口选项</span><small id="contractOptionCount">0个报价</small></div>
          <div class="contract-grid" id="contractGrid" role="group" aria-label="盘口选项与实时赔率"></div>
          <div class="sr-only-selectors" hidden aria-hidden="true">
            <select id="line" tabindex="-1"></select>
            <select id="selection" tabindex="-1"></select>
          </div>
        </section>

        <section class="section" aria-labelledby="probTitle">
          <div class="section-title"><strong id="probTitle">模型概率</strong><span class="badge" id="probSource">等待分析</span></div>
          <div class="grid-2">
            <div class="field"><label for="pointProb">点估计</label><div class="input-wrap"><input id="pointProb" type="number" min="0.01" max="99.99" step="0.01" placeholder="分析后自动赋值" readonly><span class="suffix">%</span></div></div>
            <div class="field"><label for="conservativeProb">保守边界</label><div class="input-wrap"><input id="conservativeProb" type="number" min="0.01" max="99.99" step="0.01" placeholder="分析后自动赋值" readonly><span class="suffix">%</span></div></div>
          </div>
          <div class="grid-2">
            <div class="field"><label for="minimumEv">保守EV执行线</label><div class="input-wrap"><input id="minimumEv" type="number" min="0" max="100" step="0.1" value="0" readonly><span class="suffix">%</span></div></div>
            <div class="field"><label for="freshness">报价时效</label><div class="input-wrap"><input id="freshness" type="number" min="1" max="300" step="1" value="15" readonly><span class="suffix">秒</span></div></div>
          </div>
          <div class="check-row">
            <input id="confirmed" type="checkbox" disabled>
            <label class="check-label" for="confirmed">由当前分析报告自动确认；无有效报告值时固定空仓</label>
          </div>
        </section>

        <section class="section" aria-labelledby="riskTitle">
          <div class="section-title"><strong id="riskTitle">资金约束</strong><span class="badge">固定小额</span></div>
          <div class="grid-2">
            <div class="field"><label for="bankroll">模型余额</label><div class="input-wrap"><input id="bankroll" type="number" min="0.01" step="0.01" readonly><span class="suffix">元</span></div></div>
            <div class="field"><label for="dailyExposure">当前暴露</label><div class="input-wrap"><input id="dailyExposure" type="number" min="0" step="0.01" readonly><span class="suffix">元</span></div></div>
          </div>
        </section>

        <section class="metrics" aria-label="实时计算结果">
          <div class="metric"><small>当前十进制价</small><strong id="odds">—</strong></div>
          <div class="metric"><small>点估计EV</small><strong id="pointEv">—</strong></div>
          <div class="metric"><small>保守EV</small><strong id="conservativeEv">—</strong></div>
          <div class="metric"><small>最低可接受价</small><strong id="minimumOdds">—</strong></div>
          <div class="metric"><small>报价年龄</small><strong id="quoteAge">—</strong></div>
          <div class="metric"><small>凯利诊断</small><strong id="kelly">—</strong></div>
        </section>

        <section class="decision" id="decision" aria-live="polite" aria-atomic="true">
          <div class="decision-title" id="decisionTitle">等待比赛分析</div>
          <div class="decision-reason" id="decisionReason">分析完成后，概率与合约会按比赛ID自动同步。</div>
        </section>

        <section class="stake-card">
          <div class="stake-copy"><small>候选金额</small><strong id="stakeNote">未通过价格与风险闸门</strong></div>
          <div class="stake-amount zero" id="stake">¥0</div>
        </section>
        <div class="footer"><b>不点击赔率 · 不提交订单 · 不自动锁单</b><br>只有明确说“锁单/已下单”后才更新项目状态</div>
      </main>`;
    return wrapper;
  }

  function bindUi() {
    const ids = [
      "liveDot", "modelLine", "collapse", "close", "dragHandle", "matchName", "matchMeta", "quoteCount",
      "contractType", "market", "line", "selection", "contractOptionCount", "contractGrid",
      "probSource", "pointProb", "conservativeProb", "minimumEv", "freshness",
      "confirmed", "bankroll", "dailyExposure", "odds", "pointEv", "conservativeEv", "minimumOdds", "quoteAge",
      "kelly", "decision", "decisionTitle", "decisionReason", "stake", "stakeNote"
    ];
    ui = Object.fromEntries(ids.map((id) => [id, shadow.getElementById(id)]));
  }

  function setOptions(select, rows, selectedValue, labelFn) {
    select.replaceChildren();
    if (!rows.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "暂无可用数据";
      select.append(option);
      return "";
    }
    for (const row of rows) {
      const option = document.createElement("option");
      option.value = row.value;
      option.textContent = labelFn(row);
      select.append(option);
    }
    select.value = rows.some((row) => row.value === selectedValue) ? selectedValue : rows[0].value;
    return select.value;
  }

  function marketFamily(quote) {
    const name = String(quote?.market_name || "").trim();
    const compact = name.replace(/[\s_\-—]/g, "");
    if (compact === "全场波胆" || compact === "全场高倍波胆") {
      return { key: "family|correct_score|full_time", label: "全场波胆" };
    }
    if (compact === "上半场波胆" || compact === "上半场高倍波胆") {
      return { key: "family|correct_score|first_half", label: "上半场波胆" };
    }
    return {
      key: [quote?.market_code || "", quote?.child_market_code || "", name].join("|"),
      label: name || `玩法 ${quote?.market_code || ""}`,
    };
  }

  function marketKey(quote) {
    return marketFamily(quote).key;
  }

  function marketLabel(quote) {
    return marketFamily(quote).label;
  }

  function lineKey(quote) {
    const line = String(quote.handicap_line ?? "").trim();
    if (line) return line.replace(":", "-");
    if (marketKey(quote).startsWith("family|correct_score|")) {
      const selection = selectionKey(quote);
      if (/^\d+[:\-]\d+$/.test(selection)) return selection.replace(":", "-");
      if (selection.toLowerCase() === "other") return "其他比分";
    }
    return line;
  }

  function selectionKey(quote) {
    return String(quote.selection_code || quote.selection_name || "").trim();
  }

  function numericLine(value) {
    const text = String(value ?? "").trim();
    if (!text) return null;
    const parts = text.split("/").map(Number);
    if (parts.some((part) => !Number.isFinite(part))) return null;
    return parts.length === 2 ? (parts[0] + parts[1]) / 2 : (parts.length === 1 ? parts[0] : null);
  }

  function contractTypeFor(quote) {
    if (!quote) return { value: null, label: "未选择" };
    const name = String(quote.market_name || "");
    if (name.includes("波胆") || name.includes("比分")) return { value: "binary_no_push", label: "比分单选" };
    if (name.includes("独赢") || name.includes("胜平负")) return { value: "three_way_selection", label: "三项单选" };
    if (name.includes("大小") || name.includes("让球")) {
      const line = numericLine(quote.handicap_line);
      if (line === null || Math.abs(Math.abs(line % 1) - 0.5) > 0.0001) {
        return { value: null, label: "含走盘/半结算" };
      }
    }
    return { value: "binary_no_push", label: "无走盘二项" };
  }

  function selectedQuote() {
    const candidates = verifiedQuotes.filter((quote) =>
      marketKey(quote) === ui.market.value &&
      lineKey(quote) === ui.line.value &&
      selectionKey(quote) === ui.selection.value
    );
    const exactProfileQuote = currentRemoteProfile?.contract
      ? candidates.find((quote) => quoteMatchesContract(quote, currentRemoteProfile.contract))
      : null;
    if (exactProfileQuote) return exactProfileQuote;
    return candidates.sort((a, b) => {
      const timeDifference = Number(b.source_timestamp_ms || 0) - Number(a.source_timestamp_ms || 0);
      if (timeDifference) return timeDifference;
      return Number(b.inferred_decimal_odds || 0) - Number(a.inferred_decimal_odds || 0);
    })[0] || null;
  }

  function quoteMatchesContract(quote, contract) {
    if (!quote || !contract) return false;
    const exact = (field) => !String(contract[field] ?? "").trim() || String(quote[field] ?? "").trim() === String(contract[field]).trim();
    return exact("market_code") && exact("market_name") && exact("child_market_code") && exact("market_id") &&
      lineKey(quote) === String(contract.handicap_line ?? "").trim() &&
      ((contract.selection_code && String(quote.selection_code || "").trim() === String(contract.selection_code).trim()) ||
       (!contract.selection_code && contract.selection_name && String(quote.selection_name || "").trim() === String(contract.selection_name).trim()));
  }

  function selectorProfileFromRemote(profile) {
    if (!profile?.active || !profile.contract) return {};
    const quote = verifiedQuotes.find((row) => quoteMatchesContract(row, profile.contract));
    if (!quote) return {};
    return { market: marketKey(quote), line: lineKey(quote), selection: selectionKey(quote) };
  }

  function isCorrectScoreMarket(value = ui.market?.value) {
    return String(value || "").startsWith("family|correct_score|");
  }

  function betterDisplayQuote(current, candidate) {
    if (!current) return candidate;
    const timeDifference = Number(candidate.source_timestamp_ms || 0) - Number(current.source_timestamp_ms || 0);
    if (timeDifference > 0) return candidate;
    if (timeDifference < 0) return current;
    return Number(candidate.inferred_decimal_odds || 0) > Number(current.inferred_decimal_odds || 0) ? candidate : current;
  }

  function scoreSortValue(quote) {
    const line = lineKey(quote);
    const match = line.match(/^(\d+)-(\d+)$/);
    if (!match) return [999, 999, line];
    return [Number(match[1]), Number(match[2]), line];
  }

  function optionSortValue(quote) {
    if (isCorrectScoreMarket()) return scoreSortValue(quote);
    const line = lineKey(quote);
    const numeric = numericLine(line);
    const selection = selectionKey(quote);
    const selectionOrder = { "1": 0, "Home": 0, "X": 1, "Draw": 1, "2": 2, "Away": 2, "Over": 3, "Under": 4 };
    return [numeric ?? 999, selectionOrder[selection] ?? 20, `${line}|${selection}`];
  }

  function rebuildContractMatrix(marketQuotes) {
    ui.contractGrid.replaceChildren();
    ui.contractGrid.classList.toggle("score-mode", isCorrectScoreMarket());
    const optionMap = new Map();
    for (const quote of marketQuotes) {
      const key = `${lineKey(quote)}|${selectionKey(quote)}`;
      optionMap.set(key, betterDisplayQuote(optionMap.get(key), quote));
    }
    const options = [...optionMap.values()].sort((a, b) => {
      const left = optionSortValue(a);
      const right = optionSortValue(b);
      return left[0] - right[0] || left[1] - right[1] || String(left[2]).localeCompare(String(right[2]), "zh-CN", { numeric: true });
    });
    ui.contractOptionCount.textContent = `${options.length}个报价`;

    for (const quote of options) {
      const button = document.createElement("button");
      const line = lineKey(quote);
      const selection = selectionKey(quote);
      const selectionLabel = String(quote.selection_name || quote.selection_code || "").trim();
      const scoreMarket = isCorrectScoreMarket();
      const selected = line === ui.line.value && selection === ui.selection.value;
      button.type = "button";
      button.className = `contract-option${selected ? " selected" : ""}`;
      button.dataset.line = line;
      button.dataset.selection = selection;
      button.setAttribute("aria-pressed", selected ? "true" : "false");
      button.setAttribute("aria-label", `${line ? `${line}，` : ""}${selectionLabel}，赔率 ${Number(quote.inferred_decimal_odds).toFixed(2)}`);

      const primary = document.createElement("strong");
      primary.textContent = scoreMarket ? line : (line || selectionLabel);
      const detail = document.createElement("small");
      detail.textContent = scoreMarket || !line
        ? `@${Number(quote.inferred_decimal_odds).toFixed(2)}`
        : `${selectionLabel} · @${Number(quote.inferred_decimal_odds).toFixed(2)}`;
      button.append(primary, detail);
      button.addEventListener("click", () => {
        rebuildContractSelectors({ market: ui.market.value, line, selection });
        scheduleSaveAndReprice();
      });
      ui.contractGrid.append(button);
    }
  }

  function rebuildContractSelectors(profile = {}) {
    const marketMap = new Map();
    for (const quote of verifiedQuotes) {
      const key = marketKey(quote);
      if (!marketMap.has(key)) marketMap.set(key, quote);
    }
    const priority = (quote) => {
      const name = marketLabel(quote);
      if (name === "全场独赢") return 0;
      if (name === "全场让球") return 1;
      if (name === "全场大小") return 2;
      if (name === "全场波胆") return 3;
      if (name === "上半场波胆") return 4;
      return 20;
    };
    const markets = [...marketMap.entries()]
      .map(([value, quote]) => ({
        value,
        quote,
        lineCount: new Set(verifiedQuotes.filter((row) => marketKey(row) === value).map(lineKey)).size,
      }))
      .sort((a, b) => priority(a.quote) - priority(b.quote) || marketLabel(a.quote).localeCompare(marketLabel(b.quote), "zh-CN"));
    const preferredMarket = profile.market || ui.market?.value || markets.find((row) => marketLabel(row.quote) === "全场大小")?.value;
    setOptions(ui.market, markets, preferredMarket, (row) => `${marketLabel(row.quote)} · ${row.lineCount}线`);

    const marketQuotes = verifiedQuotes.filter((quote) => marketKey(quote) === ui.market.value);
    const lines = [...new Set(marketQuotes.map(lineKey))]
      .map((value) => ({ value }))
      .sort((a, b) => String(a.value).localeCompare(String(b.value), "zh-CN", { numeric: true }));
    setOptions(ui.line, lines, profile.line ?? ui.line?.value, (row) => row.value || "无盘口线");

    const lineQuotes = marketQuotes.filter((quote) => lineKey(quote) === ui.line.value);
    const selectionMap = new Map();
    for (const quote of lineQuotes) {
      const key = selectionKey(quote);
      const existing = selectionMap.get(key);
      if (!existing || Number(quote.source_timestamp_ms || 0) > Number(existing.source_timestamp_ms || 0) ||
          (Number(quote.source_timestamp_ms || 0) === Number(existing.source_timestamp_ms || 0) && Number(quote.inferred_decimal_odds || 0) > Number(existing.inferred_decimal_odds || 0))) {
        selectionMap.set(key, quote);
      }
    }
    const selections = [...selectionMap.entries()].map(([value, quote]) => ({ value, quote }));
    setOptions(ui.selection, selections, profile.selection || ui.selection?.value, (row) =>
      `${String(row.quote.selection_name || row.quote.selection_code).trim()}  @${Number(row.quote.inferred_decimal_odds).toFixed(2)}`
    );
    rebuildContractMatrix(marketQuotes);
    const type = contractTypeFor(selectedQuote());
    ui.contractType.textContent = type.label;
  }

  function numberFromInput(element) {
    const value = Number(element.value);
    return Number.isFinite(value) ? value : null;
  }

  function percentText(value) {
    return Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%` : "—";
  }

  function updateMetricClass(element, value) {
    element.classList.remove("good", "bad");
    if (!Number.isFinite(value)) return;
    element.classList.add(value > 0 ? "good" : (value < 0 ? "bad" : ""));
  }

  function renderIdle(title, reason, tone = "warn") {
    ui.decision.className = `decision ${tone}`;
    ui.decisionTitle.textContent = title;
    ui.decisionReason.textContent = reason;
    ui.stake.textContent = "¥0";
    ui.stake.className = "stake-amount zero";
    ui.stakeNote.textContent = "未通过价格与风险闸门";
  }

  function renderResult(result) {
    const price = result.price || {};
    const ev = result.ev || {};
    const staking = result.staking || {};
    ui.odds.textContent = Number.isFinite(Number(price.decimal_odds)) ? Number(price.decimal_odds).toFixed(2) : "—";
    ui.pointEv.textContent = percentText(Number(ev.point_ev));
    ui.conservativeEv.textContent = percentText(Number(ev.conservative_ev));
    ui.minimumOdds.textContent = Number.isFinite(Number(ev.minimum_acceptable_decimal_odds)) ? Number(ev.minimum_acceptable_decimal_odds).toFixed(2) : "—";
    ui.quoteAge.textContent = Number.isFinite(Number(price.quote_age_ms)) ? `${(Number(price.quote_age_ms) / 1000).toFixed(1)}s` : "—";
    ui.kelly.textContent = Number.isFinite(Number(staking.diagnostic_full_kelly_fraction)) ? percentText(Number(staking.diagnostic_full_kelly_fraction)) : "—";
    updateMetricClass(ui.pointEv, Number(ev.point_ev));
    updateMetricClass(ui.conservativeEv, Number(ev.conservative_ev));

    const [title, tone] = STATUS_COPY[result.decision_status] || [result.decision_status || "等待计算", "warn"];
    ui.decision.className = `decision ${tone}`;
    ui.decisionTitle.textContent = title;
    ui.decisionReason.textContent = result.reason || "—";
    const stake = Number(staking.suggested_stake || 0);
    ui.stake.textContent = `¥${stake.toFixed(0)}`;
    ui.stake.className = `stake-amount ${stake > 0 ? "" : "zero"}`;
    ui.stakeNote.textContent = stake > 0 ? "候选金额 · 仍需手动确认锁单" : "空仓或仅影子观察";
    ui.liveDot.classList.toggle("ok", Boolean(result.ok));
  }

  async function saveProfile() {
    if (!currentMatchId) return;
    const profile = {
      market: ui.market.value,
      line: ui.line.value,
      selection: ui.selection.value,
    };
    await storageSet({ [`${PROFILE_PREFIX}${currentMatchId}`]: profile });
  }

  function scheduleSaveAndReprice() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveProfile().catch(() => {}), 250);
    reprice().catch(() => {});
  }

  async function loadProfile(matchId) {
    const key = `${PROFILE_PREFIX}${matchId}`;
    const data = await storageGet({ [key]: {} });
    const profile = data[key] || {};
    return profile;
  }

  function clearAnalysisProfile(reason = "尚未发布当前比赛的有效分析配置") {
    currentRemoteProfile = null;
    ui.pointProb.value = "";
    ui.conservativeProb.value = "";
    ui.minimumEv.value = "0";
    ui.freshness.value = "15";
    ui.confirmed.checked = false;
    ui.probSource.textContent = "等待分析";
    renderIdle("等待比赛分析", reason, "warn");
  }

  function applyAnalysisProfile(profile) {
    if (!profile?.active) {
      clearAnalysisProfile(profile?.inactive_reason || "本次分析结论为空仓或配置不完整");
      return;
    }
    currentRemoteProfile = profile;
    ui.pointProb.value = (Number(profile.probability.point) * 100).toFixed(2);
    ui.conservativeProb.value = (Number(profile.probability.conservative) * 100).toFixed(2);
    ui.minimumEv.value = (Number(profile.execution?.minimum_conservative_ev || 0) * 100).toFixed(1);
    ui.freshness.value = Math.max(1, Number(profile.price?.max_quote_age_ms || 15000) / 1000).toFixed(0);
    ui.confirmed.checked = profile.probability?.confirmed_model_output === true;
    ui.probSource.textContent = `已同步 ${profile.model_version || ""}`.trim();
    if (verifiedQuotes.length) rebuildContractSelectors(selectorProfileFromRemote(profile));
  }

  async function refreshAnalysisProfile() {
    if (!currentMatchId || profileBusy) return;
    profileBusy = true;
    try {
      const response = await sendMessage({ type: "FBOS_EV_PROFILE", matchId: currentMatchId });
      if (!response?.ok) throw new Error(response?.error || "分析配置服务无响应");
      const result = response.data || {};
      if (!result.found || !result.profile) {
        clearAnalysisProfile("当前比赛尚未生成可绑定的模型概率");
        return;
      }
      if (result.profile.profile_id !== currentRemoteProfile?.profile_id) applyAnalysisProfile(result.profile);
    } catch (error) {
      clearAnalysisProfile(String(error.message || error));
    } finally {
      profileBusy = false;
    }
  }

  async function refreshModelState() {
    try {
      const response = await sendMessage({ type: "FBOS_MODEL_STATE" });
      if (!response?.ok) throw new Error(response?.error || "本地模型状态不可用");
      const state = response.data;
      ui.modelLine.textContent = `${state.model_version} · 报告自动赋值 · 实时EV`;
      if (state.bankroll?.current_balance != null) ui.bankroll.value = state.bankroll.current_balance;
      if (state.exposure?.current_open_exposure != null) ui.dailyExposure.value = state.exposure.current_open_exposure;
    } catch (error) {
      ui.modelLine.textContent = "本地模型状态未连接";
    }
  }

  async function refreshQuotes(forceProfile = null) {
    if (!currentMatchId || quoteBusy) return;
    quoteBusy = true;
    try {
      const response = await sendMessage({ type: "FBOS_BRIDGE_LATEST", matchId: currentMatchId });
      if (!response?.ok) throw new Error(response?.error || "赔率服务无响应");
      latestPayload = response.data;
      verifiedQuotes = (latestPayload.quotes || []).filter((quote) =>
        quote.odds_scale_verified === true && quote.market_status === 0 && quote.selection_status === 1
      );
      const metadata = (latestPayload.match_metadata || [])[0] || {};
      ui.matchName.textContent = metadata.home_name && metadata.away_name ? `${metadata.home_name} vs ${metadata.away_name}` : `比赛 ${currentMatchId}`;
      ui.matchMeta.textContent = metadata.tournament_name || "赛事信息待同步";
      ui.quoteCount.textContent = `${verifiedQuotes.length}个已核验报价`;
      const remoteSelector = selectorProfileFromRemote(currentRemoteProfile);
      rebuildContractSelectors(Object.keys(remoteSelector).length ? remoteSelector : (forceProfile || {}));
      ui.liveDot.classList.add("ok");
    } catch (error) {
      ui.liveDot.classList.remove("ok");
      renderIdle("本地桥接未连接", String(error.message || error), "bad");
    } finally {
      quoteBusy = false;
    }
  }

  async function reprice() {
    if (!currentMatchId || repriceBusy) return;
    const quote = selectedQuote();
    if (!quote) return renderIdle("请选择盘口", "只显示已通过赔率尺度核验的开放报价。");
    if (!currentRemoteProfile?.active || !quoteMatchesContract(quote, currentRemoteProfile.contract)) {
      return renderIdle("该盘口未赋值", "只对本场赛前分析确定的主维度计算EV；切换到报告绑定的盘口即可。", "warn");
    }
    const type = contractTypeFor(quote);
    ui.contractType.textContent = type.label;
    if (!type.value) {
      return renderIdle("该盘口需完整亚洲结算", "整数盘和四分之一盘不能用简单EV公式，当前悬浮窗不会给出金额。", "warn");
    }
    const point = numberFromInput(ui.pointProb);
    const conservative = numberFromInput(ui.conservativeProb);
    if (!(point > 0 && point < 100 && conservative > 0 && conservative <= point)) {
      return renderIdle("请输入有效模型概率", "保守概率必须大于0且不高于点估计；这里不能用市场隐含概率代替模型概率。", "warn");
    }
    const bankroll = numberFromInput(ui.bankroll);
    const exposure = numberFromInput(ui.dailyExposure);
    if (!(bankroll > 0 && exposure >= 0)) {
      return renderIdle("资金参数无效", "模型余额必须大于0，当前暴露不能为负。", "warn");
    }

    const request = {
      schema_version: "1.0",
      validation_only: !ui.confirmed.checked,
      contract: {
        match_id: currentMatchId,
        market_code: String(quote.market_code || ""),
        market_name: String(quote.market_name || ""),
        child_market_code: String(quote.child_market_code || ""),
        market_id: String(quote.market_id || ""),
        handicap_line: String(quote.handicap_line ?? ""),
        selection_code: String(quote.selection_code || ""),
        selection_name: String(quote.selection_name || ""),
        contract_type: type.value,
      },
      probability: {
        point: point / 100,
        conservative: conservative / 100,
        confirmed_model_output: ui.confirmed.checked,
        source: currentRemoteProfile?.probability?.source || "missing_analysis_profile",
        calibration_status: currentRemoteProfile?.probability?.calibration_status || "unconfirmed",
      },
      price: {
        source: "bridge",
        max_quote_age_ms: Math.max(1000, Number(ui.freshness.value || 15) * 1000),
      },
      execution: {
        minimum_conservative_ev: Math.max(0, Number(ui.minimumEv.value || 0) / 100),
      },
      staking: {
        bankroll,
        current_daily_exposure: exposure,
        daily_exposure_cap_pct: 0.05,
        single_match_cap_pct: 0.05,
        fixed_stake_min: 2,
        fixed_stake_max: 3,
        currency: "CNY",
      },
    };

    repriceBusy = true;
    try {
      const response = await sendMessage({ type: "FBOS_EV_REPRICE", request });
      if (!response?.ok) throw new Error(response?.error || "EV服务无响应");
      renderResult(response.data);
    } catch (error) {
      renderIdle("EV服务未连接", String(error.message || error), "bad");
    } finally {
      repriceBusy = false;
    }
  }

  function bindEvents() {
    for (const element of [ui.market, ui.line, ui.selection]) {
      element.addEventListener("change", () => {
        if (element === ui.market) rebuildContractSelectors({ market: ui.market.value });
        else if (element === ui.line) rebuildContractSelectors({ market: ui.market.value, line: ui.line.value });
        scheduleSaveAndReprice();
      });
    }
    ui.collapse.addEventListener("click", async () => {
      const collapsed = !shadow.querySelector(".panel").classList.toggle("collapsed") ? false : true;
      ui.collapse.textContent = collapsed ? "+" : "—";
      ui.collapse.setAttribute("aria-label", collapsed ? "展开悬浮窗" : "收起悬浮窗");
      await storageSet({ overlayCollapsed: collapsed });
    });
    ui.close.addEventListener("click", async () => {
      host.style.display = "none";
      await storageSet({ overlayEnabled: false });
    });

    let drag = null;
    ui.dragHandle.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button")) return;
      const rect = host.getBoundingClientRect();
      drag = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      ui.dragHandle.setPointerCapture(event.pointerId);
    });
    ui.dragHandle.addEventListener("pointermove", (event) => {
      if (!drag) return;
      const left = Math.max(0, Math.min(window.innerWidth - host.offsetWidth, event.clientX - drag.x));
      const top = Math.max(0, Math.min(window.innerHeight - 48, event.clientY - drag.y));
      host.style.left = `${left}px`;
      host.style.top = `${top}px`;
      host.style.right = "auto";
    });
    ui.dragHandle.addEventListener("pointerup", async (event) => {
      if (!drag) return;
      drag = null;
      ui.dragHandle.releasePointerCapture(event.pointerId);
      await storageSet({ overlayPosition: { left: host.style.left, top: host.style.top } });
    });
  }

  async function switchMatch(matchId) {
    currentMatchId = matchId;
    verifiedQuotes = [];
    latestPayload = null;
    currentRemoteProfile = null;
    clearAnalysisProfile();
    const profile = await loadProfile(matchId);
    await refreshModelState();
    await refreshAnalysisProfile();
    await refreshQuotes(profile);
    await reprice();
  }

  function startTimers() {
    clearInterval(quoteTimer);
    clearInterval(repriceTimer);
    clearInterval(routeTimer);
    clearInterval(profileTimer);
    quoteTimer = setInterval(() => refreshQuotes().catch(() => {}), QUOTE_REFRESH_MS);
    repriceTimer = setInterval(() => reprice().catch(() => {}), REPRICE_MS);
    profileTimer = setInterval(() => refreshAnalysisProfile().catch(() => {}), PROFILE_REFRESH_MS);
    routeTimer = setInterval(() => {
      const nextMatchId = matchIdFromUrl();
      if (nextMatchId && nextMatchId !== currentMatchId) switchMatch(nextMatchId).catch(() => {});
    }, 1000);
  }

  async function init() {
    if (location.protocol !== "https:" || location.hostname !== TARGET_HOST) return;
    const settings = await storageGet({ overlayEnabled: true, overlayCollapsed: false, overlayPosition: null });
    host = document.createElement("div");
    host.id = HOST_ID;
    shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    try {
      style.textContent = await fetch(chrome.runtime.getURL("overlay.css")).then((response) => response.text());
    } catch {
      style.textContent = ":host{position:fixed;z-index:2147483646;top:18px;right:18px}.panel{width:356px;background:#0d1729;color:white;padding:12px;border-radius:16px;font:13px system-ui}";
    }
    shadow.append(style, createTemplate());
    document.documentElement.append(host);
    bindUi();
    bindEvents();
    if (settings.overlayCollapsed) {
      shadow.querySelector(".panel").classList.add("collapsed");
      ui.collapse.textContent = "+";
    }
    if (settings.overlayPosition?.left && settings.overlayPosition?.top) {
      host.style.left = settings.overlayPosition.left;
      host.style.top = settings.overlayPosition.top;
      host.style.right = "auto";
    }
    host.style.display = settings.overlayEnabled ? "block" : "none";
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes.overlayEnabled) {
        host.style.display = changes.overlayEnabled.newValue ? "block" : "none";
        if (changes.overlayEnabled.newValue && currentMatchId) refreshQuotes().catch(() => {});
      }
    });
    const matchId = matchIdFromUrl();
    if (matchId) await switchMatch(matchId);
    else renderIdle("等待比赛页面", "打开具体比赛详情后会自动加载已核验盘口。", "warn");
    startTimers();
  }

  init().catch(() => {});
})();
