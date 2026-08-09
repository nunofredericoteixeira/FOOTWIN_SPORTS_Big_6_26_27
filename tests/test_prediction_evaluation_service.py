# -*- coding: utf-8 -*-

from __future__ import annotations

import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from migrate_model_learning_infrastructure import (
    MIGRATION_SQL,
)
from src.database.init_database import connect_database
from src.database.schema import create_schema
from src.services.prediction_evaluation_service import (
    calculate_brier_score,
    calculate_log_loss,
    determine_outcome,
    determine_predicted_outcome,
    determine_prudent_prediction,
    parse_score,
    run_prediction_evaluation,
)


class TestPredictionEvaluationMetrics(unittest.TestCase):
    def test_determine_outcome(self) -> None:
        self.assertEqual(determine_outcome(2, 1), "1")
        self.assertEqual(determine_outcome(1, 1), "X")
        self.assertEqual(determine_outcome(0, 2), "2")

    def test_predicted_outcome_uses_highest_probability(
        self,
    ) -> None:
        self.assertEqual(
            determine_predicted_outcome(
                0.20,
                0.30,
                0.50,
            ),
            "2",
        )

    def test_predicted_outcome_tie_is_deterministic(
        self,
    ) -> None:
        self.assertEqual(
            determine_predicted_outcome(
                0.40,
                0.40,
                0.20,
            ),
            "1",
        )

    def test_prudent_prediction_uses_double_chance(
        self,
    ) -> None:
        self.assertEqual(
            determine_prudent_prediction(
                0.334562,
                0.270783,
                0.394655,
                "1-1",
            ),
            "X2",
        )

    def test_prudent_prediction_includes_score_outcome(
        self,
    ) -> None:
        self.assertEqual(
            determine_prudent_prediction(
                0.60,
                0.25,
                0.15,
                "1-1",
            ),
            "1X",
        )

    def test_brier_score(self) -> None:
        score = calculate_brier_score(
            0.50,
            0.30,
            0.20,
            "1",
        )

        self.assertAlmostEqual(
            score,
            0.38,
            places=12,
        )

    def test_log_loss(self) -> None:
        score = calculate_log_loss(
            0.50,
            0.30,
            0.20,
            "X",
        )

        self.assertAlmostEqual(
            score,
            -math.log(0.30),
            places=12,
        )

    def test_parse_score(self) -> None:
        self.assertEqual(
            parse_score(" 2-1 "),
            (2, 1),
        )

        self.assertEqual(
            parse_score("0:0"),
            (0, 0),
        )

        self.assertIsNone(
            parse_score("resultado indisponível")
        )


class TestPredictionEvaluationDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )

        self.database_path = (
            Path(self.temporary_directory.name)
            / "footwin_test.db"
        )

        self._create_database()
        self._insert_reference_data()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_database(self) -> None:
        connection = sqlite3.connect(
            self.database_path
        )

        try:
            connection.execute(
                "PRAGMA foreign_keys = ON;"
            )

            create_schema(connection)
            connection.executescript(MIGRATION_SQL)
            connection.execute(
                """
                ALTER TABLE prediction_evaluations
                ADD COLUMN prudent_prediction TEXT
                CHECK (
                    prudent_prediction IS NULL
                    OR prudent_prediction IN (
                        '1', 'X', '2', '1X', '12', 'X2'
                    )
                )
                """
            )
            connection.execute(
                """
                ALTER TABLE prediction_evaluations
                ADD COLUMN prudent_outcome_hit INTEGER
                CHECK (
                    prudent_outcome_hit IS NULL
                    OR prudent_outcome_hit IN (0, 1)
                )
                """
            )
            connection.commit()

        finally:
            connection.close()

    def _insert_reference_data(self) -> None:
        connection = connect_database(
            self.database_path
        )

        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO leagues (
                        league_id,
                        league_name,
                        country,
                        country_code,
                        season_label,
                        team_count,
                        matches_per_team,
                        total_matches,
                        league_strength_factor,
                        relegation_places,
                        playoff_places,
                        active
                    )
                    VALUES (
                        'POR1',
                        'Liga Portugal',
                        'Portugal',
                        'POR',
                        '2026/27',
                        18,
                        34,
                        306,
                        1.0,
                        2,
                        1,
                        1
                    )
                    """
                )

                connection.executemany(
                    """
                    INSERT INTO teams (
                        team_id,
                        league_id,
                        team_name,
                        short_name,
                        normalized_name,
                        country,
                        season_label,
                        promoted,
                        previous_division,
                        active
                    )
                    VALUES (
                        ?,
                        'POR1',
                        ?,
                        ?,
                        ?,
                        'Portugal',
                        '2026/27',
                        0,
                        'POR1',
                        1
                    )
                    """,
                    (
                        (
                            "HOME",
                            "Home Team",
                            "HOME",
                            "home team",
                        ),
                        (
                            "AWAY",
                            "Away Team",
                            "AWAY",
                            "away team",
                        ),
                    ),
                )

                connection.execute(
                    """
                    INSERT INTO model_versions (
                        model_version,
                        season_label,
                        version_status,
                        parameter_hash,
                        parameters_json
                    )
                    VALUES (
                        'MODEL_TEST',
                        '2026/27',
                        'ACTIVE',
                        'hash-model-test',
                        '{}'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO matches (
                        match_id,
                        league_id,
                        season_label,
                        round_number,
                        match_date,
                        home_team_id,
                        away_team_id,
                        status,
                        home_goals,
                        away_goals,
                        schedule_type
                    )
                    VALUES (
                        'MATCH_001',
                        'POR1',
                        '2026/27',
                        1,
                        '2026-08-09T12:00:00+00:00',
                        'HOME',
                        'AWAY',
                        'PLAYED',
                        1,
                        0,
                        'OFFICIAL'
                    )
                    """
                )

                self._insert_prediction(
                    connection,
                    prediction_id=(
                        "MATCH_001__MODEL_TEST"
                    ),
                    prediction_stage="PRE_MATCH",
                    prediction_version=1,
                    is_current=1,
                    home_probability=0.60,
                    draw_probability=0.25,
                    away_probability=0.15,
                    most_likely_score="1-0",
                )

                self._insert_prediction(
                    connection,
                    prediction_id=(
                        "MATCH_001__MODEL_TEST__"
                        "CONFIRMED_LINEUP__V001"
                    ),
                    prediction_stage=(
                        "CONFIRMED_LINEUP"
                    ),
                    prediction_version=1,
                    is_current=0,
                    home_probability=0.40,
                    draw_probability=0.30,
                    away_probability=0.30,
                    most_likely_score="1-1",
                )

                self._insert_prediction(
                    connection,
                    prediction_id=(
                        "MATCH_001__MODEL_TEST__"
                        "CONFIRMED_LINEUP__V002"
                    ),
                    prediction_stage=(
                        "CONFIRMED_LINEUP"
                    ),
                    prediction_version=2,
                    is_current=1,
                    home_probability=0.55,
                    draw_probability=0.30,
                    away_probability=0.15,
                    most_likely_score="1-0",
                )

        finally:
            connection.close()

    def _insert_prediction(
        self,
        connection: sqlite3.Connection,
        *,
        prediction_id: str,
        prediction_stage: str,
        prediction_version: int,
        is_current: int,
        home_probability: float,
        draw_probability: float,
        away_probability: float,
        most_likely_score: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO match_predictions (
                prediction_id,
                match_id,
                model_version,
                prediction_timestamp,
                lambda_home,
                lambda_away,
                home_win_probability,
                draw_probability,
                away_win_probability,
                most_likely_score,
                data_confidence,
                prediction_stage,
                prediction_version,
                lineup_confirmed,
                lineup_data_quality,
                is_current
            )
            VALUES (
                ?,
                'MATCH_001',
                'MODEL_TEST',
                '2026-08-09T10:00:00+00:00',
                1.50,
                0.80,
                ?,
                ?,
                ?,
                ?,
                1.0,
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                prediction_id,
                home_probability,
                draw_probability,
                away_probability,
                most_likely_score,
                prediction_stage,
                prediction_version,
                int(
                    prediction_stage
                    == "CONFIRMED_LINEUP"
                ),
                (
                    "COMPLETE"
                    if prediction_stage
                    == "CONFIRMED_LINEUP"
                    else "NOT_APPLICABLE"
                ),
                is_current,
            ),
        )

    def test_run_prefers_current_confirmed_lineup(
        self,
    ) -> None:
        summary = run_prediction_evaluation(
            database_path=self.database_path,
        )

        self.assertEqual(
            summary.eligible_predictions,
            1,
        )

        self.assertEqual(
            summary.inserted_evaluations,
            1,
        )

        connection = connect_database(
            self.database_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    prediction_id,
                    prediction_stage,
                    actual_outcome,
                    predicted_outcome,
                    outcome_hit,
                    prudent_prediction,
                    prudent_outcome_hit,
                    exact_score_hit
                FROM prediction_evaluations
                """
            ).fetchone()

            self.assertIsNotNone(row)

            self.assertEqual(
                row["prediction_id"],
                (
                    "MATCH_001__MODEL_TEST__"
                    "CONFIRMED_LINEUP__V002"
                ),
            )

            self.assertEqual(
                row["prediction_stage"],
                "CONFIRMED_LINEUP",
            )

            self.assertEqual(
                row["actual_outcome"],
                "1",
            )

            self.assertEqual(
                row["predicted_outcome"],
                "1",
            )

            self.assertEqual(
                row["outcome_hit"],
                1,
            )

            self.assertEqual(
                row["prudent_prediction"],
                "1",
            )

            self.assertEqual(
                row["prudent_outcome_hit"],
                1,
            )

            self.assertEqual(
                row["exact_score_hit"],
                1,
            )

        finally:
            connection.close()

    def test_existing_evaluation_gets_prudent_backfill(
        self,
    ) -> None:
        first_summary = run_prediction_evaluation(
            database_path=self.database_path,
        )

        connection = connect_database(
            self.database_path
        )

        try:
            with connection:
                connection.execute(
                    """
                    UPDATE prediction_evaluations
                    SET
                        prudent_prediction = NULL,
                        prudent_outcome_hit = NULL
                    """
                )
        finally:
            connection.close()

        second_summary = run_prediction_evaluation(
            database_path=self.database_path,
        )

        self.assertEqual(
            first_summary.inserted_evaluations,
            1,
        )

        self.assertEqual(
            second_summary.inserted_evaluations,
            0,
        )

        self.assertEqual(
            second_summary.existing_evaluations,
            1,
        )

        connection = connect_database(
            self.database_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    prudent_prediction,
                    prudent_outcome_hit
                FROM prediction_evaluations
                """
            ).fetchone()

            self.assertEqual(
                row["prudent_prediction"],
                "1",
            )

            self.assertEqual(
                row["prudent_outcome_hit"],
                1,
            )

        finally:
            connection.close()

    def test_run_is_idempotent(self) -> None:
        first_summary = run_prediction_evaluation(
            database_path=self.database_path,
        )

        second_summary = run_prediction_evaluation(
            database_path=self.database_path,
        )

        self.assertEqual(
            first_summary.inserted_evaluations,
            1,
        )

        self.assertEqual(
            second_summary.inserted_evaluations,
            0,
        )

        self.assertEqual(
            second_summary.existing_evaluations,
            1,
        )

        connection = connect_database(
            self.database_path
        )

        try:
            count = connection.execute(
                """
                SELECT COUNT(*)
                FROM prediction_evaluations
                """
            ).fetchone()[0]

            self.assertEqual(count, 1)

        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
