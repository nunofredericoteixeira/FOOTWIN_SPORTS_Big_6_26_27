# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.config.path_config import load_paths_config


class LeagueConfigurationError(RuntimeError):
    """Erro relacionado com a configuração das ligas."""


REQUIRED_LEAGUE_FIELDS = {
    "name",
    "country",
    "country_code",
    "season_label",
    "team_count",
    "matches_per_team",
    "total_matches",
    "league_strength_factor",
    "relegation_places",
    "playoff_places",
    "active",
}


def load_leagues_config(
    config_file: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Carrega e valida o ficheiro config/leagues.yaml."""

    if config_file is None:
        paths = load_paths_config()
        config_path = paths["project_root"] / "config" / "leagues.yaml"
    else:
        config_path = Path(config_file).expanduser().resolve()

    if not config_path.exists():
        raise LeagueConfigurationError(
            f"Ficheiro de ligas inexistente: {config_path}"
        )

    try:
        with config_path.open("r", encoding="utf-8") as file:
            leagues = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:
        raise LeagueConfigurationError(
            f"Erro ao interpretar o YAML: {config_path}"
        ) from exc

    if not isinstance(leagues, dict) or not leagues:
        raise LeagueConfigurationError(
            "O ficheiro leagues.yaml não contém ligas válidas."
        )

    validate_leagues_config(leagues)

    return leagues


def validate_leagues_config(
    leagues: dict[str, dict[str, Any]],
) -> None:
    """Valida a estrutura e os cálculos de todas as ligas."""

    errors: list[str] = []

    for league_id, league in leagues.items():
        if not isinstance(league, dict):
            errors.append(
                f"{league_id}: a configuração deve ser um dicionário."
            )
            continue

        missing_fields = REQUIRED_LEAGUE_FIELDS - set(league)

        if missing_fields:
            errors.append(
                f"{league_id}: faltam campos: "
                f"{', '.join(sorted(missing_fields))}"
            )
            continue

        team_count = league["team_count"]
        matches_per_team = league["matches_per_team"]
        total_matches = league["total_matches"]

        if not isinstance(team_count, int) or team_count <= 1:
            errors.append(
                f"{league_id}: team_count inválido: {team_count}"
            )
            continue

        expected_matches_per_team = 2 * (team_count - 1)
        expected_total_matches = team_count * (team_count - 1)

        if matches_per_team != expected_matches_per_team:
            errors.append(
                f"{league_id}: matches_per_team={matches_per_team}; "
                f"esperado={expected_matches_per_team}"
            )

        if total_matches != expected_total_matches:
            errors.append(
                f"{league_id}: total_matches={total_matches}; "
                f"esperado={expected_total_matches}"
            )

        strength_factor = league["league_strength_factor"]

        if not isinstance(strength_factor, (int, float)):
            errors.append(
                f"{league_id}: league_strength_factor deve ser numérico."
            )
        elif strength_factor <= 0:
            errors.append(
                f"{league_id}: league_strength_factor deve ser positivo."
            )

        relegation_places = league["relegation_places"]
        playoff_places = league["playoff_places"]

        if relegation_places < 0 or playoff_places < 0:
            errors.append(
                f"{league_id}: lugares de descida/playoff inválidos."
            )

        if relegation_places + playoff_places >= team_count:
            errors.append(
                f"{league_id}: lugares de descida e playoff excessivos."
            )

    active_leagues = [
        league_id
        for league_id, league in leagues.items()
        if league.get("active") is True
    ]

    if len(active_leagues) != 6:
        errors.append(
            f"Esperadas 6 ligas ativas; encontradas {len(active_leagues)}."
        )

    total_teams = sum(
        league["team_count"]
        for league in leagues.values()
        if league.get("active") is True
    )

    if total_teams != 114:
        errors.append(
            f"Esperadas 114 equipas; encontradas {total_teams}."
        )

    total_matches_all_leagues = sum(
        league["total_matches"]
        for league in leagues.values()
        if league.get("active") is True
    )

    if total_matches_all_leagues != 2058:
        errors.append(
            "Esperados 2.058 jogos; "
            f"encontrados {total_matches_all_leagues}."
        )

    if errors:
        formatted_errors = "\n".join(
            f" - {error}" for error in errors
        )

        raise LeagueConfigurationError(
            "Configuração das ligas inválida:\n"
            f"{formatted_errors}"
        )


def get_active_leagues() -> dict[str, dict[str, Any]]:
    """Devolve apenas as ligas marcadas como ativas."""

    leagues = load_leagues_config()

    return {
        league_id: league
        for league_id, league in leagues.items()
        if league["active"] is True
    }
