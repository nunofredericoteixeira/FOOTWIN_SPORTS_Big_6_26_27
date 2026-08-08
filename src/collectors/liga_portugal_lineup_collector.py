# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from src.database.init_database import connect_database
from src.models.lineup_context_service import (
    calculate_lineup_hash,
)


PROVIDER = "LIGA_PORTUGAL"
DEFAULT_TIMEOUT = 30

USER_AGENT = (
    "Mozilla/5.0 "
    "(Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


class LigaPortugalLineupError(RuntimeError):
    """Erro na recolha de onzes da Liga Portugal."""


@dataclass(frozen=True)
class MatchEndpointParameters:
    season: str
    competition: str
    round_number: int
    fixture_number: int
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
    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


def safe_identifier(value: str) -> str:
    normalized = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        str(value).strip(),
    )

    return normalized.strip("_")


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
    """
    Exemplo esperado:

    https://www.ligaportugal.pt/
    match/20262027/ligaportugalbetclic/1/9
    """

    parsed_url = urlparse(
        str(source_url).strip()
    )

    path_parts = [
        part
        for part in parsed_url.path.split("/")
        if part
    ]

    try:
        match_index = path_parts.index(
            "match"
        )

        season = path_parts[
            match_index + 1
        ]

        competition = path_parts[
            match_index + 2
        ]

        round_number = int(
            path_parts[
                match_index + 3
            ]
        )

        fixture_number = int(
            path_parts[
                match_index + 4
            ]
        )

    except (
        ValueError,
        IndexError,
    ) as exc:
        raise LigaPortugalLineupError(
            "Não foi possível interpretar "
            f"o source_url: {source_url}"
        ) from exc

    if not season:
        raise LigaPortugalLineupError(
            "A época está vazia no source_url."
        )

    if not competition:
        raise LigaPortugalLineupError(
            "A competição está vazia "
            "no source_url."
        )

    if round_number < 1:
        raise LigaPortugalLineupError(
            "A jornada obtida do source_url "
            "é inválida."
        )

    if fixture_number < 1:
        raise LigaPortugalLineupError(
            "O número do jogo obtido do "
            "source_url é inválido."
        )

    return MatchEndpointParameters(
        season=season,
        competition=competition,
        round_number=round_number,
        fixture_number=fixture_number,
        source_url=source_url,
    )


def create_session() -> requests.Session:
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/json, "
                "text/plain, */*"
            ),
            "Accept-Language": (
                "pt-PT,pt;q=0.9,en;q=0.8"
            ),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )

    return session


def build_endpoint_url() -> str:
    return (
        "https://www.ligaportugal.pt"
        "/api/v1/match/formations"
    )


def fetch_formations(
    parameters: MatchEndpointParameters,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[
    requests.Response,
    Any | None,
]:
    session = create_session()

    session.headers.update(
        {
            "Referer": (
                parameters.source_url
            ),
            "Origin": (
                "https://www.ligaportugal.pt"
            ),
        }
    )

    response = session.get(
        build_endpoint_url(),
        params={
            "season": parameters.season,
            "competition": (
                parameters.competition
            ),
            "round": (
                parameters.round_number
            ),
            "fixture": (
                parameters.fixture_number
            ),
        },
        timeout=timeout,
        allow_redirects=True,
    )

    try:
        payload = response.json()

    except (
        requests.JSONDecodeError,
        ValueError,
    ):
        payload = None

    return response, payload


def unwrap_payload(
    payload: Any,
) -> Any:
    current = payload

    for _ in range(6):
        if not isinstance(
            current,
            dict,
        ):
            break

        moved = False

        for key in (
            "data",
            "value",
            "result",
            "payload",
        ):
            if (
                key in current
                and current[key]
                is not None
            ):
                current = current[key]
                moved = True
                break

        if not moved:
            break

    return current


def get_first_value(
    value: dict[str, Any],
    keys: tuple[str, ...],
) -> Any:
    lowered = {
        str(key).lower(): child
        for key, child
        in value.items()
    }

    for key in keys:
        if key.lower() in lowered:
            return lowered[
                key.lower()
            ]

    return None


def text_or_none(
    value: Any,
) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()

    return cleaned or None


def integer_or_none(
    value: Any,
) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ):
        return None


