import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const BASE = "D:/MyProject/football-betting-oneshot";
const RUNTIME_PATH = `${BASE}/05_RUNTIME_STATE.json`;

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
}

function required(value, label) {
  if (value === null || value === undefined || value === "") throw new Error(`Missing required field: ${label}`);
  return value;
}

function nested(object, dotted, fallback = "未记录") {
  let value = object;
  for (const key of dotted.split(".")) value = value?.[key];
  return value === null || value === undefined || value === "" ? fallback : value;
}

function numericId(value, prefix) {
  const match = String(value ?? "").match(new RegExp(`^${prefix}(\\d+)$`, "i"));
  return match ? Number(match[1]) : null;
}

function normalize(value) {
  return String(value ?? "").replace(/[\s\-—_｜|.·]+/g, "").toLowerCase();
}

function scorePair(value) {
  const match = String(value ?? "").match(/(\d+)\s*[-:：]\s*(\d+)/);
  return match ? [Number(match[1]), Number(match[2])] : null;
}

function scoreDistance(predicted, actual) {
  const predictedPair = scorePair(predicted);
  const actualPair = scorePair(actual);
  if (!predictedPair || !actualPair) return null;
  return Math.abs(predictedPair[0] - actualPair[0]) + Math.abs(predictedPair[1] - actualPair[1]);
}

function splitQuarterLine(line) {
  const quarters = Math.round(Number(line) * 4);
  if (!Number.isFinite(quarters)) return [];
  return Math.abs(quarters) % 2 === 1
    ? [(quarters - 1) / 4, (quarters + 1) / 4]
    : [quarters / 4];
}

function legStatus(delta) {
  if (delta > 1e-9) return "win";
  if (delta < -1e-9) return "loss";
  return "push";
}

function combineLegs(statuses) {
  if (!statuses.length) return "not_evaluable";
  if (statuses.every((item) => item === "win")) return "win";
  if (statuses.every((item) => item === "loss")) return "loss";
  if (statuses.every((item) => item === "push")) return "push";
  if (statuses.includes("win") && statuses.includes("push") && !statuses.includes("loss")) return "half_win";
  if (statuses.includes("loss") && statuses.includes("push") && !statuses.includes("win")) return "half_loss";
  return "not_evaluable";
}

function settlePrimaryContract(contract, score90m) {
  if (!contract || contract.explicit_unique !== true) return "not_counted";
  if (contract.scope !== "regulation_90m_plus_stoppage") return "not_evaluable";
  const score = scorePair(score90m);
  if (!score) return "not_evaluable";
  const [home, away] = score;
  const market = String(contract.market_type ?? "").toLowerCase();
  const selection = String(contract.selection ?? "").toLowerCase();
  if (market === "1x2") {
    const result = home > away ? "home" : home < away ? "away" : "draw";
    return selection === result ? "win" : "loss";
  }
  if (market === "btts") {
    const result = home > 0 && away > 0 ? "yes" : "no";
    return selection === result ? "win" : "loss";
  }
  if (market === "correct_score") {
    const predicted = scorePair(contract.score ?? contract.selection);
    return predicted && predicted[0] === home && predicted[1] === away ? "win" : "loss";
  }
  if (market === "total") {
    const total = home + away;
    const legs = splitQuarterLine(contract.line).map((line) => legStatus(selection === "over" ? total - line : line - total));
    return ["over", "under"].includes(selection) ? combineLegs(legs) : "not_evaluable";
  }
  if (market === "asian_handicap") {
    const selectedGoals = selection === "home" ? home : selection === "away" ? away : null;
    const otherGoals = selection === "home" ? away : selection === "away" ? home : null;
    if (selectedGoals === null) return "not_evaluable";
    return combineLegs(splitQuarterLine(contract.line).map((line) => legStatus(selectedGoals + line - otherGoals)));
  }
  if (market === "team_total") {
    const goals = contract.team === "home" ? home : contract.team === "away" ? away : null;
    if (goals === null || !["over", "under"].includes(selection)) return "not_evaluable";
    return combineLegs(splitQuarterLine(contract.line).map((line) => legStatus(selection === "over" ? goals - line : line - goals)));
  }
  return "not_evaluable";
}

function primarySettlementLabel(review) {
  const contract = review.audit?.primary_contract;
  if (!contract) return nested(review, "audit.primary_hit"); // schema 1.0 legacy records
  const status = settlePrimaryContract(contract, review.result.score_90m);
  const labels = {win: "是｜全赢", half_win: "半红", push: "走水", half_loss: "半黑", loss: "否｜全输", not_counted: "不可计入｜赛前未冻结唯一主维度", not_evaluable: "不可核验｜合约字段或结算时段不完整"};
  return labels[status] ?? labels.not_evaluable;
}

