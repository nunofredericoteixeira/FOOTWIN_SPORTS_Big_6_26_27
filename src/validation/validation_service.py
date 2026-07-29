# -*- coding: utf-8 -*-

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from src.config.model_config import load_model_version
from src.config.path_config import load_paths_config
from src.database.dataset_versions import (
    register_dataset_version,
    update_dataset_status,
)
from src.database.execution_runs import (
    ExecutionRun,
    fail_execution_run,
    finish_execution_run,
    start_execution_run,
)
from src.database.init_database import connect_database
from src.utils.logger import get_logger
from src.validation.dataset_validator import (
    ValidationIssue,
    ValidationResult,
    validate_dataset,
)
from src.validation.validation_report import create_validation_report


logger = get_logger("validation.service")


@dataclass
class ValidationServiceResult:
    run: ExecutionRun
    validation: ValidationResult
    report_path: Path
    dataset_version: str
    dataset_status: str
    record_count: int


class ValidationServiceError(RuntimeError):
    """Erro ocorrido durante o serviço completo de validação."""


def run_dataset_validation(
    dataset_path: str | Path | None = None,
    dataset_version: str | None = None,
) -> ValidationServiceResult:
    """
    Executa o fluxo completo de validação do dataset.

    Fluxo:
    - resolve o caminho do dataset;
    - regista ou atualiza a versão;
    - inicia execution_run;
    - valida o Excel;
    - grava os problemas na SQLite;
    - cria o relatório Excel;
    - atualiza o estado do dataset;
    - termina a execução.
    """

    model_config = load_model_version()
    paths = load_paths_config()

    model_version = str(
        model_config["model_version"]
    )

    configured_dataset_version = str(
        model_config["dataset"]["expected_version"]
    )

    final_dataset_version = (
        dataset_version.strip()
        if dataset_version
        else configured_dataset_version
    )

    final_dataset_path = _resolve_dataset_path(
        dataset_path=dataset_path,
        paths=paths,
    )

    register_dataset_version(
        dataset_version=final_dataset_version,
        season_label=str(model_config["season_label"]),
        file_path=final_dataset_path,
        record_count=0,
        status="VALIDATING",
    )

    run = start_execution_run(
        run_type="VALIDATION",
        model_version=model_version,
        dataset_version=final_dataset_version,
    )

    logger.info(
        "Fluxo de validação iniciado | "
        "run_id=%s | dataset_version=%s | ficheiro=%s",
        run.run_id,
        final_dataset_version,
        final_dataset_path,
    )

    try:
        validation_result = validate_dataset(
            dataset_path=final_dataset_path,
        )

        total_records = _calculate_total_records(
            validation_result
        )

        save_validation_issues(
            run_id=run.run_id,
            dataset_version=final_dataset_version,
            issues=validation_result.issues,
        )

        report_path = create_validation_report(
            result=validation_result,
        )

        if validation_result.approved:
            execution_status = "SUCCESS"
            dataset_status = "APPROVED"
            error_message = None
        else:
            execution_status = "FAILED"
            dataset_status = "REJECTED"
            error_message = (
                "O dataset foi rejeitado pelo validador. "
                f"Erros: {validation_result.error_count}; "
                f"avisos: {validation_result.warning_count}."
            )

        update_dataset_status(
            dataset_version=final_dataset_version,
            status=dataset_status,
            record_count=total_records,
        )

        finished_run = finish_execution_run(
            run_id=run.run_id,
            status=execution_status,
            error_count=validation_result.error_count,
            warning_count=validation_result.warning_count,
            error_message=error_message,
        )

        logger.info(
            "Fluxo de validação concluído | "
            "run_id=%s | execução=%s | dataset=%s | "
            "registos=%s | relatório=%s",
            run.run_id,
            finished_run.status,
            dataset_status,
            total_records,
            report_path,
        )

        return ValidationServiceResult(
            run=finished_run,
            validation=validation_result,
            report_path=report_path,
            dataset_version=final_dataset_version,
            dataset_status=dataset_status,
            record_count=total_records,
        )

    except Exception as exc:
        logger.exception(
            "Falha no fluxo de validação | run_id=%s",
            run.run_id,
        )

        try:
            update_dataset_status(
                dataset_version=final_dataset_version,
                status="REJECTED",
            )
        except Exception:
            logger.exception(
                "Não foi possível atualizar o dataset para REJECTED."
            )

        try:
            fail_execution_run(
                run_id=run.run_id,
                error_message=str(exc),
                error_count=1,
            )
        except Exception:
            logger.exception(
                "Não foi possível finalizar a execução como FAILED."
            )

        raise ValidationServiceError(
            f"Erro no fluxo de validação: {exc}"
        ) from exc


