# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from dataclasses import replace
from statistics import fmean
from typing import Any, Mapping, Sequence

from src.models.performance_rating import (
    PerformanceRating,
    clamp_rating,
    normalize_weights,
    weighted_rating,
)


class PromotedTeamAdjustmentError(ValueError):
    """Erro no ajuste dos ratings das equipas promovidas."""


_PROMOTION_FACTOR_NAMES = {
    "CHAMPION": "champion_factor",
    "DIRECT": "direct_factor",
    "PLAYOFF": "playoff_factor",
}


def adjust_promoted_team_ratings(
    ratings: Sequence[PerformanceRating],
    source_by_team: Mapping[str, Mapping[str, Any]],
    promotion_config: Mapping[str, Any],
    performance_weights: Mapping[str, Any],
) -> list[PerformanceRating]:
    """
    Ajusta as equipas promovidas para o contexto da primeira divisão.

    Processo:
    1. Calcula uma referência usando os últimos clubes não promovidos.
    2. Aplica o fator correspondente ao método de promoção.
    3. Faz regressão parcial para a referência da parte inferior da liga.
    4. Recalcula o rating final com os pesos oficiais.

    As equipas não promovidas permanecem inalteradas.
    """

    if not ratings:
        raise PromotedTeamAdjustmentError(
            "Não existem ratings para ajustar."
        )

    normalized_weights = normalize_weights(
        performance_weights
    )

    regression_weight = _parse_fraction(
        promotion_config.get(
            "first_division_regression_weight"
        ),
        field_name="first_division_regression_weight",
        allow_zero=True,
    )

    reference_percentage = _parse_fraction(
        promotion_config.get(
            "lower_table_reference_percentage"
        ),
        field_name="lower_table_reference_percentage",
        allow_zero=False,
    )

    permanent_ratings = [
        rating
        for rating in ratings
        if not _is_promoted(
            source_by_team.get(
                rating.team_id,
                {},
            )
        )
    ]

    if not permanent_ratings:
        raise PromotedTeamAdjustmentError(
            "Não existem equipas permanentes para calcular "
            "a referência da primeira divisão."
        )

    reference = calculate_lower_table_reference(
        ratings=permanent_ratings,
        reference_percentage=reference_percentage,
    )

    adjusted: list[PerformanceRating] = []

    for rating in ratings:
        source = source_by_team.get(
            rating.team_id
        )

        if source is None:
            raise PromotedTeamAdjustmentError(
                f"Não existe registo de origem para {rating.team_id}."
            )

        if not _is_promoted(source):
            adjusted.append(rating)
            continue

        promotion_method = _clean_promotion_method(
            source.get("promotion_method")
        )

        general_factor = _promotion_factor(
            promotion_config=promotion_config,
            group_name="general",
            promotion_method=promotion_method,
        )

        attack_factor = _promotion_factor(
            promotion_config=promotion_config,
            group_name="attack",
            promotion_method=promotion_method,
        )

        defence_factor = _promotion_factor(
            promotion_config=promotion_config,
            group_name="defence",
            promotion_method=promotion_method,
        )

        adjusted_ppg = _adjust_component(
            original=rating.ppg_rating,
            factor=general_factor,
            reference=reference["ppg_rating"],
            regression_weight=regression_weight,
        )

        adjusted_attack = _adjust_component(
            original=rating.attack_rating,
            factor=attack_factor,
            reference=reference["attack_rating"],
            regression_weight=regression_weight,
        )

        adjusted_defence = _adjust_component(
            original=rating.defence_rating,
            factor=defence_factor,
            reference=reference["defence_rating"],
            regression_weight=regression_weight,
        )

        adjusted_goal_difference = _adjust_component(
            original=rating.goal_difference_rating,
            factor=general_factor,
            reference=reference["goal_difference_rating"],
            regression_weight=regression_weight,
        )

        adjusted_final = weighted_rating(
            ppg_rating=adjusted_ppg,
            attack_rating=adjusted_attack,
            defence_rating=adjusted_defence,
            goal_difference_rating=adjusted_goal_difference,
            weights=normalized_weights,
        )

        adjusted.append(
            replace(
                rating,
                ppg_rating=round(adjusted_ppg, 6),
                attack_rating=round(adjusted_attack, 6),
                defence_rating=round(adjusted_defence, 6),
                goal_difference_rating=round(
                    adjusted_goal_difference,
                    6,
                ),
                final_rating=round(adjusted_final, 6),
            )
        )

    return sorted(
        adjusted,
        key=lambda item: (
            -item.final_rating,
            item.team_id,
        ),
    )


