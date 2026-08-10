"""Offline source-to-ledger population helpers for P0/P1 competitions."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Iterable, Mapping

from .p0_p1_identity import P0P1TeamIdentityCandidateBuilder, SourceMatchObservation, normalize_source_team_name, reviewed_mappings
from .providers.football_data_uk import FootballDataCoUkHistoricalAdapter, parse_football_data_result_rows
from .providers.openfootball import OpenFootballHistoricalAdapter, parse_football_txt_rows
from .historical_results import deduplicate_historical_results


def _football_data_kickoff(date_text: str, time_text: str) -> str:
    match_date = datetime.strptime(date_text, "%d/%m/%Y").date()
    if time_text:
        try:
            clock = datetime.strptime(time_text, "%H:%M").strftime("%H:%M")
        except ValueError:
            clock = "00:00"
    else:
        clock = "00:00"
    return f"{match_date.isoformat()}T{clock}:00Z"


def source_observations(config: Mapping[str, Any], raw_text: str) -> list[SourceMatchObservation]:
    """Extract raw result observations without applying identity mappings."""

    provider = str(config["provider"])
    rows: list[SourceMatchObservation] = []
    if provider == "football-data.co.uk":
        parsed = parse_football_data_result_rows(raw_text, season_filter=config.get("season_filter"))
        for row in parsed:
            kickoff_at = _football_data_kickoff(str(row["date"]), str(row.get("time") or ""))
            rows.append(
                SourceMatchObservation(
                    provider=provider,
                    competition_id=str(config["competition_id"]),
                    season_id=str(config["season_id"]),
                    country=str(config.get("country") or ""),
                    kickoff_at=kickoff_at,
                    home_name=str(row["home"]),
                    away_name=str(row["away"]),
                    home_goals=int(row["home_goals"]),
                    away_goals=int(row["away_goals"]),
                    source_ref=f"{config.get('source_url')}#line={row['line_number']}",
                    match_type=str(config.get("match_type") or "league"),
                )
            )
        return rows
    if provider == "openfootball":
        for row in parse_football_txt_rows(raw_text):
            rows.append(
                SourceMatchObservation(
                    provider=provider,
                    competition_id=str(config["competition_id"]),
                    season_id=str(config["season_id"]),
                    country=str(config.get("country") or ""),
                    kickoff_at=str(row["kickoff_at"]),
                    home_name=str(row["home"]),
                    away_name=str(row["away"]),
                    home_goals=int(row["home_goals"]),
                    away_goals=int(row["away_goals"]),
                    source_ref=f"{config.get('repository')}@{config.get('commit_sha')}:{config.get('source_file')}:line:{row['line_number']}",
                    match_type=str(config.get("match_type") or "league"),
                )
            )
        return rows
    raise ValueError(f"unsupported P0/P1 source provider: {provider}")


def build_identity_candidates(
    source_inputs: Iterable[Mapping[str, Any]],
    *,
    canonical_seeds: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[SourceMatchObservation]]:
    observations: list[SourceMatchObservation] = []
    for source in source_inputs:
        observations.extend(source_observations(source, str(source["raw_text"])))
    result = P0P1TeamIdentityCandidateBuilder().build(observations, canonical_seeds=canonical_seeds)
    return result, observations


def expand_exact_provider_mappings(
    candidate_result: Mapping[str, Any],
    source_inputs: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Propagate a reviewed source mapping to an identical name in another season.

    This is intentionally exact-name and same provider/country/competition only;
    promoted teams with a new name remain unresolved.
    """

    mappings = reviewed_mappings(candidate_result)
    candidate_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for (provider, raw_name), mapping in mappings.items():
        key = (provider, normalize_source_team_name(raw_name), str(mapping.get("country") or ""))
        candidate_by_key[key] = mapping
    for source in source_inputs:
        provider = str(source["provider"])
        country = str(source.get("country") or "")
        if provider not in {"football-data.co.uk", "openfootball"}:
            continue
        if provider == "football-data.co.uk":
            rows = parse_football_data_result_rows(str(source["raw_text"]), season_filter=source.get("season_filter"))
            names = {str(row["home"]) for row in rows} | {str(row["away"]) for row in rows}
        else:
            parsed = parse_football_txt_rows(str(source["raw_text"]))
            names = {str(row["home"]) for row in parsed} | {str(row["away"]) for row in parsed}
        for raw_name in names:
            key = (provider, normalize_source_team_name(raw_name), country)
            prior = candidate_by_key.get(key)
            if prior is None or (provider, raw_name) in mappings:
                continue
            propagated = dict(prior)
            propagated["provider_team_name"] = raw_name
            propagated["provider_team_id"] = None
            propagated["evidence"] = {
                **dict(prior.get("evidence") or {}),
                "exact_provider_name_reused_across_season": True,
                "source_season_id": source.get("season_id"),
            }
            mappings[(provider, raw_name)] = propagated
    return mappings


