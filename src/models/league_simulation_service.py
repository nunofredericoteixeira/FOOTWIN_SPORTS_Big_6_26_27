# -*- coding: utf-8 -*-

from __future__ import annotations

import math
import random
import sqlite3
import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.config.model_config import load_full_model_config
from src.database.init_database import connect_database
from src.utils.logger import get_logger


logger = get_logger(
    "models.league_simulation_service"
)


DEFAULT_SIMULATION_COUNT = 10_000
DEFAULT_RANDOM_SEED = 202627
DEFAULT_EUROPE_PLACES = 4
DEFAULT_RELEGATION_PLACES = 3
DEFAULT_PLAYOFF_PLACES = 1

MIN_SIMULATION_COUNT = 1
MAX_SIMULATION_COUNT = 1_000_000

MIN_LAMBDA = 0.01
MAX_LAMBDA = 10.0


@dataclass(frozen=True)
class SimulationMatch:
    match_id: str
    league_id: str
    season_label: str
    home_team_id: str
    away_team_id: str
    lambda_home: float
    lambda_away: float


@dataclass
class TeamSimulationState:
    team_id: str
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def goal_difference(self) -> int:
        return (
            self.goals_for
            - self.goals_against
        )


@dataclass
class TeamSimulationAccumulator:
    team_id: str

    positions: list[int] = field(
        default_factory=list
    )

    points: list[int] = field(
        default_factory=list
    )

    goals_for: list[int] = field(
        default_factory=list
    )

    goals_against: list[int] = field(
        default_factory=list
    )

    goal_differences: list[int] = field(
        default_factory=list
    )

    title_count: int = 0
    europe_count: int = 0
    relegation_count: int = 0
    playoff_count: int = 0


@dataclass(frozen=True)
class TeamSimulationResult:
    team_id: str

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
        tuple[int, float],
        ...
    ]


@dataclass(frozen=True)
class LeagueSimulationResult:
    simulation_id: str
    league_id: str
    season_label: str
    model_version: str
    run_id: str | None
    simulation_count: int
    random_seed: int
    team_results: tuple[
        TeamSimulationResult,
        ...
    ]


class LeagueSimulationError(RuntimeError):
    """Erro durante a simulação Monte Carlo."""


