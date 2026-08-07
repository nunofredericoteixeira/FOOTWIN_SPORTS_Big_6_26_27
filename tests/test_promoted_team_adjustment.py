# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from src.models.performance_rating import PerformanceRating
from src.models.promoted_team_adjustment import (
    PromotedTeamAdjustmentError,
    adjust_promoted_team_ratings,
    calculate_lower_table_reference,
)


class TestPromotedTeamAdjustment(unittest.TestCase):
    def setUp(self) -> None:
        self.ratings = [
            PerformanceRating(
                team_id="TEAM_A",
                points_per_game=2.4,
                attack_per_game=2.0,
                defence_conceded_per_game=0.8,
                goal_difference_per_game=1.2,
                ppg_rating=100.0,
                attack_rating=100.0,
                defence_rating=100.0,
                goal_difference_rating=100.0,
                final_rating=100.0,
            ),
            PerformanceRating(
                team_id="TEAM_B",
                points_per_game=1.8,
                attack_per_game=1.5,
                defence_conceded_per_game=1.1,
                goal_difference_per_game=0.4,
                ppg_rating=70.0,
                attack_rating=65.0,
                defence_rating=70.0,
                goal_difference_rating=65.0,
                final_rating=68.0,
            ),
            PerformanceRating(
                team_id="TEAM_C",
                points_per_game=1.1,
                attack_per_game=1.0,
                defence_conceded_per_game=1.6,
                goal_difference_per_game=-0.6,
                ppg_rating=25.0,
                attack_rating=20.0,
                defence_rating=25.0,
                goal_difference_rating=20.0,
                final_rating=23.0,
            ),
            PerformanceRating(
                team_id="TEAM_PROMOTED",
                points_per_game=2.1,
                attack_per_game=1.9,
                defence_conceded_per_game=0.9,
                goal_difference_per_game=1.0,
                ppg_rating=90.0,
                attack_rating=90.0,
                defence_rating=90.0,
                goal_difference_rating=90.0,
                final_rating=90.0,
            ),
        ]

        self.source_by_team = {
            "TEAM_A": {
                "promoted": 0,
                "promotion_method": None,
            },
            "TEAM_B": {
                "promoted": 0,
                "promotion_method": None,
            },
            "TEAM_C": {
                "promoted": 0,
                "promotion_method": None,
            },
            "TEAM_PROMOTED": {
                "promoted": 1,
                "promotion_method": "CHAMPION",
            },
        }

        self.promotion_config = {
            "general": {
                "champion_factor": 0.82,
                "direct_factor": 0.79,
                "playoff_factor": 0.75,
            },
            "attack": {
                "champion_factor": 0.84,
                "direct_factor": 0.81,
                "playoff_factor": 0.77,
            },
            "defence": {
                "champion_factor": 0.78,
                "direct_factor": 0.75,
                "playoff_factor": 0.71,
            },
            "first_division_regression_weight": 0.35,
            "lower_table_reference_percentage": 0.25,
        }

        self.performance_weights = {
            "ppg_weight": 0.45,
            "attack_weight": 0.20,
            "defence_weight": 0.20,
            "goal_difference_weight": 0.15,
        }

    def test_lower_table_reference_uses_bottom_quarter(
        self,
    ) -> None:
        reference = calculate_lower_table_reference(
            ratings=self.ratings[:3],
            reference_percentage=0.25,
        )

        self.assertEqual(
            reference["reference_count"],
            1.0,
        )

        self.assertEqual(
            reference["final_rating"],
            23.0,
        )

    def test_non_promoted_teams_remain_unchanged(
        self,
    ) -> None:
        adjusted = adjust_promoted_team_ratings(
            ratings=self.ratings,
            source_by_team=self.source_by_team,
            promotion_config=self.promotion_config,
            performance_weights=self.performance_weights,
        )

        adjusted_by_team = {
            item.team_id: item
            for item in adjusted
        }

        self.assertEqual(
            adjusted_by_team["TEAM_A"],
            self.ratings[0],
        )

        self.assertEqual(
            adjusted_by_team["TEAM_B"],
            self.ratings[1],
        )

        self.assertEqual(
            adjusted_by_team["TEAM_C"],
            self.ratings[2],
        )

    def test_promoted_team_rating_is_reduced(
        self,
    ) -> None:
        adjusted = adjust_promoted_team_ratings(
            ratings=self.ratings,
            source_by_team=self.source_by_team,
            promotion_config=self.promotion_config,
            performance_weights=self.performance_weights,
        )

        promoted = next(
            item
            for item in adjusted
            if item.team_id == "TEAM_PROMOTED"
        )

        self.assertLess(
            promoted.final_rating,
            90.0,
        )

        self.assertLess(
            promoted.attack_rating,
            90.0,
        )

        self.assertLess(
            promoted.defence_rating,
            90.0,
        )

    def test_playoff_factor_is_more_penalizing_than_champion(
        self,
    ) -> None:
        champion_adjusted = adjust_promoted_team_ratings(
            ratings=self.ratings,
            source_by_team=self.source_by_team,
            promotion_config=self.promotion_config,
            performance_weights=self.performance_weights,
        )

        playoff_sources = {
            team_id: dict(source)
            for team_id, source in self.source_by_team.items()
        }

        playoff_sources["TEAM_PROMOTED"][
            "promotion_method"
        ] = "PLAYOFF"

        playoff_adjusted = adjust_promoted_team_ratings(
            ratings=self.ratings,
            source_by_team=playoff_sources,
            promotion_config=self.promotion_config,
            performance_weights=self.performance_weights,
        )

        champion_rating = next(
            item.final_rating
            for item in champion_adjusted
            if item.team_id == "TEAM_PROMOTED"
        )

        playoff_rating = next(
            item.final_rating
            for item in playoff_adjusted
            if item.team_id == "TEAM_PROMOTED"
        )

        self.assertLess(
            playoff_rating,
            champion_rating,
        )

    def test_invalid_promotion_method_is_rejected(
        self,
    ) -> None:
        invalid_sources = {
            team_id: dict(source)
            for team_id, source in self.source_by_team.items()
        }

        invalid_sources["TEAM_PROMOTED"][
            "promotion_method"
        ] = "UNKNOWN"

        with self.assertRaises(
            PromotedTeamAdjustmentError
        ):
            adjust_promoted_team_ratings(
                ratings=self.ratings,
                source_by_team=invalid_sources,
                promotion_config=self.promotion_config,
                performance_weights=self.performance_weights,
            )


if __name__ == "__main__":
    unittest.main()
