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


UTC_NAIVE_LEAGUES = {
    "ENG1",
    "ESP1",
    "FRA1",
    "ITA1",
    "GER1",
}


def parse_match_datetime(
    value: str,
    *,
    league_id: str | None = None,
) -> datetime:
    """
    Converte a data guardada em SQLite para UTC.

    ENG1, ESP1, FRA1, ITA1 e GER1 guardam datas naive
    que já representam UTC.
    POR1 mantém a interpretação histórica pela hora de Portugal.
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
        league = (
            league_id.strip().upper()
            if league_id
            else ""
        )

        if league in UTC_NAIVE_LEAGUES:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )
        else:
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
                str(row["match_date"]),
                league_id=str(row["league_id"]),
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


LALIGA_API_BASE_URL = (
    "https://apim.laliga.com/public-service"
)

LALIGA_SUBSCRIPTION_KEY = (
    "c13c3a8e2f6b46da9c5c425cf61fab3e"
)


def extract_laliga_provider_match_id(
    match_id: str,
) -> str | None:
    match = re.search(
        r"_LL(\d+)_",
        match_id,
    )

    if match is None:
        return None

    return match.group(1)


def collect_laliga_final_result(
    match_id: str,
    source_url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> FinalResult | None:
    provider_match_id = extract_laliga_provider_match_id(
        match_id
    )

    if provider_match_id is None:
        raise FinalResultServiceError(
            "Não foi possível extrair o ID LaLiga do jogo: "
            f"{match_id}"
        )

    response = requests.get(
        f"{LALIGA_API_BASE_URL}/api/v1/matches",
        params={
            "subscriptionSlug": "laliga-easports-2026",
            "seasonYear": 2026,
            "limit": 100,
            "orderField": "date",
            "orderType": "asc",
        },
        headers={
            "Ocp-Apim-Subscription-Key": (
                LALIGA_SUBSCRIPTION_KEY
            ),
            "Content-Language": "en",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    payload = response.json()

    for item in payload.get("matches", []):
        if str(item.get("id")) != provider_match_id:
            continue

        if item.get("status") != "FullTime":
            return None

        home_score = item.get("home_score")
        away_score = item.get("away_score")

        if (
            home_score is None
            or away_score is None
        ):
            return None

        return FinalResult(
            match_id=match_id,
            home_goals=int(home_score),
            away_goals=int(away_score),
            source_url=source_url,
        )

    return None



PREMIER_LEAGUE_API_BASE_URL = (
    "https://footballapi.pulselive.com/football"
)

PREMIER_LEAGUE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/150.0 Safari/537.36"
    ),
    "Origin": "https://www.premierleague.com",
    "Referer": "https://www.premierleague.com/",
    "Accept": "application/json",
}


def extract_premier_league_provider_match_id(
    match_id: str,
) -> str | None:
    match = re.search(
        r"_PL(\d+)_",
        match_id,
    )

    if match is None:
        return None

    return match.group(1)


def collect_premier_league_final_result(
    match_id: str,
    source_url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> FinalResult | None:
    provider_match_id = (
        extract_premier_league_provider_match_id(
            match_id
        )
    )

    if provider_match_id is None:
        raise FinalResultServiceError(
            "Não foi possível extrair o ID "
            "Premier League do jogo: "
            f"{match_id}"
        )

    response = requests.get(
        (
            f"{PREMIER_LEAGUE_API_BASE_URL}"
            f"/fixtures/{provider_match_id}"
        ),
        params={
            "altIds": "true",
        },
        headers=PREMIER_LEAGUE_HEADERS,
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    payload = response.json()

    status = str(
        payload.get("status") or ""
    ).strip().upper()

    if status != "C":
        return None

    teams = payload.get("teams")

    if (
        not isinstance(teams, list)
        or len(teams) != 2
    ):
        raise FinalResultServiceError(
            "Payload Premier League concluído "
            "sem exatamente duas equipas."
        )

    home_score = teams[0].get("score")
    away_score = teams[1].get("score")

    if (
        home_score is None
        or away_score is None
    ):
        raise FinalResultServiceError(
            "Jogo Premier League concluído "
            "sem resultado final."
        )

    return FinalResult(
        match_id=match_id,
        home_goals=int(float(home_score)),
        away_goals=int(float(away_score)),
        source_url=source_url,
    )


LIGUE1_API_BASE_URL = "https://ma-api.ligue1.fr"

LIGUE1_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def extract_ligue1_provider_match_id(
    match_id: str,
) -> str | None:
    match = re.search(
        r"_L1(\d+)_",
        match_id,
    )

    if match is None:
        return None

    return (
        "l1_championship_match_"
        + match.group(1)
    )


def collect_ligue1_final_result(
    match_id: str,
    source_url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> FinalResult | None:
    provider_match_id = (
        extract_ligue1_provider_match_id(
            match_id
        )
    )

    if provider_match_id is None:
        raise FinalResultServiceError(
            "Não foi possível extrair o ID "
            "oficial Ligue 1 do jogo: "
            f"{match_id}"
        )

    response = requests.get(
        (
            f"{LIGUE1_API_BASE_URL}"
            f"/championship-match/{provider_match_id}"
        ),
        headers=LIGUE1_HEADERS,
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    payload = response.json()

    period = str(
        payload.get("period") or ""
    ).strip().casefold()

    if period != "fulltime":
        return None

    home = payload.get("home")
    away = payload.get("away")

    if not isinstance(home, dict):
        raise FinalResultServiceError(
            "Payload Ligue 1 concluído sem "
            "objeto home válido."
        )

    if not isinstance(away, dict):
        raise FinalResultServiceError(
            "Payload Ligue 1 concluído sem "
            "objeto away válido."
        )

    home_score = home.get("score")
    away_score = away.get("score")

    if (
        home_score is None
        or away_score is None
    ):
        raise FinalResultServiceError(
            "Jogo Ligue 1 concluído "
            "sem resultado final."
        )

    return FinalResult(
        match_id=match_id,
        home_goals=int(float(home_score)),
        away_goals=int(float(away_score)),
        source_url=source_url,
    )

SERIEA_API_BASE_URL = (
    "https://seriea-api.prd.sdp.deltatre.digital/v1"
)

SERIEA_SEASON_ID = (
    "serie-a::Football_Season::"
    "ed7fdc2a3e7b408b942ec177b7b956b5"
)

SERIEA_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/plain; x-api-version=1.0",
}


def extract_seriea_match_id_from_source_url(
    source_url: str,
) -> str | None:
    match = re.search(
        r"(serie-a::Football_Match::[A-Za-z0-9]+)",
        source_url,
    )

    if match is None:
        return None

    return match.group(1)


def collect_seriea_final_result(
    match_id: str,
    source_url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> FinalResult | None:
    from urllib.parse import quote

    provider_match_id = (
        extract_seriea_match_id_from_source_url(
            source_url
        )
    )

    if provider_match_id is None:
        raise FinalResultServiceError(
            "Não foi possível extrair o ID "
            "oficial Serie A do source_url: "
            f"{source_url}"
        )

    response = requests.get(
        (
            f"{SERIEA_API_BASE_URL}"
            f"/serie-a/football/seasons/"
            f"{quote(SERIEA_SEASON_ID, safe='')}"
            f"/matches/"
            f"{quote(provider_match_id, safe='')}"
            f"/header"
        ),
        headers=SERIEA_HEADERS,
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    payload = response.json()

    status = str(
        payload.get("status") or ""
    ).strip().upper()

    if status != "FINISHED":
        return None

    phase = str(
        payload.get("phase") or ""
    ).strip().upper()

    if phase != "FULL_TIME":
        return None

    home_score = payload.get(
        "providerHomeScore"
    )
    away_score = payload.get(
        "providerAwayScore"
    )

    if (
        home_score is None
        or away_score is None
    ):
        raise FinalResultServiceError(
            "Jogo Serie A FINISHED/FULL_TIME "
            "sem resultado final."
        )

    return FinalResult(
        match_id=match_id,
        home_goals=int(float(home_score)),
        away_goals=int(float(away_score)),
        source_url=source_url,
    )


BUNDESLIGA_API_BASE_URL = (
    "https://wapp.bapi.bundesliga.com"
)

BUNDESLIGA_COMPETITION_ID = (
    "DFL-COM-000001"
)

BUNDESLIGA_SEASON_ID = (
    "DFL-SEA-0001KA"
)

BUNDESLIGA_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}


def extract_bundesliga_provider_match_id(
    match_id: str,
) -> str | None:
    match = re.search(
        r"_(DFLJ[A-Z0-9]+)_",
        match_id,
    )

    if match is None:
        return None

    compact = match.group(1)

    return (
        "DFL-MAT-"
        + compact.removeprefix("DFL")
    )


def collect_bundesliga_final_result(
    match_id: str,
    source_url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> FinalResult | None:
    provider_match_id = (
        extract_bundesliga_provider_match_id(
            match_id
        )
    )

    if provider_match_id is None:
        raise FinalResultServiceError(
            "Não foi possível extrair o ID "
            "oficial Bundesliga do jogo: "
            f"{match_id}"
        )

    response = requests.get(
        (
            f"{BUNDESLIGA_API_BASE_URL}/all/"
            f"{BUNDESLIGA_COMPETITION_ID}/"
            f"seasons/{BUNDESLIGA_SEASON_ID}/"
            "matches.json"
        ),
        headers=BUNDESLIGA_HEADERS,
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise FinalResultServiceError(
            "Payload Bundesliga inesperado: "
            f"{type(payload).__name__}."
        )

    item = payload.get(
        provider_match_id
    )

    if item is None:
        return None

    if not isinstance(item, dict):
        raise FinalResultServiceError(
            "Registo Bundesliga do jogo "
            "não é um objeto válido."
        )

    status = str(
        item.get("matchStatus") or ""
    ).strip().upper()

    if status != "FINAL_WHISTLE":
        return None

    score = item.get("score")

    if not isinstance(score, dict):
        raise FinalResultServiceError(
            "Jogo Bundesliga terminado "
            "sem objeto score válido."
        )

    home = score.get("home")
    away = score.get("away")

    if (
        not isinstance(home, dict)
        or not isinstance(away, dict)
    ):
        raise FinalResultServiceError(
            "Jogo Bundesliga terminado "
            "sem score home/away válido."
        )

    home_score = home.get("fulltime")
    away_score = away.get("fulltime")

    if (
        home_score is None
        or away_score is None
    ):
        raise FinalResultServiceError(
            "Jogo Bundesliga FINAL_WHISTLE "
            "sem resultado fulltime."
        )

    return FinalResult(
        match_id=match_id,
        home_goals=int(float(home_score)),
        away_goals=int(float(away_score)),
        source_url=source_url,
    )


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
                row_league_id = str(
                    row["league_id"]
                ).upper()

                if row_league_id == "ESP1":
                    result = collect_laliga_final_result(
                        match_id=match_id,
                        source_url=source_url,
                        timeout_seconds=timeout_seconds,
                    )
                elif row_league_id == "ENG1":
                    result = collect_premier_league_final_result(
                        match_id=match_id,
                        source_url=source_url,
                        timeout_seconds=timeout_seconds,
                    )
                elif row_league_id == "FRA1":
                    result = collect_ligue1_final_result(
                        match_id=match_id,
                        source_url=source_url,
                        timeout_seconds=timeout_seconds,
                    )
                elif row_league_id == "ITA1":
                    result = collect_seriea_final_result(
                        match_id=match_id,
                        source_url=source_url,
                        timeout_seconds=timeout_seconds,
                    )
                elif row_league_id == "GER1":
                    result = collect_bundesliga_final_result(
                        match_id=match_id,
                        source_url=source_url,
                        timeout_seconds=timeout_seconds,
                    )
                else:
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
