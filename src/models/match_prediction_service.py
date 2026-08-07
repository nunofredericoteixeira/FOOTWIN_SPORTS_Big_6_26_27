# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.model_config import load_full_model_config
from src.database.init_database import connect_database
from src.models.league_goal_environment import (
    LeagueGoalEnvironment,
    calculate_expected_goals_base,
    calculate_league_goal_environment,
)
from src.models.poisson_model import (
    PoissonMatchDistribution,
    ScoreProbability,
    build_match_distribution,
    calculate_both_teams_to_score_probability,
    calculate_clean_sheet_probabilities,
    calculate_over_probability,
    calculate_under_probability,
    get_most_likely_scores,
)
from src.models.team_strength import (
    TeamStrength,
    calculate_matchup_factors,
    calculate_team_strength,
)
from src.utils.logger import get_logger


logger = get_logger("models.match_prediction_service")


@dataclass(frozen=True)
class MatchPrediction:
    home_team_id: str
    home_team_name: str

    away_team_id: str
    away_team_name: str

    league_id: str
    league_name: str

    season_label: str
    model_version: str

    expected_home_goals: float
    expected_away_goals: float
    expected_total_goals: float

    home_win_probability: float
    draw_probability: float
    away_win_probability: float

    over_15_probability: float
    under_15_probability: float

    over_25_probability: float
    under_25_probability: float

    over_35_probability: float
    under_35_probability: float

    both_teams_to_score_probability: float
    both_teams_not_to_score_probability: float

    home_clean_sheet_probability: float
    away_clean_sheet_probability: float

    home_matchup_factor: float
    away_matchup_factor: float

    prediction_confidence: float

    most_likely_scores: tuple[ScoreProbability, ...]


class MatchPredictionServiceError(RuntimeError):
    """Erro durante a previsão de um jogo."""


