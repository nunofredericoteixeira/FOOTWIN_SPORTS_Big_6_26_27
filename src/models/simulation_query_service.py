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
class PositionProbability:
    position: int
    probability: float


@dataclass(frozen=True)
class SimulationTeamSummary:
    team_id: str
    team_name: str

    average_position: float
    median_position: float

    average_points: float
    average_goals_for: float
    average_goals_against: float
    average_goal_difference: float

    title_probability: float
    europe_probability: float
    relegation_probability: float
    playoff_probability: float

    points_p10: float
    points_p25: float
    points_p50: float
    points_p75: float
    points_p90: float

    position_probabilities: tuple[
        PositionProbability,
        ...
    ]


@dataclass(frozen=True)
class SimulationSummary:
    simulation_id: str
    league_id: str
    league_name: str
    season_label: str
    model_version: str
    run_id: str | None

    simulation_count: int
    random_seed: int
    status: str

    started_at: str
    finished_at: str | None

    teams: tuple[
        SimulationTeamSummary,
        ...
    ]


class SimulationQueryError(RuntimeError):
    """Erro ao consultar simulações."""


def get_latest_simulation(
    league_id: str,
    season_label: str = "2026/27",
    model_version: str | None = None,
    database_path: str | Path | None = None,
    required_status: str = "SUCCESS",
) -> SimulationSummary:
    """
    Obtém a simulação mais recente de uma liga.
    """

    final_league_id = clean_required_text(
        league_id,
        "league_id",
    ).upper()

    final_season_label = clean_required_text(
        season_label,
        "season_label",
    )

    final_model_version = (
        model_version.strip()
        if model_version
        else get_configured_model_version()
    )

    final_status = clean_required_text(
        required_status,
        "required_status",
    ).upper()

    connection = connect_database(
        database_path
    )

    try:
        row = connection.execute(
            """
            SELECT
                s.simulation_id
            FROM league_simulations s
            WHERE s.league_id = ?
              AND s.season_label = ?
              AND s.model_version = ?
              AND s.status = ?
            ORDER BY
                COALESCE(
                    s.finished_at,
                    s.started_at
                ) DESC,
                s.started_at DESC,
                s.simulation_id DESC
            LIMIT 1
            """,
            (
                final_league_id,
                final_season_label,
                final_model_version,
                final_status,
            ),
        ).fetchone()

        if row is None:
            raise SimulationQueryError(
                "Não foi encontrada nenhuma simulação "
                f"com estado {final_status} para "
                f"{final_league_id}, "
                f"{final_season_label}, "
                f"{final_model_version}."
            )

        return load_simulation_summary(
            connection=connection,
            simulation_id=str(
                row["simulation_id"]
            ),
        )

    finally:
        connection.close()


def get_simulation_by_id(
    simulation_id: str,
    database_path: str | Path | None = None,
) -> SimulationSummary:
    """
    Obtém uma simulação através do identificador.
    """

    final_simulation_id = clean_required_text(
        simulation_id,
        "simulation_id",
    )

    connection = connect_database(
        database_path
    )

    try:
        return load_simulation_summary(
            connection=connection,
            simulation_id=final_simulation_id,
        )

    finally:
        connection.close()