def calculate_lower_table_reference(
    ratings: Sequence[PerformanceRating],
    reference_percentage: float,
) -> dict[str, float]:
    """
    Calcula a média das componentes dos últimos X% da liga.

    A ordenação usa o rating final original das equipas permanentes.
    """

    if not ratings:
        raise PromotedTeamAdjustmentError(
            "Não existem ratings para calcular a referência inferior."
        )

    percentage = _parse_fraction(
        reference_percentage,
        field_name="reference_percentage",
        allow_zero=False,
    )

    ordered = sorted(
        ratings,
        key=lambda item: (
            item.final_rating,
            item.team_id,
        ),
    )

    reference_count = max(
        1,
        math.ceil(
            len(ordered)
            * percentage
        ),
    )

    selected = ordered[
        :reference_count
    ]

    return {
        "ppg_rating": fmean(
            item.ppg_rating
            for item in selected
        ),
        "attack_rating": fmean(
            item.attack_rating
            for item in selected
        ),
        "defence_rating": fmean(
            item.defence_rating
            for item in selected
        ),
        "goal_difference_rating": fmean(
            item.goal_difference_rating
            for item in selected
        ),
        "final_rating": fmean(
            item.final_rating
            for item in selected
        ),
        "reference_count": float(
            reference_count
        ),
    }


def _adjust_component(
    original: float,
    factor: float,
    reference: float,
    regression_weight: float,
) -> float:
    """
    Aplica fator de promoção e regressão para a referência inferior.

    Fórmula:
        ajustado =
            (original × fator) × (1 - regressão)
            + referência × regressão
    """

    factored_value = (
        float(original)
        * float(factor)
    )

    adjusted_value = (
        factored_value
        * (1.0 - float(regression_weight))
        + float(reference)
        * float(regression_weight)
    )

    return clamp_rating(
        adjusted_value
    )


def _promotion_factor(
    promotion_config: Mapping[str, Any],
    group_name: str,
    promotion_method: str,
) -> float:
    try:
        group = promotion_config[
            group_name
        ]
        factor_name = _PROMOTION_FACTOR_NAMES[
            promotion_method
        ]
        value = group[
            factor_name
        ]

    except KeyError as exc:
        raise PromotedTeamAdjustmentError(
            "Configuração de promoção incompleta para "
            f"{group_name}.{promotion_method}."
        ) from exc

    return _parse_fraction(
        value,
        field_name=(
            f"promotion.{group_name}.{factor_name}"
        ),
        allow_zero=False,
    )


def _clean_promotion_method(
    value: Any,
) -> str:
    if value is None:
        raise PromotedTeamAdjustmentError(
            "Método de promoção vazio."
        )

    method = str(value).strip().upper()

    if method not in _PROMOTION_FACTOR_NAMES:
        raise PromotedTeamAdjustmentError(
            "Método de promoção inválido: "
            f"{value}. Esperado: CHAMPION, DIRECT ou PLAYOFF."
        )

    return method


def _is_promoted(
    source: Mapping[str, Any],
) -> bool:
    value = source.get(
        "promoted",
        0,
    )

    if isinstance(value, bool):
        return value

    try:
        return int(value) == 1

    except (TypeError, ValueError):
        return False


def _parse_fraction(
    value: Any,
    field_name: str,
    allow_zero: bool,
) -> float:
    try:
        parsed = float(value)

    except (TypeError, ValueError) as exc:
        raise PromotedTeamAdjustmentError(
            f"Valor inválido em {field_name}: {value}"
        ) from exc

    if not math.isfinite(parsed):
        raise PromotedTeamAdjustmentError(
            f"Valor não finito em {field_name}."
        )

    minimum = 0.0 if allow_zero else 0.0

    if (
        parsed < minimum
        or parsed > 1.0
        or (
            not allow_zero
            and parsed == 0.0
        )
    ):
        interval = "[0, 1]" if allow_zero else "]0, 1]"

        raise PromotedTeamAdjustmentError(
            f"{field_name} deve estar no intervalo {interval}."
        )

    return parsed