def predict_match(
    home_team_id: str,
    away_team_id: str,
    season_label: str = "2026/27",
    model_version: str | None = None,
    max_goals: int = 12,
    score_limit: int = 10,
    database_path: str | Path | None = None,
) -> MatchPrediction:
    """
    Calcula a previsão completa de um jogo.

    Inclui:

    - forças ofensivas e defensivas;
    - médias de golos da liga;
    - xG;
    - probabilidades 1X2;
    - mercados de golos;
    - ambas marcam;
    - clean sheets;
    - marcadores mais prováveis.
    """

    final_home_team_id = clean_required_text(
        home_team_id,
        "home_team_id",
    )

    final_away_team_id = clean_required_text(
        away_team_id,
        "away_team_id",
    )

    if final_home_team_id == final_away_team_id:
        raise MatchPredictionServiceError(
            "Uma equipa não pode jogar contra si própria."
        )

    final_model_version = (
        model_version.strip()
        if model_version
        else get_configured_model_version()
    )

    connection = connect_database(
        database_path
    )

    try:
        home_row = load_team_rating(
            connection=connection,
            team_id=final_home_team_id,
            season_label=season_label,
            model_version=final_model_version,
        )

        away_row = load_team_rating(
            connection=connection,
            team_id=final_away_team_id,
            season_label=season_label,
            model_version=final_model_version,
        )

        if home_row["league_id"] != away_row["league_id"]:
            raise MatchPredictionServiceError(
                "As duas equipas pertencem a ligas diferentes."
            )

        league_id = str(
            home_row["league_id"]
        )

        league_name = str(
            home_row["league_name"]
        )

        played_matches = load_played_league_matches(
            connection=connection,
            league_id=league_id,
            season_label=season_label,
        )

    finally:
        connection.close()

    home_strength = calculate_team_strength(
        home_row
    )

    away_strength = calculate_team_strength(
        away_row
    )

    home_matchup_factor, away_matchup_factor = (
        calculate_matchup_factors(
            home_team=home_strength,
            away_team=away_strength,
        )
    )

    environment = calculate_league_goal_environment(
        league_id=league_id,
        matches=played_matches,
        fallback_home_average=1.55,
        fallback_away_average=1.25,
    )

    expected_home_goals, expected_away_goals = (
        calculate_expected_goals_base(
            environment=environment,
            home_matchup_factor=home_matchup_factor,
            away_matchup_factor=away_matchup_factor,
        )
    )

    distribution = build_match_distribution(
        expected_home_goals=expected_home_goals,
        expected_away_goals=expected_away_goals,
        max_goals=max_goals,
    )

    prediction_confidence = calculate_prediction_confidence(
        home_strength=home_strength,
        away_strength=away_strength,
        environment=environment,
    )

    over_15 = calculate_over_probability(
        distribution,
        1.5,
    )

    under_15 = calculate_under_probability(
        distribution,
        1.5,
    )

    over_25 = calculate_over_probability(
        distribution,
        2.5,
    )

    under_25 = calculate_under_probability(
        distribution,
        2.5,
    )

    over_35 = calculate_over_probability(
        distribution,
        3.5,
    )

    under_35 = calculate_under_probability(
        distribution,
        3.5,
    )

    both_teams_score = (
        calculate_both_teams_to_score_probability(
            distribution
        )
    )

    home_clean_sheet, away_clean_sheet = (
        calculate_clean_sheet_probabilities(
            distribution
        )
    )

    most_likely_scores = tuple(
        get_most_likely_scores(
            distribution=distribution,
            limit=score_limit,
        )
    )

    outcome_total = (
        distribution.home_win_probability
        + distribution.draw_probability
        + distribution.away_win_probability
    )

    if outcome_total <= 0.0:
        raise MatchPredictionServiceError(
            "A soma das probabilidades 1X2 deve ser superior a zero."
        )

    home_win_probability = (
        distribution.home_win_probability
        / outcome_total
    )
    draw_probability = (
        distribution.draw_probability
        / outcome_total
    )
    away_win_probability = (
        1.0
        - home_win_probability
        - draw_probability
    )

    prediction = MatchPrediction(
        home_team_id=final_home_team_id,
        home_team_name=str(
            home_row["team_name"]
        ),
        away_team_id=final_away_team_id,
        away_team_name=str(
            away_row["team_name"]
        ),
        league_id=league_id,
        league_name=league_name,
        season_label=season_label,
        model_version=final_model_version,
        expected_home_goals=round(
            expected_home_goals,
            6,
        ),
        expected_away_goals=round(
            expected_away_goals,
            6,
        ),
        expected_total_goals=round(
            expected_home_goals
            + expected_away_goals,
            6,
        ),
        home_win_probability=round(
            home_win_probability,
            12,
        ),
        draw_probability=round(
            draw_probability,
            12,
        ),
        away_win_probability=round(
            away_win_probability,
            12,
        ),
        over_15_probability=round(
            over_15,
            12,
        ),
        under_15_probability=round(
            under_15,
            12,
        ),
        over_25_probability=round(
            over_25,
            12,
        ),
        under_25_probability=round(
            under_25,
            12,
        ),
        over_35_probability=round(
            over_35,
            12,
        ),
        under_35_probability=round(
            under_35,
            12,
        ),
        both_teams_to_score_probability=round(
            both_teams_score,
            12,
        ),
        both_teams_not_to_score_probability=round(
            distribution.total_probability
            - both_teams_score,
            12,
        ),
        home_clean_sheet_probability=round(
            home_clean_sheet,
            12,
        ),
        away_clean_sheet_probability=round(
            away_clean_sheet,
            12,
        ),
        home_matchup_factor=round(
            home_matchup_factor,
            6,
        ),
        away_matchup_factor=round(
            away_matchup_factor,
            6,
        ),
        prediction_confidence=round(
            prediction_confidence,
            6,
        ),
        most_likely_scores=most_likely_scores,
    )

    validate_prediction(
        prediction=prediction,
        distribution=distribution,
    )

    logger.info(
        "Previsão calculada | %s vs %s | "
        "xG=%.3f-%.3f | casa=%.2f%% | "
        "empate=%.2f%% | fora=%.2f%%",
        prediction.home_team_id,
        prediction.away_team_id,
        prediction.expected_home_goals,
        prediction.expected_away_goals,
        prediction.home_win_probability * 100,
        prediction.draw_probability * 100,
        prediction.away_win_probability * 100,
    )

    return prediction


def load_team_rating(
    connection: sqlite3.Connection,
    team_id: str,
    season_label: str,
    model_version: str,
) -> dict[str, Any]:
    """
    Carrega o rating e a identificação de uma equipa.
    """

    row = connection.execute(
        """
        SELECT
            r.team_id,
            t.team_name,
            r.league_id,
            l.league_name,
            r.attack_rating,
            r.defence_rating,
            r.absolute_rating,
            r.rating_confidence
        FROM team_ratings r
        INNER JOIN teams t
            ON t.team_id = r.team_id
        INNER JOIN leagues l
            ON l.league_id = r.league_id
        WHERE r.team_id = ?
          AND r.season_label = ?
          AND r.model_version = ?
          AND t.active = 1
          AND l.active = 1
        """,
        (
            team_id,
            season_label,
            model_version,
        ),
    ).fetchone()

    if row is None:
        raise MatchPredictionServiceError(
            f"Não existe rating para a equipa {team_id}, "
            f"época {season_label} e modelo {model_version}."
        )

    return dict(row)


