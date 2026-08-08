# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.database.init_database import connect_database


MIN_ATTACK_FACTOR = 0.88
MAX_ATTACK_FACTOR = 1.12

MIN_DEFENCE_FACTOR = 0.88
MAX_DEFENCE_FACTOR = 1.12

MIN_GOALKEEPER_FACTOR = 0.90
MAX_GOALKEEPER_FACTOR = 1.10


class LineupContextError(RuntimeError):
    """Erro ao carregar ou avaliar um onze inicial."""


@dataclass(frozen=True)
class TeamLineupContext:
    team_id: str
    starters_count: int

    attack_factor: float
    defence_factor: float
    goalkeeper_factor: float

    mapped_players: int
    unmapped_players: int

    formation: str | None
    data_quality: str


@dataclass(frozen=True)
class MatchLineupContext:
    lineup_id: str
    lineup_hash: str
    match_id: str
    lineup_confirmed: bool

    home: TeamLineupContext
    away: TeamLineupContext

    data_quality: str

    def to_snapshot_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(
        minimum,
        min(maximum, value),
    )


def normalize_position(
    position_code: str | None,
) -> str:
    value = str(
        position_code or ""
    ).strip().upper()

    goalkeeper_codes = {
        "GK",
        "G",
        "GOALKEEPER",
        "GUARDA-REDES",
        "GR",
    }

    defender_codes = {
        "CB",
        "LB",
        "RB",
        "LWB",
        "RWB",
        "DF",
        "DEF",
        "DEFENDER",
    }

    midfielder_codes = {
        "DM",
        "CM",
        "AM",
        "LM",
        "RM",
        "MF",
        "MID",
        "MIDFIELDER",
    }

    attacker_codes = {
        "LW",
        "RW",
        "ST",
        "CF",
        "SS",
        "FW",
        "ATT",
        "FORWARD",
    }

    if value in goalkeeper_codes:
        return "GOALKEEPER"

    if value in defender_codes:
        return "DEFENDER"

    if value in midfielder_codes:
        return "MIDFIELDER"

    if value in attacker_codes:
        return "ATTACKER"

    return "UNKNOWN"


def calculate_team_lineup_factors(
    starters: list[sqlite3.Row],
) -> tuple[
    float,
    float,
    float,
    int,
    int,
    str,
]:
    """
    Calcula fatores conservadores para um onze.

    Nesta fase ainda não existem ratings individuais.
    Por isso são usados:
    - completude do mapeamento;
    - equilíbrio posicional;
    - presença de guarda-redes;
    - total de onze titulares.

    Quando os ratings individuais forem importados,
    esta função será enriquecida sem alterar o modelo.
    """

    starters_count = len(starters)

    mapped_players = sum(
        1
        for player in starters
        if player["player_id"] is not None
    )

    unmapped_players = (
        starters_count - mapped_players
    )

    positions = [
        normalize_position(
            player["position_code"]
        )
        for player in starters
    ]

    goalkeeper_count = positions.count(
        "GOALKEEPER"
    )
    defender_count = positions.count(
        "DEFENDER"
    )
    midfielder_count = positions.count(
        "MIDFIELDER"
    )
    attacker_count = positions.count(
        "ATTACKER"
    )

    completeness = min(
        starters_count / 11.0,
        1.0,
    )

    mapping_ratio = (
        mapped_players / starters_count
        if starters_count
        else 0.0
    )

    attack_factor = 1.0
    defence_factor = 1.0
    goalkeeper_factor = 1.0

    if starters_count < 11:
        missing_ratio = (
            11 - starters_count
        ) / 11.0

        attack_factor -= (
            0.06 * missing_ratio
        )
        defence_factor -= (
            0.06 * missing_ratio
        )

    if attacker_count == 0:
        attack_factor -= 0.025
    elif attacker_count >= 4:
        attack_factor += 0.015

    if midfielder_count < 2:
        attack_factor -= 0.010
        defence_factor -= 0.010
    elif midfielder_count >= 5:
        attack_factor += 0.005
        defence_factor += 0.005

    if defender_count < 3:
        defence_factor -= 0.025
    elif defender_count >= 5:
        defence_factor += 0.015

    if goalkeeper_count == 0:
        goalkeeper_factor -= 0.070
        defence_factor -= 0.030
    elif goalkeeper_count > 1:
        goalkeeper_factor -= 0.020

    mapping_penalty = (
        1.0 - mapping_ratio
    ) * 0.015

    attack_factor -= mapping_penalty
    defence_factor -= mapping_penalty

    attack_factor = clamp(
        attack_factor,
        MIN_ATTACK_FACTOR,
        MAX_ATTACK_FACTOR,
    )

    defence_factor = clamp(
        defence_factor,
        MIN_DEFENCE_FACTOR,
        MAX_DEFENCE_FACTOR,
    )

    goalkeeper_factor = clamp(
        goalkeeper_factor,
        MIN_GOALKEEPER_FACTOR,
        MAX_GOALKEEPER_FACTOR,
    )

    if (
        starters_count == 11
        and goalkeeper_count == 1
        and mapping_ratio >= 0.90
    ):
        data_quality = "COMPLETE"

    elif (
        starters_count == 11
        and goalkeeper_count == 1
    ):
        data_quality = "PARTIAL_MAPPING"

    else:
        data_quality = "FALLBACK_USED"

    return (
        round(attack_factor, 6),
        round(defence_factor, 6),
        round(goalkeeper_factor, 6),
        mapped_players,
        unmapped_players,
        data_quality,
    )


