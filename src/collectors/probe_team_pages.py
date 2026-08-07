# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.collectors.team_sources import get_team_sources


OUTPUT_DIRECTORY = Path("data/raw/team_pages")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,pt-PT;q=0.8,pt;q=0.7",
}

TEAM_LINK_PATTERNS = (
    "/club/",
    "/clubs/",
    "/team/",
    "/teams/",
    "/squad/",
    "/squads/",
    "/equipa/",
    "/equipas/",
    "/clube/",
    "/clubes/",
)


def clean_text(value: str | None) -> str:
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def extract_link_candidates(
    html: str,
    base_url: str,
) -> list[dict[str, str]]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

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

        absolute_url = urljoin(
            base_url,
            href,
        )

        lower_href = absolute_url.lower()

        if not any(
            pattern in lower_href
            for pattern in TEAM_LINK_PATTERNS
        ):
            continue

        if not text:
            image = anchor.find("img")

            if image is not None:
                text = clean_text(
                    image.get("alt")
                    or image.get("title")
                )

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
            {
                "text": text,
                "url": absolute_url,
            }
        )

    return candidates


def extract_json_script_candidates(
    html: str,
) -> list[str]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results: list[str] = []

    for script in soup.find_all("script"):
        script_type = clean_text(
            script.get("type")
        ).lower()

        script_id = clean_text(
            script.get("id")
        )

        content = script.string or script.get_text()

        if not content:
            continue

        content = content.strip()

        if (
            script_type == "application/ld+json"
            or script_type == "application/json"
            or script_id in {
                "__NEXT_DATA__",
                "__NUXT_DATA__",
            }
        ):
            preview = clean_text(content)[:500]

            results.append(
                preview
            )

    return results


def probe_source(
    league_id: str,
    source_url: str,
) -> dict:
    response = requests.get(
        source_url,
        headers=HEADERS,
        timeout=45,
        allow_redirects=True,
    )

    response.raise_for_status()

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    html_path = (
        OUTPUT_DIRECTORY
        / f"{league_id}.html"
    )

    html_path.write_text(
        response.text,
        encoding="utf-8",
    )

    links = extract_link_candidates(
        html=response.text,
        base_url=response.url,
    )

    json_scripts = extract_json_script_candidates(
        response.text
    )

    result = {
        "league_id": league_id,
        "status_code": response.status_code,
        "final_url": response.url,
        "html_path": str(
            html_path.resolve()
        ),
        "html_bytes": len(
            response.content
        ),
        "link_candidates": links,
        "json_script_previews": json_scripts,
    }

    json_path = (
        OUTPUT_DIRECTORY
        / f"{league_id}_probe.json"
    )

    json_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return result


def main() -> int:
    sources = get_team_sources()

    print()
    print("=" * 110)
    print("DIAGNÓSTICO DAS PÁGINAS DE EQUIPAS")
    print("=" * 110)

    for league_id, source in sources.items():
        print()
        print(
            f"🔎 {league_id} — "
            f"{source.league_name}"
        )

        try:
            result = probe_source(
                league_id=league_id,
                source_url=source.source_url,
            )

            print(
                f"HTTP:             "
                f"{result['status_code']}"
            )

            print(
                f"URL final:        "
                f"{result['final_url']}"
            )

            print(
                f"HTML guardado:    "
                f"{result['html_path']}"
            )

            print(
                f"Links candidatos: "
                f"{len(result['link_candidates'])}"
            )

            print(
                f"Scripts JSON:     "
                f"{len(result['json_script_previews'])}"
            )

            for candidate in (
                result["link_candidates"][:25]
            ):
                print(
                    f"  - {candidate['text']} | "
                    f"{candidate['url']}"
                )

        except Exception as exc:
            print(
                f"❌ Erro: {exc}"
            )

    print()
    print("=" * 110)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
