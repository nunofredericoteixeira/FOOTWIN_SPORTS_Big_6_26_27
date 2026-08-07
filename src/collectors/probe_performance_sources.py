# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


OUTPUT_DIRECTORY = Path(
    "data/raw/performance_pages"
)

TIMEOUT_SECONDS = 40

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": (
        "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7"
    ),
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


SOURCES = {
    "ENG1": (
        "https://www.premierleague.com/en/tables/"
        "premier-league/2025-26/all-matchweeks"
    ),
    "ESP1": (
        "https://www.laliga.com/en-GB/"
        "laliga-easports/standing"
    ),
    "ITA1": (
        "https://en.legaseriea.it/"
        "serie-a/standings"
    ),
    "GER1": (
        "https://www.bundesliga.com/en/"
        "bundesliga/table/2025-2026"
    ),
    "FRA1": (
        "https://ligue1.com/standings"
    ),
    "POR1": (
        "https://www.ligaportugal.pt/"
        "competition/911/"
        "liga-portugal-betclic/"
        "round/20252026"
    ),
}


TEAM_HINTS = {
    "ENG1": (
        "Arsenal",
        "Liverpool",
        "Manchester City",
    ),
    "ESP1": (
        "Barcelona",
        "Real Madrid",
        "Atlético",
    ),
    "ITA1": (
        "Inter",
        "Juventus",
        "Napoli",
    ),
    "GER1": (
        "Bayern",
        "Dortmund",
        "Leipzig",
    ),
    "FRA1": (
        "Paris",
        "Marseille",
        "Monaco",
    ),
    "POR1": (
        "Benfica",
        "Porto",
        "Sporting",
    ),
}


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def save_text(
    path: Path,
    content: str,
) -> None:
    path.write_text(
        content,
        encoding="utf-8",
    )


def count_html_tables(
    soup: BeautifulSoup,
) -> int:
    return len(
        soup.find_all("table")
    )


def find_team_contexts(
    html: str,
    hints: tuple[str, ...],
) -> list[str]:
    contexts: list[str] = []
    lower_html = html.casefold()

    for hint in hints:
        search_value = hint.casefold()
        start = 0

        while True:
            index = lower_html.find(
                search_value,
                start,
            )

            if index < 0:
                break

            left = max(
                0,
                index - 140,
            )

            right = min(
                len(html),
                index
                + len(hint)
                + 220,
            )

            context = clean_text(
                html[left:right]
            )

            if context not in contexts:
                contexts.append(
                    context
                )

            start = (
                index
                + len(search_value)
            )

            if len(contexts) >= 20:
                return contexts

    return contexts


def inspect_scripts(
    soup: BeautifulSoup,
) -> list[str]:
    results: list[str] = []

    for script in soup.find_all("script"):
        script_id = clean_text(
            script.get("id")
        )

        script_type = clean_text(
            script.get("type")
        )

        script_src = clean_text(
            script.get("src")
        )

        content = (
            script.string
            or script.get_text()
            or ""
        ).strip()

        if (
            script_id
            or script_src
            or "json" in script_type.casefold()
            or "__NEXT_DATA__" in content
            or "__NUXT_DATA__" in content
        ):
            results.append(
                " | ".join(
                    [
                        f"id={script_id}",
                        f"type={script_type}",
                        f"src={script_src}",
                        f"bytes={len(content)}",
                    ]
                )
            )

    return results


def extract_json_script_summary(
    soup: BeautifulSoup,
) -> list[str]:
    summaries: list[str] = []

    for script_id in (
        "__NEXT_DATA__",
        "__NUXT_DATA__",
    ):
        script = soup.find(
            "script",
            id=script_id,
        )

        if script is None:
            continue

        content = (
            script.string
            or script.get_text()
            or ""
        ).strip()

        try:
            parsed = json.loads(
                content
            )

            if isinstance(parsed, dict):
                keys = list(
                    parsed.keys()
                )

                summaries.append(
                    f"{script_id}: "
                    f"dict keys={keys[:30]}"
                )

            elif isinstance(parsed, list):
                summaries.append(
                    f"{script_id}: "
                    f"list items={len(parsed)}"
                )

            else:
                summaries.append(
                    f"{script_id}: "
                    f"type={type(parsed).__name__}"
                )

        except Exception as exc:
            summaries.append(
                f"{script_id}: "
                f"JSON inválido: {exc}"
            )

    return summaries


def extract_candidate_urls(
    html: str,
) -> list[str]:
    patterns = (
        r"https?://[^\"'\s<>\\]+",
        r"(?:https?:)?//[^\"'\s<>\\]+",
        r"/api/[^\"'\s<>\\]+",
    )

    candidates: list[str] = []

    markers = (
        "standing",
        "table",
        "classification",
        "ranking",
        "season",
        "competition",
        "team",
    )

    for pattern in patterns:
        for match in re.findall(
            pattern,
            html,
            flags=re.IGNORECASE,
        ):
            cleaned = (
                match
                .replace("\\/", "/")
                .replace("\\u0026", "&")
            )

            lower = cleaned.casefold()

            if not any(
                marker in lower
                for marker in markers
            ):
                continue

            if cleaned not in candidates:
                candidates.append(
                    cleaned
                )

            if len(candidates) >= 100:
                return candidates

    return candidates


