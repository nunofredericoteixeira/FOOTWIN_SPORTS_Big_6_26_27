# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.collectors.premier_league_lineup_client import (
    LineupAvailability,
    fetch_premier_league_lineup,
)

from src.database.init_database import connect_database

from src.models.lineup_context_service import (
    calculate_lineup_hash,
)


PROVIDER = "PREMIER_LEAGUE"


class PremierLeagueLineupError(RuntimeError):
    pass


@dataclass
class CollectionResult:
    match_id: str
    fetch_status: str
    http_status: int | None
    home_starters: int
    away_starters: int
    lineup_id: str | None
    lineup_hash: str | None
    message: str


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


def safe_identifier(
    value: str,
) -> str:
    return (
        str(value)
        .strip()
        .replace("/", "_")
        .replace(" ", "_")
    )


def create_mapping_id(
    entity_type: str,
    internal_entity_id: str,
    external_entity_id: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"{PROVIDER}|"
            f"{entity_type}|"
            f"{internal_entity_id}|"
            f"{external_entity_id}"
        ).encode("utf-8")
    ).hexdigest()[:20]

    return (
        f"MAP__{PROVIDER}__"
        f"{entity_type}__{digest}"
    )


def normalize_name(
    value: str,
) -> str:
    return (
        str(value)
        .lower()
        .strip()
    )


def parse_fixture_id(
    source_url: str,
) -> str:
    parts = [
        p
        for p in urlparse(
            source_url
        ).path.split("/")
        if p
    ]

    if not parts:
        raise PremierLeagueLineupError(
            "URL sem fixture."
        )

    return parts[-1]


def load_match(
    connection: sqlite3.Connection,
    match_id: str,
) -> sqlite3.Row:

    row = connection.execute(
        """
        SELECT
            *
        FROM matches
        WHERE match_id = ?
        LIMIT 1
        """,
        (match_id,),
    ).fetchone()

    if row is None:
        raise PremierLeagueLineupError(
            f"Jogo não encontrado: {match_id}"
        )

    return row


def record_fetch(
    connection: sqlite3.Connection,
    match_id: str,
    fixture_id: str,
    status: str,
    http_status: int | None,
    message: str | None,
) -> None:

    attempted_at = utc_now()

    fetch_id = (
        f"FETCH__{PROVIDER}__"
        f"{safe_identifier(match_id)}__"
        f"{uuid.uuid4().hex[:16]}"
    )

    connection.execute(
        """
        INSERT INTO match_lineup_fetches (
            fetch_id,
            match_id,
            provider,
            provider_fixture_id,
            attempted_at,
            fetch_status,
            http_status,
            error_message
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            fetch_id,
            match_id,
            PROVIDER,
            fixture_id,
            attempted_at,
            status,
            http_status,
            message,
        ),
    )


def create_lineup_id(
    match_id: str,
    lineup_hash: str,
) -> str:

    return (
        f"{PROVIDER}__"
        f"{safe_identifier(match_id)}__"
        f"{lineup_hash[:16]}"
    )


def ensure_player(
    connection: sqlite3.Connection,
    match_id: str,
    team_id: str,
    player_id_external: str,
    player_name: str,
    position: str | None,
    shirt_number: int | None,
) -> str:

    player_id = (
        f"PLAYER__{PROVIDER}__"
        f"{safe_identifier(player_id_external)}"
    )

    connection.execute(
        """
        INSERT INTO players (
            player_id,
            full_name,
            normalized_name,
            primary_position,
            active
        )
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(player_id)
        DO UPDATE SET
            full_name = excluded.full_name,
            normalized_name = excluded.normalized_name,
            primary_position =
                COALESCE(
                    excluded.primary_position,
                    players.primary_position
                ),
            active = 1,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            player_id,
            player_name,
            normalize_name(player_name),
            position,
        ),
    )

    season = connection.execute(
        """
        SELECT season_label
        FROM matches
        WHERE match_id = ?
        """,
        (match_id,),
    ).fetchone()

    season_label = str(
        season["season_label"]
    )

    squad_id = (
        f"SQUAD__"
        f"{safe_identifier(team_id)}__"
        f"{safe_identifier(season_label)}__"
        f"{safe_identifier(player_id)}"
    )

    connection.execute(
        """
        INSERT INTO team_squads (
            team_squad_id,
            team_id,
            player_id,
            season_label,
            shirt_number,
            position_code,
            squad_status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')
        ON CONFLICT(team_id, player_id, season_label)
        DO UPDATE SET
            shirt_number =
                COALESCE(
                    excluded.shirt_number,
                    team_squads.shirt_number
                ),
            position_code =
                COALESCE(
                    excluded.position_code,
                    team_squads.position_code
                )
        """,
        (
            squad_id,
            team_id,
            player_id,
            season_label,
            shirt_number,
            position,
        ),
    )

    mapping_id = create_mapping_id(
        "PLAYER",
        player_id,
        player_id_external,
    )

    connection.execute(
        """
        INSERT INTO external_provider_mappings (
            mapping_id,
            provider,
            entity_type,
            internal_entity_id,
            external_entity_id,
            external_name,
            mapping_status,
            confidence
        )
        VALUES (?, ?, 'PLAYER', ?, ?, ?, 'AUTOMATIC', 1.0)
        ON CONFLICT(provider, entity_type, external_entity_id)
        DO UPDATE SET
            internal_entity_id =
                excluded.internal_entity_id,
            mapping_status = 'AUTOMATIC'
        """,
        (
            mapping_id,
            PROVIDER,
            player_id,
            player_id_external,
            player_name,
        ),
    )

    return player_id


