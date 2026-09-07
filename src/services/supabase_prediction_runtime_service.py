from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from src.database.init_database import get_database_path

load_dotenv(dotenv_path=".env")

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "",
).rstrip("/")

SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY",
    "",
)

REQUEST_TIMEOUT = 20
REQUEST_ATTEMPTS = 3
REQUEST_RETRY_DELAY_SECONDS = 1.0

PREDICTIONS_TABLE = "runtime_match_predictions"
EVALUATIONS_TABLE = "runtime_prediction_evaluations"
LINEUPS_TABLE = "runtime_match_lineups"
LINEUP_PLAYERS_TABLE = "runtime_match_lineup_players"


class SupabasePredictionRuntimeError(RuntimeError):
    pass


def _resolve_database_path(
    database_path: str | Path | None,
) -> Path:
    if database_path is None:
        return get_database_path()

    return Path(
        database_path
    ).expanduser().resolve()


def _validate_config() -> None:
    if not SUPABASE_URL:
        raise SupabasePredictionRuntimeError(
            "SUPABASE_URL não configurado."
        )

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise SupabasePredictionRuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY não configurada."
        )


def _headers(
    *,
    return_representation: bool = False,
) -> dict[str, str]:
    _validate_config()

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": (
            f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"
        ),
        "Content-Type": "application/json",
    }

    if return_representation:
        headers["Prefer"] = "return=representation"
    else:
        headers["Prefer"] = "return=minimal"

    return headers


def _raise_for_response(
    response: requests.Response,
) -> None:
    if response.ok:
        return

    try:
        data = response.json()
    except ValueError:
        data = {}

    message = (
        data.get("message")
        or data.get("error_description")
        or data.get("error")
        or response.text
        or f"Erro HTTP {response.status_code}"
    )

    raise SupabasePredictionRuntimeError(
        str(message)
    )


def _sqlite_timestamp_to_postgres(
    value: Any,
) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()

    if not cleaned:
        return None

    parsed = datetime.fromisoformat(
        cleaned.replace(
            "Z",
            "+00:00",
        )
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )
    else:
        parsed = parsed.astimezone(
            timezone.utc
        )

    return parsed.isoformat()


def _postgres_timestamp_to_sqlite(
    value: Any,
) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()

    if not cleaned:
        return None

    parsed = datetime.fromisoformat(
        cleaned.replace(
            "Z",
            "+00:00",
        )
    )

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    return parsed.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _bool_value(
    value: Any,
) -> bool:
    return bool(
        int(value or 0)
    )


def _upsert_rows(
    *,
    table: str,
    rows: list[dict[str, Any]],
    on_conflict: str,
) -> int:
    if not rows:
        return 0

    last_error: requests.RequestException | None = None

    for attempt in range(1, REQUEST_ATTEMPTS + 1):
        try:
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/{table}",
                headers={
                    **_headers(),
                    "Prefer": (
                        "resolution=merge-duplicates,"
                        "return=minimal"
                    ),
                },
                params={
                    "on_conflict": on_conflict,
                },
                json=rows,
                timeout=REQUEST_TIMEOUT,
            )

            _raise_for_response(response)

            return len(rows)

        except requests.RequestException as exc:
            last_error = exc

            if attempt >= REQUEST_ATTEMPTS:
                break

            time.sleep(
                REQUEST_RETRY_DELAY_SECONDS
                * attempt
            )

    raise SupabasePredictionRuntimeError(
        "Falha de transporte ao persistir "
        f"{table} após {REQUEST_ATTEMPTS} tentativas: "
        f"{last_error}"
    )


def _load_all_rows(
    *,
    table: str,
    order: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    page_size = 1000
    offset = 0

    while True:
        response = None
        last_error: requests.RequestException | None = None

        for attempt in range(1, REQUEST_ATTEMPTS + 1):
            try:
                response = requests.get(
                    f"{SUPABASE_URL}/rest/v1/{table}",
                    headers=_headers(),
                    params={
                        "select": "*",
                        "order": order,
                        "limit": str(page_size),
                        "offset": str(offset),
                    },
                    timeout=REQUEST_TIMEOUT,
                )

                _raise_for_response(response)
                break

            except requests.RequestException as exc:
                last_error = exc

                if attempt >= REQUEST_ATTEMPTS:
                    raise SupabasePredictionRuntimeError(
                        "Falha de transporte ao carregar "
                        f"{table} após "
                        f"{REQUEST_ATTEMPTS} tentativas: "
                        f"{last_error}"
                    ) from exc

                time.sleep(
                    REQUEST_RETRY_DELAY_SECONDS
                    * attempt
                )

        if response is None:
            raise SupabasePredictionRuntimeError(
                f"Sem resposta ao carregar {table}."
            )

        page = [
            dict(row)
            for row in response.json()
        ]

        rows.extend(page)

        if len(page) < page_size:
            break

        offset += page_size

    return rows


def load_all_runtime_predictions() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=PREDICTIONS_TABLE,
        order="prediction_id.asc",
    )