def combine_data_quality(
    home_quality: str,
    away_quality: str,
) -> str:
    ranking = {
        "COMPLETE": 1,
        "PARTIAL_MAPPING": 2,
        "FALLBACK_USED": 3,
    }

    qualities = [
        home_quality,
        away_quality,
    ]

    return max(
        qualities,
        key=lambda quality: ranking.get(
            quality,
            99,
        ),
    )


def calculate_lineup_hash(
    match_id: str,
    home_players: list[dict[str, Any]],
    away_players: list[dict[str, Any]],
) -> str:
    payload = {
        "match_id": match_id,
        "home": sorted(
            home_players,
            key=lambda item: (
                str(item.get("provider_player_id") or ""),
                str(item.get("player_name") or ""),
            ),
        ),
        "away": sorted(
            away_players,
            key=lambda item: (
                str(item.get("provider_player_id") or ""),
                str(item.get("player_name") or ""),
            ),
        ),
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def load_match_lineup_context(
    match_id: str,
    database_path: str | Path | None = None,
) -> MatchLineupContext | None:
    """
    Carrega o onze atual e confirmado de um jogo.

    Retorna None quando ainda não existe um onze
    confirmado e válido para ambas as equipas.
    """

    connection = connect_database(
        database_path
    )

    try:
        lineup = connection.execute(
            """
            SELECT
                ml.lineup_id,
                ml.match_id,
                ml.lineup_hash,
                ml.lineup_status,
                ml.home_formation,
                ml.away_formation,
                m.home_team_id,
                m.away_team_id
            FROM match_lineups AS ml
            INNER JOIN matches AS m
                ON m.match_id = ml.match_id
            WHERE ml.match_id = ?
              AND ml.is_current = 1
              AND ml.lineup_status IN (
                  'CONFIRMED',
                  'CORRECTED'
              )
            LIMIT 1
            """,
            (match_id,),
        ).fetchone()

        if lineup is None:
            return None

        players = connection.execute(
            """
            SELECT
                lineup_player_id,
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
            FROM match_lineup_players
            WHERE lineup_id = ?
              AND role = 'STARTER'
            ORDER BY
                team_id,
                shirt_number,
                player_name
            """,
            (lineup["lineup_id"],),
        ).fetchall()

        home_starters = [
            player
            for player in players
            if player["team_id"]
            == lineup["home_team_id"]
        ]

        away_starters = [
            player
            for player in players
            if player["team_id"]
            == lineup["away_team_id"]
        ]

        if (
            len(home_starters) != 11
            or len(away_starters) != 11
        ):
            return None

        (
            home_attack,
            home_defence,
            home_goalkeeper,
            home_mapped,
            home_unmapped,
            home_quality,
        ) = calculate_team_lineup_factors(
            home_starters
        )

        (
            away_attack,
            away_defence,
            away_goalkeeper,
            away_mapped,
            away_unmapped,
            away_quality,
        ) = calculate_team_lineup_factors(
            away_starters
        )

        final_quality = combine_data_quality(
            home_quality,
            away_quality,
        )

        return MatchLineupContext(
            lineup_id=str(
                lineup["lineup_id"]
            ),
            lineup_hash=str(
                lineup["lineup_hash"]
            ),
            match_id=str(
                lineup["match_id"]
            ),
            lineup_confirmed=True,
            home=TeamLineupContext(
                team_id=str(
                    lineup["home_team_id"]
                ),
                starters_count=(
                    len(home_starters)
                ),
                attack_factor=home_attack,
                defence_factor=home_defence,
                goalkeeper_factor=(
                    home_goalkeeper
                ),
                mapped_players=home_mapped,
                unmapped_players=home_unmapped,
                formation=(
                    lineup["home_formation"]
                ),
                data_quality=home_quality,
            ),
            away=TeamLineupContext(
                team_id=str(
                    lineup["away_team_id"]
                ),
                starters_count=(
                    len(away_starters)
                ),
                attack_factor=away_attack,
                defence_factor=away_defence,
                goalkeeper_factor=(
                    away_goalkeeper
                ),
                mapped_players=away_mapped,
                unmapped_players=away_unmapped,
                formation=(
                    lineup["away_formation"]
                ),
                data_quality=away_quality,
            ),
            data_quality=final_quality,
        )

    finally:
        connection.close()
