# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src.database.init_database import connect_database
from src.models.lineup_context_service import calculate_lineup_hash


PROVIDER = "LIGUE1_FR"
DEFAULT_TIMEOUT = 30
API_BASE_URL = "https://ma-api.ligue1.fr"

USER_AGENT = (
    "Mozilla/5.0 "
    "(Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


class Ligue1LineupError(RuntimeError):
    """Erro na recolha de onzes da Ligue 1."""


@dataclass(frozen=True)
class MatchEndpointParameters:
    provider_fixture_id: str
    source_url: str


@dataclass(frozen=True)
class ParsedPlayer:
    provider_player_id: str
    player_name: str
    role: str
    position_code: str | None
    formation_position: str | None
    shirt_number: int | None
    captain: bool


@dataclass(frozen=True)
class ParsedTeamLineup:
    formation: str | None
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
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_identifier(value: str) -> str:
    normalized = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        str(value).strip(),
    )
    return normalized.strip("_")


def normalize_player_name(value: str | None) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = text.casefold()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


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


def make_fetch_id(
    match_id: str,
    attempted_at: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"{PROVIDER}|"
            f"{match_id}|"
            f"{attempted_at}"
        ).encode("utf-8")
    ).hexdigest()[:16]

    return (
        f"FETCH__{PROVIDER}__"
        f"{safe_identifier(match_id)}__"
        f"{digest}"
    )


def parse_match_source_url(
    source_url: str,
) -> MatchEndpointParameters:
    value = str(source_url or "").strip()

    match = re.search(
        r"(l1_championship_match_\d+)",
        value,
        flags=re.IGNORECASE,
    )

    if match is None:
        raise Ligue1LineupError(
            "Não foi possível extrair o ID oficial "
            "do jogo a partir de source_url."
        )

    provider_fixture_id = match.group(1)

    return MatchEndpointParameters(
        provider_fixture_id=provider_fixture_id,
        source_url=value,
    )


