# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.config.path_config import load_paths_config
from src.database.init_database import (
    connect_database,
    get_database_path,
    run_integrity_check,
)
from src.utils.logger import get_logger


logger = get_logger("database.backup")


@dataclass
class BackupResult:
    source_path: Path
    backup_path: Path
    source_checksum: str
    backup_checksum: str
    size_bytes: int
    integrity_status: str

    @property
    def checksum_matches(self) -> bool:
        return self.source_checksum == self.backup_checksum


class DatabaseBackupError(RuntimeError):
    """Erro relacionado com backups da base de dados."""


def create_database_backup(
    backup_label: str = "manual",
    database_path: str | Path | None = None,
    keep_latest: int = 30,
) -> BackupResult:
    """
    Cria um backup consistente da base SQLite.

    Usa a API de backup do SQLite, em vez de copiar diretamente
    o ficheiro enquanto a base pode estar em modo WAL.
    """

    source_path = (
        Path(database_path).expanduser().resolve()
        if database_path is not None
        else get_database_path()
    )

    if not source_path.exists():
        raise DatabaseBackupError(
            f"A base de dados não existe: {source_path}"
        )

    integrity_status = run_integrity_check(source_path)

    if integrity_status.lower() != "ok":
        raise DatabaseBackupError(
            "A base de dados falhou o teste de integridade: "
            f"{integrity_status}"
        )

    paths = load_paths_config()
    backup_directory: Path = paths["database"]["backups"]

    backup_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = _normalize_label(backup_label)

    backup_filename = (
        f"footwin_sports_{timestamp}_{safe_label}.db"
    )

    backup_path = backup_directory / backup_filename

    logger.info(
        "A iniciar backup SQLite | origem=%s | destino=%s",
        source_path,
        backup_path,
    )

    source_connection = connect_database(source_path)

    try:
        destination_connection = sqlite3.connect(
            backup_path,
            timeout=30,
        )

        try:
            source_connection.backup(
                destination_connection,
                pages=100,
            )

            destination_connection.commit()

        finally:
            destination_connection.close()

    except sqlite3.Error as exc:
        if backup_path.exists():
            backup_path.unlink(missing_ok=True)

        raise DatabaseBackupError(
            f"Erro ao criar backup SQLite: {exc}"
        ) from exc

    finally:
        source_connection.close()

    backup_integrity = run_integrity_check(backup_path)

    if backup_integrity.lower() != "ok":
        backup_path.unlink(missing_ok=True)

        raise DatabaseBackupError(
            "O backup criado falhou o teste de integridade: "
            f"{backup_integrity}"
        )

    source_checksum = calculate_file_sha256(source_path)
    backup_checksum = calculate_file_sha256(backup_path)

    if source_checksum != backup_checksum:
        logger.warning(
            "Os checksums dos ficheiros SQLite diferem. "
            "Isto pode acontecer devido a metadados internos, "
            "embora ambas as bases estejam íntegras."
        )

    result = BackupResult(
        source_path=source_path,
        backup_path=backup_path,
        source_checksum=source_checksum,
        backup_checksum=backup_checksum,
        size_bytes=backup_path.stat().st_size,
        integrity_status=backup_integrity,
    )

    logger.info(
        "Backup SQLite concluído | ficheiro=%s | "
        "tamanho=%s bytes | integridade=%s",
        backup_path,
        result.size_bytes,
        result.integrity_status,
    )

    if keep_latest > 0:
        cleanup_old_backups(
            keep_latest=keep_latest,
        )

    return result


def list_database_backups() -> list[Path]:
    """Lista os backups do mais recente para o mais antigo."""

    paths = load_paths_config()
    backup_directory: Path = paths["database"]["backups"]

    if not backup_directory.exists():
        return []

    backups = [
        path
        for path in backup_directory.glob(
            "footwin_sports_*.db"
        )
        if path.is_file()
    ]

    return sorted(
        backups,
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def cleanup_old_backups(
    keep_latest: int = 30,
) -> list[Path]:
    """
    Remove backups antigos, mantendo apenas os mais recentes.
    """

    if keep_latest < 1:
        raise DatabaseBackupError(
            "keep_latest deve ser pelo menos 1."
        )

    backups = list_database_backups()
    backups_to_remove = backups[keep_latest:]

    removed: list[Path] = []

    for backup_path in backups_to_remove:
        try:
            backup_path.unlink()
            removed.append(backup_path)

            logger.info(
                "Backup antigo removido | ficheiro=%s",
                backup_path,
            )

        except OSError:
            logger.exception(
                "Não foi possível remover backup antigo | ficheiro=%s",
                backup_path,
            )

    return removed


def verify_backup(
    backup_path: str | Path,
) -> dict[str, str | int | bool]:
    """
    Verifica a existência, integridade, tamanho e checksum de um backup.
    """

    path = Path(backup_path).expanduser().resolve()

    if not path.exists():
        raise DatabaseBackupError(
            f"O backup não existe: {path}"
        )

    if not path.is_file():
        raise DatabaseBackupError(
            f"O caminho não é um ficheiro: {path}"
        )

    integrity = run_integrity_check(path)
    checksum = calculate_file_sha256(path)

    return {
        "path": str(path),
        "exists": True,
        "integrity": integrity,
        "checksum_sha256": checksum,
        "size_bytes": path.stat().st_size,
        "valid": integrity.lower() == "ok",
    }


def restore_database_backup(
    backup_path: str | Path,
    target_path: str | Path | None = None,
    create_safety_backup: bool = True,
) -> Path:
    """
    Restaura uma base a partir de um backup.

    Por segurança, pode criar primeiro um backup da base atual.
    """

    source_backup = Path(
        backup_path
    ).expanduser().resolve()

    if not source_backup.exists():
        raise DatabaseBackupError(
            f"O backup não existe: {source_backup}"
        )

    backup_check = verify_backup(source_backup)

    if not backup_check["valid"]:
        raise DatabaseBackupError(
            "O backup selecionado não está íntegro."
        )

    destination = (
        Path(target_path).expanduser().resolve()
        if target_path is not None
        else get_database_path()
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if destination.exists() and create_safety_backup:
        create_database_backup(
            backup_label="before_restore",
            database_path=destination,
        )

    temporary_path = destination.with_suffix(
        destination.suffix + ".restore_tmp"
    )

    shutil.copy2(
        source_backup,
        temporary_path,
    )

    restored_integrity = run_integrity_check(
        temporary_path
    )

    if restored_integrity.lower() != "ok":
        temporary_path.unlink(missing_ok=True)

        raise DatabaseBackupError(
            "A cópia temporária restaurada não está íntegra."
        )

    temporary_path.replace(destination)

    logger.info(
        "Base restaurada com sucesso | backup=%s | destino=%s",
        source_backup,
        destination,
    )

    return destination


def calculate_file_sha256(
    file_path: str | Path,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Calcula o SHA-256 de um ficheiro."""

    path = Path(file_path).expanduser().resolve()

    sha256 = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            chunk = file.read(chunk_size)

            if not chunk:
                break

            sha256.update(chunk)

    return sha256.hexdigest()


def _normalize_label(label: str) -> str:
    cleaned = (
        label.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )

    valid_characters = [
        character
        for character in cleaned
        if character.isalnum() or character == "_"
    ]

    normalized = "".join(valid_characters).strip("_")

    return normalized or "backup"
