"""Small provider protocol and shared normalized-record helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from ..contracts import DataProvenance


class FootballDataProvider(Protocol):
    provider_name: str
    provider_version: str

    def get_team_identity(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def get_match_history(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def get_team_stats(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def get_xg(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def get_lineup(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def get_availability(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def provenance(
    *,
    provider: str,
    source: str,
    source_record_ref: str,
    captured_at: str,
    source_as_of_at: str | None,
    source_url: str | None = None,
    data_license: str | None = None,
    attribution_required: bool = False,
    commercial_use_review: str = "not_required",
    parser_version: str | None = None,
    synthetic: bool = False,
    observation_origin: str = "provider_observation",
    provider_schema: str | None = None,
    provider_schema_reference: str | None = None,
) -> dict[str, Any]:
    return DataProvenance(
        provider=provider,
        source=source,
        source_record_ref=source_record_ref,
        captured_at=captured_at,
        source_as_of_at=source_as_of_at,
        source_url=source_url,
        data_license=data_license,
        attribution_required=attribution_required,
        commercial_use_review=commercial_use_review,
        parser_version=parser_version,
        synthetic=synthetic,
        observation_origin=observation_origin,
        provider_schema=provider_schema,
        provider_schema_reference=provider_schema_reference,
    ).to_dict()


def common_record(
    *,
    contract_version: str,
    source: str,
    source_entity_id: str | None,
    canonical_entity_id: str | None,
    captured_at: str,
    source_as_of_at: str | None,
    competition: str | None,
    season: str | None,
    home_away_context: str,
    sample_matches: int | None,
    sample_minutes: int | None,
    value: Any,
    unit: str | None,
    quality: str,
    freshness: Mapping[str, Any],
    missing_reason: list[str],
    provenance_record: Mapping[str, Any],
    provider_competition_id: str | None = None,
    provider_competition_name: str | None = None,
    provider_season_id: str | None = None,
    provider_season_name: str | None = None,
    canonical_competition_id: str | None = None,
    canonical_season_id: str | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": contract_version,
        "source": source,
        "source_entity_id": source_entity_id,
        "canonical_entity_id": canonical_entity_id,
        "captured_at": captured_at,
        "source_as_of_at": source_as_of_at,
        "competition": competition,
        "season": season,
        "provider_competition_id": provider_competition_id,
        "provider_competition_name": provider_competition_name,
        "provider_season_id": provider_season_id,
        "provider_season_name": provider_season_name,
        "canonical_competition_id": canonical_competition_id,
        "canonical_season_id": canonical_season_id,
        "home_away_context": home_away_context,
        "sample_size": {"matches": sample_matches, "minutes": sample_minutes},
        "value": value,
        "unit": unit,
        "quality": quality,
        "freshness": dict(freshness),
        "missing_reason": list(missing_reason),
        "provenance": dict(provenance_record),
    }
