from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

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


class SupabaseMatchRuntimeStateError(RuntimeError):
    pass


def _validate_config() -> None:
    if not SUPABASE_URL:
        raise SupabaseMatchRuntimeStateError(
            "SUPABASE_URL não configurado."
        )

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise SupabaseMatchRuntimeStateError(
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

    raise SupabaseMatchRuntimeStateError(
        str(message)
    )


def load_match_runtime_state(
    *,
    match_id: str,
) -> dict[str, Any] | None:
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/match_runtime_state",
        headers=_headers(),
        params={
            "select": (
                "match_id,league_id,match_date,"
                "status,home_goals,away_goals,"
                "source_url,created_at,updated_at"
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


def load_match_runtime_states(
    *,
    match_ids: list[str],
) -> dict[str, dict[str, Any]]:
    cleaned_ids = [
        str(match_id).strip()
        for match_id in match_ids
        if str(match_id).strip()
    ]

    if not cleaned_ids:
        return {}

    result: dict[str, dict[str, Any]] = {}
    chunk_size = 100

    for start in range(
        0,
        len(cleaned_ids),
        chunk_size,
    ):
        chunk = cleaned_ids[
            start:start + chunk_size
        ]

        quoted = ",".join(
            f'"{match_id}"'
            for match_id in chunk
        )

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/match_runtime_state",
            headers=_headers(),
            params={
                "select": (
                    "match_id,league_id,match_date,"
                    "status,home_goals,away_goals,"
                    "source_url,created_at,updated_at"
                ),
                "match_id": f"in.({quoted})",
            },
            timeout=REQUEST_TIMEOUT,
        )

        _raise_for_response(response)

        for row in response.json():
            result[str(row["match_id"])] = dict(
                row
            )

    return result


def save_match_runtime_state(
    *,
    match_id: str,
    league_id: str,
    match_date: str,
    status: str,
    home_goals: int | None,
    away_goals: int | None,
    source_url: str,
) -> None:
    normalized_status = str(
        status
    ).strip().upper()

    existing = load_match_runtime_state(
        match_id=str(match_id),
    )

    terminal_statuses = {
        "PLAYED",
        "AWARDED",
        "CANCELLED",
        "ABANDONED",
    }

    non_terminal_statuses = {
        "SCHEDULED",
        "POSTPONED",
    }

    if (
        existing
        and str(
            existing.get("status", "")
        ).strip().upper() in terminal_statuses
        and normalized_status in non_terminal_statuses
    ):
        normalized_status = str(
            existing["status"]
        ).strip().upper()

        home_goals = existing.get(
            "home_goals"
        )
        away_goals = existing.get(
            "away_goals"
        )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    payload = {
        "match_id": str(match_id),
        "league_id": str(league_id),
        "match_date": str(match_date),
        "status": normalized_status,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "source_url": str(source_url),
        "updated_at": now,
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/match_runtime_state",
        headers={
            **_headers(),
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



def load_all_match_runtime_states() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0

    while True:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/match_runtime_state",
            headers=_headers(),
            params={
                "select": (
                    "match_id,league_id,match_date,"
                    "status,home_goals,away_goals,"
                    "source_url,created_at,updated_at"
                ),
                "order": "match_id.asc",
                "limit": str(page_size),
                "offset": str(offset),
            },
            timeout=REQUEST_TIMEOUT,
        )

        _raise_for_response(response)

        page = [
            dict(row)
            for row in response.json()
        ]

        rows.extend(page)

        if len(page) < page_size:
            break

        offset += page_size

    return rows


def _postgres_datetime_to_sqlite(
    value: str,
) -> str:
    cleaned = str(value or "").strip()

    if not cleaned:
        raise SupabaseMatchRuntimeStateError(
            "match_date vazio no estado persistente."
        )

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


def hydrate_sqlite_match_runtime_state(
    *,
    database_path: str | os.PathLike[str],
) -> int:
    states = load_all_match_runtime_states()

    if not states:
        return 0

    connection = sqlite3.connect(
        str(database_path)
    )

    applied = 0

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        for state in states:
            cursor = connection.execute(
                """
                UPDATE matches
                SET
                    match_date = ?,
                    status = ?,
                    home_goals = ?,
                    away_goals = ?,
                    source_url = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_id = ?
                """,
                (
                    _postgres_datetime_to_sqlite(
                        str(state["match_date"])
                    ),
                    str(state["status"]),
                    state.get("home_goals"),
                    state.get("away_goals"),
                    str(state["source_url"]),
                    str(state["match_id"]),
                ),
            )

            if cursor.rowcount == 1:
                applied += 1

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return applied
