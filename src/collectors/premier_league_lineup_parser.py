# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PremierLeagueLineupParseError(RuntimeError):
    """Erro ao interpretar um payload de onzes da Pulselive."""


@dataclass(frozen=True)
class PremierLeaguePlayer:
    provider_player_id: str
    opta_player_id: str | None
    display_name: str
    shirt_number: int | None
    match_position: str | None
    registered_position: str | None
    position_description: str | None
    is_captain: bool
    is_starter: bool
    source_order: int
    formation_row: int | None
    formation_slot: int | None


@dataclass(frozen=True)
class PremierLeagueTeamLineup:
    provider_team_id: str
    side: str
    team_name: str
    formation: str | None
    starters: tuple[PremierLeaguePlayer, ...]
    substitutes: tuple[PremierLeaguePlayer, ...]


@dataclass(frozen=True)
class PremierLeagueMatchLineup:
    provider_fixture_id: str
    home: PremierLeagueTeamLineup
    away: PremierLeagueTeamLineup


def _integer(
    value: Any,
    field_name: str,
) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise PremierLeagueLineupParseError(
            f"Valor inválido em {field_name}: {value!r}"
        ) from exc


def _optional_integer(
    value: Any,
) -> int | None:
    if value is None:
        return None

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _optional_text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def _extract_team_identity(
    participant: dict[str, Any],
) -> tuple[str, str]:
    team = participant.get("team")

    if not isinstance(team, dict):
        raise PremierLeagueLineupParseError(
            "Participante sem objeto team válido."
        )

    provider_team_id = str(
        _integer(
            team.get("id"),
            "teams[].team.id",
        )
    )

    team_name = str(
        team.get("name")
        or team.get("shortName")
        or ""
    ).strip()

    if not team_name:
        raise PremierLeagueLineupParseError(
            f"Equipa {provider_team_id} sem nome."
        )

    return provider_team_id, team_name


def _formation_positions(
    formation: dict[str, Any] | None,
) -> dict[int, tuple[int, int]]:
    if not isinstance(formation, dict):
        return {}

    rows = formation.get("players")

    if not isinstance(rows, list):
        return {}

    positions: dict[int, tuple[int, int]] = {}

    for row_index, row in enumerate(
        rows,
        start=1,
    ):
        if not isinstance(row, list):
            continue

        for slot_index, player_id in enumerate(
            row,
            start=1,
        ):
            normalized_id = _integer(
                player_id,
                "formation.players",
            )

            if normalized_id in positions:
                raise PremierLeagueLineupParseError(
                    "Jogador repetido na formação: "
                    f"{normalized_id}"
                )

            positions[normalized_id] = (
                row_index,
                slot_index,
            )

    return positions


def _parse_player(
    raw_player: dict[str, Any],
    *,
    is_starter: bool,
    source_order: int,
    formation_positions: dict[int, tuple[int, int]],
) -> PremierLeaguePlayer:
    provider_player_id_int = _integer(
        raw_player.get("id"),
        "player.id",
    )

    provider_player_id = str(
        provider_player_id_int
    )

    name = raw_player.get("name") or {}

    if not isinstance(name, dict):
        name = {}

    display_name = str(
        name.get("display")
        or " ".join(
            str(name.get(key) or "").strip()
            for key in ("first", "middle", "last")
        ).strip()
    ).strip()

    if not display_name:
        raise PremierLeagueLineupParseError(
            f"Jogador {provider_player_id} sem nome."
        )

    alt_ids = raw_player.get("altIds") or {}

    if not isinstance(alt_ids, dict):
        alt_ids = {}

    info = raw_player.get("info") or {}

    if not isinstance(info, dict):
        info = {}

    tactical_position = formation_positions.get(
        provider_player_id_int
    )

    formation_row = (
        tactical_position[0]
        if tactical_position
        else None
    )

    formation_slot = (
        tactical_position[1]
        if tactical_position
        else None
    )

    return PremierLeaguePlayer(
        provider_player_id=provider_player_id,
        opta_player_id=_optional_text(
            alt_ids.get("opta")
        ),
        display_name=display_name,
        shirt_number=_optional_integer(
            raw_player.get("matchShirtNumber")
        ),
        match_position=_optional_text(
            raw_player.get("matchPosition")
        ),
        registered_position=_optional_text(
            info.get("position")
        ),
        position_description=_optional_text(
            info.get("positionInfo")
        ),
        is_captain=bool(
            raw_player.get("captain", False)
        ),
        is_starter=is_starter,
        source_order=source_order,
        formation_row=formation_row,
        formation_slot=formation_slot,
    )


