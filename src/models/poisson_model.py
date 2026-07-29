# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


DEFAULT_MAX_GOALS = 10
MIN_EXPECTED_GOALS = 0.01
MAX_EXPECTED_GOALS = 10.0
PROBABILITY_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ScoreProbability:
    home_goals: int
    away_goals: int
    probability: float


@dataclass(frozen=True)
class MatchOutcomeProbabilities:
    home_win: float
    draw: float
    away_win: float


@dataclass(frozen=True)
class PoissonMatchDistribution:
    expected_home_goals: float
    expected_away_goals: float
    max_goals: int

    score_probabilities: tuple[ScoreProbability, ...]

    home_win_probability: float
    draw_probability: float
    away_win_probability: float

    total_probability: float
    omitted_probability: float


class PoissonModelError(ValueError):
    """Erro durante o cálculo da distribuição de Poisson."""


def poisson_probability(
    expected_goals: float,
    goals: int,
) -> float:
    """
    Calcula a probabilidade de marcar exatamente determinado
    número de golos segundo a distribuição de Poisson.

    Fórmula:

        P(X = k) = exp(-lambda) * lambda^k / k!
    """

    lambda_value = validate_expected_goals(
        expected_goals,
        "expected_goals",
    )

    final_goals = validate_goal_count(
        goals,
        "goals",
    )

    probability = (
        math.exp(-lambda_value)
        * math.pow(lambda_value, final_goals)
        / math.factorial(final_goals)
    )

    return probability


