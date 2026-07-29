# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.model_config import load_full_model_config
from src.database.init_database import connect_database
from src.models.performance_rating import (
    PerformanceRating,
    calculate_performance_ratings,
)
from src.utils.logger import get_logger
from src.models.performance_rating import (
    PerformanceRating,
    calculate_performance_ratings,
)
from src.utils.logger import get_logger


logger = get_logger("models.rating_service")


@dataclass
class RatingServiceResult:
    leagues_processed: int = 0
    teams_processed: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0


class RatingServiceError(RuntimeError):
    """Erro durante o cálculo ou gravação dos ratings."""


def calculate_and_store_ratings(
    performance_season: str = "2025/26",
    rating_season: str = "2026/27",
    model_version: str | None = None,
    run_id: str | None = None,
    dataset_version: str | None = None,
    database_path: str | Path | None = None,
) -> RatingServiceResult:
    """
    Calcula e grava os ratings de todas as ligas com desempenho disponível.

    A normalização é feita separadamente por liga.

    A operação de gravação é atómica:
    - todos os ratings são calculados primeiro;
    - os dados só são gravados quando todas as ligas forem válidas;
    - qualquer erro durante a gravação provoca rollback total.
    """

    final_model_version = (
        model_version.strip()
        if model_version
        else get_configured_model_version()
    )

    connection = connect_database(database_path)
    result = RatingServiceResult()

    try:
        performance_rows = load_performance_rows(
            connection=connection,
            performance_season=performance_season,
            dataset_version=dataset_version,
        )

        if not performance_rows:
            raise RatingServiceError(
                "Não existem desempenhos disponíveis para calcular ratings."
            )

        rows_by_league = group_rows_by_league(
            performance_rows
        )

        prepared_ratings: list[dict[str, Any]] = []

        # ==========================================================
        # FASE 1 — Calcular tudo sem gravar
        # ==========================================================

        for league_id, league_rows in sorted(
            rows_by_league.items()
        ):
            if len(league_rows) < 2:
                raise RatingServiceError(
                    f"A liga {league_id} possui apenas "
                    f"{len(league_rows)} equipa(s). "
                    "São necessárias pelo menos duas para normalizar."
                )

            ratings = calculate_performance_ratings(
                records=league_rows
            )

            source_by_team = {
                str(row["team_id"]): row
                for row in league_rows
            }

            for rating in ratings:
                source = source_by_team[
                    rating.team_id
                ]

                prepared_ratings.append(
                    build_database_rating(
                        rating=rating,
                        source=source,
                        league_id=league_id,
                        rating_season=rating_season,
                        model_version=final_model_version,
                        run_id=run_id,
                    )
                )

            result.leagues_processed += 1
            result.teams_processed += len(ratings)

        # ==========================================================
        # FASE 2 — Gravar tudo numa transação
        # ==========================================================

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            for rating_record in prepared_ratings:
                action = upsert_team_rating(
                    connection=connection,
                    rating=rating_record,
                )

                if action == "INSERTED":
                    result.inserted += 1

                elif action == "UPDATED":
                    result.updated += 1

                elif action == "UNCHANGED":
                    result.unchanged += 1

            validate_stored_ratings(
                connection=connection,
                rating_season=rating_season,
                model_version=final_model_version,
                expected_total=len(prepared_ratings),
                team_ids=[
                    item["team_id"]
                    for item in prepared_ratings
                ],
            )

            connection.commit()

        except Exception:
            connection.rollback()

            logger.exception(
                "Gravação dos ratings revertida integralmente | "
                "modelo=%s | época=%s",
                final_model_version,
                rating_season,
            )

            raise

    except RatingServiceError:
        result.errors += 1
        raise

    except sqlite3.Error as exc:
        result.errors += 1

        raise RatingServiceError(
            f"Erro SQLite durante o cálculo dos ratings: {exc}"
        ) from exc

    except Exception as exc:
        result.errors += 1

        raise RatingServiceError(
            f"Erro durante o cálculo dos ratings: {exc}"
        ) from exc

    finally:
        connection.close()

    logger.info(
        "Ratings concluídos | ligas=%s | equipas=%s | "
        "inseridos=%s | atualizados=%s | inalterados=%s",
        result.leagues_processed,
        result.teams_processed,
        result.inserted,
        result.updated,
        result.unchanged,
    )

    return result