def load_played_league_matches(
    connection: sqlite3.Connection,
    league_id: str,
    season_label: str,
) -> list[dict[str, Any]]:
    """
    Carrega os jogos concluídos de uma liga.

    Se ainda não existirem resultados na época, a função
    devolve uma lista vazia e serão usadas médias fallback.
    """

    rows = connection.execute(
        """
        SELECT
            league_id,
            status,
            home_goals,
            away_goals
        FROM matches
        WHERE league_id = ?
          AND season_label = ?
          AND status IN ('PLAYED', 'AWARDED')
          AND home_goals IS NOT NULL
          AND away_goals IS NOT NULL
        ORDER BY match_date, match_id
        """,
        (
            league_id,
            season_label,
        ),
    ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def calculate_prediction_confidence(
    home_strength: TeamStrength,
    away_strength: TeamStrength,
    environment: LeagueGoalEnvironment,
) -> float:
    """
    Calcula a confiança global da previsão.

    A confiança base é a média das confianças dos ratings.

    Quando já existem jogos concluídos na liga, adiciona
    gradualmente até 10% de confiança contextual.
    """

    ratings_confidence = (
        home_strength.rating_confidence
        + away_strength.rating_confidence
    ) / 2.0

    if environment.matches_played <= 0:
        environment_factor = 0.90

    else:
        sample_progress = min(
            1.0,
            environment.matches_played / 100.0,
        )

        environment_factor = (
            0.90
            + sample_progress * 0.10
        )

    final_confidence = (
        ratings_confidence
        * environment_factor
    )

    return max(
        0.0,
        min(
            1.0,
            final_confidence,
        ),
    )


def validate_prediction(
    prediction: MatchPrediction,
    distribution: PoissonMatchDistribution,
) -> None:
    """
    Confirma a coerência das probabilidades calculadas.
    """

    outcome_total = (
        prediction.home_win_probability
        + prediction.draw_probability
        + prediction.away_win_probability
    )

    if abs(
        outcome_total
        - 1.0
    ) > 0.000001:
        raise MatchPredictionServiceError(
            "As probabilidades 1X2 não somam 1.0."
        )

    market_pairs = (
        (
            prediction.over_15_probability,
            prediction.under_15_probability,
            "1.5",
        ),
        (
            prediction.over_25_probability,
            prediction.under_25_probability,
            "2.5",
        ),
        (
            prediction.over_35_probability,
            prediction.under_35_probability,
            "3.5",
        ),
        (
            prediction.both_teams_to_score_probability,
            prediction.both_teams_not_to_score_probability,
            "BTTS",
        ),
    )

    for first, second, market_name in market_pairs:
        total = first + second

        if abs(
            total
            - distribution.total_probability
        ) > 0.000001:
            raise MatchPredictionServiceError(
                f"As probabilidades do mercado {market_name} "
                "não correspondem à probabilidade total."
            )

    probability_fields = (
        prediction.home_win_probability,
        prediction.draw_probability,
        prediction.away_win_probability,
        prediction.over_15_probability,
        prediction.under_15_probability,
        prediction.over_25_probability,
        prediction.under_25_probability,
        prediction.over_35_probability,
        prediction.under_35_probability,
        prediction.both_teams_to_score_probability,
        prediction.both_teams_not_to_score_probability,
        prediction.home_clean_sheet_probability,
        prediction.away_clean_sheet_probability,
        prediction.prediction_confidence,
    )

    for probability in probability_fields:
        if not 0.0 <= probability <= 1.0:
            raise MatchPredictionServiceError(
                "Foi encontrada uma probabilidade "
                "fora do intervalo 0–1."
            )

    if prediction.expected_home_goals <= 0:
        raise MatchPredictionServiceError(
            "expected_home_goals deve ser superior a zero."
        )

    if prediction.expected_away_goals <= 0:
        raise MatchPredictionServiceError(
            "expected_away_goals deve ser superior a zero."
        )

    if not prediction.most_likely_scores:
        raise MatchPredictionServiceError(
            "Não existem marcadores prováveis."
        )


def get_configured_model_version() -> str:
    """
    Obtém a versão ativa do modelo.
    """

    config = load_full_model_config()

    try:
        return str(
            config["version"]["model_version"]
        )

    except KeyError as exc:
        raise MatchPredictionServiceError(
            "Não foi possível obter "
            "version.model_version."
        ) from exc


def clean_required_text(
    value: Any,
    field_name: str,
) -> str:
    if value is None:
        raise MatchPredictionServiceError(
            f"{field_name} vazio."
        )

    cleaned = str(value).strip()

    if not cleaned:
        raise MatchPredictionServiceError(
            f"{field_name} vazio."
        )

    return cleaned
