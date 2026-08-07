# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


RAW_DIRECTORY = Path(
    "data/raw/team_pages"
)

OUTPUT_DIRECTORY = Path(
    "data/raw/team_candidates"
)


ENGLISH_TEAM_HINTS = (
    "arsenal",
    "aston villa",
    "bournemouth",
    "brentford",
    "brighton",
    "burnley",
    "chelsea",
    "crystal palace",
    "everton",
    "fulham",
    "leeds",
    "liverpool",
    "manchester",
    "newcastle",
    "nottingham",
    "sunderland",
    "tottenham",
    "west ham",
    "wolves",
    "wolverhampton",
)

PORTUGUESE_TEAM_HINTS = (
    "benfica",
    "porto",
    "sporting",
    "braga",
    "guimarães",
    "guimaraes",
    "vitória",
    "vitoria",
    "famalicão",
    "famalicao",
    "gil vicente",
    "moreirense",
    "rio ave",
    "estoril",
    "casa pia",
    "santa clara",
    "nacional",
    "alverca",
    "aves",
    "tondela",
    "chaves",
    "farense",
    "marítimo",
    "maritimo",
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def unique_preserving_order(
    values: list[str],
) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        cleaned = clean_text(value)

        if not cleaned:
            continue

        key = cleaned.casefold()

        if key in seen:
            continue

        seen.add(key)
        result.append(cleaned)

    return result


def extract_contexts(
    text: str,
    hints: tuple[str, ...],
    context_size: int = 180,
) -> list[str]:
    lower_text = text.lower()
    contexts: list[str] = []

    for hint in hints:
        start = 0

        while True:
            index = lower_text.find(
                hint.lower(),
                start,
            )

            if index < 0:
                break

            left = max(
                0,
                index - context_size,
            )

            right = min(
                len(text),
                index + len(hint) + context_size,
            )

            context = clean_text(
                text[left:right]
            )

            contexts.append(
                context
            )

            start = index + len(hint)

    return unique_preserving_order(
        contexts
    )


def extract_attribute_candidates(
    html: str,
) -> list[str]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    values: list[str] = []

    attributes = (
        "alt",
        "title",
        "aria-label",
        "data-team",
        "data-club",
        "data-name",
        "href",
        "src",
    )

    for tag in soup.find_all(True):
        for attribute in attributes:
            value = tag.get(attribute)

            if not value:
                continue

            cleaned = clean_text(value)

            lower = cleaned.lower()

            if any(
                marker in lower
                for marker in (
                    "team",
                    "club",
                    "crest",
                    "badge",
                    "logo",
                    "squad",
                    "arsenal",
                    "liverpool",
                    "manchester",
                    "benfica",
                    "porto",
                    "sporting",
                    "braga",
                )
            ):
                values.append(
                    f"{attribute}={cleaned}"
                )

    return unique_preserving_order(
        values
    )


def extract_filename_candidates(
    html: str,
) -> list[str]:
    patterns = (
        r"""["']([^"']*(?:team|club|crest|badge|logo)[^"']*)["']""",
        r"""https?://[^\s"'<>\\]+""",
        r"""(?:/|\\/)assets/[^\s"'<>\\]+""",
        r"""(?:/|\\/)media/[^\s"'<>\\]+""",
        r"""(?:/|\\/)images/[^\s"'<>\\]+""",
    )

    results: list[str] = []

    for pattern in patterns:
        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE,
        )

        for match in matches:
            value = (
                match
                .replace("\\/", "/")
                .replace("\\u0026", "&")
            )

            if any(
                hint in value.lower()
                for hint in (
                    ENGLISH_TEAM_HINTS
                    + PORTUGUESE_TEAM_HINTS
                )
            ):
                results.append(
                    value
                )

    return unique_preserving_order(
        results
    )


def flatten_json_values(
    value: Any,
    results: list[str],
) -> None:
    if isinstance(value, str):
        results.append(
            value
        )
        return

    if isinstance(value, list):
        for item in value:
            flatten_json_values(
                item,
                results,
            )
        return

    if isinstance(value, dict):
        for key, item in value.items():
            results.append(
                str(key)
            )

            flatten_json_values(
                item,
                results,
            )