def list_simulations(
    league_id: str | None = None,
    season_label: str | None = None,
    model_version: str | None = None,
    status: str | None = None,
    limit: int = 20,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Lista os cabeçalhos das simulações existentes.
    """

    final_limit = validate_positive_integer(
        limit,
        "limit",
    )

    conditions: list[str] = []
    parameters: list[Any] = []

    if league_id:
        conditions.append(
            "s.league_id = ?"
        )

        parameters.append(
            league_id.strip().upper()
        )

    if season_label:
        conditions.append(
            "s.season_label = ?"
        )

        parameters.append(
            season_label.strip()
        )

    if model_version:
        conditions.append(
            "s.model_version = ?"
        )

        parameters.append(
            model_version.strip()
        )

    if status:
        conditions.append(
            "s.status = ?"
        )

        parameters.append(
            status.strip().upper()
        )

    where_clause = (
        "WHERE " + " AND ".join(conditions)
        if conditions
        else ""
    )

    parameters.append(
        final_limit
    )

    connection = connect_database(
        database_path
    )

    try:
        rows = connection.execute(
            f"""
            SELECT
                s.simulation_id,
                s.league_id,
                l.league_name,
                s.season_label,
                s.model_version,
                s.run_id,
                s.simulation_count,
                s.random_seed,
                s.status,
                s.started_at,
                s.finished_at,
                COUNT(r.team_id)
                    AS stored_team_count
            FROM league_simulations s
            INNER JOIN leagues l
                ON l.league_id = s.league_id
            LEFT JOIN league_simulation_results r
                ON r.simulation_id = s.simulation_id
            {where_clause}
            GROUP BY
                s.simulation_id,
                s.league_id,
                l.league_name,
                s.season_label,
                s.model_version,
                s.run_id,
                s.simulation_count,
                s.random_seed,
                s.status,
                s.started_at,
                s.finished_at
            ORDER BY
                COALESCE(
                    s.finished_at,
                    s.started_at
                ) DESC,
                s.started_at DESC,
                s.simulation_id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def load_simulation_summary(
    connection: sqlite3.Connection,
    simulation_id: str,
) -> SimulationSummary:
    """
    Carrega o cabeçalho, equipas e posições.
    """

    header = connection.execute(
        """
        SELECT
            s.simulation_id,
            s.league_id,
            l.league_name,
            s.season_label,
            s.model_version,
            s.run_id,
            s.simulation_count,
            s.random_seed,
            s.status,
            s.started_at,
            s.finished_at
        FROM league_simulations s
        INNER JOIN leagues l
            ON l.league_id = s.league_id
        WHERE s.simulation_id = ?
        """,
        (
            simulation_id,
        ),
    ).fetchone()

    if header is None:
        raise SimulationQueryError(
            f"A simulação {simulation_id} "
            "não foi encontrada."
        )

    team_rows = connection.execute(
        """
        SELECT
            r.team_id,
            t.team_name,
            r.average_position,
            r.median_position,
            r.average_points,
            r.average_goals_for,
            r.average_goals_against,
            r.average_goal_difference,
            r.title_probability,
            r.europe_probability,
            r.relegation_probability,
            r.playoff_probability,
            r.points_p10,
            r.points_p25,
            r.points_p50,
            r.points_p75,
            r.points_p90
        FROM league_simulation_results r
        INNER JOIN teams t
            ON t.team_id = r.team_id
        WHERE r.simulation_id = ?
        ORDER BY
            r.average_position,
            -r.average_points,
            r.team_id
        """,
        (
            simulation_id,
        ),
    ).fetchall()

    if not team_rows:
        raise SimulationQueryError(
            f"A simulação {simulation_id} "
            "não possui resultados por equipa."
        )

    position_rows = connection.execute(
        """
        SELECT
            team_id,
            position,
            probability
        FROM position_probabilities
        WHERE simulation_id = ?
        ORDER BY
            team_id,
            position
        """,
        (
            simulation_id,
        ),
    ).fetchall()

    probabilities_by_team: dict[
        str,
        list[PositionProbability]
    ] = {}

    for row in position_rows:
        team_id = str(
            row["team_id"]
        )

        probabilities_by_team.setdefault(
            team_id,
            [],
        ).append(
            PositionProbability(
                position=int(
                    row["position"]
                ),
                probability=float(
                    row["probability"]
                ),
            )
        )

    teams: list[
        SimulationTeamSummary
    ] = []

    for row in team_rows:
        team_id = str(
            row["team_id"]
        )

        positions = tuple(
            probabilities_by_team.get(
                team_id,
                [],
            )
        )

        validate_position_probabilities(
            team_id=team_id,
            probabilities=positions,
        )

        teams.append(
            SimulationTeamSummary(
                team_id=team_id,
                team_name=str(
                    row["team_name"]
                ),
                average_position=float(
                    row["average_position"]
                ),
                median_position=float(
                    row["median_position"]
                ),
                average_points=float(
                    row["average_points"]
                ),
                average_goals_for=float(
                    row["average_goals_for"]
                ),
                average_goals_against=float(
                    row["average_goals_against"]
                ),
                average_goal_difference=float(
                    row[
                        "average_goal_difference"
                    ]
                ),
                title_probability=float(
                    row["title_probability"]
                ),
                europe_probability=float(
                    row["europe_probability"]
                ),
                relegation_probability=float(
                    row[
                        "relegation_probability"
                    ]
                ),
                playoff_probability=float(
                    row["playoff_probability"]
                ),
                points_p10=float(
                    row["points_p10"]
                ),
                points_p25=float(
                    row["points_p25"]
                ),
                points_p50=float(
                    row["points_p50"]
                ),
                points_p75=float(
                    row["points_p75"]
                ),
                points_p90=float(
                    row["points_p90"]
                ),
                position_probabilities=positions,
            )
        )

    validate_simulation_summary(
        simulation_id=simulation_id,
        teams=teams,
    )

    return SimulationSummary(
        simulation_id=str(
            header["simulation_id"]
        ),
        league_id=str(
            header["league_id"]
        ),
        league_name=str(
            header["league_name"]
        ),
        season_label=str(
            header["season_label"]
        ),
        model_version=str(
            header["model_version"]
        ),
        run_id=(
            str(header["run_id"])
            if header["run_id"] is not None
            else None
        ),
        simulation_count=int(
            header["simulation_count"]
        ),
        random_seed=int(
            header["random_seed"]
        ),
        status=str(
            header["status"]
        ),
        started_at=str(
            header["started_at"]
        ),
        finished_at=(
            str(header["finished_at"])
            if header["finished_at"]
            is not None
            else None
        ),
        teams=tuple(teams),
    )


def validate_position_probabilities(
    team_id: str,
    probabilities: tuple[
        PositionProbability,
        ...
    ],
) -> None:
    """
    Valida as probabilidades de posição de uma equipa.
    """

    if not probabilities:
        raise SimulationQueryError(
            f"A equipa {team_id} não possui "
            "probabilidades de posição."
        )

    seen_positions: set[int] = set()

    total = 0.0

    for item in probabilities:
        if item.position <= 0:
            raise SimulationQueryError(
                f"A equipa {team_id} possui "
                "uma posição inválida."
            )

        if item.position in seen_positions:
            raise SimulationQueryError(
                f"A equipa {team_id} possui "
                f"a posição {item.position} duplicada."
            )

        if not math.isfinite(
            item.probability
        ):
            raise SimulationQueryError(
                f"A equipa {team_id} possui "
                "uma probabilidade não finita."
            )

        if not (
            0.0
            <= item.probability
            <= 1.0
        ):
            raise SimulationQueryError(
                f"A equipa {team_id} possui "
                "uma probabilidade fora de 0–1."
            )

        seen_positions.add(
            item.position
        )

        total += item.probability

    if not math.isclose(
        total,
        1.0,
        abs_tol=0.000001,
    ):
        raise SimulationQueryError(
            f"As probabilidades da equipa "
            f"{team_id} totalizam {total:.8f}, "
            "em vez de 1."
        )


def validate_simulation_summary(
    simulation_id: str,
    teams: list[
        SimulationTeamSummary
    ],
) -> None:
    """
    Valida os totais globais da simulação.
    """

    team_count = len(
        teams
    )

    if team_count < 2:
        raise SimulationQueryError(
            f"A simulação {simulation_id} "
            "possui menos de duas equipas."
        )

    title_total = sum(
        team.title_probability
        for team in teams
    )

    if not math.isclose(
        title_total,
        1.0,
        abs_tol=0.000001,
    ):
        raise SimulationQueryError(
            "As probabilidades de título "
            f"totalizam {title_total:.8f}, "
            "em vez de 1."
        )

    for expected_position in range(
        1,
        team_count + 1,
    ):
        position_total = sum(
            next(
                (
                    item.probability
                    for item
                    in team.position_probabilities
                    if item.position
                    == expected_position
                ),
                0.0,
            )
            for team in teams
        )

        if not math.isclose(
            position_total,
            1.0,
            abs_tol=0.000001,
        ):
            raise SimulationQueryError(
                f"As probabilidades globais da "
                f"posição {expected_position} "
                f"totalizam {position_total:.8f}, "
                "em vez de 1."
            )


def get_position_probability(
    team: SimulationTeamSummary,
    position: int,
) -> float:
    """
    Obtém a probabilidade de uma equipa terminar
    numa determinada posição.
    """

    final_position = validate_positive_integer(
        position,
        "position",
    )

    for item in team.position_probabilities:
        if item.position == final_position:
            return item.probability

    return 0.0


def validate_positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(
        value,
        bool,
    ):
        raise SimulationQueryError(
            f"{field_name} deve ser inteiro."
        )

    try:
        numeric = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise SimulationQueryError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(
        numeric
    ):
        raise SimulationQueryError(
            f"{field_name} não é finito."
        )

    if not numeric.is_integer():
        raise SimulationQueryError(
            f"{field_name} deve ser inteiro."
        )

    integer_value = int(
        numeric
    )

    if integer_value <= 0:
        raise SimulationQueryError(
            f"{field_name} deve ser "
            "superior a zero."
        )

    return integer_value


def clean_required_text(
    value: Any,
    field_name: str,
) -> str:
    if value is None:
        raise SimulationQueryError(
            f"{field_name} vazio."
        )

    cleaned = str(
        value
    ).strip()

    if not cleaned:
        raise SimulationQueryError(
            f"{field_name} vazio."
        )

    return cleaned


def get_configured_model_version() -> str:
    """
    Obtém a versão ativa do modelo.
    """

    config = load_full_model_config()

    try:
        return str(
            config["version"][
                "model_version"
            ]
        )

    except KeyError as exc:
        raise SimulationQueryError(
            "Não foi possível obter "
            "version.model_version."
        ) from exc
