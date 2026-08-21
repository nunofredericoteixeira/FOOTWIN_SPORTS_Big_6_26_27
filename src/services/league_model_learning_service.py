from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from src.database.init_database import connect_database
from src.models.match_prediction_service import predict_match
from src.models.prediction_storage_service import predict_and_store_matches
from src.services.prediction_evaluation_service import (
    calculate_brier_score,
    calculate_log_loss,
    determine_predicted_outcome,
    determine_prudent_prediction,
)


STAGE_PRIORITY = {
    "CONFIRMED_LINEUP": 1,
    "MANUAL_OVERRIDE": 2,
    "PRE_MATCH": 3,
}


@dataclass(frozen=True)
class LearningMatch:
    match_id: str
    league_id: str
    season_label: str
    round_number: int | None
    match_date: str
    home_team_id: str
    away_team_id: str
    actual_home_goals: int
    actual_away_goals: int
    actual_outcome: str
    prediction_id: str
    prediction_stage: str
    model_version: str


@dataclass(frozen=True)
class LeagueLearningState:
    league_id: str
    season_label: str
    active_model_version: str
    evaluated_matches: tuple[LearningMatch, ...]


class LeagueModelLearningError(RuntimeError):
    pass


def get_active_league_model(
    connection: sqlite3.Connection,
    *,
    league_id: str,
    season_label: str,
) -> str:
    row = connection.execute(
        """
        SELECT model_version
        FROM model_versions
        WHERE league_id = ?
          AND season_label = ?
          AND version_status = 'ACTIVE'
        ORDER BY
            COALESCE(activated_at, created_at) DESC,
            created_at DESC
        LIMIT 1
        """,
        (
            league_id.strip().upper(),
            season_label,
        ),
    ).fetchone()

    if row is None:
        raise LeagueModelLearningError(
            f"Não existe modelo ACTIVE para {league_id} / {season_label}."
        )

    return str(row["model_version"])


def load_learning_matches(
    connection: sqlite3.Connection,
    *,
    league_id: str,
    season_label: str,
) -> tuple[LearningMatch, ...]:
    rows = connection.execute(
        """
        WITH ranked AS (
            SELECT
                pe.prediction_id,
                pe.match_id,
                pe.model_version,
                pe.prediction_stage,
                pe.actual_home_goals,
                pe.actual_away_goals,
                pe.actual_outcome,
                m.league_id,
                m.season_label,
                m.round_number,
                m.match_date,
                m.home_team_id,
                m.away_team_id,
                ROW_NUMBER() OVER (
                    PARTITION BY pe.match_id
                    ORDER BY
                        CASE pe.prediction_stage
                            WHEN 'CONFIRMED_LINEUP' THEN 1
                            WHEN 'MANUAL_OVERRIDE' THEN 2
                            WHEN 'PRE_MATCH' THEN 3
                            ELSE 9
                        END,
                        pe.evaluated_at DESC,
                        pe.evaluation_id DESC
                ) AS rn
            FROM prediction_evaluations pe
            JOIN matches m
              ON m.match_id = pe.match_id
            WHERE m.league_id = ?
              AND m.season_label = ?
        )
        SELECT *
        FROM ranked
        WHERE rn = 1
        ORDER BY
            match_date,
            match_id
        """,
        (
            league_id.strip().upper(),
            season_label,
        ),
    ).fetchall()

    return tuple(
        LearningMatch(
            match_id=str(row["match_id"]),
            league_id=str(row["league_id"]),
            season_label=str(row["season_label"]),
            round_number=(
                int(row["round_number"])
                if row["round_number"] is not None
                else None
            ),
            match_date=str(row["match_date"]),
            home_team_id=str(row["home_team_id"]),
            away_team_id=str(row["away_team_id"]),
            actual_home_goals=int(row["actual_home_goals"]),
            actual_away_goals=int(row["actual_away_goals"]),
            actual_outcome=str(row["actual_outcome"]),
            prediction_id=str(row["prediction_id"]),
            prediction_stage=str(row["prediction_stage"]),
            model_version=str(row["model_version"]),
        )
        for row in rows
    )


def load_league_learning_state(
    *,
    league_id: str,
    season_label: str = "2026/27",
    database_path: str | Path | None = None,
) -> LeagueLearningState:
    final_league_id = league_id.strip().upper()

    connection = connect_database(database_path)

    try:
        active_model_version = get_active_league_model(
            connection,
            league_id=final_league_id,
            season_label=season_label,
        )

        evaluated_matches = load_learning_matches(
            connection,
            league_id=final_league_id,
            season_label=season_label,
        )

        return LeagueLearningState(
            league_id=final_league_id,
            season_label=season_label,
            active_model_version=active_model_version,
            evaluated_matches=evaluated_matches,
        )

    finally:
        connection.close()


def get_last_analyzed_sample_size(
    connection: sqlite3.Connection,
    *,
    league_id: str,
) -> int:
    row = connection.execute(
        """
        SELECT MAX(sample_size) AS sample_size
        FROM model_candidates
        WHERE league_id = ?
          AND evaluation_scope = 'LEAGUE'
        """,
        (league_id.strip().upper(),),
    ).fetchone()

    if row is None or row["sample_size"] is None:
        return 0

    return int(row["sample_size"])


