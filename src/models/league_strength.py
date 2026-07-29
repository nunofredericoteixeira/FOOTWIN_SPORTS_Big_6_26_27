# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


NEUTRAL_RATING = 50.0
MIN_RATING = 0.0
MAX_RATING = 100.0


@dataclass(frozen=True)
class LeagueAdjustedRating:
    team_id: str
    league_id: str
    league_relative_rating: float
    league_strength_factor: float
    absolute_rating: float


class LeagueStrengthError(ValueError):
    """Erro no cálculo da força relativa das ligas."""


def calculate_absolute_rating(
    league_relative_rating: float,
    league_strength_factor: float,
    neutral_rating: float = NEUTRAL_RATING,
) -> float:
    """
    Ajusta o rating relativo de uma equipa pela força da liga.

    O fator é aplicado à distância do rating relativamente
    ao ponto neutro, normalmente 50.
    """

    relative_rating = to_finite_float(
        league_relative_rating,
        "league_relative_rating",
    )

    strength_factor = to_finite_float(
        league_strength_factor,
        "league_strength_factor",
    )

    neutral = to_finite_float(
        neutral_rating,
        "neutral_rating",
    )

    if not MIN_RATING <= relative_rating <= MAX_RATING:
        raise LeagueStrengthError(
            "league_relative_rating deve estar entre 0 e 100."
        )

    if not MIN_RATING <= neutral <= MAX_RATING:
        raise LeagueStrengthError(
            "neutral_rating deve estar entre 0 e 100."
        )

    if strength_factor <= 0:
        raise LeagueStrengthError(
            "league_strength_factor deve ser superior a zero."
        )

    adjusted = (
        neutral
        + (relative_rating - neutral)
        * strength_factor
    )

    return round(
        clamp_rating(adjusted),
        6,
    )


def calculate_league_adjusted_ratings(
    ratings: Iterable[Mapping[str, Any]],
    league_factors: Mapping[str, Any],
) -> list[LeagueAdjustedRating]:
    """
    Calcula os ratings absolutos de várias equipas.
    """

    results: list[LeagueAdjustedRating] = []
    seen_team_ids: set[str] = set()

    for record in ratings:
        team_id = clean_required_text(
            record.get("team_id"),
            "team_id",
        )

        league_id = clean_required_text(
            record.get("league_id"),
            "league_id",
        ).upper()

        if team_id in seen_team_ids:
            raise LeagueStrengthError(
                f"Equipa duplicada: {team_id}"
            )

        seen_team_ids.add(team_id)

        if league_id not in league_factors:
            raise LeagueStrengthError(
                f"Falta o fator da liga: {league_id}"
            )

        relative_rating = to_finite_float(
            record.get("league_relative_rating"),
            "league_relative_rating",
        )

        strength_factor = to_finite_float(
            league_factors[league_id],
            f"league_strength_factor[{league_id}]",
        )

        absolute_rating = calculate_absolute_rating(
            league_relative_rating=relative_rating,
            league_strength_factor=strength_factor,
        )

        results.append(
            LeagueAdjustedRating(
                team_id=team_id,
                league_id=league_id,
                league_relative_rating=round(
                    relative_rating,
                    6,
                ),
                league_strength_factor=round(
                    strength_factor,
                    6,
                ),
                absolute_rating=absolute_rating,
            )
        )

    if not results:
        raise LeagueStrengthError(
            "Não existem ratings para ajustar."
        )

    return sorted(
        results,
        key=lambda item: (
            -item.absolute_rating,
            item.team_id,
        ),
    )


def clamp_rating(
    value: float,
) -> float:
    return max(
        MIN_RATING,
        min(MAX_RATING, float(value)),
    )


def to_finite_float(
    value: Any,
    field_name: str,
) -> float:
    try:
        parsed = float(value)

    except (TypeError, ValueError) as exc:
        raise LeagueStrengthError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(parsed):
        raise LeagueStrengthError(
            f"{field_name} não é finito."
        )

    return parsed


def clean_required_text(
    value: Any,
    field_name: str,
) -> str:
    if value is None:
        raise LeagueStrengthError(
            f"{field_name} vazio."
        )

    cleaned = str(value).strip()

    if not cleaned:
        raise LeagueStrengthError(
            f"{field_name} vazio."
        )

    return cleaned
