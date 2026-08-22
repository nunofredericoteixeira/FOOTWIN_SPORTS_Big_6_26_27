# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_FIXTURES_JSON = Path(
    "data/raw/performance_pages/"
    "ITA1_2026_27_seriea_fixtures.json"
)

LEAGUE_ID = "ITA1"
SEASON_LABEL = "2026/27"
DATASET_VERSION = "DATASET_2026_27_V001"

SERIEA_PROVIDER = "LEGA_SERIE_A_SDP"

SERIEA_SEASON_ID = (
    "serie-a::Football_Season::"
    "ed7fdc2a3e7b408b942ec177b7b956b5"
)

SERIEA_COMPETITION_ID = (
    "serie-a::Football_Competition::"
    "ec93b94f74294dc98ab5bcfd67fc0d88"
)


TEAM_MAPPING = {
    "serie-a::Football_Team::b5846a2413804c2e8cab8b773b18370a":
        "ITA1_ATALANTA",
    "serie-a::Football_Team::4af71b35aab34ad5a7d06148abe66ad6":
        "ITA1_BOLOGNA",
    "serie-a::Football_Team::25aecd0eda3e4453aabd9a9d5e7fba0d":
        "ITA1_CAGLIARI",
    "serie-a::Football_Team::367e70bf50b346209f8a0f16429850cb":
        "ITA1_COMO",
    "serie-a::Football_Team::5bce12d5bd864c2297695d970f92576d":
        "ITA1_FIORENTINA",
    "serie-a::Football_Team::b283fcc0aeda401bb081fcd764e290db":
        "ITA1_FROSINONE",
    "serie-a::Football_Team::8c7aa94d22f44738951748e2ccdf319a":
        "ITA1_GENOA",
    "serie-a::Football_Team::b7421caff23448c49134fa4f9095ee09":
        "ITA1_INTER",
    "serie-a::Football_Team::0ae9210dce6f4f9b9d50aeeb19b0d371":
        "ITA1_JUVENTUS",
    "serie-a::Football_Team::fe6490f2b16e45be9956a1cd04aaf3a2":
        "ITA1_LAZIO",
    "serie-a::Football_Team::ced7bf0df3a140dfa48138311122133b":
        "ITA1_LECCE",
    "serie-a::Football_Team::d0867ddf777c41789ca282b8276002b0":
        "ITA1_MILAN",
    "serie-a::Football_Team::9ba470f39580450fac7654956ba574fa":
        "ITA1_MONZA",
    "serie-a::Football_Team::f791dab8f0e4449e9884dd8dbd42dbcc":
        "ITA1_NAPOLI",
    "serie-a::Football_Team::3294993c79b14d918ccdc78da0fb90c5":
        "ITA1_PARMA",
    "serie-a::Football_Team::8ddc09c1aa73448da2dff953edd95d82":
        "ITA1_ROMA",
    "serie-a::Football_Team::b70390ba4e3c4bc2947a37617d53e8a3":
        "ITA1_SASSUOLO",
    "serie-a::Football_Team::a55dcc2058e94976b572262fc564a74c":
        "ITA1_TORINO",
    "serie-a::Football_Team::630b1e3631db42498d1b7bc94595c5e0":
        "ITA1_UDINESE",
    "serie-a::Football_Team::a28236708d214df3a2e2e04ceb7e5c54":
        "ITA1_VENEZIA",
}


SERIEA_STATUS_MAPPING = {
    "UPCOMING": "SCHEDULED",
    "LIVE": "SCHEDULED",
    "FINISHED": "PLAYED",
    "POSTPONED": "POSTPONED",
    "CANCELLED": "CANCELLED",
    "ABANDONED": "ABANDONED",
}


@dataclass(frozen=True)
class SerieAFixture:
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


class SerieAFixturesError(RuntimeError):
    """Erro na recolha ou validação do calendário ITA1."""