def run_league_simulation(
    league_id: str,
    season_label: str = "2026/27",
    model_version: str | None = None,
    simulation_count: int = (
        DEFAULT_SIMULATION_COUNT
    ),
    random_seed: int = (
        DEFAULT_RANDOM_SEED
    ),
    europe_places: int = (
        DEFAULT_EUROPE_PLACES
    ),
    relegation_places: int = (
        DEFAULT_RELEGATION_PLACES
    ),
    playoff_places: int = (
        DEFAULT_PLAYOFF_PLACES
    ),
    run_id: str | None = None,
    database_path: str | Path | None = None,
    store_results: bool = True,
) -> LeagueSimulationResult:
    """
    Executa uma simulação Monte Carlo completa da liga.

    Cada jogo é sorteado com duas distribuições de Poisson:

        golos da casa ~ Poisson(lambda_home)
        golos fora    ~ Poisson(lambda_away)

    A classificação usa:

        1. Pontos
        2. Diferença de golos
        3. Golos marcados
        4. team_id
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

    final_simulation_count = (
        validate_simulation_count(
            simulation_count
        )
    )

    final_random_seed = validate_integer(
        random_seed,
        "random_seed",
    )

    final_europe_places = (
        validate_non_negative_integer(
            europe_places,
            "europe_places",
        )
    )

    final_relegation_places = (
        validate_non_negative_integer(
            relegation_places,
            "relegation_places",
        )
    )

    final_playoff_places = (
        validate_non_negative_integer(
            playoff_places,
            "playoff_places",
        )
    )

    connection = connect_database(
        database_path
    )

    simulation_id = build_simulation_id(
        league_id=final_league_id,
        season_label=final_season_label,
        model_version=final_model_version,
    )

    started_at = utc_now_iso()

    try:
        league_exists = connection.execute(
            """
            SELECT league_id
            FROM leagues
            WHERE league_id = ?
              AND active = 1
            """,
            (
                final_league_id,
            ),
        ).fetchone()

        if league_exists is None:
            raise LeagueSimulationError(
                f"A liga {final_league_id} "
                "não existe ou está inativa."
            )

        matches = load_simulation_matches(
            connection=connection,
            league_id=final_league_id,
            season_label=final_season_label,
            model_version=(
                final_model_version
            ),
        )

        if not matches:
            raise LeagueSimulationError(
                "Não existem jogos com previsões "
                f"para a liga {final_league_id}, "
                f"época {final_season_label} e "
                f"modelo {final_model_version}."
            )

        team_ids = collect_team_ids(
            matches
        )

        validate_position_rules(
            team_count=len(team_ids),
            europe_places=(
                final_europe_places
            ),
            relegation_places=(
                final_relegation_places
            ),
            playoff_places=(
                final_playoff_places
            ),
        )

        if store_results:
            insert_simulation_header(
                connection=connection,
                simulation_id=simulation_id,
                league_id=final_league_id,
                season_label=(
                    final_season_label
                ),
                model_version=(
                    final_model_version
                ),
                run_id=run_id,
                simulation_count=(
                    final_simulation_count
                ),
                random_seed=(
                    final_random_seed
                ),
                status="RUNNING",
                started_at=started_at,
            )

            connection.commit()

        result = simulate_league(
            simulation_id=simulation_id,
            league_id=final_league_id,
            season_label=(
                final_season_label
            ),
            model_version=(
                final_model_version
            ),
            run_id=run_id,
            matches=matches,
            simulation_count=(
                final_simulation_count
            ),
            random_seed=(
                final_random_seed
            ),
            europe_places=(
                final_europe_places
            ),
            relegation_places=(
                final_relegation_places
            ),
            playoff_places=(
                final_playoff_places
            ),
        )

        if store_results:
            try:
                connection.execute(
                    "BEGIN IMMEDIATE"
                )

                store_simulation_results(
                    connection=connection,
                    result=result,
                )

                connection.execute(
                    """
                    UPDATE league_simulations
                    SET
                        status = ?,
                        finished_at = ?
                    WHERE simulation_id = ?
                    """,
                    (
                        "SUCCESS",
                        utc_now_iso(),
                        simulation_id,
                    ),
                )

                validate_stored_simulation(
                    connection=connection,
                    result=result,
                )

                connection.commit()

            except Exception:
                connection.rollback()

                try:
                    connection.execute(
                        """
                        UPDATE league_simulations
                        SET
                            status = ?,
                            finished_at = ?
                        WHERE simulation_id = ?
                        """,
                        (
                            "FAILED",
                            utc_now_iso(),
                            simulation_id,
                        ),
                    )

                    connection.commit()

                except Exception:
                    connection.rollback()

                raise

    except Exception:
        logger.exception(
            "Erro na simulação da liga | "
            "liga=%s | época=%s | modelo=%s",
            final_league_id,
            final_season_label,
            final_model_version,
        )

        raise

    finally:
        connection.close()

    logger.info(
        "Simulação concluída | "
        "simulation_id=%s | liga=%s | "
        "simulações=%s | equipas=%s",
        result.simulation_id,
        result.league_id,
        result.simulation_count,
        len(result.team_results),
    )

    return result


def simulate_league(
    simulation_id: str,
    league_id: str,
    season_label: str,
    model_version: str,
    run_id: str | None,
    matches: list[SimulationMatch],
    simulation_count: int,
    random_seed: int,
    europe_places: int,
    relegation_places: int,
    playoff_places: int,
) -> LeagueSimulationResult:
    """
    Executa as simulações em memória.
    """

    random_generator = random.Random(
        random_seed
    )

    team_ids = collect_team_ids(
        matches
    )

    accumulators = {
        team_id: TeamSimulationAccumulator(
            team_id=team_id
        )
        for team_id in team_ids
    }

    team_count = len(team_ids)

    for _ in range(simulation_count):
        states = {
            team_id: TeamSimulationState(
                team_id=team_id
            )
            for team_id in team_ids
        }

        for match in matches:
            home_goals = sample_poisson(
                lambda_value=(
                    match.lambda_home
                ),
                random_generator=(
                    random_generator
                ),
            )

            away_goals = sample_poisson(
                lambda_value=(
                    match.lambda_away
                ),
                random_generator=(
                    random_generator
                ),
            )

            apply_match_result(
                home_state=states[
                    match.home_team_id
                ],
                away_state=states[
                    match.away_team_id
                ],
                home_goals=home_goals,
                away_goals=away_goals,
            )

        standings = rank_team_states(
            states.values()
        )

        for position, state in enumerate(
            standings,
            start=1,
        ):
            accumulator = accumulators[
                state.team_id
            ]

            accumulator.positions.append(
                position
            )

            accumulator.points.append(
                state.points
            )

            accumulator.goals_for.append(
                state.goals_for
            )

            accumulator.goals_against.append(
                state.goals_against
            )

            accumulator.goal_differences.append(
                state.goal_difference
            )

            if position == 1:
                accumulator.title_count += 1

            if (
                europe_places > 0
                and position <= europe_places
            ):
                accumulator.europe_count += 1

            if (
                relegation_places > 0
                and position
                > team_count
                - relegation_places
            ):
                accumulator.relegation_count += 1

            if (
                playoff_places > 0
                and is_playoff_position(
                    position=position,
                    team_count=team_count,
                    relegation_places=(
                        relegation_places
                    ),
                    playoff_places=(
                        playoff_places
                    ),
                )
            ):
                accumulator.playoff_count += 1

    team_results = tuple(
        sorted(
            (
                build_team_simulation_result(
                    accumulator=accumulator,
                    simulation_count=(
                        simulation_count
                    ),
                    team_count=team_count,
                )
                for accumulator
                in accumulators.values()
            ),
            key=lambda item: (
                item.average_position,
                -item.average_points,
                item.team_id,
            ),
        )
    )

    return LeagueSimulationResult(
        simulation_id=simulation_id,
        league_id=league_id,
        season_label=season_label,
        model_version=model_version,
        run_id=run_id,
        simulation_count=(
            simulation_count
        ),
        random_seed=random_seed,
        team_results=team_results,
    )


def load_simulation_matches(
    connection: sqlite3.Connection,
    league_id: str,
    season_label: str,
    model_version: str,
) -> list[SimulationMatch]:
    """
    Carrega os jogos e os respetivos lambdas.
    """

    rows = connection.execute(
        """
        SELECT
            m.match_id,
            m.league_id,
            m.season_label,
            m.home_team_id,
            m.away_team_id,
            p.lambda_home,
            p.lambda_away
        FROM matches m
        INNER JOIN match_predictions p
            ON p.match_id = m.match_id
        WHERE m.league_id = ?
          AND m.season_label = ?
          AND p.model_version = ?
          AND m.status IN (
              'SCHEDULED',
              'POSTPONED'
          )
        ORDER BY
            m.round_number,
            m.match_date,
            m.match_id
        """,
        (
            league_id,
            season_label,
            model_version,
        ),
    ).fetchall()

    matches: list[
        SimulationMatch
    ] = []

    for row in rows:
        lambda_home = validate_lambda(
            row["lambda_home"],
            "lambda_home",
        )

        lambda_away = validate_lambda(
            row["lambda_away"],
            "lambda_away",
        )

        home_team_id = clean_required_text(
            row["home_team_id"],
            "home_team_id",
        )

        away_team_id = clean_required_text(
            row["away_team_id"],
            "away_team_id",
        )

        if home_team_id == away_team_id:
            raise LeagueSimulationError(
                f"Jogo inválido "
                f"{row['match_id']}: "
                "a equipa joga contra si própria."
            )

        matches.append(
            SimulationMatch(
                match_id=str(
                    row["match_id"]
                ),
                league_id=str(
                    row["league_id"]
                ),
                season_label=str(
                    row["season_label"]
                ),
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                lambda_home=lambda_home,
                lambda_away=lambda_away,
            )
        )

    return matches


def collect_team_ids(
    matches: Iterable[
        SimulationMatch
    ],
) -> list[str]:
    """
    Obtém todas as equipas presentes nos jogos.
    """

    team_ids: set[str] = set()

    for match in matches:
        team_ids.add(
            match.home_team_id
        )

        team_ids.add(
            match.away_team_id
        )

    if len(team_ids) < 2:
        raise LeagueSimulationError(
            "São necessárias pelo menos "
            "duas equipas para simular."
        )

    return sorted(
        team_ids
    )


def apply_match_result(
    home_state: TeamSimulationState,
    away_state: TeamSimulationState,
    home_goals: int,
    away_goals: int,
) -> None:
    """
    Aplica o resultado às duas equipas.
    """

    final_home_goals = (
        validate_non_negative_integer(
            home_goals,
            "home_goals",
        )
    )

    final_away_goals = (
        validate_non_negative_integer(
            away_goals,
            "away_goals",
        )
    )

    home_state.goals_for += (
        final_home_goals
    )

    home_state.goals_against += (
        final_away_goals
    )

    away_state.goals_for += (
        final_away_goals
    )

    away_state.goals_against += (
        final_home_goals
    )

    if final_home_goals > final_away_goals:
        home_state.points += 3

    elif final_home_goals < final_away_goals:
        away_state.points += 3

    else:
        home_state.points += 1
        away_state.points += 1


def rank_team_states(
    states: Iterable[
        TeamSimulationState
    ],
) -> list[TeamSimulationState]:
    """
    Ordena a classificação simulada.
    """

    return sorted(
        states,
        key=lambda state: (
            -state.points,
            -state.goal_difference,
            -state.goals_for,
            state.team_id,
        ),
    )


def sample_poisson(
    lambda_value: float,
    random_generator: random.Random,
) -> int:
    """
    Sorteia um valor segundo Poisson.

    Usa o algoritmo de Knuth, adequado aos lambdas
    de futebol normalmente inferiores a 5.
    """

    final_lambda = validate_lambda(
        lambda_value,
        "lambda_value",
    )

    limit = math.exp(
        -final_lambda
    )

    product = 1.0
    count = 0

    while product > limit:
        count += 1
        product *= (
            random_generator.random()
        )

    return count - 1


def build_team_simulation_result(
    accumulator: TeamSimulationAccumulator,
    simulation_count: int,
    team_count: int,
) -> TeamSimulationResult:
    """
    Converte os dados acumulados num resultado final.
    """

    if (
        len(accumulator.positions)
        != simulation_count
    ):
        raise LeagueSimulationError(
            f"A equipa {accumulator.team_id} "
            "não possui todas as posições simuladas."
        )

    position_counts: dict[
        int,
        int
    ] = defaultdict(int)

    for position in accumulator.positions:
        position_counts[
            position
        ] += 1

    position_probabilities = tuple(
        (
            position,
            round(
                position_counts.get(
                    position,
                    0,
                )
                / simulation_count,
                12,
            ),
        )
        for position in range(
            1,
            team_count + 1,
        )
    )

    return TeamSimulationResult(
        team_id=accumulator.team_id,

        average_position=round(
            statistics.fmean(
                accumulator.positions
            ),
            6,
        ),

        median_position=round(
            float(
                statistics.median(
                    accumulator.positions
                )
            ),
            6,
        ),

        average_points=round(
            statistics.fmean(
                accumulator.points
            ),
            6,
        ),

        average_goals_for=round(
            statistics.fmean(
                accumulator.goals_for
            ),
            6,
        ),

        average_goals_against=round(
            statistics.fmean(
                accumulator.goals_against
            ),
            6,
        ),

        average_goal_difference=round(
            statistics.fmean(
                accumulator.goal_differences
            ),
            6,
        ),

        title_probability=round(
            accumulator.title_count
            / simulation_count,
            12,
        ),

        europe_probability=round(
            accumulator.europe_count
            / simulation_count,
            12,
        ),

        relegation_probability=round(
            accumulator.relegation_count
            / simulation_count,
            12,
        ),

        playoff_probability=round(
            accumulator.playoff_count
            / simulation_count,
            12,
        ),

        points_p10=round(
            percentile(
                accumulator.points,
                10,
            ),
            6,
        ),

        points_p25=round(
            percentile(
                accumulator.points,
                25,
            ),
            6,
        ),

        points_p50=round(
            percentile(
                accumulator.points,
                50,
            ),
            6,
        ),

        points_p75=round(
            percentile(
                accumulator.points,
                75,
            ),
            6,
        ),

        points_p90=round(
            percentile(
                accumulator.points,
                90,
            ),
            6,
        ),

        position_probabilities=(
            position_probabilities
        ),
    )


def store_simulation_results(
    connection: sqlite3.Connection,
    result: LeagueSimulationResult,
) -> None:
    """
    Grava os resultados agregados e as posições.
    """

    for team_result in result.team_results:
        connection.execute(
            """
            INSERT INTO league_simulation_results (
                simulation_id,
                team_id,
                average_position,
                median_position,
                average_points,
                average_goals_for,
                average_goals_against,
                average_goal_difference,
                title_probability,
                europe_probability,
                relegation_probability,
                playoff_probability,
                points_p10,
                points_p25,
                points_p50,
                points_p75,
                points_p90
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
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                result.simulation_id,
                team_result.team_id,
                team_result.average_position,
                team_result.median_position,
                team_result.average_points,
                team_result.average_goals_for,
                team_result.average_goals_against,
                team_result.average_goal_difference,
                team_result.title_probability,
                team_result.europe_probability,
                team_result.relegation_probability,
                team_result.playoff_probability,
                team_result.points_p10,
                team_result.points_p25,
                team_result.points_p50,
                team_result.points_p75,
                team_result.points_p90,
            ),
        )

        for (
            position,
            probability,
        ) in (
            team_result
            .position_probabilities
        ):
            connection.execute(
                """
                INSERT INTO position_probabilities (
                    simulation_id,
                    team_id,
                    position,
                    probability
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    result.simulation_id,
                    team_result.team_id,
                    position,
                    probability,
                ),
            )


def insert_simulation_header(
    connection: sqlite3.Connection,
    simulation_id: str,
    league_id: str,
    season_label: str,
    model_version: str,
    run_id: str | None,
    simulation_count: int,
    random_seed: int,
    status: str,
    started_at: str,
) -> None:
    """
    Cria o cabeçalho da simulação.
    """

    connection.execute(
        """
        INSERT INTO league_simulations (
            simulation_id,
            league_id,
            season_label,
            model_version,
            run_id,
            simulation_count,
            random_seed,
            status,
            started_at,
            finished_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            simulation_id,
            league_id,
            season_label,
            model_version,
            run_id,
            simulation_count,
            random_seed,
            status,
            started_at,
        ),
    )


