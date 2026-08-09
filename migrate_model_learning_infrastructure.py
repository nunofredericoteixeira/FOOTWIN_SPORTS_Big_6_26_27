# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"
BACKUP_DIRECTORY = BASE_DIR / "database" / "backups"

MIGRATION_ID = "0004_model_learning_infrastructure"
MIGRATION_DESCRIPTION = (
    "Criar versões imutáveis do modelo, avaliações, "
    "candidatos e decisões de promoção"
)


MIGRATION_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS
    idx_team_ratings_model_snapshot_unique
ON team_ratings (
    team_id,
    season_label,
    model_version
);

CREATE TABLE IF NOT EXISTS model_versions (
    model_version TEXT PRIMARY KEY,
    season_label TEXT NOT NULL,
    parent_model_version TEXT,
    version_status TEXT NOT NULL,
    parameter_hash TEXT NOT NULL UNIQUE,
    parameters_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at TEXT,
    retired_at TEXT,
    notes TEXT,

    FOREIGN KEY (parent_model_version)
        REFERENCES model_versions (model_version)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CHECK (
        version_status IN (
            'ACTIVE',
            'CANDIDATE',
            'RETIRED',
            'REJECTED'
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_model_versions_active_season_unique
ON model_versions (season_label)
WHERE version_status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_model_versions_status
ON model_versions (
    season_label,
    version_status
);

CREATE TABLE IF NOT EXISTS model_parameters (
    model_parameter_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    parameter_value REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (model_version)
        REFERENCES model_versions (model_version)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE (
        model_version,
        parameter_name
    )
);

CREATE INDEX IF NOT EXISTS idx_model_parameters_version
ON model_parameters (model_version);

CREATE TABLE IF NOT EXISTS prediction_evaluations (
    evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER NOT NULL,
    match_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prediction_stage TEXT NOT NULL,
    actual_home_goals INTEGER NOT NULL,
    actual_away_goals INTEGER NOT NULL,
    actual_outcome TEXT NOT NULL,
    predicted_outcome TEXT NOT NULL,
    outcome_hit INTEGER NOT NULL,
    exact_score_hit INTEGER NOT NULL,
    brier_score REAL NOT NULL,
    log_loss REAL NOT NULL,
    evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (prediction_id)
        REFERENCES match_predictions (prediction_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (match_id)
        REFERENCES matches (match_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (model_version)
        REFERENCES model_versions (model_version)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    UNIQUE (prediction_id),

    CHECK (
        prediction_stage IN (
            'PRE_MATCH',
            'CONFIRMED_LINEUP'
        )
    ),

    CHECK (actual_home_goals >= 0),
    CHECK (actual_away_goals >= 0),

    CHECK (
        actual_outcome IN ('1', 'X', '2')
    ),

    CHECK (
        predicted_outcome IN ('1', 'X', '2')
    ),

    CHECK (outcome_hit IN (0, 1)),
    CHECK (exact_score_hit IN (0, 1)),
    CHECK (brier_score >= 0),
    CHECK (log_loss >= 0)
);

CREATE INDEX IF NOT EXISTS idx_prediction_evaluations_match
ON prediction_evaluations (
    match_id,
    evaluated_at
);

CREATE INDEX IF NOT EXISTS idx_prediction_evaluations_model
ON prediction_evaluations (
    model_version,
    prediction_stage,
    evaluated_at
);

CREATE TABLE IF NOT EXISTS model_candidates (
    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_model_version TEXT NOT NULL UNIQUE,
    parent_model_version TEXT NOT NULL,
    evaluation_scope TEXT NOT NULL DEFAULT 'GLOBAL',
    sample_size INTEGER NOT NULL DEFAULT 0,
    baseline_brier_score REAL,
    candidate_brier_score REAL,
    baseline_log_loss REAL,
    candidate_log_loss REAL,
    baseline_outcome_accuracy REAL,
    candidate_outcome_accuracy REAL,
    candidate_status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    evaluated_at TEXT,

    FOREIGN KEY (candidate_model_version)
        REFERENCES model_versions (model_version)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (parent_model_version)
        REFERENCES model_versions (model_version)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CHECK (
        evaluation_scope = 'GLOBAL'
    ),

    CHECK (sample_size >= 0),

    CHECK (
        candidate_status IN (
            'PENDING',
            'EVALUATED',
            'APPROVED',
            'REJECTED',
            'PROMOTED'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_model_candidates_status
ON model_candidates (
    candidate_status,
    created_at
);

CREATE TABLE IF NOT EXISTS model_promotion_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL UNIQUE,
    decision TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    brier_improvement REAL,
    log_loss_improvement REAL,
    outcome_accuracy_improvement REAL,
    decision_reason TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (candidate_id)
        REFERENCES model_candidates (candidate_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CHECK (
        decision IN (
            'PROMOTE',
            'REJECT',
            'INSUFFICIENT_SAMPLE'
        )
    ),

    CHECK (sample_size >= 0)
);

CREATE INDEX IF NOT EXISTS idx_model_promotion_decisions_date
ON model_promotion_decisions (decided_at);
"""


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )


def main() -> None:
    if not DATABASE_PATH.exists():
        raise SystemExit(
            f"Base de dados não encontrada: {DATABASE_PATH}"
        )

    BACKUP_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    backup_path = (
        BACKUP_DIRECTORY
        / (
            "footwin_sports_"
            f"BEFORE_{MIGRATION_ID}_"
            f"{utc_timestamp()}.db"
        )
    )

    shutil.copy2(
        DATABASE_PATH,
        backup_path,
    )

    print()
    print("=" * 100)
    print("FOOTWIN SPORTS — MIGRAÇÃO 0004")
    print("=" * 100)
    print(f"Base de dados: {DATABASE_PATH}")
    print(f"Backup criado: {backup_path}")

    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        connection.execute(
            "PRAGMA journal_mode = WAL"
        )
        connection.execute(
            "PRAGMA busy_timeout = 30000"
        )

        existing = connection.execute(
            """
            SELECT migration_id
            FROM schema_migrations
            WHERE migration_id = ?
            """,
            (MIGRATION_ID,),
        ).fetchone()

        if existing is not None:
            print()
            print(
                "Migração já aplicada. "
                "Nenhuma alteração necessária."
            )
            return

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        connection.executescript(
            MIGRATION_SQL
        )

        connection.execute(
            """
            INSERT INTO schema_migrations (
                migration_id,
                description
            )
            VALUES (?, ?)
            """,
            (
                MIGRATION_ID,
                MIGRATION_DESCRIPTION,
            ),
        )

        connection.commit()

        expected_tables = {
            "model_versions",
            "model_parameters",
            "prediction_evaluations",
            "model_candidates",
            "model_promotion_decisions",
        }

        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

        existing_tables = {
            str(row["name"])
            for row in rows
        }

        missing = (
            expected_tables
            - existing_tables
        )

        if missing:
            raise RuntimeError(
                "Faltam tabelas após a migração: "
                + ", ".join(
                    sorted(missing)
                )
            )

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        foreign_keys = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        print()
        print("=" * 100)
        print("VALIDAÇÃO FINAL")
        print("=" * 100)

        for table_name in sorted(
            expected_tables
        ):
            total = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {table_name}
                """
            ).fetchone()["total"]

            print(
                f"{table_name:<30} "
                f"registos={total}"
            )

        print()
        print(f"Integrity check: {integrity}")
        print(
            "Foreign key check: "
            f"{'ok' if not foreign_keys else 'ERRO'}"
        )
        print("=" * 100)

    except Exception:
        connection.rollback()

        print()
        print(
            "ERRO: migração revertida "
            "integralmente."
        )

        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
