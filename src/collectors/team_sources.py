# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LeagueTeamSource:
    league_id: str
    league_name: str
    country: str
    expected_team_count: int
    source_url: str


TEAM_SOURCES: dict[str, LeagueTeamSource] = {
    "ENG1": LeagueTeamSource(
        league_id="ENG1",
        league_name="Premier League",
        country="England",
        expected_team_count=20,
        source_url=(
            "https://www.premierleague.com/en/tables/"
            "premier-league/2026-27/all-matchweeks"
        ),
    ),
    "ESP1": LeagueTeamSource(
        league_id="ESP1",
        league_name="LaLiga",
        country="Spain",
        expected_team_count=20,
        source_url=(
            "https://www.laliga.com/en-GB/"
            "laliga-easports/clubs"
        ),
    ),
    "ITA1": LeagueTeamSource(
        league_id="ITA1",
        league_name="Serie A",
        country="Italy",
        expected_team_count=20,
        source_url=(
            "https://en.legaseriea.it/serie-a/"
            "fixtures-results"
        ),
    ),
    "GER1": LeagueTeamSource(
        league_id="GER1",
        league_name="Bundesliga",
        country="Germany",
        expected_team_count=18,
        source_url=(
            "https://www.bundesliga.com/en/"
            "bundesliga/table"
        ),
    ),
    "FRA1": LeagueTeamSource(
        league_id="FRA1",
        league_name="Ligue 1",
        country="France",
        expected_team_count=18,
        source_url=(
            "https://ligue1.com/en/competitions/"
            "ligue1mcdonalds/standings"
        ),
    ),
    "POR1": LeagueTeamSource(
        league_id="POR1",
        league_name="Liga Portugal",
        country="Portugal",
        expected_team_count=18,
        source_url=(
            "https://www.ligaportugal.pt/"
            "competition/911/liga-portugal-betclic/"
            "round/20262027?tab=standings"
        ),
    ),
}


def get_team_sources() -> dict[str, LeagueTeamSource]:
    """
    Devolve as fontes oficiais das seis ligas.
    """

    return dict(TEAM_SOURCES)


def validate_team_sources() -> None:
    """
    Valida as fontes e os totais configurados.
    """

    expected_league_ids = {
        "ENG1",
        "ESP1",
        "ITA1",
        "GER1",
        "FRA1",
        "POR1",
    }

    actual_league_ids = set(
        TEAM_SOURCES
    )

    if actual_league_ids != expected_league_ids:
        missing = (
            expected_league_ids
            - actual_league_ids
        )

        extra = (
            actual_league_ids
            - expected_league_ids
        )

        raise RuntimeError(
            "Fontes de equipas inválidas. "
            f"Em falta: {sorted(missing)}; "
            f"adicionais: {sorted(extra)}."
        )

    total_teams = sum(
        source.expected_team_count
        for source in TEAM_SOURCES.values()
    )

    if total_teams != 114:
        raise RuntimeError(
            "Total de equipas inválido: "
            f"{total_teams}. Esperado: 114."
        )

    for source in TEAM_SOURCES.values():
        if not source.source_url.startswith(
            "https://"
        ):
            raise RuntimeError(
                "URL inválido para "
                f"{source.league_id}: "
                f"{source.source_url}"
            )


validate_team_sources()