def load_performance_rows(
    connection: sqlite3.Connection,
    performance_season: str,
    dataset_version: str | None = None,
) -> list[dict[str, Any]]:
    """
    Carrega os desempenhos necessários para o rating.
    """

    if dataset_version:
        rows = connection.execute(
            """
            SELECT
                p.team_id,
                p.target_league_id AS league_id,
                p.played,
                p.points,
                p.goals_for,
                p.goals_against,
                p.goal_difference,
                p.data_confidence,
                p.dataset_version
            FROM team_season_performance p
            INNER JOIN teams t
                ON t.team_id = p.team_id
            WHERE p.season_label = ?
              AND p.dataset_version = ?
              AND t.active = 1
            ORDER BY
                p.target_league_id,
                p.position,
                p.team_id
            """,
            (
                performance_season,
                dataset_version,
            ),
        ).fetchall()

    else:
        rows = connection.execute(
            """
            SELECT
                p.team_id,
                p.target_league_id AS league_id,
                p.played,
                p.points,
                p.goals_for,
                p.goals_against,
                p.goal_difference,
                p.data_confidence,
                p.dataset_version
            FROM team_season_performance p
            INNER JOIN teams t
                ON t.team_id = p.team_id
            WHERE p.season_label = ?
              AND t.active = 1
            ORDER BY
                p.target_league_id,
                p.position,
                p.team_id
            """,
            (performance_season,),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def group_rows_by_league(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Agrupa os desempenhos pela liga de destino.
    """

    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        league_id = str(
            row["league_id"]
        ).strip().upper()

        if not league_id:
            raise RatingServiceError(
                f"A equipa {row.get('team_id')} não possui league_id."
            )

        grouped.setdefault(
            league_id,
            [],
        ).append(row)

    return grouped


def build_database_rating(
    rating: PerformanceRating,
    source: dict[str, Any],
    league_id: str,
    rating_season: str,
    model_version: str,
    run_id: str | None,
) -> dict[str, Any]:
    """
    Converte o rating calculado para o formato da tabela.
    """

    confidence = source.get(
        "data_confidence",
        1.0,
    )

    try:
        rating_confidence = float(confidence)

    except (TypeError, ValueError) as exc:
        raise RatingServiceError(
            f"Confiança inválida para {rating.team_id}: {confidence}"
        ) from exc

    if not 0.0 <= rating_confidence <= 1.0:
        raise RatingServiceError(
            f"Confiança fora do intervalo 0–1 para "
            f"{rating.team_id}: {rating_confidence}"
        )

    return {
        "team_id": rating.team_id,
        "league_id": league_id,
        "season_label": rating_season,
        "model_version": model_version,
        "run_id": run_id,
        "points_per_game": rating.points_per_game,
        "goals_for_per_game": rating.attack_per_game,
        "goals_against_per_game": (
            rating.defence_conceded_per_game
        ),
        "goal_difference_per_game": (
            rating.goal_difference_per_game
        ),
        "ppg_rating": rating.ppg_rating,
        "attack_rating": rating.attack_rating,
        "defence_rating": rating.defence_rating,
        "goal_difference_rating": (
            rating.goal_difference_rating
        ),
        "performance_rating": rating.final_rating,

        # Nesta primeira versão, o rating absoluto ainda é
        # igual ao rating relativo à liga. Posteriormente será
        # ajustado pelo fator de força das seis ligas.
        "absolute_rating": rating.final_rating,
        "league_relative_rating": rating.final_rating,
        "rating_confidence": rating_confidence,
    }


def upsert_team_rating(
    connection: sqlite3.Connection,
    rating: dict[str, Any],
) -> str:
    """
    Insere ou atualiza um rating.

    A chave lógica é:
        team_id + season_label + model_version
    """

    existing = connection.execute(
        """
        SELECT *
        FROM team_ratings
        WHERE team_id = ?
          AND season_label = ?
          AND model_version = ?
        """,
        (
            rating["team_id"],
            rating["season_label"],
            rating["model_version"],
        ),
    ).fetchone()

    if existing is None:
        connection.execute(
            """
            INSERT INTO team_ratings (
                team_id,
                league_id,
                season_label,
                model_version,
                run_id,
                points_per_game,
                goals_for_per_game,
                goals_against_per_game,
                goal_difference_per_game,
                ppg_rating,
                attack_rating,
                defence_rating,
                goal_difference_rating,
                performance_rating,
                absolute_rating,
                league_relative_rating,
                rating_confidence
            )
            VALUES (
                :team_id,
                :league_id,
                :season_label,
                :model_version,
                :run_id,
                :points_per_game,
                :goals_for_per_game,
                :goals_against_per_game,
                :goal_difference_per_game,
                :ppg_rating,
                :attack_rating,
                :defence_rating,
                :goal_difference_rating,
                :performance_rating,
                :absolute_rating,
                :league_relative_rating,
                :rating_confidence
            )
            """,
            rating,
        )

        logger.info(
            "Rating inserido | team_id=%s | rating=%.2f",
            rating["team_id"],
            rating["performance_rating"],
        )

        return "INSERTED"

    if not rating_has_changes(
        existing=existing,
        new_values=rating,
    ):
        return "UNCHANGED"

    connection.execute(
        """
        UPDATE team_ratings
        SET
            league_id = :league_id,
            run_id = :run_id,
            points_per_game = :points_per_game,
            goals_for_per_game = :goals_for_per_game,
            goals_against_per_game = :goals_against_per_game,
            goal_difference_per_game = :goal_difference_per_game,
            ppg_rating = :ppg_rating,
            attack_rating = :attack_rating,
            defence_rating = :defence_rating,
            goal_difference_rating = :goal_difference_rating,
            performance_rating = :performance_rating,
            absolute_rating = :absolute_rating,
            league_relative_rating = :league_relative_rating,
            rating_confidence = :rating_confidence
        WHERE team_id = :team_id
          AND season_label = :season_label
          AND model_version = :model_version
        """,
        rating,
    )

    logger.info(
        "Rating atualizado | team_id=%s | rating=%.2f",
        rating["team_id"],
        rating["performance_rating"],
    )

    return "UPDATED"


def rating_has_changes(
    existing: sqlite3.Row,
    new_values: dict[str, Any],
) -> bool:
    """
    Confirma se existem alterações relevantes.
    """

    text_fields = (
        "league_id",
        "run_id",
    )

    numeric_fields = (
        "points_per_game",
        "goals_for_per_game",
        "goals_against_per_game",
        "goal_difference_per_game",
        "ppg_rating",
        "attack_rating",
        "defence_rating",
        "goal_difference_rating",
        "performance_rating",
        "absolute_rating",
        "league_relative_rating",
        "rating_confidence",
    )

    for field in text_fields:
        if existing[field] != new_values[field]:
            return True

    for field in numeric_fields:
        if abs(
            float(existing[field])
            - float(new_values[field])
        ) > 0.000001:
            return True

    return False


def validate_stored_ratings(
    connection: sqlite3.Connection,
    rating_season: str,
    model_version: str,
    expected_total: int,
    team_ids: list[str],
) -> None:
    """
    Valida os ratings gravados para as equipas processadas.
    """

    if not team_ids:
        raise RatingServiceError(
            "Não existem equipas para validar."
        )

    placeholders = ",".join(
        "?"
        for _ in team_ids
    )

    parameters: list[Any] = [
        rating_season,
        model_version,
        *team_ids,
    ]

    total = connection.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM team_ratings
        WHERE season_label = ?
          AND model_version = ?
          AND team_id IN ({placeholders})
        """,
        parameters,
    ).fetchone()["total"]

    if int(total) != expected_total:
        raise RatingServiceError(
            "Total de ratings incorreto após gravação. "
            f"Esperado={expected_total}; encontrado={total}"
        )

    invalid = connection.execute(
        f"""
        SELECT
            team_id,
            performance_rating,
            absolute_rating,
            league_relative_rating,
            rating_confidence
        FROM team_ratings
        WHERE season_label = ?
          AND model_version = ?
          AND team_id IN ({placeholders})
          AND (
              performance_rating < 0
              OR performance_rating > 100
              OR absolute_rating < 0
              OR absolute_rating > 100
              OR league_relative_rating < 0
              OR league_relative_rating > 100
              OR rating_confidence < 0
              OR rating_confidence > 1
          )
        """,
        parameters,
    ).fetchall()

    if invalid:
        invalid_teams = ", ".join(
            str(row["team_id"])
            for row in invalid
        )

        raise RatingServiceError(
            "Foram encontrados ratings fora dos intervalos "
            f"permitidos: {invalid_teams}"
        )


def list_team_ratings(
    season_label: str = "2026/27",
    model_version: str | None = None,
    league_id: str | None = None,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Lista os ratings gravados.
    """

    final_model_version = (
        model_version.strip()
        if model_version
        else get_configured_model_version()
    )

    connection = connect_database(database_path)

    try:
        if league_id:
            rows = connection.execute(
                """
                SELECT
                    r.*,
                    t.team_name
                FROM team_ratings r
                INNER JOIN teams t
                    ON t.team_id = r.team_id
                WHERE r.season_label = ?
                  AND r.model_version = ?
                  AND r.league_id = ?
                ORDER BY
                    r.absolute_rating DESC,
                    r.team_id
                """,
                (
                    season_label,
                    final_model_version,
                    league_id.strip().upper(),
                ),
            ).fetchall()

        else:
            rows = connection.execute(
                """
                SELECT
                    r.*,
                    t.team_name
                FROM team_ratings r
                INNER JOIN teams t
                    ON t.team_id = r.team_id
                WHERE r.season_label = ?
                  AND r.model_version = ?
                ORDER BY
                    r.league_id,
                    r.absolute_rating DESC,
                    r.team_id
                """,
                (
                    season_label,
                    final_model_version,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def get_configured_model_version() -> str:
    """
    Obtém a versão ativa do modelo.
    """

    config = load_full_model_config()

    try:
        return str(
            config["version"]["model_version"]
        )

    except KeyError as exc:
        raise RatingServiceError(
            "Não foi possível encontrar version.model_version."
        ) from exc
