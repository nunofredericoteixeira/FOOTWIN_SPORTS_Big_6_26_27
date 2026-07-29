# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from src.models.league_goal_environment import (
    calculate_league_goal_environment,
)
from src.models.match_prediction_service import (
    MatchPredictionServiceError,
    calculate_prediction_confidence,
    clean_required_text,
)
from src.models.team_strength import (
    calculate_team_strength,
)


class TestPredictionConfidence(unittest.TestCase):
    def setUp(self) -> None:
        self.home_strength = calculate_team_strength(
            {
                "team_id": "HOME",
                "league_id": "ENG1",
                "attack_rating": 80,
                "defence_rating": 70,
                "absolute_rating": 75,
                "rating_confidence": 1.0,
            }
        )

        self.away_strength = calculate_team_strength(
            {
                "team_id": "AWAY",
                "league_id": "ENG1",
                "attack_rating": 60,
                "defence_rating": 55,
                "absolute_rating": 58,
                "rating_confidence": 0.8,
            }
        )

    def test_confidence_without_played_matches(self) -> None:
        environment = calculate_league_goal_environment(
            league_id="ENG1",
            matches=[],
        )

        confidence = calculate_prediction_confidence(
            home_strength=self.home_strength,
            away_strength=self.away_strength,
            environment=environment,
        )

        expected = (
            ((1.0 + 0.8) / 2.0)
            * 0.90
        )

        self.assertAlmostEqual(
            confidence,
            expected,
            places=6,
        )

    def test_confidence_increases_with_sample(self) -> None:
        matches = [
            {
                "league_id": "ENG1",
                "status": "PLAYED",
                "home_goals": 2,
                "away_goals": 1,
            }
            for _ in range(100)
        ]

        environment = calculate_league_goal_environment(
            league_id="ENG1",
            matches=matches,
        )

        confidence = calculate_prediction_confidence(
            home_strength=self.home_strength,
            away_strength=self.away_strength,
            environment=environment,
        )

        expected = (
            (1.0 + 0.8) / 2.0
        )

        self.assertAlmostEqual(
            confidence,
            expected,
            places=6,
        )

    def test_confidence_stays_between_zero_and_one(
        self,
    ) -> None:
        environment = calculate_league_goal_environment(
            league_id="ENG1",
            matches=[],
        )

        confidence = calculate_prediction_confidence(
            home_strength=self.home_strength,
            away_strength=self.away_strength,
            environment=environment,
        )

        self.assertGreaterEqual(
            confidence,
            0.0,
        )

        self.assertLessEqual(
            confidence,
            1.0,
        )


class TestRequiredText(unittest.TestCase):
    def test_valid_text(self) -> None:
        self.assertEqual(
            clean_required_text(
                " ENG1_VALID_01 ",
                "team_id",
            ),
            "ENG1_VALID_01",
        )

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(
            MatchPredictionServiceError
        ):
            clean_required_text(
                "",
                "team_id",
            )

    def test_none_is_rejected(self) -> None:
        with self.assertRaises(
            MatchPredictionServiceError
        ):
            clean_required_text(
                None,
                "team_id",
            )


if __name__ == "__main__":
    unittest.main()
