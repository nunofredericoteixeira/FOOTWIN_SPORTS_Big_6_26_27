# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.collectors.laliga_lineup_client import (
    fetch_laliga_match_lineups,
    fetch_laliga_team_squad,
)

from src.collectors.laliga_fixtures_collector import (
    DEFAULT_FIXTURES_JSON,
)

from src.database.init_database import connect_database

from src.models.lineup_context_service import (
    calculate_lineup_hash,
)


PROVIDER = "LALIGA"


class LaligaLineupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedPlayer:
    provider_player_id: str
    display_name: str
    shirt_number: int | None
    position: int | None
    position_code: str | None
    is_starter: bool
    is_captain: bool


@dataclass(frozen=True)
class ParsedTeamLineup:
    starters: tuple[ParsedPlayer, ...]
    substitutes: tuple[ParsedPlayer, ...]


@dataclass(frozen=True)
class ParsedMatchLineup:
    home: ParsedTeamLineup
    away: ParsedTeamLineup


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


def normalize_name(
    value: str,
) -> str:
    return (
        str(value)
        .lower()
        .strip()
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


def parse_fixture_id(
    match_id: str,
) -> str:
    match = re.search(
        r"_LL(\d+)_",
        str(match_id),
    )

    if match is None:
        raise LaligaLineupError(
            "Não foi possível extrair "
            "o fixture_id LaLiga de match_id: "
            f"{match_id}"
        )

    return match.group(1)


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
        raise LaligaLineupError(
            f"Jogo não encontrado: {match_id}"
        )

    if str(row["league_id"]) != "ESP1":
        raise LaligaLineupError(
            "O collector LaLiga apenas aceita jogos ESP1."
        )

    return row


def parse_player(
    entry: dict[str, Any],
) -> ParsedPlayer | None:
    status = str(
        entry.get("status") or ""
    ).strip().lower()

    if status not in {
        "start",
        "sub",
    }:
        return None

    person = entry.get("person") or {}

    if not isinstance(person, dict):
        return None

    name = str(
        person.get("name")
        or person.get("nickname")
        or ""
    ).strip()

    if not name:
        return None

    external_id = entry.get("id")

    if external_id is None:
        return None

    shirt_number = entry.get(
        "shirt_number"
    )

    if not isinstance(
        shirt_number,
        int,
    ):
        shirt_number = None

    position = entry.get(
        "position"
    )

    if not isinstance(
        position,
        int,
    ):
        position = None

    return ParsedPlayer(
        provider_player_id=str(
            external_id
        ),
        display_name=name,
        shirt_number=shirt_number,
        position=position,
        position_code=None,
        is_starter=(
            status == "start"
        ),
        is_captain=bool(
            entry.get("captain")
        ),
    )


def parse_team_lineup(
    entries: Any,
) -> ParsedTeamLineup:
    starters: list[ParsedPlayer] = []
    substitutes: list[ParsedPlayer] = []

    if not isinstance(
        entries,
        list,
    ):
        entries = []

    for entry in entries:
        if not isinstance(
            entry,
            dict,
        ):
            continue

        player = parse_player(
            entry
        )

        if player is None:
            continue

        if player.is_starter:
            starters.append(
                player
            )
        else:
            substitutes.append(
                player
            )

    starters.sort(
        key=lambda player: (
            player.position
            if player.position is not None
            else 999
        )
    )

    substitutes.sort(
        key=lambda player: (
            player.position
            if player.position is not None
            else 999
        )
    )

    return ParsedTeamLineup(
        starters=tuple(
            starters
        ),
        substitutes=tuple(
            substitutes
        ),
    )


LALIGA_POSITION_MAPPING = {
    "portero": "GOALKEEPER",
    "defensa": "DEFENDER",
    "centrocampista": "MIDFIELDER",
    "delantero": "FORWARD",
}


def load_fixture_team_slugs(
    fixture_id: str,
    json_path: str | Path = DEFAULT_FIXTURES_JSON,
) -> tuple[str, str]:
    path = Path(
        json_path
    ).expanduser().resolve()

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        payload,
        list,
    ):
        raise LaligaLineupError(
            "JSON de fixtures LaLiga inválido."
        )

    target = next(
        (
            item
            for item in payload
            if (
                isinstance(item, dict)
                and str(item.get("id")) == str(fixture_id)
            )
        ),
        None,
    )

    if target is None:
        raise LaligaLineupError(
            "Fixture LaLiga não encontrada "
            f"no JSON local: {fixture_id}"
        )

    home_team = (
        target.get("home_team")
        or {}
    )
    away_team = (
        target.get("away_team")
        or {}
    )

    home_slug = str(
        home_team.get("slug")
        or ""
    ).strip()

    away_slug = str(
        away_team.get("slug")
        or ""
    ).strip()

    if not home_slug or not away_slug:
        raise LaligaLineupError(
            "Fixture LaLiga sem slugs válidos: "
            f"{fixture_id}"
        )

    return (
        home_slug,
        away_slug,
    )