def load_all_runtime_evaluations() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=EVALUATIONS_TABLE,
        order="prediction_id.asc",
    )


def load_all_runtime_lineups() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=LINEUPS_TABLE,
        order="lineup_id.asc",
    )


def load_all_runtime_lineup_players() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=LINEUP_PLAYERS_TABLE,
        order="lineup_player_id.asc",
    )


def _load_sqlite_rows_for_match(
    *,
    connection: sqlite3.Connection,
    table: str,
    match_id: str,
    extra_where: str = "",
) -> list[sqlite3.Row]:
    sql = f"""
        SELECT *
        FROM {table}
        WHERE match_id = ?
        {extra_where}
    """

    return connection.execute(
        sql,
        (match_id,),
    ).fetchall()


def sync_match_prediction_runtime(
    *,
    match_id: str,
    database_path: str | Path,
) -> dict[str, int]:
    connection = sqlite3.connect(
        str(_resolve_database_path(database_path))
    )

    connection.row_factory = sqlite3.Row

    try:
        prediction_rows = _load_sqlite_rows_for_match(
            connection=connection,
            table="match_predictions",
            match_id=match_id,
            extra_where=(
                "AND prediction_stage = "
                "'CONFIRMED_LINEUP'"
            ),
        )

        lineup_rows = _load_sqlite_rows_for_match(
            connection=connection,
            table="match_lineups",
            match_id=match_id,
        )

        player_rows = _load_sqlite_rows_for_match(
            connection=connection,
            table="match_lineup_players",
            match_id=match_id,
        )

        runtime_player_rows = connection.execute(
            """
            SELECT DISTINCT p.*
            FROM players p
            JOIN match_lineup_players mlp
              ON mlp.player_id = p.player_id
            WHERE mlp.match_id = ?
              AND mlp.player_id IS NOT NULL
            ORDER BY p.player_id
            """,
            (match_id,),
        ).fetchall()

        evaluation_rows = _load_sqlite_rows_for_match(
            connection=connection,
            table="prediction_evaluations",
            match_id=match_id,
        )

        predictions: list[dict[str, Any]] = []

        for row in prediction_rows:
            record = dict(row)

            for field in (
                "prediction_timestamp",
                "data_cutoff",
                "created_at",
                "superseded_at",
            ):
                record[field] = (
                    _sqlite_timestamp_to_postgres(
                        record.get(field)
                    )
                )

            record["lineup_confirmed"] = _bool_value(
                record["lineup_confirmed"]
            )

            record["is_current"] = _bool_value(
                record["is_current"]
            )

            predictions.append(
                record
            )

        lineups: list[dict[str, Any]] = []

        for row in lineup_rows:
            record = dict(row)

            for field in (
                "announced_at",
                "fetched_at",
                "created_at",
                "updated_at",
            ):
                record[field] = (
                    _sqlite_timestamp_to_postgres(
                        record.get(field)
                    )
                )

            record["is_current"] = _bool_value(
                record["is_current"]
            )

            lineups.append(
                record
            )

        runtime_players: list[dict[str, Any]] = []

        for row in runtime_player_rows:
            record = dict(row)

            record["active"] = _bool_value(
                record["active"]
            )

            record["created_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("created_at")
                )
            )

            record["updated_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("updated_at")
                )
            )

            runtime_players.append(
                record
            )

        players: list[dict[str, Any]] = []

        for row in player_rows:
            record = dict(row)

            record["captain"] = _bool_value(
                record["captain"]
            )

            record["created_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("created_at")
                )
            )

            players.append(
                record
            )

        evaluations: list[dict[str, Any]] = []

        for row in evaluation_rows:
            record = dict(row)

            record.pop(
                "evaluation_id",
                None,
            )

            record["outcome_hit"] = _bool_value(
                record["outcome_hit"]
            )

            record["exact_score_hit"] = _bool_value(
                record["exact_score_hit"]
            )

            prudent_hit = record.get(
                "prudent_outcome_hit"
            )

            record["prudent_outcome_hit"] = (
                None
                if prudent_hit is None
                else _bool_value(prudent_hit)
            )

            record["evaluated_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("evaluated_at")
                )
            )

            evaluations.append(
                record
            )

        result = {
            "players": _upsert_rows(
                table=PLAYERS_TABLE,
                rows=runtime_players,
                on_conflict="player_id",
            ),
            "predictions": _upsert_rows(
                table=PREDICTIONS_TABLE,
                rows=predictions,
                on_conflict="prediction_id",
            ),
            "lineups": _upsert_rows(
                table=LINEUPS_TABLE,
                rows=lineups,
                on_conflict="lineup_id",
            ),
            "lineup_players": _upsert_rows(
                table=LINEUP_PLAYERS_TABLE,
                rows=players,
                on_conflict="lineup_player_id",
            ),
            "evaluations": _upsert_rows(
                table=EVALUATIONS_TABLE,
                rows=evaluations,
                on_conflict="prediction_id",
            ),
        }

        return result

    finally:
        connection.close()

