# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.model_config import load_full_model_config
from src.database.init_database import connect_database
from src.models.lineup_context_service import (
    MatchLineupContext,
    load_match_lineup_context,
)
from src.models.match_prediction_service import (
    MatchPrediction,
    predict_match,
)
from src.utils.logger import get_logger


logger = get_logger(
    "models.prediction_storage_service"
)


@dataclass
class PredictionStorageResult:
    matches_processed: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: int = 0


class PredictionStorageError(RuntimeError):
    """Erro durante a gravação das previsões."""


def predict_and_store_matches(
    season_label: str = "2026/27",
    model_version: str | None = None,
    dataset_version: str | None = None,
    league_id: str | None = None,
    round_number: int | None = None,
    match_id: str | None = None,
    prediction_stage: str = "PRE_MATCH",
    run_id: str | None = None,
    max_goals: int = 12,
    score_limit: int = 10,
    database_path: str | Path | None = None,
) -> PredictionStorageResult:
    """
    Calcula e guarda previsões para jogos calendarizados.

    É possível filtrar por:
    - dataset_version;
    - league_id;
    - round_number;
    - match_id.

    A operação é atómica:
    1. Carrega os jogos elegíveis.
    2. Calcula todas as previsões sem gravar.
    3. Se alguma previsão falhar, nenhuma é gravada.
    4. Grava tudo numa única transação.
    5. Qualquer erro provoca rollback total.
    """

    final_prediction_stage = str(
        prediction_stage
    ).strip().upper()

    allowed_prediction_stages = {
        "PRE_MATCH",
        "CONFIRMED_LINEUP",
        "MANUAL_OVERRIDE",
    }

    if (
        final_prediction_stage
        not in allowed_prediction_stages
    ):
        raise PredictionStorageError(
            "prediction_stage inválido: "
            f"{prediction_stage}."
        )


    final_model_version = (
        model_version.strip()
        if model_version
        else get_configured_model_version()
    )

    connection = connect_database(
        database_path
    )

    result = PredictionStorageResult()

    try:
        matches = load_matches_for_prediction(
            connection=connection,
            season_label=season_label,
            dataset_version=dataset_version,
            league_id=league_id,
            round_number=round_number,
            match_id=match_id,
        )

        if not matches:
            raise PredictionStorageError(
                "Não foram encontrados jogos elegíveis "
                "para previsão."
            )

        prepared_records: list[
            dict[str, Any]
        ] = []

        preparation_errors: list[str] = []

        # ======================================================
        # FASE 1 — Calcular todas as previsões sem gravar
        # ======================================================

        for match in matches:
            try:
                prediction = predict_match(
                    home_team_id=str(
                        match["home_team_id"]
                    ),
                    away_team_id=str(
                        match["away_team_id"]
                    ),
                    season_label=season_label,
                    model_version=(
                        final_model_version
                    ),
                    match_id=str(
                        match["match_id"]
                    ),
                    prediction_stage=(
                        final_prediction_stage
                    ),
                    max_goals=max_goals,
                    score_limit=score_limit,
                    database_path=database_path,
                )

                lineup_context: (
                    MatchLineupContext | None
                ) = None

                if (
                    final_prediction_stage
                    == "CONFIRMED_LINEUP"
                ):
                    lineup_context = (
                        load_match_lineup_context(
                            match_id=str(
                                match["match_id"]
                            ),
                            database_path=(
                                database_path
                            ),
                        )
                    )

                    if lineup_context is None:
                        raise PredictionStorageError(
                            "Não foi possível carregar "
                            "o onze confirmado durante "
                            "a preparação da previsão."
                        )

                record = build_prediction_record(
                    match=match,
                    prediction=prediction,
                    run_id=run_id,
                    prediction_stage=(
                        final_prediction_stage
                    ),
                    lineup_context=(
                        lineup_context
                    ),
                )

                prepared_records.append(
                    record
                )

                result.matches_processed += 1

            except Exception as exc:
                result.errors += 1

                message = (
                    f"match_id="
                    f"{match.get('match_id')} | "
                    f"erro={exc}"
                )

                preparation_errors.append(
                    message
                )

                logger.error(
                    "Erro ao preparar previsão | %s",
                    message,
                )

        if preparation_errors:
            details = "\n".join(
                f" - {message}"
                for message
                in preparation_errors
            )

            raise PredictionStorageError(
                "A gravação foi cancelada antes "
                "da transação. "
                f"Foram encontrados "
                f"{result.errors} erro(s):\n"
                f"{details}"
            )

        available_columns = get_table_columns(
            connection=connection,
            table_name="match_predictions",
        )

        if not available_columns:
            raise PredictionStorageError(
                "A tabela match_predictions "
                "não existe ou não possui colunas."
            )

        validate_required_table_columns(
            connection=connection,
            available_columns=available_columns,
        )

        # ======================================================
        # FASE 2 — Gravar tudo numa transação
        # ======================================================

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            for record in prepared_records:
                action = upsert_prediction(
                    connection=connection,
                    record=record,
                    available_columns=(
                        available_columns
                    ),
                )

                if action == "INSERTED":
                    result.inserted += 1

                elif action == "UPDATED":
                    result.updated += 1

                elif action == "UNCHANGED":
                    result.unchanged += 1

                else:
                    result.skipped += 1

            validate_stored_predictions(
                connection=connection,
                records=prepared_records,
                model_version=(
                    final_model_version
                ),
                available_columns=(
                    available_columns
                ),
            )

            connection.commit()

        except Exception:
            connection.rollback()

            logger.exception(
                "Gravação das previsões "
                "revertida integralmente | "
                "modelo=%s | época=%s",
                final_model_version,
                season_label,
            )

            raise

    except PredictionStorageError:
        raise

    except sqlite3.Error as exc:
        result.errors += 1

        raise PredictionStorageError(
            "Erro SQLite durante a gravação: "
            f"{exc}"
        ) from exc

    except Exception as exc:
        result.errors += 1

        raise PredictionStorageError(
            "Erro durante a gravação "
            f"das previsões: {exc}"
        ) from exc

    finally:
        connection.close()

    logger.info(
        "Previsões concluídas | "
        "jogos=%s | inseridos=%s | "
        "atualizados=%s | inalterados=%s | "
        "ignorados=%s | erros=%s",
        result.matches_processed,
        result.inserted,
        result.updated,
        result.unchanged,
        result.skipped,
        result.errors,
    )

    return result


