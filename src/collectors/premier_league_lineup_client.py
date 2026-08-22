# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests

from src.collectors.premier_league_lineup_parser import (
    PremierLeagueLineupParseError,
    PremierLeagueMatchLineup,
    parse_premier_league_lineup,
)


PROVIDER = "PREMIER_LEAGUE"
API_BASE_URL = (
    "https://footballapi.pulselive.com/football"
)
DEFAULT_TIMEOUT = 30

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/150.0 Safari/537.36"
    ),
    "Origin": "https://www.premierleague.com",
    "Referer": "https://www.premierleague.com/",
    "Accept": "application/json",
}


class PremierLeagueLineupClientError(RuntimeError):
    """Erro de comunicação com a Pulselive."""


class LineupAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    FIXTURE_NOT_FOUND = "FIXTURE_NOT_FOUND"
    HTTP_ERROR = "HTTP_ERROR"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"


@dataclass(frozen=True)
class PremierLeagueLineupFetchResult:
    provider: str
    provider_fixture_id: str
    availability: LineupAvailability
    http_status: int | None
    request_url: str | None
    message: str
    parsed_lineup: PremierLeagueMatchLineup | None
    payload: dict[str, Any] | None


def create_premier_league_session() -> requests.Session:
    session = requests.Session()

    session.headers.update(
        DEFAULT_HEADERS
    )

    return session


def normalize_fixture_id(
    value: str | int | float,
) -> str:
    try:
        normalized = int(float(value))
    except (TypeError, ValueError) as exc:
        raise PremierLeagueLineupClientError(
            f"Fixture ID inválido: {value!r}"
        ) from exc

    if normalized <= 0:
        raise PremierLeagueLineupClientError(
            f"Fixture ID inválido: {normalized}"
        )

    return str(normalized)


def fixture_url(
    provider_fixture_id: str,
) -> str:
    return (
        f"{API_BASE_URL}/fixtures/"
        f"{provider_fixture_id}"
    )


def fetch_premier_league_lineup(
    provider_fixture_id: str | int | float,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
) -> PremierLeagueLineupFetchResult:
    fixture_id = normalize_fixture_id(
        provider_fixture_id
    )

    owns_session = session is None

    active_session = (
        session
        if session is not None
        else create_premier_league_session()
    )

    url = fixture_url(
        fixture_id
    )

    try:
        try:
            response = active_session.get(
                url,
                params={
                    "altIds": "true",
                },
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise PremierLeagueLineupClientError(
                f"Erro de rede ao consultar "
                f"fixture {fixture_id}: {exc}"
            ) from exc

        request_url = str(
            response.url
        )

        if response.status_code == 404:
            return PremierLeagueLineupFetchResult(
                provider=PROVIDER,
                provider_fixture_id=fixture_id,
                availability=(
                    LineupAvailability.FIXTURE_NOT_FOUND
                ),
                http_status=response.status_code,
                request_url=request_url,
                message=(
                    "Fixture não encontrado na Pulselive."
                ),
                parsed_lineup=None,
                payload=None,
            )

        if response.status_code != 200:
            return PremierLeagueLineupFetchResult(
                provider=PROVIDER,
                provider_fixture_id=fixture_id,
                availability=(
                    LineupAvailability.HTTP_ERROR
                ),
                http_status=response.status_code,
                request_url=request_url,
                message=(
                    "A Pulselive respondeu com "
                    f"HTTP {response.status_code}."
                ),
                parsed_lineup=None,
                payload=None,
            )

        try:
            payload = response.json()
        except ValueError:
            return PremierLeagueLineupFetchResult(
                provider=PROVIDER,
                provider_fixture_id=fixture_id,
                availability=(
                    LineupAvailability.INVALID_PAYLOAD
                ),
                http_status=response.status_code,
                request_url=request_url,
                message=(
                    "A resposta Pulselive não contém "
                    "JSON válido."
                ),
                parsed_lineup=None,
                payload=None,
            )

        if not isinstance(payload, dict):
            return PremierLeagueLineupFetchResult(
                provider=PROVIDER,
                provider_fixture_id=fixture_id,
                availability=(
                    LineupAvailability.INVALID_PAYLOAD
                ),
                http_status=response.status_code,
                request_url=request_url,
                message=(
                    "O payload Pulselive não é "
                    "um objeto JSON."
                ),
                parsed_lineup=None,
                payload=None,
            )

        payload_fixture_id = payload.get(
            "id"
        )

        try:
            normalized_payload_id = (
                normalize_fixture_id(
                    payload_fixture_id
                )
            )
        except PremierLeagueLineupClientError:
            return PremierLeagueLineupFetchResult(
                provider=PROVIDER,
                provider_fixture_id=fixture_id,
                availability=(
                    LineupAvailability.INVALID_PAYLOAD
                ),
                http_status=response.status_code,
                request_url=request_url,
                message=(
                    "O payload não contém um fixture ID "
                    "válido."
                ),
                parsed_lineup=None,
                payload=payload,
            )

        if normalized_payload_id != fixture_id:
            return PremierLeagueLineupFetchResult(
                provider=PROVIDER,
                provider_fixture_id=fixture_id,
                availability=(
                    LineupAvailability.INVALID_PAYLOAD
                ),
                http_status=response.status_code,
                request_url=request_url,
                message=(
                    "O fixture devolvido não corresponde "
                    "ao fixture solicitado."
                ),
                parsed_lineup=None,
                payload=payload,
            )

        team_lists = payload.get(
            "teamLists"
        )

        valid_team_lists = (
            isinstance(team_lists, list)
            and len(team_lists) == 2
            and all(
                isinstance(team_list, dict)
                for team_list in team_lists
            )
        )

        if not valid_team_lists:
            return PremierLeagueLineupFetchResult(
                provider=PROVIDER,
                provider_fixture_id=fixture_id,
                availability=(
                    LineupAvailability.NOT_PUBLISHED
                ),
                http_status=response.status_code,
                request_url=request_url,
                message=(
                    "O fixture existe, mas os onzes "
                    "oficiais ainda não estão publicados."
                ),
                parsed_lineup=None,
                payload=payload,
            )

        try:
            parsed = parse_premier_league_lineup(
                payload
            )
        except PremierLeagueLineupParseError as exc:
            return PremierLeagueLineupFetchResult(
                provider=PROVIDER,
                provider_fixture_id=fixture_id,
                availability=(
                    LineupAvailability.INVALID_PAYLOAD
                ),
                http_status=response.status_code,
                request_url=request_url,
                message=(
                    "Os onzes estão presentes, mas "
                    f"o payload é inválido: {exc}"
                ),
                parsed_lineup=None,
                payload=payload,
            )

        return PremierLeagueLineupFetchResult(
            provider=PROVIDER,
            provider_fixture_id=fixture_id,
            availability=(
                LineupAvailability.AVAILABLE
            ),
            http_status=response.status_code,
            request_url=request_url,
            message=(
                "Onzes oficiais recolhidos "
                "e validados."
            ),
            parsed_lineup=parsed,
            payload=payload,
        )

    finally:
        if owns_session:
            active_session.close()
