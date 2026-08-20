# -*- coding: utf-8 -*-

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.exports.simulation_excel_exporter import (
    SimulationExcelExportResult,
    export_simulation_to_excel,
)
from src.models.league_simulation_service import (
    LeagueSimulationResult,
    run_league_simulation,
)
from src.models.prediction_storage_service import (
    PredictionStorageResult,
    predict_and_store_matches,
)
from src.models.simulation_query_service import (
    SimulationSummary,
    get_simulation_by_id,
)
from src.database.init_database import connect_database
from src.utils.logger import get_logger


logger = get_logger(
    "services.league_prediction_pipeline"
)


@dataclass(frozen=True)
class LeaguePredictionPipelineResult:
    """
    Resultado final da execução integrada do pipeline.
    """

    run_id: str

    league_id: str
    season_label: str
    model_version: str

    started_at: str
    finished_at: str

    prediction_result: PredictionStorageResult
    simulation_result: LeagueSimulationResult
    simulation_summary: SimulationSummary
    excel_result: SimulationExcelExportResult


class LeaguePredictionPipelineError(RuntimeError):
    """
    Erro durante a execução integrada do pipeline.
    """


def run_league_prediction_pipeline(
    league_id: str,
    season_label: str = "2026/27",
    model_version: str | None = None,
    dataset_version: str | None = None,
    simulation_count: int = 10_000,
    random_seed: int = 202627,
    europe_places: int = 4,
    relegation_places: int = 3,
    playoff_places: int = 0,
    max_goals: int = 12,
    score_limit: int = 10,
    output_directory: str | Path | None = None,
    output_filename: str | None = None,
    database_path: str | Path | None = None,
) -> LeaguePredictionPipelineResult:
    """
    Executa o pipeline completo de uma liga.

    Etapas:

    1. Calcula e guarda as previsões dos jogos.
    2. Executa a simulação Monte Carlo da liga.
    3. Lê e valida a simulação gravada.
    4. Exporta os resultados para Excel.
    5. Devolve um resumo integrado da execução.
    """

    final_league_id = clean_required_text(
        league_id,
        "league_id",
    ).upper()

    final_season_label = clean_required_text(
        season_label,
        "season_label",
    )

    final_database_path = (
        Path(database_path)
        if database_path is not None
        else None
    )

    if model_version is not None:
        final_model_version = clean_required_text(
            model_version,
            "model_version",
        )
    else:
        connection = connect_database(
            final_database_path
        )

        try:
            row = connection.execute(
                """
                SELECT model_version
                FROM model_versions
                WHERE league_id = ?
                  AND season_label = ?
                  AND version_status = 'ACTIVE'
                ORDER BY
                    COALESCE(activated_at, created_at) DESC,
                    created_at DESC
                LIMIT 1
                """,
                (
                    final_league_id,
                    final_season_label,
                ),
            ).fetchone()
        finally:
            connection.close()

        final_model_version = (
            str(row["model_version"])
            if row is not None
            else "MODEL_0_1"
        )

    final_output_directory = (
        Path(output_directory)
        if output_directory is not None
        else Path("outputs/simulations")
    )

    run_id = build_pipeline_run_id(
        league_id=final_league_id,
        season_label=final_season_label,
    )

    started_at = utc_now_iso()

    logger.info(
        "Início do pipeline da liga | "
        "run_id=%s | liga=%s | época=%s | "
        "modelo=%s | simulações=%s",
        run_id,
        final_league_id,
        final_season_label,
        final_model_version,
        simulation_count,
    )

    # ==========================================================
    # ETAPA 1 — PREVISÕES
    # ==========================================================

    try:
        logger.info(
            "Etapa 1/4 — A calcular e guardar previsões | "
            "run_id=%s | liga=%s",
            run_id,
            final_league_id,
        )

        prediction_result = predict_and_store_matches(
            season_label=final_season_label,
            model_version=final_model_version,
            dataset_version=dataset_version,
            league_id=final_league_id,
            run_id=run_id,
            max_goals=max_goals,
            score_limit=score_limit,
            database_path=final_database_path,
        )

    except Exception as exc:
        logger.exception(
            "Falha na etapa de previsões | "
            "run_id=%s | liga=%s",
            run_id,
            final_league_id,
        )

        raise LeaguePredictionPipelineError(
            "O pipeline foi interrompido na etapa "
            "de cálculo e gravação das previsões.\n"
            f"Run ID: {run_id}\n"
            f"Liga: {final_league_id}\n"
            f"Erro original: {exc}"
        ) from exc

    # ==========================================================
    # ETAPA 2 — SIMULAÇÃO MONTE CARLO
    # ==========================================================

    try:
        logger.info(
            "Etapa 2/4 — A executar simulação Monte Carlo | "
            "run_id=%s | liga=%s",
            run_id,
            final_league_id,
        )

        simulation_result = run_league_simulation(
            league_id=final_league_id,
            season_label=final_season_label,
            model_version=final_model_version,
            simulation_count=simulation_count,
            random_seed=random_seed,
            europe_places=europe_places,
            relegation_places=relegation_places,
            playoff_places=playoff_places,
            run_id=run_id,
            database_path=final_database_path,
            store_results=True,
        )

    except Exception as exc:
        logger.exception(
            "Falha na etapa de simulação | "
            "run_id=%s | liga=%s",
            run_id,
            final_league_id,
        )

        raise LeaguePredictionPipelineError(
            "O pipeline foi interrompido na etapa "
            "de simulação Monte Carlo.\n"
            f"Run ID: {run_id}\n"
            f"Liga: {final_league_id}\n"
            f"Previsões processadas: "
            f"{prediction_result.matches_processed}\n"
            f"Erro original: {exc}"
        ) from exc

    # ==========================================================
    # ETAPA 3 — LEITURA E VALIDAÇÃO DA SIMULAÇÃO
    # ==========================================================

    try:
        logger.info(
            "Etapa 3/4 — A ler a simulação gravada | "
            "run_id=%s | simulation_id=%s",
            run_id,
            simulation_result.simulation_id,
        )

        simulation_summary = get_simulation_by_id(
            simulation_id=(
                simulation_result.simulation_id
            ),
            database_path=final_database_path,
        )

        validate_simulation_summary(
            simulation_summary=simulation_summary,
            expected_league_id=final_league_id,
            expected_season_label=final_season_label,
            expected_model_version=final_model_version,
            expected_run_id=run_id,
        )

    except Exception as exc:
        logger.exception(
            "Falha na leitura da simulação | "
            "run_id=%s | simulation_id=%s",
            run_id,
            simulation_result.simulation_id,
        )

        raise LeaguePredictionPipelineError(
            "O pipeline foi interrompido na etapa "
            "de leitura e validação da simulação.\n"
            f"Run ID: {run_id}\n"
            f"Simulation ID: "
            f"{simulation_result.simulation_id}\n"
            f"Erro original: {exc}"
        ) from exc

    # ==========================================================
    # ETAPA 4 — EXPORTAÇÃO EXCEL
    # ==========================================================

    try:
        logger.info(
            "Etapa 4/4 — A exportar a simulação para Excel | "
            "run_id=%s | simulation_id=%s",
            run_id,
            simulation_result.simulation_id,
        )

        excel_result = export_simulation_to_excel(
            simulation=simulation_summary,
            output_directory=(
                final_output_directory
            ),
            filename=output_filename,
        )

    except Exception as exc:
        logger.exception(
            "Falha na exportação Excel | "
            "run_id=%s | simulation_id=%s",
            run_id,
            simulation_result.simulation_id,
        )

        raise LeaguePredictionPipelineError(
            "O pipeline foi interrompido na etapa "
            "de exportação para Excel.\n"
            f"Run ID: {run_id}\n"
            f"Simulation ID: "
            f"{simulation_result.simulation_id}\n"
            f"Erro original: {exc}"
        ) from exc

    finished_at = utc_now_iso()

    result = LeaguePredictionPipelineResult(
        run_id=run_id,
        league_id=final_league_id,
        season_label=final_season_label,
        model_version=final_model_version,
        started_at=started_at,
        finished_at=finished_at,
        prediction_result=prediction_result,
        simulation_result=simulation_result,
        simulation_summary=simulation_summary,
        excel_result=excel_result,
    )

    logger.info(
        "Pipeline concluído com sucesso | "
        "run_id=%s | liga=%s | simulation_id=%s | "
        "Excel=%s",
        run_id,
        final_league_id,
        simulation_result.simulation_id,
        excel_result.output_path,
    )

    return result


