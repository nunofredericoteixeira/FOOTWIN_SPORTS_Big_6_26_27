# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_FIXTURES_JSON = Path(
    "data/raw/performance_pages/"
    "ESP1_2026_27_laliga-easports-2026_fixtures.json"
)

LEAGUE_ID = "ESP1"
SEASON_LABEL = "2026/27"
DATASET_VERSION = "DATASET_2026_27_V001"

LALIGA_COMPETITION_ID = 1
LALIGA_COMPETITION_SLUG = "primera-division"
LALIGA_SEASON_ID = 102
LALIGA_SEASON_YEAR = 2026
LALIGA_PROVIDER = "LALIGA_PUBLIC_SERVICE"


TEAM_MAPPING = {
    "Athletic Club": "ESP1_ATHLETIC_CLUB",
    "Atlético de Madrid": "ESP1_ATLETICO_MADRID",
    "CA Osasuna": "ESP1_OSASUNA",
    "Celta": "ESP1_CELTA",
    "Deportivo Alavés": "ESP1_ALAVES",
    "Elche CF": "ESP1_ELCHE",
    "FC Barcelona": "ESP1_BARCELONA",
    "Getafe CF": "ESP1_GETAFE",
    "Levante UD": "ESP1_LEVANTE",
    "Málaga CF": "ESP1_MALAGA",
    "R. Racing Club": "ESP1_RACING",
    "RC Deportivo": "ESP1_DEPORTIVO",
    "RCD Espanyol de Barcelona": "ESP1_ESPANYOL",
    "Rayo Vallecano": "ESP1_RAYO_VALLECANO",
    "Real Betis": "ESP1_REAL_BETIS",
    "Real Madrid": "ESP1_REAL_MADRID",
    "Real Sociedad": "ESP1_REAL_SOCIEDAD",
    "Sevilla FC": "ESP1_SEVILLA",
    "Valencia CF": "ESP1_VALENCIA",
    "Villarreal CF": "ESP1_VILLARREAL",
}


LALIGA_STATUS_MAPPING = {
    "PreMatch": "SCHEDULED",
}


@dataclass(frozen=True)
class LaLigaFixture:
    match_id: str
    league_id: str
    season_label: str
    round_number: int
    match_date: str
    home_team_id: str
    away_team_id: str
    status: str
    home_goals: int | None
    away_goals: int | None
    schedule_type: str
    source_url: str
    dataset_version: str
    provider: str
    provider_fixture_id: str
    provider_home_team_id: str
    provider_away_team_id: str
    opta_fixture_id: str | None
    lde_fixture_id: str | None


class LaLigaFixturesError(RuntimeError):
    """Erro na recolha ou validação do calendário ESP1."""


def _to_integer(
    value: Any,
    field_name: str,
) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise LaLigaFixturesError(
            f"Valor inválido em {field_name}: {value!r}"
        ) from exc


def _build_internal_match_id(
    round_number: int,
    provider_fixture_id: str,
    home_team_id: str,
    away_team_id: str,
) -> str:
    return (
        f"ESP1_2026_27_"
        f"R{round_number:02d}_"
        f"LL{provider_fixture_id}_"
        f"{home_team_id}_"
        f"{away_team_id}"
    )