def validate_stored_simulation(
    connection: sqlite3.Connection,
    result: LeagueSimulationResult,
) -> None:
    """
    Confirma que todos os resultados foram gravados.
    """

    stored_team_count = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM league_simulation_results
        WHERE simulation_id = ?
        """,
        (
            result.simulation_id,
        ),
    ).fetchone()["total"]

    expected_team_count = len(
        result.team_results
    )

    if int(stored_team_count) != (
        expected_team_count
    ):
        raise LeagueSimulationError(
            "Número incorreto de resultados "
            "de equipas gravados. "
            f"Esperado={expected_team_count}; "
            f"encontrado={stored_team_count}"
        )

    expected_position_count = (
        expected_team_count
        * expected_team_count
    )

    stored_position_count = (
        connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM position_probabilities
            WHERE simulation_id = ?
            """,
            (
                result.simulation_id,
            ),
        ).fetchone()["total"]
    )

    if int(stored_position_count) != (
        expected_position_count
    ):
        raise LeagueSimulationError(
            "Número incorreto de probabilidades "
            "de posição gravadas. "
            f"Esperado="
            f"{expected_position_count}; "
            f"encontrado="
            f"{stored_position_count}"
        )

    invalid_probabilities = (
        connection.execute(
            """
            SELECT
                team_id,
                SUM(probability) AS total
            FROM position_probabilities
            WHERE simulation_id = ?
            GROUP BY team_id
            HAVING ABS(
                SUM(probability) - 1.0
            ) > 0.000001
            """,
            (
                result.simulation_id,
            ),
        ).fetchall()
    )

    if invalid_probabilities:
        invalid_teams = ", ".join(
            str(row["team_id"])
            for row
            in invalid_probabilities
        )

        raise LeagueSimulationError(
            "As probabilidades de posição "
            "não totalizam 1 para: "
            f"{invalid_teams}"
        )


