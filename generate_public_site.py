from __future__ import annotations

from pathlib import Path

from flask import render_template_string

from web_app import (
    HTML_TEMPLATE,
    app,
    get_algorithm_accuracy,
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

    future_matches = [
        match
        for match in matches
        if match["status"] in (
            "SCHEDULED",
            "POSTPONED",
        )
    ]

    next_match_id = None

    if future_matches:
        next_match = min(
            future_matches,
            key=lambda match: match["sort_timestamp"],
        )
        next_match_id = next_match["match_id"]

    for match in matches:
        match.setdefault("bet_odd", None)
        match.setdefault("bet_stake", None)
        match.setdefault("bet_prudent", match.get("prudent"))
        match.setdefault("bet_status", "pending")

    accuracy = get_algorithm_accuracy()

    algorithm_accuracy_label = (
        "Sem dados"
        if accuracy is None
        else f"{accuracy:.2f}%"
    )

    with app.app_context():
        html = render_template_string(
            HTML_TEMPLATE,
            matches=matches,
            round_number=round_number,
            key=key,
            updated_at=updated_at,
            algorithm_accuracy_label=algorithm_accuracy_label,
            next_match_id=next_match_id,
            initial_bankroll=0.0,
            current_bankroll=0.0,
            stake_mode="FIXED",
            default_stake_value=0.0,
        )

        # O Flask local usa /assets/..., mas o GitHub Pages publica
        # o site dentro da pasta do repositório. No HTML estático,
        # os caminhos devem ser relativos ao docs/index.html.
        html = html.replace(
            'src="/assets/',
            'src="assets/',
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