def store_lineup_player(
    connection: sqlite3.Connection,
    lineup_id: str,
    match_id: str,
    team_id: str,
    player,
) -> None:

    internal_player_id = ensure_player(
        connection=connection,
        match_id=match_id,
        team_id=team_id,
        player_id_external=(
            player.provider_player_id
        ),
        player_name=(
            player.display_name
        ),
        position=(
            player.match_position
            or player.registered_position
        ),
        shirt_number=(
            player.shirt_number
        ),
    )

    lineup_player_id = (
        f"{lineup_id}__"
        f"{safe_identifier(team_id)}__"
        f"{safe_identifier(player.provider_player_id)}"
    )

    connection.execute(
        """
        INSERT INTO match_lineup_players (
            lineup_player_id,
            lineup_id,
            match_id,
            team_id,
            player_id,
            provider_player_id,
            player_name,
            role,
            position_code,
            formation_position,
            shirt_number,
            captain,
            mapping_status
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(lineup_player_id)
        DO NOTHING
        """,
        (
            lineup_player_id,
            lineup_id,
            match_id,
            team_id,
            internal_player_id,
            player.provider_player_id,
            player.display_name,
            (
                "STARTER"
                if player.is_starter
                else "SUBSTITUTE"
            ),
            (
                player.match_position
                or player.registered_position
            ),
            (
                str(player.formation_row)
                if player.formation_row
                else None
            ),
            player.shirt_number,
            1 if player.is_captain else 0,
            "AUTOMATIC",
        ),
    )


def collect_match_lineup(
    match_id: str,
    database_path: str | Path | None = None,
) -> CollectionResult:

    connection = connect_database(
        database_path
    )

    try:
        match = load_match(
            connection,
            match_id,
        )

        fixture_id = parse_fixture_id(
            str(match["source_url"])
        )

        result = fetch_premier_league_lineup(
            fixture_id
        )

        if (
            result.availability
            != LineupAvailability.AVAILABLE
        ):

            status = {
                LineupAvailability.NOT_PUBLISHED:
                    "NO_LINEUP",
                LineupAvailability.FIXTURE_NOT_FOUND:
                    "PROVIDER_ERROR",
                LineupAvailability.HTTP_ERROR:
                    "HTTP_ERROR",
                LineupAvailability.INVALID_PAYLOAD:
                    "INVALID",
            }.get(
                result.availability,
                "PROVIDER_ERROR",
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                fixture_id=fixture_id,
                status=status,
                http_status=result.http_status,
                message=result.message,
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status=status,
                http_status=result.http_status,
                home_starters=0,
                away_starters=0,
                lineup_id=None,
                lineup_hash=None,
                message=result.message,
            )


        lineup = result.parsed_lineup


        home_hash = [
            {
                "provider_player_id":
                    p.provider_player_id,
                "player_name":
                    p.display_name,
                "shirt_number":
                    p.shirt_number,
            }
            for p in lineup.home.starters
        ]


        away_hash = [
            {
                "provider_player_id":
                    p.provider_player_id,
                "player_name":
                    p.display_name,
                "shirt_number":
                    p.shirt_number,
            }
            for p in lineup.away.starters
        ]


        lineup_hash = calculate_lineup_hash(
            match_id=match_id,
            home_players=home_hash,
            away_players=away_hash,
        )


        lineup_id = create_lineup_id(
            match_id=match_id,
            lineup_hash=lineup_hash,
        )


        existing = connection.execute(
            """
            SELECT lineup_id
            FROM match_lineups
            WHERE lineup_hash = ?
            LIMIT 1
            """,
            (
                lineup_hash,
            ),
        ).fetchone()


        if existing is None:

            connection.execute(
                """
                INSERT INTO match_lineups (
                    lineup_id,
                    match_id,
                    provider,
                    lineup_status,
                    home_formation,
                    away_formation,
                    lineup_hash,
                    fetched_at,
                    is_current
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, 1
                )
                """,
                (
                    lineup_id,
                    match_id,
                    PROVIDER,
                    "CONFIRMED",
                    lineup.home.formation,
                    lineup.away.formation,
                    lineup_hash,
                    utc_now(),
                ),
            )


            for player in (
                lineup.home.starters
                + lineup.home.substitutes
            ):
                store_lineup_player(
                    connection=connection,
                    lineup_id=lineup_id,
                    match_id=match_id,
                    team_id=(
                        str(match["home_team_id"])
                    ),
                    player=player,
                )


            for player in (
                lineup.away.starters
                + lineup.away.substitutes
            ):
                store_lineup_player(
                    connection=connection,
                    lineup_id=lineup_id,
                    match_id=match_id,
                    team_id=(
                        str(match["away_team_id"])
                    ),
                    player=player,
                )


        record_fetch(
            connection=connection,
            match_id=match_id,
            fixture_id=fixture_id,
            status="SUCCESS",
            http_status=result.http_status,
            message="Onze confirmado gravado.",
        )

        connection.commit()


        return CollectionResult(
            match_id=match_id,
            fetch_status="SUCCESS",
            http_status=result.http_status,
            home_starters=len(
                lineup.home.starters
            ),
            away_starters=len(
                lineup.away.starters
            ),
            lineup_id=lineup_id,
            lineup_hash=lineup_hash,
            message=(
                "Onze confirmado gravado."
            ),
        )


    finally:
        connection.close()