def bool_value(
    value: Any,
) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(
        value,
        (int, float),
    ):
        return bool(value)

    cleaned = str(
        value or ""
    ).strip().lower()

    return cleaned in {
        "1",
        "true",
        "yes",
        "sim",
        "captain",
    }


def normalize_role(
    participant: dict[str, Any],
    index: int,
) -> str:
    role_value = get_first_value(
        participant,
        (
            "role",
            "lineupRole",
            "lineupType",
            "participantType",
            "status",
            "type",
        ),
    )

    normalized = str(
        role_value or ""
    ).strip().upper()

    starter_markers = {
        "STARTER",
        "STARTING",
        "STARTING_XI",
        "INITIAL",
        "INITIAL_LINEUP",
        "TITULAR",
        "1",
    }

    substitute_markers = {
        "SUBSTITUTE",
        "SUB",
        "BENCH",
        "RESERVE",
        "SUPLENTE",
        "2",
    }

    if normalized in starter_markers:
        return "STARTER"

    if normalized in substitute_markers:
        return "SUBSTITUTE"

    starter_flag = get_first_value(
        participant,
        (
            "starter",
            "isStarter",
            "starting",
            "isStarting",
            "initialLineup",
            "isInitialLineup",
        ),
    )

    if bool_value(starter_flag):
        return "STARTER"

    substitute_flag = get_first_value(
        participant,
        (
            "substitute",
            "isSubstitute",
            "bench",
            "isBench",
        ),
    )

    if bool_value(substitute_flag):
        return "SUBSTITUTE"

    # Alguns payloads devolvem primeiro os 11 titulares.
    if index < 11:
        return "STARTER"

    return "SUBSTITUTE"


def extract_player_object(
    participant: dict[str, Any],
) -> dict[str, Any]:
    player = get_first_value(
        participant,
        (
            "player",
            "athlete",
            "person",
        ),
    )

    if isinstance(
        player,
        dict,
    ):
        merged = dict(participant)

        for key, value in player.items():
            if key not in merged:
                merged[key] = value

        return merged

    return participant


def parse_player(
    participant: dict[str, Any],
    index: int,
) -> ParsedPlayer | None:
    data = extract_player_object(
        participant
    )

    provider_player_id = text_or_none(
        get_first_value(
            data,
            (
                "external_id",
                "externalId",
                "playerId",
                "player_id",
                "id",
                "code",
            ),
        )
    )

    player_name = text_or_none(
        get_first_value(
            data,
            (
                "fullName",
                "fullname",
                "playerName",
                "name",
                "shirtName",
                "displayName",
            ),
        )
    )

    if player_name is None:
        return None

    if provider_player_id is None:
        provider_player_id = (
            hashlib.sha256(
                player_name.lower().encode(
                    "utf-8"
                )
            ).hexdigest()[:20]
        )

    role = normalize_role(
        participant=participant,
        index=index,
    )

    position_code = text_or_none(
        get_first_value(
            data,
            (
                "positionCode",
                "position",
                "playerPosition",
                "positionDescription",
            ),
        )
    )

    formation_position = text_or_none(
        get_first_value(
            participant,
            (
                "formationPosition",
                "tacticalPosition",
                "positionInFormation",
                "fieldPosition",
            ),
        )
    )

    shirt_number = integer_or_none(
        get_first_value(
            data,
            (
                "shirtNumber",
                "kitNumber",
                "number",
                "jerseyNumber",
            ),
        )
    )

    captain = bool_value(
        get_first_value(
            participant,
            (
                "captain",
                "isCaptain",
            ),
        )
    )

    return ParsedPlayer(
        provider_player_id=(
            provider_player_id
        ),
        player_name=player_name,
        role=role,
        position_code=position_code,
        formation_position=(
            formation_position
        ),
        shirt_number=shirt_number,
        captain=captain,
    )


