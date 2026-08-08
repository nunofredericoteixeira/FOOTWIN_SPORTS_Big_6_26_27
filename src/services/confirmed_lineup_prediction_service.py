# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.database.init_database import connect_database
from src.models.lineup_context_service import (
    load_match_lineup_context,
)
from src.models.prediction_storage_service import (
    PredictionStorageError,
    predict_and_store_matches,
)


DEFAULT_SEASON_LABEL = "2026/27"
DEFAULT_WINDOW_START_MINUTES = 75
DEFAULT_WINDOW_END_MINUTES = 5


class ConfirmedLineupPredictionError(RuntimeError):
    """Erro no processamento automático dos onzes."""


@dataclass
class MatchProcessingResult:
    match_id: str
    league_id: str
    round_number: int | None
    match_date: str
    home_team_name: str
    away_team_name: str
    status: str
    lineup_found: bool = False
    prediction_action: str = "NOT_PROCESSED"
    prediction_version: int | None = None
    message: str = ""


@dataclass
class ConfirmedLineupRunResult:
    checked_matches: int = 0
    lineup_matches: int = 0
    predictions_inserted: int = 0
    predictions_unchanged: int = 0
    predictions_updated: int = 0
    skipped: int = 0
    errors: int = 0
    matches: list[MatchProcessingResult] = field(
        default_factory=list
    )


def parse_database_datetime(
    value: str,
) -> datetime:
    """
    Converte as datas guardadas na base para UTC.

    As datas atuais do FOOTWIN não possuem timezone.
    Nesta fase são tratadas como UTC para manter
    consistência com os restantes serviços.
    """

    cleaned = str(value).strip()

    if not cleaned:
        raise ConfirmedLineupPredictionError(
            "Foi encontrada uma data de jogo vazia."
        )

    normalized = cleaned.replace(
        "Z",
        "+00:00",
    )

    try:
        parsed = datetime.fromisoformat(
            normalized
        )
    except ValueError as exc:
        raise ConfirmedLineupPredictionError(
            f"Data de jogo inválida: {value}"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )
    else:
        parsed = parsed.astimezone(
            timezone.utc
        )

    return parsed


def load_due_matches(
    connection: sqlite3.Connection,
    now_utc: datetime,
    season_label: str,
    window_start_minutes: int,
    window_end_minutes: int,
    league_id: str | None = None,
    match_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Carrega jogos cujo início está dentro da janela
    operacional para recolha e previsão com onze.
    """

    if window_start_minutes <= 0:
        raise ConfirmedLineupPredictionError(
            "window_start_minutes deve ser superior a zero."
        )

    if window_end_minutes < 0:
        raise ConfirmedLineupPredictionError(
            "window_end_minutes não pode ser negativo."
        )

    if (
        window_start_minutes
        <= window_end_minutes
    ):
        raise ConfirmedLineupPredictionError(
            "A janela inicial deve ser superior "
            "à janela final."
        )

    lower_bound = (
        now_utc
        + timedelta(
            minutes=window_end_minutes
        )
    )

    upper_bound = (
        now_utc
        + timedelta(
            minutes=window_start_minutes
        )
    )

    conditions = [
        "m.season_label = ?",
        (
            "m.status IN "
            "('SCHEDULED', 'POSTPONED')"
        ),
        "m.match_date IS NOT NULL",
        "TRIM(m.match_date) <> ''",
    ]

    parameters: list[Any] = [
        season_label,
    ]

    if league_id:
        conditions.append(
            "m.league_id = ?"
        )
        parameters.append(
            league_id.strip().upper()
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
            ht.team_name AS home_team_name,
            at.team_name AS away_team_name
        FROM matches AS m
        INNER JOIN teams AS ht
            ON ht.team_id = m.home_team_id
        INNER JOIN teams AS at
            ON at.team_id = m.away_team_id
        WHERE {where_clause}
          AND ht.active = 1
          AND at.active = 1
        ORDER BY
            m.match_date,
            m.match_id
        """,
        parameters,
    ).fetchall()

    due_matches: list[
        dict[str, Any]
    ] = []

    for row in rows:
        match = dict(row)

        kickoff = parse_database_datetime(
            str(match["match_date"])
        )

        if (
            lower_bound
            <= kickoff
            <= upper_bound
        ):
            match["kickoff_utc"] = kickoff
            match["minutes_until_kickoff"] = (
                kickoff - now_utc
            ).total_seconds() / 60.0

            due_matches.append(
                match
            )

    return due_matches