def extract_squad_players(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    squads = payload.get(
        "squads",
        [],
    )

    if not isinstance(
        squads,
        list,
    ):
        return []

    return [
        item
        for item in squads
        if (
            isinstance(item, dict)
            and isinstance(
                item.get("role"),
                dict,
            )
            and (
                item["role"].get("slug")
                == "jugador"
            )
        )
    ]


def squad_player_name(
    player: dict[str, Any],
) -> str:
    person = (
        player.get("person")
        or {}
    )

    if not isinstance(
        person,
        dict,
    ):
        person = {}

    return str(
        person.get("nickname")
        or person.get("name")
        or player.get("nickname")
        or player.get("name")
        or ""
    ).strip()


def find_position_code(
    player: ParsedPlayer,
    squad_players: list[dict[str, Any]],
) -> str | None:
    candidates = squad_players

    if player.shirt_number is not None:
        shirt_candidates = [
            item
            for item in squad_players
            if (
                item.get("shirt_number")
                == player.shirt_number
            )
        ]

        if len(shirt_candidates) == 1:
            candidates = shirt_candidates

        elif len(shirt_candidates) > 1:
            candidates = shirt_candidates

    normalized_target = normalize_name(
        player.display_name
    )

    name_matches = [
        item
        for item in candidates
        if normalize_name(
            squad_player_name(item)
        ) == normalized_target
    ]

    if len(name_matches) == 1:
        matched = name_matches[0]

    elif (
        player.shirt_number is not None
        and len(candidates) == 1
    ):
        matched = candidates[0]

    else:
        all_name_matches = [
            item
            for item in squad_players
            if normalize_name(
                squad_player_name(item)
            ) == normalized_target
        ]

        if len(all_name_matches) != 1:
            return None

        matched = all_name_matches[0]

    position = (
        matched.get("position")
        or {}
    )

    if not isinstance(
        position,
        dict,
    ):
        return None

    slug = str(
        position.get("slug")
        or ""
    ).strip().lower()

    return LALIGA_POSITION_MAPPING.get(
        slug
    )


def enrich_team_positions(
    team: ParsedTeamLineup,
    squad_payload: dict[str, Any],
) -> ParsedTeamLineup:
    squad_players = extract_squad_players(
        squad_payload
    )

    def enrich(
        player: ParsedPlayer,
    ) -> ParsedPlayer:
        return ParsedPlayer(
            provider_player_id=(
                player.provider_player_id
            ),
            display_name=(
                player.display_name
            ),
            shirt_number=(
                player.shirt_number
            ),
            position=(
                player.position
            ),
            position_code=find_position_code(
                player,
                squad_players,
            ),
            is_starter=(
                player.is_starter
            ),
            is_captain=(
                player.is_captain
            ),
        )

    return ParsedTeamLineup(
        starters=tuple(
            enrich(player)
            for player in team.starters
        ),
        substitutes=tuple(
            enrich(player)
            for player in team.substitutes
        ),
    )


def parse_match_lineup(
    payload: dict[str, Any],
) -> ParsedMatchLineup:
    return ParsedMatchLineup(
        home=parse_team_lineup(
            payload.get(
                "home_team_lineups",
                [],
            )
        ),
        away=parse_team_lineup(
            payload.get(
                "away_team_lineups",
                [],
            )
        ),
    )


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
            full_name =
                excluded.full_name,
            normalized_name =
                excluded.normalized_name,
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
            normalize_name(
                player_name
            ),
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
        VALUES (
            ?, ?, ?, ?, ?, ?, 'ACTIVE'
        )
        ON CONFLICT(
            team_id,
            player_id,
            season_label
        )
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
        VALUES (
            ?, ?, 'PLAYER', ?, ?, ?,
            'AUTOMATIC', 1.0
        )
        ON CONFLICT(
            provider,
            entity_type,
            external_entity_id
        )
        DO UPDATE SET
            internal_entity_id =
                excluded.internal_entity_id,
            mapping_status =
                'AUTOMATIC'
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
    player: ParsedPlayer,
) -> None:
    position_code = (
        player.position_code
    )

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
        position=position_code,
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
        DO UPDATE SET
            player_id =
                excluded.player_id,
            player_name =
                excluded.player_name,
            role =
                excluded.role,
            position_code =
                excluded.position_code,
            formation_position =
                excluded.formation_position,
            shirt_number =
                excluded.shirt_number,
            captain =
                excluded.captain,
            mapping_status =
                excluded.mapping_status
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
            position_code,
            position_code,
            player.shirt_number,
            (
                1
                if player.is_captain
                else 0
            ),
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
            match_id
        )

        try:
            payload = fetch_laliga_match_lineups(
                fixture_id
            )
        except Exception as exc:
            record_fetch(
                connection=connection,
                match_id=match_id,
                fixture_id=fixture_id,
                status="HTTP_ERROR",
                http_status=None,
                message=str(exc),
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="HTTP_ERROR",
                http_status=None,
                home_starters=0,
                away_starters=0,
                lineup_id=None,
                lineup_hash=None,
                message=str(exc),
            )

        lineup = parse_match_lineup(
            payload
        )

        try:
            (
                home_slug,
                away_slug,
            ) = load_fixture_team_slugs(
                fixture_id
            )

            home_squad = fetch_laliga_team_squad(
                team_slug=home_slug,
                season_year=2026,
            )

            away_squad = fetch_laliga_team_squad(
                team_slug=away_slug,
                season_year=2026,
            )

            lineup = ParsedMatchLineup(
                home=enrich_team_positions(
                    lineup.home,
                    home_squad,
                ),
                away=enrich_team_positions(
                    lineup.away,
                    away_squad,
                ),
            )

        except Exception as exc:
            raise LaligaLineupError(
                "Não foi possível enriquecer "
                "as posições oficiais LaLiga: "
                f"{exc}"
            ) from exc

        home_starters = len(
            lineup.home.starters
        )

        away_starters = len(
            lineup.away.starters
        )

        if (
            home_starters != 11
            or away_starters != 11
        ):
            message = (
                "Onze ainda não confirmado: "
                f"home={home_starters}, "
                f"away={away_starters}."
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                fixture_id=fixture_id,
                status="NO_LINEUP",
                http_status=200,
                message=message,
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="NO_LINEUP",
                http_status=200,
                home_starters=home_starters,
                away_starters=away_starters,
                lineup_id=None,
                lineup_hash=None,
                message=message,
            )

        home_hash = [
            {
                "provider_player_id":
                    player.provider_player_id,
                "player_name":
                    player.display_name,
                "shirt_number":
                    player.shirt_number,
            }
            for player in (
                lineup.home.starters
            )
        ]

        away_hash = [
            {
                "provider_player_id":
                    player.provider_player_id,
                "player_name":
                    player.display_name,
                "shirt_number":
                    player.shirt_number,
            }
            for player in (
                lineup.away.starters
            )
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
            (lineup_hash,),
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
                    None,
                    None,
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
                team_id=str(
                    match[
                        "home_team_id"
                    ]
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
                team_id=str(
                    match[
                        "away_team_id"
                    ]
                ),
                player=player,
            )

        record_fetch(
            connection=connection,
            match_id=match_id,
            fixture_id=fixture_id,
            status="SUCCESS",
            http_status=200,
            message=(
                "Onze confirmado gravado."
            ),
        )

        connection.commit()

        return CollectionResult(
            match_id=match_id,
            fetch_status="SUCCESS",
            http_status=200,
            home_starters=home_starters,
            away_starters=away_starters,
            lineup_id=lineup_id,
            lineup_hash=lineup_hash,
            message=(
                "Onze confirmado gravado."
            ),
        )

    finally:
        connection.close()