def _normalize_match_date(
    value: Any,
) -> str:
    if not value:
        raise LaLigaFixturesError(
            "Fixture sem date."
        )

    raw = str(value).strip()

    try:
        parsed = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise LaLigaFixturesError(
            f"Data inválida: {raw!r}"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    parsed_utc = parsed.astimezone(
        timezone.utc
    )

    return parsed_utc.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _extract_team(
    fixture: dict[str, Any],
    field_name: str,
) -> tuple[str, str, str]:
    team = fixture.get(field_name)

    if not isinstance(team, dict):
        raise LaLigaFixturesError(
            f"Fixture sem {field_name} válido."
        )

    team_name = str(
        team.get("nickname")
        or team.get("boundname")
        or team.get("name")
        or ""
    ).strip()

    if not team_name:
        raise LaLigaFixturesError(
            f"{field_name} sem nome."
        )

    internal_team_id = TEAM_MAPPING.get(
        team_name
    )

    if internal_team_id is None:
        raise LaLigaFixturesError(
            f"Equipa LaLiga não mapeada: "
            f"{team_name!r}"
        )

    provider_team_id = str(
        _to_integer(
            team.get("id"),
            f"{field_name}.id",
        )
    )

    return (
        team_name,
        internal_team_id,
        provider_team_id,
    )


def parse_fixture(
    fixture: dict[str, Any],
) -> LaLigaFixture:
    provider_fixture_id = str(
        _to_integer(
            fixture.get("id"),
            "fixture.id",
        )
    )

    competition = (
        fixture.get("competition")
        or {}
    )

    if _to_integer(
        competition.get("id"),
        "competition.id",
    ) != LALIGA_COMPETITION_ID:
        raise LaLigaFixturesError(
            f"Fixture {provider_fixture_id} "
            "com competição inesperada."
        )

    if competition.get(
        "slug"
    ) != LALIGA_COMPETITION_SLUG:
        raise LaLigaFixturesError(
            f"Fixture {provider_fixture_id} "
            "com competition.slug inesperado."
        )

    season = (
        fixture.get("season")
        or {}
    )

    if _to_integer(
        season.get("id"),
        "season.id",
    ) != LALIGA_SEASON_ID:
        raise LaLigaFixturesError(
            f"Fixture {provider_fixture_id} "
            "com season.id inesperado."
        )

    if _to_integer(
        season.get("year"),
        "season.year",
    ) != LALIGA_SEASON_YEAR:
        raise LaLigaFixturesError(
            f"Fixture {provider_fixture_id} "
            "com season.year inesperado."
        )

    gameweek = (
        fixture.get("gameweek")
        or {}
    )

    round_number = _to_integer(
        gameweek.get("week"),
        "gameweek.week",
    )

    if not 1 <= round_number <= 38:
        raise LaLigaFixturesError(
            f"Jornada inválida: "
            f"{round_number}"
        )

    (
        home_name,
        home_team_id,
        home_provider_id,
    ) = _extract_team(
        fixture,
        "home_team",
    )

    (
        away_name,
        away_team_id,
        away_provider_id,
    ) = _extract_team(
        fixture,
        "away_team",
    )

    if home_team_id == away_team_id:
        raise LaLigaFixturesError(
            f"Fixture {provider_fixture_id} "
            "com a mesma equipa em casa e fora."
        )

    raw_status = str(
        fixture.get("status")
        or ""
    ).strip()

    if raw_status not in LALIGA_STATUS_MAPPING:
        raise LaLigaFixturesError(
            f"Status LaLiga não suportado: "
            f"{raw_status!r}"
        )

    status = LALIGA_STATUS_MAPPING[
        raw_status
    ]

    home_goals = None
    away_goals = None

    match_date = _normalize_match_date(
        fixture.get("date")
    )

    source_url = (
        "https://www.laliga.com/"
        "en-GB/match/"
        f"{fixture.get('slug')}"
    )

    match_id = _build_internal_match_id(
        round_number=round_number,
        provider_fixture_id=provider_fixture_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )

    opta_fixture_id = str(
        fixture.get("opta_id")
        or ""
    ).strip() or None

    lde_fixture_id = str(
        fixture.get("lde_id")
        or ""
    ).strip() or None

    return LaLigaFixture(
        match_id=match_id,
        league_id=LEAGUE_ID,
        season_label=SEASON_LABEL,
        round_number=round_number,
        match_date=match_date,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        status=status,
        home_goals=home_goals,
        away_goals=away_goals,
        schedule_type="OFFICIAL",
        source_url=source_url,
        dataset_version=DATASET_VERSION,
        provider=LALIGA_PROVIDER,
        provider_fixture_id=provider_fixture_id,
        provider_home_team_id=home_provider_id,
        provider_away_team_id=away_provider_id,
        opta_fixture_id=opta_fixture_id,
        lde_fixture_id=lde_fixture_id,
    )


def collect_laliga_fixtures(
    json_path: str | Path = DEFAULT_FIXTURES_JSON,
) -> list[LaLigaFixture]:
    path = Path(
        json_path
    ).expanduser().resolve()

    if not path.exists():
        raise LaLigaFixturesError(
            f"JSON LaLiga não encontrado: "
            f"{path}"
        )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        payload,
        list,
    ):
        raise LaLigaFixturesError(
            "O JSON consolidado deveria "
            "ser uma lista."
        )

    fixtures = [
        parse_fixture(item)
        for item in payload
        if isinstance(item, dict)
    ]

    validate_laliga_fixtures(
        fixtures
    )

    return sorted(
        fixtures,
        key=lambda item: (
            item.round_number,
            item.match_date,
            item.provider_fixture_id,
        ),
    )


