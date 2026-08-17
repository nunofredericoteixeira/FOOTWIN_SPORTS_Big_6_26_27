# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"
BACKUP_DIRECTORY = BASE_DIR / "database" / "backups"

MIGRATION_ID = "0006_league_scoped_model_learning"
MIGRATION_DESCRIPTION = (
    "Adicionar versionamento e aprendizagem de modelos "
    "independentes por liga"
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )


def table_count(
    connection: sqlite3.Connection,
    table_name: str,
) -> int:
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]
    )


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
    print("FOOTWIN SPORTS — MIGRAÇÃO 0006")
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

        before_counts = {
            table_name: table_count(
                connection,
                table_name,
            )
            for table_name in (
                "model_versions",
                "model_parameters",
                "model_candidates",
                "model_promotion_decisions",
                "prediction_evaluations",
            )
        }

        #
        # A alteração da UNIQUE(parameter_hash) exige
        # reconstruir model_versions. Como existem tabelas
        # filhas, as FKs são temporariamente desligadas
        # durante a reconstrução e integralmente validadas
        # antes do fim.
        #
        connection.execute(
            "PRAGMA foreign_keys = OFF"
        )

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        connection.execute(
            """
            CREATE TABLE model_versions_new (
                model_version TEXT PRIMARY KEY,
                league_id TEXT,
                season_label TEXT NOT NULL,
                parent_model_version TEXT,
                version_status TEXT NOT NULL,
                parameter_hash TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                activated_at TEXT,
                retired_at TEXT,
                notes TEXT,

                FOREIGN KEY (parent_model_version)
                    REFERENCES model_versions_new (
                        model_version
                    )
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,

                CHECK (
                    league_id IS NULL
                    OR LENGTH(TRIM(league_id)) > 0
                ),

                CHECK (
                    version_status IN (
                        'ACTIVE',
                        'CANDIDATE',
                        'RETIRED',
                        'REJECTED'
                    )
                )
            )
            """
        )

        connection.execute(
            """
            INSERT INTO model_versions_new (
                model_version,
                league_id,
                season_label,
                parent_model_version,
                version_status,
                parameter_hash,
                parameters_json,
                created_at,
                activated_at,
                retired_at,
                notes
            )
            SELECT
                model_version,
                NULL,
                season_label,
                parent_model_version,
                version_status,
                parameter_hash,
                parameters_json,
                created_at,
                activated_at,
                retired_at,
                notes
            FROM model_versions
            """
        )

        connection.execute(
            "DROP TABLE model_versions"
        )

        connection.execute(
            """
            ALTER TABLE model_versions_new
            RENAME TO model_versions
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX
                idx_model_versions_active_global_unique
            ON model_versions (
                season_label
            )
            WHERE
                version_status = 'ACTIVE'
                AND league_id IS NULL
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX
                idx_model_versions_active_league_unique
            ON model_versions (
                season_label,
                league_id
            )
            WHERE
                version_status = 'ACTIVE'
                AND league_id IS NOT NULL
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX
                idx_model_versions_hash_global_unique
            ON model_versions (
                parameter_hash
            )
            WHERE league_id IS NULL
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX
                idx_model_versions_hash_league_unique
            ON model_versions (
                league_id,
                parameter_hash
            )
            WHERE league_id IS NOT NULL
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_model_versions_status
            ON model_versions (
                season_label,
                league_id,
                version_status
            )
            """
        )

        #
        # model_candidates tem atualmente um CHECK
        # que só permite GLOBAL. É reconstruída para
        # suportar candidatos específicos por liga.
        #
        connection.execute(
            """
            CREATE TABLE model_candidates_new (
                candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_model_version TEXT NOT NULL UNIQUE,
                parent_model_version TEXT NOT NULL,
                league_id TEXT,
                evaluation_scope TEXT NOT NULL
                    DEFAULT 'GLOBAL',
                sample_size INTEGER NOT NULL DEFAULT 0,
                baseline_brier_score REAL,
                candidate_brier_score REAL,
                baseline_log_loss REAL,
                candidate_log_loss REAL,
                baseline_outcome_accuracy REAL,
                candidate_outcome_accuracy REAL,
                candidate_status TEXT NOT NULL
                    DEFAULT 'PENDING',
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
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
                    evaluation_scope IN (
                        'GLOBAL',
                        'LEAGUE'
                    )
                ),

                CHECK (
                    (
                        evaluation_scope = 'GLOBAL'
                        AND league_id IS NULL
                    )
                    OR
                    (
                        evaluation_scope = 'LEAGUE'
                        AND league_id IS NOT NULL
                        AND LENGTH(TRIM(league_id)) > 0
                    )
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
            )
            """
        )

        connection.execute(
            """
            INSERT INTO model_candidates_new (
                candidate_id,
                candidate_model_version,
                parent_model_version,
                league_id,
                evaluation_scope,
                sample_size,
                baseline_brier_score,
                candidate_brier_score,
                baseline_log_loss,
                candidate_log_loss,
                baseline_outcome_accuracy,
                candidate_outcome_accuracy,
                candidate_status,
                created_at,
                evaluated_at
            )
            SELECT
                candidate_id,
                candidate_model_version,
                parent_model_version,
                NULL,
                evaluation_scope,
                sample_size,
                baseline_brier_score,
                candidate_brier_score,
                baseline_log_loss,
                candidate_log_loss,
                baseline_outcome_accuracy,
                candidate_outcome_accuracy,
                candidate_status,
                created_at,
                evaluated_at
            FROM model_candidates
            """
        )

        #
        # model_promotion_decisions referencia
        # model_candidates, por isso também é preservada
        # durante a troca da tabela pai.
        #
        connection.execute(
            """
            CREATE TABLE model_promotion_decisions_new (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL UNIQUE,
                decision TEXT NOT NULL,
                sample_size INTEGER NOT NULL,
                brier_improvement REAL,
                log_loss_improvement REAL,
                outcome_accuracy_improvement REAL,
                decision_reason TEXT NOT NULL,
                decided_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (candidate_id)
                    REFERENCES model_candidates_new (
                        candidate_id
                    )
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
            )
            """
        )

        connection.execute(
            """
            INSERT INTO model_promotion_decisions_new (
                decision_id,
                candidate_id,
                decision,
                sample_size,
                brier_improvement,
                log_loss_improvement,
                outcome_accuracy_improvement,
                decision_reason,
                decided_at
            )
            SELECT
                decision_id,
                candidate_id,
                decision,
                sample_size,
                brier_improvement,
                log_loss_improvement,
                outcome_accuracy_improvement,
                decision_reason,
                decided_at
            FROM model_promotion_decisions
            """
        )

        connection.execute(
            "DROP TABLE model_promotion_decisions"
        )

        connection.execute(
            "DROP TABLE model_candidates"
        )

        connection.execute(
            """
            ALTER TABLE model_candidates_new
            RENAME TO model_candidates
            """
        )

        connection.execute(
            """
            ALTER TABLE model_promotion_decisions_new
            RENAME TO model_promotion_decisions
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_model_candidates_status
            ON model_candidates (
                league_id,
                candidate_status,
                created_at
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_model_candidates_scope
            ON model_candidates (
                evaluation_scope,
                league_id,
                created_at
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_model_promotion_decisions_date
            ON model_promotion_decisions (
                decided_at
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

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        after_counts = {
            table_name: table_count(
                connection,
                table_name,
            )
            for table_name in (
                "model_versions",
                "model_parameters",
                "model_candidates",
                "model_promotion_decisions",
                "prediction_evaluations",
            )
        }

        if before_counts != after_counts:
            raise RuntimeError(
                "A migração alterou contagens históricas. "
                f"Antes={before_counts}; "
                f"depois={after_counts}"
            )

        model_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(model_versions)"
            ).fetchall()
        }

        candidate_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(model_candidates)"
            ).fetchall()
        }

        if "league_id" not in model_columns:
            raise RuntimeError(
                "league_id não existe em model_versions."
            )

        if "league_id" not in candidate_columns:
            raise RuntimeError(
                "league_id não existe em model_candidates."
            )

        legacy_model = connection.execute(
            """
            SELECT
                model_version,
                league_id,
                version_status
            FROM model_versions
            WHERE model_version = 'MODEL_0_1'
            """
        ).fetchone()

        if legacy_model is None:
            raise RuntimeError(
                "MODEL_0_1 desapareceu durante a migração."
            )

        if legacy_model["league_id"] is not None:
            raise RuntimeError(
                "MODEL_0_1 deve permanecer como modelo "
                "global legado."
            )

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        foreign_keys = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if integrity != "ok":
            raise RuntimeError(
                "Integrity check falhou: "
                f"{integrity}"
            )

        if foreign_keys:
            raise RuntimeError(
                "Foreign key check encontrou erros: "
                f"{foreign_keys}"
            )

        print()
        print("=" * 100)
        print("VALIDAÇÃO FINAL")
        print("=" * 100)

        for table_name, total in after_counts.items():
            print(
                f"{table_name:<30} "
                f"registos={total}"
            )

        print()
        print(
            "MODEL_0_1 global preservado: ok"
        )
        print(
            "model_versions.league_id: ok"
        )
        print(
            "model_candidates.league_id: ok"
        )
        print(
            "ACTIVE global por época: protegido"
        )
        print(
            "ACTIVE por liga/época: protegido"
        )
        print(
            "Hashes iguais entre ligas: permitidos"
        )
        print(
            "Hash duplicado na mesma liga: protegido"
        )
        print(f"Integrity check: {integrity}")
        print("Foreign key check: ok")
        print("=" * 100)

    except Exception:
        connection.rollback()

        try:
            connection.execute(
                "PRAGMA foreign_keys = ON"
            )
        except sqlite3.Error:
            pass

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