def validate_simulation_summary(
    simulation_summary: SimulationSummary,
    expected_league_id: str,
    expected_season_label: str,
    expected_model_version: str,
    expected_run_id: str,
) -> None:
    """
    Confirma que a simulação lida corresponde à execução atual.
    """

    if simulation_summary.status.upper() != "SUCCESS":
        raise LeaguePredictionPipelineError(
            "A simulação não terminou com estado SUCCESS. "
            f"Estado encontrado: "
            f"{simulation_summary.status}"
        )

    if (
        simulation_summary.league_id.upper()
        != expected_league_id.upper()
    ):
        raise LeaguePredictionPipelineError(
            "A liga da simulação não corresponde "
            "à liga solicitada. "
            f"Esperado: {expected_league_id}; "
            f"encontrado: "
            f"{simulation_summary.league_id}."
        )

    if (
        simulation_summary.season_label
        != expected_season_label
    ):
        raise LeaguePredictionPipelineError(
            "A época da simulação não corresponde "
            "à época solicitada. "
            f"Esperado: {expected_season_label}; "
            f"encontrado: "
            f"{simulation_summary.season_label}."
        )

    if (
        simulation_summary.model_version
        != expected_model_version
    ):
        raise LeaguePredictionPipelineError(
            "A versão do modelo da simulação "
            "não corresponde à versão solicitada. "
            f"Esperado: {expected_model_version}; "
            f"encontrado: "
            f"{simulation_summary.model_version}."
        )

    if (
        simulation_summary.run_id is not None
        and simulation_summary.run_id
        != expected_run_id
    ):
        raise LeaguePredictionPipelineError(
            "O run_id da simulação não corresponde "
            "ao pipeline atual. "
            f"Esperado: {expected_run_id}; "
            f"encontrado: "
            f"{simulation_summary.run_id}."
        )

    if not simulation_summary.teams:
        raise LeaguePredictionPipelineError(
            "A simulação não possui resultados "
            "de equipas."
        )