def load_matches_for_prediction(
    connection: sqlite3.Connection,
    season_label: str,
    dataset_version: str | None = None,
    league_id: str | None = None,
    round_number: int | None = None,
    match_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Carrega jogos elegíveis para previsão.
    """

    conditions = [
        "m.season_label = ?",
        (
            "m.status IN "
            "('SCHEDULED', 'POSTPONED')"
        ),
        "m.match_date > CURRENT_TIMESTAMP",
    ]

    parameters: list[Any] = [
        season_label,
    ]

    if dataset_version:
        conditions.append(
            "m.dataset_version = ?"
        )

        parameters.append(
            dataset_version
        )

    if league_id:
        conditions.append(
            "m.league_id = ?"
        )

        parameters.append(
            league_id.strip().upper()
        )

    if round_number is not None:
        if round_number < 1:
            raise PredictionStorageError(
                "round_number deve ser igual ou superior a 1."
            )

        conditions.append(
            "m.round_number = ?"
        )

        parameters.append(
            round_number
        )

    if match_id:
        conditions.append(
            "m.match_id = ?"
        )

        parameters.append(
            match_id.strip()
        )

    where_clause = " AND ".join(
        conditions
    )

    rows = connection.execute(
        f"""
        SELECT
            m.match_id,
            m.league_id,
            m.season_label,
            m.round_number,
            m.match_date,
            m.home_team_id,
            m.away_team_id,
            m.status,
            m.dataset_version
        FROM matches m
        INNER JOIN teams ht
            ON ht.team_id = m.home_team_id
        INNER JOIN teams at
            ON at.team_id = m.away_team_id
        WHERE {where_clause}
          AND ht.active = 1
          AND at.active = 1
        ORDER BY
            m.league_id,
            m.round_number,
            m.match_date,
            m.match_id
        """,
        parameters,
    ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def build_prediction_record(
    match: dict[str, Any],
    prediction: MatchPrediction,
    run_id: str | None,
    prediction_stage: str,
    lineup_context: (
        MatchLineupContext | None
    ) = None,
) -> dict[str, Any]:
    """
    Converte uma previsão para o formato da tabela,
    incluindo etapa, versão e contexto do onze.
    """

    if not prediction.most_likely_scores:
        raise PredictionStorageError(
            "A previsão não possui "
            "marcadores prováveis."
        )

    top_score = (
        prediction.most_likely_scores[0]
    )

    likely_scores = list(
        prediction.most_likely_scores
    )

    def format_score(index: int) -> str | None:
        if index >= len(likely_scores):
            return None

        score = likely_scores[index]

        return (
            f"{score.home_goals}-"
            f"{score.away_goals}"
        )

    prediction_timestamp = (
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        )
    )

    scores_json = json.dumps(
        [
            {
                "home_goals": (
                    score.home_goals
                ),
                "away_goals": (
                    score.away_goals
                ),
                "probability": (
                    score.probability
                ),
            }
            for score
            in prediction.most_likely_scores
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    stage = str(
        prediction_stage
    ).strip().upper()

    match_id = str(
        match["match_id"]
    )

    prediction_id = (
        f"{match_id}__"
        f"{prediction.model_version}__"
        f"{stage}__V001"
    )

    return {
        "prediction_id": prediction_id,
        "match_id": match_id,
        "prediction_stage": stage,
        "prediction_version": 1,
        "parent_prediction_id": None,

        "lineup_id": (
            lineup_context.lineup_id
            if lineup_context is not None
            else None
        ),
        "lineup_hash": (
            lineup_context.lineup_hash
            if lineup_context is not None
            else None
        ),
        "lineup_confirmed": (
            1
            if (
                lineup_context is not None
                and lineup_context.lineup_confirmed
            )
            else 0
        ),
        "lineup_data_quality": (
            lineup_context.data_quality
            if lineup_context is not None
            else "NOT_APPLICABLE"
        ),

        "is_current": 1,
        "input_snapshot_json": (
            lineup_context.to_snapshot_json()
            if lineup_context is not None
            else None
        ),
        "superseded_at": None,
        "league_id": (
            prediction.league_id
        ),
        "season_label": (
            prediction.season_label
        ),
        "model_version": (
            prediction.model_version
        ),
        "run_id": run_id,
        "prediction_timestamp": (
            prediction_timestamp
        ),

        "expected_home_goals": (
            prediction.expected_home_goals
        ),
        "expected_away_goals": (
            prediction.expected_away_goals
        ),
        "expected_total_goals": (
            prediction.expected_total_goals
        ),

        "home_xg": (
            prediction.expected_home_goals
        ),
        "away_xg": (
            prediction.expected_away_goals
        ),

        "lambda_home": (
            prediction.expected_home_goals
        ),
        "lambda_away": (
            prediction.expected_away_goals
        ),

        "home_win_probability": (
            prediction.home_win_probability
        ),
        "draw_probability": (
            prediction.draw_probability
        ),
        "away_win_probability": (
            prediction.away_win_probability
        ),

        "home_win_prob": (
            prediction.home_win_probability
        ),
        "draw_prob": (
            prediction.draw_probability
        ),
        "away_win_prob": (
            prediction.away_win_probability
        ),

        "over_15_probability": (
            prediction.over_15_probability
        ),
        "under_15_probability": (
            prediction.under_15_probability
        ),

        "over_25_probability": (
            prediction.over_25_probability
        ),
        "over_2_5_probability": (
            prediction.over_25_probability
        ),
        "under_25_probability": (
            prediction.under_25_probability
        ),

        "over_35_probability": (
            prediction.over_35_probability
        ),
        "under_35_probability": (
            prediction.under_35_probability
        ),

        "over_25_prob": (
            prediction.over_25_probability
        ),
        "under_25_prob": (
            prediction.under_25_probability
        ),

        "both_teams_to_score_probability": (
            prediction
            .both_teams_to_score_probability
        ),
        "both_teams_not_to_score_probability": (
            prediction
            .both_teams_not_to_score_probability
        ),

        "btts_probability": (
            prediction
            .both_teams_to_score_probability
        ),
        "btts_prob": (
            prediction
            .both_teams_to_score_probability
        ),

        "home_clean_sheet_probability": (
            prediction
            .home_clean_sheet_probability
        ),
        "away_clean_sheet_probability": (
            prediction
            .away_clean_sheet_probability
        ),

        "predicted_home_goals": (
            top_score.home_goals
        ),
        "predicted_away_goals": (
            top_score.away_goals
        ),

        "most_likely_home_goals": (
            top_score.home_goals
        ),
        "most_likely_away_goals": (
            top_score.away_goals
        ),
        "most_likely_score_probability": (
            top_score.probability
        ),

        "most_likely_score": (
            format_score(0)
        ),
        "second_likely_score": (
            format_score(1)
        ),
        "third_likely_score": (
            format_score(2)
        ),

        "most_likely_scores_json": (
            scores_json
        ),
        "score_probabilities_json": (
            scores_json
        ),

        "home_matchup_factor": (
            prediction.home_matchup_factor
        ),
        "away_matchup_factor": (
            prediction.away_matchup_factor
        ),

        "prediction_confidence": (
            prediction.prediction_confidence
        ),
        "confidence": (
            prediction.prediction_confidence
        ),
        "data_confidence": (
            prediction.prediction_confidence
        ),

        "dataset_version": (
            match.get("dataset_version")
        ),
    }


def upsert_prediction(
    connection: sqlite3.Connection,
    record: dict[str, Any],
    available_columns: set[str],
) -> str:
    """
    Grava previsões por etapa e por versão.

    Regras:
    - uma etapa pode ter apenas uma versão atual;
    - cálculos iguais devolvem UNCHANGED;
    - cálculos alterados desativam a versão anterior;
    - a nova versão é sempre inserida, nunca sobrescrita.
    """

    filtered_record = {
        key: value
        for key, value
        in record.items()
        if key in available_columns
    }

    required_fields = {
        "prediction_id",
        "match_id",
        "model_version",
        "prediction_stage",
        "prediction_version",
        "is_current",
    }

    missing = (
        required_fields
        - set(filtered_record)
    )

    if missing:
        raise PredictionStorageError(
            "Faltam campos obrigatórios para "
            "versionamento: "
            + ", ".join(
                sorted(missing)
            )
        )

    match_id = str(
        filtered_record["match_id"]
    )
    model_version = str(
        filtered_record["model_version"]
    )
    stage = str(
        filtered_record["prediction_stage"]
    )

    if stage == "PRE_MATCH":
        confirmed_lineup = connection.execute(
            """
            SELECT prediction_id
            FROM match_predictions
            WHERE match_id = ?
              AND model_version = ?
              AND prediction_stage = 'CONFIRMED_LINEUP'
              AND is_current = 1
            ORDER BY
                prediction_version DESC,
                created_at DESC
            LIMIT 1
            """,
            (
                match_id,
                model_version,
            ),
        ).fetchone()

        if confirmed_lineup is not None:
            logger.info(
                "PRE_MATCH congelado | "
                "match_id=%s | modelo=%s | "
                "confirmed_lineup=%s",
                match_id,
                model_version,
                confirmed_lineup["prediction_id"],
            )

            return "FROZEN"

    current = connection.execute(
        """
        SELECT *
        FROM match_predictions
        WHERE match_id = ?
          AND model_version = ?
          AND prediction_stage = ?
          AND is_current = 1
        ORDER BY
            prediction_version DESC,
            created_at DESC
        LIMIT 1
        """,
        (
            match_id,
            model_version,
            stage,
        ),
    ).fetchone()

    if current is not None:
        comparison_record = dict(
            filtered_record
        )

        comparison_record[
            "prediction_id"
        ] = current["prediction_id"]

        comparison_record[
            "prediction_version"
        ] = current["prediction_version"]

        if not prediction_has_changes(
            existing=current,
            new_values=comparison_record,
        ):
            return "UNCHANGED"

        next_version = (
            int(
                current["prediction_version"]
                or 0
            )
            + 1
        )

        superseded_at = datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        )

        connection.execute(
            """
            UPDATE match_predictions
            SET
                is_current = 0,
                superseded_at = ?
            WHERE prediction_id = ?
            """,
            (
                superseded_at,
                current["prediction_id"],
            ),
        )

    else:
        maximum_version = connection.execute(
            """
            SELECT COALESCE(
                MAX(prediction_version),
                0
            ) AS maximum_version
            FROM match_predictions
            WHERE match_id = ?
              AND model_version = ?
              AND prediction_stage = ?
            """,
            (
                match_id,
                model_version,
                stage,
            ),
        ).fetchone()["maximum_version"]

        next_version = (
            int(maximum_version or 0)
            + 1
        )

    parent_prediction_id = None

    if stage == "CONFIRMED_LINEUP":
        parent = connection.execute(
            """
            SELECT prediction_id
            FROM match_predictions
            WHERE match_id = ?
              AND model_version = ?
              AND prediction_stage = 'PRE_MATCH'
              AND is_current = 1
            ORDER BY
                prediction_version DESC
            LIMIT 1
            """,
            (
                match_id,
                model_version,
            ),
        ).fetchone()

        if parent is not None:
            parent_prediction_id = str(
                parent["prediction_id"]
            )

    filtered_record[
        "prediction_version"
    ] = next_version

    filtered_record[
        "prediction_id"
    ] = (
        f"{match_id}__"
        f"{model_version}__"
        f"{stage}__"
        f"V{next_version:03d}"
    )

    filtered_record[
        "parent_prediction_id"
    ] = parent_prediction_id

    filtered_record[
        "is_current"
    ] = 1

    filtered_record[
        "superseded_at"
    ] = None

    columns = list(
        filtered_record.keys()
    )

    placeholders = [
        f":{column}"
        for column in columns
    ]

    connection.execute(
        f"""
        INSERT INTO match_predictions (
            {", ".join(columns)}
        )
        VALUES (
            {", ".join(placeholders)}
        )
        """,
        filtered_record,
    )

    logger.info(
        "Previsão inserida | "
        "match_id=%s | stage=%s | versão=%s",
        match_id,
        stage,
        next_version,
    )

    return "INSERTED"



def prediction_has_changes(
    existing: sqlite3.Row,
    new_values: dict[str, Any],
) -> bool:
    """
    Confirma se uma previsão possui alterações relevantes.

    prediction_timestamp é ignorado na comparação.
    Assim, a repetição com os mesmos cálculos devolve
    UNCHANGED, apesar de a hora atual ser diferente.
    """

    ignored_fields = {
        "prediction_id",
        "match_id",
        "model_version",
        "prediction_stage",
        "prediction_version",
        "parent_prediction_id",
        "prediction_timestamp",
        "is_current",
        "superseded_at",
        "created_at",
        "updated_at",
    }

    existing_columns = set(
        existing.keys()
    )

    for field, new_value in new_values.items():
        if field in ignored_fields:
            continue

        if field not in existing_columns:
            continue

        existing_value = existing[field]

        if isinstance(new_value, float):
            if existing_value is None:
                return True

            try:
                difference = abs(
                    float(existing_value)
                    - new_value
                )

            except (
                TypeError,
                ValueError,
            ):
                return True

            if difference > 0.000001:
                return True

        elif existing_value != new_value:
            return True

    return False


def validate_stored_predictions(
    connection: sqlite3.Connection,
    records: list[dict[str, Any]],
    model_version: str,
    available_columns: set[str],
) -> None:
    """
    Confirma que cada previsão preparada possui uma
    versão atual gravada para o jogo, modelo e etapa.

    A validação distingue PRE_MATCH de
    CONFIRMED_LINEUP, permitindo que ambas coexistam.
    """

    if not records:
        raise PredictionStorageError(
            "Não existem previsões para validar."
        )

    supports_stages = {
        "prediction_stage",
        "prediction_version",
        "is_current",
    }.issubset(
        available_columns
    )

    for record in records:
        match_id = str(
            record["match_id"]
        )

        stage = str(
            record.get(
                "prediction_stage",
                "PRE_MATCH",
            )
        )

        if supports_stages:
            stored = connection.execute(
                """
                SELECT
                    prediction_id,
                    prediction_stage,
                    prediction_version,
                    is_current
                FROM match_predictions
                WHERE match_id = ?
                  AND model_version = ?
                  AND prediction_stage = ?
                  AND is_current = 1
                ORDER BY
                    prediction_version DESC
                LIMIT 1
                """,
                (
                    match_id,
                    model_version,
                    stage,
                ),
            ).fetchone()

        else:
            stored = connection.execute(
                """
                SELECT prediction_id
                FROM match_predictions
                WHERE match_id = ?
                  AND model_version = ?
                LIMIT 1
                """,
                (
                    match_id,
                    model_version,
                ),
            ).fetchone()

        if stored is None:
            raise PredictionStorageError(
                "Previsão não encontrada após "
                "gravação: "
                f"match_id={match_id}; "
                f"model_version={model_version}; "
                f"prediction_stage={stage}."
            )


def validate_required_table_columns(
    connection: sqlite3.Connection,
    available_columns: set[str],
) -> None:
    """
    Confirma que as colunas obrigatórias sem default
    podem ser preenchidas pelo serviço.
    """

    supplied_columns = {
        "match_id",
        "league_id",
        "season_label",
        "model_version",
        "run_id",
        "prediction_timestamp",

        "expected_home_goals",
        "expected_away_goals",
        "expected_total_goals",

        "home_xg",
        "away_xg",

        "lambda_home",
        "lambda_away",

        "home_win_probability",
        "draw_probability",
        "away_win_probability",

        "home_win_prob",
        "draw_prob",
        "away_win_prob",

        "over_15_probability",
        "under_15_probability",

        "over_25_probability",
        "under_25_probability",

        "over_35_probability",
        "under_35_probability",

        "over_25_prob",
        "under_25_prob",

        (
            "both_teams_to_score_"
            "probability"
        ),
        (
            "both_teams_not_to_score_"
            "probability"
        ),

        "btts_probability",
        "btts_prob",

        "home_clean_sheet_probability",
        "away_clean_sheet_probability",

        "predicted_home_goals",
        "predicted_away_goals",

        "most_likely_home_goals",
        "most_likely_away_goals",
        "most_likely_score_probability",

        "most_likely_scores_json",
        "score_probabilities_json",

        "home_matchup_factor",
        "away_matchup_factor",

        "prediction_confidence",
        "confidence",
        "data_confidence",

        "dataset_version",
    }

    table_info = connection.execute(
        """
        PRAGMA table_info(
            "match_predictions"
        )
        """
    ).fetchall()

    unsupported_required: list[str] = []

    for column in table_info:
        column_name = str(
            column["name"]
        )

        is_primary_key = bool(
            column["pk"]
        )

        is_not_null = bool(
            column["notnull"]
        )

        has_default = (
            column["dflt_value"]
            is not None
        )

        if is_primary_key:
            continue

        if (
            is_not_null
            and not has_default
            and column_name
            not in supplied_columns
        ):
            unsupported_required.append(
                column_name
            )

    if unsupported_required:
        raise PredictionStorageError(
            "A tabela match_predictions possui "
            "colunas NOT NULL sem valor default "
            "que o serviço ainda não preenche: "
            + ", ".join(
                sorted(
                    unsupported_required
                )
            )
        )

    if "match_id" not in available_columns:
        raise PredictionStorageError(
            "Falta a coluna match_id na tabela "
            "match_predictions."
        )

    if (
        "model_version"
        not in available_columns
    ):
        raise PredictionStorageError(
            "Falta a coluna model_version na tabela "
            "match_predictions."
        )


def list_stored_predictions(
    season_label: str = "2026/27",
    model_version: str | None = None,
    league_id: str | None = None,
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Lista as previsões guardadas juntamente com os jogos.
    """

    final_model_version = (
        model_version.strip()
        if model_version
        else get_configured_model_version()
    )

    connection = connect_database(
        database_path
    )

    try:
        conditions = [
            "p.model_version = ?",
            "m.season_label = ?",
        ]

        parameters: list[Any] = [
            final_model_version,
            season_label,
        ]

        if league_id:
            conditions.append(
                "m.league_id = ?"
            )

            parameters.append(
                league_id.strip().upper()
            )

        where_clause = " AND ".join(
            conditions
        )

        rows = connection.execute(
            f"""
            SELECT
                p.*,
                m.league_id
                    AS match_league_id,
                m.round_number,
                m.match_date,
                m.home_team_id,
                ht.team_name
                    AS home_team_name,
                m.away_team_id,
                at.team_name
                    AS away_team_name,
                m.status
                    AS match_status
            FROM match_predictions p
            INNER JOIN matches m
                ON m.match_id = p.match_id
            INNER JOIN teams ht
                ON ht.team_id = m.home_team_id
            INNER JOIN teams at
                ON at.team_id = m.away_team_id
            WHERE {where_clause}
            ORDER BY
                m.league_id,
                m.round_number,
                m.match_date,
                m.match_id
            """,
            parameters,
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def get_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    """
    Obtém as colunas existentes numa tabela SQLite.
    """

    rows = connection.execute(
        f'PRAGMA table_info("{table_name}")'
    ).fetchall()

    return {
        str(row["name"])
        for row in rows
    }


def get_configured_model_version() -> str:
    """
    Obtém a versão ativa do modelo.
    """

    config = load_full_model_config()

    try:
        return str(
            config["version"][
                "model_version"
            ]
        )

    except KeyError as exc:
        raise PredictionStorageError(
            "Não foi possível obter "
            "version.model_version."
        ) from exc
