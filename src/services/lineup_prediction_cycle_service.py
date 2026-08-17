# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.collectors.liga_portugal_lineup_collector import (
    CollectionResult,
    LigaPortugalLineupError,
    collect_match_lineup as collect_por1_lineup,
)

from src.collectors.ligue1_lineup_collector import (
    collect_match_lineup as collect_fra1_lineup,
)

from src.collectors.premier_league_lineup_collector import (
    collect_match_lineup as collect_eng1_lineup,
)

from src.collectors.laliga_lineup_collector import (
    collect_match_lineup as collect_esp1_lineup,
)

from src.collectors.seriea_lineup_collector import (
    collect_match_lineup as collect_ita1_lineup,
)
from src.collectors.bundesliga_lineup_collector import (
    collect_match_lineup as collect_ger1_lineup,
)
from src.database.init_database import connect_database
from src.models.lineup_context_service import (
    load_match_lineup_context,
)
from src.models.prediction_storage_service import (
    PredictionStorageError,
    predict_and_store_matches,
)


LEAGUE_TIMEZONES = {
    "POR1": ZoneInfo("Europe/Lisbon"),
    "ENG1": ZoneInfo("Europe/London"),
    "ESP1": ZoneInfo("Europe/Madrid"),
    "FRA1": ZoneInfo("Europe/Paris"),
    "ITA1": ZoneInfo("Europe/Rome"),
    "GER1": ZoneInfo("Europe/Berlin"),
}

DEFAULT_SEASON_LABEL = "2026/27"
DEFAULT_WINDOW_START_MINUTES = 75
DEFAULT_WINDOW_END_MINUTES = 5

PORTUGAL_TIMEZONE = ZoneInfo(
    "Europe/Lisbon"
)


class LineupPredictionCycleError(RuntimeError):
    """Erro no ciclo automático de onzes e previsões."""


@dataclass
class MatchCycleResult:
    match_id: str
    league_id: str
    round_number: int | None
    match_date: str
    home_team_name: str
    away_team_name: str
    minutes_until_kickoff: float

    collection_status: str = "NOT_EXECUTED"
    http_status: int | None = None
    home_starters: int = 0
    away_starters: int = 0
    lineup_id: str | None = None

    prediction_status: str = "NOT_EXECUTED"
    prediction_id: str | None = None
    prediction_version: int | None = None

    message: str = ""


@dataclass
class CycleRunResult:
    checked_matches: int = 0
    collections_executed: int = 0
    lineups_available: int = 0
    predictions_inserted: int = 0
    predictions_unchanged: int = 0
    predictions_updated: int = 0
    waiting_lineups: int = 0
    skipped: int = 0
    errors: int = 0

    matches: list[MatchCycleResult] = field(
        default_factory=list
    )


