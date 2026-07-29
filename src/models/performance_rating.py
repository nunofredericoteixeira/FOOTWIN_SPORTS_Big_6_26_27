# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.config.model_config import load_full_model_config


RATING_MIN = 0.0
RATING_MAX = 100.0
DEFAULT_NEUTRAL_RATING = 50.0


@dataclass(frozen=True)
class RawPerformanceMetrics:
    """
    Métricas desportivas não normalizadas de uma equipa.
    """

    team_id: str
    played: int
    points: int
    goals_for: int
    goals_against: int
    goal_difference: int

    points_per_game: float
    attack_per_game: float
    defence_conceded_per_game: float
    goal_difference_per_game: float


@dataclass(frozen=True)
class PerformanceRating:
    """
    Componentes normalizadas e rating final de uma equipa.
    """

    team_id: str

    points_per_game: float
    attack_per_game: float
    defence_conceded_per_game: float
    goal_difference_per_game: float

    ppg_rating: float
    attack_rating: float
    defence_rating: float
    goal_difference_rating: float

    final_rating: float


class PerformanceRatingError(ValueError):
    """Erro na preparação ou cálculo dos ratings."""


def calculate_performance_ratings(
    records: Iterable[Mapping[str, Any]],
    weights: Mapping[str, Any] | None = None,
) -> list[PerformanceRating]:
    """
    Calcula ratings de desempenho numa escala de 0 a 100.

    A normalização é efetuada dentro do grupo recebido,
    normalmente uma liga completa.

    Um valor superior representa melhor desempenho.
    Na componente defensiva, sofrer menos golos é melhor.
    """

    prepared_metrics = [
        prepare_raw_metrics(record)
        for record in records
    ]

    if not prepared_metrics:
        raise PerformanceRatingError(
            "Não existem desempenhos para calcular ratings."
        )

    ensure_unique_team_ids(prepared_metrics)

    final_weights = (
        normalize_weights(weights)
        if weights is not None
        else load_performance_weights()
    )

    ppg_values = [
        item.points_per_game
        for item in prepared_metrics
    ]

    attack_values = [
        item.attack_per_game
        for item in prepared_metrics
    ]

    defence_values = [
        item.defence_conceded_per_game
        for item in prepared_metrics
    ]

    goal_difference_values = [
        item.goal_difference_per_game
        for item in prepared_metrics
    ]

    ratings: list[PerformanceRating] = []

    for metrics in prepared_metrics:
        ppg_rating = min_max_rating(
            value=metrics.points_per_game,
            values=ppg_values,
            higher_is_better=True,
        )

        attack_rating = min_max_rating(
            value=metrics.attack_per_game,
            values=attack_values,
            higher_is_better=True,
        )

        defence_rating = min_max_rating(
            value=metrics.defence_conceded_per_game,
            values=defence_values,
            higher_is_better=False,
        )

        goal_difference_rating = min_max_rating(
            value=metrics.goal_difference_per_game,
            values=goal_difference_values,
            higher_is_better=True,
        )

        final_rating = weighted_rating(
            ppg_rating=ppg_rating,
            attack_rating=attack_rating,
            defence_rating=defence_rating,
            goal_difference_rating=goal_difference_rating,
            weights=final_weights,
        )

        ratings.append(
            PerformanceRating(
                team_id=metrics.team_id,
                points_per_game=round(
                    metrics.points_per_game,
                    6,
                ),
                attack_per_game=round(
                    metrics.attack_per_game,
                    6,
                ),
                defence_conceded_per_game=round(
                    metrics.defence_conceded_per_game,
                    6,
                ),
                goal_difference_per_game=round(
                    metrics.goal_difference_per_game,
                    6,
                ),
                ppg_rating=round(ppg_rating, 6),
                attack_rating=round(attack_rating, 6),
                defence_rating=round(defence_rating, 6),
                goal_difference_rating=round(
                    goal_difference_rating,
                    6,
                ),
                final_rating=round(final_rating, 6),
            )
        )

    return sorted(
        ratings,
        key=lambda item: (
            -item.final_rating,
            item.team_id,
        ),
    )


def prepare_raw_metrics(
    record: Mapping[str, Any],
) -> RawPerformanceMetrics:
    """
    Valida um registo e calcula as métricas por jogo.
    """

    team_id = clean_team_id(
        record.get("team_id")
    )

    played = to_integer(
        value=record.get("played"),
        field_name="played",
        minimum=1,
    )

    points = to_integer(
        value=record.get("points"),
        field_name="points",
    )

    goals_for = to_integer(
        value=record.get("goals_for"),
        field_name="goals_for",
        minimum=0,
    )

    goals_against = to_integer(
        value=record.get("goals_against"),
        field_name="goals_against",
        minimum=0,
    )

    goal_difference = to_integer(
        value=record.get("goal_difference"),
        field_name="goal_difference",
    )

    expected_goal_difference = (
        goals_for
        - goals_against
    )

    if goal_difference != expected_goal_difference:
        raise PerformanceRatingError(
            f"Equipa {team_id}: goal_difference incorreto. "
            f"Esperado={expected_goal_difference}; "
            f"encontrado={goal_difference}"
        )

    return RawPerformanceMetrics(
        team_id=team_id,
        played=played,
        points=points,
        goals_for=goals_for,
        goals_against=goals_against,
        goal_difference=goal_difference,
        points_per_game=points / played,
        attack_per_game=goals_for / played,
        defence_conceded_per_game=(
            goals_against / played
        ),
        goal_difference_per_game=(
            goal_difference / played
        ),
    )