PLAYERS_TABLE = "runtime_players"


def load_all_runtime_players() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=PLAYERS_TABLE,
        order="player_id.asc",
    )


def _load_seed_player_ids(
    *,
    seed_database_path: str | Path,
) -> set[str]:
    connection = sqlite3.connect(
        str(seed_database_path)
    )

    try:
        return {
            str(row[0])
            for row in connection.execute(
                """
                SELECT player_id
                FROM players
                """
            )
        }
    finally:
        connection.close()


def sync_runtime_players(
    *,
    database_path: str | Path,
    seed_database_path: str | Path,
) -> int:
    seed_player_ids = _load_seed_player_ids(
        seed_database_path=seed_database_path,
    )

    connection = sqlite3.connect(
        str(_resolve_database_path(database_path))
    )

    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM players
            ORDER BY player_id
            """
        ).fetchall()

        payload: list[dict[str, Any]] = []

        for row in rows:
            record = dict(row)

            player_id = str(
                record["player_id"]
            )

            if player_id in seed_player_ids:
                continue

            record["active"] = _bool_value(
                record["active"]
            )

            record["created_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("created_at")
                )
            )

            record["updated_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("updated_at")
                )
            )

            payload.append(
                record
            )

        return _upsert_rows(
            table=PLAYERS_TABLE,
            rows=payload,
            on_conflict="player_id",
        )

    finally:
        connection.close()


def hydrate_sqlite_prediction_runtime(
    *,
    database_path: str | Path,
) -> dict[str, int]:
    runtime_players = load_all_runtime_players()
    lineups = load_all_runtime_lineups()
    lineup_players = load_all_runtime_lineup_players()
    predictions = load_all_runtime_predictions()
    evaluations = load_all_runtime_evaluations()

    connection = sqlite3.connect(
        str(_resolve_database_path(database_path))
    )

    applied = {
        "players": 0,
        "lineups": 0,
        "lineup_players": 0,
        "predictions": 0,
        "evaluations": 0,
    }

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        for row in runtime_players:
            cursor = connection.execute(
                """
                INSERT INTO players (
                    player_id,
                    full_name,
                    normalized_name,
                    date_of_birth,
                    nationality,
                    primary_position,
                    active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_id)
                DO UPDATE SET
                    full_name = excluded.full_name,
                    normalized_name = excluded.normalized_name,
                    date_of_birth = excluded.date_of_birth,
                    nationality = excluded.nationality,
                    primary_position = excluded.primary_position,
                    active = excluded.active,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    row["player_id"],
                    row["full_name"],
                    row["normalized_name"],
                    row.get("date_of_birth"),
                    row.get("nationality"),
                    row.get("primary_position"),
                    1 if row["active"] else 0,
                    _postgres_timestamp_to_sqlite(
                        row.get("created_at")
                    ),
                    _postgres_timestamp_to_sqlite(
                        row.get("updated_at")
                    ),
                ),
            )

            if cursor.rowcount:
                applied["players"] += 1

        for row in lineups:
            cursor = connection.execute(
                """
                INSERT INTO match_lineups (
                    lineup_id,
                    match_id,
                    provider,
                    provider_fixture_id,
                    lineup_status,
                    home_formation,
                    away_formation,
                    lineup_hash,
                    announced_at,
                    fetched_at,
                    is_current,
                    raw_payload_json,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(lineup_id)
                DO UPDATE SET
                    match_id = excluded.match_id,
                    provider = excluded.provider,
                    provider_fixture_id = excluded.provider_fixture_id,
                    lineup_status = excluded.lineup_status,
                    home_formation = excluded.home_formation,
                    away_formation = excluded.away_formation,
                    lineup_hash = excluded.lineup_hash,
                    announced_at = excluded.announced_at,
                    fetched_at = excluded.fetched_at,
                    is_current = excluded.is_current,
                    raw_payload_json = excluded.raw_payload_json,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    row["lineup_id"],
                    row["match_id"],
                    row["provider"],
                    row.get("provider_fixture_id"),
                    row["lineup_status"],
                    row.get("home_formation"),
                    row.get("away_formation"),
                    row["lineup_hash"],
                    _postgres_timestamp_to_sqlite(
                        row.get("announced_at")
                    ),
                    _postgres_timestamp_to_sqlite(
                        row.get("fetched_at")
                    ),
                    1 if row["is_current"] else 0,
                    row.get("raw_payload_json"),
                    _postgres_timestamp_to_sqlite(
                        row.get("created_at")
                    ),
                    _postgres_timestamp_to_sqlite(
                        row.get("updated_at")
                    ),
                ),
            )

            if cursor.rowcount:
                applied["lineups"] += 1

        for row in lineup_players:
            cursor = connection.execute(
                """
                INSERT INTO match_lineup_players (
                    lineup_player_id,
                    lineup_id,
                    match_id,
                    team_id,
                    player_id,
                    provider_player_id,
                    player_name,
                    role,
                    position_code,
                    formation_position,
                    shirt_number,
                    captain,
                    mapping_status,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(lineup_player_id)
                DO UPDATE SET
                    lineup_id = excluded.lineup_id,
                    match_id = excluded.match_id,
                    team_id = excluded.team_id,
                    player_id = excluded.player_id,
                    provider_player_id = excluded.provider_player_id,
                    player_name = excluded.player_name,
                    role = excluded.role,
                    position_code = excluded.position_code,
                    formation_position = excluded.formation_position,
                    shirt_number = excluded.shirt_number,
                    captain = excluded.captain,
                    mapping_status = excluded.mapping_status,
                    created_at = excluded.created_at
                """,
                (
                    row["lineup_player_id"],
                    row["lineup_id"],
                    row["match_id"],
                    row["team_id"],
                    row.get("player_id"),
                    row.get("provider_player_id"),
                    row["player_name"],
                    row["role"],
                    row.get("position_code"),
                    row.get("formation_position"),
                    row.get("shirt_number"),
                    1 if row["captain"] else 0,
                    row["mapping_status"],
                    _postgres_timestamp_to_sqlite(
                        row.get("created_at")
                    ),
                ),
            )

            if cursor.rowcount:
                applied["lineup_players"] += 1

        for row in predictions:
            columns = [
                "prediction_id",
                "match_id",
                "model_version",
                "run_id",
                "prediction_timestamp",
                "data_cutoff",
                "lambda_home",
                "lambda_away",
                "home_win_probability",
                "draw_probability",
                "away_win_probability",
                "most_likely_score",
                "second_likely_score",
                "third_likely_score",
                "over_2_5_probability",
                "btts_probability",
                "data_confidence",
                "created_at",
                "prediction_stage",
                "prediction_version",
                "parent_prediction_id",
                "lineup_id",
                "lineup_hash",
                "lineup_confirmed",
                "lineup_data_quality",
                "is_current",
                "input_snapshot_json",
                "superseded_at",
            ]

            values = [
                row.get("prediction_id"),
                row.get("match_id"),
                row.get("model_version"),
                row.get("run_id"),
                _postgres_timestamp_to_sqlite(
                    row.get("prediction_timestamp")
                ),
                _postgres_timestamp_to_sqlite(
                    row.get("data_cutoff")
                ),
                row.get("lambda_home"),
                row.get("lambda_away"),
                row.get("home_win_probability"),
                row.get("draw_probability"),
                row.get("away_win_probability"),
                row.get("most_likely_score"),
                row.get("second_likely_score"),
                row.get("third_likely_score"),
                row.get("over_2_5_probability"),
                row.get("btts_probability"),
                row.get("data_confidence"),
                _postgres_timestamp_to_sqlite(
                    row.get("created_at")
                ),
                row.get("prediction_stage"),
                row.get("prediction_version"),
                row.get("parent_prediction_id"),
                row.get("lineup_id"),
                row.get("lineup_hash"),
                1 if row.get("lineup_confirmed") else 0,
                row.get("lineup_data_quality"),
                1 if row.get("is_current") else 0,
                row.get("input_snapshot_json"),
                _postgres_timestamp_to_sqlite(
                    row.get("superseded_at")
                ),
            ]

            update_columns = [
                column
                for column in columns
                if column != "prediction_id"
            ]

            cursor = connection.execute(
                f"""
                INSERT INTO match_predictions (
                    {", ".join(columns)}
                )
                VALUES (
                    {", ".join("?" for _ in columns)}
                )
                ON CONFLICT(prediction_id)
                DO UPDATE SET
                    {", ".join(
                        f"{column} = excluded.{column}"
                        for column in update_columns
                    )}
                """,
                values,
            )

            if cursor.rowcount:
                applied["predictions"] += 1

        for row in evaluations:
            cursor = connection.execute(
                """
                INSERT INTO prediction_evaluations (
                    prediction_id,
                    match_id,
                    model_version,
                    prediction_stage,
                    actual_home_goals,
                    actual_away_goals,
                    actual_outcome,
                    predicted_outcome,
                    outcome_hit,
                    exact_score_hit,
                    brier_score,
                    log_loss,
                    evaluated_at,
                    prudent_prediction,
                    prudent_outcome_hit
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(prediction_id)
                DO UPDATE SET
                    match_id = excluded.match_id,
                    model_version = excluded.model_version,
                    prediction_stage = excluded.prediction_stage,
                    actual_home_goals = excluded.actual_home_goals,
                    actual_away_goals = excluded.actual_away_goals,
                    actual_outcome = excluded.actual_outcome,
                    predicted_outcome = excluded.predicted_outcome,
                    outcome_hit = excluded.outcome_hit,
                    exact_score_hit = excluded.exact_score_hit,
                    brier_score = excluded.brier_score,
                    log_loss = excluded.log_loss,
                    evaluated_at = excluded.evaluated_at,
                    prudent_prediction = excluded.prudent_prediction,
                    prudent_outcome_hit = excluded.prudent_outcome_hit
                """,
                (
                    row["prediction_id"],
                    row["match_id"],
                    row["model_version"],
                    row["prediction_stage"],
                    row["actual_home_goals"],
                    row["actual_away_goals"],
                    row["actual_outcome"],
                    row["predicted_outcome"],
                    1 if row["outcome_hit"] else 0,
                    1 if row["exact_score_hit"] else 0,
                    row["brier_score"],
                    row["log_loss"],
                    _postgres_timestamp_to_sqlite(
                        row.get("evaluated_at")
                    ),
                    row.get("prudent_prediction"),
                    (
                        None
                        if row.get("prudent_outcome_hit") is None
                        else (
                            1
                            if row["prudent_outcome_hit"]
                            else 0
                        )
                    ),
                ),
            )

            if cursor.rowcount:
                applied["evaluations"] += 1

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return applied


LEARNING_MODEL_VERSIONS_TABLE = "runtime_model_versions"
LEARNING_MODEL_PARAMETERS_TABLE = "runtime_model_parameters"
LEARNING_TEAM_RATINGS_TABLE = "runtime_team_ratings"
LEARNING_MODEL_CANDIDATES_TABLE = "runtime_model_candidates"
LEARNING_PROMOTION_DECISIONS_TABLE = (
    "runtime_model_promotion_decisions"
)


def load_all_runtime_model_versions() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=LEARNING_MODEL_VERSIONS_TABLE,
        order="created_at.asc,model_version.asc",
    )


def load_all_runtime_model_parameters() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=LEARNING_MODEL_PARAMETERS_TABLE,
        order="model_version.asc,parameter_name.asc",
    )


def load_all_runtime_team_ratings() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=LEARNING_TEAM_RATINGS_TABLE,
        order="model_version.asc,team_id.asc",
    )


def load_all_runtime_model_candidates() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=LEARNING_MODEL_CANDIDATES_TABLE,
        order="created_at.asc,candidate_model_version.asc",
    )


def load_all_runtime_promotion_decisions() -> list[dict[str, Any]]:
    return _load_all_rows(
        table=LEARNING_PROMOTION_DECISIONS_TABLE,
        order="decided_at.asc,candidate_model_version.asc",
    )


def sync_league_learning_runtime(
    *,
    league_id: str,
    database_path: str | Path,
) -> dict[str, int]:
    final_league_id = str(
        league_id
    ).strip().upper()

    if not final_league_id:
        raise SupabasePredictionRuntimeError(
            "league_id é obrigatório."
        )

    connection = sqlite3.connect(
        str(_resolve_database_path(database_path))
    )
    connection.row_factory = sqlite3.Row

    try:
        model_rows = connection.execute(
            """
            SELECT *
            FROM model_versions
            WHERE league_id = ?
            ORDER BY created_at, model_version
            """,
            (final_league_id,),
        ).fetchall()

        model_versions = {
            str(row["model_version"])
            for row in model_rows
        }

        parameter_rows: list[sqlite3.Row] = []
        rating_rows: list[sqlite3.Row] = []

        if model_versions:
            placeholders = ",".join(
                "?"
                for _ in model_versions
            )

            parameter_rows = connection.execute(
                f"""
                SELECT *
                FROM model_parameters
                WHERE model_version IN ({placeholders})
                ORDER BY model_version, parameter_name
                """,
                tuple(sorted(model_versions)),
            ).fetchall()

            rating_rows = connection.execute(
                f"""
                SELECT *
                FROM team_ratings
                WHERE model_version IN ({placeholders})
                ORDER BY model_version, team_id
                """,
                tuple(sorted(model_versions)),
            ).fetchall()

        candidate_rows = connection.execute(
            """
            SELECT *
            FROM model_candidates
            WHERE league_id = ?
            ORDER BY created_at, candidate_id
            """,
            (final_league_id,),
        ).fetchall()

        decision_rows = connection.execute(
            """
            SELECT
                mc.candidate_model_version,
                mpd.decision,
                mpd.sample_size,
                mpd.brier_improvement,
                mpd.log_loss_improvement,
                mpd.outcome_accuracy_improvement,
                mpd.decision_reason,
                mpd.decided_at
            FROM model_promotion_decisions mpd
            JOIN model_candidates mc
              ON mc.candidate_id = mpd.candidate_id
            WHERE mc.league_id = ?
            ORDER BY mpd.decided_at, mc.candidate_model_version
            """,
            (final_league_id,),
        ).fetchall()

        models: list[dict[str, Any]] = []

        for row in model_rows:
            record = dict(row)

            for field in (
                "created_at",
                "activated_at",
                "retired_at",
            ):
                record[field] = (
                    _sqlite_timestamp_to_postgres(
                        record.get(field)
                    )
                )

            models.append(
                record
            )

        parameters: list[dict[str, Any]] = []

        for row in parameter_rows:
            record = dict(row)

            record.pop(
                "model_parameter_id",
                None,
            )

            record["created_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("created_at")
                )
            )

            parameters.append(
                record
            )

        ratings: list[dict[str, Any]] = []

        for row in rating_rows:
            record = dict(row)

            record.pop(
                "rating_id",
                None,
            )

            record["created_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("created_at")
                )
            )

            ratings.append(
                record
            )

        candidates: list[dict[str, Any]] = []

        for row in candidate_rows:
            record = dict(row)

            record.pop(
                "candidate_id",
                None,
            )

            for field in (
                "created_at",
                "evaluated_at",
            ):
                record[field] = (
                    _sqlite_timestamp_to_postgres(
                        record.get(field)
                    )
                )

            candidates.append(
                record
            )

        decisions: list[dict[str, Any]] = []

        for row in decision_rows:
            record = dict(row)

            record["decided_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("decided_at")
                )
            )

            decisions.append(
                record
            )

        return {
            "model_versions": _upsert_rows(
                table=LEARNING_MODEL_VERSIONS_TABLE,
                rows=models,
                on_conflict="model_version",
            ),
            "model_parameters": _upsert_rows(
                table=LEARNING_MODEL_PARAMETERS_TABLE,
                rows=parameters,
                on_conflict="model_version,parameter_name",
            ),
            "team_ratings": _upsert_rows(
                table=LEARNING_TEAM_RATINGS_TABLE,
                rows=ratings,
                on_conflict=(
                    "team_id,season_label,model_version"
                ),
            ),
            "model_candidates": _upsert_rows(
                table=LEARNING_MODEL_CANDIDATES_TABLE,
                rows=candidates,
                on_conflict="candidate_model_version",
            ),
            "promotion_decisions": _upsert_rows(
                table=LEARNING_PROMOTION_DECISIONS_TABLE,
                rows=decisions,
                on_conflict="candidate_model_version",
            ),
        }

    finally:
        connection.close()


def hydrate_sqlite_learning_runtime(
    *,
    database_path: str | Path,
) -> dict[str, int]:
    model_versions = load_all_runtime_model_versions()
    model_parameters = load_all_runtime_model_parameters()
    team_ratings = load_all_runtime_team_ratings()
    model_candidates = load_all_runtime_model_candidates()
    promotion_decisions = (
        load_all_runtime_promotion_decisions()
    )

    connection = sqlite3.connect(
        str(_resolve_database_path(database_path))
    )
    connection.row_factory = sqlite3.Row

    applied = {
        "model_versions": 0,
        "model_parameters": 0,
        "team_ratings": 0,
        "model_candidates": 0,
        "promotion_decisions": 0,
    }

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        non_active_versions = [
            row
            for row in model_versions
            if row.get("version_status") != "ACTIVE"
        ]

        active_versions = [
            row
            for row in model_versions
            if row.get("version_status") == "ACTIVE"
        ]

        for row in (
            non_active_versions
            + active_versions
        ):
            cursor = connection.execute(
                """
                INSERT INTO model_versions (
                    model_version,
                    league_id,
                    season_label,
                    parent_model_version,
                    version_status,
                    parameter_hash,
                    parameters_json,
                    created_at,
                    activated_at,
                    retired_at,
                    notes
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(model_version)
                DO UPDATE SET
                    league_id = excluded.league_id,
                    season_label = excluded.season_label,
                    parent_model_version = excluded.parent_model_version,
                    version_status = excluded.version_status,
                    parameter_hash = excluded.parameter_hash,
                    parameters_json = excluded.parameters_json,
                    created_at = excluded.created_at,
                    activated_at = excluded.activated_at,
                    retired_at = excluded.retired_at,
                    notes = excluded.notes
                """,
                (
                    row["model_version"],
                    row.get("league_id"),
                    row["season_label"],
                    row.get("parent_model_version"),
                    row["version_status"],
                    row["parameter_hash"],
                    row["parameters_json"],
                    _postgres_timestamp_to_sqlite(
                        row.get("created_at")
                    ),
                    _postgres_timestamp_to_sqlite(
                        row.get("activated_at")
                    ),
                    _postgres_timestamp_to_sqlite(
                        row.get("retired_at")
                    ),
                    row.get("notes"),
                ),
            )

            if cursor.rowcount:
                applied["model_versions"] += 1

        for row in model_parameters:
            cursor = connection.execute(
                """
                INSERT INTO model_parameters (
                    model_version,
                    parameter_name,
                    parameter_value,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(
                    model_version,
                    parameter_name
                )
                DO UPDATE SET
                    parameter_value = excluded.parameter_value,
                    created_at = excluded.created_at
                """,
                (
                    row["model_version"],
                    row["parameter_name"],
                    row["parameter_value"],
                    _postgres_timestamp_to_sqlite(
                        row.get("created_at")
                    ),
                ),
            )

            if cursor.rowcount:
                applied["model_parameters"] += 1

        for row in team_ratings:
            cursor = connection.execute(
                """
                INSERT INTO team_ratings (
                    team_id,
                    league_id,
                    season_label,
                    model_version,
                    run_id,
                    points_per_game,
                    goals_for_per_game,
                    goals_against_per_game,
                    goal_difference_per_game,
                    ppg_rating,
                    attack_rating,
                    defence_rating,
                    goal_difference_rating,
                    performance_rating,
                    absolute_rating,
                    league_relative_rating,
                    rating_confidence,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(
                    team_id,
                    season_label,
                    model_version
                )
                DO UPDATE SET
                    league_id = excluded.league_id,
                    run_id = excluded.run_id,
                    points_per_game = excluded.points_per_game,
                    goals_for_per_game = excluded.goals_for_per_game,
                    goals_against_per_game = excluded.goals_against_per_game,
                    goal_difference_per_game = excluded.goal_difference_per_game,
                    ppg_rating = excluded.ppg_rating,
                    attack_rating = excluded.attack_rating,
                    defence_rating = excluded.defence_rating,
                    goal_difference_rating = excluded.goal_difference_rating,
                    performance_rating = excluded.performance_rating,
                    absolute_rating = excluded.absolute_rating,
                    league_relative_rating = excluded.league_relative_rating,
                    rating_confidence = excluded.rating_confidence,
                    created_at = excluded.created_at
                """,
                (
                    row["team_id"],
                    row["league_id"],
                    row["season_label"],
                    row["model_version"],
                    row.get("run_id"),
                    row["points_per_game"],
                    row["goals_for_per_game"],
                    row["goals_against_per_game"],
                    row["goal_difference_per_game"],
                    row["ppg_rating"],
                    row["attack_rating"],
                    row["defence_rating"],
                    row["goal_difference_rating"],
                    row["performance_rating"],
                    row["absolute_rating"],
                    row["league_relative_rating"],
                    row["rating_confidence"],
                    _postgres_timestamp_to_sqlite(
                        row.get("created_at")
                    ),
                ),
            )

            if cursor.rowcount:
                applied["team_ratings"] += 1

        for row in model_candidates:
            cursor = connection.execute(
                """
                INSERT INTO model_candidates (
                    candidate_model_version,
                    parent_model_version,
                    league_id,
                    evaluation_scope,
                    sample_size,
                    baseline_brier_score,
                    candidate_brier_score,
                    baseline_log_loss,
                    candidate_log_loss,
                    baseline_outcome_accuracy,
                    candidate_outcome_accuracy,
                    candidate_status,
                    created_at,
                    evaluated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(candidate_model_version)
                DO UPDATE SET
                    parent_model_version = excluded.parent_model_version,
                    league_id = excluded.league_id,
                    evaluation_scope = excluded.evaluation_scope,
                    sample_size = excluded.sample_size,
                    baseline_brier_score = excluded.baseline_brier_score,
                    candidate_brier_score = excluded.candidate_brier_score,
                    baseline_log_loss = excluded.baseline_log_loss,
                    candidate_log_loss = excluded.candidate_log_loss,
                    baseline_outcome_accuracy = excluded.baseline_outcome_accuracy,
                    candidate_outcome_accuracy = excluded.candidate_outcome_accuracy,
                    candidate_status = excluded.candidate_status,
                    created_at = excluded.created_at,
                    evaluated_at = excluded.evaluated_at
                """,
                (
                    row["candidate_model_version"],
                    row["parent_model_version"],
                    row.get("league_id"),
                    row["evaluation_scope"],
                    row["sample_size"],
                    row.get("baseline_brier_score"),
                    row.get("candidate_brier_score"),
                    row.get("baseline_log_loss"),
                    row.get("candidate_log_loss"),
                    row.get("baseline_outcome_accuracy"),
                    row.get("candidate_outcome_accuracy"),
                    row["candidate_status"],
                    _postgres_timestamp_to_sqlite(
                        row.get("created_at")
                    ),
                    _postgres_timestamp_to_sqlite(
                        row.get("evaluated_at")
                    ),
                ),
            )

            if cursor.rowcount:
                applied["model_candidates"] += 1

        for row in promotion_decisions:
            candidate = connection.execute(
                """
                SELECT candidate_id
                FROM model_candidates
                WHERE candidate_model_version = ?
                """,
                (
                    row["candidate_model_version"],
                ),
            ).fetchone()

            if candidate is None:
                raise SupabasePredictionRuntimeError(
                    "Candidato runtime inexistente durante "
                    "hidratação: "
                    f"{row['candidate_model_version']}"
                )

            candidate_id = int(
                candidate["candidate_id"]
            )

            cursor = connection.execute(
                """
                INSERT INTO model_promotion_decisions (
                    candidate_id,
                    decision,
                    sample_size,
                    brier_improvement,
                    log_loss_improvement,
                    outcome_accuracy_improvement,
                    decision_reason,
                    decided_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id)
                DO UPDATE SET
                    decision = excluded.decision,
                    sample_size = excluded.sample_size,
                    brier_improvement = excluded.brier_improvement,
                    log_loss_improvement = excluded.log_loss_improvement,
                    outcome_accuracy_improvement = excluded.outcome_accuracy_improvement,
                    decision_reason = excluded.decision_reason,
                    decided_at = excluded.decided_at
                """,
                (
                    candidate_id,
                    row["decision"],
                    row["sample_size"],
                    row.get("brier_improvement"),
                    row.get("log_loss_improvement"),
                    row.get(
                        "outcome_accuracy_improvement"
                    ),
                    row["decision_reason"],
                    _postgres_timestamp_to_sqlite(
                        row.get("decided_at")
                    ),
                ),
            )

            if cursor.rowcount:
                applied["promotion_decisions"] += 1

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return applied


def sync_league_evaluation_runtime(
    *,
    league_id: str,
    database_path: str | Path,
) -> int:
    final_league_id = str(
        league_id
    ).strip().upper()

    if not final_league_id:
        raise SupabasePredictionRuntimeError(
            "league_id é obrigatório."
        )

    connection = sqlite3.connect(
        str(_resolve_database_path(database_path))
    )
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT pe.*
            FROM prediction_evaluations pe
            JOIN matches m
              ON m.match_id = pe.match_id
            WHERE m.league_id = ?
            ORDER BY pe.evaluation_id
            """,
            (final_league_id,),
        ).fetchall()

        evaluations: list[dict[str, Any]] = []

        for row in rows:
            record = dict(row)

            record.pop(
                "evaluation_id",
                None,
            )

            record["outcome_hit"] = _bool_value(
                record["outcome_hit"]
            )

            record["exact_score_hit"] = _bool_value(
                record["exact_score_hit"]
            )

            prudent_hit = record.get(
                "prudent_outcome_hit"
            )

            record["prudent_outcome_hit"] = (
                None
                if prudent_hit is None
                else _bool_value(prudent_hit)
            )

            record["evaluated_at"] = (
                _sqlite_timestamp_to_postgres(
                    record.get("evaluated_at")
                )
            )

            evaluations.append(
                record
            )

        return _upsert_rows(
            table=EVALUATIONS_TABLE,
            rows=evaluations,
            on_conflict="prediction_id",
        )

    finally:
        connection.close()