def _normalize_match_date(
    value: Any,
) -> str:
    if not value:
        raise SerieAFixturesError(
            "Fixture sem matchDateUtc."
        )

    raw = str(value).strip()

    try:
        parsed = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise SerieAFixturesError(
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


def _provider_match_token(
    provider_fixture_id: str,
) -> str:
    prefix = "kama:Match:"

    if not provider_fixture_id.startswith(prefix):
        raise SerieAFixturesError(
            "providerId Serie A inesperado: "
            f"{provider_fixture_id!r}"
        )

    token = provider_fixture_id[
        len(prefix):
    ].strip()

    if not token.isdigit():
        raise SerieAFixturesError(
            "providerId numérico Serie A inválido: "
            f"{provider_fixture_id!r}"
        )

    return token


def _build_internal_match_id(
    round_number: int,
    provider_fixture_id: str,
    home_team_id: str,
    away_team_id: str,
) -> str:
    numeric_id = _provider_match_token(
        provider_fixture_id
    )

    return (
        f"ITA1_2026_27_"
        f"R{round_number:02d}_"
        f"SA{numeric_id}_"
        f"{home_team_id}_"
        f"{away_team_id}"
    )


def _extract_team(
    fixture: dict[str, Any],
    field_name: str,
) -> tuple[str, str, str]:
    team = fixture.get(field_name)

    if not isinstance(team, dict):
        raise SerieAFixturesError(
            f"Fixture sem {field_name} válido."
        )

    provider_team_id = str(
        team.get("teamId")
        or ""
    ).strip()

    if not provider_team_id:
        raise SerieAFixturesError(
            f"{field_name} sem teamId."
        )

    internal_team_id = TEAM_MAPPING.get(
        provider_team_id
    )

    team_name = str(
        team.get("shortName")
        or team.get("officialName")
        or team.get("mediaName")
        or provider_team_id
    ).strip()

    if internal_team_id is None:
        raise SerieAFixturesError(
            "Equipa Serie A não mapeada: "
            f"{team_name!r} "
            f"({provider_team_id})"
        )

    return (
        team_name,
        internal_team_id,
        provider_team_id,
    )


def _extract_round_number(
    fixture: dict[str, Any],
) -> int:
    explicit = fixture.get(
        "_round_number"
    )

    if explicit is not None:
        try:
            round_number = int(
                explicit
            )
        except (TypeError, ValueError) as exc:
            raise SerieAFixturesError(
                f"Jornada inválida: {explicit!r}"
            ) from exc
    else:
        match_set = fixture.get(
            "matchSet"
        )

        if not isinstance(
            match_set,
            dict,
        ):
            raise SerieAFixturesError(
                "Fixture sem matchSet."
            )

        name = str(
            match_set.get("name")
            or ""
        ).strip()

        prefix = "Matchday "

        if not name.startswith(prefix):
            raise SerieAFixturesError(
                f"Nome de jornada inesperado: {name!r}"
            )

        raw_number = name[
            len(prefix):
        ].strip()

        if not raw_number.isdigit():
            raise SerieAFixturesError(
                f"Jornada inválida: {name!r}"
            )

        round_number = int(
            raw_number
        )

    if not 1 <= round_number <= 38:
        raise SerieAFixturesError(
            f"Jornada fora do intervalo 1–38: "
            f"{round_number}"
        )

    return round_number


def parse_fixture(
    fixture: dict[str, Any],
) -> SerieAFixture:
    match_id_source = str(
        fixture.get("matchId")
        or ""
    ).strip()

    if not match_id_source.startswith(
        "serie-a::Football_Match::"
    ):
        raise SerieAFixturesError(
            "matchId Serie A inesperado: "
            f"{match_id_source!r}"
        )

    provider_fixture_id = str(
        fixture.get("providerId")
        or ""
    ).strip()

    if not provider_fixture_id:
        raise SerieAFixturesError(
            "Fixture sem providerId."
        )

    _provider_match_token(
        provider_fixture_id
    )

    season_id = str(
        fixture.get("seasonId")
        or ""
    ).strip()

    if season_id != SERIEA_SEASON_ID:
        raise SerieAFixturesError(
            f"Fixture {provider_fixture_id}: "
            "seasonId inesperado "
            f"{season_id!r}."
        )

    round_number = _extract_round_number(
        fixture
    )

    (
        _home_name,
        home_team_id,
        home_provider_id,
    ) = _extract_team(
        fixture,
        "home",
    )

    (
        _away_name,
        away_team_id,
        away_provider_id,
    ) = _extract_team(
        fixture,
        "away",
    )

    if home_team_id == away_team_id:
        raise SerieAFixturesError(
            f"Fixture {provider_fixture_id}: "
            "mesma equipa em casa e fora."
        )

    raw_status = str(
        fixture.get("status")
        or ""
    ).strip().upper()

    status = SERIEA_STATUS_MAPPING.get(
        raw_status
    )

    if status is None:
        raise SerieAFixturesError(
            f"Fixture {provider_fixture_id}: "
            f"status Serie A não suportado "
            f"{raw_status!r}."
        )

    home_goals = None
    away_goals = None

    if status == "PLAYED":
        home_raw = fixture.get(
            "providerHomeScore"
        )
        away_raw = fixture.get(
            "providerAwayScore"
        )

        if (
            home_raw is None
            or away_raw is None
        ):
            raise SerieAFixturesError(
                f"Fixture {provider_fixture_id}: "
                "jogo FINISHED sem resultado."
            )

        try:
            home_goals = int(
                home_raw
            )
            away_goals = int(
                away_raw
            )
        except (TypeError, ValueError) as exc:
            raise SerieAFixturesError(
                f"Fixture {provider_fixture_id}: "
                "resultado inválido."
            ) from exc

    source_url = (
        "https://www.legaseriea.it/serie-a/match/"
        f"{match_id_source}"
    )

    match_id = _build_internal_match_id(
        round_number=round_number,
        provider_fixture_id=provider_fixture_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )

    return SerieAFixture(
        match_id=match_id,
        league_id=LEAGUE_ID,
        season_label=SEASON_LABEL,
        round_number=round_number,
        match_date=_normalize_match_date(
            fixture.get("matchDateUtc")
        ),
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        status=status,
        home_goals=home_goals,
        away_goals=away_goals,
        schedule_type="OFFICIAL",
        source_url=source_url,
        dataset_version=DATASET_VERSION,
        provider=SERIEA_PROVIDER,
        provider_fixture_id=provider_fixture_id,
        provider_home_team_id=home_provider_id,
        provider_away_team_id=away_provider_id,
    )


def collect_seriea_fixtures(
    json_path: str | Path = DEFAULT_FIXTURES_JSON,
) -> list[SerieAFixture]:
    path = Path(
        json_path
    ).expanduser().resolve()

    if not path.exists():
        raise SerieAFixturesError(
            "JSON Serie A não encontrado: "
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
        raise SerieAFixturesError(
            "O JSON consolidado Serie A deveria "
            "ser uma lista."
        )

    fixtures = [
        parse_fixture(item)
        for item in payload
        if isinstance(item, dict)
    ]

    validate_seriea_fixtures(
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


def validate_seriea_fixtures(
    fixtures: list[SerieAFixture],
) -> None:
    expected_total = 380

    if len(fixtures) != expected_total:
        raise SerieAFixturesError(
            f"Esperavam-se {expected_total} jogos; "
            f"foram preparados {len(fixtures)}."
        )

    match_ids = [
        fixture.match_id
        for fixture in fixtures
    ]

    provider_ids = [
        fixture.provider_fixture_id
        for fixture in fixtures
    ]

    if len(set(match_ids)) != expected_total:
        raise SerieAFixturesError(
            "Existem match_id internos duplicados."
        )

    if len(set(provider_ids)) != expected_total:
        raise SerieAFixturesError(
            "Existem providerId Serie A duplicados."
        )

    rounds = {
        fixture.round_number
        for fixture in fixtures
    }

    if rounds != set(range(1, 39)):
        raise SerieAFixturesError(
            "O calendário não contém exatamente "
            "as jornadas 1 a 38."
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
        missing = sorted(
            expected_teams - teams
        )

        unexpected = sorted(
            teams - expected_teams
        )

        raise SerieAFixturesError(
            "As equipas presentes no calendário "
            "não correspondem às 20 equipas "
            "mapeadas. "
            f"Em falta={missing}; "
            f"inesperadas={unexpected}"
        )

    appearances = {
        team_id: 0
        for team_id in expected_teams
    }

    home_appearances = {
        team_id: 0
        for team_id in expected_teams
    }

    away_appearances = {
        team_id: 0
        for team_id in expected_teams
    }

    round_counts = {
        round_number: 0
        for round_number in range(1, 39)
    }

    directed_pairings: set[
        tuple[str, str]
    ] = set()

    unordered_pairings: dict[
        tuple[str, str],
        int,
    ] = {}

    for fixture in fixtures:
        appearances[
            fixture.home_team_id
        ] += 1

        appearances[
            fixture.away_team_id
        ] += 1

        home_appearances[
            fixture.home_team_id
        ] += 1

        away_appearances[
            fixture.away_team_id
        ] += 1

        round_counts[
            fixture.round_number
        ] += 1

        directed = (
            fixture.home_team_id,
            fixture.away_team_id,
        )

        if directed in directed_pairings:
            raise SerieAFixturesError(
                "Emparelhamento casa/fora "
                "duplicado: "
                f"{directed}"
            )

        directed_pairings.add(
            directed
        )

        unordered = tuple(
            sorted(
                (
                    fixture.home_team_id,
                    fixture.away_team_id,
                )
            )
        )

        unordered_pairings[
            unordered
        ] = (
            unordered_pairings.get(
                unordered,
                0,
            )
            + 1
        )

    invalid_rounds = {
        round_number: total
        for round_number, total
        in round_counts.items()
        if total != 10
    }

    if invalid_rounds:
        raise SerieAFixturesError(
            "Existem jornadas sem exatamente "
            f"10 jogos: {invalid_rounds}"
        )

    invalid_appearances = {
        team_id: total
        for team_id, total
        in appearances.items()
        if total != 38
    }

    if invalid_appearances:
        raise SerieAFixturesError(
            "Equipas sem exatamente 38 jogos: "
            f"{invalid_appearances}"
        )

    invalid_home = {
        team_id: total
        for team_id, total
        in home_appearances.items()
        if total != 19
    }

    if invalid_home:
        raise SerieAFixturesError(
            "Equipas sem exatamente 19 jogos "
            f"em casa: {invalid_home}"
        )

    invalid_away = {
        team_id: total
        for team_id, total
        in away_appearances.items()
        if total != 19
    }

    if invalid_away:
        raise SerieAFixturesError(
            "Equipas sem exatamente 19 jogos "
            f"fora: {invalid_away}"
        )

    if len(unordered_pairings) != 190:
        raise SerieAFixturesError(
            "Número incorreto de pares de equipas: "
            f"{len(unordered_pairings)}."
        )

    invalid_pairs = {
        pairing: total
        for pairing, total
        in unordered_pairings.items()
        if total != 2
    }

    if invalid_pairs:
        raise SerieAFixturesError(
            "Existem pares que não jogam "
            "exatamente duas vezes: "
            f"{invalid_pairs}"
        )


def fixture_to_database_record(
    fixture: SerieAFixture,
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
