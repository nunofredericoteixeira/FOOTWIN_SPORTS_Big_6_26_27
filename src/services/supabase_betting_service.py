from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv(
    "SUPABASE_PUBLISHABLE_KEY",
    "",
)

REQUEST_TIMEOUT = 20


class SupabaseBettingError(RuntimeError):
    pass


def _headers(
    access_token: str,
    *,
    return_representation: bool = False,
) -> dict[str, str]:
    if not SUPABASE_URL:
        raise SupabaseBettingError(
            "SUPABASE_URL não configurado."
        )

    if not SUPABASE_PUBLISHABLE_KEY:
        raise SupabaseBettingError(
            "SUPABASE_PUBLISHABLE_KEY não configurada."
        )

    if not access_token:
        raise SupabaseBettingError(
            "Access token vazio."
        )

    headers = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {access_token}",
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

    raise SupabaseBettingError(str(message))


def load_bankroll(
    *,
    user_id: str,
    access_token: str,
) -> dict[str, Any] | None:
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/user_bankrolls",
        headers=_headers(access_token),
        params={
            "select": (
                "user_id,initial_balance,current_balance,"
                "stake_mode,default_stake_value"
            ),
            "user_id": f"eq.{user_id}",
            "limit": "1",
        },
        timeout=REQUEST_TIMEOUT,
    )

    _raise_for_response(response)

    rows = response.json()

    if not rows:
        return None

    return dict(rows[0])


def save_bankroll(
    *,
    user_id: str,
    access_token: str,
    initial_balance: float,
    current_balance: float,
    stake_mode: str,
    default_stake_value: float = 0.0,
) -> None:
    normalized_mode = str(
        stake_mode or "FIXED"
    ).strip().upper()

    if normalized_mode not in {
        "FIXED",
        "PERCENTAGE",
    }:
        raise SupabaseBettingError(
            f"stake_mode inválido: {stake_mode}"
        )

    existing = load_bankroll(
        user_id=user_id,
        access_token=access_token,
    )

    payload = {
        "initial_balance": float(initial_balance),
        "current_balance": float(current_balance),
        "stake_mode": normalized_mode,
        "default_stake_value": float(
            default_stake_value
        ),
    }

    if existing is None:
        payload["user_id"] = user_id

        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/user_bankrolls",
            headers=_headers(access_token),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    else:
        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/user_bankrolls",
            headers=_headers(access_token),
            params={
                "user_id": f"eq.{user_id}",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

    _raise_for_response(response)


def load_user_bets(
    *,
    user_id: str,
    access_token: str,
) -> list[dict[str, Any]]:
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/user_bets",
        headers=_headers(access_token),
        params={
            "select": (
                "id,user_id,match_id,selection,odd,"
                "stake_amount,potential_return,status,"
                "actual_return,profit_loss,balance_before,"
                "balance_after_stake,"
                "balance_after_settlement,home_goals,"
                "away_goals,placed_at,settled_at"
            ),
            "user_id": f"eq.{user_id}",
            "order": "placed_at.asc,id.asc",
        },
        timeout=REQUEST_TIMEOUT,
    )

    _raise_for_response(response)

    return [
        dict(row)
        for row in response.json()
    ]


def settle_bet(
    *,
    user_id: str,
    access_token: str,
    bet_id: int,
    status: str,
    actual_return: float,
    profit_loss: float,
    balance_after_settlement: float,
    home_goals: int,
    away_goals: int,
) -> bool:
    normalized_status = str(
        status or ""
    ).strip().upper()

    if normalized_status not in {
        "WON",
        "LOST",
    }:
        raise SupabaseBettingError(
            f"status de liquidação inválido: {status}"
        )

    response = requests.patch(
        f"{SUPABASE_URL}/rest/v1/user_bets",
        headers=_headers(
            access_token,
            return_representation=True,
        ),
        params={
            "id": f"eq.{int(bet_id)}",
            "user_id": f"eq.{user_id}",
            "status": "eq.PENDING",
        },
        json={
            "status": normalized_status,
            "actual_return": float(actual_return),
            "profit_loss": float(profit_loss),
            "balance_after_settlement": float(
                balance_after_settlement
            ),
            "home_goals": int(home_goals),
            "away_goals": int(away_goals),
            "settled_at": datetime.now(
                timezone.utc
            ).isoformat(),
        },
        timeout=REQUEST_TIMEOUT,
    )

    _raise_for_response(response)

    rows = response.json()

    return bool(rows)


def save_pending_bet(
    *,
    user_id: str,
    access_token: str,
    match_id: str,
    selection: str,
    odd: float,
    stake_amount: float,
    balance_before: float,
    balance_after_stake: float,
) -> None:
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/user_bets",
        headers=_headers(access_token),
        params={
            "select": "id,status",
            "user_id": f"eq.{user_id}",
            "match_id": f"eq.{match_id}",
            "limit": "1",
        },
        timeout=REQUEST_TIMEOUT,
    )

    _raise_for_response(response)

    rows = response.json()

    if rows:
        existing_status = str(
            rows[0].get("status") or "PENDING"
        ).upper()

        if existing_status in {
            "WON",
            "LOST",
        }:
            return

    payload = {
        "selection": selection,
        "odd": float(odd),
        "stake_amount": float(stake_amount),
        "potential_return": float(
            odd * stake_amount
        ),
        "status": "PENDING",
        "balance_before": float(balance_before),
        "balance_after_stake": float(
            balance_after_stake
        ),
        "actual_return": None,
        "profit_loss": None,
        "balance_after_settlement": None,
        "home_goals": None,
        "away_goals": None,
        "settled_at": None,
    }

    if rows:
        bet_id = rows[0]["id"]

        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/user_bets",
            headers=_headers(access_token),
            params={
                "id": f"eq.{bet_id}",
                "user_id": f"eq.{user_id}",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    else:
        payload.update(
            {
                "user_id": user_id,
                "match_id": match_id,
            }
        )

        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/user_bets",
            headers=_headers(access_token),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

    _raise_for_response(response)