def build_normalized_records(
    source_inputs: Iterable[Mapping[str, Any]],
    mappings: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse configured captures through the existing historical adapters."""

    records: list[dict[str, Any]] = []
    parse_counts: list[dict[str, Any]] = []
    for source in source_inputs:
        provider = str(source["provider"])
        raw_text = str(source["raw_text"])
        resolver = {
            raw_name: dict(mapping)
            for (mapped_provider, raw_name), mapping in mappings.items()
            if mapped_provider == provider
        }
        common = {
            "competition_id": source.get("competition_id"),
            "season_id": source.get("season_id"),
            "provider_competition_id": str(source.get("provider_competition_id") or source.get("competition_id")),
            "provider_competition_name": str(source.get("provider_competition_name") or source.get("competition_id")),
            "provider_season_id": str(source.get("provider_season_id") or source.get("season_id")),
            "provider_season_name": str(source.get("provider_season_name") or source.get("season_id")),
            "source_file": str(source.get("source_file") or ""),
            "captured_at": str(source["captured_at"]),
            "country": str(source.get("country") or ""),
            "entity_type": str(source.get("entity_type") or "club"),
            "match_type": str(source.get("match_type") or "league"),
            "team_identity_resolver": resolver,
        }
        if provider == "football-data.co.uk":
            adapter = FootballDataCoUkHistoricalAdapter(
                **common,
                source_url=str(source.get("source_url") or ""),
                raw_sha256=str(source.get("raw_sha256") or hashlib.sha256(raw_text.encode("utf-8")).hexdigest()),
            )
            parsed = adapter.parse_csv_text(raw_text, season_filter=source.get("season_filter"))
        elif provider == "openfootball":
            adapter = OpenFootballHistoricalAdapter(
                **common,
                repository=str(source.get("repository") or ""),
                commit_sha=str(source.get("commit_sha") or ""),
                source_as_of_at=source.get("source_as_of_at"),
                synthetic=False,
            )
            parsed = adapter.parse_text(raw_text)
        else:
            raise ValueError(f"unsupported P0/P1 source provider: {provider}")
        records.extend(parsed)
        parse_counts.append(
            {
                "provider": provider,
                "competition_id": source.get("competition_id"),
                "season_id": source.get("season_id"),
                "parsed_records": len(parsed),
                "eligible_records": sum(bool(row.get("eligible_for_team_strength")) for row in parsed),
                "mapped_team_names": len(resolver),
            }
        )
    dedup = deduplicate_historical_results(records)
    return dedup.records, {
        "input_records": len(records),
        "deduplicated_records": len(dedup.records),
        "duplicates_collapsed": dedup.duplicates_collapsed,
        "possible_duplicates": dedup.possible_duplicates,
        "conflicts": dedup.conflicts,
        "parse_counts": parse_counts,
    }


__all__ = [
    "build_identity_candidates",
    "build_normalized_records",
    "expand_exact_provider_mappings",
    "source_observations",
]