def _parse_team_lineup(
    raw_team_list: dict[str, Any],
    *,
    side: str,
    team_name: str,
) -> PremierLeagueTeamLineup:
    provider_team_id = str(
        _integer(
            raw_team_list.get("teamId"),
            "teamLists[].teamId",
        )
    )

    raw_lineup = raw_team_list.get("lineup")
    raw_substitutes = raw_team_list.get(
        "substitutes"
    )

    if not isinstance(raw_lineup, list):
        raise PremierLeagueLineupParseError(
            f"Equipa {provider_team_id} sem lineup."
        )

    if not isinstance(raw_substitutes, list):
        raise PremierLeagueLineupParseError(
            f"Equipa {provider_team_id} sem substitutes."
        )

    formation = raw_team_list.get("formation")

    if not isinstance(formation, dict):
        formation = {}

    formation_positions = _formation_positions(
        formation
    )

    starters = tuple(
        _parse_player(
            player,
            is_starter=True,
            source_order=index,
            formation_positions=formation_positions,
        )
        for index, player in enumerate(
            raw_lineup,
            start=1,
        )
        if isinstance(player, dict)
    )

    substitutes = tuple(
        _parse_player(
            player,
            is_starter=False,
            source_order=index,
            formation_positions={},
        )
        for index, player in enumerate(
            raw_substitutes,
            start=1,
        )
        if isinstance(player, dict)
    )

    if len(starters) != 11:
        raise PremierLeagueLineupParseError(
            f"Equipa {team_name}: esperavam-se "
            f"11 titulares; foram encontrados "
            f"{len(starters)}."
        )

    starter_ids = {
        int(player.provider_player_id)
        for player in starters
    }

    if len(starter_ids) != 11:
        raise PremierLeagueLineupParseError(
            f"Equipa {team_name}: existem titulares duplicados."
        )

    formation_ids = set(
        formation_positions
    )

    if formation_ids and formation_ids != starter_ids:
        missing = sorted(
            starter_ids - formation_ids
        )

        unexpected = sorted(
            formation_ids - starter_ids
        )

        raise PremierLeagueLineupParseError(
            f"Equipa {team_name}: formação não corresponde "
            f"aos titulares. Em falta={missing}; "
            f"inesperados={unexpected}"
        )

    captain_total = sum(
        player.is_captain
        for player in starters
    )

    if captain_total != 1:
        raise PremierLeagueLineupParseError(
            f"Equipa {team_name}: esperava-se exatamente "
            f"um capitão titular; foram encontrados "
            f"{captain_total}."
        )

    goalkeeper_total = sum(
        player.match_position == "G"
        for player in starters
    )

    if goalkeeper_total != 1:
        raise PremierLeagueLineupParseError(
            f"Equipa {team_name}: esperava-se exatamente "
            f"um guarda-redes titular; foram encontrados "
            f"{goalkeeper_total}."
        )

    all_player_ids = [
        player.provider_player_id
        for player in starters + substitutes
    ]

    if len(all_player_ids) != len(
        set(all_player_ids)
    ):
        raise PremierLeagueLineupParseError(
            f"Equipa {team_name}: jogador repetido entre "
            "titulares e suplentes."
        )

    return PremierLeagueTeamLineup(
        provider_team_id=provider_team_id,
        side=side,
        team_name=team_name,
        formation=_optional_text(
            formation.get("label")
        ),
        starters=starters,
        substitutes=substitutes,
    )


def parse_premier_league_lineup(
    payload: dict[str, Any],
) -> PremierLeagueMatchLineup:
    provider_fixture_id = str(
        _integer(
            payload.get("id"),
            "fixture.id",
        )
    )

    participants = payload.get("teams")

    if (
        not isinstance(participants, list)
        or len(participants) != 2
    ):
        raise PremierLeagueLineupParseError(
            "O fixture deveria conter exatamente "
            "duas equipas em teams."
        )

    home_team_id, home_team_name = (
        _extract_team_identity(
            participants[0]
        )
    )

    away_team_id, away_team_name = (
        _extract_team_identity(
            participants[1]
        )
    )

    raw_team_lists = payload.get("teamLists")

    if (
        not isinstance(raw_team_lists, list)
        or len(raw_team_lists) != 2
    ):
        raise PremierLeagueLineupParseError(
            "teamLists deveria conter exatamente "
            "duas equipas."
        )

    team_lists_by_id: dict[str, dict[str, Any]] = {}

    for raw_team_list in raw_team_lists:
        if not isinstance(raw_team_list, dict):
            continue

        team_id = str(
            _integer(
                raw_team_list.get("teamId"),
                "teamLists[].teamId",
            )
        )

        if team_id in team_lists_by_id:
            raise PremierLeagueLineupParseError(
                f"teamId duplicado em teamLists: {team_id}"
            )

        team_lists_by_id[team_id] = raw_team_list

    if set(team_lists_by_id) != {
        home_team_id,
        away_team_id,
    }:
        raise PremierLeagueLineupParseError(
            "Os teamId de teamLists não correspondem "
            "às equipas do fixture."
        )

    home = _parse_team_lineup(
        team_lists_by_id[home_team_id],
        side="HOME",
        team_name=home_team_name,
    )

    away = _parse_team_lineup(
        team_lists_by_id[away_team_id],
        side="AWAY",
        team_name=away_team_name,
    )

    return PremierLeagueMatchLineup(
        provider_fixture_id=provider_fixture_id,
        home=home,
        away=away,
    )
