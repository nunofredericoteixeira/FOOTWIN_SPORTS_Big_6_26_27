# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


DEFAULT_HOME_GOALS_AVERAGE = 1.55
DEFAULT_AWAY_GOALS_AVERAGE = 1.25

MIN_GOALS_AVERAGE = 0.10
MAX_GOALS_AVERAGE = 5.00

MIN_HOME_ADVANTAGE = 0.80
MAX_HOME_ADVANTAGE = 1.30


@dataclass(frozen=True)
class LeagueGoalEnvironment:
    """
    Contexto médio de golos de uma liga.
    """

    league_id: str

    matches_played: int
    total_home_goals: int
    total_away_goals: int

    home_goals_average: float
    away_goals_average: float
    total_goals_average: float

    home_attack_factor: float
    away_attack_factor: float


class LeagueGoalEnvironmentError(ValueError):
    """Erro no cálculo do contexto de golos da liga."""


def calculate_league_goal_environment(
    league_id: str,
    matches: Iterable[Mapping[str, Any]],
    fallback_home_average: float = DEFAULT_HOME_GOALS_AVERAGE,
    fallback_away_average: float = DEFAULT_AWAY_GOALS_AVERAGE,
) -> LeagueGoalEnvironment:
    """
    Calcula as médias de golos de uma liga.

    Apenas considera jogos com:

        status = PLAYED ou AWARDED
        home_goals preenchido
        away_goals preenchido

    Se não existirem jogos concluídos, utiliza os valores fallback.
    """

    final_league_id = clean_required_text(
        league_id,
        "league_id",
    ).upper()

    parsed_fallback_home = validate_goal_average(
        fallback_home_average,
        "fallback_home_average",
    )

    parsed_fallback_away = validate_goal_average(
        fallback_away_average,
        "fallback_away_average",
    )

    matches_played = 0
    total_home_goals = 0
    total_away_goals = 0

    for match in matches:
        match_league_id = clean_required_text(
            match.get("league_id"),
            "match.league_id",
        ).upper()

        if match_league_id != final_league_id:
            raise LeagueGoalEnvironmentError(
                f"Foi encontrado um jogo da liga "
                f"{match_league_id} no cálculo de {final_league_id}."
            )

        status = clean_required_text(
            match.get("status"),
            "status",
        ).upper()

        if status not in {
            "PLAYED",
            "AWARDED",
        }:
            continue

        home_goals = to_non_negative_integer(
            match.get("home_goals"),
            "home_goals",
        )

        away_goals = to_non_negative_integer(
            match.get("away_goals"),
            "away_goals",
        )

        matches_played += 1
        total_home_goals += home_goals
        total_away_goals += away_goals

    if matches_played == 0:
        home_average = parsed_fallback_home
        away_average = parsed_fallback_away

    else:
        home_average = (
            total_home_goals
            / matches_played
        )

        away_average = (
            total_away_goals
            / matches_played
        )

    total_average = (
        home_average
        + away_average
    )

    home_attack_factor, away_attack_factor = (
        calculate_home_advantage_factors(
            home_goals_average=home_average,
            away_goals_average=away_average,
        )
    )

    return LeagueGoalEnvironment(
        league_id=final_league_id,
        matches_played=matches_played,
        total_home_goals=total_home_goals,
        total_away_goals=total_away_goals,
        home_goals_average=round(
            home_average,
            6,
        ),
        away_goals_average=round(
            away_average,
            6,
        ),
        total_goals_average=round(
            total_average,
            6,
        ),
        home_attack_factor=round(
            home_attack_factor,
            6,
        ),
        away_attack_factor=round(
            away_attack_factor,
            6,
        ),
    )


def calculate_home_advantage_factors(
    home_goals_average: float,
    away_goals_average: float,
) -> tuple[float, float]:
    """
    Calcula fatores simétricos de vantagem da casa.

    A média das duas componentes permanece próxima de 1,00.

    Exemplo:

        casa = 1,60
        fora = 1,20

        proporção casa = 1,60 / 1,40 = 1,142857
        proporção fora = 1,20 / 1,40 = 0,857143
    """

    home_average = validate_goal_average(
        home_goals_average,
        "home_goals_average",
    )

    away_average = validate_goal_average(
        away_goals_average,
        "away_goals_average",
    )

    neutral_average = (
        home_average
        + away_average
    ) / 2.0

    if neutral_average <= 0:
        raise LeagueGoalEnvironmentError(
            "A média neutra de golos deve ser superior a zero."
        )

    raw_home_factor = (
        home_average
        / neutral_average
    )

    raw_away_factor = (
        away_average
        / neutral_average
    )

    home_factor = clamp(
        raw_home_factor,
        MIN_HOME_ADVANTAGE,
        MAX_HOME_ADVANTAGE,
    )

    away_factor = clamp(
        raw_away_factor,
        MIN_HOME_ADVANTAGE,
        MAX_HOME_ADVANTAGE,
    )

    return (
        round(home_factor, 6),
        round(away_factor, 6),
    )


