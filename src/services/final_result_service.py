# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from src.database.init_database import connect_database
from src.utils.logger import get_logger


logger = get_logger("services.final_result_service")


DEFAULT_MINUTES_AFTER_KICKOFF = 120
DEFAULT_TIMEOUT_SECONDS = 30

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


class FinalResultServiceError(RuntimeError):
    """Erro ocorrido durante a recolha de resultados finais."""


@dataclass(frozen=True)
class FinalResult:
    """Resultado final recolhido da fonte oficial."""

    match_id: str
    home_goals: int
    away_goals: int
    source_url: str


@dataclass(frozen=True)
class FinalResultRunSummary:
    """Resumo de uma execução do serviço."""

    eligible_matches: int
    checked_matches: int
    updated_matches: int
    unavailable_matches: int
    failed_matches: int


def utc_now_iso() -> str:
    """Devolve a hora UTC atual em formato ISO 8601."""

    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


def parse_match_datetime(value: str) -> datetime:
    """
    Converte a data guardada em SQLite para datetime.

    As datas sem fuso horário são interpretadas como hora de Portugal
    continental durante o horário de verão de agosto, equivalente a UTC+1.
    """

    cleaned = value.strip()

    try:
        parsed = datetime.fromisoformat(
            cleaned.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise FinalResultServiceError(
            f"Data de jogo inválida: {value!r}"
        ) from exc

    if parsed.tzinfo is None:
        portugal_summer_offset = timezone(
            timedelta(hours=1)
        )
        parsed = parsed.replace(
            tzinfo=portugal_summer_offset
        )

    return parsed.astimezone(timezone.utc)


def get_eligible_matches(
    connection: sqlite3.Connection,
    *,
    league_id: str | None = None,
    season_label: str | None = None,
    minutes_after_kickoff: int = DEFAULT_MINUTES_AFTER_KICKOFF,
    now_utc: datetime | None = None,
) -> list[sqlite3.Row]:
    """
    Obtém jogos elegíveis para consulta do resultado final.

    Um jogo é elegível quando:
    - ainda não está marcado como PLAYED;
    - não tem ambos os golos preenchidos;
    - possui data e URL de origem;
    - já passaram pelo menos N minutos desde o início.
    """

    reference_time = (
        now_utc.astimezone(timezone.utc)
        if now_utc is not None
        else datetime.now(timezone.utc)
    )

    conditions = [
        "status NOT IN ('PLAYED', 'CANCELLED', 'ABANDONED')",
        "(home_goals IS NULL OR away_goals IS NULL)",
        "match_date IS NOT NULL",
        "TRIM(match_date) <> ''",
        "source_url IS NOT NULL",
        "TRIM(source_url) <> ''",
    ]

    parameters: list[object] = []

    if league_id:
        conditions.append("league_id = ?")
        parameters.append(league_id.strip().upper())

    if season_label:
        conditions.append("season_label = ?")
        parameters.append(season_label.strip())

    rows = connection.execute(
        f"""
        SELECT
            match_id,
            league_id,
            season_label,
            round_number,
            match_date,
            home_team_id,
            away_team_id,
            status,
            home_goals,
            away_goals,
            source_url
        FROM matches
        WHERE {" AND ".join(conditions)}
        ORDER BY match_date, match_id
        """,
        parameters,
    ).fetchall()

    threshold = timedelta(
        minutes=minutes_after_kickoff
    )

    eligible: list[sqlite3.Row] = []

    for row in rows:
        try:
            kickoff_utc = parse_match_datetime(
                str(row["match_date"])
            )
        except FinalResultServiceError:
            logger.exception(
                "Data inválida no jogo | match_id=%s | data=%s",
                row["match_id"],
                row["match_date"],
            )
            continue

        if reference_time >= kickoff_utc + threshold:
            eligible.append(row)

    return eligible


def fetch_page_html(
    source_url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Descarrega o HTML da página oficial do jogo."""

    response = requests.get(
        source_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        },
        timeout=timeout_seconds,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response.text


def extract_final_score(html: str) -> tuple[int, int] | None:
    """
    Extrai o marcador final do cabeçalho da página Liga Portugal.

    Só aceita o marcador quando o respetivo elemento estiver marcado
    como terminado: classe CSS 'ended' ou 'finished'.
    """

    soup = BeautifulSoup(html, "html.parser")

    selectors = (
        ".match_header_info_result "
        ".match-item-row-score.ended",
        ".match_header_info_result "
        ".match-item-row-score.finished",
    )

    score_element = None

    for selector in selectors:
        score_element = soup.select_one(selector)
        if score_element is not None:
            break

    if score_element is None:
        return None

    score_text = score_element.get_text(
        " ",
        strip=True,
    )

    match = re.search(
        r"(?<!\d)(\d{1,2})\s*[-–:]\s*(\d{1,2})(?!\d)",
        score_text,
    )

    if match is None:
        return None

    home_goals = int(match.group(1))
    away_goals = int(match.group(2))

    return home_goals, away_goals


def collect_final_result(
    match_id: str,
    source_url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> FinalResult | None:
    """Consulta e interpreta o resultado final de um jogo."""

    html = fetch_page_html(
        source_url,
        timeout_seconds=timeout_seconds,
    )

    score = extract_final_score(html)

    if score is None:
        return None

    home_goals, away_goals = score

    return FinalResult(
        match_id=match_id,
        home_goals=home_goals,
        away_goals=away_goals,
        source_url=source_url,
    )


def update_match_result(
    connection: sqlite3.Connection,
    result: FinalResult,
) -> None:
    """Grava o resultado final na tabela matches."""

    cursor = connection.execute(
        """
        UPDATE matches
        SET
            status = 'PLAYED',
            home_goals = ?,
            away_goals = ?,
            updated_at = ?
        WHERE match_id = ?
        """,
        (
            result.home_goals,
            result.away_goals,
            utc_now_iso(),
            result.match_id,
        ),
    )

    if cursor.rowcount != 1:
        raise FinalResultServiceError(
            "Não foi possível atualizar exatamente um jogo: "
            f"{result.match_id}"
        )


def run_final_result_update(
    *,
    league_id: str | None = None,
    season_label: str | None = None,
    minutes_after_kickoff: int = DEFAULT_MINUTES_AFTER_KICKOFF,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    database_path: str | Path | None = None,
) -> FinalResultRunSummary:
    """Procura e grava todos os resultados finais elegíveis."""

    connection = connect_database(database_path)

    checked_matches = 0
    updated_matches = 0
    unavailable_matches = 0
    failed_matches = 0

    try:
        eligible_matches = get_eligible_matches(
            connection,
            league_id=league_id,
            season_label=season_label,
            minutes_after_kickoff=minutes_after_kickoff,
        )

        logger.info(
            "Jogos elegíveis para resultado final | total=%s",
            len(eligible_matches),
        )

        for row in eligible_matches:
            checked_matches += 1

            match_id = str(row["match_id"])
            source_url = str(row["source_url"])

            logger.info(
                "A consultar resultado | match_id=%s | url=%s",
                match_id,
                source_url,
            )

            try:
                result = collect_final_result(
                    match_id=match_id,
                    source_url=source_url,
                    timeout_seconds=timeout_seconds,
                )

                if result is None:
                    unavailable_matches += 1

                    logger.info(
                        "Resultado final ainda indisponível | "
                        "match_id=%s",
                        match_id,
                    )
                    continue

                with connection:
                    update_match_result(
                        connection,
                        result,
                    )

                updated_matches += 1

                logger.info(
                    "Resultado final gravado | "
                    "match_id=%s | resultado=%s-%s",
                    result.match_id,
                    result.home_goals,
                    result.away_goals,
                )

            except Exception:
                failed_matches += 1

                logger.exception(
                    "Falha ao processar resultado | "
                    "match_id=%s",
                    match_id,
                )

        return FinalResultRunSummary(
            eligible_matches=len(eligible_matches),
            checked_matches=checked_matches,
            updated_matches=updated_matches,
            unavailable_matches=unavailable_matches,
            failed_matches=failed_matches,
        )

    finally:
        connection.close()