def print_pipeline_summary(
    result: LeaguePredictionPipelineResult,
) -> None:
    """
    Mostra no Terminal o resumo final do pipeline.
    """

    prediction = result.prediction_result
    simulation = result.simulation_result
    excel = result.excel_result

    print()
    print("=" * 100)
    print("✅ PIPELINE FOOTWIN SPORTS CONCLUÍDO")
    print("=" * 100)

    print(
        f"Run ID:                  "
        f"{result.run_id}"
    )

    print(
        f"Liga:                    "
        f"{result.league_id}"
    )

    print(
        f"Época:                   "
        f"{result.season_label}"
    )

    print(
        f"Versão do modelo:        "
        f"{result.model_version}"
    )

    print(
        f"Início UTC:              "
        f"{result.started_at}"
    )

    print(
        f"Fim UTC:                 "
        f"{result.finished_at}"
    )

    print("-" * 100)
    print("PREVISÕES")
    print("-" * 100)

    print(
        f"Jogos processados:       "
        f"{prediction.matches_processed}"
    )

    print(
        f"Previsões inseridas:     "
        f"{prediction.inserted}"
    )

    print(
        f"Previsões atualizadas:   "
        f"{prediction.updated}"
    )

    print(
        f"Previsões sem alterações:"
        f" {prediction.unchanged}"
    )

    print(
        f"Previsões ignoradas:     "
        f"{prediction.skipped}"
    )

    print(
        f"Erros nas previsões:     "
        f"{prediction.errors}"
    )

    print("-" * 100)
    print("SIMULAÇÃO MONTE CARLO")
    print("-" * 100)

    print(
        f"Simulation ID:           "
        f"{simulation.simulation_id}"
    )

    print(
        f"Número de simulações:    "
        f"{simulation.simulation_count:,}"
    )

    print(
        f"Seed aleatória:          "
        f"{simulation.random_seed}"
    )

    print(
        f"Equipas simuladas:       "
        f"{len(simulation.team_results)}"
    )

    print(
        f"Estado:                  "
        f"{result.simulation_summary.status}"
    )

    print("-" * 100)
    print("EXPORTAÇÃO EXCEL")
    print("-" * 100)

    print(
        f"Ficheiro:                "
        f"{excel.output_path}"
    )

    print(
        f"Equipas exportadas:      "
        f"{excel.team_count}"
    )

    print(
        f"Folhas:                  "
        f"{', '.join(excel.sheet_names)}"
    )

    print("=" * 100)


def build_pipeline_run_id(
    league_id: str,
    season_label: str,
) -> str:
    """
    Cria um identificador único para o pipeline.
    """

    safe_season = (
        season_label
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )

    unique_suffix = uuid.uuid4().hex[:8]

    return (
        f"PIPELINE_"
        f"{league_id}_"
        f"{safe_season}_"
        f"{timestamp}_"
        f"{unique_suffix}"
    )


def clean_required_text(
    value: str,
    field_name: str,
) -> str:
    """
    Limpa e valida um texto obrigatório.
    """

    if value is None:
        raise LeaguePredictionPipelineError(
            f"O campo {field_name} é obrigatório."
        )

    cleaned = str(value).strip()

    if not cleaned:
        raise LeaguePredictionPipelineError(
            f"O campo {field_name} não pode "
            "estar vazio."
        )

    return cleaned


def utc_now_iso() -> str:
    """
    Devolve a data e hora UTC em formato ISO.
    """

    return datetime.now(
        timezone.utc
    ).isoformat()
