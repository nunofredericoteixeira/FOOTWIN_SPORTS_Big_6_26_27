# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


RAW_DIRECTORY = Path(
    "data/raw/team_pages"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept-Language": (
        "en-US,en;q=0.9,pt-PT;q=0.8,pt;q=0.7"
    ),
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def extract_urls(
    text: str,
) -> list[str]:
    patterns = [
        r"https?://[^\s\"'<>\\]+",
        r"/api/[A-Za-z0-9_/?=&.%:\-]+",
        r"/[A-Za-z0-9_\-]+/(?:team|teams|club|clubs|standings)"
        r"[A-Za-z0-9_/?=&.%:\-]*",
    ]

    urls: set[str] = set()

    for pattern in patterns:
        for match in re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            cleaned = (
                match
                .replace("\\u0026", "&")
                .replace("\\/", "/")
                .rstrip(
                    ".,);]}\\"
                )
            )

            lower = cleaned.lower()

            if any(
                keyword in lower
                for keyword in (
                    "api",
                    "team",
                    "teams",
                    "club",
                    "clubs",
                    "standings",
                    "competition",
                    "season",
                )
            ):
                urls.add(cleaned)

    return sorted(urls)


def inspect_saved_page(
    league_id: str,
) -> None:
    path = (
        RAW_DIRECTORY
        / f"{league_id}.html"
    )

    print()
    print("=" * 120)
    print(
        f"{league_id} — ENDPOINTS E URLS CANDIDATOS"
    )
    print("=" * 120)

    if not path.exists():
        print(
            f"Ficheiro não encontrado: {path}"
        )
        return

    html = path.read_text(
        encoding="utf-8",
    )

    urls = extract_urls(
        html
    )

    if not urls:
        print(
            "Nenhum endpoint candidato encontrado."
        )
        return

    for url in urls[:120]:
        print(url)

    print(
        f"\nTotal de candidatos: {len(urls)}"
    )


def inspect_serie_a_team_page() -> None:
    url = (
        "https://en.legaseriea.it/team/index"
    )

    print()
    print("=" * 120)
    print("ITA1 — PÁGINA OFICIAL DE CLUBES")
    print("=" * 120)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=45,
        allow_redirects=True,
    )

    print(
        f"HTTP:      {response.status_code}"
    )

    print(
        f"URL final: {response.url}"
    )

    print(
        f"Bytes:     {len(response.content)}"
    )

    response.raise_for_status()

    output_path = (
        RAW_DIRECTORY
        / "ITA1_TEAMS.html"
    )

    output_path.write_text(
        response.text,
        encoding="utf-8",
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    candidates: list[
        tuple[str, str]
    ] = []

    seen: set[
        tuple[str, str]
    ] = set()

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        href = clean_text(
            anchor.get("href")
        )

        text = clean_text(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            image = anchor.find("img")

            if image is not None:
                text = clean_text(
                    image.get("alt")
                    or image.get("title")
                )

        absolute_url = urljoin(
            response.url,
            href,
        )

        lower_url = absolute_url.lower()

        if not any(
            fragment in lower_url
            for fragment in (
                "/team/",
                "/teams/",
                "/club/",
                "/clubs/",
            )
        ):
            continue

        if not text:
            continue

        key = (
            text.casefold(),
            absolute_url,
        )

        if key in seen:
            continue

        seen.add(key)
        candidates.append(
            (
                text,
                absolute_url,
            )
        )

    print(
        f"Links de clubes encontrados: "
        f"{len(candidates)}"
    )

    for text, team_url in candidates[:40]:
        print(
            f"  - {text} | {team_url}"
        )

    print(
        f"HTML guardado: "
        f"{output_path.resolve()}"
    )


def main() -> int:
    RAW_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    for league_id in (
        "ENG1",
        "FRA1",
        "POR1",
    ):
        inspect_saved_page(
            league_id
        )

    inspect_serie_a_team_page()

    print()
    print("=" * 120)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