def extract_participant_list(
    team_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = (
        "participants",
        "players",
        "lineup",
        "squad",
        "teamPlayers",
        "athletes",
    )

    for key in candidates:
        value = get_first_value(
            team_payload,
            (key,),
        )

        if isinstance(
            value,
            list,
        ):
            return [
                item
                for item in value
                if isinstance(
                    item,
                    dict,
                )
            ]

        if isinstance(
            value,
            dict,
        ):
            for nested_key in (
                "items",
                "data",
                "value",
                "participants",
                "players",
            ):
                nested = get_first_value(
                    value,
                    (nested_key,),
                )

                if isinstance(
                    nested,
                    list,
                ):
                    return [
                        item
                        for item in nested
                        if isinstance(
                            item,
                            dict,
                        )
                    ]

    return []


def parse_team_lineup(
    team_payload: Any,
) -> ParsedTeamLineup:
    if not isinstance(
        team_payload,
        dict,
    ):
        return ParsedTeamLineup(
            formation=None,
            starters=(),
            substitutes=(),
        )

    formation = text_or_none(
        get_first_value(
            team_payload,
            (
                "formationDescription",
                "formation",
                "tactic",
                "tacticalFormation",
            ),
        )
    )

    raw_participants = (
        extract_participant_list(
            team_payload
        )
    )

    parsed_players: list[
        ParsedPlayer
    ] = []

    for index, participant in enumerate(
        raw_participants
    ):
        parsed = parse_player(
            participant=participant,
            index=index,
        )

        if parsed is not None:
            parsed_players.append(
                parsed
            )

    starters = tuple(
        player
        for player in parsed_players
        if player.role == "STARTER"
    )

    substitutes = tuple(
        player
        for player in parsed_players
        if player.role == "SUBSTITUTE"
    )

    return ParsedTeamLineup(
        formation=formation,
        starters=starters,
        substitutes=substitutes,
    )


def find_team_payload(
    payload: Any,
    team_type: str,
) -> Any:
    if not isinstance(
        payload,
        dict,
    ):
        return None

    if team_type == "home":
        direct_keys = (
            "homeTeam",
            "home",
            "homeLineup",
            "teamHome",
        )
    else:
        direct_keys = (
            "awayTeam",
            "away",
            "awayLineup",
            "teamAway",
        )

    direct = get_first_value(
        payload,
        direct_keys,
    )

    if direct is not None:
        return direct

    for child in payload.values():
        if isinstance(
            child,
            dict,
        ):
            found = find_team_payload(
                child,
                team_type,
            )

            if found is not None:
                return found

    return None


def parse_match_lineup(
    payload: Any,
) -> ParsedMatchLineup:
    unwrapped = unwrap_payload(
        payload
    )

    home_payload = find_team_payload(
        unwrapped,
        "home",
    )

    away_payload = find_team_payload(
        unwrapped,
        "away",
    )

    return ParsedMatchLineup(
        home=parse_team_lineup(
            home_payload
        ),
        away=parse_team_lineup(
            away_payload
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
        raise LigaPortugalLineupError(
            f"Jogo não encontrado: {match_id}"
        )

    if not row["source_url"]:
        raise LigaPortugalLineupError(
            "O jogo não possui source_url."
        )

    return row


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
        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?
        )
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
) -> tuple[
    str | None,
    str,
]:
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
        str(
            row["internal_entity_id"]
        ),
        str(
            row["mapping_status"]
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
        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?
        )
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
) -> tuple[
    str,
    str,
    bool,
]:
    home_hash_players = [
        player_to_hash_dict(player)
        for player
        in parsed.home.starters
    ]

    away_hash_players = [
        player_to_hash_dict(player)
        for player
        in parsed.away.starters
    ]

    lineup_hash = calculate_lineup_hash(
        match_id=str(
            match["match_id"]
        ),
        home_players=(
            home_hash_players
        ),
        away_players=(
            away_hash_players
        ),
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
        match_id=str(
            match["match_id"]
        ),
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
        (
            match["match_id"],
        ),
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
            ?,
            ?,
            ?,
            ?,
            'CONFIRMED',
            ?,
            ?,
            ?,
            ?,
            ?,
            1,
            ?
        )
        """,
        (
            lineup_id,
            match["match_id"],
            PROVIDER,
            str(
                parameters.fixture_number
            ),
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
            match_id=str(
                match["match_id"]
            ),
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
            match_id=str(
                match["match_id"]
            ),
            team_id=away_team_id,
            player=player,
        )

    return (
        lineup_id,
        lineup_hash,
        True,
    )


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
            f"{parameters.season}|"
            f"{parameters.competition}|"
            f"{parameters.round_number}|"
            f"{parameters.fixture_number}"
        )

        try:
            response, payload = (
                fetch_formations(
                    parameters=parameters,
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
                fetch_status=(
                    "HTTP_ERROR"
                ),
                home_starters_count=0,
                away_starters_count=0,
                http_status=None,
                response_hash=None,
                raw_payload_json=None,
                error_message=str(exc),
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

        raw_text = response.text or ""

        response_digest = (
            hashlib.sha256(
                raw_text.encode(
                    "utf-8",
                    errors="ignore",
                )
            ).hexdigest()
        )

        payload_json = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if payload is not None
            else raw_text
        )

        if response.status_code != 200:
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
                fetch_status=(
                    "HTTP_ERROR"
                ),
                home_starters_count=0,
                away_starters_count=0,
                http_status=(
                    response.status_code
                ),
                response_hash=(
                    response_digest
                ),
                raw_payload_json=(
                    payload_json
                ),
                error_message=(
                    f"HTTP "
                    f"{response.status_code}"
                ),
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="HTTP_ERROR",
                http_status=(
                    response.status_code
                ),
                home_starters=0,
                away_starters=0,
                lineup_id=None,
                lineup_hash=None,
                message=(
                    f"Endpoint devolveu HTTP "
                    f"{response.status_code}."
                ),
            )

        if not payload:
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
                http_status=200,
                response_hash=(
                    response_digest
                ),
                raw_payload_json=(
                    payload_json
                ),
                error_message=None,
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="NO_LINEUP",
                http_status=200,
                home_starters=0,
                away_starters=0,
                lineup_id=None,
                lineup_hash=None,
                message=(
                    "O endpoint respondeu, mas "
                    "o onze ainda não foi publicado."
                ),
            )

        parsed = parse_match_lineup(
            payload
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
                home_starters_count=(
                    home_count
                ),
                away_starters_count=(
                    away_count
                ),
                http_status=200,
                response_hash=(
                    response_digest
                ),
                raw_payload_json=(
                    payload_json
                ),
                error_message=(
                    "Era esperado um total de "
                    "11 titulares por equipa."
                ),
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status=status,
                http_status=200,
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
            home_starters_count=(
                home_count
            ),
            away_starters_count=(
                away_count
            ),
            http_status=200,
            response_hash=(
                response_digest
            ),
            raw_payload_json=(
                payload_json
            ),
            error_message=None,
        )

        connection.commit()

        return CollectionResult(
            match_id=match_id,
            fetch_status="SUCCESS",
            http_status=200,
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
        connection.rollback()
        raise

    finally:
        connection.close()


def print_result(
    result: CollectionResult,
) -> None:
    print()
    print("=" * 110)
    print(
        "FOOTWIN SPORTS — RECOLHA DO ONZE"
    )
    print("=" * 110)
    print(
        f"match_id: {result.match_id}"
    )
    print(
        f"Estado da recolha: "
        f"{result.fetch_status}"
    )
    print(
        f"HTTP: {result.http_status}"
    )
    print(
        f"Titulares casa: "
        f"{result.home_starters}"
    )
    print(
        f"Titulares fora: "
        f"{result.away_starters}"
    )
    print(
        f"lineup_id: "
        f"{result.lineup_id}"
    )
    print(
        f"lineup_hash: "
        f"{result.lineup_hash}"
    )
    print(
        f"Mensagem: {result.message}"
    )
    print("=" * 110)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recolhe o onze oficial de um jogo "
            "da Liga Portugal."
        )
    )

    parser.add_argument(
        "--match-id",
        required=True,
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    result = collect_match_lineup(
        match_id=args.match_id,
        timeout=args.timeout,
    )

    print_result(
        result
    )

    if result.fetch_status in {
        "HTTP_ERROR",
        "PROVIDER_ERROR",
        "MAPPING_ERROR",
    }:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