def write_report(
    league_id: str,
    url: str,
    status_code: int,
    content_type: str,
    html: str,
    soup: BeautifulSoup,
) -> Path:
    output_path = (
        OUTPUT_DIRECTORY
        / f"{league_id}_diagnostic.txt"
    )

    contexts = find_team_contexts(
        html,
        TEAM_HINTS[league_id],
    )

    scripts = inspect_scripts(
        soup
    )

    json_summaries = (
        extract_json_script_summary(
            soup
        )
    )

    candidate_urls = (
        extract_candidate_urls(
            html
        )
    )

    lines: list[str] = []

    lines.append(
        "=" * 110
    )

    lines.append(
        f"{league_id} — DIAGNÓSTICO"
    )

    lines.append(
        "=" * 110
    )

    lines.append(
        f"URL: {url}"
    )

    lines.append(
        f"HTTP: {status_code}"
    )

    lines.append(
        f"Content-Type: {content_type}"
    )

    lines.append(
        f"Bytes: {len(html.encode('utf-8'))}"
    )

    lines.append(
        f"Tabelas HTML: {count_html_tables(soup)}"
    )

    lines.append(
        f"Scripts relevantes: {len(scripts)}"
    )

    lines.append(
        f"Contextos de equipas: {len(contexts)}"
    )

    lines.append(
        f"URLs candidatas: {len(candidate_urls)}"
    )

    lines.append("")
    lines.append(
        "=" * 110
    )
    lines.append(
        "RESUMO DOS JSON"
    )
    lines.append(
        "=" * 110
    )

    if json_summaries:
        lines.extend(
            json_summaries
        )
    else:
        lines.append(
            "Nenhum JSON principal encontrado."
        )

    lines.append("")
    lines.append(
        "=" * 110
    )
    lines.append(
        "CONTEXTOS COM EQUIPAS"
    )
    lines.append(
        "=" * 110
    )

    if contexts:
        for context in contexts:
            lines.append("")
            lines.append(
                context
            )
    else:
        lines.append(
            "Nenhum nome de equipa encontrado "
            "diretamente no HTML."
        )

    lines.append("")
    lines.append(
        "=" * 110
    )
    lines.append(
        "SCRIPTS RELEVANTES"
    )
    lines.append(
        "=" * 110
    )

    if scripts:
        lines.extend(
            scripts[:150]
        )
    else:
        lines.append(
            "Nenhum script relevante encontrado."
        )

    lines.append("")
    lines.append(
        "=" * 110
    )
    lines.append(
        "URLS CANDIDATAS"
    )
    lines.append(
        "=" * 110
    )

    if candidate_urls:
        lines.extend(
            candidate_urls
        )
    else:
        lines.append(
            "Nenhuma URL candidata encontrada."
        )

    save_text(
        output_path,
        "\n".join(lines),
    )

    return output_path


def process_source(
    league_id: str,
    url: str,
) -> None:
    print()
    print("-" * 110)
    print(
        f"{league_id}: {url}"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT_SECONDS,
    )

    html = response.text

    html_path = (
        OUTPUT_DIRECTORY
        / f"{league_id}.html"
    )

    save_text(
        html_path,
        html,
    )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    report_path = write_report(
        league_id=league_id,
        url=url,
        status_code=response.status_code,
        content_type=response.headers.get(
            "Content-Type",
            "",
        ),
        html=html,
        soup=soup,
    )

    print(
        f"HTTP:       {response.status_code}"
    )

    print(
        f"Bytes:      {len(response.content)}"
    )

    print(
        f"HTML:       {html_path.resolve()}"
    )

    print(
        f"Diagnóstico:{report_path.resolve()}"
    )


def main() -> int:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("=" * 110)
    print(
        "FOOTWIN SPORTS — "
        "DIAGNÓSTICO DAS CLASSIFICAÇÕES 2025/26"
    )
    print("=" * 110)

    errors: list[str] = []

    for league_id, url in SOURCES.items():
        try:
            process_source(
                league_id,
                url,
            )

        except Exception as exc:
            errors.append(
                f"{league_id}: {exc}"
            )

            print(
                f"❌ {league_id}: {exc}"
            )

    print()
    print("=" * 110)

    if errors:
        print(
            "⚠️ DIAGNÓSTICO CONCLUÍDO COM ERROS"
        )

        for error in errors:
            print(
                f"  - {error}"
            )

        return 1

    print(
        "✅ DIAGNÓSTICO CONCLUÍDO"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
