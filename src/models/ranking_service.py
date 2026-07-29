# -*- coding: utf-8 -*-

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.model_config import load_full_model_config
from src.database.init_database import connect_database


@dataclass(frozen=True)
class TeamRanking:
    team_id: str
    team_name: str
    league_id: str
    league_name: str
    season_label: str
    model_version: str

    global_position: int
    league_position: int

    absolute_rating: float
    league_relative_rating: float
    performance_rating: float
    rating_confidence: float

    gap_to_previous: float
    gap_to_leader: float

    rating_level: str


class RankingServiceError(RuntimeError):
    """Erro durante a criação ou consulta dos rankings."""


def build_team_rankings(
    season_label: str = "2026/27",
    model_version: str | None = None,
    league_id: str | None = None,
    database_path: str | Path | None = None,
) -> list[TeamRanking]:
    """
    Cria o ranking global ou o ranking filtrado por liga.

    O ranking global é ordenado por:

    1. absolute_rating;
    2. performance_rating;
    3. rating_confidence;
    4. team_name.
    """

    final_model_version = (
        model_version.strip()
        if model_version
        else get_configured_model_version()
    )

    connection = connect_database(database_path)

    try:
        rows = load_rating_rows(
            connection=connection,
            season_label=season_label,
            model_version=final_model_version,
        )

    finally:
        connection.close()

    if not rows:
        raise RankingServiceError(
            "Não existem ratings disponíveis para criar o ranking."
        )

    validate_rating_rows(rows)

    sorted_global_rows = sorted(
        rows,
        key=ranking_sort_key,
    )

    global_position_by_team = {
        str(row["team_id"]): position
        for position, row in enumerate(
            sorted_global_rows,
            start=1,
        )
    }

    league_positions = build_league_positions(
        sorted_global_rows
    )

    if league_id:
        requested_league = (
            league_id.strip().upper()
        )

        selected_rows = [
            row
            for row in sorted_global_rows
            if str(row["league_id"]).upper()
            == requested_league
        ]

        if not selected_rows:
            raise RankingServiceError(
                f"Não existem ratings para a liga {requested_league}."
            )

    else:
        selected_rows = sorted_global_rows

    global_leader_rating = float(
        sorted_global_rows[0]["absolute_rating"]
    )

    rankings: list[TeamRanking] = []
    previous_rating: float | None = None

    for row in selected_rows:
        absolute_rating = float(
            row["absolute_rating"]
        )

        if previous_rating is None:
            gap_to_previous = 0.0
        else:
            gap_to_previous = (
                previous_rating
                - absolute_rating
            )

        gap_to_leader = (
            global_leader_rating
            - absolute_rating
        )

        team_id = str(
            row["team_id"]
        )

        rankings.append(
            TeamRanking(
                team_id=team_id,
                team_name=str(
                    row["team_name"]
                ),
                league_id=str(
                    row["league_id"]
                ),
                league_name=str(
                    row["league_name"]
                ),
                season_label=str(
                    row["season_label"]
                ),
                model_version=str(
                    row["model_version"]
                ),
                global_position=(
                    global_position_by_team[
                        team_id
                    ]
                ),
                league_position=(
                    league_positions[
                        team_id
                    ]
                ),
                absolute_rating=round(
                    absolute_rating,
                    6,
                ),
                league_relative_rating=round(
                    float(
                        row[
                            "league_relative_rating"
                        ]
                    ),
                    6,
                ),
                performance_rating=round(
                    float(
                        row[
                            "performance_rating"
                        ]
                    ),
                    6,
                ),
                rating_confidence=round(
                    float(
                        row[
                            "rating_confidence"
                        ]
                    ),
                    6,
                ),
                gap_to_previous=round(
                    gap_to_previous,
                    6,
                ),
                gap_to_leader=round(
                    gap_to_leader,
                    6,
                ),
                rating_level=get_rating_level(
                    absolute_rating
                ),
            )
        )

        previous_rating = absolute_rating

    return rankings