def learning_is_due(
    connection: sqlite3.Connection,
    *,
    league_id: str,
    current_sample_size: int,
) -> tuple[bool, int]:
    last_analyzed = get_last_analyzed_sample_size(
        connection,
        league_id=league_id,
    )

    return (
        current_sample_size > last_analyzed,
        last_analyzed,
    )


def print_learning_due_state(
    *,
    database_path: str | Path,
    season_label: str = "2026/27",
) -> None:
    connection = connect_database(database_path)

    try:
        print("\n=== APRENDIZAGEM AUTOMÁTICA — ESTADO ===")

        for league_id in (
            "POR1",
            "ESP1",
            "ENG1",
            "FRA1",
            "ITA1",
            "GER1",
        ):
            matches = load_learning_matches(
                connection,
                league_id=league_id,
                season_label=season_label,
            )

            due, last_analyzed = learning_is_due(
                connection,
                league_id=league_id,
                current_sample_size=len(matches),
            )

            print(
                league_id,
                "| jogos atuais =",
                len(matches),
                "| última amostra analisada =",
                last_analyzed,
                "| RECALIBRAR =",
                "SIM" if due else "NAO",
            )

    finally:
        connection.close()



def create_learning_database_copy(
    *,
    source_database_path: str | Path,
    league_id: str,
) -> Path:
    source = Path(source_database_path)

    if not source.exists():
        raise LeagueModelLearningError(
            f"Base de dados não encontrada: {source}"
        )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix=f"footwin_learning_{league_id.lower()}_"
        )
    )

    target = temp_dir / "footwin_sports.db"

    shutil.copy2(
        source,
        target,
    )

    connection = connect_database(target)

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        connection.execute(
            """
            UPDATE matches
            SET
                status = 'SCHEDULED',
                home_goals = NULL,
                away_goals = NULL
            WHERE league_id = ?
              AND status IN ('PLAYED', 'AWARDED')
            """,
            (
                league_id.strip().upper(),
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return target


def validate_learning_database_copy(
    *,
    database_path: str | Path,
    league_id: str,
) -> None:
    connection = connect_database(
        database_path
    )

    try:
        remaining = connection.execute(
            """
            SELECT COUNT(*)
            FROM matches
            WHERE league_id = ?
              AND status IN ('PLAYED', 'AWARDED')
            """,
            (
                league_id.strip().upper(),
            ),
        ).fetchone()[0]

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        foreign_keys = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        print(
            "TEMP DB =",
            database_path,
        )
        print(
            "PLAYED/AWARDED restantes =",
            remaining,
        )
        print(
            "INTEGRITY =",
            integrity,
        )
        print(
            "FOREIGN_KEYS =",
            foreign_keys,
        )

        if remaining != 0:
            raise LeagueModelLearningError(
                "A cópia histórica ainda contém "
                "resultados visíveis da liga."
            )

        if integrity != "ok":
            raise LeagueModelLearningError(
                f"Integrity check falhou: {integrity}"
            )

        if foreign_keys:
            raise LeagueModelLearningError(
                "Foreign key check falhou."
            )

    finally:
        connection.close()


@dataclass(frozen=True)
class BacktestScore:
    predicted_outcome: str
    prudent_prediction: str
    outcome_hit: int
    prudent_hit: int
    brier_score: float
    log_loss: float
    signals: int


def get_top_score_text(
    prediction: Any,
) -> str | None:
    scores = getattr(
        prediction,
        "most_likely_scores",
        None,
    )

    if not scores:
        return None

    top = scores[0]

    home_goals = getattr(
        top,
        "home_goals",
        None,
    )
    away_goals = getattr(
        top,
        "away_goals",
        None,
    )

    if (
        home_goals is not None
        and away_goals is not None
    ):
        return f"{int(home_goals)}-{int(away_goals)}"

    return str(top)


def score_prediction(
    *,
    prediction: Any,
    actual_outcome: str,
    prudent_threshold: float = 0.10,
) -> BacktestScore:
    home = float(
        prediction.home_win_probability
    )
    draw = float(
        prediction.draw_probability
    )
    away = float(
        prediction.away_win_probability
    )

    predicted = determine_predicted_outcome(
        home,
        draw,
        away,
    )

    prudent = determine_prudent_prediction(
        home,
        draw,
        away,
        most_likely_score=get_top_score_text(
            prediction
        ),
        threshold=prudent_threshold,
    )

    return BacktestScore(
        predicted_outcome=predicted,
        prudent_prediction=prudent,
        outcome_hit=int(
            predicted == actual_outcome
        ),
        prudent_hit=int(
            actual_outcome in prudent
        ),
        brier_score=calculate_brier_score(
            home,
            draw,
            away,
            actual_outcome,
        ),
        log_loss=calculate_log_loss(
            home,
            draw,
            away,
            actual_outcome,
        ),
        signals=len(prudent),
    )


@dataclass(frozen=True)
class CandidateParameters:
    strength_spread: float
    fallback_home_goals_average: float
    fallback_away_goals_average: float


@dataclass(frozen=True)
class CandidateEvaluation:
    parameters: CandidateParameters
    sample_size: int
    outcome_hits: int
    prudent_hits: int
    signals_per_game: float
    brier_score: float
    log_loss: float


def _canonical_json(
    value: dict[str, Any],
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def create_temporary_candidate_model(
    connection: sqlite3.Connection,
    *,
    league_id: str,
    season_label: str,
    parent_model_version: str,
    candidate_model_version: str,
    parameters: CandidateParameters,
) -> None:
    parent = connection.execute(
        """
        SELECT parameters_json
        FROM model_versions
        WHERE model_version = ?
        """,
        (parent_model_version,),
    ).fetchone()

    if parent is None:
        raise LeagueModelLearningError(
            f"Modelo pai inexistente: {parent_model_version}"
        )

    cfg = copy.deepcopy(
        json.loads(parent["parameters_json"])
    )

    cfg["version"]["model_version"] = (
        candidate_model_version
    )

    cfg["version"]["created_for"] = (
        f"{league_id} — temporary learning candidate"
    )

    cfg["weights"].setdefault(
        "operational",
        {},
    )

    cfg["weights"]["operational"] = {
        "strength_spread": (
            parameters.strength_spread
        ),
        "fallback_home_goals_average": (
            parameters.fallback_home_goals_average
        ),
        "fallback_away_goals_average": (
            parameters.fallback_away_goals_average
        ),
    }

    parameters_json = _canonical_json(cfg)

    parameter_hash = hashlib.sha256(
        parameters_json.encode("utf-8")
    ).hexdigest()

    connection.execute(
        """
        INSERT INTO model_versions (
            model_version,
            league_id,
            season_label,
            parent_model_version,
            version_status,
            parameter_hash,
            parameters_json,
            notes
        )
        VALUES (?, ?, ?, ?, 'CANDIDATE', ?, ?, ?)
        """,
        (
            candidate_model_version,
            league_id,
            season_label,
            parent_model_version,
            parameter_hash,
            parameters_json,
            "Temporary automatic learning candidate.",
        ),
    )

    source_parameters = connection.execute(
        """
        SELECT
            parameter_name,
            parameter_value
        FROM model_parameters
        WHERE model_version = ?
        """,
        (parent_model_version,),
    ).fetchall()

    values = {
        str(row["parameter_name"]): float(
            row["parameter_value"]
        )
        for row in source_parameters
    }

    values[
        "operational.strength_spread"
    ] = parameters.strength_spread

    values[
        "operational.fallback_home_goals_average"
    ] = parameters.fallback_home_goals_average

    values[
        "operational.fallback_away_goals_average"
    ] = parameters.fallback_away_goals_average

    connection.executemany(
        """
        INSERT INTO model_parameters (
            model_version,
            parameter_name,
            parameter_value
        )
        VALUES (?, ?, ?)
        """,
        [
            (
                candidate_model_version,
                name,
                value,
            )
            for name, value in sorted(
                values.items()
            )
        ],
    )

    connection.execute(
        """
        INSERT INTO team_ratings (
            team_id,
            league_id,
            season_label,
            model_version,
            run_id,
            points_per_game,
            goals_for_per_game,
            goals_against_per_game,
            goal_difference_per_game,
            ppg_rating,
            attack_rating,
            defence_rating,
            goal_difference_rating,
            performance_rating,
            absolute_rating,
            league_relative_rating,
            rating_confidence,
            created_at
        )
        SELECT
            team_id,
            league_id,
            season_label,
            ?,
            run_id,
            points_per_game,
            goals_for_per_game,
            goals_against_per_game,
            goal_difference_per_game,
            ppg_rating,
            attack_rating,
            defence_rating,
            goal_difference_rating,
            performance_rating,
            absolute_rating,
            league_relative_rating,
            rating_confidence,
            CURRENT_TIMESTAMP
        FROM team_ratings
        WHERE model_version = ?
          AND league_id = ?
          AND season_label = ?
        """,
        (
            candidate_model_version,
            parent_model_version,
            league_id,
            season_label,
        ),
    )


def remove_temporary_candidate_model(
    connection: sqlite3.Connection,
    *,
    candidate_model_version: str,
) -> None:
    connection.execute(
        """
        DELETE FROM match_predictions
        WHERE model_version = ?
        """,
        (candidate_model_version,),
    )

    connection.execute(
        """
        DELETE FROM team_ratings
        WHERE model_version = ?
        """,
        (candidate_model_version,),
    )

    connection.execute(
        """
        DELETE FROM model_parameters
        WHERE model_version = ?
        """,
        (candidate_model_version,),
    )

    connection.execute(
        """
        DELETE FROM model_versions
        WHERE model_version = ?
        """,
        (candidate_model_version,),
    )


def prepare_matches_for_temporary_backtest(
    connection: sqlite3.Connection,
    *,
    matches: tuple[LearningMatch, ...],
) -> None:
    from datetime import datetime, timedelta, timezone

    base = (
        datetime.now(timezone.utc)
        + timedelta(days=30)
    )

    for index, match in enumerate(matches):
        future_date = (
            base + timedelta(minutes=index)
        ).strftime("%Y-%m-%d %H:%M:%S")

        connection.execute(
            """
            UPDATE matches
            SET
                status = 'SCHEDULED',
                match_date = ?
            WHERE match_id = ?
            """,
            (
                future_date,
                match.match_id,
            ),
        )


def evaluate_candidate_model(
    *,
    database_path: str | Path,
    league_id: str,
    season_label: str,
    parent_model_version: str,
    matches: tuple[LearningMatch, ...],
    parameters: CandidateParameters,
    candidate_model_version: str = (
        "__TEMP_LEARNING_CANDIDATE__"
    ),
    prudent_threshold: float = 0.10,
) -> CandidateEvaluation:
    if not matches:
        raise LeagueModelLearningError(
            "Não existem jogos para avaliar."
        )

    connection = connect_database(
        database_path
    )

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        remove_temporary_candidate_model(
            connection,
            candidate_model_version=(
                candidate_model_version
            ),
        )

        create_temporary_candidate_model(
            connection,
            league_id=league_id,
            season_label=season_label,
            parent_model_version=(
                parent_model_version
            ),
            candidate_model_version=(
                candidate_model_version
            ),
            parameters=parameters,
        )

        prepare_matches_for_temporary_backtest(
            connection,
            matches=matches,
        )

        connection.commit()

    except Exception:
        connection.rollback()
        connection.close()
        raise

    else:
        connection.close()

    scores: list[BacktestScore] = []

    try:
        for match in matches:
            if (
                match.prediction_stage
                == "CONFIRMED_LINEUP"
            ):
                predict_and_store_matches(
                    season_label=season_label,
                    model_version=(
                        candidate_model_version
                    ),
                    league_id=league_id,
                    match_id=match.match_id,
                    prediction_stage="PRE_MATCH",
                    database_path=database_path,
                )

            prediction = predict_match(
                home_team_id=match.home_team_id,
                away_team_id=match.away_team_id,
                season_label=season_label,
                model_version=(
                    candidate_model_version
                ),
                match_id=match.match_id,
                prediction_stage=(
                    match.prediction_stage
                ),
                database_path=database_path,
            )

            scores.append(
                score_prediction(
                    prediction=prediction,
                    actual_outcome=(
                        match.actual_outcome
                    ),
                    prudent_threshold=(
                        prudent_threshold
                    ),
                )
            )

        return CandidateEvaluation(
            parameters=parameters,
            sample_size=len(scores),
            outcome_hits=sum(
                item.outcome_hit
                for item in scores
            ),
            prudent_hits=sum(
                item.prudent_hit
                for item in scores
            ),
            signals_per_game=mean(
                item.signals
                for item in scores
            ),
            brier_score=mean(
                item.brier_score
                for item in scores
            ),
            log_loss=mean(
                item.log_loss
                for item in scores
            ),
        )

    finally:
        cleanup = connect_database(
            database_path
        )

        try:
            with cleanup:
                remove_temporary_candidate_model(
                    cleanup,
                    candidate_model_version=(
                        candidate_model_version
                    ),
                )

        finally:
            cleanup.close()


MIN_PROMOTION_SAMPLE_SIZE = 10
MIN_PARAMETER_STABILITY = 0.60


@dataclass(frozen=True)
class LearningDecision:
    decision: str
    sample_size: int
    brier_improvement: float
    log_loss_improvement: float
    outcome_accuracy_improvement: float
    prudent_accuracy_improvement: float
    parameter_stability: float
    reason: str


def calculate_parameter_stability(
    selected_parameters: list[
        CandidateParameters
    ],
) -> float:
    if not selected_parameters:
        return 0.0

    counts: dict[
        tuple[float, float, float],
        int,
    ] = {}

    for parameters in selected_parameters:
        key = (
            parameters.strength_spread,
            parameters.fallback_home_goals_average,
            parameters.fallback_away_goals_average,
        )

        counts[key] = counts.get(
            key,
            0,
        ) + 1

    return max(counts.values()) / len(
        selected_parameters
    )


def decide_model_promotion(
    *,
    baseline: CandidateEvaluation,
    out_of_sample: CandidateEvaluation,
    selected_parameters: list[
        CandidateParameters
    ],
) -> LearningDecision:
    if (
        baseline.sample_size
        != out_of_sample.sample_size
    ):
        raise LeagueModelLearningError(
            "Baseline e validação out-of-sample "
            "têm amostras diferentes."
        )

    sample_size = baseline.sample_size

    brier_improvement = (
        baseline.brier_score
        - out_of_sample.brier_score
    )

    log_loss_improvement = (
        baseline.log_loss
        - out_of_sample.log_loss
    )

    baseline_outcome_accuracy = (
        baseline.outcome_hits
        / sample_size
        if sample_size
        else 0.0
    )

    candidate_outcome_accuracy = (
        out_of_sample.outcome_hits
        / sample_size
        if sample_size
        else 0.0
    )

    baseline_prudent_accuracy = (
        baseline.prudent_hits
        / sample_size
        if sample_size
        else 0.0
    )

    candidate_prudent_accuracy = (
        out_of_sample.prudent_hits
        / sample_size
        if sample_size
        else 0.0
    )

    outcome_accuracy_improvement = (
        candidate_outcome_accuracy
        - baseline_outcome_accuracy
    )

    prudent_accuracy_improvement = (
        candidate_prudent_accuracy
        - baseline_prudent_accuracy
    )

    parameter_stability = (
        calculate_parameter_stability(
            selected_parameters
        )
    )

    if sample_size < MIN_PROMOTION_SAMPLE_SIZE:
        return LearningDecision(
            decision="INSUFFICIENT_SAMPLE",
            sample_size=sample_size,
            brier_improvement=brier_improvement,
            log_loss_improvement=(
                log_loss_improvement
            ),
            outcome_accuracy_improvement=(
                outcome_accuracy_improvement
            ),
            prudent_accuracy_improvement=(
                prudent_accuracy_improvement
            ),
            parameter_stability=(
                parameter_stability
            ),
            reason=(
                "Amostra independente ainda inferior "
                f"ao mínimo de {MIN_PROMOTION_SAMPLE_SIZE} "
                "jogos para promoção automática."
            ),
        )

    if (
        parameter_stability
        < MIN_PARAMETER_STABILITY
    ):
        return LearningDecision(
            decision="INSUFFICIENT_SAMPLE",
            sample_size=sample_size,
            brier_improvement=brier_improvement,
            log_loss_improvement=(
                log_loss_improvement
            ),
            outcome_accuracy_improvement=(
                outcome_accuracy_improvement
            ),
            prudent_accuracy_improvement=(
                prudent_accuracy_improvement
            ),
            parameter_stability=(
                parameter_stability
            ),
            reason=(
                "Parâmetros instáveis entre validações "
                "out-of-sample; manter modelo ACTIVE."
            ),
        )

    improves_probabilistic_scores = (
        brier_improvement > 0.0
        and log_loss_improvement > 0.0
    )

    does_not_degrade_outcomes = (
        outcome_accuracy_improvement >= 0.0
        and prudent_accuracy_improvement >= 0.0
    )

    if (
        improves_probabilistic_scores
        and does_not_degrade_outcomes
    ):
        return LearningDecision(
            decision="PROMOTE",
            sample_size=sample_size,
            brier_improvement=brier_improvement,
            log_loss_improvement=(
                log_loss_improvement
            ),
            outcome_accuracy_improvement=(
                outcome_accuracy_improvement
            ),
            prudent_accuracy_improvement=(
                prudent_accuracy_improvement
            ),
            parameter_stability=(
                parameter_stability
            ),
            reason=(
                "Validação out-of-sample melhora Brier "
                "e LogLoss, não degrada 1X2 nem prudente "
                "e apresenta parâmetros estáveis."
            ),
        )

    return LearningDecision(
        decision="REJECT",
        sample_size=sample_size,
        brier_improvement=brier_improvement,
        log_loss_improvement=(
            log_loss_improvement
        ),
        outcome_accuracy_improvement=(
            outcome_accuracy_improvement
        ),
        prudent_accuracy_improvement=(
            prudent_accuracy_improvement
        ),
        parameter_stability=(
            parameter_stability
        ),
        reason=(
            "O candidato não cumpre simultaneamente "
            "os critérios de melhoria probabilística "
            "e de não degradação 1X2/prudente."
        ),
    )


DEFAULT_SPREAD_GRID = (
    0.10, 0.20, 0.30, 0.40, 0.50, 0.60,
)

DEFAULT_HOME_AVERAGE_GRID = (
    1.35, 1.45, 1.55, 1.65, 1.75, 1.85,
)

DEFAULT_AWAY_AVERAGE_GRID = (
    0.85, 0.95, 1.05, 1.15, 1.25, 1.35,
)


@dataclass(frozen=True)
class LeaveOneOutResult:
    out_of_sample: CandidateEvaluation
    selected_parameters: tuple[
        CandidateParameters,
        ...
    ]


@dataclass(frozen=True)
class LeagueLearningAnalysis:
    league_id: str
    season_label: str
    active_model_version: str
    baseline: CandidateEvaluation
    best_full_sample: CandidateEvaluation
    leave_one_out: LeaveOneOutResult
    decision: LearningDecision


def candidate_sort_key(
    result: CandidateEvaluation,
) -> tuple[float, float, int, int, float]:
    return (
        result.log_loss,
        result.brier_score,
        -result.outcome_hits,
        -result.prudent_hits,
        result.signals_per_game,
    )


def search_best_candidate(
    *,
    database_path: str | Path,
    league_id: str,
    season_label: str,
    parent_model_version: str,
    matches: tuple[LearningMatch, ...],
    spreads: tuple[float, ...] = (
        DEFAULT_SPREAD_GRID
    ),
    home_averages: tuple[float, ...] = (
        DEFAULT_HOME_AVERAGE_GRID
    ),
    away_averages: tuple[float, ...] = (
        DEFAULT_AWAY_AVERAGE_GRID
    ),
) -> CandidateEvaluation:
    results: list[
        CandidateEvaluation
    ] = []

    for spread in spreads:
        for home_average in home_averages:
            for away_average in away_averages:
                result = evaluate_candidate_model(
                    database_path=database_path,
                    league_id=league_id,
                    season_label=season_label,
                    parent_model_version=(
                        parent_model_version
                    ),
                    matches=matches,
                    parameters=CandidateParameters(
                        strength_spread=spread,
                        fallback_home_goals_average=(
                            home_average
                        ),
                        fallback_away_goals_average=(
                            away_average
                        ),
                    ),
                )

                results.append(
                    result
                )

    if not results:
        raise LeagueModelLearningError(
            "A pesquisa não produziu candidatos."
        )

    return min(
        results,
        key=candidate_sort_key,
    )


def run_leave_one_out(
    *,
    database_path: str | Path,
    league_id: str,
    season_label: str,
    parent_model_version: str,
    matches: tuple[LearningMatch, ...],
) -> LeaveOneOutResult:
    if len(matches) < 2:
        raise LeagueModelLearningError(
            "Leave-one-out requer pelo menos 2 jogos."
        )

    holdout_results: list[
        CandidateEvaluation
    ] = []

    selected_parameters: list[
        CandidateParameters
    ] = []

    for holdout_index, holdout_match in enumerate(
        matches
    ):
        train_matches = tuple(
            match
            for index, match in enumerate(matches)
            if index != holdout_index
        )

        best = search_best_candidate(
            database_path=database_path,
            league_id=league_id,
            season_label=season_label,
            parent_model_version=(
                parent_model_version
            ),
            matches=train_matches,
        )

        selected_parameters.append(
            best.parameters
        )

        holdout = evaluate_candidate_model(
            database_path=database_path,
            league_id=league_id,
            season_label=season_label,
            parent_model_version=(
                parent_model_version
            ),
            matches=(holdout_match,),
            parameters=best.parameters,
        )

        holdout_results.append(
            holdout
        )

    return LeaveOneOutResult(
        out_of_sample=CandidateEvaluation(
            parameters=selected_parameters[0],
            sample_size=len(
                holdout_results
            ),
            outcome_hits=sum(
                result.outcome_hits
                for result in holdout_results
            ),
            prudent_hits=sum(
                result.prudent_hits
                for result in holdout_results
            ),
            signals_per_game=mean(
                result.signals_per_game
                for result in holdout_results
            ),
            brier_score=mean(
                result.brier_score
                for result in holdout_results
            ),
            log_loss=mean(
                result.log_loss
                for result in holdout_results
            ),
        ),
        selected_parameters=tuple(
            selected_parameters
        ),
    )


def load_operational_parameters(
    connection: sqlite3.Connection,
    *,
    model_version: str,
) -> CandidateParameters:
    row = connection.execute(
        """
        SELECT parameters_json
        FROM model_versions
        WHERE model_version = ?
        """,
        (model_version,),
    ).fetchone()

    if row is None:
        raise LeagueModelLearningError(
            f"Modelo inexistente: {model_version}"
        )

    cfg = json.loads(
        row["parameters_json"]
    )

    operational = cfg[
        "weights"
    ][
        "operational"
    ]

    return CandidateParameters(
        strength_spread=float(
            operational[
                "strength_spread"
            ]
        ),
        fallback_home_goals_average=float(
            operational[
                "fallback_home_goals_average"
            ]
        ),
        fallback_away_goals_average=float(
            operational[
                "fallback_away_goals_average"
            ]
        ),
    )


def analyze_league_learning(
    *,
    source_database_path: str | Path,
    league_id: str,
    season_label: str = "2026/27",
) -> LeagueLearningAnalysis:
    temp_db = create_learning_database_copy(
        source_database_path=(
            source_database_path
        ),
        league_id=league_id,
    )

    temp_directory = temp_db.parent

    try:
        state = load_league_learning_state(
            league_id=league_id,
            season_label=season_label,
            database_path=temp_db,
        )

        if not state.evaluated_matches:
            raise LeagueModelLearningError(
                f"{league_id}: sem jogos avaliados."
            )

        connection = connect_database(
            temp_db
        )

        try:
            active_parameters = (
                load_operational_parameters(
                    connection,
                    model_version=(
                        state.active_model_version
                    ),
                )
            )

        finally:
            connection.close()

        baseline = evaluate_candidate_model(
            database_path=temp_db,
            league_id=state.league_id,
            season_label=state.season_label,
            parent_model_version=(
                state.active_model_version
            ),
            matches=state.evaluated_matches,
            parameters=active_parameters,
        )

        best_full_sample = search_best_candidate(
            database_path=temp_db,
            league_id=state.league_id,
            season_label=state.season_label,
            parent_model_version=(
                state.active_model_version
            ),
            matches=state.evaluated_matches,
        )

        leave_one_out = run_leave_one_out(
            database_path=temp_db,
            league_id=state.league_id,
            season_label=state.season_label,
            parent_model_version=(
                state.active_model_version
            ),
            matches=state.evaluated_matches,
        )

        decision = decide_model_promotion(
            baseline=baseline,
            out_of_sample=(
                leave_one_out.out_of_sample
            ),
            selected_parameters=list(
                leave_one_out.selected_parameters
            ),
        )

        return LeagueLearningAnalysis(
            league_id=state.league_id,
            season_label=state.season_label,
            active_model_version=(
                state.active_model_version
            ),
            baseline=baseline,
            best_full_sample=(
                best_full_sample
            ),
            leave_one_out=(
                leave_one_out
            ),
            decision=decision,
        )

    finally:
        shutil.rmtree(
            temp_directory,
            ignore_errors=True,
        )


@dataclass(frozen=True)
class AutomaticLearningRun:
    league_id: str
    triggered: bool
    reason: str
    current_sample_size: int
    last_analyzed_sample_size: int
    analysis: LeagueLearningAnalysis | None = None


def run_automatic_league_learning(
    *,
    league_id: str,
    season_label: str = "2026/27",
    newly_inserted_evaluations: int = 0,
    database_path: str | Path | None = None,
) -> AutomaticLearningRun:
    """
    Orquestra a aprendizagem pós-jogo de uma liga.

    Regras:
    - não executa aprendizagem se nenhuma nova avaliação foi gravada;
    - trabalha sempre por liga;
    - usa apenas jogos independentes deduplicados;
    - só recalibra quando a amostra atual é superior à última analisada;
    - a análise é feita numa cópia temporária da base;
    - cada nova análise é persistida como nova versão da liga;
    - só promove automaticamente quando a decisão é PROMOTE;
    - previsões históricas já publicadas nunca são recalculadas.
    """

    final_league_id = str(
        league_id
    ).strip().upper()

    if not final_league_id:
        raise LeagueModelLearningError(
            "league_id é obrigatório."
        )

    if newly_inserted_evaluations <= 0:
        return AutomaticLearningRun(
            league_id=final_league_id,
            triggered=False,
            reason=(
                "Nenhuma nova avaliação foi gravada."
            ),
            current_sample_size=0,
            last_analyzed_sample_size=0,
            analysis=None,
        )

    connection = connect_database(
        database_path
    )

    try:
        matches = load_learning_matches(
            connection,
            league_id=final_league_id,
            season_label=season_label,
        )

        current_sample_size = len(
            matches
        )

        (
            due,
            last_analyzed_sample_size,
        ) = learning_is_due(
            connection,
            league_id=final_league_id,
            current_sample_size=(
                current_sample_size
            ),
        )

    finally:
        connection.close()

    if not due:
        return AutomaticLearningRun(
            league_id=final_league_id,
            triggered=False,
            reason=(
                "A amostra independente atual já foi "
                "analisada anteriormente."
            ),
            current_sample_size=(
                current_sample_size
            ),
            last_analyzed_sample_size=(
                last_analyzed_sample_size
            ),
            analysis=None,
        )

    analysis = analyze_league_learning(
        source_database_path=(
            database_path
        ),
        league_id=final_league_id,
        season_label=season_label,
    )

    candidate_model_version = (
        persist_learning_analysis(
            analysis=analysis,
            database_path=database_path,
        )
    )

    if (
        analysis.decision.decision
        == "PROMOTE"
    ):
        promote_candidate_model(
            candidate_model_version=(
                candidate_model_version
            ),
            league_id=final_league_id,
            season_label=season_label,
            database_path=database_path,
        )

        final_reason = (
            "Nova amostra independente analisada; "
            f"{candidate_model_version} foi promovido "
            "a ACTIVE."
        )

    else:
        final_reason = (
            "Nova amostra independente analisada; "
            f"{candidate_model_version} persistido com "
            f"decisão {analysis.decision.decision}. "
            "Modelo ACTIVE mantido."
        )

    return AutomaticLearningRun(
        league_id=final_league_id,
        triggered=True,
        reason=final_reason,
        current_sample_size=(
            current_sample_size
        ),
        last_analyzed_sample_size=(
            last_analyzed_sample_size
        ),
        analysis=analysis,
    )


def next_league_model_version(
    connection: sqlite3.Connection,
    *,
    league_id: str,
) -> str:
    prefix = f"{league_id.strip().upper()}_MODEL_0_"

    rows = connection.execute(
        """
        SELECT model_version
        FROM model_versions
        WHERE league_id = ?
          AND model_version LIKE ?
        """,
        (
            league_id.strip().upper(),
            f"{prefix}%",
        ),
    ).fetchall()

    numbers: list[int] = []

    for row in rows:
        value = str(row["model_version"])

        try:
            numbers.append(
                int(value.rsplit("_", 1)[1])
            )
        except (IndexError, ValueError):
            continue

    next_number = (
        max(numbers) + 1
        if numbers
        else 1
    )

    return f"{prefix}{next_number}"


def persist_learning_analysis(
    *,
    analysis: LeagueLearningAnalysis,
    database_path: str | Path | None = None,
) -> str:
    """
    Persiste uma nova versão candidata e a respetiva decisão.

    Nesta fase:
    - INSUFFICIENT_SAMPLE -> CANDIDATE
    - REJECT -> REJECTED
    - PROMOTE -> CANDIDATE, aguardando promoção transacional
      numa rotina separada.
    """

    connection = connect_database(
        database_path
    )

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        candidate_model_version = (
            next_league_model_version(
                connection,
                league_id=analysis.league_id,
            )
        )

        decision = analysis.decision

        if decision.decision == "REJECT":
            version_status = "REJECTED"
            candidate_status = "REJECTED"
        else:
            version_status = "CANDIDATE"
            candidate_status = "EVALUATED"

        best = analysis.best_full_sample
        params = best.parameters

        create_temporary_candidate_model(
            connection,
            league_id=analysis.league_id,
            season_label=analysis.season_label,
            parent_model_version=(
                analysis.active_model_version
            ),
            candidate_model_version=(
                candidate_model_version
            ),
            parameters=params,
        )

        connection.execute(
            """
            UPDATE model_versions
            SET
                version_status = ?,
                notes = ?
            WHERE model_version = ?
            """,
            (
                version_status,
                (
                    "Automatic league learning | "
                    f"sample={decision.sample_size} | "
                    f"decision={decision.decision} | "
                    f"stability={decision.parameter_stability:.6f} | "
                    f"{decision.reason}"
                ),
                candidate_model_version,
            ),
        )

        cursor = connection.execute(
            """
            INSERT INTO model_candidates (
                candidate_model_version,
                parent_model_version,
                league_id,
                evaluation_scope,
                sample_size,
                baseline_brier_score,
                candidate_brier_score,
                baseline_log_loss,
                candidate_log_loss,
                baseline_outcome_accuracy,
                candidate_outcome_accuracy,
                candidate_status,
                evaluated_at
            )
            VALUES (
                ?, ?, ?, 'LEAGUE', ?,
                ?, ?, ?, ?, ?, ?,
                ?, CURRENT_TIMESTAMP
            )
            """,
            (
                candidate_model_version,
                analysis.active_model_version,
                analysis.league_id,
                decision.sample_size,
                analysis.baseline.brier_score,
                best.brier_score,
                analysis.baseline.log_loss,
                best.log_loss,
                (
                    100.0
                    * analysis.baseline.outcome_hits
                    / analysis.baseline.sample_size
                ),
                (
                    100.0
                    * best.outcome_hits
                    / best.sample_size
                ),
                candidate_status,
            ),
        )

        candidate_id = int(
            cursor.lastrowid
        )

        connection.execute(
            """
            INSERT INTO model_promotion_decisions (
                candidate_id,
                decision,
                sample_size,
                brier_improvement,
                log_loss_improvement,
                outcome_accuracy_improvement,
                decision_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                decision.decision,
                decision.sample_size,
                decision.brier_improvement,
                decision.log_loss_improvement,
                (
                    100.0
                    * decision.outcome_accuracy_improvement
                ),
                (
                    f"{decision.reason} "
                    f"Prudent improvement="
                    f"{100.0 * decision.prudent_accuracy_improvement:.2f} pp; "
                    f"parameter stability="
                    f"{100.0 * decision.parameter_stability:.2f}%."
                ),
            ),
        )

        connection.commit()

        return candidate_model_version

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def promote_candidate_model(
    *,
    candidate_model_version: str,
    league_id: str,
    season_label: str = "2026/27",
    database_path: str | Path | None = None,
) -> None:
    """
    Promove atomicamente um candidato já aprovado.

    Regras:
    - só atua na liga/época indicadas;
    - exige candidato existente;
    - exige decisão PROMOTE;
    - retira ACTIVE atual antes de ativar o candidato;
    - atualiza model_candidates para PROMOTED;
    - rollback integral em caso de erro.
    """

    final_league_id = (
        str(league_id)
        .strip()
        .upper()
    )

    connection = connect_database(
        database_path
    )

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        candidate = connection.execute(
            """
            SELECT
                mv.model_version,
                mv.league_id,
                mv.season_label,
                mv.version_status,
                mc.candidate_id,
                mc.candidate_status,
                mpd.decision
            FROM model_versions mv
            JOIN model_candidates mc
              ON mc.candidate_model_version
               = mv.model_version
            JOIN model_promotion_decisions mpd
              ON mpd.candidate_id
               = mc.candidate_id
            WHERE mv.model_version = ?
            """,
            (
                candidate_model_version,
            ),
        ).fetchone()

        if candidate is None:
            raise LeagueModelLearningError(
                "Candidato inexistente ou sem decisão: "
                f"{candidate_model_version}"
            )

        if (
            str(candidate["league_id"])
            != final_league_id
            or str(candidate["season_label"])
            != season_label
        ):
            raise LeagueModelLearningError(
                "O candidato não pertence à liga/época "
                "indicadas."
            )

        if str(candidate["decision"]) != "PROMOTE":
            raise LeagueModelLearningError(
                "O candidato não possui decisão PROMOTE."
            )

        if (
            str(candidate["version_status"])
            not in {"CANDIDATE", "ACTIVE"}
        ):
            raise LeagueModelLearningError(
                "Estado inválido para promoção: "
                f"{candidate['version_status']}"
            )

        connection.execute(
            """
            UPDATE model_versions
            SET
                version_status = 'RETIRED',
                retired_at = CURRENT_TIMESTAMP
            WHERE league_id = ?
              AND season_label = ?
              AND version_status = 'ACTIVE'
              AND model_version <> ?
            """,
            (
                final_league_id,
                season_label,
                candidate_model_version,
            ),
        )

        connection.execute(
            """
            UPDATE model_versions
            SET
                version_status = 'ACTIVE',
                activated_at = COALESCE(
                    activated_at,
                    CURRENT_TIMESTAMP
                ),
                retired_at = NULL
            WHERE model_version = ?
            """,
            (
                candidate_model_version,
            ),
        )

        connection.execute(
            """
            UPDATE model_candidates
            SET candidate_status = 'PROMOTED'
            WHERE candidate_model_version = ?
            """,
            (
                candidate_model_version,
            ),
        )

        active_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM model_versions
            WHERE league_id = ?
              AND season_label = ?
              AND version_status = 'ACTIVE'
            """,
            (
                final_league_id,
                season_label,
            ),
        ).fetchone()[0]

        if int(active_count) != 1:
            raise LeagueModelLearningError(
                "A promoção não deixou exatamente "
                "um modelo ACTIVE na liga."
            )

        active_model = connection.execute(
            """
            SELECT model_version
            FROM model_versions
            WHERE league_id = ?
              AND season_label = ?
              AND version_status = 'ACTIVE'
            """,
            (
                final_league_id,
                season_label,
            ),
        ).fetchone()

        if (
            active_model is None
            or str(active_model["model_version"])
            != candidate_model_version
        ):
            raise LeagueModelLearningError(
                "O candidato não ficou ACTIVE "
                "após a promoção."
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
