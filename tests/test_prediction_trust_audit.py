import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.prediction_trust_audit import (  # noqa: E402
    build_unique_match_cohort,
    classify_duplicate_groups,
    evaluate_prospective_metrics,
    summarize_prediction_cohort,
)


BASE_KICKOFF = "2026-08-13T04:00:00+08:00"


def prediction(
    prediction_id: str,
    *,
    match_id: str = "M-1",
    job_id: str = "JOB-1",
    score: str = "1-1",
    created: str = "2026-08-12T14:00:00+08:00",
    source: str = "2026-08-12T12:00:00+08:00",
    freeze: str = "2026-08-12T14:01:00+08:00",
    prediction_status: str = "formal",
    home_probability: float = 0.5,
    away_probability: float = 0.2,
    lambda_home: float = 1.4,
    lambda_away: float = 0.8,
) -> dict:
    return {
        "prediction_id": prediction_id,
        "job_id": job_id,
        "match_id": match_id,
        "match_key": f"KEY-{match_id}",
        "match_identity": {
            "match_key": f"KEY-{match_id}",
            "home": "Home",
            "away": "Away",
            "kickoff_at": BASE_KICKOFF,
        },
        "kickoff_at": BASE_KICKOFF,
        "source_cutoff_at": source,
        "prediction_created_at": created,
        "freeze_created_at": freeze,
        "prediction_status": prediction_status,
        "model_role": "champion",
        "prediction_variant": "model_only",
        "manual_override": False,
        "model_input_snapshot_ref": f"snapshots/{prediction_id}.json",
        "input_sha256": f"input-{prediction_id}",
        "model_source_fingerprint": "champion-fingerprint",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "data_grade": "B",
        "critical_missing_fields": [],
        "missing_critical_fields": [],
        "probabilities": {
            "home": home_probability,
            "draw": 1.0 - home_probability - away_probability,
            "away": away_probability,
        },
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "btts": {"yes": 0.55, "no": 0.45},
        "totals": [
            {"goals": "0", "probability": 0.1},
            {"goals": "1", "probability": 0.2},
            {"goals": "2", "probability": 0.25},
            {"goals": "3", "probability": 0.2},
            {"goals": "4", "probability": 0.15},
            {"goals": "5", "probability": 0.1},
        ],
        "unique_score": score,
        "score_distribution": [
            {"rank": 1, "score": score, "probability": 0.2},
            {"rank": 2, "score": "0-0", "probability": 0.15},
            {"rank": 3, "score": "2-1", "probability": 0.1},
        ],
    }


def test_unique_cohort_selects_latest_legal_version_without_mutating_history():
    older = prediction("P-OLDER")
    newer = prediction(
        "P-NEWER",
        created="2026-08-12T15:00:00+08:00",
        source="2026-08-12T14:59:00+08:00",
        freeze="2026-08-12T15:01:00+08:00",
    )
    post_kickoff = prediction(
        "P-POST",
        created="2026-08-13T05:00:00+08:00",
        source="2026-08-13T04:59:00+08:00",
        freeze="2026-08-13T05:01:00+08:00",
    )
    original = [older.copy(), newer.copy(), post_kickoff.copy()]

    result = build_unique_match_cohort(original)

    assert [record["prediction_id"] for record in result["selected_records"]] == ["P-NEWER"]
    assert result["raw_record_count"] == 3
    assert result["legal_record_count"] == 2
    assert result["unique_match_count"] == 1
    assert result["superseded_record_count"] == 1
    assert original == [older, newer, post_kickoff]


def test_duplicate_groups_distinguish_history_final_collision_identity_and_false_positive():
    legitimate = [
        prediction("A-1", job_id="JOB-A", match_id="M-A"),
        prediction(
            "A-2",
            job_id="JOB-A",
            match_id="M-A",
            created="2026-08-12T15:00:00+08:00",
            source="2026-08-12T14:59:00+08:00",
            freeze="2026-08-12T15:01:00+08:00",
        ),
    ]
    actual_final = [
        prediction("B-1", job_id="JOB-B", match_id="M-B", created="2026-08-12T16:00:00+08:00", source="2026-08-12T15:59:00+08:00", freeze="2026-08-12T16:01:00+08:00"),
        prediction("B-2", job_id="JOB-B", match_id="M-B", created="2026-08-12T16:00:00+08:00", source="2026-08-12T15:59:00+08:00", freeze="2026-08-12T16:01:00+08:00"),
    ]
    identity_collision = [
        prediction("C-1", job_id="JOB-C", match_id="M-C1"),
        prediction("C-2", job_id="JOB-C", match_id="M-C2"),
    ]
    health_false_positive = [
        prediction("D-1", job_id="JOB-D", match_id="M-D"),
        {"prediction_id": "D-2", "job_id": "JOB-D", "match_id": "M-D", "prediction_status": "formal"},
    ]

    result = classify_duplicate_groups(
        legitimate + actual_final + identity_collision + health_false_positive
    )

    assert result["duplicate_group_count"] == 4
    assert result["classification_counts"] == {"A": 1, "B": 1, "C": 1, "D": 1}
    assert result["actual_immutable_frozen_integrity_violation"] is True
    assert result["unique_affected_matches"] == 5


def test_summary_and_prospective_metrics_are_unique_match_metrics():
    first = prediction(
        "P-1",
        match_id="M-1",
        score="1-1",
        home_probability=0.6,
        away_probability=0.2,
        lambda_home=1.1,
        lambda_away=0.8,
    )
    second = prediction("P-2", match_id="M-2", score="2-1", home_probability=0.2, away_probability=0.6, lambda_home=1.1, lambda_away=1.3)

    summary = summarize_prediction_cohort([first, second])
    assert summary["sample_count"] == 2
    assert summary["top1_score_distribution"] == {"1-1": 1, "2-1": 1}
    assert summary["score_counts"]["1-1"] == 1
    assert summary["lambda"]["gap_lt_0_5"]["count"] == 2
    assert summary["cross_market"]["home_leader_plus_draw_score_top1"]["count"] == 1

    results = {
        "KEY-M-1": {"match_key": "KEY-M-1", "home_score": 1, "away_score": 1, "result_90m": "1-1", "scope": "regulation_90m_plus_stoppage", "verified_at": "2026-08-14T08:00:00+08:00"},
        "KEY-M-2": {"match_key": "KEY-M-2", "home_score": 0, "away_score": 1, "result_90m": "0-1", "scope": "regulation_90m_plus_stoppage", "verified_at": "2026-08-14T08:00:00+08:00"},
    }
    metrics = evaluate_prospective_metrics([first, second], results, formal_prediction_ids={"P-1", "P-2"})
    assert metrics["sample_count"] == 2
    assert metrics["one_x_two"]["accuracy"] == 0.5
    assert metrics["exact_score"]["top1_hit_rate"] == 0.5
    assert metrics["exact_score"]["top3_hit_rate"] == 0.5
    assert metrics["btts"]["sample_count"] == 2
    assert metrics["ou_2_5"]["sample_count"] == 2