def load_match(
    connection: sqlite3.Connection,
    match_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            m.match_id,
            m.league_id,
            m.season_label,
            m.round_number,
            m.match_date,
            m.home_team_id,
            m.away_team_id,
            m.status,
            m.source_url,
            ht.team_name AS home_team_name,
            at.team_name AS away_team_name
        FROM matches AS m
        INNER JOIN teams AS ht
            ON ht.team_id = m.home_team_id
        INNER JOIN teams AS at
            ON at.team_id = m.away_team_id
        WHERE m.match_id = ?
        LIMIT 1
        """,
        (match_id,),
    ).fetchone()

    if row is None:
        raise Ligue1LineupError(
            f"Jogo não encontrado: {match_id}"
        )

    if str(row["league_id"]) != "FRA1":
        raise Ligue1LineupError(
            "O collector Ligue 1 apenas aceita jogos FRA1."
        )

    if not row["source_url"]:
        raise Ligue1LineupError(
            "O jogo não possui source_url."
        )

    return row


def fetch_match_payload(
    provider_fixture_id: str,
    timeout: int,
) -> tuple[requests.Response, dict[str, Any]]:
    url = (
        f"{API_BASE_URL}/championship-match/"
        f"{provider_fixture_id}"
    )

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise Ligue1LineupError(
            "A API da Ligue 1 devolveu um payload inválido."
        )

    return response, payload


def fetch_player_payload(
    provider_player_id: str,
    timeout: int,
) -> dict[str, Any]:
    url = (
        f"{API_BASE_URL}/championship-player/"
        f"{provider_player_id}"
    )

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise Ligue1LineupError(
            "A API da Ligue 1 devolveu dados "
            "de jogador inválidos."
        )

    return payload


def player_name_from_payload(
    payload: dict[str, Any],
    provider_player_id: str,
) -> str:
    first_name = str(
        payload.get("firstName") or ""
    ).strip()

    last_name = str(
        payload.get("lastName") or ""
    ).strip()

    full_name = " ".join(
        part
        for part in (first_name, last_name)
        if part
    ).strip()

    return full_name or provider_player_id


def player_position_from_payload(
    detail: dict[str, Any],
    match_player: dict[str, Any],
) -> str | None:
    championship = (
        detail.get("championships") or {}
    ).get("1") or {}

    real_positions = championship.get(
        "realsPositions"
    )

    if (
        isinstance(real_positions, list)
        and real_positions
    ):
        value = str(real_positions[0]).strip()
        if value:
            return value.upper()

    position = championship.get("position")

    if position is None:
        position = match_player.get("position")

    if position is None:
        return None

    mapping = {
        1: "GOALKEEPER",
        2: "DEFENDER",
        3: "MIDFIELDER",
        4: "FORWARD",
    }

    try:
        numeric_position = int(position)
    except (TypeError, ValueError):
        numeric_position = None

    if numeric_position in mapping:
        return mapping[numeric_position]

    text = str(position).strip()
    return text or None


def player_shirt_number(
    detail: dict[str, Any],
    match_player: dict[str, Any],
) -> int | None:
    value = match_player.get("shirtNumber")

    if value is None:
        championship = (
            detail.get("championships") or {}
        ).get("1") or {}
        value = championship.get("jerseyNumber")

    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_team_lineup(
    team_payload: dict[str, Any],
    timeout: int,
) -> ParsedTeamLineup:
    players_payload = team_payload.get(
        "players"
    ) or {}

    if not isinstance(players_payload, dict):
        raise Ligue1LineupError(
            "O campo players da Ligue 1 "
            "não é um dicionário."
        )

    parsed_players: list[ParsedPlayer] = []

    for provider_player_id, raw_player in (
        players_payload.items()
    ):
        if not isinstance(raw_player, dict):
            continue

        formation_place = raw_player.get(
            "formationPlace"
        )

        try:
            formation_place_int = (
                int(formation_place)
                if formation_place is not None
                else None
            )
        except (TypeError, ValueError):
            formation_place_int = None

        is_starter = (
            formation_place_int is not None
            and 1 <= formation_place_int <= 11
        )

        is_substitute = (
            formation_place_int == 0
        )

        if not is_starter and not is_substitute:
            continue

        detail = fetch_player_payload(
            provider_player_id=str(
                provider_player_id
            ),
            timeout=timeout,
        )

        player_name = player_name_from_payload(
            payload=detail,
            provider_player_id=str(
                provider_player_id
            ),
        )

        parsed_players.append(
            ParsedPlayer(
                provider_player_id=str(
                    provider_player_id
                ),
                player_name=player_name,
                role=(
                    "STARTER"
                    if is_starter
                    else "SUBSTITUTE"
                ),
                position_code=(
                    player_position_from_payload(
                        detail=detail,
                        match_player=raw_player,
                    )
                ),
                formation_position=(
                    str(formation_place_int)
                    if formation_place_int
                    is not None
                    else None
                ),
                shirt_number=player_shirt_number(
                    detail=detail,
                    match_player=raw_player,
                ),
                captain=bool(
                    raw_player.get("captain")
                    or False
                ),
            )
        )

    starters = tuple(
        sorted(
            (
                player
                for player in parsed_players
                if player.role == "STARTER"
            ),
            key=lambda player: (
                int(
                    player.formation_position
                    or 999
                )
            ),
        )
    )

    substitutes = tuple(
        sorted(
            (
                player
                for player in parsed_players
                if player.role
                == "SUBSTITUTE"
            ),
            key=lambda player: (
                player.shirt_number
                if player.shirt_number
                is not None
                else 999,
                player.player_name,
            ),
        )
    )

    formation = team_payload.get(
        "formation"
    )

    if formation is not None:
        formation = str(formation).strip() or None

    return ParsedTeamLineup(
        formation=formation,
        starters=starters,
        substitutes=substitutes,
    )


def parse_match_lineup(
    payload: dict[str, Any],
    timeout: int,
) -> ParsedMatchLineup:
    home_payload = payload.get("home") or {}
    away_payload = payload.get("away") or {}

    if not isinstance(home_payload, dict):
        raise Ligue1LineupError(
            "Payload home inválido."
        )

    if not isinstance(away_payload, dict):
        raise Ligue1LineupError(
            "Payload away inválido."
        )

    return ParsedMatchLineup(
        home=parse_team_lineup(
            team_payload=home_payload,
            timeout=timeout,
        ),
        away=parse_team_lineup(
            team_payload=away_payload,
            timeout=timeout,
        ),
    )


def player_to_hash_dict(
    player: ParsedPlayer,
) -> dict[str, Any]:
    return {
        "provider_player_id": (
            player.provider_player_id
        ),
        "player_name": (
            player.player_name
        ),
        "position_code": (
            player.position_code
        ),
        "formation_position": (
            player.formation_position
        ),
        "shirt_number": (
            player.shirt_number
        ),
        "captain": (
            player.captain
        ),
    }


def record_fetch(
    connection: sqlite3.Connection,
    match_id: str,
    provider_fixture_id: str,
    attempted_at: str,
    fetch_status: str,
    home_starters_count: int,
    away_starters_count: int,
    http_status: int | None,
    response_hash: str | None,
    raw_payload_json: str | None,
    error_message: str | None,
) -> None:
    fetch_id = make_fetch_id(
        match_id=match_id,
        attempted_at=attempted_at,
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
            home_starters_count,
            away_starters_count,
            http_status,
            response_hash,
            raw_payload_json,
            error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fetch_id,
            match_id,
            PROVIDER,
            provider_fixture_id,
            attempted_at,
            fetch_status,
            home_starters_count,
            away_starters_count,
            http_status,
            response_hash,
            raw_payload_json,
            error_message,
        ),
    )


def find_player_mapping(
    connection: sqlite3.Connection,
    provider_player_id: str,
) -> tuple[str | None, str]:
    row = connection.execute(
        """
        SELECT
            internal_entity_id,
            mapping_status
        FROM external_provider_mappings
        WHERE provider = ?
          AND entity_type = 'PLAYER'
          AND external_entity_id = ?
          AND mapping_status IN (
              'CONFIRMED',
              'AUTOMATIC',
              'MANUAL'
          )
        LIMIT 1
        """,
        (
            PROVIDER,
            provider_player_id,
        ),
    ).fetchone()

    if row is None:
        return None, "UNMATCHED"

    return (
        str(row["internal_entity_id"]),
        str(row["mapping_status"]),
    )


def ensure_internal_player(
    connection: sqlite3.Connection,
    match_id: str,
    team_id: str,
    player: ParsedPlayer,
) -> tuple[str, str]:
    provider_player_id = str(
        player.provider_player_id
    ).strip()

    if not provider_player_id:
        raise Ligue1LineupError(
            "Não é possível criar um jogador "
            "sem provider_player_id."
        )

    season_row = connection.execute(
        """
        SELECT season_label
        FROM matches
        WHERE match_id = ?
        LIMIT 1
        """,
        (match_id,),
    ).fetchone()

    if season_row is None:
        raise Ligue1LineupError(
            f"Jogo não encontrado: {match_id}"
        )

    season_label = str(
        season_row["season_label"]
    )

    player_id = (
        f"PLAYER__{PROVIDER}__"
        f"{safe_identifier(provider_player_id)}"
    )

    normalized_name = normalize_player_name(
        player.player_name
    )

    if not normalized_name:
        normalized_name = (
            normalize_player_name(
                provider_player_id
            )
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
        ON CONFLICT (player_id)
        DO UPDATE SET
            full_name = excluded.full_name,
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
            player.player_name,
            normalized_name,
            player.position_code,
        ),
    )

    team_squad_id = (
        f"SQUAD__{safe_identifier(team_id)}__"
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
        ON CONFLICT (
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
                ),
            squad_status = 'ACTIVE',
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            team_squad_id,
            team_id,
            player_id,
            season_label,
            player.shirt_number,
            player.position_code,
        ),
    )

    mapping_id = create_mapping_id(
        entity_type="PLAYER",
        internal_entity_id=player_id,
        external_entity_id=(
            provider_player_id
        ),
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
        ON CONFLICT (
            provider,
            entity_type,
            external_entity_id
        )
        DO UPDATE SET
            internal_entity_id =
                excluded.internal_entity_id,
            external_name =
                excluded.external_name,
            mapping_status = 'AUTOMATIC',
            confidence = 1.0,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            mapping_id,
            PROVIDER,
            player_id,
            provider_player_id,
            player.player_name,
        ),
    )

    return player_id, "AUTOMATIC"


def create_lineup_id(
    match_id: str,
    lineup_hash: str,
) -> str:
    return (
        f"{PROVIDER}__"
        f"{safe_identifier(match_id)}__"
        f"{lineup_hash[:16]}"
    )


def store_lineup_player(
    connection: sqlite3.Connection,
    lineup_id: str,
    match_id: str,
    team_id: str,
    player: ParsedPlayer,
) -> None:
    player_id, mapping_status = (
        find_player_mapping(
            connection=connection,
            provider_player_id=(
                player.provider_player_id
            ),
        )
    )

    if player_id is None:
        player_id, mapping_status = (
            ensure_internal_player(
                connection=connection,
                match_id=match_id,
                team_id=team_id,
                player=player,
            )
        )

    lineup_player_id = (
        f"{lineup_id}__"
        f"{safe_identifier(team_id)}__"
        f"{player.role}__"
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lineup_player_id,
            lineup_id,
            match_id,
            team_id,
            player_id,
            player.provider_player_id,
            player.player_name,
            player.role,
            player.position_code,
            player.formation_position,
            player.shirt_number,
            1 if player.captain else 0,
            mapping_status,
        ),
    )


def store_confirmed_lineup(
    connection: sqlite3.Connection,
    match: sqlite3.Row,
    parameters: MatchEndpointParameters,
    parsed: ParsedMatchLineup,
    payload_json: str,
    fetched_at: str,
) -> tuple[str, str, bool]:
    home_hash_players = [
        player_to_hash_dict(player)
        for player in parsed.home.starters
    ]

    away_hash_players = [
        player_to_hash_dict(player)
        for player in parsed.away.starters
    ]

    lineup_hash = calculate_lineup_hash(
        match_id=str(match["match_id"]),
        home_players=home_hash_players,
        away_players=away_hash_players,
    )

    existing = connection.execute(
        """
        SELECT
            lineup_id,
            lineup_hash,
            is_current
        FROM match_lineups
        WHERE match_id = ?
          AND lineup_hash = ?
        LIMIT 1
        """,
        (
            match["match_id"],
            lineup_hash,
        ),
    ).fetchone()

    if existing is not None:
        return (
            str(existing["lineup_id"]),
            lineup_hash,
            False,
        )

    lineup_id = create_lineup_id(
        match_id=str(match["match_id"]),
        lineup_hash=lineup_hash,
    )

    connection.execute(
        """
        UPDATE match_lineups
        SET
            is_current = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE match_id = ?
          AND is_current = 1
        """,
        (match["match_id"],),
    )

    connection.execute(
        """
        INSERT INTO match_lineups (
            lineup_id,
            match_id,
            provider,
            provider_fixture_id,
            lineup_status,
            home_formation,
            away_formation,
            lineup_hash,
            announced_at,
            fetched_at,
            is_current,
            raw_payload_json
        )
        VALUES (
            ?, ?, ?, ?, 'CONFIRMED',
            ?, ?, ?, ?, ?, 1, ?
        )
        """,
        (
            lineup_id,
            match["match_id"],
            PROVIDER,
            parameters.provider_fixture_id,
            parsed.home.formation,
            parsed.away.formation,
            lineup_hash,
            fetched_at,
            fetched_at,
            payload_json,
        ),
    )

    home_team_id = str(
        match["home_team_id"]
    )

    away_team_id = str(
        match["away_team_id"]
    )

    for player in (
        *parsed.home.starters,
        *parsed.home.substitutes,
    ):
        store_lineup_player(
            connection=connection,
            lineup_id=lineup_id,
            match_id=str(match["match_id"]),
            team_id=home_team_id,
            player=player,
        )

    for player in (
        *parsed.away.starters,
        *parsed.away.substitutes,
    ):
        store_lineup_player(
            connection=connection,
            lineup_id=lineup_id,
            match_id=str(match["match_id"]),
            team_id=away_team_id,
            player=player,
        )

    return lineup_id, lineup_hash, True


def collect_match_lineup(
    match_id: str,
    database_path: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> CollectionResult:
    connection = connect_database(
        database_path
    )

    attempted_at = utc_now()

    try:
        match = load_match(
            connection=connection,
            match_id=match_id,
        )

        parameters = parse_match_source_url(
            str(match["source_url"])
        )

        provider_fixture_id = (
            parameters.provider_fixture_id
        )

        try:
            response, payload = (
                fetch_match_payload(
                    provider_fixture_id=(
                        provider_fixture_id
                    ),
                    timeout=timeout,
                )
            )
        except requests.RequestException as exc:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                provider_fixture_id=(
                    provider_fixture_id
                ),
                attempted_at=attempted_at,
                fetch_status="HTTP_ERROR",
                home_starters_count=0,
                away_starters_count=0,
                http_status=(
                    exc.response.status_code
                    if exc.response is not None
                    else None
                ),
                response_hash=None,
                raw_payload_json=None,
                error_message=str(exc),
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="HTTP_ERROR",
                http_status=(
                    exc.response.status_code
                    if exc.response is not None
                    else None
                ),
                home_starters=0,
                away_starters=0,
                lineup_id=None,
                lineup_hash=None,
                message=str(exc),
            )

        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        response_digest = hashlib.sha256(
            payload_json.encode("utf-8")
        ).hexdigest()

        home_payload = payload.get(
            "home"
        ) or {}

        away_payload = payload.get(
            "away"
        ) or {}

        home_players = (
            home_payload.get("players") or {}
            if isinstance(home_payload, dict)
            else {}
        )

        away_players = (
            away_payload.get("players") or {}
            if isinstance(away_payload, dict)
            else {}
        )

        def raw_starter_count(
            players: Any,
        ) -> int:
            if not isinstance(players, dict):
                return 0

            count = 0

            for player in players.values():
                if not isinstance(player, dict):
                    continue

                value = player.get(
                    "formationPlace"
                )

                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue

                if 1 <= value <= 11:
                    count += 1

            return count

        raw_home_starters = (
            raw_starter_count(home_players)
        )

        raw_away_starters = (
            raw_starter_count(away_players)
        )

        if (
            raw_home_starters == 0
            and raw_away_starters == 0
        ):
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                provider_fixture_id=(
                    provider_fixture_id
                ),
                attempted_at=attempted_at,
                fetch_status="NO_LINEUP",
                home_starters_count=0,
                away_starters_count=0,
                http_status=response.status_code,
                response_hash=response_digest,
                raw_payload_json=payload_json,
                error_message=None,
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="NO_LINEUP",
                http_status=response.status_code,
                home_starters=0,
                away_starters=0,
                lineup_id=None,
                lineup_hash=None,
                message=(
                    "O endpoint respondeu, mas "
                    "o onze ainda não foi publicado."
                ),
            )

        try:
            parsed = parse_match_lineup(
                payload=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                provider_fixture_id=(
                    provider_fixture_id
                ),
                attempted_at=attempted_at,
                fetch_status="HTTP_ERROR",
                home_starters_count=(
                    raw_home_starters
                ),
                away_starters_count=(
                    raw_away_starters
                ),
                http_status=(
                    exc.response.status_code
                    if exc.response is not None
                    else None
                ),
                response_hash=response_digest,
                raw_payload_json=payload_json,
                error_message=str(exc),
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="HTTP_ERROR",
                http_status=(
                    exc.response.status_code
                    if exc.response is not None
                    else None
                ),
                home_starters=(
                    raw_home_starters
                ),
                away_starters=(
                    raw_away_starters
                ),
                lineup_id=None,
                lineup_hash=None,
                message=(
                    "Falha ao enriquecer os "
                    f"jogadores: {exc}"
                ),
            )

        home_count = len(
            parsed.home.starters
        )

        away_count = len(
            parsed.away.starters
        )

        if (
            home_count != 11
            or away_count != 11
        ):
            status = (
                "PARTIAL"
                if (
                    home_count > 0
                    or away_count > 0
                )
                else "INVALID"
            )

            connection.execute(
                "BEGIN IMMEDIATE"
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                provider_fixture_id=(
                    provider_fixture_id
                ),
                attempted_at=attempted_at,
                fetch_status=status,
                home_starters_count=home_count,
                away_starters_count=away_count,
                http_status=response.status_code,
                response_hash=response_digest,
                raw_payload_json=payload_json,
                error_message=(
                    "Era esperado um total de "
                    "11 titulares por equipa."
                ),
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status=status,
                http_status=response.status_code,
                home_starters=home_count,
                away_starters=away_count,
                lineup_id=None,
                lineup_hash=None,
                message=(
                    "Resposta recebida, mas não "
                    "contém 11 titulares por equipa."
                ),
            )

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        lineup_id, lineup_hash, inserted = (
            store_confirmed_lineup(
                connection=connection,
                match=match,
                parameters=parameters,
                parsed=parsed,
                payload_json=payload_json,
                fetched_at=attempted_at,
            )
        )

        record_fetch(
            connection=connection,
            match_id=match_id,
            provider_fixture_id=(
                provider_fixture_id
            ),
            attempted_at=attempted_at,
            fetch_status="SUCCESS",
            home_starters_count=home_count,
            away_starters_count=away_count,
            http_status=response.status_code,
            response_hash=response_digest,
            raw_payload_json=payload_json,
            error_message=None,
        )

        connection.commit()

        return CollectionResult(
            match_id=match_id,
            fetch_status="SUCCESS",
            http_status=response.status_code,
            home_starters=home_count,
            away_starters=away_count,
            lineup_id=lineup_id,
            lineup_hash=lineup_hash,
            message=(
                "Novo onze confirmado gravado."
                if inserted
                else (
                    "O onze confirmado já "
                    "estava gravado."
                )
            ),
        )

    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recolhe o onze oficial de um "
            "jogo da Ligue 1."
        )
    )

    parser.add_argument(
        "match_id",
        help="match_id interno FOOTWIN.",
    )

    parser.add_argument(
        "--database-path",
        default=None,
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
    )

    args = parser.parse_args()

    result = collect_match_lineup(
        match_id=args.match_id,
        database_path=args.database_path,
        timeout=args.timeout,
    )

    print(f"match_id: {result.match_id}")
    print(f"fetch_status: {result.fetch_status}")
    print(f"http_status: {result.http_status}")
    print(f"home_starters: {result.home_starters}")
    print(f"away_starters: {result.away_starters}")
    print(f"lineup_id: {result.lineup_id}")
    print(f"lineup_hash: {result.lineup_hash}")
    print(f"message: {result.message}")


if __name__ == "__main__":
    main()
