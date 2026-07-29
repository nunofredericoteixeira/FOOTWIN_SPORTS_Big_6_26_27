# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


NEUTRAL_RATING = 50.0
NEUTRAL_STRENGTH = 1.0

DEFAULT_STRENGTH_SPREAD = 0.40
MIN_STRENGTH = 0.50
MAX_STRENGTH = 1.50


@dataclass(frozen=True)
class TeamStrength:
    team_id: str
    league_id: str

    attack_rating: float
    defence_rating: float
    absolute_rating: float

    attack_strength: float
    defence_strength: float
    overall_strength: float

    rating_confidence: float


class TeamStrengthError(ValueError):
    """Erro durante o cálculo das forças das equipas."""


def rating_to_strength(
    rating: float,
    neutral_rating: float = NEUTRAL_RATING,
    spread: float = DEFAULT_STRENGTH_SPREAD,
    minimum: float = MIN_STRENGTH,
    maximum: float = MAX_STRENGTH,
) -> float:
    """
    Converte um rating entre 0 e 100 num multiplicador.

    Com spread=0,40:

        rating 0   -> 0,60
        rating 50  -> 1,00
        rating 100 -> 1,40

    O resultado final é limitado pelos valores minimum e maximum.
    """

    parsed_rating = to_finite_float(
        rating,
        "rating",
    )

    parsed_neutral = to_finite_float(
        neutral_rating,
        "neutral_rating",
    )

    parsed_spread = to_finite_float(
        spread,
        "spread",
    )

    parsed_minimum = to_finite_float(
        minimum,
        "minimum",
    )

    parsed_maximum = to_finite_float(
        maximum,
        "maximum",
    )

    if not 0.0 <= parsed_rating <= 100.0:
        raise TeamStrengthError(
            "rating deve estar entre 0 e 100."
        )

    if not 0.0 <= parsed_neutral <= 100.0:
        raise TeamStrengthError(
            "neutral_rating deve estar entre 0 e 100."
        )

    if parsed_spread < 0:
        raise TeamStrengthError(
            "spread não pode ser negativo."
        )

    if parsed_minimum <= 0:
        raise TeamStrengthError(
            "minimum deve ser superior a zero."
        )

    if parsed_maximum <= parsed_minimum:
        raise TeamStrengthError(
            "maximum deve ser superior a minimum."
        )

    normalized_distance = (
        parsed_rating
        - parsed_neutral
    ) / 50.0

    strength = (
        NEUTRAL_STRENGTH
        + normalized_distance
        * parsed_spread
    )

    return round(
        clamp(
            strength,
            parsed_minimum,
            parsed_maximum,
        ),
        6,
    )


def calculate_team_strength(
    record: Mapping[str, Any],
    spread: float = DEFAULT_STRENGTH_SPREAD,
) -> TeamStrength:
    """
    Calcula as forças ofensiva, defensiva e global
    de uma única equipa.
    """

    team_id = clean_required_text(
        record.get("team_id"),
        "team_id",
    )

    league_id = clean_required_text(
        record.get("league_id"),
        "league_id",
    ).upper()

    attack_rating = validate_rating(
        record.get("attack_rating"),
        "attack_rating",
    )

    defence_rating = validate_rating(
        record.get("defence_rating"),
        "defence_rating",
    )

    absolute_rating = validate_rating(
        record.get("absolute_rating"),
        "absolute_rating",
    )

    confidence = validate_confidence(
        record.get(
            "rating_confidence",
            1.0,
        )
    )

    attack_strength = rating_to_strength(
        rating=attack_rating,
        spread=spread,
    )

    defence_strength = rating_to_strength(
        rating=defence_rating,
        spread=spread,
    )

    overall_strength = rating_to_strength(
        rating=absolute_rating,
        spread=spread,
    )

    return TeamStrength(
        team_id=team_id,
        league_id=league_id,
        attack_rating=round(
            attack_rating,
            6,
        ),
        defence_rating=round(
            defence_rating,
            6,
        ),
        absolute_rating=round(
            absolute_rating,
            6,
        ),
        attack_strength=attack_strength,
        defence_strength=defence_strength,
        overall_strength=overall_strength,
        rating_confidence=round(
            confidence,
            6,
        ),
    )


def calculate_team_strengths(
    records: Iterable[Mapping[str, Any]],
    spread: float = DEFAULT_STRENGTH_SPREAD,
) -> list[TeamStrength]:
    """
    Calcula as forças de várias equipas e ordena-as
    pela força global.
    """

    results: list[TeamStrength] = []
    seen_team_ids: set[str] = set()

    for record in records:
        strength = calculate_team_strength(
            record=record,
            spread=spread,
        )

        if strength.team_id in seen_team_ids:
            raise TeamStrengthError(
                f"Equipa duplicada: {strength.team_id}"
            )

        seen_team_ids.add(
            strength.team_id
        )

        results.append(
            strength
        )

    if not results:
        raise TeamStrengthError(
            "Não existem equipas para calcular forças."
        )

    return sorted(
        results,
        key=lambda item: (
            -item.overall_strength,
            -item.attack_strength,
            -item.defence_strength,
            item.team_id,
        ),
    )


def calculate_matchup_factors(
    home_team: TeamStrength,
    away_team: TeamStrength,
) -> tuple[float, float]:
    """
    Calcula os fatores-base do confronto.

    Quanto melhor a defesa adversária, menor deverá ser
    o potencial ofensivo da equipa.

    Fator da casa:
        ataque da casa / defesa visitante

    Fator visitante:
        ataque visitante / defesa da casa
    """

    if home_team.team_id == away_team.team_id:
        raise TeamStrengthError(
            "Uma equipa não pode jogar contra si própria."
        )

    if home_team.league_id != away_team.league_id:
        raise TeamStrengthError(
            "As equipas devem pertencer à mesma liga."
        )

    home_factor = (
        home_team.attack_strength
        / away_team.defence_strength
    )

    away_factor = (
        away_team.attack_strength
        / home_team.defence_strength
    )

    return (
        round(
            clamp(
                home_factor,
                MIN_STRENGTH,
                MAX_STRENGTH,
            ),
            6,
        ),
        round(
            clamp(
                away_factor,
                MIN_STRENGTH,
                MAX_STRENGTH,
            ),
            6,
        ),
    )


def validate_rating(
    value: Any,
    field_name: str,
) -> float:
    parsed = to_finite_float(
        value,
        field_name,
    )

    if not 0.0 <= parsed <= 100.0:
        raise TeamStrengthError(
            f"{field_name} deve estar entre 0 e 100."
        )

    return parsed


def validate_confidence(
    value: Any,
) -> float:
    parsed = to_finite_float(
        value,
        "rating_confidence",
    )

    if not 0.0 <= parsed <= 1.0:
        raise TeamStrengthError(
            "rating_confidence deve estar entre 0 e 1."
        )

    return parsed


def to_finite_float(
    value: Any,
    field_name: str,
) -> float:
    try:
        parsed = float(value)

    except (TypeError, ValueError) as exc:
        raise TeamStrengthError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(parsed):
        raise TeamStrengthError(
            f"{field_name} não é finito."
        )

    return parsed


def clean_required_text(
    value: Any,
    field_name: str,
) -> str:
    if value is None:
        raise TeamStrengthError(
            f"{field_name} vazio."
        )

    cleaned = str(value).strip()

    if not cleaned:
        raise TeamStrengthError(
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
