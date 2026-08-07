# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.config.path_config import load_paths_config
from src.database.init_database import connect_database
from src.database.schema import create_schema
from src.importers.fixtures_importer import (
    import_fixtures,
    read_fixtures_from_excel,
    upsert_fixture,
)
from src.importers.performance_importer import (
    PerformanceImportError,
    import_performance,
    read_performance_from_excel,
)
from src.importers.teams_importer import (
    TeamImportError,
    import_teams,
    read_teams_from_excel,
)


VALID_DATASET_VERSION = "TEST_DATASET_4_TEAMS_VALID_V001"
INVALID_DATASET_VERSION = "TEST_DATASET_4_TEAMS_V001"


class TestImporterReaders(unittest.TestCase):
    """
    Testa a leitura dos ficheiros Excel sem alterar a SQLite.
    """

    @classmethod
    def setUpClass(cls) -> None:
        paths = load_paths_config()

        cls.valid_dataset = (
            paths["data"]["input"]
            / "TEST_DATASET_4_TEAMS_VALID.xlsx"
        )

        cls.invalid_dataset = (
            paths["data"]["input"]
            / "TEST_DATASET_4_TEAMS.xlsx"
        )

        if not cls.valid_dataset.exists():
            raise FileNotFoundError(
                f"Falta o dataset válido: {cls.valid_dataset}"
            )

        if not cls.invalid_dataset.exists():
            raise FileNotFoundError(
                f"Falta o dataset inválido: {cls.invalid_dataset}"
            )

    def test_read_four_valid_teams(self) -> None:
        records = read_teams_from_excel(
            self.valid_dataset
        )

        self.assertEqual(
            len(records),
            4,
        )

        team_ids = {
            record["team_id"]
            for _, record in records
        }

        self.assertEqual(
            team_ids,
            {
                "ENG1_VALID_01",
                "ENG1_VALID_02",
                "ENG1_VALID_03",
                "ENG1_VALID_04",
            },
        )

    def test_read_four_valid_performances(self) -> None:
        records = read_performance_from_excel(
            self.valid_dataset
        )

        self.assertEqual(
            len(records),
            4,
        )

    def test_read_four_valid_fixtures(self) -> None:
        records = read_fixtures_from_excel(
            self.valid_dataset
        )

        self.assertEqual(
            len(records),
            4,
        )

    def test_read_three_invalid_performances(self) -> None:
        records = read_performance_from_excel(
            self.invalid_dataset
        )

        self.assertEqual(
            len(records),
            3,
        )


