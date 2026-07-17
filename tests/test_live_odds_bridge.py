import base64
import gzip
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from live_odds_bridge import (  # noqa: E402
    _allowed_origin,
    BridgeStore,
    BridgeValidationError,
    PersistentAnalysisQueue,
    make_handler,
    normalize_event,
    public_ev_profile,
    public_model_state,
    sanitize,
    validate_event,
)
import live_odds_bridge as bridge_module  # noqa: E402


def sample_event():
    return {
        "schema_version": "1.0",
        "captured_at": "2026-07-14T06:30:00.000Z",
        "source_type": "worker_message",
        "page_url": "https://user-pc-new.hl99yjjpf.com/#/details/5503037/3169/1?ms=0",
        "page_title": "match detail",
        "session_id": "test-session",
        "sequence": 1,
        "transport_meta": {"worker_url": "https://user-pc-new.hl99yjjpf.com/ws-worker.js"},
        "payload": {
            "cmd": "odds_update",
            "match_id": 5503037,
            "market": "asian_handicap",
            "odds": 1.91,
            "token": "must-not-be-stored",
            "account": {"balance": 9999},
        },
    }


class LiveOddsBridgeTests(unittest.TestCase):
    def test_verified_deep_snapshot_requires_all_model_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "data" / "fetch_runs" / "20260717_170000"
            run.mkdir(parents=True)
            snapshot = run / "20260717_170000_500_deep_2026-07-17_1362710.json"
            complete = {
                "shuju_id": 1362710,
                "ouzhi": {"bookmakers": [{}]},
                "yazhi": {"companies": [{}]},
                "rangqiu": {"companies": [{}]},
                "daxiao": {"companies": [{}]},
                "shuju": {"recent_form": {}},
                "touzhu": {"betfair": {}},
            }
            snapshot.write_text(json.dumps(complete), encoding="utf-8")
            with patch.object(bridge_module, "PROJECT_ROOT", root):
                self.assertEqual(
                    snapshot,
                    bridge_module._verified_deep_snapshot("1362710", "2026-07-17"),
                )
                complete["daxiao"]["companies"] = []
                snapshot.write_text(json.dumps(complete), encoding="utf-8")
                self.assertIsNone(
                    bridge_module._verified_deep_snapshot("1362710", "2026-07-17")
                )

    def test_non_500_match_does_not_publish_cloud_fallback(self):
        self.assertEqual(
            {"status": "not_applicable"},
            bridge_module._publish_deep_fallback({"id": "nowscore-123"}, "gh"),
        )

    def test_local_file_report_origin_can_read_loopback_reprice(self):
        self.assertTrue(_allowed_origin("null"))
        self.assertTrue(_allowed_origin("chrome-extension://test-extension"))
        self.assertFalse(_allowed_origin("https://example.com"))

    def test_overlay_is_shadow_dom_read_only_and_polls_local_reprice(self):
        source = (ROOT / "integrations" / "live_odds_bridge" / "chrome_extension" / "overlay.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("attachShadow({ mode: \"open\" })", source)
        self.assertIn("FBOS_EV_REPRICE", source)
        self.assertIn("REPRICE_MS = 1000", source)
        self.assertIn("marketFamily(quote).key", source)
        self.assertIn('family|correct_score|full_time', source)
        self.assertIn('family|correct_score|first_half', source)
        self.assertIn('return selection.replace(":", "-")', source)
        self.assertIn('<select id="market"></select>', source)
        self.assertIn('class="contract-grid"', source)
        self.assertIn('function rebuildContractMatrix', source)
        self.assertIn('aria-label="盘口选项与实时赔率"', source)
        self.assertIn('class="sr-only-selectors" hidden', source)
        self.assertNotIn('function rebuildMarketPicker', source)
        self.assertNotIn("盘口线 / 比分", source)
        self.assertIn('name.includes("波胆")', source)
        self.assertIn("explicit_lock_required", (ROOT / "scripts" / "live_ev_reprice.py").read_text(encoding="utf-8"))
        self.assertNotIn("document.querySelector", source)
        self.assertNotIn("WS_MSG_SEND", source)
        self.assertNotIn(".click()", source)

    def test_manifest_loads_ev_overlay_at_document_idle(self):
        manifest = json.loads(
            (ROOT / "integrations" / "live_odds_bridge" / "chrome_extension" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("0.9.4", manifest["version"])
        self.assertIn("https://gemini077.github.io/football-betting-oneshot/*", manifest["host_permissions"])
        overlay = next(item for item in manifest["content_scripts"] if "overlay.js" in item.get("js", []))
        self.assertEqual("document_idle", overlay["run_at"])

    def test_background_exposes_local_and_remote_analysis_profile_sync(self):
        source = (ROOT / "integrations" / "live_odds_bridge" / "chrome_extension" / "background.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('"/v1/reprice"', source)
        self.assertIn('"/v1/model-state"', source)
        self.assertIn('"/v1/latest"', source)
        self.assertIn('"/v1/ev-profile"', source)
        self.assertIn("FBOS_EV_PROFILE", source)
        self.assertIn("REMOTE_PROFILE_ROOT", source)
        self.assertIn("index.json", source)
        self.assertIn("sameTeamPair", source)
        self.assertIn("home_aliases", source)
        self.assertIn("competitionCompatible", source)
        self.assertIn("kickoffCompatible", source)
        self.assertIn("loadNewestAnalysisProfile", source)
        self.assertNotIn("user-pc-new.hl99yjjpf.com/#/", source)

    def test_overlay_auto_loads_analysis_profile_and_does_not_require_manual_probability(self):
        source = (ROOT / "integrations" / "live_odds_bridge" / "chrome_extension" / "overlay.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("refreshAnalysisProfile", source)
        self.assertIn("applyAnalysisProfile", source)
        self.assertIn('type: "FBOS_EV_PROFILE"', source)
        self.assertIn("homeName: currentMatchMetadata.home_name", source)
        self.assertIn("awayName: currentMatchMetadata.away_name", source)
        self.assertIn("tournamentName: currentMatchMetadata.tournament_name", source)
        self.assertIn("kickoffTimestamp: currentMatchMetadata.kickoff_timestamp", source)
        self.assertIn("GitHub", source)
        self.assertIn("分析后自动赋值", source)
        self.assertIn("clearAnalysisProfile", source)

    def test_public_model_state_exposes_model_risk_not_channel_account(self):
        state = public_model_state()
        self.assertTrue(state["ok"])
        self.assertIn("current_balance", state["bankroll"])
        self.assertFalse(state["contains_channel_account_data"])
        self.assertFalse(state["in_play_betting_enabled"])

    def test_public_ev_profile_rejects_path_traversal_and_returns_current_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "current").mkdir()
            profile = {
                "active": True,
                "match": {"match_id": "5503037"},
                "probability": {"point": 0.56, "conservative": 0.53},
                "execution_authorized": False,
            }
            (root / "current" / "5503037.json").write_text(json.dumps(profile), encoding="utf-8")
            result = public_ev_profile("5503037", profile_root=root)
            self.assertTrue(result["found"])
            self.assertEqual(0.56, result["profile"]["probability"]["point"])
            self.assertFalse(result["execution_authorized"])
            with self.assertRaises(BridgeValidationError):
                public_ev_profile("../../05_RUNTIME_STATE", profile_root=root)
    def test_content_script_handles_invalidated_extension_context(self):
        source = (ROOT / "integrations" / "live_odds_bridge" / "chrome_extension" / "content.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("try {", source)
        self.assertIn("disableInvalidContext", source)
        self.assertIn("document.removeEventListener(EVENT_NAME, handleBridgeEvent)", source)

    def test_main_hook_does_not_override_xhr_send_and_accepts_api_prefixes(self):
        source = (ROOT / "integrations" / "live_odds_bridge" / "chrome_extension" / "main-hook.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("XMLHttpRequest.prototype.send =", source)
        self.assertIn("parsed.pathname.endsWith(endpoint)", source)

    def test_normalizer_ignores_blank_match_metadata(self):
        event = sample_event()
        event["payload"] = {"cd": {"mid": "5503037", "mhs": "0", "mas": "0"}}
        rows = normalize_event(validate_event(event))
        self.assertFalse(any(row["record_type"] == "match_metadata" for row in rows))

    def test_sanitize_removes_credentials_and_account_fields(self):
        cleaned = sanitize({
            "match": 97,
            "password": "secret",
            "authorization": "Bearer abcdefghijklmnop",
            "nested": {"odds": 1.9, "balance": 100},
        })
        self.assertEqual(cleaned["match"], 97)
        self.assertNotIn("password", cleaned)
        self.assertNotIn("authorization", cleaned)
        self.assertEqual(cleaned["nested"], {"odds": 1.9})

    def test_sanitize_removes_user_info_and_user_id(self):
        cleaned = sanitize({
            "market": {"odds": 1.8},
            "UserCtr": {"user_info": {"userId": "private", "nickname": "private"}},
        })
        self.assertEqual(cleaned, {"market": {"odds": 1.8}, "UserCtr": {}})

    def test_validate_event_accepts_target_page_and_forces_shadow_flags(self):
        clean = validate_event(sample_event())
        self.assertEqual(
            clean["page_url"],
            "https://user-pc-new.hl99yjjpf.com/#/details/5503037/3169/1",
        )
        self.assertNotIn("token", clean["payload"])
        self.assertNotIn("account", clean["payload"])
        self.assertTrue(clean["analysis_input_only"])
        self.assertFalse(clean["lock_state_changed"])
        self.assertFalse(clean["bankroll_state_changed"])
        self.assertFalse(clean["in_play_betting_enabled"])

    def test_validate_event_rejects_other_hosts(self):
        event = sample_event()
        event["page_url"] = "https://example.com/match"
        with self.assertRaises(BridgeValidationError):
            validate_event(event)

    def test_validate_event_accepts_allowlisted_match_api_response(self):
        event = sample_event()
        event["source_type"] = "api_response"
        event["transport_meta"] = {
            "transport": "xmlhttprequest",
            "request_path": "/v1/w/matchDetail/getMatchDetailPB",
        }
        event["payload"] = {
            "data": {
                "mid": "5503037",
                "mhn": "Home",
                "man": "Away",
                "hpsData": [{"hpid": "2", "hpn": "Total Goals"}],
                "user_info": {"userId": "private"},
            }
        }
        clean = validate_event(event)
        self.assertNotIn("user_info", clean["payload"]["data"])
        rows = normalize_event(clean)
        self.assertTrue(any(row["record_type"] == "match_metadata" for row in rows))
        self.assertTrue(any(row["record_type"] == "market_definition" for row in rows))

    def test_validate_event_decodes_bounded_gzip_json_match_api_response(self):
        event = sample_event()
        event["source_type"] = "api_response"
        event["transport_meta"] = {
            "transport": "xmlhttprequest",
            "request_path": "/v1/w/matchDetail/getMatchOddsInfo1PB",
        }
        decoded = {
            "mid": "5503037",
            "mhn": "Home",
            "man": "Away",
            "hpsData": [{
                "mid": "5503037",
                "hpid": "2",
                "chpid": "2",
                "hpn": "Full Time Total",
                "ctsp": "1784015846984",
                "hl": [{
                    "hid": "market-1",
                    "hs": 0,
                    "hmt": 1,
                    "hv": "2.5",
                    "ol": [{
                        "oid": "selection-1",
                        "ot": "Over",
                        "otv": "Over 2.5",
                        "os": 1,
                        "ov": 193000,
                        "obv": 193000,
                        "ov2": "0.93",
                    }],
                }],
            }],
            "user_info": {"userId": "private"},
        }
        event["payload"] = {
            "code": 0,
            "data": base64.b64encode(gzip.compress(json.dumps(decoded).encode("utf-8"))).decode("ascii"),
        }
        clean = validate_event(event)
        self.assertEqual(clean["payload"]["_fbos_data_encoding"], "base64_gzip_json")
        self.assertNotIn("user_info", clean["payload"]["data"])
        rows = normalize_event(clean)
        self.assertTrue(any(row["record_type"] == "match_metadata" for row in rows))
        self.assertTrue(any(row["record_type"] == "market_definition" for row in rows))
        quote = next(row for row in rows if row["record_type"] == "odds_quote")
        self.assertEqual(quote["market_name"], "Full Time Total")
        self.assertEqual(quote["handicap_line"], "2.5")
        self.assertEqual(quote["inferred_decimal_odds"], 1.93)
        self.assertTrue(quote["odds_scale_verified"])

    def test_store_inherits_verified_ov_scale_for_correct_score_in_same_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BridgeStore(Path(tmp), stamp="20260714_170000")
            event = sample_event()
            event["source_type"] = "api_response"
            event["transport_meta"] = {
                "transport": "xmlhttprequest",
                "request_path": "/v1/w/matchDetail/getMatchOddsInfo1PB",
            }
            event["payload"] = {
                "data": {
                    "markets": [
                        {
                            "mid": "5507028", "hpid": "2", "chpid": "2", "hpn": "全场大小",
                            "ctsp": "1784015846984",
                            "hl": [{
                                "hid": "total-25", "hs": 0, "hmt": 1, "hv": "2.5",
                                "ol": [{"oid": "over", "ot": "Over", "otv": "大 2.5", "os": 1, "ov": 193000, "ov2": "0.93"}],
                            }],
                        },
                        {
                            "mid": "5507028", "hpid": "7", "chpid": "7", "hpn": "全场波胆",
                            "ctsp": "1784015846984",
                            "hl": [{
                                "hid": "score-11", "hs": 0, "hmt": 1, "hv": "1-1",
                                "ol": [{"oid": "score11", "ot": "1:1", "otv": "1-1", "os": 1, "ov": 650000}],
                            }],
                        },
                    ]
                }
            }
            store.record(validate_event(event))
            latest = store.latest("5507028", active_only=False)
            score = next(row for row in latest["quotes"] if row["market_code"] == "7")
            self.assertEqual(6.5, score["inferred_decimal_odds"])
            self.assertTrue(score["odds_scale_verified"])
            self.assertEqual("same_match_ov_field_peer_crosscheck", score["odds_scale_verification_basis"])

    def test_validate_event_rejects_user_api_response(self):
        event = sample_event()
        event["source_type"] = "api_response"
        event["transport_meta"] = {"request_path": "/user/amount"}
        event["payload"] = {"balance": 51.43}
        with self.assertRaises(BridgeValidationError):
            validate_event(event)

    def test_validate_event_rejects_dom_snapshots(self):
        event = sample_event()
        event["source_type"] = "dom_snapshot"
        event["payload"] = {"rows": [{"text": "51.43"}]}
        with self.assertRaises(BridgeValidationError):
            validate_event(event)

    def test_validate_event_rejects_echoed_outbound_ws_message(self):
        event = sample_event()
        event["payload"] = {
            "cmd": "js_code",
            "data": {
                "fun": "window.postMessage",
                "param": [{"cmd": "WS_MSG_SEND", "data": {"mid": "5503037"}}],
            },
        }
        with self.assertRaises(BridgeValidationError):
            validate_event(event)

    def test_normalize_inbound_market_update(self):
        event = sample_event()
        event["payload"] = {
            "cmd": "js_code",
            "data": {
                "fun": "wslog.send_msg",
                "param": [
                    "WS---R:",
                    json.dumps({
                        "cd": {
                            "hls2": {
                                "1100438": [{
                                    "hpid": "1100438",
                                    "hid": "m1",
                                    "mid": "5503037",
                                    "hs": 0,
                                    "hv": "",
                                    "ol": [{
                                        "oid": "o1", "ot": "1", "os": 1,
                                        "ov": "180000", "obv": "180000", "ov2": "0.80",
                                    }],
                                    "t": "1784013649370",
                                }],
                            }
                        }
                    }),
                ],
            },
        }
        clean = validate_event(event)
        rows = normalize_event(clean)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["record_type"], "odds_quote")
        self.assertEqual(rows[0]["match_id"], "5503037")
        self.assertEqual(rows[0]["market_code"], "1100438")
        self.assertEqual(rows[0]["inferred_decimal_odds"], 1.8)
        self.assertTrue(rows[0]["odds_scale_verified"])

    def test_normalize_correct_score_uses_selection_as_missing_websocket_line(self):
        event = sample_event()
        event["payload"] = {
            "cd": {
                "hls2": {
                    "1100484": [{
                        "hpid": "1100484",
                        "hid": "high-score-market",
                        "mid": "5507028",
                        "hs": 0,
                        "hv": "",
                        "ol": [{
                            "oid": "score-5-1", "ot": "5:1", "os": 1,
                            "ov": "2600000", "ov2": "25.00",
                        }],
                    }],
                }
            }
        }
        rows = normalize_event(validate_event(event))
        self.assertEqual(1, len(rows))
        self.assertEqual("5-1", rows[0]["handicap_line"])
        self.assertEqual("5:1", rows[0]["selection_code"])

    def test_store_deduplicates_and_writes_datetime_named_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BridgeStore(Path(tmp), stamp="20260714_143000")
            clean = validate_event(sample_event())
            stored_first, _ = store.record(clean)
            stored_second, _ = store.record(clean)
            self.assertTrue(stored_first)
            self.assertFalse(stored_second)
            self.assertEqual(store.stored, 1)
            self.assertEqual(store.deduplicated, 1)
            self.assertEqual(store.events_path.name, "20260714_143000_live_odds_events.jsonl")
            self.assertFalse(store.events_path.exists())
            manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "read_only_shadow")
            self.assertFalse(manifest["lock_state_changed"])
            self.assertFalse(manifest["bankroll_state_changed"])
            self.assertFalse(manifest["in_play_betting_enabled"])
            self.assertFalse(manifest["raw_event_storage"])

    def test_store_writes_only_changed_normalized_market_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BridgeStore(Path(tmp), stamp="20260714_143001")
            event = sample_event()
            event["payload"] = {"cd": {"hls2": {"115": [{
                "hpid": "115", "mid": "5503037", "hv": "2.5", "hs": 0,
                "ol": [{"oid": "o1", "ot": "Over", "os": 1, "ov": "193000", "ov2": "0.93"}],
            }]}}}
            first = validate_event(event)
            second = dict(first)
            second["captured_at"] = "2026-07-14T06:30:02.000Z"
            second["sequence"] = 2
            self.assertTrue(store.record(first)[0])
            self.assertFalse(store.record(second)[0])
            self.assertEqual(1, len(store.normalized_path.read_text(encoding="utf-8").splitlines()))

    def test_store_exposes_latest_quote_by_match_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BridgeStore(Path(tmp), stamp="20260714_143050")
            event = sample_event()
            event["payload"] = {
                "cd": {
                    "hls2": {
                        "115": [{
                            "hpid": "115", "mid": "5503037", "hv": "5", "hs": 0,
                            "ol": [{"oid": "o1", "ot": "Over", "os": 1, "ov": "217000"}],
                        }]
                    }
                }
            }
            store.record(validate_event(event))
            latest = store.latest("5503037")
            self.assertEqual(latest["quote_count"], 1)
            self.assertEqual(latest["quotes"][0]["inferred_decimal_odds"], 2.17)
            self.assertFalse(latest["in_play_betting_enabled"])
            self.assertTrue(latest["active_only"])

    def test_http_receiver_accepts_extension_origin_and_rejects_page_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BridgeStore(Path(tmp), stamp="20260714_143100")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/events"
                body = json.dumps(sample_event()).encode("utf-8")
                request = Request(
                    endpoint,
                    data=body,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "chrome-extension://test-extension-id",
                    },
                )
                with urlopen(request, timeout=3) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertTrue(result["ok"])
                self.assertEqual(store.stored, 1)

                blocked = Request(
                    endpoint,
                    data=body,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "https://user-pc-new.hl99yjjpf.com",
                    },
                )
                with self.assertRaises(Exception):
                    urlopen(blocked, timeout=3)
                self.assertEqual(store.rejected, 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_workspace_selection_queues_local_analysis_without_github(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BridgeStore(Path(tmp), stamp="20260716_190000")
            selection_path = Path(tmp) / "selected_matches.json"
            launched = []
            launcher = lambda match: launched.append(match) or {"status": "queued", "pid": 123}
            with patch.object(bridge_module, "WORKSPACE_SELECTION_PATH", selection_path):
                server = ThreadingHTTPServer(
                    ("127.0.0.1", 0), make_handler(store, analysis_launcher=launcher)
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/analysis-selections"
                    payload = {"match": {
                        "id": "2040514", "home": "主队", "away": "客队",
                        "business_date": "2026-07-16", "kickoff": "2026-07-17 03:00",
                    }}
                    request = Request(
                        endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
                        headers={"Content-Type": "application/json", "Origin": "https://gemini077.github.io"},
                    )
                    with urlopen(request, timeout=3) as response:
                        result = json.loads(response.read().decode("utf-8"))
                        self.assertEqual(202, response.status)
                    self.assertTrue(result["ok"])
                    self.assertTrue(result["automatic_analysis"])
                    self.assertEqual("queued", result["analysis_job"]["status"])
                    self.assertEqual("2040514", launched[0]["id"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)

    def test_persistent_analysis_queue_keeps_fifo_jobs_and_deduplicates_active_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            launched = []
            queue = PersistentAnalysisQueue(
                Path(tmp) / "queue.json",
                launcher=lambda match: launched.append(match["id"]) or {"status": "queued"},
                retry_delays=(0.0,),
            )
            first = queue.enqueue({"id": "101", "business_date": "2026-07-17", "home": "A", "away": "B"})
            duplicate = queue.enqueue({"id": "101", "business_date": "2026-07-17", "home": "A", "away": "B"})
            second = queue.enqueue({"id": "102", "business_date": "2026-07-17", "home": "C", "away": "D"})
            self.assertFalse(first["deduplicated"])
            self.assertTrue(duplicate["deduplicated"])
            self.assertNotEqual(first["job_id"], second["job_id"])
            self.assertEqual("dispatched", queue.process_once()["status"])
            self.assertEqual("dispatched", queue.process_once()["status"])
            self.assertEqual(["101", "102"], launched)
            self.assertEqual(0, queue.snapshot()["active"])
            restored = PersistentAnalysisQueue(Path(tmp) / "queue.json", launcher=lambda match: None)
            self.assertEqual(2, len(restored.snapshot()["jobs"]))
            self.assertEqual("dispatched", restored.snapshot()["jobs"][0]["status"])

    def test_persistent_analysis_queue_retries_after_transient_dispatch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempts = []

            def flaky(match):
                attempts.append(match["id"])
                if len(attempts) == 1:
                    raise BridgeValidationError("temporary network failure")
                return {"status": "queued", "mode": "test"}

            queue = PersistentAnalysisQueue(
                Path(tmp) / "queue.json", launcher=flaky, retry_delays=(0.0,), max_attempts=3,
            )
            queue.enqueue({"id": "201", "business_date": "2026-07-17", "home": "A", "away": "B"})
            self.assertEqual("retry_wait", queue.process_once()["status"])
            result = queue.process_once()
            self.assertEqual("dispatched", result["status"])
            self.assertEqual(2, result["attempts"])
            self.assertIsNone(result["last_error"])

    def test_workspace_selection_persists_before_background_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BridgeStore(Path(tmp) / "captures", stamp="20260717_090000")
            selection_path = Path(tmp) / "selected_matches.json"
            launched = []
            queue = PersistentAnalysisQueue(
                Path(tmp) / "queue.json",
                launcher=lambda match: launched.append(match["id"]) or {"status": "queued"},
            )
            with patch.object(bridge_module, "WORKSPACE_SELECTION_PATH", selection_path):
                server = ThreadingHTTPServer(
                    ("127.0.0.1", 0), make_handler(store, analysis_queue=queue)
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/analysis-selections"
                    payload = {"match": {
                        "id": "301", "home": "A", "away": "B",
                        "business_date": "2026-07-17", "kickoff": "2026-07-17 20:00",
                    }}
                    request = Request(
                        endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
                        headers={"Content-Type": "application/json", "Origin": "https://gemini077.github.io"},
                    )
                    with urlopen(request, timeout=3) as response:
                        result = json.loads(response.read().decode("utf-8"))
                    self.assertEqual("queued", result["analysis_job"]["status"])
                    self.assertEqual([], launched)
                    self.assertTrue(selection_path.exists())
                    self.assertTrue((Path(tmp) / "queue.json").exists())
                    queue.process_once()
                    self.assertEqual(["301"], launched)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)

    def test_http_reprice_endpoint_returns_candidate_without_execution_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BridgeStore(Path(tmp), stamp="20260714_143200")
            event = sample_event()
            event["payload"] = {
                "cd": {
                    "hls2": {
                        "2": [{
                            "hpid": "2", "hid": "market-total", "mid": "5503037", "hv": "2.5", "hs": 0,
                            "ol": [{
                                "oid": "over", "ot": "Over", "os": 1,
                                "ov": "199000", "ov2": "0.99",
                            }],
                            "t": str(int(__import__("time").time() * 1000)),
                        }]
                    }
                }
            }
            store.record(validate_event(event))
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/reprice"
                payload = {
                    "contract": {
                        "match_id": "5503037", "market_code": "2", "market_id": "market-total",
                        "handicap_line": "2.5", "selection_code": "Over",
                        "contract_type": "binary_no_push",
                    },
                    "probability": {
                        "point": 0.56, "conservative": 0.53,
                        "confirmed_model_output": True,
                        "source": "test", "calibration_status": "test",
                    },
                    "price": {"source": "bridge", "max_quote_age_ms": 15000},
                    "staking": {"bankroll": 51.43},
                }
                request = Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "chrome-extension://test-extension-id",
                    },
                )
                with urlopen(request, timeout=3) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertTrue(result["ok"])
                self.assertEqual("candidate_price_pass", result["decision_status"])
                self.assertEqual(2.0, result["staking"]["suggested_stake"])
                self.assertFalse(result["execution_authorized"])
                self.assertFalse(result["lock_state_changed"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()