def extract_nuxt_team_candidates(
    html: str,
) -> list[str]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    script = soup.find(
        "script",
        id="__NUXT_DATA__",
    )

    if script is None:
        return []

    content = (
        script.string
        or script.get_text()
        or ""
    ).strip()

    data = json.loads(
        content
    )

    values: list[str] = []

    flatten_json_values(
        data,
        values,
    )

    candidates: list[str] = []

    for value in values:
        cleaned = clean_text(
            value
        )

        lower = cleaned.lower()

        if any(
            hint in lower
            for hint in PORTUGUESE_TEAM_HINTS
        ):
            candidates.append(
                cleaned
            )

    return unique_preserving_order(
        candidates
    )


def write_section(
    output_path: Path,
    title: str,
    values: list[str],
) -> None:
    with output_path.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(
            "\n"
            + "=" * 120
            + "\n"
        )

        file.write(
            title
            + "\n"
        )

        file.write(
            "=" * 120
            + "\n"
        )

        file.write(
            f"TOTAL: {len(values)}\n\n"
        )

        for value in values:
            file.write(
                f"{value}\n"
            )


def process_england() -> None:
    input_path = (
        RAW_DIRECTORY
        / "ENG1.html"
    )

    output_path = (
        OUTPUT_DIRECTORY
        / "ENG1_candidates.txt"
    )

    html = input_path.read_text(
        encoding="utf-8",
    )

    output_path.write_text(
        "",
        encoding="utf-8",
    )

    contexts = extract_contexts(
        text=html,
        hints=ENGLISH_TEAM_HINTS,
    )

    attributes = extract_attribute_candidates(
        html
    )

    filenames = extract_filename_candidates(
        html
    )

    write_section(
        output_path,
        "CONTEXTOS COM NOMES DE EQUIPAS",
        contexts,
    )

    write_section(
        output_path,
        "ATRIBUTOS HTML CANDIDATOS",
        attributes,
    )

    write_section(
        output_path,
        "URLS E FICHEIROS CANDIDATOS",
        filenames,
    )

    print()
    print(
        "ENG1:"
    )

    print(
        f"  Contextos:  {len(contexts)}"
    )

    print(
        f"  Atributos:  {len(attributes)}"
    )

    print(
        f"  Ficheiros:  {len(filenames)}"
    )

    print(
        f"  Resultado:  {output_path.resolve()}"
    )


def process_portugal() -> None:
    input_path = (
        RAW_DIRECTORY
        / "POR1.html"
    )

    output_path = (
        OUTPUT_DIRECTORY
        / "POR1_candidates.txt"
    )

    html = input_path.read_text(
        encoding="utf-8",
    )

    output_path.write_text(
        "",
        encoding="utf-8",
    )

    contexts = extract_contexts(
        text=html,
        hints=PORTUGUESE_TEAM_HINTS,
    )

    attributes = extract_attribute_candidates(
        html
    )

    filenames = extract_filename_candidates(
        html
    )

    nuxt_candidates = (
        extract_nuxt_team_candidates(
            html
        )
    )

    write_section(
        output_path,
        "CONTEXTOS COM NOMES DE EQUIPAS",
        contexts,
    )

    write_section(
        output_path,
        "VALORES DO NUXT COM NOMES DE EQUIPAS",
        nuxt_candidates,
    )

    write_section(
        output_path,
        "ATRIBUTOS HTML CANDIDATOS",
        attributes,
    )

    write_section(
        output_path,
        "URLS E FICHEIROS CANDIDATOS",
        filenames,
    )

    print()
    print(
        "POR1:"
    )

    print(
        f"  Contextos:       {len(contexts)}"
    )

    print(
        f"  Valores Nuxt:    "
        f"{len(nuxt_candidates)}"
    )

    print(
        f"  Atributos:       "
        f"{len(attributes)}"
    )

    print(
        f"  Ficheiros:       "
        f"{len(filenames)}"
    )

    print(
        f"  Resultado:       "
        f"{output_path.resolve()}"
    )


def main() -> int:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("=" * 120)
    print(
        "EXTRAÇÃO DE CANDIDATOS — ENG1 E POR1"
    )
    print("=" * 120)

    process_england()
    process_portugal()

    print()
    print("=" * 120)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