def get_current_confirmed_prediction(
    connection: sqlite3.Connection,
    match_id: str,
    model_version: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            prediction_id,
            prediction_version,
            lineup_id,
            lineup_hash,
            prediction_timestamp,
            is_current
        FROM match_predictions
        WHERE match_id = ?
          AND model_version = ?
          AND prediction_stage =
              'CONFIRMED_LINEUP'
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


def get_pre_match_model_version(
    connection: sqlite3.Connection,
    match_id: str,
) -> str | None:
    row = connection.execute(
        """
        SELECT model_version
        FROM match_predictions
        WHERE match_id = ?
          AND prediction_stage = 'PRE_MATCH'
          AND is_current = 1
        ORDER BY
            prediction_version DESC,
            created_at DESC
        LIMIT 1
        """,
        (match_id,),
    ).fetchone()

    if row is None:
        return None

    return str(
        row["model_version"]
    )


def process_confirmed_lineup_predictions(
    season_label: str = DEFAULT_SEASON_LABEL,
    window_start_minutes: int = (
        DEFAULT_WINDOW_START_MINUTES
    ),
    window_end_minutes: int = (
        DEFAULT_WINDOW_END_MINUTES
    ),
    league_id: str | None = None,
    match_id: str | None = None,
    now_utc: datetime | None = None,
    database_path: str | Path | None = None,
) -> ConfirmedLineupRunResult:
    """
    Procura jogos dentro da janela operacional e
    recalcula previsões quando existe um onze confirmado.
    """

    effective_now = (
        now_utc.astimezone(
            timezone.utc
        )
        if (
            now_utc is not None
            and now_utc.tzinfo is not None
        )
        else (
            now_utc.replace(
                tzinfo=timezone.utc
            )
            if now_utc is not None
            else datetime.now(
                timezone.utc
            )
        )
    )

    connection = connect_database(
        database_path
    )

    result = ConfirmedLineupRunResult()

    try:
        matches = load_due_matches(
            connection=connection,
            now_utc=effective_now,
            season_label=season_label,
            window_start_minutes=(
                window_start_minutes
            ),
            window_end_minutes=(
                window_end_minutes
            ),
            league_id=league_id,
            match_id=match_id,
        )

        for match in matches:
            result.checked_matches += 1

            item = MatchProcessingResult(
                match_id=str(
                    match["match_id"]
                ),
                league_id=str(
                    match["league_id"]
                ),
                round_number=(
                    int(match["round_number"])
                    if match["round_number"]
                    is not None
                    else None
                ),
                match_date=str(
                    match["match_date"]
                ),
                home_team_name=str(
                    match["home_team_name"]
                ),
                away_team_name=str(
                    match["away_team_name"]
                ),
                status=str(
                    match["status"]
                ),
            )

            try:
                model_version = (
                    get_pre_match_model_version(
                        connection=connection,
                        match_id=item.match_id,
                    )
                )

                if model_version is None:
                    item.prediction_action = (
                        "SKIPPED"
                    )
                    item.message = (
                        "Não existe previsão PRE_MATCH atual."
                    )

                    result.skipped += 1
                    result.matches.append(
                        item
                    )
                    continue

                lineup_context = (
                    load_match_lineup_context(
                        match_id=item.match_id,
                        database_path=database_path,
                    )
                )

                if lineup_context is None:
                    item.prediction_action = (
                        "WAITING_LINEUP"
                    )
                    item.message = (
                        "Ainda não existe um onze "
                        "confirmado com 11 titulares "
                        "por equipa."
                    )

                    result.skipped += 1
                    result.matches.append(
                        item
                    )
                    continue

                item.lineup_found = True
                result.lineup_matches += 1

                storage_result = (
                    predict_and_store_matches(
                        season_label=season_label,
                        model_version=model_version,
                        league_id=item.league_id,
                        round_number=(
                            item.round_number
                        ),
                        match_id=item.match_id,
                        prediction_stage=(
                            "CONFIRMED_LINEUP"
                        ),
                        database_path=(
                            database_path
                        ),
                    )
                )

                if storage_result.inserted:
                    item.prediction_action = (
                        "INSERTED"
                    )
                    result.predictions_inserted += (
                        storage_result.inserted
                    )

                elif storage_result.unchanged:
                    item.prediction_action = (
                        "UNCHANGED"
                    )
                    result.predictions_unchanged += (
                        storage_result.unchanged
                    )

                elif storage_result.updated:
                    item.prediction_action = (
                        "UPDATED"
                    )
                    result.predictions_updated += (
                        storage_result.updated
                    )

                else:
                    item.prediction_action = (
                        "SKIPPED"
                    )
                    result.skipped += 1

                current_prediction = (
                    get_current_confirmed_prediction(
                        connection=connection,
                        match_id=item.match_id,
                        model_version=model_version,
                    )
                )

                if current_prediction is not None:
                    item.prediction_version = int(
                        current_prediction[
                            "prediction_version"
                        ]
                    )

                item.message = (
                    f"Onze confirmado processado | "
                    f"qualidade="
                    f"{lineup_context.data_quality} | "
                    f"lineup_id="
                    f"{lineup_context.lineup_id}"
                )

            except (
                PredictionStorageError,
                ConfirmedLineupPredictionError,
                sqlite3.Error,
                RuntimeError,
            ) as exc:
                result.errors += 1

                item.prediction_action = "ERROR"
                item.message = str(exc)

            result.matches.append(
                item
            )

    finally:
        connection.close()

    return result


def print_run_result(
    result: ConfirmedLineupRunResult,
) -> None:
    print()
    print("=" * 110)
    print(
        "FOOTWIN SPORTS — ONZES CONFIRMADOS"
    )
    print("=" * 110)

    if not result.matches:
        print(
            "Não existem jogos dentro da "
            "janela operacional."
        )

    for item in result.matches:
        print()
        print(
            f"{item.home_team_name} vs "
            f"{item.away_team_name}"
        )
        print(
            f"  match_id: {item.match_id}"
        )
        print(
            f"  Data: {item.match_date}"
        )
        print(
            f"  Liga: {item.league_id}"
        )
        print(
            f"  Jornada: {item.round_number}"
        )
        print(
            f"  Onze encontrado: "
            f"{item.lineup_found}"
        )
        print(
            f"  Ação: "
            f"{item.prediction_action}"
        )
        print(
            f"  Versão: "
            f"{item.prediction_version}"
        )
        print(
            f"  Mensagem: "
            f"{item.message}"
        )

    print()
    print("=" * 110)
    print("RESUMO")
    print("=" * 110)
    print(
        f"Jogos verificados: "
        f"{result.checked_matches}"
    )
    print(
        f"Jogos com onze: "
        f"{result.lineup_matches}"
    )
    print(
        f"Previsões inseridas: "
        f"{result.predictions_inserted}"
    )
    print(
        f"Previsões inalteradas: "
        f"{result.predictions_unchanged}"
    )
    print(
        f"Previsões atualizadas: "
        f"{result.predictions_updated}"
    )
    print(
        f"Ignorados/em espera: "
        f"{result.skipped}"
    )
    print(
        f"Erros: "
        f"{result.errors}"
    )
    print("=" * 110)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Processa automaticamente previsões "
            "baseadas em onzes confirmados."
        )
    )

    parser.add_argument(
        "--season",
        default=DEFAULT_SEASON_LABEL,
    )

    parser.add_argument(
        "--league",
        default=None,
    )

    parser.add_argument(
        "--match-id",
        default=None,
    )

    parser.add_argument(
        "--window-start",
        type=int,
        default=(
            DEFAULT_WINDOW_START_MINUTES
        ),
        help=(
            "Minutos máximos antes do jogo. "
            "Default: 75."
        ),
    )

    parser.add_argument(
        "--window-end",
        type=int,
        default=(
            DEFAULT_WINDOW_END_MINUTES
        ),
        help=(
            "Minutos mínimos antes do jogo. "
            "Default: 5."
        ),
    )

    parser.add_argument(
        "--now",
        default=None,
        help=(
            "Data/hora UTC simulada em formato ISO. "
            "Usado apenas em testes."
        ),
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    simulated_now = (
        parse_database_datetime(
            args.now
        )
        if args.now
        else None
    )

    result = (
        process_confirmed_lineup_predictions(
            season_label=args.season,
            window_start_minutes=(
                args.window_start
            ),
            window_end_minutes=(
                args.window_end
            ),
            league_id=args.league,
            match_id=args.match_id,
            now_utc=simulated_now,
        )
    )

    print_run_result(
        result
    )

    if result.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