def parse_league_datetime(
    value: str,
    league_id: str,
) -> datetime:
    """
    Converte datas de jogos usando o timezone
    correto de cada campeonato.
    """

    cleaned = str(value).strip()

    if not cleaned:
        raise LineupPredictionCycleError(
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
        raise LineupPredictionCycleError(
            f"Data de jogo inválida: {value}"
        ) from exc

    timezone_value = LEAGUE_TIMEZONES.get(
        str(league_id).upper(),
        ZoneInfo("UTC"),
    )

    if parsed.tzinfo is not None:
        return parsed.astimezone(
            timezone_value
        )

    utc_naive_leagues = {
        "ESP1",
        "FRA1",
        "ENG1",
        "ITA1",
        "GER1",
    }

    if (
        str(league_id).upper()
        in utc_naive_leagues
    ):
        return parsed.replace(
            tzinfo=ZoneInfo("UTC")
        ).astimezone(
            timezone_value
        )

    return parsed.replace(
        tzinfo=timezone_value
    )


def normalize_now(
    value: datetime | None,
) -> datetime:
    if value is None:
        return datetime.now(
            PORTUGAL_TIMEZONE
        )

    if value.tzinfo is None:
        return value.replace(
            tzinfo=PORTUGAL_TIMEZONE
        )

    return value.astimezone(
        PORTUGAL_TIMEZONE
    )


def load_due_matches(
    connection: sqlite3.Connection,
    now_local: datetime,
    season_label: str,
    window_start_minutes: int,
    window_end_minutes: int,
    league_id: str | None = None,
    match_id: str | None = None,
) -> list[dict[str, Any]]:
    if window_start_minutes <= 0:
        raise LineupPredictionCycleError(
            "window_start_minutes deve ser superior a zero."
        )

    if window_end_minutes < -120:
        raise LineupPredictionCycleError(
            "window_end_minutes não pode ser inferior a -120."
        )

    if window_start_minutes <= window_end_minutes:
        raise LineupPredictionCycleError(
            "window_start_minutes deve ser superior "
            "a window_end_minutes."
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

    rows = connection.execute(
        f"""
        SELECT
            m.match_id,
            m.league_id,
            m.season_label,
            m.round_number,
            m.match_date,
            m.status,
            m.source_url,
            m.home_team_id,
            m.away_team_id,
            ht.team_name AS home_team_name,
            at.team_name AS away_team_name
        FROM matches AS m
        INNER JOIN teams AS ht
            ON ht.team_id = m.home_team_id
        INNER JOIN teams AS at
            ON at.team_id = m.away_team_id
        WHERE {" AND ".join(conditions)}
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

        kickoff_local = (
            parse_league_datetime(
                str(match["match_date"]),
                str(match["league_id"]),
            )
        )

        minutes_until_kickoff = (
            kickoff_local - now_local
        ).total_seconds() / 60.0

        if (
            window_end_minutes
            <= minutes_until_kickoff
            <= window_start_minutes
        ):
            match[
                "kickoff_local"
            ] = kickoff_local

            match[
                "minutes_until_kickoff"
            ] = minutes_until_kickoff

            due_matches.append(
                match
            )

    return due_matches


def get_pre_match_model_version(
    connection: sqlite3.Connection,
    match_id: str,
) -> str | None:
    row = connection.execute(
        """
        SELECT
            model_version
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


def get_active_league_model_version(
    connection: sqlite3.Connection,
    league_id: str,
    season_label: str,
) -> str | None:
    """
    Obtém o modelo ACTIVE específico da liga.

    Não altera nem reescreve o PRE_MATCH existente.
    Se a liga ainda não tiver modelo próprio ACTIVE,
    o chamador poderá usar o modelo do PRE_MATCH
    como fallback de compatibilidade.
    """

    row = connection.execute(
        """
        SELECT
            model_version
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
            str(league_id).strip().upper(),
            season_label,
        ),
    ).fetchone()

    if row is None:
        return None

    return str(
        row["model_version"]
    )


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
            prediction_stage,
            lineup_id,
            lineup_hash,
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



def collect_lineup_by_league(
    league_id: str,
    match_id: str,
    database_path: str | Path | None = None,
) -> CollectionResult:
    """
    Seleciona o collector correto por campeonato.
    """

    league = str(
        league_id
    ).upper()

    collectors = {
        "POR1": collect_por1_lineup,
        "FRA1": collect_fra1_lineup,
        "ENG1": collect_eng1_lineup,
        "ESP1": collect_esp1_lineup,
        "ITA1": collect_ita1_lineup,
        "GER1": collect_ger1_lineup,
    }

    collector = collectors.get(
        league
    )

    if collector is None:
        raise LineupPredictionCycleError(
            f"Collector ainda não configurado para {league}"
        )

    return collector(
        match_id=match_id,
        database_path=database_path,
    )


def apply_collection_result(
    item: MatchCycleResult,
    collection: CollectionResult,
) -> None:
    item.collection_status = (
        collection.fetch_status
    )

    item.http_status = (
        collection.http_status
    )

    item.home_starters = (
        collection.home_starters
    )

    item.away_starters = (
        collection.away_starters
    )

    item.lineup_id = (
        collection.lineup_id
    )

    item.message = (
        collection.message
    )


def run_lineup_prediction_cycle(
    season_label: str = DEFAULT_SEASON_LABEL,
    window_start_minutes: int = (
        DEFAULT_WINDOW_START_MINUTES
    ),
    window_end_minutes: int = (
        DEFAULT_WINDOW_END_MINUTES
    ),
    league_id: str | None = None,
    match_id: str | None = None,
    now_local: datetime | None = None,
    database_path: str | Path | None = None,
) -> CycleRunResult:
    effective_now = normalize_now(
        now_local
    )

    connection = connect_database(
        database_path
    )

    result = CycleRunResult()

    try:
        due_matches = load_due_matches(
            connection=connection,
            now_local=effective_now,
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

        for match in due_matches:
            result.checked_matches += 1

            item = MatchCycleResult(
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
                minutes_until_kickoff=float(
                    match[
                        "minutes_until_kickoff"
                    ]
                ),
            )

            try:
                pre_match_model_version = (
                    get_pre_match_model_version(
                        connection=connection,
                        match_id=item.match_id,
                    )
                )

                if pre_match_model_version is None:
                    item.collection_status = (
                        "SKIPPED"
                    )

                    item.prediction_status = (
                        "SKIPPED"
                    )

                    item.message = (
                        "Não existe uma previsão "
                        "PRE_MATCH atual."
                    )

                    result.skipped += 1
                    result.matches.append(
                        item
                    )
                    continue

                league_model_version = (
                    get_active_league_model_version(
                        connection=connection,
                        league_id=item.league_id,
                        season_label=season_label,
                    )
                )

                model_version = (
                    league_model_version
                    or pre_match_model_version
                )

                collection = (
                    collect_lineup_by_league(
                        league_id=item.league_id,
                        match_id=item.match_id,
                        database_path=(
                            database_path
                        ),
                    )
                )

                result.collections_executed += 1

                apply_collection_result(
                    item=item,
                    collection=collection,
                )

                lineup_context = (
                    load_match_lineup_context(
                        match_id=item.match_id,
                        database_path=(
                            database_path
                        ),
                    )
                )

                if lineup_context is None:
                    item.prediction_status = (
                        "WAITING_LINEUP"
                    )

                    result.waiting_lineups += 1
                    result.matches.append(
                        item
                    )
                    continue

                result.lineups_available += 1

                item.lineup_id = (
                    lineup_context.lineup_id
                )

                storage_result = (
                    predict_and_store_matches(
                        season_label=(
                            season_label
                        ),
                        model_version=(
                            model_version
                        ),
                        league_id=(
                            item.league_id
                        ),
                        round_number=(
                            item.round_number
                        ),
                        match_id=(
                            item.match_id
                        ),
                        prediction_stage=(
                            "CONFIRMED_LINEUP"
                        ),
                        database_path=(
                            database_path
                        ),
                    )
                )

                if storage_result.inserted:
                    item.prediction_status = (
                        "INSERTED"
                    )

                    result.predictions_inserted += (
                        storage_result.inserted
                    )

                elif storage_result.unchanged:
                    item.prediction_status = (
                        "UNCHANGED"
                    )

                    result.predictions_unchanged += (
                        storage_result.unchanged
                    )

                elif storage_result.updated:
                    item.prediction_status = (
                        "UPDATED"
                    )

                    result.predictions_updated += (
                        storage_result.updated
                    )

                elif storage_result.skipped:
                    item.prediction_status = (
                        "SKIPPED"
                    )

                    result.skipped += (
                        storage_result.skipped
                    )

                else:
                    item.prediction_status = (
                        "NO_ACTION"
                    )

                current_prediction = (
                    get_current_confirmed_prediction(
                        connection=connection,
                        match_id=item.match_id,
                        model_version=model_version,
                    )
                )

                if current_prediction is not None:
                    item.prediction_id = str(
                        current_prediction[
                            "prediction_id"
                        ]
                    )

                    item.prediction_version = int(
                        current_prediction[
                            "prediction_version"
                        ]
                    )

                item.message = (
                    f"{item.message} | "
                    f"qualidade="
                    f"{lineup_context.data_quality}"
                )

            except (
                LigaPortugalLineupError,
                PredictionStorageError,
                LineupPredictionCycleError,
                sqlite3.Error,
                RuntimeError,
            ) as exc:
                item.prediction_status = (
                    "ERROR"
                )

                item.message = str(exc)

                result.errors += 1

            except Exception as exc:
                item.prediction_status = (
                    "ERROR"
                )

                item.message = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                result.errors += 1

            result.matches.append(
                item
            )

    finally:
        connection.close()

    return result


def print_cycle_result(
    result: CycleRunResult,
    now_local: datetime,
) -> None:
    print()
    print("=" * 110)
    print(
        "FOOTWIN SPORTS — CICLO DE ONZES "
        "E PREVISÕES"
    )
    print("=" * 110)

    print(
        "Hora de referência Portugal: "
        f"{now_local.isoformat()}"
    )

    if not result.matches:
        print()
        print(
            "Não existem jogos dentro da "
            "janela operacional."
        )

    for item in result.matches:
        print()
        print("-" * 110)

        print(
            f"{item.home_team_name} vs "
            f"{item.away_team_name}"
        )

        print(
            f"  match_id: "
            f"{item.match_id}"
        )

        print(
            f"  Data do jogo: "
            f"{item.match_date}"
        )

        print(
            "  Minutos até ao início: "
            f"{item.minutes_until_kickoff:.2f}"
        )

        print(
            f"  Liga: "
            f"{item.league_id}"
        )

        print(
            f"  Jornada: "
            f"{item.round_number}"
        )

        print(
            "  Estado da recolha: "
            f"{item.collection_status}"
        )

        print(
            f"  HTTP: "
            f"{item.http_status}"
        )

        print(
            "  Titulares casa: "
            f"{item.home_starters}"
        )

        print(
            "  Titulares fora: "
            f"{item.away_starters}"
        )

        print(
            f"  lineup_id: "
            f"{item.lineup_id}"
        )

        print(
            "  Estado da previsão: "
            f"{item.prediction_status}"
        )

        print(
            f"  prediction_id: "
            f"{item.prediction_id}"
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
        f"Jogos na janela: "
        f"{result.checked_matches}"
    )

    print(
        f"Recolhas executadas: "
        f"{result.collections_executed}"
    )

    print(
        f"Onzes disponíveis: "
        f"{result.lineups_available}"
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
        f"À espera do onze: "
        f"{result.waiting_lineups}"
    )

    print(
        f"Ignorados: "
        f"{result.skipped}"
    )

    print(
        f"Erros: "
        f"{result.errors}"
    )

    print("=" * 110)


def parse_simulated_now(
    value: str,
) -> datetime:
    cleaned = str(value).strip()

    try:
        parsed = datetime.fromisoformat(
            cleaned.replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "A data indicada em --now-local "
            "não é válida."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=PORTUGAL_TIMEZONE
        )

    return parsed.astimezone(
        PORTUGAL_TIMEZONE
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recolhe onzes oficiais e gera "
            "previsões CONFIRMED_LINEUP."
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
    )

    parser.add_argument(
        "--window-end",
        type=int,
        default=(
            DEFAULT_WINDOW_END_MINUTES
        ),
    )

    parser.add_argument(
        "--now-local",
        type=parse_simulated_now,
        default=None,
        help=(
            "Hora simulada em Portugal, "
            "por exemplo "
            "2026-08-08T15:45:00+01:00."
        ),
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    effective_now = normalize_now(
        args.now_local
    )

    result = run_lineup_prediction_cycle(
        season_label=args.season,
        window_start_minutes=(
            args.window_start
        ),
        window_end_minutes=(
            args.window_end
        ),
        league_id=args.league,
        match_id=args.match_id,
        now_local=effective_now,
    )

    print_cycle_result(
        result=result,
        now_local=effective_now,
    )

    if result.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