def build_goal_probabilities(
    expected_goals: float,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> list[float]:
    """
    Cria as probabilidades de marcar entre 0 e max_goals.
    """

    lambda_value = validate_expected_goals(
        expected_goals,
        "expected_goals",
    )

    final_max_goals = validate_max_goals(
        max_goals
    )

    return [
        poisson_probability(
            expected_goals=lambda_value,
            goals=goals,
        )
        for goals in range(
            final_max_goals + 1
        )
    ]


def build_score_matrix(
    expected_home_goals: float,
    expected_away_goals: float,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> list[list[float]]:
    """
    Cria a matriz de probabilidades dos marcadores.

    A linha representa os golos da equipa da casa.
    A coluna representa os golos da equipa visitante.
    """

    home_probabilities = build_goal_probabilities(
        expected_goals=expected_home_goals,
        max_goals=max_goals,
    )

    away_probabilities = build_goal_probabilities(
        expected_goals=expected_away_goals,
        max_goals=max_goals,
    )

    return [
        [
            home_probability
            * away_probability
            for away_probability in away_probabilities
        ]
        for home_probability in home_probabilities
    ]


def calculate_match_outcomes(
    score_matrix: Iterable[Iterable[float]],
) -> MatchOutcomeProbabilities:
    """
    Soma a matriz para obter:

    - vitória da casa;
    - empate;
    - vitória visitante.
    """

    matrix = [
        [
            validate_probability(
                value,
                "score_probability",
            )
            for value in row
        ]
        for row in score_matrix
    ]

    if not matrix:
        raise PoissonModelError(
            "A matriz de resultados está vazia."
        )

    row_length = len(
        matrix[0]
    )

    if row_length == 0:
        raise PoissonModelError(
            "A matriz de resultados não possui colunas."
        )

    if any(
        len(row) != row_length
        for row in matrix
    ):
        raise PoissonModelError(
            "A matriz de resultados não é retangular."
        )

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            if home_goals > away_goals:
                home_win += probability

            elif home_goals == away_goals:
                draw += probability

            else:
                away_win += probability

    return MatchOutcomeProbabilities(
        home_win=home_win,
        draw=draw,
        away_win=away_win,
    )


def build_match_distribution(
    expected_home_goals: float,
    expected_away_goals: float,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> PoissonMatchDistribution:
    """
    Cria a distribuição completa de um jogo.
    """

    home_xg = validate_expected_goals(
        expected_home_goals,
        "expected_home_goals",
    )

    away_xg = validate_expected_goals(
        expected_away_goals,
        "expected_away_goals",
    )

    final_max_goals = validate_max_goals(
        max_goals
    )

    matrix = build_score_matrix(
        expected_home_goals=home_xg,
        expected_away_goals=away_xg,
        max_goals=final_max_goals,
    )

    outcomes = calculate_match_outcomes(
        matrix
    )

    score_probabilities: list[
        ScoreProbability
    ] = []

    total_probability = 0.0

    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            total_probability += probability

            score_probabilities.append(
                ScoreProbability(
                    home_goals=home_goals,
                    away_goals=away_goals,
                    probability=probability,
                )
            )

    omitted_probability = max(
        0.0,
        1.0 - total_probability,
    )

    return PoissonMatchDistribution(
        expected_home_goals=round(
            home_xg,
            6,
        ),
        expected_away_goals=round(
            away_xg,
            6,
        ),
        max_goals=final_max_goals,
        score_probabilities=tuple(
            sorted(
                score_probabilities,
                key=lambda item: (
                    -item.probability,
                    item.home_goals,
                    item.away_goals,
                ),
            )
        ),
        home_win_probability=round(
            outcomes.home_win,
            12,
        ),
        draw_probability=round(
            outcomes.draw,
            12,
        ),
        away_win_probability=round(
            outcomes.away_win,
            12,
        ),
        total_probability=round(
            total_probability,
            12,
        ),
        omitted_probability=round(
            omitted_probability,
            12,
        ),
    )


def get_most_likely_scores(
    distribution: PoissonMatchDistribution,
    limit: int = 10,
) -> list[ScoreProbability]:
    """
    Devolve os marcadores exatos mais prováveis.
    """

    if limit <= 0:
        raise PoissonModelError(
            "O limite deve ser superior a zero."
        )

    return list(
        distribution.score_probabilities[
            :limit
        ]
    )


def get_score_probability(
    distribution: PoissonMatchDistribution,
    home_goals: int,
    away_goals: int,
) -> float:
    """
    Obtém a probabilidade de um marcador específico.
    """

    final_home_goals = validate_goal_count(
        home_goals,
        "home_goals",
    )

    final_away_goals = validate_goal_count(
        away_goals,
        "away_goals",
    )

    if (
        final_home_goals
        > distribution.max_goals
        or final_away_goals
        > distribution.max_goals
    ):
        return 0.0

    for score in distribution.score_probabilities:
        if (
            score.home_goals == final_home_goals
            and score.away_goals == final_away_goals
        ):
            return score.probability

    return 0.0


def calculate_over_probability(
    distribution: PoissonMatchDistribution,
    line: float,
) -> float:
    """
    Calcula a probabilidade de o total de golos ser superior
    a uma linha decimal terminada em .5.

    Exemplos:

        0.5
        1.5
        2.5
        3.5
    """

    final_line = validate_half_goal_line(
        line
    )

    probability = sum(
        score.probability
        for score in distribution.score_probabilities
        if (
            score.home_goals
            + score.away_goals
        ) > final_line
    )

    return probability


def calculate_under_probability(
    distribution: PoissonMatchDistribution,
    line: float,
) -> float:
    """
    Calcula a probabilidade de o total de golos ser inferior
    a uma linha decimal terminada em .5.
    """

    final_line = validate_half_goal_line(
        line
    )

    probability = sum(
        score.probability
        for score in distribution.score_probabilities
        if (
            score.home_goals
            + score.away_goals
        ) < final_line
    )

    return probability


def calculate_both_teams_to_score_probability(
    distribution: PoissonMatchDistribution,
) -> float:
    """
    Calcula a probabilidade de ambas as equipas marcarem.
    """

    return sum(
        score.probability
        for score in distribution.score_probabilities
        if (
            score.home_goals >= 1
            and score.away_goals >= 1
        )
    )


def calculate_clean_sheet_probabilities(
    distribution: PoissonMatchDistribution,
) -> tuple[float, float]:
    """
    Devolve:

    - probabilidade de a equipa da casa não sofrer golos;
    - probabilidade de a equipa visitante não sofrer golos.
    """

    home_clean_sheet = sum(
        score.probability
        for score in distribution.score_probabilities
        if score.away_goals == 0
    )

    away_clean_sheet = sum(
        score.probability
        for score in distribution.score_probabilities
        if score.home_goals == 0
    )

    return (
        home_clean_sheet,
        away_clean_sheet,
    )


def validate_expected_goals(
    value: float,
    field_name: str,
) -> float:
    try:
        parsed = float(value)

    except (TypeError, ValueError) as exc:
        raise PoissonModelError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(parsed):
        raise PoissonModelError(
            f"{field_name} não é finito."
        )

    if not (
        MIN_EXPECTED_GOALS
        <= parsed
        <= MAX_EXPECTED_GOALS
    ):
        raise PoissonModelError(
            f"{field_name} deve estar entre "
            f"{MIN_EXPECTED_GOALS} e "
            f"{MAX_EXPECTED_GOALS}."
        )

    return parsed


def validate_goal_count(
    value: int,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise PoissonModelError(
            f"{field_name} deve ser inteiro."
        )

    try:
        numeric = float(value)

    except (TypeError, ValueError) as exc:
        raise PoissonModelError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(numeric):
        raise PoissonModelError(
            f"{field_name} não é finito."
        )

    if not numeric.is_integer():
        raise PoissonModelError(
            f"{field_name} deve ser inteiro."
        )

    integer_value = int(numeric)

    if integer_value < 0:
        raise PoissonModelError(
            f"{field_name} não pode ser negativo."
        )

    return integer_value


def validate_max_goals(
    value: int,
) -> int:
    final_value = validate_goal_count(
        value,
        "max_goals",
    )

    if final_value < 3:
        raise PoissonModelError(
            "max_goals deve ser pelo menos 3."
        )

    if final_value > 25:
        raise PoissonModelError(
            "max_goals não pode ser superior a 25."
        )

    return final_value


def validate_probability(
    value: float,
    field_name: str,
) -> float:
    try:
        parsed = float(value)

    except (TypeError, ValueError) as exc:
        raise PoissonModelError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(parsed):
        raise PoissonModelError(
            f"{field_name} não é finito."
        )

    if not 0.0 <= parsed <= 1.0:
        raise PoissonModelError(
            f"{field_name} deve estar entre 0 e 1."
        )

    return parsed


def validate_half_goal_line(
    value: float,
) -> float:
    try:
        parsed = float(value)

    except (TypeError, ValueError) as exc:
        raise PoissonModelError(
            "Linha de golos inválida."
        ) from exc

    if not math.isfinite(parsed):
        raise PoissonModelError(
            "Linha de golos não é finita."
        )

    if parsed < 0.5:
        raise PoissonModelError(
            "A linha de golos deve ser pelo menos 0.5."
        )

    doubled = parsed * 2

    if not math.isclose(
        doubled,
        round(doubled),
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        raise PoissonModelError(
            "A linha de golos deve terminar em .0 ou .5."
        )

    if math.isclose(
        parsed,
        round(parsed),
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        raise PoissonModelError(
            "Nesta fase, apenas são aceites linhas terminadas em .5."
        )

    return parsed
