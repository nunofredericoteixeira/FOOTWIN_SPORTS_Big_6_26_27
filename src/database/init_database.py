# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.config.path_config import load_paths_config
from src.database.schema import create_schema, get_expected_tables
from src.utils.logger import get_logger


logger = get_logger("database")


class DatabaseInitializationError(RuntimeError):
    """Erro ocorrido durante a inicialização da base de dados."""


def get_database_path() -> Path:
    """Devolve o caminho absoluto da base SQLite principal."""

    paths = load_paths_config()
    database_path: Path = paths["database"]["main"]

    return database_path


def connect_database(
    database_path: str | Path | None = None,
) -> sqlite3.Connection:
    """
    Abre uma ligação SQLite com configurações seguras.

    A ligação devolve linhas acessíveis por nome de coluna.
    """

    path = (
        Path(database_path).expanduser().resolve()
        if database_path is not None
        else get_database_path()
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        connection = sqlite3.connect(
            database=path,
            timeout=30,
        )
    except sqlite3.Error as exc:
        raise DatabaseInitializationError(
            f"Não foi possível abrir a base SQLite: {path}"
        ) from exc

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")
    connection.execute("PRAGMA busy_timeout = 30000;")

    return connection


def initialize_database(
    database_path: str | Path | None = None,
) -> Path:
    """
    Cria a base de dados e todas as tabelas do esquema inicial.

    A operação é transacional.
    """

    path = (
        Path(database_path).expanduser().resolve()
        if database_path is not None
        else get_database_path()
    )

    logger.info(
        "A inicializar base de dados | caminho=%s",
        path,
    )

    connection = connect_database(path)

    try:
        with connection:
            create_schema(connection)

            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations (
                    migration_id,
                    description
                )
                VALUES (?, ?)
                """,
                (
                    "0001_initial_schema",
                    "Esquema inicial do FOOTWIN SPORTS Modelo 0.1",
                ),
            )

        validate_database_schema(connection)

    except sqlite3.Error as exc:
        logger.exception(
            "Erro SQLite durante a inicialização."
        )

        raise DatabaseInitializationError(
            f"Erro ao criar o esquema da base: {exc}"
        ) from exc

    finally:
        connection.close()

    logger.info(
        "Base de dados inicializada com sucesso | caminho=%s",
        path,
    )

    return path


def validate_database_schema(
    connection: sqlite3.Connection,
) -> None:
    """Confirma se todas as tabelas principais existem."""

    cursor = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        """
    )

    existing_tables = {
        row["name"]
        for row in cursor.fetchall()
        if not row["name"].startswith("sqlite_")
    }

    expected_tables = get_expected_tables()
    missing_tables = expected_tables - existing_tables

    if missing_tables:
        raise DatabaseInitializationError(
            "Faltam tabelas na base de dados: "
            + ", ".join(sorted(missing_tables))
        )


def run_integrity_check(
    database_path: str | Path | None = None,
) -> str:
    """Executa o PRAGMA integrity_check na base SQLite."""

    connection = connect_database(database_path)

    try:
        row = connection.execute(
            "PRAGMA integrity_check;"
        ).fetchone()

        result = str(row[0]) if row else "unknown"

    finally:
        connection.close()

    return result


def list_database_tables(
    database_path: str | Path | None = None,
) -> list[str]:
    """Lista as tabelas existentes na base."""

    connection = connect_database(database_path)

    try:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        return [
            str(row["name"])
            for row in rows
        ]

    finally:
        connection.close()
