from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_CONFIG_HTML = Path(
    "data/raw/team_pages/ESP1.html"
)


@dataclass(frozen=True)
class LaligaWebviewConfig:
    base_url: str
    subscription_key: str


@dataclass(frozen=True)
class LaligaPublicConfig:
    base_url: str
    subscription_key: str


def load_laliga_webview_config(
    html_path: Path = DEFAULT_RUNTIME_CONFIG_HTML,
) -> LaligaWebviewConfig:
    text = html_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    base_url_match = re.search(
        r'"webviewUrl":"([^"]+)"',
        text,
    )
    subscription_match = re.search(
        r'"webviewSubscription":"([^"]+)"',
        text,
    )

    if not base_url_match:
        raise RuntimeError(
            "LaLiga webviewUrl não encontrado "
            f"em {html_path}"
        )

    if not subscription_match:
        raise RuntimeError(
            "LaLiga webviewSubscription não encontrado "
            f"em {html_path}"
        )

    return LaligaWebviewConfig(
        base_url=base_url_match.group(1).rstrip("/"),
        subscription_key=subscription_match.group(1),
    )


def load_laliga_public_config(
    html_path: Path = DEFAULT_RUNTIME_CONFIG_HTML,
) -> LaligaPublicConfig:
    text = html_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    base_url_match = re.search(
        r'"backendUrl":"([^"]+)"',
        text,
    )
    subscription_match = re.search(
        r'"backendSubscription":"([^"]+)"',
        text,
    )

    if not base_url_match:
        raise RuntimeError(
            "LaLiga backendUrl não encontrado "
            f"em {html_path}"
        )

    if not subscription_match:
        raise RuntimeError(
            "LaLiga backendSubscription não encontrado "
            f"em {html_path}"
        )

    return LaligaPublicConfig(
        base_url=base_url_match.group(1).rstrip("/"),
        subscription_key=subscription_match.group(1),
    )


def fetch_laliga_team_squad(
    team_slug: str,
    season_year: int,
    *,
    config: LaligaPublicConfig | None = None,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    if config is None:
        config = load_laliga_public_config()

    slug = str(team_slug).strip()

    if not slug:
        raise ValueError(
            "LaLiga team_slug vazio."
        )

    if not isinstance(season_year, int):
        raise ValueError(
            "LaLiga season_year deve ser inteiro."
        )

    url = (
        f"{config.base_url}/api/v1/teams/"
        f"{slug}/squad"
        f"?limit=100"
        f"&offset=0"
        f"&orderField=id"
        f"&orderType=DESC"
        f"&seasonYear={season_year}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "Ocp-Apim-Subscription-Key": (
                config.subscription_key
            ),
            "Content-Language": "en",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            body = response.read().decode(
                "utf-8",
                errors="replace",
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            "Erro HTTP ao obter squad LaLiga "
            f"para team_slug={slug}: "
            f"status={exc.code}, body={body[:500]}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Erro de rede ao obter squad LaLiga "
            f"para team_slug={slug}: {exc}"
        ) from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Resposta inválida da LaLiga "
            f"para team_slug={slug}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Resposta squad LaLiga inesperada: "
            f"{type(payload).__name__}"
        )

    payload.setdefault(
        "squads",
        [],
    )

    return payload


def fetch_laliga_match_lineups(
    match_id: int | str,
    *,
    config: LaligaWebviewConfig | None = None,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    if config is None:
        config = load_laliga_webview_config()

    match_id_text = str(match_id).strip()

    if not match_id_text.isdigit():
        raise ValueError(
            "LaLiga match_id deve ser numérico: "
            f"{match_id!r}"
        )

    url = (
        f"{config.base_url}/api/web/matches/"
        f"{match_id_text}/lineups"
    )

    request = urllib.request.Request(
        url,
        headers={
            "Ocp-Apim-Subscription-Key": (
                config.subscription_key
            ),
            "Content-Language": "en",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            body = response.read().decode(
                "utf-8",
                errors="replace",
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            "Erro HTTP ao obter lineups LaLiga "
            f"para match_id={match_id_text}: "
            f"status={exc.code}, body={body[:500]}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Erro de rede ao obter lineups LaLiga "
            f"para match_id={match_id_text}: {exc}"
        ) from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Resposta inválida da LaLiga "
            f"para match_id={match_id_text}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Resposta LaLiga inesperada: "
            f"{type(payload).__name__}"
        )

    payload.setdefault(
        "home_team_lineups",
        [],
    )
    payload.setdefault(
        "away_team_lineups",
        [],
    )

    return payload


def extract_starting_players(
    lineup_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    starters = []

    for entry in lineup_entries:
        if not isinstance(entry, dict):
            continue

        if entry.get("status") != "start":
            continue

        position = entry.get("position")

        if not isinstance(position, int):
            continue

        if not 1 <= position <= 11:
            continue

        starters.append(entry)

    starters.sort(
        key=lambda item: item.get(
            "position",
            999,
        )
    )

    return starters


def extract_starting_lineups(
    payload: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    home_entries = payload.get(
        "home_team_lineups",
        [],
    )
    away_entries = payload.get(
        "away_team_lineups",
        [],
    )

    if not isinstance(home_entries, list):
        home_entries = []

    if not isinstance(away_entries, list):
        away_entries = []

    return (
        extract_starting_players(home_entries),
        extract_starting_players(away_entries),
    )