def is_playoff_position(
    position: int,
    team_count: int,
    relegation_places: int,
    playoff_places: int,
) -> bool:
    """
    Determina se a posição pertence ao playoff.

    Os lugares de playoff ficam imediatamente acima
    dos lugares de descida direta.
    """

    if playoff_places <= 0:
        return False

    final_direct_relegation_places = max(
        0,
        relegation_places,
    )

    playoff_end = (
        team_count
        - final_direct_relegation_places
    )

    playoff_start = (
        playoff_end
        - playoff_places
        + 1
    )

    return (
        playoff_start
        <= position
        <= playoff_end
    )


def validate_position_rules(
    team_count: int,
    europe_places: int,
    relegation_places: int,
    playoff_places: int,
) -> None:
    """
    Valida as zonas competitivas.
    """

    if europe_places > team_count:
        raise LeagueSimulationError(
            "europe_places não pode ser superior "
            "ao número de equipas."
        )

    if relegation_places > team_count:
        raise LeagueSimulationError(
            "relegation_places não pode ser superior "
            "ao número de equipas."
        )

    if playoff_places > team_count:
        raise LeagueSimulationError(
            "playoff_places não pode ser superior "
            "ao número de equipas."
        )

    if (
        relegation_places
        + playoff_places
        > team_count
    ):
        raise LeagueSimulationError(
            "A soma dos lugares de descida e playoff "
            "não pode ser superior ao número de equipas."
        )


