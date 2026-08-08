from __future__ import annotations

import os
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


class SupabaseAuthError(RuntimeError):
    """Erro devolvido pelo serviço de autenticação do Supabase."""


def _validate_configuration() -> None:
    if not SUPABASE_URL:
        raise SupabaseAuthError(
            "A variável SUPABASE_URL não está configurada."
        )

    if not SUPABASE_PUBLISHABLE_KEY:
        raise SupabaseAuthError(
            "A variável SUPABASE_PUBLISHABLE_KEY não está configurada."
        )


def _public_headers() -> dict[str, str]:
    _validate_configuration()

    return {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Content-Type": "application/json",
    }


def _authenticated_headers(
    access_token: str,
) -> dict[str, str]:
    headers = _public_headers()
    headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _response_data(
    response: requests.Response,
) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.ok:
        return data

    message = (
        data.get("msg")
        or data.get("message")
        or data.get("error_description")
        or data.get("error")
        or f"Erro HTTP {response.status_code}"
    )

    raise SupabaseAuthError(str(message))


def register_user(
    name: str,
    email: str,
    password: str,
) -> dict[str, Any]:
    response = requests.post(
        f"{SUPABASE_URL}/auth/v1/signup",
        headers=_public_headers(),
        json={
            "email": email,
            "password": password,
            "data": {
                "name": name,
            },
        },
        timeout=REQUEST_TIMEOUT,
    )

    return _response_data(response)


def login_user(
    email: str,
    password: str,
) -> dict[str, Any]:
    response = requests.post(
        f"{SUPABASE_URL}/auth/v1/token",
        params={
            "grant_type": "password",
        },
        headers=_public_headers(),
        json={
            "email": email,
            "password": password,
        },
        timeout=REQUEST_TIMEOUT,
    )

    return _response_data(response)


def refresh_session(
    refresh_token: str,
) -> dict[str, Any]:
    response = requests.post(
        f"{SUPABASE_URL}/auth/v1/token",
        params={
            "grant_type": "refresh_token",
        },
        headers=_public_headers(),
        json={
            "refresh_token": refresh_token,
        },
        timeout=REQUEST_TIMEOUT,
    )

    return _response_data(response)


def get_authenticated_user(
    access_token: str,
) -> dict[str, Any]:
    response = requests.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers=_authenticated_headers(access_token),
        timeout=REQUEST_TIMEOUT,
    )

    return _response_data(response)


def logout_user(
    access_token: str,
) -> None:
    response = requests.post(
        f"{SUPABASE_URL}/auth/v1/logout",
        headers=_authenticated_headers(access_token),
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code not in (200, 204):
        _response_data(response)