def save_validation_issues(
    run_id: str,
    dataset_version: str,
    issues: list[ValidationIssue],
) -> int:
    """
    Grava os erros, avisos e informações da validação na SQLite.

    Antes de inserir, remove os problemas anteriormente associados
    ao mesmo run_id.
    """

    connection = connect_database()

    inserted = 0

    try:
        with connection:
            connection.execute(
                """
                DELETE FROM validation_issues
                WHERE run_id = ?
                """,
                (run_id,),
            )

            for issue in issues:
                issue_id = _create_issue_id(
                    run_id=run_id,
                )

                connection.execute(
                    """
                    INSERT INTO validation_issues (
                        issue_id,
                        run_id,
                        dataset_version,
                        severity,
                        entity_type,
                        entity_id,
                        field_name,
                        expected_value,
                        actual_value,
                        message,
                        resolved
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        issue_id,
                        run_id,
                        dataset_version,
                        issue.severity,
                        issue.entity_type,
                        issue.entity_id,
                        issue.field_name,
                        _serialize_value(issue.expected_value),
                        _serialize_value(issue.actual_value),
                        issue.message,
                    ),
                )

                inserted += 1

    finally:
        connection.close()

    logger.info(
        "Problemas de validação gravados | "
        "run_id=%s | total=%s",
        run_id,
        inserted,
    )

    return inserted


def list_validation_issues(
    run_id: str,
) -> list[dict]:
    """Lista os problemas de validação de uma execução."""

    connection = connect_database()

    try:
        rows = connection.execute(
            """
            SELECT
                issue_id,
                run_id,
                dataset_version,
                severity,
                entity_type,
                entity_id,
                field_name,
                expected_value,
                actual_value,
                message,
                resolved,
                resolution_note,
                created_at,
                resolved_at
            FROM validation_issues
            WHERE run_id = ?
            ORDER BY
                CASE severity
                    WHEN 'ERROR' THEN 1
                    WHEN 'WARNING' THEN 2
                    ELSE 3
                END,
                created_at,
                issue_id
            """,
            (run_id,),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def count_validation_issues(
    run_id: str,
) -> dict[str, int]:
    """Conta os problemas por severidade."""

    connection = connect_database()

    try:
        rows = connection.execute(
            """
            SELECT
                severity,
                COUNT(*) AS total
            FROM validation_issues
            WHERE run_id = ?
            GROUP BY severity
            """,
            (run_id,),
        ).fetchall()

        counts = {
            "ERROR": 0,
            "WARNING": 0,
            "INFO": 0,
        }

        for row in rows:
            counts[str(row["severity"])] = int(row["total"])

        return counts

    finally:
        connection.close()


def _resolve_dataset_path(
    dataset_path: str | Path | None,
    paths: dict,
) -> Path:
    """
    Resolve o caminho final do dataset.
    """

    if dataset_path is None:
        path = (
            paths["data"]["input"]
            / "FOOTWIN_Dataset_2026_27_V001.xlsx"
        )
    else:
        path = Path(dataset_path).expanduser()

        if not path.is_absolute():
            path = paths["project_root"] / path

        path = path.resolve()

    if not path.exists():
        raise ValidationServiceError(
            f"O dataset não existe: {path}"
        )

    if not path.is_file():
        raise ValidationServiceError(
            f"O caminho do dataset não é um ficheiro: {path}"
        )

    return path


def _calculate_total_records(
    validation_result: ValidationResult,
) -> int:
    """
    Calcula o total de registos relevantes do dataset.

    Inclui:
    - ligas;
    - equipas;
    - desempenhos;
    - promovidas;
    - jogos.
    """

    relevant_keys = (
        "leagues",
        "teams",
        "performance",
        "promoted",
        "fixtures",
    )

    return sum(
        int(validation_result.counts.get(key, 0))
        for key in relevant_keys
    )


def _create_issue_id(
    run_id: str,
) -> str:
    suffix = uuid.uuid4().hex[:12].upper()

    return f"{run_id}_ISSUE_{suffix}"


def _serialize_value(value) -> str | None:
    if value is None:
        return None

    if isinstance(value, dict):
        return "; ".join(
            f"{key}={item}"
            for key, item in value.items()
        )

    if isinstance(value, (list, tuple, set)):
        return ", ".join(
            str(item)
            for item in value
        )

    return str(value)
