# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from src.models.league_goal_environment import (
    LeagueGoalEnvironmentError,
    build_default_league_environments,
    calculate_expected_goals_base,
    calculate_home_advantage_factors,
    calculate_league_goal_environment,
)


class TestHomeAdvantage(unittest.TestCase):
    def test_equal_averages_have_no_advantage(self) -> None:
        home_factor, away_factor = (
            calculate_home_advantage_factors(
                home_goals_average=1.40,
                away_goals_average=1.40,
            )
        )

        self.assertEqual(
            home_factor,
            1.0,
        )

        self.assertEqual(
            away_factor,
            1.0,
        )

    def test_home_average_creates_home_advantage(self) -> None:
        home_factor, away_factor = (
            calculate_home_advantage_factors(
                home_goals_average=1.60,
                away_goals_average=1.20,
            )
        )

        self.assertGreater(
            home_factor,
            1.0,
        )

        self.assertLess(
            away_factor,
            1.0,
        )

    def test_invalid_average_is_rejected(self) -> None:
        with self.assertRaises(
            LeagueGoalEnvironmentError
        ):
            calculate_home_advantage_factors(
                home_goals_average=0,
                away_goals_average=1.20,
            )


class TestLeagueGoalEnvironment(unittest.TestCase):
    def test_fallback_environment(self) -> None:
        environment = (
            calculate_league_goal_environment(
                league_id="ENG1",
                matches=[],
                fallback_home_average=1.55,
                fallback_away_average=1.25,
            )
        )

        self.assertEqual(
            environment.matches_played,
            0,
        )

        self.assertEqual(
            environment.home_goals_average,
            1.55,
        )

        self.assertEqual(
            environment.away_goals_average,
            1.25,
        )

        self.assertEqual(
            environment.total_goals_average,
            2.80,
        )

    def test_calculates_played_match_averages(self) -> None:
        matches = [
            {
                "league_id": "ENG1",
                "status": "PLAYED",
                "home_goals": 2,
                "away_goals": 1,
            },
            {
                "league_id": "ENG1",
                "status": "PLAYED",
                "home_goals": 1,
                "away_goals": 1,
            },
            {
                "league_id": "ENG1",
                "status": "SCHEDULED",
                "home_goals": None,
                "away_goals": None,
            },
        ]

        environment = (
            calculate_league_goal_environment(
                league_id="ENG1",
                matches=matches,
            )
        )

        self.assertEqual(
            environment.matches_played,
            2,
        )

        self.assertEqual(
            environment.total_home_goals,
            3,
        )

        self.assertEqual(
            environment.total_away_goals,
            2,
        )

        self.assertEqual(
            environment.home_goals_average,
            1.5,
        )

        self.assertEqual(
            environment.away_goals_average,
            1.0,
        )

    def test_different_league_match_is_rejected(self) -> None:
        matches = [
            {
                "league_id": "POR1",
                "status": "PLAYED",
                "home_goals": 2,
                "away_goals": 1,
            }
        ]

        with self.assertRaises(
            LeagueGoalEnvironmentError
        ):
            calculate_league_goal_environment(
                league_id="ENG1",
                matches=matches,
            )


class TestExpectedGoalsBase(unittest.TestCase):
    def test_expected_goals_with_neutral_matchup(self) -> None:
        environment = (
            calculate_league_goal_environment(
                league_id="ENG1",
                matches=[],
                fallback_home_average=1.55,
                fallback_away_average=1.25,
            )
        )

        home_xg, away_xg = (
            calculate_expected_goals_base(
                environment=environment,
                home_matchup_factor=1.0,
                away_matchup_factor=1.0,
            )
        )

        self.assertEqual(
            home_xg,
            1.55,
        )

        self.assertEqual(
            away_xg,
            1.25,
        )

    def test_stronger_home_matchup_increases_home_goals(
        self,
    ) -> None:
        environment = (
            calculate_league_goal_environment(
                league_id="ENG1",
                matches=[],
            )
        )

        home_xg, away_xg = (
            calculate_expected_goals_base(
                environment=environment,
                home_matchup_factor=1.20,
                away_matchup_factor=0.80,
            )
        )

        self.assertGreater(
            home_xg,
            environment.home_goals_average,
        )

        self.assertLess(
            away_xg,
            environment.away_goals_average,
        )


class TestDefaultEnvironments(unittest.TestCase):
    def test_builds_six_unique_environments(self) -> None:
        environments = (
            build_default_league_environments(
                [
                    "ENG1",
                    "ESP1",
                    "ITA1",
                    "GER1",
                    "FRA1",
                    "POR1",
                ]
            )
        )

        self.assertEqual(
            len(environments),
            6,
        )

        self.assertIn(
            "ENG1",
            environments,
        )

    def test_duplicate_league_is_rejected(self) -> None:
        with self.assertRaises(
            LeagueGoalEnvironmentError
        ):
            build_default_league_environments(
                [
                    "ENG1",
                    "ENG1",
                ]
            )


if __name__ == "__main__":
    unittest.main()
