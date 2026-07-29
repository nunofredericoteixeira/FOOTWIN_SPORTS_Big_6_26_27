# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from src.models.performance_rating import (
    PerformanceRatingError,
    calculate_performance_ratings,
    min_max_rating,
    normalize_weights,
    prepare_raw_metrics,
    weighted_rating,
)


class TestMinMaxRating(unittest.TestCase):
    def test_higher_value_is_better(self) -> None:
        values = [1.0, 2.0, 3.0]

        self.assertEqual(
            min_max_rating(
                value=1.0,
                values=values,
                higher_is_better=True,
            ),
            0.0,
        )

        self.assertEqual(
            min_max_rating(
                value=3.0,
                values=values,
                higher_is_better=True,
            ),
            100.0,
        )

    def test_lower_value_is_better(self) -> None:
        values = [1.0, 2.0, 3.0]

        self.assertEqual(
            min_max_rating(
                value=1.0,
                values=values,
                higher_is_better=False,
            ),
            100.0,
        )

        self.assertEqual(
            min_max_rating(
                value=3.0,
                values=values,
                higher_is_better=False,
            ),
            0.0,
        )

    def test_equal_values_return_neutral_rating(self) -> None:
        self.assertEqual(
            min_max_rating(
                value=2.0,
                values=[2.0, 2.0, 2.0],
            ),
            50.0,
        )


class TestPerformanceMetrics(unittest.TestCase):
    def test_prepare_raw_metrics(self) -> None:
        metrics = prepare_raw_metrics(
            {
                "team_id": "TEAM_01",
                "played": 10,
                "points": 20,
                "goals_for": 25,
                "goals_against": 10,
                "goal_difference": 15,
            }
        )

        self.assertEqual(
            metrics.team_id,
            "TEAM_01",
        )

        self.assertAlmostEqual(
            metrics.points_per_game,
            2.0,
        )

        self.assertAlmostEqual(
            metrics.attack_per_game,
            2.5,
        )

        self.assertAlmostEqual(
            metrics.defence_conceded_per_game,
            1.0,
        )

        self.assertAlmostEqual(
            metrics.goal_difference_per_game,
            1.5,
        )

    def test_invalid_goal_difference_is_rejected(self) -> None:
        with self.assertRaises(
            PerformanceRatingError
        ):
            prepare_raw_metrics(
                {
                    "team_id": "TEAM_01",
                    "played": 10,
                    "points": 20,
                    "goals_for": 25,
                    "goals_against": 10,
                    "goal_difference": 10,
                }
            )

    def test_zero_played_is_rejected(self) -> None:
        with self.assertRaises(
            PerformanceRatingError
        ):
            prepare_raw_metrics(
                {
                    "team_id": "TEAM_01",
                    "played": 0,
                    "points": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                    "goal_difference": 0,
                }
            )


class TestWeights(unittest.TestCase):
    def test_weights_are_normalized(self) -> None:
        weights = normalize_weights(
            {
                "ppg_weight": 4,
                "attack_weight": 3,
                "defence_weight": 2,
                "goal_difference_weight": 1,
            }
        )

        self.assertAlmostEqual(
            sum(weights.values()),
            1.0,
        )

        self.assertAlmostEqual(
            weights["ppg_weight"],
            0.4,
        )

    def test_negative_weight_is_rejected(self) -> None:
        with self.assertRaises(
            PerformanceRatingError
        ):
            normalize_weights(
                {
                    "ppg_weight": 0.4,
                    "attack_weight": 0.3,
                    "defence_weight": -0.2,
                    "goal_difference_weight": 0.5,
                }
            )

    def test_weighted_rating(self) -> None:
        result = weighted_rating(
            ppg_rating=100,
            attack_rating=80,
            defence_rating=60,
            goal_difference_rating=40,
            weights={
                "ppg_weight": 0.4,
                "attack_weight": 0.3,
                "defence_weight": 0.2,
                "goal_difference_weight": 0.1,
            },
        )

        self.assertAlmostEqual(
            result,
            80.0,
        )


class TestPerformanceRatingCalculation(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            {
                "team_id": "TEAM_A",
                "played": 10,
                "points": 25,
                "goals_for": 30,
                "goals_against": 8,
                "goal_difference": 22,
            },
            {
                "team_id": "TEAM_B",
                "played": 10,
                "points": 18,
                "goals_for": 20,
                "goals_against": 15,
                "goal_difference": 5,
            },
            {
                "team_id": "TEAM_C",
                "played": 10,
                "points": 10,
                "goals_for": 10,
                "goals_against": 25,
                "goal_difference": -15,
            },
        ]

        self.weights = {
            "ppg_weight": 0.4,
            "attack_weight": 0.2,
            "defence_weight": 0.2,
            "goal_difference_weight": 0.2,
        }

    def test_calculates_three_ratings(self) -> None:
        ratings = calculate_performance_ratings(
            records=self.records,
            weights=self.weights,
        )

        self.assertEqual(
            len(ratings),
            3,
        )

    def test_best_team_is_first(self) -> None:
        ratings = calculate_performance_ratings(
            records=self.records,
            weights=self.weights,
        )

        self.assertEqual(
            ratings[0].team_id,
            "TEAM_A",
        )

        self.assertEqual(
            ratings[-1].team_id,
            "TEAM_C",
        )

    def test_all_ratings_are_between_zero_and_one_hundred(
        self,
    ) -> None:
        ratings = calculate_performance_ratings(
            records=self.records,
            weights=self.weights,
        )

        for rating in ratings:
            with self.subTest(
                team_id=rating.team_id
            ):
                self.assertGreaterEqual(
                    rating.final_rating,
                    0.0,
                )

                self.assertLessEqual(
                    rating.final_rating,
                    100.0,
                )

    def test_duplicate_team_is_rejected(self) -> None:
        duplicate_records = [
            self.records[0],
            self.records[0],
        ]

        with self.assertRaises(
            PerformanceRatingError
        ):
            calculate_performance_ratings(
                records=duplicate_records,
                weights=self.weights,
            )


if __name__ == "__main__":
    unittest.main()
