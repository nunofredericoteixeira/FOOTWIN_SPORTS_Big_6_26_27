# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.database.init_database import connect_database
from src.utils.logger import get_logger


logger = get_logger("database.execution_runs")


VALID_RUN_STATUSES = {
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "PARTIAL",
    "FAILED",
    "SKIPPED",
    "CANCELLED",
}


@dataclass
class ExecutionRun:
    run_id: str
    run_type: str
    status: str
    started_at: str
    model_version: Optional[str] = None
    dataset_version: Optional[str] = None
    finished_at: Optional[str] = None
    hostname: Optional[str] = None
    process_id: Optional[int] = None
    error_count: int = 0
    warning_count: int = 0
    error_message: Optional[str] = None


class ExecutionRunError(RuntimeError):
    """Erro relacionado com o registo de execuções."""


def create_run_id(run_type: str) -> str:
    """
    Cria um identificador único e legível para uma execução.

    Exemplo:
        IMPORT_20260728_001500_A1B2C3D4
    """

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:8].upper()

    normalized_type = (
        run_type.strip()
        .upper()
        .replace(" ", "_")
        .replace("-", "_")
    )

    return f"{normalized_type}_{timestamp}_{suffix}"


def start_execution_run(
    run_type: str,
    model_version: str | None = None,
    dataset_version: str | None = None,
    database_path: str | Path | None = None,
) -> ExecutionRun:
    """
    Cria um novo registo de execução com estado RUNNING.
    """

    if not run_type or not run_type.strip():
        raise ExecutionRunError(
            "O tipo de execução não pode estar vazio."
        )

    run_id = create_run_id(run_type)
    started_at = datetime.now().isoformat(timespec="seconds")
    hostname = socket.gethostname()
    process_id = os.getpid()

    connection = connect_database(database_path)

    try:
        with connection:
            connection.execute(
                """
                INSERT INTO execution_runs (
                    run_id,
                    run_type,
                    model_version,
                    dataset_version,
                    started_at,
                    status,
                    hostname,
                    process_id,
                    error_count,
                    warning_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    run_type.strip().upper(),
                    model_version,
                    dataset_version,
                    started_at,
                    "RUNNING",
                    hostname,
                    process_id,
                    0,
                    0,
                ),
            )

    except Exception as exc:
        raise ExecutionRunError(
            f"Não foi possível iniciar a execução: {exc}"
        ) from exc

    finally:
        connection.close()

    execution = ExecutionRun(
        run_id=run_id,
        run_type=run_type.strip().upper(),
        model_version=model_version,
        dataset_version=dataset_version,
        started_at=started_at,
        status="RUNNING",
        hostname=hostname,
        process_id=process_id,
    )

    logger.info(
        "Execução iniciada | run_id=%s | tipo=%s",
        run_id,
        execution.run_type,
    )

    return execution


def finish_execution_run(
    run_id: str,
    status: str,
    error_count: int = 0,
    warning_count: int = 0,
    error_message: str | None = None,
    database_path: str | Path | None = None,
) -> ExecutionRun:
    """
    Finaliza uma execução existente.
    """

    normalized_status = status.strip().upper()

    if normalized_status not in VALID_RUN_STATUSES:
        raise ExecutionRunError(
            f"Estado inválido: {normalized_status}"
        )

    if normalized_status in {"PENDING", "RUNNING"}:
        raise ExecutionRunError(
            "Uma execução finalizada não pode ficar "
            "com estado PENDING ou RUNNING."
        )

    finished_at = datetime.now().isoformat(timespec="seconds")

    connection = connect_database(database_path)

    try:
        existing = connection.execute(
            """
            SELECT *
            FROM execution_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

        if existing is None:
            raise ExecutionRunError(
                f"A execução não existe: {run_id}"
            )

        with connection:
            connection.execute(
                """
                UPDATE execution_runs
                SET
                    finished_at = ?,
                    status = ?,
                    error_count = ?,
                    warning_count = ?,
                    error_message = ?
                WHERE run_id = ?
                """,
                (
                    finished_at,
                    normalized_status,
                    int(error_count),
                    int(warning_count),
                    error_message,
                    run_id,
                ),
            )

        updated = connection.execute(
            """
            SELECT *
            FROM execution_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

    finally:
        connection.close()

    if updated is None:
        raise ExecutionRunError(
            f"Não foi possível reler a execução: {run_id}"
        )

    execution = _row_to_execution_run(updated)

    logger.info(
        "Execução finalizada | run_id=%s | estado=%s | "
        "erros=%s | avisos=%s",
        run_id,
        normalized_status,
        error_count,
        warning_count,
    )

    return execution


def fail_execution_run(
    run_id: str,
    error_message: str,
    error_count: int = 1,
    warning_count: int = 0,
    database_path: str | Path | None = None,
) -> ExecutionRun:
    """
    Atalho para finalizar uma execução com estado FAILED.
    """

    return finish_execution_run(
        run_id=run_id,
        status="FAILED",
        error_count=error_count,
        warning_count=warning_count,
        error_message=error_message,
        database_path=database_path,
    )


def get_execution_run(
    run_id: str,
    database_path: str | Path | None = None,
) -> ExecutionRun | None:
    """
    Devolve uma execução pelo respetivo ID.
    """

    connection = connect_database(database_path)

    try:
        row = connection.execute(
            """
            SELECT *
            FROM execution_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_execution_run(row)

    finally:
        connection.close()


def list_execution_runs(
    limit: int = 20,
    database_path: str | Path | None = None,
) -> list[ExecutionRun]:
    """
    Lista as execuções mais recentes.
    """

    if limit <= 0:
        raise ExecutionRunError(
            "O limite deve ser superior a zero."
        )

    connection = connect_database(database_path)

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM execution_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

        return [
            _row_to_execution_run(row)
            for row in rows
        ]

    finally:
        connection.close()


def _row_to_execution_run(row) -> ExecutionRun:
    return ExecutionRun(
        run_id=row["run_id"],
        run_type=row["run_type"],
        model_version=row["model_version"],
        dataset_version=row["dataset_version"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status=row["status"],
        hostname=row["hostname"],
        process_id=row["process_id"],
        error_count=row["error_count"],
        warning_count=row["warning_count"],
        error_message=row["error_message"],
    )