def min_max_rating(
    value: float,
    values: Iterable[float],
    higher_is_better: bool = True,
) -> float:
    """
    Normaliza um valor para a escala de 0 a 100.

    Quando todos os valores são iguais, devolve 50.
    """

    numeric_values = [
        float(item)
        for item in values
    ]

    if not numeric_values:
        raise PerformanceRatingError(
            "Não existem valores para normalizar."
        )

    if not math.isfinite(float(value)):
        raise PerformanceRatingError(
            "O valor a normalizar não é finito."
        )

    if any(
        not math.isfinite(item)
        for item in numeric_values
    ):
        raise PerformanceRatingError(
            "Existem valores não finitos na normalização."
        )

    minimum = min(numeric_values)
    maximum = max(numeric_values)

    if math.isclose(
        minimum,
        maximum,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        return DEFAULT_NEUTRAL_RATING

    normalized = (
        (float(value) - minimum)
        / (maximum - minimum)
    )

    if not higher_is_better:
        normalized = 1.0 - normalized

    rating = (
        RATING_MIN
        + normalized * (RATING_MAX - RATING_MIN)
    )

    return clamp_rating(rating)


def weighted_rating(
    ppg_rating: float,
    attack_rating: float,
    defence_rating: float,
    goal_difference_rating: float,
    weights: Mapping[str, float],
) -> float:
    """
    Calcula a média ponderada das quatro componentes.
    """

    normalized_weights = normalize_weights(weights)

    final_rating = (
        float(ppg_rating)
        * normalized_weights["ppg_weight"]
        + float(attack_rating)
        * normalized_weights["attack_weight"]
        + float(defence_rating)
        * normalized_weights["defence_weight"]
        + float(goal_difference_rating)
        * normalized_weights[
            "goal_difference_weight"
        ]
    )

    return clamp_rating(final_rating)


def load_performance_weights() -> dict[str, float]:
    """
    Carrega os pesos de desempenho da configuração oficial.
    """

    config = load_full_model_config()

    try:
        configured_weights = config[
            "weights"
        ]["performance"]

    except KeyError as exc:
        raise PerformanceRatingError(
            "Falta a configuração weights.performance."
        ) from exc

    return normalize_weights(
        configured_weights
    )


def normalize_weights(
    weights: Mapping[str, Any],
) -> dict[str, float]:
    """
    Valida e normaliza os quatro pesos do modelo.
    """

    required_fields = (
        "ppg_weight",
        "attack_weight",
        "defence_weight",
        "goal_difference_weight",
    )

    parsed: dict[str, float] = {}

    for field_name in required_fields:
        if field_name not in weights:
            raise PerformanceRatingError(
                f"Falta o peso obrigatório: {field_name}"
            )

        try:
            value = float(
                weights[field_name]
            )

        except (TypeError, ValueError) as exc:
            raise PerformanceRatingError(
                f"Peso inválido: {field_name}"
            ) from exc

        if not math.isfinite(value):
            raise PerformanceRatingError(
                f"Peso não finito: {field_name}"
            )

        if value < 0:
            raise PerformanceRatingError(
                f"O peso {field_name} não pode ser negativo."
            )

        parsed[field_name] = value

    total = sum(parsed.values())

    if total <= 0:
        raise PerformanceRatingError(
            "A soma dos pesos deve ser superior a zero."
        )

    return {
        field_name: value / total
        for field_name, value in parsed.items()
    }


def ensure_unique_team_ids(
    metrics: Iterable[RawPerformanceMetrics],
) -> None:
    """
    Impede duas linhas da mesma equipa no mesmo cálculo.
    """

    seen: set[str] = set()
    duplicates: set[str] = set()

    for item in metrics:
        if item.team_id in seen:
            duplicates.add(item.team_id)

        seen.add(item.team_id)

    if duplicates:
        duplicate_text = ", ".join(
            sorted(duplicates)
        )

        raise PerformanceRatingError(
            "Existem equipas duplicadas no cálculo: "
            f"{duplicate_text}"
        )


def clean_team_id(
    value: Any,
) -> str:
    if value is None:
        raise PerformanceRatingError(
            "team_id vazio."
        )

    team_id = str(value).strip()

    if not team_id:
        raise PerformanceRatingError(
            "team_id vazio."
        )

    return team_id


def to_integer(
    value: Any,
    field_name: str,
    minimum: int | None = None,
) -> int:
    if value is None or value == "":
        raise PerformanceRatingError(
            f"{field_name} vazio."
        )

    try:
        numeric_value = float(value)

    except (TypeError, ValueError) as exc:
        raise PerformanceRatingError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(numeric_value):
        raise PerformanceRatingError(
            f"{field_name} não é finito."
        )

    if not numeric_value.is_integer():
        raise PerformanceRatingError(
            f"{field_name} deve ser inteiro."
        )

    integer_value = int(numeric_value)

    if (
        minimum is not None
        and integer_value < minimum
    ):
        raise PerformanceRatingError(
            f"{field_name} deve ser igual "
            f"ou superior a {minimum}."
        )

    return integer_value


def clamp_rating(
    value: float,
) -> float:
    """
    Garante que o rating permanece entre 0 e 100.
    """

    return max(
        RATING_MIN,
        min(RATING_MAX, float(value)),
    )