class TestImportersWithTemporaryDatabase(unittest.TestCase):
    """
    Testa os importadores numa base SQLite temporária.

    A base de produção não é alterada.
    """

    @classmethod
    def setUpClass(cls) -> None:
        paths = load_paths_config()

        cls.valid_dataset = (
            paths["data"]["input"]
            / "TEST_DATASET_4_TEAMS_VALID.xlsx"
        )

        cls.invalid_dataset = (
            paths["data"]["input"]
            / "TEST_DATASET_4_TEAMS.xlsx"
        )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()

        self.database_path = (
            Path(self.temporary_directory.name)
            / "footwin_test.db"
        )

        self._create_temporary_database()
        self._insert_test_league()
        self._insert_dataset_versions()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_temporary_database(self) -> None:
        connection = sqlite3.connect(
            self.database_path
        )

        try:
            connection.row_factory = sqlite3.Row

            connection.execute(
                "PRAGMA foreign_keys = ON;"
            )

            create_schema(connection)
            connection.commit()

        finally:
            connection.close()

    def _insert_test_league(self) -> None:
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
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ENG1",
                        "Premier League",
                        "England",
                        "ENG",
                        "2026/27",
                        20,
                        38,
                        380,
                        1.00,
                        3,
                        0,
                        1,
                    ),
                )

        finally:
            connection.close()

    def _insert_dataset_versions(self) -> None:
        connection = connect_database(
            self.database_path
        )

        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO dataset_versions (
                        dataset_version,
                        season_label,
                        file_path,
                        checksum_sha256,
                        record_count,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        VALID_DATASET_VERSION,
                        "2026/27",
                        str(self.valid_dataset.resolve()),
                        "TEST_CHECKSUM_VALID",
                        18,
                        "PENDING",
                    ),
                )

                connection.execute(
                    """
                    INSERT INTO dataset_versions (
                        dataset_version,
                        season_label,
                        file_path,
                        checksum_sha256,
                        record_count,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        INVALID_DATASET_VERSION,
                        "2026/27",
                        str(self.invalid_dataset.resolve()),
                        "TEST_CHECKSUM_INVALID",
                        15,
                        "REJECTED",
                    ),
                )

        finally:
            connection.close()

    def test_import_four_valid_teams(self) -> None:
        result = import_teams(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        self.assertEqual(
            result.inserted,
            4,
        )

        self.assertEqual(
            result.errors,
            0,
        )

        connection = connect_database(
            self.database_path
        )

        try:
            total = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM teams
                """
            ).fetchone()["total"]

        finally:
            connection.close()

        self.assertEqual(
            total,
            4,
        )

    def test_team_import_is_idempotent(self) -> None:
        first_result = import_teams(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        second_result = import_teams(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        self.assertEqual(
            first_result.inserted,
            4,
        )

        self.assertEqual(
            second_result.inserted,
            0,
        )

        self.assertEqual(
            second_result.unchanged,
            4,
        )

    def test_import_four_valid_performances(self) -> None:
        self._import_valid_teams()

        result = import_performance(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        self.assertEqual(
            result.inserted,
            4,
        )

        self.assertEqual(
            result.errors,
            0,
        )

    def test_performance_import_is_idempotent(self) -> None:
        self._import_valid_teams()

        first_result = import_performance(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        second_result = import_performance(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        self.assertEqual(
            first_result.inserted,
            4,
        )

        self.assertEqual(
            second_result.inserted,
            0,
        )

        self.assertEqual(
            second_result.unchanged,
            4,
        )

    def test_invalid_performance_rolls_back_everything(self) -> None:
        self._insert_invalid_test_teams()

        with self.assertRaises(
            PerformanceImportError
        ):
            import_performance(
                dataset_path=self.invalid_dataset,
                dataset_version=INVALID_DATASET_VERSION,
                require_approved_dataset=False,
                database_path=self.database_path,
            )

        connection = connect_database(
            self.database_path
        )

        try:
            total = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM team_season_performance
                WHERE dataset_version = ?
                """,
                (INVALID_DATASET_VERSION,),
            ).fetchone()["total"]

        finally:
            connection.close()

        self.assertEqual(
            total,
            0,
        )

    def test_import_four_valid_fixtures(self) -> None:
        self._import_valid_teams()

        result = import_fixtures(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        self.assertEqual(
            result.inserted,
            4,
        )

        self.assertEqual(
            result.errors,
            0,
        )

    def test_fixture_import_is_idempotent(self) -> None:
        self._import_valid_teams()

        first_result = import_fixtures(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        second_result = import_fixtures(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        self.assertEqual(
            first_result.inserted,
            4,
        )

        self.assertEqual(
            second_result.inserted,
            0,
        )

        self.assertEqual(
            second_result.unchanged,
            4,
        )

    def test_fixture_upsert_preserves_played_result(self) -> None:
        self._import_valid_teams()

        import_fixtures(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

        connection = connect_database(
            self.database_path
        )

        try:
            existing = connection.execute(
                """
                SELECT *
                FROM matches
                ORDER BY match_id
                LIMIT 1
                """
            ).fetchone()

            self.assertIsNotNone(existing)

            match_id = existing["match_id"]

            with connection:
                connection.execute(
                    """
                    UPDATE matches
                    SET
                        status = 'PLAYED',
                        home_goals = 2,
                        away_goals = 1
                    WHERE match_id = ?
                    """,
                    (match_id,),
                )

            played = connection.execute(
                """
                SELECT *
                FROM matches
                WHERE match_id = ?
                """,
                (match_id,),
            ).fetchone()

            incoming_fixture = {
                "match_id": played["match_id"],
                "league_id": played["league_id"],
                "season_label": played["season_label"],
                "round_number": played["round_number"],
                "match_date": played["match_date"],
                "home_team_id": played["home_team_id"],
                "away_team_id": played["away_team_id"],
                "status": "SCHEDULED",
                "home_goals": None,
                "away_goals": None,
                "schedule_type": played["schedule_type"],
                "source_url": played["source_url"],
                "dataset_version": played["dataset_version"],
            }

            with connection:
                action = upsert_fixture(
                    connection=connection,
                    fixture=incoming_fixture,
                )

            preserved = connection.execute(
                """
                SELECT
                    status,
                    home_goals,
                    away_goals
                FROM matches
                WHERE match_id = ?
                """,
                (match_id,),
            ).fetchone()

        finally:
            connection.close()

        self.assertEqual(action, "UNCHANGED")
        self.assertEqual(preserved["status"], "PLAYED")
        self.assertEqual(preserved["home_goals"], 2)
        self.assertEqual(preserved["away_goals"], 1)

    def _import_valid_teams(self) -> None:
        import_teams(
            dataset_path=self.valid_dataset,
            dataset_version=VALID_DATASET_VERSION,
            require_approved_dataset=False,
            database_path=self.database_path,
        )

    def _insert_invalid_test_teams(self) -> None:
        connection = connect_database(
            self.database_path
        )

        teams = [
            (
                "ENG1_TEST_01",
                "Footwin Test City",
                "Test City",
                "footwin_test_city",
            ),
            (
                "ENG1_TEST_02",
                "Footwin Test United",
                "Test United",
                "footwin_test_united",
            ),
            (
                "ENG1_TEST_03",
                "Footwin Test Athletic",
                "Test Athletic",
                "footwin_test_athletic",
            ),
            (
                "ENG1_TEST_04",
                "Footwin Test Rovers",
                "Test Rovers",
                "footwin_test_rovers",
            ),
        ]

        try:
            with connection:
                for (
                    team_id,
                    team_name,
                    short_name,
                    normalized_name,
                ) in teams:
                    connection.execute(
                        """
                        INSERT INTO teams (
                            team_id,
                            team_name,
                            short_name,
                            normalized_name,
                            league_id,
                            country,
                            season_label,
                            promoted,
                            promotion_method,
                            previous_division,
                            active,
                            dataset_version
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            team_id,
                            team_name,
                            short_name,
                            normalized_name,
                            "ENG1",
                            "England",
                            "2026/27",
                            0,
                            None,
                            "ENG1",
                            1,
                            INVALID_DATASET_VERSION,
                        ),
                    )

        finally:
            connection.close()


class TestRejectedDatasetProtection(unittest.TestCase):
    """
    Confirma que um dataset rejeitado é bloqueado
    quando a aprovação é obrigatória.
    """

    @classmethod
    def setUpClass(cls) -> None:
        paths = load_paths_config()

        cls.invalid_dataset = (
            paths["data"]["input"]
            / "TEST_DATASET_4_TEAMS.xlsx"
        )

    def test_rejected_dataset_blocks_team_import(self) -> None:
        with self.assertRaises(
            TeamImportError
        ):
            import_teams(
                dataset_path=self.invalid_dataset,
                dataset_version=INVALID_DATASET_VERSION,
                require_approved_dataset=True,
            )


if __name__ == "__main__":
    unittest.main()