def load_rating_rows(
    connection: sqlite3.Connection,
    season_label: str,
    model_version: str,
) -> list[dict[str, Any]]:
    """
    Carrega os ratings e a identificação das equipas.
    """

    rows = connection.execute(
        """
        SELECT
            r.team_id,
            t.team_name,
            r.league_id,
            l.league_name,
            r.season_label,
            r.model_version,
            r.absolute_rating,
            r.league_relative_rating,
            r.performance_rating,
            r.rating_confidence
        FROM team_ratings r
        INNER JOIN teams t
            ON t.team_id = r.team_id
        INNER JOIN leagues l
            ON l.league_id = r.league_id
        WHERE r.season_label = ?
          AND r.model_version = ?
          AND t.active = 1
          AND l.active = 1
        """,
        (
            season_label,
            model_version,
        ),
    ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def build_league_positions(
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Atribui a posição de cada equipa dentro da respetiva liga.
    """

    rows_by_league: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for row in rows:
        league_id = str(
            row["league_id"]
        )

        rows_by_league.setdefault(
            league_id,
            [],
        ).append(row)

    positions: dict[str, int] = {}

    for league_rows in rows_by_league.values():
        sorted_league_rows = sorted(
            league_rows,
            key=ranking_sort_key,
        )

        for position, row in enumerate(
            sorted_league_rows,
            start=1,
        ):
            positions[
                str(row["team_id"])
            ] = position

    return positions


def ranking_sort_key(
    row: dict[str, Any],
) -> tuple[float, float, float, str]:
    """
    Chave de ordenação utilizada nos rankings.
    """

    return (
        -float(
            row["absolute_rating"]
        ),
        -float(
            row["performance_rating"]
        ),
        -float(
            row["rating_confidence"]
        ),
        str(
            row["team_name"]
        ).casefold(),
    )


def validate_rating_rows(
    rows: list[dict[str, Any]],
) -> None:
    """
    Valida os ratings antes de criar o ranking.
    """

    seen_team_ids: set[str] = set()

    for row in rows:
        team_id = str(
            row.get("team_id") or ""
        ).strip()

        if not team_id:
            raise RankingServiceError(
                "Foi encontrado um rating sem team_id."
            )

        if team_id in seen_team_ids:
            raise RankingServiceError(
                f"Equipa duplicada no ranking: {team_id}"
            )

        seen_team_ids.add(team_id)

        numeric_fields = (
            "absolute_rating",
            "league_relative_rating",
            "performance_rating",
            "rating_confidence",
        )

        for field_name in numeric_fields:
            try:
                value = float(
                    row[field_name]
                )

            except (
                TypeError,
                ValueError,
                KeyError,
            ) as exc:
                raise RankingServiceError(
                    f"Valor inválido em {field_name} "
                    f"para {team_id}."
                ) from exc

            if not math.isfinite(value):
                raise RankingServiceError(
                    f"Valor não finito em {field_name} "
                    f"para {team_id}."
                )

        absolute_rating = float(
            row["absolute_rating"]
        )

        relative_rating = float(
            row["league_relative_rating"]
        )

        performance_rating = float(
            row["performance_rating"]
        )

        confidence = float(
            row["rating_confidence"]
        )

        if not 0 <= absolute_rating <= 100:
            raise RankingServiceError(
                f"absolute_rating fora do intervalo "
                f"para {team_id}."
            )

        if not 0 <= relative_rating <= 100:
            raise RankingServiceError(
                f"league_relative_rating fora do intervalo "
                f"para {team_id}."
            )

        if not 0 <= performance_rating <= 100:
            raise RankingServiceError(
                f"performance_rating fora do intervalo "
                f"para {team_id}."
            )

        if not 0 <= confidence <= 1:
            raise RankingServiceError(
                f"rating_confidence fora do intervalo "
                f"para {team_id}."
            )


def get_rating_level(
    absolute_rating: float,
) -> str:
    """
    Converte um rating num nível qualitativo.
    """

    rating = float(
        absolute_rating
    )

    if not math.isfinite(rating):
        raise RankingServiceError(
            "O rating não é finito."
        )

    if not 0 <= rating <= 100:
        raise RankingServiceError(
            "O rating deve estar entre 0 e 100."
        )

    if rating >= 85:
        return "ELITE"

    if rating >= 75:
        return "MUITO_FORTE"

    if rating >= 65:
        return "FORTE"

    if rating >= 55:
        return "ACIMA_DA_MEDIA"

    if rating >= 45:
        return "MEDIO"

    if rating >= 35:
        return "ABAIXO_DA_MEDIA"

    if rating >= 25:
        return "FRACO"

    return "MUITO_FRACO"


def get_configured_model_version() -> str:
    """
    Obtém a versão atual do modelo.
    """

    config = load_full_model_config()

    try:
        return str(
            config["version"][
                "model_version"
            ]
        )

    except KeyError as exc:
        raise RankingServiceError(
            "Não foi possível obter "
            "version.model_version."
        ) from exc
