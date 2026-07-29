# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config.model_config import load_model_version
from src.config.path_config import load_paths_config
from src.database.backup_manager import BackupResult, create_database_backup
from src.database.dataset_versions import (
    DatasetVersion,
    get_dataset_version,
    update_dataset_status,
)
from src.database.execution_runs import (
    ExecutionRun,
    fail_execution_run,
    finish_execution_run,
    start_execution_run,
)
from src.importers.fixtures_importer import (
    FixturesImportResult,
    import_fixtures,
)
from src.importers.leagues_importer import (
    LeagueImportResult,
    import_leagues,
)
from src.importers.performance_importer import (
    PerformanceImportResult,
    import_performance,
)
from src.importers.teams_importer import (
    TeamImportResult,
    import_teams,
)
from src.utils.logger import get_logger


logger = get_logger("importers.service")


@dataclass
class ImportServiceResult:
    run: ExecutionRun
    dataset: DatasetVersion
    backup: BackupResult
    leagues: LeagueImportResult
    teams: TeamImportResult
    performance: PerformanceImportResult
    fixtures: FixturesImportResult

    @property
    def total_inserted(self) -> int:
        return (
            self.leagues.inserted
            + self.teams.inserted
            + self.performance.inserted
            + self.fixtures.inserted
        )

    @property
    def total_updated(self) -> int:
        return (
            self.leagues.updated
            + self.teams.updated
            + self.performance.updated
            + self.fixtures.updated
        )

    @property
    def total_unchanged(self) -> int:
        return (
            self.leagues.unchanged
            + self.teams.unchanged
            + self.performance.unchanged
            + self.fixtures.unchanged
        )

    @property
    def total_errors(self) -> int:
        return (
            self.leagues.errors
            + self.teams.errors
            + self.performance.errors
            + self.fixtures.errors
        )


class ImportServiceError(RuntimeError):
    """Erro ocorrido durante o fluxo completo de importação."""


def run_dataset_import(
    dataset_path: str | Path | None = None,
    dataset_version: str | None = None,
    require_approved_dataset: bool = True,
    mark_dataset_as_imported: bool = True,
) -> ImportServiceResult:
    """
    Executa o fluxo completo de importação do dataset.

    Etapas:
    1. Resolve o dataset.
    2. Confirma o registo da versão.
    3. Confirma aprovação, quando exigida.
    4. Cria backup da base.
    5. Inicia execution_run.
    6. Importa ligas.
    7. Importa equipas.
    8. Importa desempenhos.
    9. Importa calendário.
    10. Atualiza o dataset para IMPORTED.
    11. Finaliza a execução.
    """

    model_config = load_model_version()

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
        dataset_path
    )

    dataset = get_dataset_version(
        final_dataset_version
    )

    if dataset is None:
        raise ImportServiceError(
            "A versão do dataset não está registada: "
            f"{final_dataset_version}"
        )

    if not dataset.file_path:
        raise ImportServiceError(
            "O dataset não possui caminho de ficheiro registado."
        )

    registered_path = Path(
        dataset.file_path
    ).expanduser().resolve()

    if registered_path != final_dataset_path:
        raise ImportServiceError(
            "O ficheiro indicado não corresponde ao caminho "
            "registado para o dataset."
        )

    if require_approved_dataset and dataset.status != "APPROVED":
        raise ImportServiceError(
            f"O dataset {final_dataset_version} não está aprovado. "
            f"Estado atual: {dataset.status}"
        )

    backup = create_database_backup(
        backup_label=f"before_import_{final_dataset_version}",
        keep_latest=30,
    )

    run = start_execution_run(
        run_type="IMPORT",
        model_version=model_version,
        dataset_version=final_dataset_version,
    )

    logger.info(
        "Fluxo de importação iniciado | "
        "run_id=%s | dataset=%s | ficheiro=%s",
        run.run_id,
        final_dataset_version,
        final_dataset_path,
    )

    try:
        leagues_result = import_leagues()

        teams_result = import_teams(
            dataset_path=final_dataset_path,
            dataset_version=final_dataset_version,
            require_approved_dataset=require_approved_dataset,
        )

        performance_result = import_performance(
            dataset_path=final_dataset_path,
            dataset_version=final_dataset_version,
            require_approved_dataset=require_approved_dataset,
        )

        fixtures_result = import_fixtures(
            dataset_path=final_dataset_path,
            dataset_version=final_dataset_version,
            require_approved_dataset=require_approved_dataset,
        )

        total_errors = (
            leagues_result.errors
            + teams_result.errors
            + performance_result.errors
            + fixtures_result.errors
        )

        if total_errors > 0:
            raise ImportServiceError(
                "A importação terminou com erros internos. "
                f"Total de erros: {total_errors}"
            )

        if mark_dataset_as_imported:
            dataset = update_dataset_status(
                dataset_version=final_dataset_version,
                status="IMPORTED",
            )
        else:
            refreshed_dataset = get_dataset_version(
                final_dataset_version
            )

            if refreshed_dataset is None:
                raise ImportServiceError(
                    "Não foi possível reler a versão do dataset."
                )

            dataset = refreshed_dataset

        finished_run = finish_execution_run(
            run_id=run.run_id,
            status="SUCCESS",
            error_count=0,
            warning_count=0,
            error_message=None,
        )

        result = ImportServiceResult(
            run=finished_run,
            dataset=dataset,
            backup=backup,
            leagues=leagues_result,
            teams=teams_result,
            performance=performance_result,
            fixtures=fixtures_result,
        )

        logger.info(
            "Fluxo de importação concluído | "
            "run_id=%s | inseridos=%s | "
            "atualizados=%s | inalterados=%s",
            run.run_id,
            result.total_inserted,
            result.total_updated,
            result.total_unchanged,
        )

        return result

    except Exception as exc:
        logger.exception(
            "Falha no fluxo de importação | "
            "run_id=%s | dataset=%s",
            run.run_id,
            final_dataset_version,
        )

        try:
            fail_execution_run(
                run_id=run.run_id,
                error_message=str(exc),
                error_count=1,
                warning_count=0,
            )
        except Exception:
            logger.exception(
                "Não foi possível terminar a execução como FAILED."
            )

        raise ImportServiceError(
            f"Erro no fluxo completo de importação: {exc}"
        ) from exc


def _resolve_dataset_path(
    dataset_path: str | Path | None,
) -> Path:
    """Resolve o caminho absoluto do dataset."""

    paths = load_paths_config()

    if dataset_path is None:
        path = (
            paths["data"]["input"]
            / "FOOTWIN_Dataset_2026_27_V001.xlsx"
        )

    else:
        path = Path(
            dataset_path
        ).expanduser()

        if not path.is_absolute():
            path = (
                paths["project_root"]
                / path
            )

        path = path.resolve()

    if not path.exists():
        raise ImportServiceError(
            f"O dataset não existe: {path}"
        )

    if not path.is_file():
        raise ImportServiceError(
            f"O caminho não corresponde a um ficheiro: {path}"
        )

    return path
