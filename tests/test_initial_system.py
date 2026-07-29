# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from pathlib import Path

from src.config.league_config import get_active_leagues
from src.config.model_config import load_full_model_config
from src.config.path_config import load_paths_config
from src.database.init_database import (
    get_database_path,
    list_database_tables,
    run_integrity_check,
)
from src.importers.teams_importer import normalize_team_name


class TestPathConfiguration(unittest.TestCase):
    def test_project_root_exists(self) -> None:
        paths = load_paths_config()
        project_root: Path = paths["project_root"]

        self.assertTrue(project_root.exists())
        self.assertTrue(project_root.is_dir())

    def test_database_path_is_inside_project(self) -> None:
        paths = load_paths_config()
        project_root: Path = paths["project_root"]
        database_path: Path = paths["database"]["main"]

        self.assertEqual(
            database_path.parent,
            project_root / "database",
        )

        self.assertEqual(
            database_path.name,
            "footwin_sports.db",
        )


class TestLeagueConfiguration(unittest.TestCase):
    def test_six_active_leagues(self) -> None:
        leagues = get_active_leagues()

        self.assertEqual(len(leagues), 6)

    def test_total_teams(self) -> None:
        leagues = get_active_leagues()

        total_teams = sum(
            int(league["team_count"])
            for league in leagues.values()
        )

        self.assertEqual(total_teams, 114)

    def test_total_matches(self) -> None:
        leagues = get_active_leagues()

        total_matches = sum(
            int(league["total_matches"])
            for league in leagues.values()
        )

        self.assertEqual(total_matches, 2058)

    def test_round_robin_calculation(self) -> None:
        leagues = get_active_leagues()

        for league_id, league in leagues.items():
            team_count = int(league["team_count"])

            expected_matches_per_team = (
                2 * (team_count - 1)
            )

            expected_total_matches = (
                team_count * (team_count - 1)
            )

            with self.subTest(league_id=league_id):
                self.assertEqual(
                    int(league["matches_per_team"]),
                    expected_matches_per_team,
                )

                self.assertEqual(
                    int(league["total_matches"]),
                    expected_total_matches,
                )


class TestModelConfiguration(unittest.TestCase):
    def test_model_version(self) -> None:
        config = load_full_model_config()

        self.assertEqual(
            config["version"]["model_version"],
            "MODEL_0_1",
        )

    def test_season_label(self) -> None:
        config = load_full_model_config()

        self.assertEqual(
            config["version"]["season_label"],
            "2026/27",
        )

    def test_performance_weights_sum_one(self) -> None:
        config = load_full_model_config()

        performance = config["weights"]["performance"]

        total = (
            float(performance["ppg_weight"])
            + float(performance["attack_weight"])
            + float(performance["defence_weight"])
            + float(
                performance["goal_difference_weight"]
            )
        )

        self.assertAlmostEqual(
            total,
            1.0,
            places=6,
        )

    def test_home_and_away_shares_sum_one(self) -> None:
        config = load_full_model_config()

        home_advantage = config["weights"][
            "home_advantage"
        ]

        total = (
            float(home_advantage["home_goal_share"])
            + float(home_advantage["away_goal_share"])
        )

        self.assertAlmostEqual(
            total,
            1.0,
            places=6,
        )


class TestDatabase(unittest.TestCase):
    def test_database_exists(self) -> None:
        database_path = get_database_path()

        self.assertTrue(database_path.exists())
        self.assertTrue(database_path.is_file())

    def test_database_integrity(self) -> None:
        self.assertEqual(
            run_integrity_check(),
            "ok",
        )

    def test_expected_tables_exist(self) -> None:
        expected_tables = {
            "schema_migrations",
            "dataset_versions",
            "leagues",
            "teams",
            "team_season_performance",
            "team_ratings",
            "matches",
            "match_predictions",
            "league_simulations",
            "league_simulation_results",
            "position_probabilities",
            "execution_runs",
            "validation_issues",
        }

        existing_tables = set(
            list_database_tables()
        )

        self.assertTrue(
            expected_tables.issubset(existing_tables)
        )


class TestTeamNameNormalization(unittest.TestCase):
    def test_normalize_name_with_accents(self) -> None:
        self.assertEqual(
            normalize_team_name("Vitória SC"),
            "vitoria_sc",
        )

    def test_normalize_name_with_spaces(self) -> None:
        self.assertEqual(
            normalize_team_name("Manchester United"),
            "manchester_united",
        )

    def test_normalize_name_with_symbols(self) -> None:
        self.assertEqual(
            normalize_team_name("Paris Saint-Germain FC"),
            "paris_saint_germain_fc",
        )

    def test_normalize_name_trims_underscores(self) -> None:
        self.assertEqual(
            normalize_team_name("  FC Porto  "),
            "fc_porto",
        )


if __name__ == "__main__":
    unittest.main()