function nextDataRow(sheet, start = 4, end = 203) {
  const values = sheet.getRange(`A${start}:A${end}`).values.flat();
  let last = start - 1;
  values.forEach((value, index) => { if (value !== null && value !== undefined && value !== "") last = start + index; });
  if (last >= end) throw new Error(`No blank rows left on ${sheet.name}`);
  return last + 1;
}

function timestamp() {
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).formatToParts(new Date()).reduce((out, item) => ({ ...out, [item.type]: item.value }), {});
  return `${parts.year}${parts.month}${parts.day}_${parts.hour}${parts.minute}${parts.second}`;
}

function isoShanghai() {
  const now = new Date();
  const local = new Date(now.getTime() + 8 * 3600 * 1000).toISOString().replace("Z", "+08:00");
  return local;
}

async function main() {
  const reviewArg = required(argument("--review"), "--review");
  const reviewPath = path.isAbsolute(reviewArg) ? reviewArg : path.join(BASE, reviewArg);
  const review = JSON.parse(await fs.readFile(reviewPath, "utf8"));
  if (!["1.0", "1.1"].includes(review.schema_version)) throw new Error("Unsupported post-match review schema version");
  if (review.schema_version === "1.1" && !review.audit?.primary_contract) throw new Error("schema 1.1 requires audit.primary_contract");
  required(review.match?.home, "match.home"); required(review.match?.away, "match.away");
  required(review.result?.score_90m, "result.score_90m");
  if (!/^\d+-\d+$/.test(review.result.score_90m)) throw new Error("result.score_90m must use home-away format");
  if (!Array.isArray(review.result.sources) || review.result.sources.length < 2) throw new Error("At least two result sources are required");

  const runtime = JSON.parse(await fs.readFile(RUNTIME_PATH, "utf8"));
  const workbookOverride = argument("--workbook");
  const workbookRel = workbookOverride || required(runtime.latest_review_workbook, "runtime.latest_review_workbook");
  const workbookPath = path.isAbsolute(workbookRel) ? workbookRel : path.join(BASE, workbookRel);
  const noRuntimeUpdate = process.argv.includes("--no-runtime-update");
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
  const dashboard = workbook.worksheets.getItem("00_投注绩效仪表盘");
  const lockSheet = workbook.worksheets.getItem("01_锁单与结算明细");
  const signalSheet = workbook.worksheets.getItem("02_赛前信号与赛果归因");
  const timelineSheet = workbook.worksheets.getItem("03_时间轴与盘口验证");
  const rootSheet = workbook.worksheets.getItem("05_根因决策树与修正池");

  const existingPairs = signalSheet.getRange("B4:B203").values.flat().filter(Boolean).map(normalize);
  const targetPair = normalize(`${review.match.home}vs${review.match.away}`);
  if (existingPairs.some((value) => value.includes(targetPair) || targetPair.includes(value.replace(/^.*?｜/, "")))) {
    console.log(JSON.stringify({ status: "already_reviewed", match: `${review.match.home} vs ${review.match.away}`, workbook: workbookRel }));
    return;
  }

  const matchIds = signalSheet.getRange("A4:A203").values.flat().map((value) => numericId(value, "M")).filter(Number.isFinite);
  const nextMatchNumber = Math.max(0, ...matchIds) + 1;
  const matchId = `M${String(nextMatchNumber).padStart(3, "0")}`;
  const timelineId = `T${String(nextMatchNumber).padStart(3, "0")}`;
  const pairLabel = `${review.match.competition}｜${review.match.home} vs ${review.match.away}`;
  const sources = review.result.sources.join("；");
  const uniqueScore = nested(review, "pre_match.unique_score");
  const distance = scoreDistance(uniqueScore, review.result.score_90m);
  const scoreHit = distance === 0 ? "是" : "否";
  const requestedAdjacent = /^是/.test(String(nested(review, "audit.adjacent_pollution", "否")));
  const adjacentPollution = distance === 1 && requestedAdjacent
    ? nested(review, "audit.adjacent_pollution")
    : `否｜比分格距离${distance ?? "无法计算"}，不属于严格相邻误差`;

  const signalRow = [
    matchId, pairLabel,
    nested(review, "pre_match.cross_validation"), nested(review, "pre_match.market_nature"),
    uniqueScore, nested(review, "pre_match.primary_dimension"),
    nested(review, "pre_match.asian_direction"), nested(review, "pre_match.total_direction"), nested(review, "pre_match.btts"),
    review.result.score_90m, primarySettlementLabel(review), scoreHit,
    adjacentPollution, nested(review, "audit.tail_pollution"), nested(review, "audit.error_attribution"),
    nested(review, "audit.logic_classification"), nested(review, "audit.random_event"), nested(review, "audit.maximum_error_type"),
    nested(review, "pre_match.maximum_error_point"), nested(review, "audit.summary"),
    nested(review, "audit.model_effective_coefficient", 0), nested(review, "audit.valid_sample", 1),
  ];
  const signalWriteRow = nextDataRow(signalSheet);
  signalSheet.getRange(`A${signalWriteRow}:V${signalWriteRow}`).values = [signalRow];

  const timelineRow = [
    timelineId, `${matchId}｜${review.match.home} vs ${review.match.away}`,
    nested(review, "timeline.countdown"), nested(review, "timeline.compliance"), nested(review, "timeline.opening"),
    nested(review, "timeline.closing"), nested(review, "timeline.change"), nested(review, "timeline.triggers"),
    nested(review, "timeline.direction_result"), nested(review, "timeline.theory_validation"), nested(review, "timeline.final_validation"),
    nested(review, "timeline.completeness"), `${nested(review, "timeline.sources_note")}｜赛果双源：${sources}`,
  ];
  const timelineWriteRow = nextDataRow(timelineSheet);
  timelineSheet.getRange(`A${timelineWriteRow}:M${timelineWriteRow}`).values = [timelineRow];

  const rootRow = [
    `${matchId}｜${review.match.home}${review.result.score_90m}${review.match.away}`,
    nested(review, "root_cause.decision_audit"), nested(review, "root_cause.counterfactual"), nested(review, "root_cause.identifiability"),
    nested(review, "root_cause.modify_model"), nested(review, "root_cause.recommendation"), nested(review, "root_cause.convergence"),
    nested(review, "root_cause.maximum_error_type"), nested(review, "root_cause.status"), nested(review, "root_cause.priority"),
    null, null, null, null,
  ];
  const rootWriteRow = nextDataRow(rootSheet);
  rootSheet.getRange(`A${rootWriteRow}:J${rootWriteRow}`).values = [rootRow.slice(0, 10)];

  const settlementResults = [];
  for (const settlement of review.lock_settlements ?? []) {
    const openBets = runtime.exposure?.open_bets ?? [];
    const openBet = openBets.find((bet) => String(bet.bet_id ?? bet.id) === String(settlement.bet_id));
    if (!openBet) {
      settlementResults.push({ bet_id: settlement.bet_id, status: "skipped_not_in_open_bets" });
      continue;
    }
    const ids = lockSheet.getRange("A4:A203").values.flat();
    const offset = ids.findIndex((value) => String(value) === String(settlement.bet_id));
    if (offset < 0) {
      settlementResults.push({ bet_id: settlement.bet_id, status: "skipped_not_in_workbook" });
      continue;
    }
    const row = offset + 4;
    lockSheet.getRange(`I${row}:K${row}`).values = [[review.result.score_90m, required(settlement.status, "settlement.status"), Number(required(settlement.actual_return, "settlement.actual_return"))]];
    lockSheet.getRange(`O${row}:P${row}`).values = [[nested(settlement, "logic_classification"), nested(settlement, "random_event")]];
    lockSheet.getRange(`T${row}`).values = [[nested(settlement, "note")]];
    runtime.bankroll.current_balance = Number(runtime.bankroll.current_balance) + Number(settlement.actual_return);
    runtime.exposure.open_bets = openBets.filter((bet) => String(bet.bet_id ?? bet.id) !== String(settlement.bet_id));
    settlementResults.push({ bet_id: settlement.bet_id, status: "settled" });
  }
  runtime.exposure.current_open_exposure = (runtime.exposure.open_bets ?? []).reduce((sum, bet) => sum + Number(bet.amount ?? bet.stake ?? 0), 0);

  const signalIds = signalSheet.getRange("A4:A203").values.flat().map((value) => numericId(value, "M")).filter(Number.isFinite);
  const reviewedCount = signalIds.length;
  const lockStatuses = lockSheet.getRange("J4:J203").values.flat();
  const settledCount = lockStatuses.filter((value) => ["红", "黑", "走水", "半红", "半黑"].includes(String(value))).length;
  const today = isoShanghai().slice(0, 10);
  dashboard.getRange("A3").values = [[`截至 ${today}｜有效复盘 ${reviewedCount} 场｜已结注单 ${settledCount} 场｜自动复盘已启用`]];
  dashboard.getRange("B5").values = [[`截至 ${today}`]];

  const addedSignalRow = signalSheet.getRange("A4:A203").values.flat().findIndex((value) => value === matchId) + 4;
  const addedTimelineRow = timelineSheet.getRange("A4:A203").values.flat().findIndex((value) => value === timelineId) + 4;
  const addedRootRow = rootSheet.getRange("A4:A203").values.flat().findIndex((value) => String(value).startsWith(`${matchId}｜`)) + 4;
  for (const [sheet, range, height] of [
    [signalSheet, `A${addedSignalRow}:V${addedSignalRow}`, 104],
    [timelineSheet, `A${addedTimelineRow}:M${addedTimelineRow}`, 96],
    [rootSheet, `A${addedRootRow}:J${addedRootRow}`, 108],
  ]) {
    const target = sheet.getRange(range); target.format.wrapText = true; target.format.verticalAlignment = "top"; target.format.rowHeight = height;
  }

  const sortedChecks = [
    ["signal", signalSheet.getRange("A4:A203").values.flat(), "M"],
    ["timeline", timelineSheet.getRange("A4:A203").values.flat(), "T"],
  ];
  for (const [label, values, prefix] of sortedChecks) {
    const ids = values.map((value) => numericId(value, prefix)).filter(Number.isFinite);
    if (!ids.every((value, index) => index === 0 || ids[index - 1] < value)) throw new Error(`${label} IDs are not strictly increasing`);
  }
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "postmatch formula error scan" });
  if (errors.ndjson && !errors.ndjson.includes('"matchCount":0') && !errors.ndjson.includes('"count":0')) console.log(`FORMULA_SCAN\n${errors.ndjson}`);

  const runId = timestamp();
  const safeCompetition = String(review.match.competition || "赛后").replace(/[<>:"/\\|?*]/g, "");
  const outputOverride = argument("--output");
  const outputRel = outputOverride || `data/postmatch_reviews/足彩复盘数据工作台_${runId}_${safeCompetition}赛后复盘.xlsx`;
  const outputPath = path.isAbsolute(outputRel) ? outputRel : `${BASE}/${outputRel}`;
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await (await SpreadsheetFile.exportXlsx(workbook)).save(outputPath);

  if (noRuntimeUpdate) {
    console.log(JSON.stringify({ status: "updated_test_copy", match_id: matchId, output: outputPath, settlements: settlementResults }));
    return;
  }

  runtime.model_version = "v0.18.1";
  runtime.updated_at = isoShanghai();
  runtime.latest_review_workbook = outputRel;
  runtime.latest_reviewed_matches = runtime.latest_reviewed_matches ?? [];
  runtime.latest_reviewed_matches.push({
    match: `${review.match.home} vs ${review.match.away}`,
    result_90m: review.result.score_90m,
    after_extra_time: review.result.after_extra_time ?? null,
    bet_locked: (review.lock_settlements ?? []).length > 0,
    review_classification: nested(review, "audit.logic_classification"),
    source_report: review.source_report ?? null,
  });
  runtime.postmatch_automation = {
    module_version: "v0.9.1", status: "event_driven_one_shot_postmatch_pipeline_enabled_periodic_polling_disabled",
    queue_builder: "scripts/postmatch_queue.py", schedule_builder: "scripts/postmatch_schedule.py", workbook_updater: "scripts/postmatch_workbook_update.mjs",
    dashboard_generator: "scripts/postmatch_dashboard.py", dashboard_latest: "data/postmatch_dashboard/latest.html",
    result_scope: "90分钟含伤停，不含加时和点球", minimum_result_sources: 2,
    standard_delay_minutes_after_kickoff: 135, single_leg_knockout_delay_minutes_after_kickoff: 195,
    maximum_result_retry_count: 1, result_retry_delay_minutes: 45, periodic_model_polling: false,
    automatic_betting: false, requires_explicit_lock_confirmation: true,
    last_updated_at: runtime.updated_at, last_match_id: matchId, last_result_90m: review.result.score_90m,
  };
  await fs.writeFile(RUNTIME_PATH, JSON.stringify(runtime, null, 2) + "\n", "utf8");
  console.log(JSON.stringify({ status: "updated", match_id: matchId, output: outputRel, settlements: settlementResults }));
}

export { combineLegs, scoreDistance, settlePrimaryContract, splitQuarterLine };

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  await main();
}
