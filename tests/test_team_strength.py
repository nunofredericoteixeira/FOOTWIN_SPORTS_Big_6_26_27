# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from src.models.team_strength import (
    TeamStrengthError,
    calculate_matchup_factors,
    calculate_team_strength,
    calculate_team_strengths,
    rating_to_strength,
)


class TestRatingToStrength(unittest.TestCase):
    def test_neutral_rating(self) -> None:
        self.assertEqual(
            rating_to_strength(50),
            1.0,
        )

    def test_maximum_rating(self) -> None:
        self.assertEqual(
            rating_to_strength(100),
            1.4,
        )

    def test_minimum_rating(self) -> None:
        self.assertEqual(
            rating_to_strength(0),
            0.6,
        )

    def test_rating_above_neutral(self) -> None:
        self.assertEqual(
            rating_to_strength(75),
            1.2,
        )

    def test_rating_below_neutral(self) -> None:
        self.assertEqual(
            rating_to_strength(25),
            0.8,
        )

    def test_invalid_rating_is_rejected(self) -> None:
        with self.assertRaises(
            TeamStrengthError
        ):
            rating_to_strength(101)


class TestTeamStrengthCalculation(unittest.TestCase):
    def setUp(self) -> None:
        self.home_record = {
            "team_id": "TEAM_HOME",
            "league_id": "ENG1",
            "attack_rating": 80,
            "defence_rating": 70,
            "absolute_rating": 75,
            "rating_confidence": 1.0,
        }

        self.away_record = {
            "team_id": "TEAM_AWAY",
            "league_id": "ENG1",
            "attack_rating": 60,
            "defence_rating": 50,
            "absolute_rating": 55,
            "rating_confidence": 0.9,
        }

    def test_calculate_team_strength(self) -> None:
        result = calculate_team_strength(
            self.home_record
        )

        self.assertEqual(
            result.team_id,
            "TEAM_HOME",
        )

        self.assertGreater(
            result.attack_strength,
            1.0,
        )

        self.assertGreater(
            result.defence_strength,
            1.0,
        )

    def test_calculate_multiple_strengths(self) -> None:
        results = calculate_team_strengths(
            [
                self.away_record,
                self.home_record,
            ]
        )

        self.assertEqual(
            len(results),
            2,
        )

        self.assertEqual(
            results[0].team_id,
            "TEAM_HOME",
        )

    def test_duplicate_team_is_rejected(self) -> None:
        with self.assertRaises(
            TeamStrengthError
        ):
            calculate_team_strengths(
                [
                    self.home_record,
                    self.home_record,
                ]
            )

    def test_matchup_factors(self) -> None:
        home = calculate_team_strength(
            self.home_record
        )

        away = calculate_team_strength(
            self.away_record
        )

        home_factor, away_factor = (
            calculate_matchup_factors(
                home_team=home,
                away_team=away,
            )
        )

        self.assertGreater(
            home_factor,
            away_factor,
        )

        self.assertGreater(
            home_factor,
            1.0,
        )

    def test_same_team_match_is_rejected(self) -> None:
        home = calculate_team_strength(
            self.home_record
        )

        with self.assertRaises(
            TeamStrengthError
        ):
            calculate_matchup_factors(
                home_team=home,
                away_team=home,
            )

    def test_different_leagues_are_rejected(self) -> None:
        home = calculate_team_strength(
            self.home_record
        )

        other_record = {
            **self.away_record,
            "league_id": "POR1",
        }

        away = calculate_team_strength(
            other_record
        )

        with self.assertRaises(
            TeamStrengthError
        ):
            calculate_matchup_factors(
                home_team=home,
                away_team=away,
            )


if __name__ == "__main__":
    unittest.main()
