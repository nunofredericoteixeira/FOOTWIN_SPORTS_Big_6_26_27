# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.config.league_config import get_active_leagues
from src.database.init_database import connect_database
from src.utils.logger import get_logger


logger = get_logger("importers.leagues")


@dataclass
class LeagueImportResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0

    @property
    def processed(self) -> int:
        return (
            self.inserted
            + self.updated
            + self.unchanged
            + self.errors
        )


class LeagueImportError(RuntimeError):
    """Erro ocorrido durante a importação das ligas."""


def import_leagues(
    database_path: str | Path | None = None,
) -> LeagueImportResult:
    """
    Importa as ligas ativas da configuração YAML para a SQLite.

    A operação é idempotente:
    - insere ligas inexistentes;
    - atualiza ligas alteradas;
    - mantém ligas sem alterações.
    """

    configured_leagues = get_active_leagues()
    result = LeagueImportResult()

    logger.info(
        "A iniciar importação de ligas | total=%s",
        len(configured_leagues),
    )

    connection = connect_database(database_path)

    try:
        with connection:
            for league_id, league in configured_leagues.items():
                try:
                    action = _upsert_league(
                        connection=connection,
                        league_id=league_id,
                        league=league,
                    )

                    if action == "INSERTED":
                        result.inserted += 1
                    elif action == "UPDATED":
                        result.updated += 1
                    else:
                        result.unchanged += 1

                except sqlite3.Error:
                    result.errors += 1

                    logger.exception(
                        "Erro ao importar liga | league_id=%s",
                        league_id,
                    )

        validate_imported_leagues(
            connection=connection,
            configured_leagues=configured_leagues,
        )

    except sqlite3.Error as exc:
        raise LeagueImportError(
            f"Erro SQLite durante a importação das ligas: {exc}"
        ) from exc

    finally:
        connection.close()

    logger.info(
        "Importação de ligas concluída | "
        "inseridas=%s | atualizadas=%s | "
        "inalteradas=%s | erros=%s",
        result.inserted,
        result.updated,
        result.unchanged,
        result.errors,
    )

    return result


def _upsert_league(
    connection: sqlite3.Connection,
    league_id: str,
    league: dict,
) -> str:
    """
    Insere ou atualiza uma liga.

    Devolve:
    - INSERTED
    - UPDATED
    - UNCHANGED
    """

    existing = connection.execute(
        """
        SELECT
            league_id,
            league_name,
            country,
            country_code,
            season_label,
            team_count,
            matches_per_team,
            total_matches,
            league_strength_factor,
            relegation_places,
            playoff_places,
            active
        FROM leagues
        WHERE league_id = ?
        """,
        (league_id,),
    ).fetchone()

    values = {
        "league_id": league_id,
        "league_name": league["name"],
        "country": league["country"],
        "country_code": league["country_code"],
        "season_label": league["season_label"],
        "team_count": int(league["team_count"]),
        "matches_per_team": int(league["matches_per_team"]),
        "total_matches": int(league["total_matches"]),
        "league_strength_factor": float(
            league["league_strength_factor"]
        ),
        "relegation_places": int(
            league["relegation_places"]
        ),
        "playoff_places": int(
            league["playoff_places"]
        ),
        "active": int(bool(league["active"])),
    }

    if existing is None:
        connection.execute(
            """
            INSERT INTO leagues (
                league_id,
                league_name,
                country,
                country_code,
                season_label,
                team_count,
                matches_per_team,
                total_matches,
                league_strength_factor,
                relegation_places,
                playoff_places,
                active
            )
            VALUES (
                :league_id,
                :league_name,
                :country,
                :country_code,
                :season_label,
                :team_count,
                :matches_per_team,
                :total_matches,
                :league_strength_factor,
                :relegation_places,
                :playoff_places,
                :active
            )
            """,
            values,
        )

        logger.info(
            "Liga inserida | %s - %s",
            league_id,
            league["name"],
        )

        return "INSERTED"

    changed = _league_has_changes(
        existing=existing,
        values=values,
    )

    if not changed:
        logger.debug(
            "Liga sem alterações | %s",
            league_id,
        )

        return "UNCHANGED"

    connection.execute(
        """
        UPDATE leagues
        SET
            league_name = :league_name,
            country = :country,
            country_code = :country_code,
            season_label = :season_label,
            team_count = :team_count,
            matches_per_team = :matches_per_team,
            total_matches = :total_matches,
            league_strength_factor = :league_strength_factor,
            relegation_places = :relegation_places,
            playoff_places = :playoff_places,
            active = :active,
            updated_at = CURRENT_TIMESTAMP
        WHERE league_id = :league_id
        """,
        values,
    )

    logger.info(
        "Liga atualizada | %s - %s",
        league_id,
        league["name"],
    )

    return "UPDATED"


def _league_has_changes(
    existing: sqlite3.Row,
    values: dict,
) -> bool:
    fields = (
        "league_name",
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
    )

    for field in fields:
        existing_value = existing[field]
        configured_value = values[field]

        if field == "league_strength_factor":
            if abs(
                float(existing_value)
                - float(configured_value)
            ) > 0.000001:
                return True
        elif existing_value != configured_value:
            return True

    return False


def validate_imported_leagues(
    connection: sqlite3.Connection,
    configured_leagues: dict,
) -> None:
    """Confirma se as seis ligas ficaram corretamente importadas."""

    rows = connection.execute(
        """
        SELECT
            league_id,
            team_count,
            total_matches,
            active
        FROM leagues
        WHERE active = 1
        ORDER BY league_id
        """
    ).fetchall()

    imported = {
        row["league_id"]: row
        for row in rows
    }

    missing = set(configured_leagues) - set(imported)

    if missing:
        raise LeagueImportError(
            "Faltam ligas na base de dados: "
            + ", ".join(sorted(missing))
        )

    if len(imported) != 6:
        raise LeagueImportError(
            "A base de dados deve conter exatamente 6 ligas ativas. "
            f"Foram encontradas {len(imported)}."
        )

    total_teams = sum(
        int(row["team_count"])
        for row in rows
    )

    total_matches = sum(
        int(row["total_matches"])
        for row in rows
    )

    if total_teams != 114:
        raise LeagueImportError(
            f"Total de equipas inválido: {total_teams}."
        )

    if total_matches != 2058:
        raise LeagueImportError(
            f"Total de jogos inválido: {total_matches}."
        )


def list_imported_leagues(
    database_path: str | Path | None = None,
) -> list[dict]:
    """Lista as ligas existentes na SQLite."""

    connection = connect_database(database_path)

    try:
        rows = connection.execute(
            """
            SELECT
                league_id,
                league_name,
                country,
                season_label,
                team_count,
                total_matches,
                league_strength_factor,
                active
            FROM leagues
            ORDER BY
                CASE league_id
                    WHEN 'ENG1' THEN 1
                    WHEN 'ESP1' THEN 2
                    WHEN 'ITA1' THEN 3
                    WHEN 'GER1' THEN 4
                    WHEN 'FRA1' THEN 5
                    WHEN 'POR1' THEN 6
                    ELSE 99
                END
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()
