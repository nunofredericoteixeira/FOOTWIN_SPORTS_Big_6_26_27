from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "",
).rstrip("/")

SUPABASE_PUBLISHABLE_KEY = os.getenv(
    "SUPABASE_PUBLISHABLE_KEY",
    "",
)

SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY",
    "",
)

REQUEST_TIMEOUT = 20


class SupabaseBwinOddsError(RuntimeError):
    pass


def _validate_base_config() -> None:
    if not SUPABASE_URL:
        raise SupabaseBwinOddsError(
            "SUPABASE_URL não configurado."
        )


def _user_headers(
    access_token: str,
) -> dict[str, str]:
    _validate_base_config()

    if not SUPABASE_PUBLISHABLE_KEY:
        raise SupabaseBwinOddsError(
            "SUPABASE_PUBLISHABLE_KEY não configurada."
        )

    if not access_token:
        raise SupabaseBwinOddsError(
            "Access token vazio."
        )

    return {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _service_headers(
    *,
    return_representation: bool = False,
) -> dict[str, str]:
    _validate_base_config()

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise SupabaseBwinOddsError(
            "SUPABASE_SERVICE_ROLE_KEY não configurada."
        )

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

    raise SupabaseBwinOddsError(
        str(message)
    )


def load_bwin_odds(
    *,
    match_id: str,
    access_token: str,
) -> dict[str, Any] | None:
    response = requests.get(
        (
            f"{SUPABASE_URL}/rest/v1/"
            "match_bwin_odds"
        ),
        headers=_user_headers(
            access_token
        ),
        params={
            "select": (
                "match_id,league_id,event_date,"
                "source,bookmaker,tipsterarea_id,"
                "canonical_url,odd_1,odd_x,odd_2,"
                "odd_1x,odd_12,odd_x2,"
                "fetched_at,updated_at"
            ),
            "match_id": f"eq.{match_id}",
            "limit": "1",
        },
        timeout=REQUEST_TIMEOUT,
    )

    _raise_for_response(response)

    rows = response.json()

    if not rows:
        return None

    return dict(rows[0])


def load_bwin_odds_internal(
    *,
    match_id: str,
) -> dict[str, Any] | None:
    """
    Lê o cache global usando SERVICE_ROLE.

    Destina-se apenas a processos internos, como o ciclo
    automático de CONFIRMED_LINEUP, para evitar recolhas
    repetidas e sobrescritas desnecessárias.
    """

    response = requests.get(
        (
            f"{SUPABASE_URL}/rest/v1/"
            "match_bwin_odds"
        ),
        headers=_service_headers(),
        params={
            "select": (
                "match_id,league_id,event_date,"
                "source,bookmaker,tipsterarea_id,"
                "canonical_url,odd_1,odd_x,odd_2,"
                "odd_1x,odd_12,odd_x2,"
                "fetched_at,updated_at"
            ),
            "match_id": f"eq.{match_id}",
            "limit": "1",
        },
        timeout=REQUEST_TIMEOUT,
    )

    _raise_for_response(response)

    rows = response.json()

    if not rows:
        return None

    return dict(rows[0])


def load_bwin_odds_for_matches(
    *,
    match_ids: list[str],
    access_token: str,
) -> dict[str, dict[str, Any]]:
    cleaned_ids = [
        str(match_id).strip()
        for match_id in match_ids
        if str(match_id).strip()
    ]

    if not cleaned_ids:
        return {}

    quoted = ",".join(
        f'"{match_id}"'
        for match_id in cleaned_ids
    )

    response = requests.get(
        (
            f"{SUPABASE_URL}/rest/v1/"
            "match_bwin_odds"
        ),
        headers=_user_headers(
            access_token
        ),
        params={
            "select": (
                "match_id,league_id,event_date,"
                "source,bookmaker,tipsterarea_id,"
                "canonical_url,odd_1,odd_x,odd_2,"
                "odd_1x,odd_12,odd_x2,"
                "fetched_at,updated_at"
            ),
            "match_id": f"in.({quoted})",
        },
        timeout=REQUEST_TIMEOUT,
    )

    _raise_for_response(response)

    return {
        str(row["match_id"]): dict(row)
        for row in response.json()
    }


def save_bwin_odds(
    *,
    match_id: str,
    league_id: str,
    event_date: str,
    tipsterarea_id: int,
    canonical_url: str,
    odds: dict[str, float],
) -> None:
    now = datetime.now(
        timezone.utc
    ).isoformat()

    payload = {
        "match_id": str(match_id),
        "league_id": str(league_id),
        "event_date": str(event_date),
        "source": "TIPSTERAREA",
        "bookmaker": "BWIN",
        "tipsterarea_id": int(
            tipsterarea_id
        ),
        "canonical_url": str(
            canonical_url
        ),
        "odd_1": odds.get("1"),
        "odd_x": odds.get("X"),
        "odd_2": odds.get("2"),
        "odd_1x": odds.get("1X"),
        "odd_12": odds.get("12"),
        "odd_x2": odds.get("X2"),
        "fetched_at": now,
        "updated_at": now,
    }

    response = requests.post(
        (
            f"{SUPABASE_URL}/rest/v1/"
            "match_bwin_odds"
        ),
        headers={
            **_service_headers(),
            "Prefer": (
                "resolution=merge-duplicates,"
                "return=minimal"
            ),
        },
        params={
            "on_conflict": "match_id",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    _raise_for_response(response)
