# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"
BACKUP_DIRECTORY = BASE_DIR / "database" / "backups"

MIGRATION_ID = "0005_prudent_prediction_evaluation"
MIGRATION_DESCRIPTION = (
    "Adicionar prognóstico prudente e respetivo acerto "
    "às avaliações das previsões"
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )


def column_names(
    connection: sqlite3.Connection,
) -> set[str]:
    rows = connection.execute(
        "PRAGMA table_info(prediction_evaluations)"
    ).fetchall()

    return {
        str(row["name"])
        for row in rows
    }


def main() -> None:
    if not DATABASE_PATH.exists():
        raise SystemExit(
            "Base de dados não encontrada: "
            f"{DATABASE_PATH}"
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
    print("FOOTWIN SPORTS — MIGRAÇÃO 0005")
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

        existing_columns = column_names(connection)

        if "prudent_prediction" not in existing_columns:
            connection.execute(
                """
                ALTER TABLE prediction_evaluations
                ADD COLUMN prudent_prediction TEXT
                CHECK (
                    prudent_prediction IS NULL
                    OR prudent_prediction IN (
                        '1',
                        'X',
                        '2',
                        '1X',
                        '12',
                        'X2'
                    )
                )
                """
            )

        existing_columns = column_names(connection)

        if "prudent_outcome_hit" not in existing_columns:
            connection.execute(
                """
                ALTER TABLE prediction_evaluations
                ADD COLUMN prudent_outcome_hit INTEGER
                CHECK (
                    prudent_outcome_hit IS NULL
                    OR prudent_outcome_hit IN (0, 1)
                )
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

        final_columns = column_names(connection)

        required_columns = {
            "prudent_prediction",
            "prudent_outcome_hit",
        }

        missing_columns = (
            required_columns
            - final_columns
        )

        if missing_columns:
            raise RuntimeError(
                "Faltam colunas após a migração: "
                + ", ".join(
                    sorted(missing_columns)
                )
            )

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        foreign_keys = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        total = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM prediction_evaluations
            """
        ).fetchone()["total"]

        print()
        print("=" * 100)
        print("VALIDAÇÃO FINAL")
        print("=" * 100)
        print(
            "prediction_evaluations "
            f"registos={total}"
        )
        print(
            "Coluna prudent_prediction: ok"
        )
        print(
            "Coluna prudent_outcome_hit: ok"
        )
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
