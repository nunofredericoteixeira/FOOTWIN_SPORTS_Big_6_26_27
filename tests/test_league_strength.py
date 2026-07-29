# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from src.models.league_strength import (
    LeagueStrengthError,
    calculate_absolute_rating,
    calculate_league_adjusted_ratings,
)


class TestAbsoluteRating(unittest.TestCase):
    def test_neutral_rating_remains_neutral(self) -> None:
        self.assertEqual(
            calculate_absolute_rating(
                league_relative_rating=50,
                league_strength_factor=1.20,
            ),
            50.0,
        )

    def test_strong_league_increases_high_rating(self) -> None:
        self.assertEqual(
            calculate_absolute_rating(
                league_relative_rating=80,
                league_strength_factor=1.10,
            ),
            83.0,
        )

    def test_strong_league_decreases_low_rating(self) -> None:
        self.assertEqual(
            calculate_absolute_rating(
                league_relative_rating=20,
                league_strength_factor=1.10,
            ),
            17.0,
        )

    def test_weaker_league_brings_rating_towards_neutral(
        self,
    ) -> None:
        self.assertEqual(
            calculate_absolute_rating(
                league_relative_rating=80,
                league_strength_factor=0.90,
            ),
            77.0,
        )

    def test_rating_is_clamped_to_zero(self) -> None:
        self.assertEqual(
            calculate_absolute_rating(
                league_relative_rating=0,
                league_strength_factor=2.0,
            ),
            0.0,
        )

    def test_rating_is_clamped_to_one_hundred(self) -> None:
        self.assertEqual(
            calculate_absolute_rating(
                league_relative_rating=100,
                league_strength_factor=2.0,
            ),
            100.0,
        )

    def test_zero_factor_is_rejected(self) -> None:
        with self.assertRaises(
            LeagueStrengthError
        ):
            calculate_absolute_rating(
                league_relative_rating=80,
                league_strength_factor=0,
            )


class TestLeagueAdjustedRatings(unittest.TestCase):
    def test_adjusts_and_orders_teams(self) -> None:
        ratings = [
            {
                "team_id": "ENG_TEAM",
                "league_id": "ENG1",
                "league_relative_rating": 80,
            },
            {
                "team_id": "POR_TEAM",
                "league_id": "POR1",
                "league_relative_rating": 80,
            },
        ]

        results = calculate_league_adjusted_ratings(
            ratings=ratings,
            league_factors={
                "ENG1": 1.10,
                "POR1": 0.90,
            },
        )

        self.assertEqual(
            results[0].team_id,
            "ENG_TEAM",
        )

        self.assertEqual(
            results[0].absolute_rating,
            83.0,
        )

        self.assertEqual(
            results[1].absolute_rating,
            77.0,
        )

    def test_missing_league_factor_is_rejected(self) -> None:
        with self.assertRaises(
            LeagueStrengthError
        ):
            calculate_league_adjusted_ratings(
                ratings=[
                    {
                        "team_id": "TEAM_01",
                        "league_id": "ENG1",
                        "league_relative_rating": 80,
                    }
                ],
                league_factors={},
            )

    def test_duplicate_team_is_rejected(self) -> None:
        with self.assertRaises(
            LeagueStrengthError
        ):
            calculate_league_adjusted_ratings(
                ratings=[
                    {
                        "team_id": "TEAM_01",
                        "league_id": "ENG1",
                        "league_relative_rating": 80,
                    },
                    {
                        "team_id": "TEAM_01",
                        "league_id": "ENG1",
                        "league_relative_rating": 70,
                    },
                ],
                league_factors={
                    "ENG1": 1.10,
                },
            )


if __name__ == "__main__":
    unittest.main()
