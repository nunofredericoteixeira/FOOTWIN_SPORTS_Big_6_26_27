# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import html as html_module
import json
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.database.init_database import connect_database
from src.models.lineup_context_service import calculate_lineup_hash


PROVIDER = "BUNDESLIGA"
DEFAULT_TIMEOUT = 30

USER_AGENT = (
    "Mozilla/5.0 "
    "(Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


class BundesligaLineupError(RuntimeError):
    pass


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
    team_name: str
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
    ).isoformat(timespec="seconds")


def safe_identifier(value: str) -> str:
    return re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        str(value).strip(),
    ).strip("_")


def normalize_name(
    value: str | None,
) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text.casefold(),
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def parse_provider_fixture_id(
    match_id: str,
) -> str:
    found = re.search(
        r"_(DFLJ[A-Z0-9]+)_",
        str(match_id),
        flags=re.IGNORECASE,
    )

    if found is None:
        raise BundesligaLineupError(
            f"ID DFL não encontrado em {match_id}"
        )

    return (
        "DFL-MAT-"
        + found.group(1).upper().removeprefix("DFL")
    )


def build_match_base_url(
    source_url: str,
) -> str:
    value = str(
        source_url or ""
    ).strip()

    if not value:
        raise BundesligaLineupError(
            "Jogo sem source_url."
        )

    result = re.sub(
        r"/(?:liveticker|lineup|stats|table|news)/?$",
        "",
        value,
        flags=re.IGNORECASE,
    )

    if "/bundesliga/matchday/" not in result.lower():
        raise BundesligaLineupError(
            "source_url Bundesliga inválido."
        )

    return result


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
        JOIN teams AS ht
          ON ht.team_id = m.home_team_id
        JOIN teams AS at
          ON at.team_id = m.away_team_id
        WHERE m.match_id = ?
        LIMIT 1
        """,
        (match_id,),
    ).fetchone()

    if row is None:
        raise BundesligaLineupError(
            f"Jogo não encontrado: {match_id}"
        )

    if str(
        row["league_id"]
    ).upper() != "GER1":
        raise BundesligaLineupError(
            "Collector Bundesliga aceita apenas GER1."
        )

    return row


def fetch_match_html(
    source_url: str,
    timeout: int,
) -> tuple[
    requests.Response,
    str,
]:
    url = build_match_base_url(
        source_url
    )

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml"
            ),
        },
    )

    response.raise_for_status()

    return response, response.text


def classify_tactical_positions(
    players: list[dict],
) -> list[dict]:
    if len(players) != 11:
        return players

    levels = sorted(
        {
            round(
                float(player["y"]),
                3,
            )
            for player in players
        },
        reverse=True,
    )

    if len(levels) < 4:
        return players

    goalkeeper_y = levels[0]
    defender_y = levels[1]
    forward_y = levels[-1]

    classified = []

    for player in players:
        y = round(
            float(player["y"]),
            3,
        )

        if y == goalkeeper_y:
            position_code = "GK"
        elif y == defender_y:
            position_code = "DF"
        elif y == forward_y:
            position_code = "FW"
        else:
            position_code = "MF"

        classified.append(
            {
                **player,
                "position_code":
                    position_code,
            }
        )

    return classified


def parse_team_blocks(
    page: str,
) -> dict[str, ParsedTeamLineup]:
    blocks = re.findall(
        r"<livetickerevent-lineup\b.*?"
        r"</livetickerevent-lineup>",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )

    result = {}

    for block in blocks:
        headline = re.search(
            r"Starting line-up:\s*([^<]+)",
            block,
            flags=re.IGNORECASE,
        )

        if headline is None:
            continue

        team_name = html_module.unescape(
            headline.group(1)
        ).strip()

        matches = re.findall(
            r'<foreignObject[^>]*\bx="([^"]+)"'
            r'[^>]*\by="([^"]+)"'
            r'[^>]*>.*?'
            r'<a[^>]*class="player-link"'
            r'[^>]*href="/en/player/([^"]+)"'
            r'.*?'
            r'<img[^>]*alt="([^"]+)"',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

        unique = {}

        for x, y, slug, name in matches:
            slug = slug.strip()

            if not slug or slug in unique:
                continue

            unique[slug] = {
                "provider_player_id":
                    slug,
                "player_name":
                    html_module.unescape(
                        name
                    ).strip(),
                "x":
                    float(x),
                "y":
                    float(y),
            }

        players = list(
            unique.values()
        )

        if len(players) != 11:
            continue

        players = classify_tactical_positions(
            players
        )

        starters = tuple(
            ParsedPlayer(
                provider_player_id=(
                    player[
                        "provider_player_id"
                    ]
                ),
                player_name=(
                    player["player_name"]
                ),
                role="STARTER",
                position_code=(
                    player.get(
                        "position_code"
                    )
                ),
                formation_position=str(index),
                shirt_number=None,
                captain=False,
            )
            for index, player
            in enumerate(
                players,
                start=1,
            )
        )

        result[
            normalize_name(team_name)
        ] = ParsedTeamLineup(
            team_name=team_name,
            formation=None,
            starters=starters,
            substitutes=tuple(),
        )

    return result


def parse_match_lineup(
    page: str,
    home_team_name: str,
    away_team_name: str,
) -> ParsedMatchLineup | None:
    teams = parse_team_blocks(
        page
    )

    home = teams.get(
        normalize_name(home_team_name)
    )

    away = teams.get(
        normalize_name(away_team_name)
    )

    if home is None or away is None:
        return None

    if (
        len(home.starters) != 11
        or len(away.starters) != 11
    ):
        return None

    return ParsedMatchLineup(
        home=home,
        away=away,
    )


def player_to_hash_dict(
    player: ParsedPlayer,
) -> dict:
    return {
        "provider_player_id":
            player.provider_player_id,
        "player_name":
            player.player_name,
        "position_code":
            player.position_code,
        "formation_position":
            player.formation_position,
        "shirt_number":
            player.shirt_number,
        "captain":
            player.captain,
    }


def create_mapping_id(
    internal_entity_id: str,
    external_entity_id: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"{PROVIDER}|PLAYER|"
            f"{internal_entity_id}|"
            f"{external_entity_id}"
        ).encode("utf-8")
    ).hexdigest()[:20]

    return (
        f"MAP__{PROVIDER}__PLAYER__{digest}"
    )


def record_fetch(
    connection: sqlite3.Connection,
    match_id: str,
    provider_fixture_id: str,
    attempted_at: str,
    fetch_status: str,
    home_starters_count: int = 0,
    away_starters_count: int = 0,
    http_status: int | None = None,
    response_hash: str | None = None,
    raw_payload_json: str | None = None,
    error_message: str | None = None,
) -> None:
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



def ensure_internal_player(
    connection: sqlite3.Connection,
    match_id: str,
    team_id: str,
    player: ParsedPlayer,
) -> str:
    player_id = (
        f"PLAYER__{PROVIDER}__"
        f"{safe_identifier(player.provider_player_id)}"
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
            normalize_name(
                player.player_name
            ),
            player.position_code,
        ),
    )

    season = connection.execute(
        """
        SELECT season_label
        FROM matches
        WHERE match_id = ?
        LIMIT 1
        """,
        (match_id,),
    ).fetchone()

    if season is None:
        raise BundesligaLineupError(
            f"Jogo não encontrado: {match_id}"
        )

    season_label = str(
        season["season_label"]
    )

    squad_id = (
        f"SQUAD__{safe_identifier(team_id)}__"
        f"{safe_identifier(player_id)}__"
        f"{safe_identifier(season_label)}"
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
                ),
            squad_status = 'ACTIVE',
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            squad_id,
            team_id,
            player_id,
            season_label,
            player.shirt_number,
            player.position_code,
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
        ON CONFLICT(
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
            create_mapping_id(
                player_id,
                player.provider_player_id,
            ),
            PROVIDER,
            player_id,
            player.provider_player_id,
            player.player_name,
        ),
    )

    return player_id


def ensure_team_squad(
    connection: sqlite3.Connection,
    match_id: str,
    team_id: str,
    player_id: str,
    player: ParsedPlayer,
) -> None:
    season = connection.execute(
        """
        SELECT season_label
        FROM matches
        WHERE match_id = ?
        LIMIT 1
        """,
        (match_id,),
    ).fetchone()

    if season is None:
        raise BundesligaLineupError(
            f"Jogo não encontrado: {match_id}"
        )

    season_label = str(
        season["season_label"]
    )

    squad_id = (
        f"SQUAD__{safe_identifier(team_id)}__"
        f"{safe_identifier(player_id)}__"
        f"{safe_identifier(season_label)}"
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
                ),
            squad_status = 'ACTIVE',
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            squad_id,
            team_id,
            player_id,
            season_label,
            player.shirt_number,
            player.position_code,
        ),
    )



def store_lineup_player(
    connection: sqlite3.Connection,
    lineup_id: str,
    match_id: str,
    team_id: str,
    player: ParsedPlayer,
) -> None:
    mapped = connection.execute(
        """
        SELECT internal_entity_id
        FROM external_provider_mappings
        WHERE provider = ?
          AND entity_type = 'PLAYER'
          AND external_entity_id = ?
        LIMIT 1
        """,
        (
            PROVIDER,
            player.provider_player_id,
        ),
    ).fetchone()

    if mapped is None:
        player_id = ensure_internal_player(
            connection,
            match_id,
            team_id,
            player,
        )
    else:
        player_id = str(
            mapped["internal_entity_id"]
        )

        ensure_team_squad(
            connection=connection,
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            player=player,
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
            "AUTOMATIC",
        ),
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
            connection,
            match_id,
        )

        provider_fixture_id = (
            parse_provider_fixture_id(
                match_id
            )
        )

        try:
            response, page = (
                fetch_match_html(
                    str(
                        match["source_url"]
                    ),
                    timeout,
                )
            )

        except requests.RequestException as exc:
            http_status = (
                exc.response.status_code
                if exc.response is not None
                else None
            )

            connection.execute(
                "BEGIN IMMEDIATE"
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                provider_fixture_id=provider_fixture_id,
                attempted_at=attempted_at,
                fetch_status="HTTP_ERROR",
                http_status=http_status,
                error_message=str(exc),
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="HTTP_ERROR",
                http_status=http_status,
                home_starters=0,
                away_starters=0,
                lineup_id=None,
                lineup_hash=None,
                message=str(exc),
            )

        response_hash = hashlib.sha256(
            page.encode("utf-8")
        ).hexdigest()

        parsed = parse_match_lineup(
            page,
            str(
                match["home_team_name"]
            ),
            str(
                match["away_team_name"]
            ),
        )

        if parsed is None:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                provider_fixture_id=provider_fixture_id,
                attempted_at=attempted_at,
                fetch_status="NO_LINEUP",
                home_starters_count=0,
                away_starters_count=0,
                http_status=response.status_code,
                response_hash=response_hash,
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
                    "O onze ainda não foi publicado."
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
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                provider_fixture_id=provider_fixture_id,
                attempted_at=attempted_at,
                fetch_status="PARTIAL",
                home_starters_count=home_count,
                away_starters_count=away_count,
                http_status=response.status_code,
                response_hash=response_hash,
                error_message=(
                    "Era esperado um total de "
                    "11 titulares por equipa."
                ),
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="PARTIAL",
                http_status=response.status_code,
                home_starters=home_count,
                away_starters=away_count,
                lineup_id=None,
                lineup_hash=None,
                message=(
                    "Não existem 11 titulares "
                    "por equipa."
                ),
            )

        lineup_hash = calculate_lineup_hash(
            match_id=match_id,
            home_players=[
                player_to_hash_dict(p)
                for p in (
                    parsed.home.starters
                )
            ],
            away_players=[
                player_to_hash_dict(p)
                for p in (
                    parsed.away.starters
                )
            ],
        )

        existing = connection.execute(
            """
            SELECT lineup_id
            FROM match_lineups
            WHERE match_id = ?
              AND lineup_hash = ?
            LIMIT 1
            """,
            (
                match_id,
                lineup_hash,
            ),
        ).fetchone()

        if existing is not None:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            record_fetch(
                connection=connection,
                match_id=match_id,
                provider_fixture_id=provider_fixture_id,
                attempted_at=attempted_at,
                fetch_status="SUCCESS",
                home_starters_count=11,
                away_starters_count=11,
                http_status=response.status_code,
                response_hash=response_hash,
            )

            connection.commit()

            return CollectionResult(
                match_id=match_id,
                fetch_status="SUCCESS",
                http_status=response.status_code,
                home_starters=11,
                away_starters=11,
                lineup_id=str(
                    existing["lineup_id"]
                ),
                lineup_hash=lineup_hash,
                message=(
                    "O onze confirmado já estava gravado."
                ),
            )

        lineup_id = (
            f"{PROVIDER}__"
            f"{safe_identifier(match_id)}__"
            f"{lineup_hash[:16]}"
        )

        payload_json = json.dumps(
            {
                "source_url":
                    build_match_base_url(
                        str(
                            match["source_url"]
                        )
                    ),
                "provider_fixture_id":
                    provider_fixture_id,
                "home": [
                    player_to_hash_dict(p)
                    for p in (
                        parsed.home.starters
                    )
                ],
                "away": [
                    player_to_hash_dict(p)
                    for p in (
                        parsed.away.starters
                    )
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        connection.execute(
            """
            UPDATE match_lineups
            SET
                is_current = 0,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE match_id = ?
              AND is_current = 1
            """,
            (match_id,),
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
                match_id,
                PROVIDER,
                provider_fixture_id,
                parsed.home.formation,
                parsed.away.formation,
                lineup_hash,
                attempted_at,
                attempted_at,
                payload_json,
            ),
        )

        for player in (
            parsed.home.starters
        ):
            store_lineup_player(
                connection,
                lineup_id,
                match_id,
                str(
                    match["home_team_id"]
                ),
                player,
            )

        for player in (
            parsed.away.starters
        ):
            store_lineup_player(
                connection,
                lineup_id,
                match_id,
                str(
                    match["away_team_id"]
                ),
                player,
            )

        record_fetch(
            connection=connection,
            match_id=match_id,
            provider_fixture_id=provider_fixture_id,
            attempted_at=attempted_at,
            fetch_status="SUCCESS",
            home_starters_count=11,
            away_starters_count=11,
            http_status=response.status_code,
            response_hash=response_hash,
            raw_payload_json=payload_json,
        )

        connection.commit()

        return CollectionResult(
            match_id=match_id,
            fetch_status="SUCCESS",
            http_status=response.status_code,
            home_starters=11,
            away_starters=11,
            lineup_id=lineup_id,
            lineup_hash=lineup_hash,
            message=(
                "Novo onze confirmado gravado."
            ),
        )

    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise

    finally:
        connection.close()
