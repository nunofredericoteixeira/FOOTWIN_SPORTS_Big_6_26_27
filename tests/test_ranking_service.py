# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from src.models.ranking_service import (
    RankingServiceError,
    build_league_positions,
    get_rating_level,
    ranking_sort_key,
    validate_rating_rows,
)


class TestRatingLevels(unittest.TestCase):
    def test_elite(self) -> None:
        self.assertEqual(
            get_rating_level(90),
            "ELITE",
        )

    def test_muito_forte(self) -> None:
        self.assertEqual(
            get_rating_level(80),
            "MUITO_FORTE",
        )

    def test_forte(self) -> None:
        self.assertEqual(
            get_rating_level(70),
            "FORTE",
        )

    def test_medio(self) -> None:
        self.assertEqual(
            get_rating_level(50),
            "MEDIO",
        )

    def test_muito_fraco(self) -> None:
        self.assertEqual(
            get_rating_level(10),
            "MUITO_FRACO",
        )

    def test_invalid_rating_is_rejected(self) -> None:
        with self.assertRaises(
            RankingServiceError
        ):
            get_rating_level(101)


class TestRankingOrdering(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            {
                "team_id": "TEAM_B",
                "team_name": "Team B",
                "league_id": "ENG1",
                "absolute_rating": 80,
                "performance_rating": 75,
                "rating_confidence": 1.0,
            },
            {
                "team_id": "TEAM_A",
                "team_name": "Team A",
                "league_id": "ENG1",
                "absolute_rating": 90,
                "performance_rating": 85,
                "rating_confidence": 1.0,
            },
            {
                "team_id": "TEAM_C",
                "team_name": "Team C",
                "league_id": "POR1",
                "absolute_rating": 70,
                "performance_rating": 80,
                "rating_confidence": 0.9,
            },
        ]

    def test_sorting_places_best_team_first(self) -> None:
        ordered = sorted(
            self.rows,
            key=ranking_sort_key,
        )

        self.assertEqual(
            ordered[0]["team_id"],
            "TEAM_A",
        )

        self.assertEqual(
            ordered[-1]["team_id"],
            "TEAM_C",
        )

    def test_league_positions(self) -> None:
        positions = build_league_positions(
            self.rows
        )

        self.assertEqual(
            positions["TEAM_A"],
            1,
        )

        self.assertEqual(
            positions["TEAM_B"],
            2,
        )

        self.assertEqual(
            positions["TEAM_C"],
            1,
        )


class TestRankingValidation(unittest.TestCase):
    def test_valid_rows(self) -> None:
        rows = [
            {
                "team_id": "TEAM_A",
                "absolute_rating": 80,
                "league_relative_rating": 75,
                "performance_rating": 75,
                "rating_confidence": 1.0,
            }
        ]

        validate_rating_rows(rows)

    def test_duplicate_team_is_rejected(self) -> None:
        rows = [
            {
                "team_id": "TEAM_A",
                "absolute_rating": 80,
                "league_relative_rating": 75,
                "performance_rating": 75,
                "rating_confidence": 1.0,
            },
            {
                "team_id": "TEAM_A",
                "absolute_rating": 70,
                "league_relative_rating": 65,
                "performance_rating": 65,
                "rating_confidence": 1.0,
            },
        ]

        with self.assertRaises(
            RankingServiceError
        ):
            validate_rating_rows(rows)

    def test_invalid_confidence_is_rejected(self) -> None:
        rows = [
            {
                "team_id": "TEAM_A",
                "absolute_rating": 80,
                "league_relative_rating": 75,
                "performance_rating": 75,
                "rating_confidence": 1.5,
            }
        ]

        with self.assertRaises(
            RankingServiceError
        ):
            validate_rating_rows(rows)


if __name__ == "__main__":
    unittest.main()
