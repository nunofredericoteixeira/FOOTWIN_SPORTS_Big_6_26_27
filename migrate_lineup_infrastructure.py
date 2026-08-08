# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"
BACKUP_DIRECTORY = BASE_DIR / "database" / "backups"

MIGRATION_ID = "0003_lineup_infrastructure"
MIGRATION_DESCRIPTION = (
    "Criar jogadores, plantéis, onzes oficiais "
    "e histórico de recolha"
)


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    date_of_birth TEXT,
    nationality TEXT,
    primary_position TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (active IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_players_normalized_name
ON players (normalized_name);

CREATE TABLE IF NOT EXISTS team_squads (
    team_squad_id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    season_label TEXT NOT NULL,
    shirt_number INTEGER,
    position_code TEXT,
    squad_status TEXT NOT NULL DEFAULT 'ACTIVE',
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (team_id)
        REFERENCES teams (team_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (player_id)
        REFERENCES players (player_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE (
        team_id,
        player_id,
        season_label
    ),

    CHECK (
        squad_status IN (
            'ACTIVE',
            'LOAN',
            'INJURED',
            'SUSPENDED',
            'INACTIVE',
            'TRANSFERRED'
        )
    ),

    CHECK (
        shirt_number IS NULL
        OR shirt_number >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_team_squads_team
ON team_squads (
    team_id,
    season_label
);

CREATE INDEX IF NOT EXISTS idx_team_squads_player
ON team_squads (
    player_id,
    season_label
);

CREATE TABLE IF NOT EXISTS external_provider_mappings (
    mapping_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    internal_entity_id TEXT NOT NULL,
    external_entity_id TEXT NOT NULL,
    external_name TEXT,
    mapping_status TEXT NOT NULL DEFAULT 'CONFIRMED',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        provider,
        entity_type,
        external_entity_id
    ),

    UNIQUE (
        provider,
        entity_type,
        internal_entity_id
    ),

    CHECK (
        entity_type IN (
            'LEAGUE',
            'TEAM',
            'PLAYER',
            'MATCH'
        )
    ),

    CHECK (
        mapping_status IN (
            'CONFIRMED',
            'AUTOMATIC',
            'MANUAL',
            'PENDING',
            'REJECTED'
        )
    ),

    CHECK (
        confidence >= 0
        AND confidence <= 1
    )
);

CREATE INDEX IF NOT EXISTS idx_provider_mappings_internal
ON external_provider_mappings (
    entity_type,
    internal_entity_id
);

CREATE INDEX IF NOT EXISTS idx_provider_mappings_external
ON external_provider_mappings (
    provider,
    entity_type,
    external_entity_id
);

CREATE TABLE IF NOT EXISTS match_lineups (
    lineup_id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_fixture_id TEXT,
    lineup_status TEXT NOT NULL,
    home_formation TEXT,
    away_formation TEXT,
    lineup_hash TEXT NOT NULL,
    announced_at TEXT,
    fetched_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1,
    raw_payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (match_id)
        REFERENCES matches (match_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE (
        match_id,
        lineup_hash
    ),

    CHECK (
        lineup_status IN (
            'PENDING',
            'PARTIAL',
            'CONFIRMED',
            'CORRECTED',
            'INVALID'
        )
    ),

    CHECK (is_current IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_match_lineups_match
ON match_lineups (
    match_id,
    is_current
);

CREATE INDEX IF NOT EXISTS idx_match_lineups_hash
ON match_lineups (
    lineup_hash
);

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_match_lineups_current_unique
ON match_lineups (match_id)
WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS match_lineup_players (
    lineup_player_id TEXT PRIMARY KEY,
    lineup_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    player_id TEXT,
    provider_player_id TEXT,
    player_name TEXT NOT NULL,
    role TEXT NOT NULL,
    position_code TEXT,
    formation_position TEXT,
    shirt_number INTEGER,
    captain INTEGER NOT NULL DEFAULT 0,
    mapping_status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (lineup_id)
        REFERENCES match_lineups (lineup_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (match_id)
        REFERENCES matches (match_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (team_id)
        REFERENCES teams (team_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (player_id)
        REFERENCES players (player_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    UNIQUE (
        lineup_id,
        team_id,
        role,
        provider_player_id
    ),

    CHECK (
        role IN (
            'STARTER',
            'SUBSTITUTE'
        )
    ),

    CHECK (captain IN (0, 1)),

    CHECK (
        mapping_status IN (
            'CONFIRMED',
            'AUTOMATIC',
            'MANUAL',
            'PENDING',
            'UNMATCHED'
        )
    ),

    CHECK (
        shirt_number IS NULL
        OR shirt_number >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_lineup_players_lineup
ON match_lineup_players (
    lineup_id,
    team_id,
    role
);

CREATE INDEX IF NOT EXISTS idx_lineup_players_player
ON match_lineup_players (
    player_id
);

CREATE TABLE IF NOT EXISTS match_lineup_fetches (
    fetch_id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_fixture_id TEXT,
    attempted_at TEXT NOT NULL,
    fetch_status TEXT NOT NULL,
    home_starters_count INTEGER NOT NULL DEFAULT 0,
    away_starters_count INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    response_hash TEXT,
    raw_payload_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (match_id)
        REFERENCES matches (match_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    CHECK (
        fetch_status IN (
            'SUCCESS',
            'NO_LINEUP',
            'PARTIAL',
            'INVALID',
            'HTTP_ERROR',
            'PROVIDER_ERROR',
            'MAPPING_ERROR'
        )
    ),

    CHECK (home_starters_count >= 0),
    CHECK (away_starters_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_lineup_fetches_match
ON match_lineup_fetches (
    match_id,
    attempted_at
);

CREATE INDEX IF NOT EXISTS idx_lineup_fetches_status
ON match_lineup_fetches (
    fetch_status,
    attempted_at
);
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
    print("FOOTWIN SPORTS — MIGRAÇÃO 0003")
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
            "players",
            "team_squads",
            "external_provider_mappings",
            "match_lineups",
            "match_lineup_players",
            "match_lineup_fetches",
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
