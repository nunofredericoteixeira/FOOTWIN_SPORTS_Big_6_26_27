# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"
BACKUP_DIRECTORY = BASE_DIR / "database" / "backups"

MIGRATION_ID = "0002_prediction_versioning"
MIGRATION_DESCRIPTION = (
    "Adicionar versionamento e classificação "
    "às previsões dos jogos"
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )


def column_names(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {
        str(row[1])
        for row in rows
    }


def add_column_if_missing(
    connection: sqlite3.Connection,
    existing_columns: set[str],
    column_name: str,
    column_sql: str,
) -> None:
    if column_name in existing_columns:
        print(
            f"  = Coluna já existente: {column_name}"
        )
        return

    connection.execute(
        f"""
        ALTER TABLE match_predictions
        ADD COLUMN {column_sql}
        """
    )

    existing_columns.add(column_name)

    print(
        f"  + Coluna criada: {column_name}"
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
    print("FOOTWIN SPORTS — MIGRAÇÃO 0002")
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

        migration = connection.execute(
            """
            SELECT migration_id
            FROM schema_migrations
            WHERE migration_id = ?
            """,
            (MIGRATION_ID,),
        ).fetchone()

        if migration is not None:
            print()
            print(
                "Migração já aplicada. "
                "Nenhuma alteração necessária."
            )
            return

        print()
        print("A iniciar transação...")

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        columns = column_names(
            connection,
            "match_predictions",
        )

        add_column_if_missing(
            connection,
            columns,
            "prediction_stage",
            (
                "prediction_stage TEXT "
                "NOT NULL DEFAULT 'PRE_MATCH'"
            ),
        )

        add_column_if_missing(
            connection,
            columns,
            "prediction_version",
            (
                "prediction_version INTEGER "
                "NOT NULL DEFAULT 1"
            ),
        )

        add_column_if_missing(
            connection,
            columns,
            "parent_prediction_id",
            "parent_prediction_id TEXT",
        )

        add_column_if_missing(
            connection,
            columns,
            "lineup_id",
            "lineup_id TEXT",
        )

        add_column_if_missing(
            connection,
            columns,
            "lineup_hash",
            "lineup_hash TEXT",
        )

        add_column_if_missing(
            connection,
            columns,
            "lineup_confirmed",
            (
                "lineup_confirmed INTEGER "
                "NOT NULL DEFAULT 0"
            ),
        )

        add_column_if_missing(
            connection,
            columns,
            "lineup_data_quality",
            (
                "lineup_data_quality TEXT "
                "NOT NULL DEFAULT 'NOT_APPLICABLE'"
            ),
        )

        add_column_if_missing(
            connection,
            columns,
            "is_current",
            (
                "is_current INTEGER "
                "NOT NULL DEFAULT 1"
            ),
        )

        add_column_if_missing(
            connection,
            columns,
            "input_snapshot_json",
            "input_snapshot_json TEXT",
        )

        add_column_if_missing(
            connection,
            columns,
            "superseded_at",
            "superseded_at TEXT",
        )

        print()
        print("A reparar prediction_id vazios...")

        empty_before = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM match_predictions
            WHERE prediction_id IS NULL
               OR TRIM(prediction_id) = ''
            """
        ).fetchone()["total"]

        connection.execute(
            """
            UPDATE match_predictions
            SET prediction_id = (
                'LEGACY__'
                || printf('%08d', rowid)
            )
            WHERE prediction_id IS NULL
               OR TRIM(prediction_id) = ''
            """
        )

        empty_after = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM match_predictions
            WHERE prediction_id IS NULL
               OR TRIM(prediction_id) = ''
            """
        ).fetchone()["total"]

        print(
            "  Prediction IDs reparados: "
            f"{int(empty_before) - int(empty_after)}"
        )

        print()
        print("A classificar previsões existentes...")

        connection.execute(
            """
            UPDATE match_predictions
            SET
                prediction_stage = 'PRE_MATCH',
                prediction_version = 1,
                lineup_confirmed = 0,
                lineup_data_quality = 'NOT_APPLICABLE',
                is_current = 1
            """
        )

        print()
        print("A criar índices...")

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_predictions_match_stage
            ON match_predictions (
                match_id,
                model_version,
                prediction_stage
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_predictions_lineup_hash
            ON match_predictions (
                match_id,
                lineup_hash
            )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_predictions_stage_version_unique
            ON match_predictions (
                match_id,
                model_version,
                prediction_stage,
                prediction_version
            )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_predictions_current_stage_unique
            ON match_predictions (
                match_id,
                model_version,
                prediction_stage
            )
            WHERE is_current = 1
            """
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

        print()
        print("Migração confirmada com sucesso.")

        total = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM match_predictions
            """
        ).fetchone()["total"]

        pre_match = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM match_predictions
            WHERE prediction_stage = 'PRE_MATCH'
              AND prediction_version = 1
              AND is_current = 1
            """
        ).fetchone()["total"]

        empty_ids = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM match_predictions
            WHERE prediction_id IS NULL
               OR TRIM(prediction_id) = ''
            """
        ).fetchone()["total"]

        migrations = connection.execute(
            """
            SELECT
                migration_id,
                description,
                applied_at
            FROM schema_migrations
            ORDER BY applied_at, migration_id
            """
        ).fetchall()

        print()
        print("=" * 100)
        print("VALIDAÇÃO FINAL")
        print("=" * 100)
        print(f"Total de previsões: {total}")
        print(f"Previsões PRE_MATCH v1 atuais: {pre_match}")
        print(f"Prediction IDs vazios: {empty_ids}")

        print()
        print("Migrações registadas:")

        for row in migrations:
            print(
                f"  {row['migration_id']} | "
                f"{row['description']} | "
                f"{row['applied_at']}"
            )

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        print()
        print(f"Integrity check: {integrity}")
        print("=" * 100)

    except Exception:
        connection.rollback()
        print()
        print("ERRO: migração revertida integralmente.")
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