def percentile(
    values: Iterable[int | float],
    percentile_value: float,
) -> float:
    """
    Calcula percentil com interpolação linear.
    """

    sorted_values = sorted(
        float(value)
        for value in values
    )

    if not sorted_values:
        raise LeagueSimulationError(
            "Não existem valores para calcular "
            "o percentil."
        )

    if not (
        0.0
        <= percentile_value
        <= 100.0
    ):
        raise LeagueSimulationError(
            "O percentil deve estar entre 0 e 100."
        )

    if len(sorted_values) == 1:
        return sorted_values[0]

    index = (
        len(sorted_values) - 1
    ) * (
        percentile_value / 100.0
    )

    lower_index = math.floor(
        index
    )

    upper_index = math.ceil(
        index
    )

    if lower_index == upper_index:
        return sorted_values[
            lower_index
        ]

    lower_value = sorted_values[
        lower_index
    ]

    upper_value = sorted_values[
        upper_index
    ]

    fraction = (
        index
        - lower_index
    )

    return (
        lower_value
        + (
            upper_value
            - lower_value
        )
        * fraction
    )


def build_simulation_id(
    league_id: str,
    season_label: str,
    model_version: str,
) -> str:
    """
    Cria um identificador único para a simulação.
    """

    normalized_season = (
        season_label
        .replace("/", "_")
        .replace(" ", "_")
    )

    unique_part = (
        uuid.uuid4().hex[:12].upper()
    )

    return (
        f"SIM_{league_id}_"
        f"{normalized_season}_"
        f"{model_version}_"
        f"{unique_part}"
    )


def utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


def validate_simulation_count(
    value: Any,
) -> int:
    final_value = validate_integer(
        value,
        "simulation_count",
    )

    if not (
        MIN_SIMULATION_COUNT
        <= final_value
        <= MAX_SIMULATION_COUNT
    ):
        raise LeagueSimulationError(
            "simulation_count deve estar entre "
            f"{MIN_SIMULATION_COUNT} e "
            f"{MAX_SIMULATION_COUNT}."
        )

    return final_value


def validate_lambda(
    value: Any,
    field_name: str,
) -> float:
    try:
        parsed = float(value)

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise LeagueSimulationError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(
        parsed
    ):
        raise LeagueSimulationError(
            f"{field_name} não é finito."
        )

    if not (
        MIN_LAMBDA
        <= parsed
        <= MAX_LAMBDA
    ):
        raise LeagueSimulationError(
            f"{field_name} deve estar entre "
            f"{MIN_LAMBDA} e "
            f"{MAX_LAMBDA}."
        )

    return parsed


def validate_integer(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(
        value,
        bool,
    ):
        raise LeagueSimulationError(
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
        raise LeagueSimulationError(
            f"{field_name} inválido."
        ) from exc

    if not math.isfinite(
        numeric
    ):
        raise LeagueSimulationError(
            f"{field_name} não é finito."
        )

    if not numeric.is_integer():
        raise LeagueSimulationError(
            f"{field_name} deve ser inteiro."
        )

    return int(
        numeric
    )


def validate_non_negative_integer(
    value: Any,
    field_name: str,
) -> int:
    final_value = validate_integer(
        value,
        field_name,
    )

    if final_value < 0:
        raise LeagueSimulationError(
            f"{field_name} não pode ser negativo."
        )

    return final_value


def clean_required_text(
    value: Any,
    field_name: str,
) -> str:
    if value is None:
        raise LeagueSimulationError(
            f"{field_name} vazio."
        )

    cleaned = str(
        value
    ).strip()

    if not cleaned:
        raise LeagueSimulationError(
            f"{field_name} vazio."
        )

    return cleaned


def get_configured_model_version() -> str:
    """
    Obtém a versão configurada do modelo.
    """

    config = load_full_model_config()

    try:
        return str(
            config["version"][
                "model_version"
            ]
        )

    except KeyError as exc:
        raise LeagueSimulationError(
            "Não foi possível obter "
            "version.model_version."
        ) from exc
