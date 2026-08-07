# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,pt-PT;q=0.8,pt;q=0.7",
}

RAW_DIRECTORY = Path(
    "data/raw/team_pages"
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def probe_premier_league_api() -> None:
    print()
    print("=" * 110)
    print("ENG1 — TESTE DA API OFICIAL")
    print("=" * 110)

    base_url = (
        "https://sdp-prem-prod."
        "premier-league-prod.pulselive.com/api"
    )

    candidates = [
        (
            f"{base_url}/football/competitions/"
            "comp=1/compseasons?page=0&pageSize=100"
        ),
        (
            f"{base_url}/football/competitions/"
            "comp=1/compseasons"
        ),
        (
            f"{base_url}/football/teams"
            "?comp=1&compCodeForSort=PL"
            "&compSeasons=2026"
            "&page=0&pageSize=100"
        ),
        (
            f"{base_url}/football/teams"
            "?comp=1&compSeasons=2026"
            "&page=0&pageSize=100"
        ),
    ]

    for index, url in enumerate(
        candidates,
        start=1,
    ):
        print()
        print(f"Teste #{index}")
        print(url)

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=45,
            )

            print(
                f"HTTP:  {response.status_code}"
            )

            print(
                f"Bytes: {len(response.content)}"
            )

            print(
                f"Tipo:  "
                f"{response.headers.get('content-type')}"
            )

            preview = clean_text(
                response.text
            )[:1000]

            print(
                f"Pré-visualização: {preview}"
            )

            output_path = (
                RAW_DIRECTORY
                / f"ENG1_API_{index}.txt"
            )

            output_path.write_text(
                response.text,
                encoding="utf-8",
            )

        except Exception as exc:
            print(
                f"ERRO: {exc}"
            )


def collect_strings(
    value: Any,
    results: set[str],
) -> None:
    if isinstance(value, str):
        cleaned = clean_text(value)

        if (
            2 <= len(cleaned) <= 80
            and any(
                character.isalpha()
                for character in cleaned
            )
        ):
            results.add(cleaned)

        return

    if isinstance(value, list):
        for item in value:
            collect_strings(
                item,
                results,
            )

        return

    if isinstance(value, dict):
        for key, item in value.items():
            key_text = clean_text(
                key
            ).lower()

            if any(
                word in key_text
                for word in (
                    "team",
                    "club",
                    "name",
                    "short",
                    "official",
                )
            ):
                collect_strings(
                    item,
                    results,
                )

            elif isinstance(
                item,
                (list, dict),
            ):
                collect_strings(
                    item,
                    results,
                )


def probe_liga_portugal_nuxt() -> None:
    print()
    print("=" * 110)
    print("POR1 — EXTRAÇÃO DO __NUXT_DATA__")
    print("=" * 110)

    path = (
        RAW_DIRECTORY
        / "POR1.html"
    )

    html = path.read_text(
        encoding="utf-8",
    )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    script = soup.find(
        "script",
        id="__NUXT_DATA__",
    )

    if script is None:
        print(
            "Não foi encontrado __NUXT_DATA__."
        )
        return

    content = (
        script.string
        or script.get_text()
        or ""
    ).strip()

    data = json.loads(
        content
    )

    strings: set[str] = set()

    collect_strings(
        data,
        strings,
    )

    filtered = sorted(
        value
        for value in strings
        if any(
            marker in value.lower()
            for marker in (
                "fc",
                "sc",
                "cf",
                "afc",
                "sad",
                "sporting",
                "benfica",
                "porto",
                "braga",
                "estoril",
                "famalic",
                "gil vicente",
                "moreirense",
                "rio ave",
                "vitória",
                "vitoria",
                "nacional",
                "marítimo",
                "maritimo",
                "aves",
                "casa pia",
                "santa clara",
                "tondela",
                "chaves",
                "farense",
                "alverca",
            )
        )
    )

    print(
        f"Strings candidatas: "
        f"{len(filtered)}"
    )

    for value in filtered:
        print(
            f"  - {value}"
        )

    output_path = (
        RAW_DIRECTORY
        / "POR1_STRING_CANDIDATES.txt"
    )

    output_path.write_text(
        "\n".join(filtered),
        encoding="utf-8",
    )

    print()
    print(
        f"Resultado guardado em: "
        f"{output_path.resolve()}"
    )


def main() -> int:
    RAW_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    probe_premier_league_api()
    probe_liga_portugal_nuxt()

    print()
    print("=" * 110)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
