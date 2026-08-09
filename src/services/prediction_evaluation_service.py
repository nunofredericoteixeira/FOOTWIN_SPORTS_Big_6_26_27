# -*- coding: utf-8 -*-

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.database.init_database import connect_database
from src.utils.logger import get_logger


logger = get_logger("services.prediction_evaluation_service")

LOG_LOSS_EPSILON = 1e-15
VALID_PREDICTION_STAGES = {
    "PRE_MATCH",
    "CONFIRMED_LINEUP",
}


class PredictionEvaluationServiceError(RuntimeError):
    """Erro ocorrido durante a avaliação de previsões."""


@dataclass(frozen=True)
class PredictionEvaluation:
    """Avaliação calculada para uma previsão oficial."""

    prediction_id: str
    match_id: str
    model_version: str
    prediction_stage: str
    actual_home_goals: int
    actual_away_goals: int
    actual_outcome: str
    predicted_outcome: str
    outcome_hit: int
    prudent_prediction: str
    prudent_outcome_hit: int
    exact_score_hit: int
    brier_score: float
    log_loss: float


@dataclass(frozen=True)
class PredictionEvaluationRunSummary:
    """Resumo de uma execução do avaliador."""

    eligible_predictions: int
    inserted_evaluations: int
    existing_evaluations: int
    failed_evaluations: int


def determine_outcome(
    home_goals: int,
    away_goals: int,
) -> str:
    """Converte um resultado final para 1, X ou 2."""

    if home_goals < 0 or away_goals < 0:
        raise PredictionEvaluationServiceError(
            "Os golos não podem ser negativos."
        )

    if home_goals > away_goals:
        return "1"

    if home_goals == away_goals:
        return "X"

    return "2"


def normalize_probabilities(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
) -> tuple[float, float, float]:
    """Valida e normaliza as probabilidades 1X2."""

    probabilities = (
        float(home_probability),
        float(draw_probability),
        float(away_probability),
    )

    if not all(
        math.isfinite(value)
        for value in probabilities
    ):
        raise PredictionEvaluationServiceError(
            "As probabilidades têm de ser finitas."
        )

    if any(
        value < 0.0 or value > 1.0
        for value in probabilities
    ):
        raise PredictionEvaluationServiceError(
            "As probabilidades têm de estar entre 0 e 1."
        )

    total = sum(probabilities)

    if total <= 0.0:
        raise PredictionEvaluationServiceError(
            "A soma das probabilidades tem de ser positiva."
        )

    return tuple(
        value / total
        for value in probabilities
    )


def determine_predicted_outcome(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
) -> str:
    """
    Devolve o resultado simples mais provável.

    Em caso de igualdade absoluta, aplica a ordem determinística
    1, X, 2.
    """

    probabilities = normalize_probabilities(
        home_probability,
        draw_probability,
        away_probability,
    )

    outcomes = ("1", "X", "2")

    best_index = max(
        range(len(probabilities)),
        key=lambda index: probabilities[index],
    )

    return outcomes[best_index]


