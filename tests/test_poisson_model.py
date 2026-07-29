# -*- coding: utf-8 -*-

from __future__ import annotations

import math
import unittest

from src.models.poisson_model import (
    PoissonModelError,
    build_goal_probabilities,
    build_match_distribution,
    build_score_matrix,
    calculate_both_teams_to_score_probability,
    calculate_clean_sheet_probabilities,
    calculate_match_outcomes,
    calculate_over_probability,
    calculate_under_probability,
    get_most_likely_scores,
    get_score_probability,
    poisson_probability,
)


class TestPoissonProbability(unittest.TestCase):
    def test_zero_goals_probability(self) -> None:
        result = poisson_probability(
            expected_goals=1.5,
            goals=0,
        )

        self.assertAlmostEqual(
            result,
            math.exp(-1.5),
            places=12,
        )

    def test_one_goal_probability(self) -> None:
        result = poisson_probability(
            expected_goals=1.5,
            goals=1,
        )

        expected = (
            math.exp(-1.5)
            * 1.5
        )

        self.assertAlmostEqual(
            result,
            expected,
            places=12,
        )

    def test_negative_goals_are_rejected(self) -> None:
        with self.assertRaises(
            PoissonModelError
        ):
            poisson_probability(
                expected_goals=1.5,
                goals=-1,
            )

    def test_invalid_expected_goals_are_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            PoissonModelError
        ):
            poisson_probability(
                expected_goals=0,
                goals=1,
            )


class TestGoalProbabilities(unittest.TestCase):
    def test_builds_expected_number_of_values(self) -> None:
        probabilities = build_goal_probabilities(
            expected_goals=1.5,
            max_goals=10,
        )

        self.assertEqual(
            len(probabilities),
            11,
        )

    def test_probability_sum_is_close_to_one(self) -> None:
        probabilities = build_goal_probabilities(
            expected_goals=1.5,
            max_goals=15,
        )

        self.assertAlmostEqual(
            sum(probabilities),
            1.0,
            places=8,
        )


class TestScoreMatrix(unittest.TestCase):
    def test_matrix_dimensions(self) -> None:
        matrix = build_score_matrix(
            expected_home_goals=1.6,
            expected_away_goals=1.2,
            max_goals=10,
        )

        self.assertEqual(
            len(matrix),
            11,
        )

        self.assertEqual(
            len(matrix[0]),
            11,
        )

    def test_outcome_probabilities_sum_close_to_one(
        self,
    ) -> None:
        matrix = build_score_matrix(
            expected_home_goals=1.6,
            expected_away_goals=1.2,
            max_goals=15,
        )

        outcomes = calculate_match_outcomes(
            matrix
        )

        total = (
            outcomes.home_win
            + outcomes.draw
            + outcomes.away_win
        )

        self.assertAlmostEqual(
            total,
            1.0,
            places=8,
        )

    def test_home_advantage_increases_home_win(
        self,
    ) -> None:
        distribution = build_match_distribution(
            expected_home_goals=2.0,
            expected_away_goals=0.8,
            max_goals=12,
        )

        self.assertGreater(
            distribution.home_win_probability,
            distribution.away_win_probability,
        )


class TestMatchDistribution(unittest.TestCase):
    def setUp(self) -> None:
        self.distribution = build_match_distribution(
            expected_home_goals=1.6,
            expected_away_goals=1.2,
            max_goals=12,
        )

    def test_distribution_total_is_close_to_one(
        self,
    ) -> None:
        self.assertAlmostEqual(
            self.distribution.total_probability,
            1.0,
            places=7,
        )

    def test_outcomes_sum_close_to_total(self) -> None:
        total_outcomes = (
            self.distribution.home_win_probability
            + self.distribution.draw_probability
            + self.distribution.away_win_probability
        )

        self.assertAlmostEqual(
            total_outcomes,
            self.distribution.total_probability,
            places=9,
        )

    def test_score_probability(self) -> None:
        probability = get_score_probability(
            distribution=self.distribution,
            home_goals=1,
            away_goals=1,
        )

        expected = (
            poisson_probability(1.6, 1)
            * poisson_probability(1.2, 1)
        )

        self.assertAlmostEqual(
            probability,
            expected,
            places=12,
        )

    def test_most_likely_scores(self) -> None:
        scores = get_most_likely_scores(
            distribution=self.distribution,
            limit=5,
        )

        self.assertEqual(
            len(scores),
            5,
        )

        for previous, current in zip(
            scores,
            scores[1:],
        ):
            self.assertGreaterEqual(
                previous.probability,
                current.probability,
            )


class TestGoalMarkets(unittest.TestCase):
    def setUp(self) -> None:
        self.distribution = build_match_distribution(
            expected_home_goals=1.6,
            expected_away_goals=1.2,
            max_goals=15,
        )

    def test_over_and_under_sum_close_to_one(
        self,
    ) -> None:
        over = calculate_over_probability(
            self.distribution,
            2.5,
        )

        under = calculate_under_probability(
            self.distribution,
            2.5,
        )

        self.assertAlmostEqual(
            over + under,
            self.distribution.total_probability,
            places=8,
        )

    def test_both_teams_to_score_probability(
        self,
    ) -> None:
        probability = (
            calculate_both_teams_to_score_probability(
                self.distribution
            )
        )

        self.assertGreater(
            probability,
            0.0,
        )

        self.assertLess(
            probability,
            1.0,
        )

    def test_clean_sheet_probabilities(self) -> None:
        home_clean_sheet, away_clean_sheet = (
            calculate_clean_sheet_probabilities(
                self.distribution
            )
        )

        self.assertAlmostEqual(
            home_clean_sheet,
            math.exp(-1.2),
            places=7,
        )

        self.assertAlmostEqual(
            away_clean_sheet,
            math.exp(-1.6),
            places=7,
        )

    def test_invalid_goal_line_is_rejected(self) -> None:
        with self.assertRaises(
            PoissonModelError
        ):
            calculate_over_probability(
                self.distribution,
                2.3,
            )


if __name__ == "__main__":
    unittest.main()
