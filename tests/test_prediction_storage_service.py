# -*- coding: utf-8 -*-

from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.models.prediction_storage_service import (
    upsert_prediction,
)
from src.services.league_model_learning_service import (
    evaluate_candidate_model,
)


class TestPreMatchFreeze(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )

        self.database_path = (
            Path(self.temporary_directory.name)
            / "footwin_test.db"
        )

        self.connection = sqlite3.connect(
            self.database_path
        )
        self.connection.row_factory = sqlite3.Row

        self.connection.execute(
            """
            CREATE TABLE match_predictions (
                prediction_id TEXT PRIMARY KEY,
                match_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prediction_stage TEXT NOT NULL,
                prediction_version INTEGER NOT NULL,
                is_current INTEGER NOT NULL,
                parent_prediction_id TEXT,
                superseded_at TEXT,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.connection.execute(
            """
            INSERT INTO match_predictions (
                prediction_id,
                match_id,
                model_version,
                prediction_stage,
                prediction_version,
                is_current
            )
            VALUES (
                'PUBLISHED_PRE_MATCH',
                'MATCH_001',
                'MODEL_0_1',
                'PRE_MATCH',
                1,
                1
            )
            """
        )

        self.connection.commit()

        self.available_columns = {
            "prediction_id",
            "match_id",
            "model_version",
            "prediction_stage",
            "prediction_version",
            "is_current",
            "parent_prediction_id",
            "superseded_at",
            "created_at",
        }

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary_directory.cleanup()

    def _record(
        self,
        *,
        model_version: str,
    ) -> dict[str, object]:
        return {
            "prediction_id": "IGNORED_BY_UPSERT",
            "match_id": "MATCH_001",
            "model_version": model_version,
            "prediction_stage": "PRE_MATCH",
            "prediction_version": 1,
            "is_current": 1,
        }

    def _current_pre_matches(
        self,
    ) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                prediction_id,
                model_version,
                prediction_version
            FROM match_predictions
            WHERE match_id = 'MATCH_001'
              AND prediction_stage = 'PRE_MATCH'
              AND is_current = 1
            ORDER BY model_version
            """
        ).fetchall()

    def test_pre_match_is_frozen_across_models(
        self,
    ) -> None:
        action = upsert_prediction(
            connection=self.connection,
            record=self._record(
                model_version="POR1_MODEL_0_1",
            ),
            available_columns=self.available_columns,
        )

        rows = self._current_pre_matches()

        self.assertEqual(action, "FROZEN")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["prediction_id"],
            "PUBLISHED_PRE_MATCH",
        )
        self.assertEqual(
            rows[0]["model_version"],
            "MODEL_0_1",
        )

    def test_pre_match_is_frozen_for_same_model(
        self,
    ) -> None:
        action = upsert_prediction(
            connection=self.connection,
            record=self._record(
                model_version="MODEL_0_1",
            ),
            available_columns=self.available_columns,
        )

        rows = self._current_pre_matches()

        self.assertEqual(action, "FROZEN")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["prediction_version"],
            1,
        )

    def test_explicit_backtest_bypass_allows_insert(
        self,
    ) -> None:
        action = upsert_prediction(
            connection=self.connection,
            record=self._record(
                model_version=(
                    "__TEMP_LEARNING_CANDIDATE__"
                ),
            ),
            available_columns=self.available_columns,
            allow_pre_match_recalculation=True,
        )

        rows = self._current_pre_matches()

        self.assertEqual(action, "INSERTED")
        self.assertEqual(len(rows), 2)

        model_versions = {
            row["model_version"]
            for row in rows
        }

        self.assertEqual(
            model_versions,
            {
                "MODEL_0_1",
                "__TEMP_LEARNING_CANDIDATE__",
            },
        )


class TestLearningPreMatchBypass(unittest.TestCase):
    def test_learning_explicitly_enables_bypass(
        self,
    ) -> None:
        source = inspect.getsource(
            evaluate_candidate_model
        )

        self.assertIn(
            "allow_pre_match_recalculation=True",
            source,
        )


if __name__ == "__main__":
    unittest.main()