def calculate_expected_goals_base(
    environment: LeagueGoalEnvironment,
    home_matchup_factor: float,
    away_matchup_factor: float,
) -> tuple[float, float]:
    """
    Calcula os golos esperados preliminares do jogo.

    Estes valores ainda não utilizam Poisson.

    Fórmulas:

        xG casa =
            média de golos da casa
            × fator do confronto da casa

        xG visitante =
            média de golos visitante
            × fator do confronto visitante
    """

    home_factor = validate_positive_factor(
        home_matchup_factor,
        "home_matchup_factor",
    )

    away_factor = validate_positive_factor(
        away_matchup_factor,
        "away_matchup_factor",
    )

    expected_home_goals = (
        environment.home_goals_average
        * home_factor
    )

    expected_away_goals = (
        environment.away_goals_average
        * away_factor
    )

    return (
        round(
            clamp(
                expected_home_goals,
                0.05,
                5.00,
            ),
            6,
        ),
        round(
            clamp(
                expected_away_goals,
                0.05,
                5.00,
            ),
            6,
        ),
    )


def build_default_league_environments(
    league_ids: Iterable[str],
    home_average: float = DEFAULT_HOME_GOALS_AVERAGE,
    away_average: float = DEFAULT_AWAY_GOALS_AVERAGE,
) -> dict[str, LeagueGoalEnvironment]:
    """
    Cria contextos fallback para várias ligas.
    """

    environments: dict[
        str,
        LeagueGoalEnvironment,
    ] = {}

    for league_id in league_ids:
        final_league_id = clean_required_text(
            league_id,
            "league_id",
        ).upper()

        if final_league_id in environments:
            raise LeagueGoalEnvironmentError(
                f"Liga duplicada: {final_league_id}"
            )

        environments[final_league_id] = (
            calculate_league_goal_environment(
                league_id=final_league_id,
                matches=[],
                fallback_home_average=home_average,
                fallback_away_average=away_average,
            )
        )

    if not environments:
        raise LeagueGoalEnvironmentError(
            "Não existem ligas para criar contextos."
        )

    return environments


def validate_goal_average(
    value: Any,
    field_name: str,
) -> float:
    parsed = to_finite_float(
        value,
        field_name,
    )

    if not (
        MIN_GOALS_AVERAGE
        <= parsed
        <= MAX_GOALS_AVERAGE
    ):
        raise LeagueGoalEnvironmentError(
            f"{field_name} deve estar entre "
            f"{MIN_GOALS_AVERAGE} e {MAX_GOALS_AVERAGE}."
        )

    return parsed


def validate_positive_factor(
    value: Any,
    field_name: str,
) -> float:
    parsed = to_finite_float(
        value,
        field_name,
    )

    if parsed <= 0:
        raise LeagueGoalEnvironmentError(
            f"{field_name} deve ser superior a zero."
        )

    return parsed


def to_non_negative_integer(
    value: Any,
    field_name: str,
) -> int:
    if value is None or value == "":
        raise LeagueGoalEnvironmentError(
            f"{field_name} vazio."
        )

    try:
        numeric = float(value)

    except (TypeError, ValueError) as exc:
        raise LeagueGoalEnvironmentError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(numeric):
        raise LeagueGoalEnvironmentError(
            f"{field_name} não é finito."
        )

    if not numeric.is_integer():
        raise LeagueGoalEnvironmentError(
            f"{field_name} deve ser inteiro."
        )

    integer_value = int(numeric)

    if integer_value < 0:
        raise LeagueGoalEnvironmentError(
            f"{field_name} não pode ser negativo."
        )

    return integer_value


def to_finite_float(
    value: Any,
    field_name: str,
) -> float:
    try:
        parsed = float(value)

    except (TypeError, ValueError) as exc:
        raise LeagueGoalEnvironmentError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(parsed):
        raise LeagueGoalEnvironmentError(
            f"{field_name} não é finito."
        )

    return parsed


def clean_required_text(
    value: Any,
    field_name: str,
) -> str:
    if value is None:
        raise LeagueGoalEnvironmentError(
            f"{field_name} vazio."
        )

    cleaned = str(value).strip()

    if not cleaned:
        raise LeagueGoalEnvironmentError(
            f"{field_name} vazio."
        )

    return cleaned


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(
        minimum,
        min(
            maximum,
            float(value),
        ),
    )
