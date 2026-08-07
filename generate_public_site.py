from __future__ import annotations

from pathlib import Path

from flask import render_template_string

from web_app import (
    HTML_TEMPLATE,
    app,
    get_next_round_matches,
)


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "docs" / "index.html"


def generate_public_site() -> Path:
    round_number, matches = get_next_round_matches()

    key = ", ".join(
        match["prudent"]
        for match in matches
    )

    timestamps = [
        timestamp
        for match in matches
        for timestamp in (
            match.get("prediction_timestamp"),
            match.get("result_updated_at"),
        )
        if timestamp
    ]

    updated_at = (
        max(timestamps)
        if timestamps
        else "Sem registo"
    )

    with app.app_context():
        html = render_template_string(
            HTML_TEMPLATE,
            matches=matches,
            round_number=round_number,
            key=key,
            updated_at=updated_at,
        )

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        html,
        encoding="utf-8",
    )

    return OUTPUT_PATH


if __name__ == "__main__":
    generated_path = generate_public_site()

    print(
        "Site público gerado:",
        generated_path,
    )