def validate_laliga_fixtures(
    fixtures: list[LaLigaFixture],
) -> None:
    if len(fixtures) != 380:
        raise LaLigaFixturesError(
            f"Esperavam-se 380 jogos; "
            f"foram preparados "
            f"{len(fixtures)}."
        )

    match_ids = [
        fixture.match_id
        for fixture in fixtures
    ]

    provider_ids = [
        fixture.provider_fixture_id
        for fixture in fixtures
    ]

    if len(set(match_ids)) != 380:
        raise LaLigaFixturesError(
            "Existem match_id internos "
            "duplicados."
        )

    if len(set(provider_ids)) != 380:
        raise LaLigaFixturesError(
            "Existem fixture IDs LaLiga "
            "duplicados."
        )

    rounds = {
        fixture.round_number
        for fixture in fixtures
    }

    if rounds != set(range(1, 39)):
        raise LaLigaFixturesError(
            "O calendário não contém "
            "exatamente as jornadas 1 a 38."
        )

    expected_teams = set(
        TEAM_MAPPING.values()
    )

    teams = {
        fixture.home_team_id
        for fixture in fixtures
    } | {
        fixture.away_team_id
        for fixture in fixtures
    }

    if teams != expected_teams:
        raise LaLigaFixturesError(
            "As equipas presentes no "
            "calendário não correspondem "
            "às 20 equipas mapeadas."
        )

    appearances = {
        team_id: 0
        for team_id in expected_teams
    }

    pairings: set[
        tuple[str, str]
    ] = set()

    round_counts = {
        round_number: 0
        for round_number in range(1, 39)
    }

    for fixture in fixtures:
        appearances[
            fixture.home_team_id
        ] += 1

        appearances[
            fixture.away_team_id
        ] += 1

        round_counts[
            fixture.round_number
        ] += 1

        pairing = (
            fixture.home_team_id,
            fixture.away_team_id,
        )

        if pairing in pairings:
            raise LaLigaFixturesError(
                "Emparelhamento casa/fora "
                "duplicado: "
                f"{pairing}"
            )

        pairings.add(
            pairing
        )

    invalid_rounds = {
        round_number: total
        for round_number, total
        in round_counts.items()
        if total != 10
    }

    if invalid_rounds:
        raise LaLigaFixturesError(
            "Jornadas sem exatamente "
            f"10 jogos: {invalid_rounds}"
        )

    invalid_appearances = {
        team_id: total
        for team_id, total
        in appearances.items()
        if total != 38
    }

    if invalid_appearances:
        raise LaLigaFixturesError(
            "Equipas sem exatamente "
            f"38 jogos: "
            f"{invalid_appearances}"
        )


def fixture_to_database_record(
    fixture: LaLigaFixture,
) -> dict[str, Any]:
    return {
        "match_id": fixture.match_id,
        "league_id": fixture.league_id,
        "season_label": fixture.season_label,
        "round_number": fixture.round_number,
        "match_date": fixture.match_date,
        "home_team_id": fixture.home_team_id,
        "away_team_id": fixture.away_team_id,
        "status": fixture.status,
        "home_goals": fixture.home_goals,
        "away_goals": fixture.away_goals,
        "schedule_type": fixture.schedule_type,
        "source_url": fixture.source_url,
        "dataset_version": fixture.dataset_version,
    }
