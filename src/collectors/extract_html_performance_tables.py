# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


INPUT_DIRECTORY = Path(
    "data/raw/performance_pages"
)

LEAGUES = {
    "ITA1": INPUT_DIRECTORY / "ITA1.html",
    "GER1": INPUT_DIRECTORY / "GER1.html",
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


def extract_table_rows(
    html_path: Path,
) -> list[list[str]]:
    html = html_path.read_text(
        encoding="utf-8",
    )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    tables = soup.find_all(
        "table"
    )

    print(
        f"Tabelas encontradas: {len(tables)}"
    )

    all_rows: list[list[str]] = []

    for table_number, table in enumerate(
        tables,
        start=1,
    ):
        print()
        print(
            f"--- TABELA #{table_number} ---"
        )

        rows = table.find_all(
            "tr"
        )

        print(
            f"Linhas HTML: {len(rows)}"
        )

        for row in rows:
            cells = row.find_all(
                [
                    "th",
                    "td",
                ]
            )

            values = [
                clean_text(
                    cell.get_text(
                        " ",
                        strip=True,
                    )
                )
                for cell in cells
            ]

            values = [
                value
                for value in values
                if value
            ]

            if values:
                all_rows.append(
                    values
                )

    return all_rows


def print_rows(
    league_id: str,
    rows: list[list[str]],
) -> None:
    print()
    print("=" * 120)
    print(
        f"{league_id} — LINHAS EXTRAÍDAS"
    )
    print("=" * 120)

    print(
        f"Total de linhas úteis: {len(rows)}"
    )

    for row_number, row in enumerate(
        rows,
        start=1,
    ):
        print()
        print(
            f"{row_number:02d}: {row}"
        )

    print()
    print("=" * 120)


def process_league(
    league_id: str,
    html_path: Path,
) -> None:
    print()
    print("#" * 120)
    print(
        f"{league_id}: {html_path.resolve()}"
    )
    print("#" * 120)

    if not html_path.exists():
        raise FileNotFoundError(
            f"Ficheiro inexistente: "
            f"{html_path}"
        )

    rows = extract_table_rows(
        html_path
    )

    print_rows(
        league_id,
        rows,
    )


def main() -> int:
    print()
    print("=" * 120)
    print(
        "FOOTWIN SPORTS — EXTRAÇÃO DAS TABELAS HTML"
    )
    print("=" * 120)

    errors: list[str] = []

    for league_id, html_path in (
        LEAGUES.items()
    ):
        try:
            process_league(
                league_id,
                html_path,
            )

        except Exception as exc:
            errors.append(
                f"{league_id}: {exc}"
            )

            print()
            print(
                f"❌ {league_id}: {exc}"
            )

    if errors:
        print()
        print("=" * 120)
        print(
            "⚠️ EXTRAÇÃO CONCLUÍDA COM ERROS"
        )

        for error in errors:
            print(
                f"  - {error}"
            )

        print("=" * 120)

        return 1

    print()
    print(
        "✅ EXTRAÇÃO CONCLUÍDA"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
