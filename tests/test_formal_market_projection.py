import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from exact_distribution import (  # noqa: E402
    build_exact_distribution_contract,
    build_prediction_time_exact_distribution_state,
)
from official_jc_handicap import build_jc_handicap_contract  # noqa: E402
from formal_market_projection import (  # noqa: E402
    project_frozen_formal_markets,
    summarize_formal_markets,
    verify_formal_markets,
)
from test_official_jc_handicap import captured  # noqa: E402


TZ = timezone(timedelta(hours=8))


def exact_contract(
    *,
    prediction_id: str = "FORMAL-PROJECTION-1",
    model_role: str = "champion",
    model_family: str = "recent_form_market_calibrated_poisson_v2",
    release_version: str = "v0.19.0",
    model_source_fingerprint: str = "model-fingerprint",
    input_sha256: str = "input-hash",
) -> dict:
    cells = {(home, away): 1 / 169 for home in range(13) for away in range(13)}
    state = build_prediction_time_exact_distribution_state(
        cells,
        lambda_home=1.2,
        lambda_away=0.9,
        rho=0.0,
    )
    return build_exact_distribution_contract(
        state,
        model_identity={
            "prediction_id": prediction_id,
            "model_role": model_role,
            "model_family": model_family,
            "release_version": release_version,
            "model_source_fingerprint": model_source_fingerprint,
            "input_sha256": input_sha256,
        },
    )


def formal_record(
    *,
    prediction_id: str = "FORMAL-PROJECTION-1",
    match_id: str | None = None,
) -> dict:
    exact = exact_contract(prediction_id=prediction_id)
    handicap = build_jc_handicap_contract(
        exact,
        captured(1),
        model_identity={
            "prediction_id": prediction_id,
            "model_family": "recent_form_market_calibrated_poisson_v2",
        },
    )
    record = {
        "prediction_id": prediction_id,
        "prediction_status": "formal",
        "model_role": "champion",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "release_version": "v0.19.0",
        "model_source_fingerprint": "model-fingerprint",
        "input_sha256": "input-hash",
        "exact_score_distribution": exact,
        "jc_total_goals": exact["jc_total_goals"],
        "jc_handicap": handicap,
    }
    if match_id is not None:
        record["match_id"] = match_id
    return record


def test_projection_preserves_frozen_formal_market_parity_and_finite_support():
    record = formal_record()

    projection = project_frozen_formal_markets(record)
    markets = projection["markets"]

    assert markets["exact_score"]["status"] == "AVAILABLE"
    assert len(markets["exact_score"]["contract"]["cells"]) == 169
    assert markets["exact_score"]["contract"] == record["exact_score_distribution"]
    assert markets["exact_score"]["contract"]["score_space"]["tail_bucket"] is False
    assert markets["jc_total_goals"]["status"] == "AVAILABLE"
    assert markets["jc_total_goals"]["contract"] == record["jc_total_goals"]
    assert markets["jc_total_goals"]["contract"]["selection_order"] == [
        "0", "1", "2", "3", "4", "5", "6", "7+"
    ]
    assert markets["jc_handicap"]["status"] == "AVAILABLE"
    assert markets["jc_handicap"]["contract"] == record["jc_handicap"]
    assert markets["jc_handicap"]["contract"]["official_integer_line"] == 1

    summary = summarize_formal_markets(projection)
    assert "cells" not in summary["markets"]["exact_score"]
    assert summary["markets"]["exact_score"]["cell_count"] == 169
    assert summary["markets"]["jc_handicap"]["line"] == 1

    verification = verify_formal_markets(projection, "13-0")
    assert verification["exact_score"]["verification_status"] == "OUT_OF_EXPLICIT_SUPPORT"
    assert verification["exact_score"]["actual_probability"] is None
    assert verification["exact_score"]["actual_rank"] is None
    assert verification["exact_score"]["represented_support_status"] == "OUT_OF_EXPLICIT_SUPPORT"
    assert verification["jc_total_goals"]["actual_selection"] == "7+"

    represented = verify_formal_markets(projection, "1-0")["exact_score"]
    assert represented["verification_status"] == "VERIFIED"
    assert represented["actual_probability"] == pytest.approx(1 / 169)
    assert represented["actual_rank"] == 14
    assert represented["represented_support_status"] == "REPRESENTED"


def test_missing_formal_market_contracts_are_independent_and_not_reconstructed():
    record = formal_record()
    record.pop("jc_handicap")

    markets = project_frozen_formal_markets(record)["markets"]

    assert markets["exact_score"]["status"] == "AVAILABLE"
    assert markets["jc_total_goals"]["status"] == "AVAILABLE"
    assert markets["jc_handicap"]["status"] == "NOT_RECORDED"
    verification = verify_formal_markets(project_frozen_formal_markets(record), "1-0")
    assert verification["exact_score"]["verification_status"] == "VERIFIED"
    assert verification["jc_total_goals"]["verification_status"] == "VERIFIED"
    assert verification["jc_handicap"]["verification_status"] == "NOT_RECORDED"


def test_invalid_formal_market_is_unavailable_without_poisoning_other_markets():
    record = formal_record()
    record["jc_handicap"]["content_sha256"] = "invalid"

    markets = project_frozen_formal_markets(record)["markets"]

    assert markets["exact_score"]["status"] == "AVAILABLE"
    assert markets["jc_total_goals"]["status"] == "AVAILABLE"
    assert markets["jc_handicap"]["status"] == "UNAVAILABLE"


def test_legacy_record_without_formal_contract_stays_unrecorded():
    projection = project_frozen_formal_markets(
        {
            "prediction_id": "LEGACY-1",
            "prediction_status": "formal",
            "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        }
    )

    assert {item["status"] for item in projection["markets"].values()} == {"NOT_RECORDED"}
    verification = verify_formal_markets(projection, "1-0")
    assert {item["verification_status"] for item in verification.values()} == {"NOT_RECORDED"}