def determine_prudent_prediction(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    most_likely_score: object = None,
    threshold: float = 0.10,
) -> str:
    """
    Calcula o prognóstico prudente oficial.

    Usa dupla possibilidade quando a diferença entre as duas
    probabilidades mais elevadas é igual ou inferior ao limite.
    O sinal implícito no marcador mais provável é sempre incluído.
    """

    threshold_value = float(threshold)

    if not math.isfinite(threshold_value):
        raise PredictionEvaluationServiceError(
            "O limite prudente tem de ser finito."
        )

    if threshold_value < 0.0:
        raise PredictionEvaluationServiceError(
            "O limite prudente não pode ser negativo."
        )

    probabilities = normalize_probabilities(
        home_probability,
        draw_probability,
        away_probability,
    )

    ranked = sorted(
        zip(
            ("1", "X", "2"),
            probabilities,
            strict=True,
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    first_outcome, first_probability = ranked[0]
    second_outcome, second_probability = ranked[1]

    outcome_order = {
        "1": 0,
        "X": 1,
        "2": 2,
    }

    if (
        first_probability
        - second_probability
    ) <= threshold_value:
        prudent_prediction = "".join(
            sorted(
                (
                    first_outcome,
                    second_outcome,
                ),
                key=lambda outcome: outcome_order[outcome],
            )
        )
    else:
        prudent_prediction = first_outcome

    predicted_score = parse_score(
        most_likely_score
    )

    if predicted_score is not None:
        score_outcome = determine_outcome(
            predicted_score[0],
            predicted_score[1],
        )

        if score_outcome not in prudent_prediction:
            prudent_prediction = "".join(
                sorted(
                    {
                        first_outcome,
                        score_outcome,
                    },
                    key=lambda outcome: outcome_order[outcome],
                )
            )

    return prudent_prediction


def calculate_brier_score(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    actual_outcome: str,
) -> float:
    """Calcula o Brier Score multiclasse para 1X2."""

    probabilities = normalize_probabilities(
        home_probability,
        draw_probability,
        away_probability,
    )

    outcomes = ("1", "X", "2")

    if actual_outcome not in outcomes:
        raise PredictionEvaluationServiceError(
            f"Resultado real inválido: {actual_outcome!r}"
        )

    return sum(
        (
            probability
            - (1.0 if outcome == actual_outcome else 0.0)
        )
        ** 2
        for outcome, probability in zip(
            outcomes,
            probabilities,
            strict=True,
        )
    )


def calculate_log_loss(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    actual_outcome: str,
) -> float:
    """Calcula a perda logarítmica da classe realmente observada."""

    probabilities = normalize_probabilities(
        home_probability,
        draw_probability,
        away_probability,
    )

    probability_by_outcome = {
        "1": probabilities[0],
        "X": probabilities[1],
        "2": probabilities[2],
    }

    if actual_outcome not in probability_by_outcome:
        raise PredictionEvaluationServiceError(
            f"Resultado real inválido: {actual_outcome!r}"
        )

    actual_probability = max(
        probability_by_outcome[actual_outcome],
        LOG_LOSS_EPSILON,
    )

    return -math.log(actual_probability)


def parse_score(
    value: object,
) -> tuple[int, int] | None:
    """Interpreta um marcador previsto no formato casa-fora."""

    if value is None:
        return None

    match = re.fullmatch(
        r"\s*(\d{1,2})\s*[-–:]\s*(\d{1,2})\s*",
        str(value),
    )

    if match is None:
        return None

    return int(match.group(1)), int(match.group(2))


def get_eligible_predictions(
    connection: sqlite3.Connection,
    *,
    league_id: str | None = None,
    season_label: str | None = None,
    model_version: str | None = None,
) -> list[sqlite3.Row]:
    """
    Seleciona a previsão oficial a avaliar por jogo e modelo.

    Prioridade:
    1. CONFIRMED_LINEUP atual;
    2. PRE_MATCH atual.

    Apenas considera jogos oficialmente concluídos, com resultado
    preenchido, e previsões ainda não avaliadas.
    """

    conditions = [
        "m.status IN ('PLAYED', 'AWARDED')",
        "m.home_goals IS NOT NULL",
        "m.away_goals IS NOT NULL",
        "mp.is_current = 1",
        (
            "mp.prediction_stage IN "
            "('PRE_MATCH', 'CONFIRMED_LINEUP')"
        ),
    ]

    parameters: list[object] = []

    if league_id:
        conditions.append("m.league_id = ?")
        parameters.append(league_id.strip().upper())

    if season_label:
        conditions.append("m.season_label = ?")
        parameters.append(season_label.strip())

    if model_version:
        conditions.append("mp.model_version = ?")
        parameters.append(model_version.strip())

    return connection.execute(
        f"""
        WITH ranked_predictions AS (
            SELECT
                mp.prediction_id,
                mp.match_id,
                mp.model_version,
                mp.prediction_stage,
                mp.prediction_version,
                mp.home_win_probability,
                mp.draw_probability,
                mp.away_win_probability,
                mp.most_likely_score,
                m.home_goals,
                m.away_goals,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        mp.match_id,
                        mp.model_version
                    ORDER BY
                        CASE mp.prediction_stage
                            WHEN 'CONFIRMED_LINEUP' THEN 1
                            WHEN 'PRE_MATCH' THEN 2
                            ELSE 3
                        END,
                        mp.prediction_version DESC,
                        mp.prediction_timestamp DESC,
                        mp.prediction_id DESC
                ) AS selection_rank
            FROM matches AS m
            INNER JOIN match_predictions AS mp
                ON mp.match_id = m.match_id
            WHERE {" AND ".join(conditions)}
        )
        SELECT
            ranked.prediction_id,
            ranked.match_id,
            ranked.model_version,
            ranked.prediction_stage,
            ranked.prediction_version,
            ranked.home_win_probability,
            ranked.draw_probability,
            ranked.away_win_probability,
            ranked.most_likely_score,
            ranked.home_goals,
            ranked.away_goals,
            CASE
                WHEN evaluation.prediction_id IS NULL THEN 0
                ELSE 1
            END AS already_evaluated
        FROM ranked_predictions AS ranked
        LEFT JOIN prediction_evaluations AS evaluation
            ON evaluation.prediction_id = ranked.prediction_id
        WHERE ranked.selection_rank = 1
        ORDER BY
            ranked.match_id,
            ranked.model_version
        """,
        parameters,
    ).fetchall()


def build_prediction_evaluation(
    row: sqlite3.Row,
) -> PredictionEvaluation:
    """Calcula todas as métricas de uma previsão selecionada."""

    prediction_stage = str(row["prediction_stage"])

    if prediction_stage not in VALID_PREDICTION_STAGES:
        raise PredictionEvaluationServiceError(
            "Estágio de previsão inválido: "
            f"{prediction_stage!r}"
        )

    actual_home_goals = int(row["home_goals"])
    actual_away_goals = int(row["away_goals"])

    actual_outcome = determine_outcome(
        actual_home_goals,
        actual_away_goals,
    )

    home_probability = float(
        row["home_win_probability"]
    )
    draw_probability = float(
        row["draw_probability"]
    )
    away_probability = float(
        row["away_win_probability"]
    )

    predicted_outcome = determine_predicted_outcome(
        home_probability,
        draw_probability,
        away_probability,
    )

    prudent_prediction = determine_prudent_prediction(
        home_probability,
        draw_probability,
        away_probability,
        row["most_likely_score"],
    )

    predicted_score = parse_score(
        row["most_likely_score"]
    )

    exact_score_hit = int(
        predicted_score
        == (
            actual_home_goals,
            actual_away_goals,
        )
    )

    return PredictionEvaluation(
        prediction_id=str(row["prediction_id"]),
        match_id=str(row["match_id"]),
        model_version=str(row["model_version"]),
        prediction_stage=prediction_stage,
        actual_home_goals=actual_home_goals,
        actual_away_goals=actual_away_goals,
        actual_outcome=actual_outcome,
        predicted_outcome=predicted_outcome,
        outcome_hit=int(
            predicted_outcome == actual_outcome
        ),
        prudent_prediction=prudent_prediction,
        prudent_outcome_hit=int(
            actual_outcome in prudent_prediction
        ),
        exact_score_hit=exact_score_hit,
        brier_score=calculate_brier_score(
            home_probability,
            draw_probability,
            away_probability,
            actual_outcome,
        ),
        log_loss=calculate_log_loss(
            home_probability,
            draw_probability,
            away_probability,
            actual_outcome,
        ),
    )


def insert_prediction_evaluation(
    connection: sqlite3.Connection,
    evaluation: PredictionEvaluation,
) -> bool:
    """
    Grava uma avaliação de forma idempotente.

    Devolve True quando foi inserida e False quando já existia.
    """

    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO prediction_evaluations (
            prediction_id,
            match_id,
            model_version,
            prediction_stage,
            actual_home_goals,
            actual_away_goals,
            actual_outcome,
            predicted_outcome,
            outcome_hit,
            prudent_prediction,
            prudent_outcome_hit,
            exact_score_hit,
            brier_score,
            log_loss
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evaluation.prediction_id,
            evaluation.match_id,
            evaluation.model_version,
            evaluation.prediction_stage,
            evaluation.actual_home_goals,
            evaluation.actual_away_goals,
            evaluation.actual_outcome,
            evaluation.predicted_outcome,
            evaluation.outcome_hit,
            evaluation.prudent_prediction,
            evaluation.prudent_outcome_hit,
            evaluation.exact_score_hit,
            evaluation.brier_score,
            evaluation.log_loss,
        ),
    )

    return cursor.rowcount == 1


def update_existing_prudent_evaluation(
    connection: sqlite3.Connection,
    evaluation: PredictionEvaluation,
) -> bool:
    """
    Preenche os campos prudentes de uma avaliação já existente.

    Não altera as restantes métricas nem a data original.
    """

    cursor = connection.execute(
        """
        UPDATE prediction_evaluations
        SET
            prudent_prediction = ?,
            prudent_outcome_hit = ?
        WHERE prediction_id = ?
          AND (
              prudent_prediction IS NULL
              OR prudent_outcome_hit IS NULL
          )
        """,
        (
            evaluation.prudent_prediction,
            evaluation.prudent_outcome_hit,
            evaluation.prediction_id,
        ),
    )

    return cursor.rowcount == 1


def run_prediction_evaluation(
    *,
    league_id: str | None = None,
    season_label: str | None = None,
    model_version: str | None = None,
    database_path: str | Path | None = None,
) -> PredictionEvaluationRunSummary:
    """Avalia e grava todas as previsões oficiais elegíveis."""

    connection = connect_database(database_path)

    inserted_evaluations = 0
    existing_evaluations = 0
    failed_evaluations = 0

    try:
        eligible_predictions = get_eligible_predictions(
            connection,
            league_id=league_id,
            season_label=season_label,
            model_version=model_version,
        )

        logger.info(
            "Previsões elegíveis para avaliação | total=%s",
            len(eligible_predictions),
        )

        for row in eligible_predictions:
            try:
                evaluation = build_prediction_evaluation(
                    row
                )

                if int(row["already_evaluated"]) == 1:
                    with connection:
                        updated = (
                            update_existing_prudent_evaluation(
                                connection,
                                evaluation,
                            )
                        )

                    existing_evaluations += 1

                    if updated:
                        logger.info(
                            "Avaliação prudente preenchida | "
                            "prediction_id=%s | "
                            "prudente=%s | acerto=%s",
                            evaluation.prediction_id,
                            evaluation.prudent_prediction,
                            evaluation.prudent_outcome_hit,
                        )

                    continue

                with connection:
                    inserted = insert_prediction_evaluation(
                        connection,
                        evaluation,
                    )

                if inserted:
                    inserted_evaluations += 1

                    logger.info(
                        "Avaliação gravada | "
                        "prediction_id=%s | "
                        "real=%s | simples=%s | "
                        "prudente=%s | "
                        "acerto_simples=%s | "
                        "acerto_prudente=%s | marcador=%s",
                        evaluation.prediction_id,
                        evaluation.actual_outcome,
                        evaluation.predicted_outcome,
                        evaluation.prudent_prediction,
                        evaluation.outcome_hit,
                        evaluation.prudent_outcome_hit,
                        evaluation.exact_score_hit,
                    )
                else:
                    existing_evaluations += 1

            except Exception:
                failed_evaluations += 1

                logger.exception(
                    "Falha ao avaliar previsão | "
                    "prediction_id=%s",
                    row["prediction_id"],
                )

        return PredictionEvaluationRunSummary(
            eligible_predictions=len(
                eligible_predictions
            ),
            inserted_evaluations=inserted_evaluations,
            existing_evaluations=existing_evaluations,
            failed_evaluations=failed_evaluations,
        )

    finally:
        connection.close()
