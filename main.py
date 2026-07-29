# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config.league_config import get_active_leagues
from src.config.model_config import load_full_model_config
from src.config.path_config import (
    ensure_project_directories,
    load_paths_config,
)
from src.database.backup_manager import (
    create_database_backup,
    list_database_backups,
)
from src.database.dataset_versions import (
    get_dataset_version,
    list_dataset_versions,
)
from src.database.execution_runs import list_execution_runs
from src.database.init_database import (
    initialize_database,
    list_database_tables,
    run_integrity_check,
)
from src.importers.import_service import run_dataset_import
from src.importers.leagues_importer import import_leagues
from src.templates.create_dataset_template import (
    DATASET_FILENAME,
    create_dataset_template,
)
from src.utils.logger import configure_logging, get_logger
from src.validation.validation_service import run_dataset_validation


logger = get_logger("main")


PROGRAM_NAME = "FOOTWIN SPORTS BIG 6 — 2026/27"
DEFAULT_DATASET_VERSION = "DATASET_2026_27_V001"


class FootwinApplicationError(RuntimeError):
    """Erro geral da aplicação FOOTWIN SPORTS."""


def build_argument_parser() -> argparse.ArgumentParser:
    """
    Cria o parser dos argumentos da linha de comandos.
    """

    parser = argparse.ArgumentParser(
        prog="FOOTWIN SPORTS",
        description=(
            "Sistema de dados, ratings, previsões e simulações "
            "das seis principais ligas europeias."
        ),
    )

    parser.add_argument(
        "--mode",
        choices=[
            "setup",
            "create-template",
            "validate",
            "import",
            "backup",
            "status",
            "list-runs",
        ],
        help="Modo de execução.",
    )

    parser.add_argument(
        "--dataset",
        help=(
            "Caminho do dataset Excel. "
            "Quando omitido, usa o dataset oficial."
        ),
    )

    parser.add_argument(
        "--dataset-version",
        default=None,
        help=(
            "Versão do dataset. "
            f"Valor oficial: {DEFAULT_DATASET_VERSION}"
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Permite substituir ficheiros existentes.",
    )

    parser.add_argument(
        "--allow-unapproved",
        action="store_true",
        help=(
            "Permite importar um dataset não aprovado. "
            "Utilizar apenas em testes técnicos."
        ),
    )

    parser.add_argument(
        "--do-not-mark-imported",
        action="store_true",
        help=(
            "Não altera o estado do dataset para IMPORTED. "
            "Destina-se a testes."
        ),
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=[
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ],
        help="Nível dos logs.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Quantidade de registos a apresentar.",
    )

    return parser


def main() -> int:
    """
    Ponto de entrada principal da aplicação.
    """

    parser = build_argument_parser()
    args = parser.parse_args()

    configure_logging(
        log_level=args.log_level,
    )

    try:
        if args.mode is None:
            return interactive_menu()

        return execute_mode(
            mode=args.mode,
            dataset_path=args.dataset,
            dataset_version=args.dataset_version,
            overwrite=args.overwrite,
            allow_unapproved=args.allow_unapproved,
            do_not_mark_imported=args.do_not_mark_imported,
            limit=args.limit,
        )

    except KeyboardInterrupt:
        print()
        print("⚠️ Execução cancelada pelo utilizador.")

        logger.warning(
            "Execução cancelada pelo utilizador."
        )

        return 130

    except Exception as exc:
        logger.exception(
            "Falha na execução principal."
        )

        print()
        print("=" * 90)
        print("❌ ERRO NO FOOTWIN SPORTS")
        print("=" * 90)
        print(exc)
        print("=" * 90)

        return 1


def execute_mode(
    mode: str,
    dataset_path: str | None = None,
    dataset_version: str | None = None,
    overwrite: bool = False,
    allow_unapproved: bool = False,
    do_not_mark_imported: bool = False,
    limit: int = 10,
) -> int:
    """
    Encaminha cada modo para a função correspondente.
    """

    handlers = {
        "setup": lambda: run_setup(),
        "create-template": lambda: run_create_template(
            overwrite=overwrite,
        ),
        "validate": lambda: run_validate(
            dataset_path=dataset_path,
            dataset_version=dataset_version,
        ),
        "import": lambda: run_import(
            dataset_path=dataset_path,
            dataset_version=dataset_version,
            allow_unapproved=allow_unapproved,
            do_not_mark_imported=do_not_mark_imported,
        ),
        "backup": lambda: run_backup(),
        "status": lambda: run_status(),
        "list-runs": lambda: run_list_runs(
            limit=limit,
        ),
    }

    handler = handlers.get(mode)

    if handler is None:
        raise FootwinApplicationError(
            f"Modo desconhecido: {mode}"
        )

    return handler()


def interactive_menu() -> int:
    """
    Apresenta o menu interativo.
    """

    while True:
        print()
        print("=" * 76)
        print(PROGRAM_NAME)
        print("=" * 76)
        print("1  — Preparar projeto")
        print("2  — Criar template Excel")
        print("3  — Validar dataset")
        print("4  — Importar dataset")
        print("5  — Criar backup")
        print("6  — Estado do sistema")
        print("7  — Listar execuções")
        print("0  — Sair")
        print("=" * 76)

        option = input(
            "Escolhe uma opção: "
        ).strip()

        if option == "0":
            print("👋 FOOTWIN SPORTS encerrado.")
            return 0

        if option == "1":
            run_setup()

        elif option == "2":
            run_create_template(
                overwrite=False,
            )

        elif option == "3":
            dataset_path = input(
                "Caminho do dataset "
                "(Enter para usar o oficial): "
            ).strip()

            dataset_version = input(
                "Versão do dataset "
                "(Enter para usar a oficial): "
            ).strip()

            run_validate(
                dataset_path=dataset_path or None,
                dataset_version=dataset_version or None,
            )

        elif option == "4":
            dataset_path = input(
                "Caminho do dataset "
                "(Enter para usar o oficial): "
            ).strip()

            dataset_version = input(
                "Versão do dataset "
                "(Enter para usar a oficial): "
            ).strip()

            answer = input(
                "Permitir dataset não aprovado? "
                "(s/N): "
            ).strip().lower()

            allow_unapproved = answer == "s"

            run_import(
                dataset_path=dataset_path or None,
                dataset_version=dataset_version or None,
                allow_unapproved=allow_unapproved,
                do_not_mark_imported=allow_unapproved,
            )

        elif option == "5":
            run_backup()

        elif option == "6":
            run_status()

        elif option == "7":
            run_list_runs(limit=10)

        else:
            print("❌ Opção inválida.")


def run_setup() -> int:
    """
    Prepara os diretórios, configurações e SQLite.
    """

    print()
    print("=" * 90)
    print("🚀 FOOTWIN SPORTS — SETUP")
    print("=" * 90)

    paths = load_paths_config()

    created_directories = ensure_project_directories(
        paths
    )

    database_path = initialize_database()

    leagues_result = import_leagues()

    leagues = get_active_leagues()
    model_config = load_full_model_config()

    print(
        f"✅ Diretório principal: "
        f"{paths['project_root']}"
    )

    if created_directories:
        print(
            f"✅ Diretórios criados: "
            f"{len(created_directories)}"
        )
    else:
        print("✅ Estrutura de diretórios já existente")

    print(f"✅ Base SQLite: {database_path}")
    print(
        f"✅ Integridade SQLite: "
        f"{run_integrity_check()}"
    )
    print(f"✅ Ligas ativas: {len(leagues)}")
    print(
        "✅ Equipas esperadas: "
        f"{sum(item['team_count'] for item in leagues.values())}"
    )
    print(
        "✅ Jogos esperados: "
        f"{sum(item['total_matches'] for item in leagues.values())}"
    )
    print(
        "✅ Modelo: "
        f"{model_config['version']['model_version']}"
    )

    print()
    print("Importação das ligas:")
    print(
        f"  Inseridas: {leagues_result.inserted}"
    )
    print(
        f"  Atualizadas: {leagues_result.updated}"
    )
    print(
        f"  Inalteradas: {leagues_result.unchanged}"
    )
    print(
        f"  Erros: {leagues_result.errors}"
    )

    print("=" * 90)
    print("🏁 SETUP: SUCCESS")
    print("=" * 90)

    return 0


def run_create_template(
    overwrite: bool = False,
) -> int:
    """
    Cria o template Excel oficial.
    """

    print()
    print("=" * 90)
    print("📄 FOOTWIN SPORTS — CRIAR TEMPLATE")
    print("=" * 90)

    paths = load_paths_config()

    output_path = (
        paths["data"]["input"]
        / DATASET_FILENAME
    )

    if output_path.exists() and not overwrite:
        print(
            "ℹ️ O template já existe:"
        )
        print(output_path)
        print()
        print(
            "Para o substituir, executa:"
        )
        print(
            "python main.py "
            "--mode create-template --overwrite"
        )

        print("=" * 90)

        return 0

    created_path = create_dataset_template(
        output_path=output_path,
        overwrite=overwrite,
    )

    print(f"✅ Template criado: {created_path}")
    print("=" * 90)

    return 0


def run_validate(
    dataset_path: str | None = None,
    dataset_version: str | None = None,
) -> int:
    """
    Valida um dataset e cria o relatório.
    """

    print()
    print("=" * 100)
    print("🔍 FOOTWIN SPORTS — VALIDAR DATASET")
    print("=" * 100)

    result = run_dataset_validation(
        dataset_path=dataset_path,
        dataset_version=dataset_version,
    )

    print(f"Run ID: {result.run.run_id}")
    print(
        f"Versão: {result.dataset_version}"
    )
    print(
        f"Estado da execução: {result.run.status}"
    )
    print(
        f"Estado do dataset: {result.dataset_status}"
    )
    print(
        f"Registos: {result.record_count}"
    )
    print(
        f"Erros: {result.validation.error_count}"
    )
    print(
        f"Avisos: {result.validation.warning_count}"
    )
    print(
        f"Relatório: {result.report_path}"
    )

    print("=" * 100)

    if result.validation.approved:
        print("✅ DATASET APPROVED")
        return 0

    print("❌ DATASET REJECTED")

    return 2


def run_import(
    dataset_path: str | None = None,
    dataset_version: str | None = None,
    allow_unapproved: bool = False,
    do_not_mark_imported: bool = False,
) -> int:
    """
    Executa o fluxo completo de importação.
    """

    print()
    print("=" * 100)
    print("📥 FOOTWIN SPORTS — IMPORTAR DATASET")
    print("=" * 100)

    result = run_dataset_import(
        dataset_path=dataset_path,
        dataset_version=dataset_version,
        require_approved_dataset=not allow_unapproved,
        mark_dataset_as_imported=not do_not_mark_imported,
    )

    print(f"Run ID: {result.run.run_id}")
    print(
        f"Estado da execução: {result.run.status}"
    )
    print(
        f"Dataset: {result.dataset.dataset_version}"
    )
    print(
        f"Estado do dataset: {result.dataset.status}"
    )
    print(
        f"Backup: {result.backup.backup_path}"
    )

    print()
    print("Ligas:")
    print(
        f"  Inseridas: {result.leagues.inserted}"
    )
    print(
        f"  Atualizadas: {result.leagues.updated}"
    )
    print(
        f"  Inalteradas: {result.leagues.unchanged}"
    )
    print(
        f"  Erros: {result.leagues.errors}"
    )

    print()
    print("Equipas:")
    print(
        f"  Inseridas: {result.teams.inserted}"
    )
    print(
        f"  Atualizadas: {result.teams.updated}"
    )
    print(
        f"  Inalteradas: {result.teams.unchanged}"
    )
    print(
        f"  Erros: {result.teams.errors}"
    )

    print()
    print("Desempenhos:")
    print(
        f"  Inseridos: {result.performance.inserted}"
    )
    print(
        f"  Atualizados: {result.performance.updated}"
    )
    print(
        f"  Inalterados: {result.performance.unchanged}"
    )
    print(
        f"  Erros: {result.performance.errors}"
    )

    print()
    print("Jogos:")
    print(
        f"  Inseridos: {result.fixtures.inserted}"
    )
    print(
        f"  Atualizados: {result.fixtures.updated}"
    )
    print(
        f"  Inalterados: {result.fixtures.unchanged}"
    )
    print(
        f"  Erros: {result.fixtures.errors}"
    )

    print()
    print("Totais:")
    print(
        f"  Inseridos: {result.total_inserted}"
    )
    print(
        f"  Atualizados: {result.total_updated}"
    )
    print(
        f"  Inalterados: {result.total_unchanged}"
    )
    print(
        f"  Erros: {result.total_errors}"
    )

    print("=" * 100)
    print("✅ IMPORTAÇÃO CONCLUÍDA")
    print("=" * 100)

    return 0


def run_backup() -> int:
    """
    Cria um backup manual da SQLite.
    """

    print()
    print("=" * 90)
    print("💾 FOOTWIN SPORTS — BACKUP")
    print("=" * 90)

    result = create_database_backup(
        backup_label="manual",
        keep_latest=30,
    )

    print(f"✅ Backup: {result.backup_path}")
    print(f"✅ Tamanho: {result.size_bytes} bytes")
    print(
        f"✅ Integridade: "
        f"{result.integrity_status}"
    )
    print(
        f"ℹ️ Checksum idêntico: "
        f"{result.checksum_matches}"
    )
    print("=" * 90)

    return 0


def run_status() -> int:
    """
    Apresenta o estado geral do sistema.
    """

    print()
    print("=" * 110)
    print("📊 FOOTWIN SPORTS — ESTADO DO SISTEMA")
    print("=" * 110)

    paths = load_paths_config()
    leagues = get_active_leagues()
    model_config = load_full_model_config()

    database_path = paths["database"]["main"]

    print(f"Projeto: {paths['project_root']}")
    print(f"Base SQLite: {database_path}")
    print(
        f"Base existente: {database_path.exists()}"
    )

    if database_path.exists():
        print(
            f"Integridade SQLite: "
            f"{run_integrity_check()}"
        )

        tables = list_database_tables()

        print(f"Tabelas: {len(tables)}")

    print(
        f"Modelo ativo: "
        f"{model_config['version']['model_version']}"
    )
    print(
        f"Época: "
        f"{model_config['version']['season_label']}"
    )
    print(f"Ligas ativas: {len(leagues)}")
    print(
        "Equipas esperadas: "
        f"{sum(item['team_count'] for item in leagues.values())}"
    )
    print(
        "Jogos esperados: "
        f"{sum(item['total_matches'] for item in leagues.values())}"
    )

    print()
    print("Datasets:")

    datasets = list_dataset_versions(
        limit=10
    )

    if datasets:
        for dataset in datasets:
            checksum = (
                dataset.checksum_sha256[:12] + "..."
                if dataset.checksum_sha256
                else "-"
            )

            print(
                f"  {dataset.dataset_version} | "
                f"{dataset.status} | "
                f"registos={dataset.record_count} | "
                f"sha256={checksum}"
            )
    else:
        print("  Nenhum dataset registado.")

    print()
    print("Backups:")

    backups = list_database_backups()

    if backups:
        for backup in backups[:5]:
            print(
                f"  {backup.name} | "
                f"{backup.stat().st_size} bytes"
            )
    else:
        print("  Nenhum backup encontrado.")

    print()
    print("Execuções recentes:")

    runs = list_execution_runs(
        limit=5
    )

    if runs:
        for run in runs:
            print(
                f"  {run.run_id} | "
                f"{run.run_type} | "
                f"{run.status} | "
                f"erros={run.error_count}"
            )
    else:
        print("  Nenhuma execução registada.")

    print("=" * 110)

    return 0


def run_list_runs(
    limit: int = 10,
) -> int:
    """
    Lista as execuções mais recentes.
    """

    if limit <= 0:
        raise FootwinApplicationError(
            "O limite deve ser superior a zero."
        )

    runs = list_execution_runs(
        limit=limit
    )

    print()
    print("=" * 130)
    print("📋 FOOTWIN SPORTS — EXECUÇÕES")
    print("=" * 130)

    if not runs:
        print("Nenhuma execução encontrada.")
        print("=" * 130)
        return 0

    for run in runs:
        print(
            f"{run.run_id} | "
            f"{run.run_type} | "
            f"{run.status} | "
            f"dataset={run.dataset_version or '-'} | "
            f"erros={run.error_count} | "
            f"avisos={run.warning_count}"
        )

    print("=" * 130)

    return 0


if __name__ == "__main__":
    sys.exit(main())
