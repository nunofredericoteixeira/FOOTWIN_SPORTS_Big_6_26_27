# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.database.init_database import connect_database
from src.utils.logger import get_logger


logger = get_logger("database.dataset_versions")


VALID_DATASET_STATUSES = {
    "PENDING",
    "VALIDATING",
    "APPROVED",
    "REJECTED",
    "IMPORTED",
    "ARCHIVED",
}


@dataclass
class DatasetVersion:
    dataset_version: str
    season_label: str
    file_path: str | None
    checksum_sha256: str | None
    record_count: int
    status: str
    created_at: str
    validated_at: str | None


class DatasetVersionError(RuntimeError):
    """Erro relacionado com as versões dos datasets."""


def calculate_sha256(
    file_path: str | Path,
    chunk_size: int = 1024 * 1024,
) -> str:
    """
    Calcula o checksum SHA-256 de um ficheiro.
    """

    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        raise DatasetVersionError(
            f"O ficheiro não existe: {path}"
        )

    if not path.is_file():
        raise DatasetVersionError(
            f"O caminho não corresponde a um ficheiro: {path}"
        )

    sha256 = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            chunk = file.read(chunk_size)

            if not chunk:
                break

            sha256.update(chunk)

    return sha256.hexdigest()


def register_dataset_version(
    dataset_version: str,
    season_label: str,
    file_path: str | Path,
    record_count: int = 0,
    status: str = "PENDING",
) -> DatasetVersion:
    """
    Insere ou atualiza uma versão de dataset.

    O checksum é calculado automaticamente.
    """

    normalized_version = dataset_version.strip()
    normalized_season = season_label.strip()
    normalized_status = status.strip().upper()

    if not normalized_version:
        raise DatasetVersionError(
            "A versão do dataset não pode estar vazia."
        )

    if not normalized_season:
        raise DatasetVersionError(
            "A época do dataset não pode estar vazia."
        )

    if normalized_status not in VALID_DATASET_STATUSES:
        raise DatasetVersionError(
            f"Estado de dataset inválido: {normalized_status}"
        )

    if record_count < 0:
        raise DatasetVersionError(
            "record_count não pode ser negativo."
        )

    path = Path(file_path).expanduser().resolve()

    checksum = calculate_sha256(path)

    validated_at = (
        datetime.now().isoformat(timespec="seconds")
        if normalized_status in {"APPROVED", "REJECTED"}
        else None
    )

    connection = connect_database()

    try:
        with connection:
            existing = connection.execute(
                """
                SELECT dataset_version
                FROM dataset_versions
                WHERE dataset_version = ?
                """,
                (normalized_version,),
            ).fetchone()

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO dataset_versions (
                        dataset_version,
                        season_label,
                        file_path,
                        checksum_sha256,
                        record_count,
                        status,
                        validated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_version,
                        normalized_season,
                        str(path),
                        checksum,
                        int(record_count),
                        normalized_status,
                        validated_at,
                    ),
                )

                logger.info(
                    "Versão de dataset inserida | versão=%s | estado=%s",
                    normalized_version,
                    normalized_status,
                )

            else:
                connection.execute(
                    """
                    UPDATE dataset_versions
                    SET
                        season_label = ?,
                        file_path = ?,
                        checksum_sha256 = ?,
                        record_count = ?,
                        status = ?,
                        validated_at = ?
                    WHERE dataset_version = ?
                    """,
                    (
                        normalized_season,
                        str(path),
                        checksum,
                        int(record_count),
                        normalized_status,
                        validated_at,
                        normalized_version,
                    ),
                )

                logger.info(
                    "Versão de dataset atualizada | versão=%s | estado=%s",
                    normalized_version,
                    normalized_status,
                )

        saved = get_dataset_version(
            normalized_version
        )

    finally:
        connection.close()

    if saved is None:
        raise DatasetVersionError(
            f"Não foi possível confirmar o dataset: {normalized_version}"
        )

    return saved


def update_dataset_status(
    dataset_version: str,
    status: str,
    record_count: int | None = None,
) -> DatasetVersion:
    """
    Atualiza o estado de uma versão já registada.
    """

    normalized_status = status.strip().upper()

    if normalized_status not in VALID_DATASET_STATUSES:
        raise DatasetVersionError(
            f"Estado de dataset inválido: {normalized_status}"
        )

    connection = connect_database()

    try:
        existing = connection.execute(
            """
            SELECT *
            FROM dataset_versions
            WHERE dataset_version = ?
            """,
            (dataset_version,),
        ).fetchone()

        if existing is None:
            raise DatasetVersionError(
                f"A versão do dataset não existe: {dataset_version}"
            )

        validated_at = (
            datetime.now().isoformat(timespec="seconds")
            if normalized_status in {"APPROVED", "REJECTED"}
            else existing["validated_at"]
        )

        final_record_count = (
            int(record_count)
            if record_count is not None
            else int(existing["record_count"])
        )

        with connection:
            connection.execute(
                """
                UPDATE dataset_versions
                SET
                    status = ?,
                    record_count = ?,
                    validated_at = ?
                WHERE dataset_version = ?
                """,
                (
                    normalized_status,
                    final_record_count,
                    validated_at,
                    dataset_version,
                ),
            )

    finally:
        connection.close()

    updated = get_dataset_version(dataset_version)

    if updated is None:
        raise DatasetVersionError(
            f"Não foi possível atualizar o dataset: {dataset_version}"
        )

    logger.info(
        "Estado do dataset atualizado | versão=%s | estado=%s",
        dataset_version,
        normalized_status,
    )

    return updated


def verify_dataset_checksum(
    dataset_version: str,
) -> bool:
    """
    Confirma se o ficheiro atual mantém o checksum registado.
    """

    dataset = get_dataset_version(dataset_version)

    if dataset is None:
        raise DatasetVersionError(
            f"A versão do dataset não existe: {dataset_version}"
        )

    if not dataset.file_path or not dataset.checksum_sha256:
        return False

    path = Path(dataset.file_path)

    if not path.exists():
        return False

    current_checksum = calculate_sha256(path)

    return current_checksum == dataset.checksum_sha256


def get_dataset_version(
    dataset_version: str,
) -> DatasetVersion | None:
    """
    Devolve uma versão de dataset.
    """

    connection = connect_database()

    try:
        row = connection.execute(
            """
            SELECT *
            FROM dataset_versions
            WHERE dataset_version = ?
            """,
            (dataset_version,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_dataset_version(row)

    finally:
        connection.close()


def list_dataset_versions(
    limit: int = 20,
) -> list[DatasetVersion]:
    """
    Lista as versões de dataset mais recentes.
    """

    if limit <= 0:
        raise DatasetVersionError(
            "O limite deve ser superior a zero."
        )

    connection = connect_database()

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM dataset_versions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

        return [
            _row_to_dataset_version(row)
            for row in rows
        ]

    finally:
        connection.close()


def _row_to_dataset_version(row) -> DatasetVersion:
    return DatasetVersion(
        dataset_version=row["dataset_version"],
        season_label=row["season_label"],
        file_path=row["file_path"],
        checksum_sha256=row["checksum_sha256"],
        record_count=int(row["record_count"]),
        status=row["status"],
        created_at=row["created_at"],
        validated_at=row["validated_at"],
    )
