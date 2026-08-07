# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path

from src.database.init_database import connect_database
from src.models.prediction_storage_service import (
    predict_and_store_matches,
)


DEFAULT_SEASON = "2026/27"
DEFAULT_MODEL_VERSION = "MODEL_0_1"
DEFAULT_THRESHOLD = 10.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calcula e apresenta prognósticos 1X2 prudentes "
            "para uma jornada específica."
        )
    )

    parser.add_argument(
        "--league",
        required=True,
        help="Identificador da liga, por exemplo POR1.",
    )

    parser.add_argument(
        "--round",
        required=True,
        type=int,
        dest="round_number",
        help="Número da jornada.",
    )

    parser.add_argument(
        "--season",
        default=DEFAULT_SEASON,
        help=f"Época. Predefinição: {DEFAULT_SEASON}.",
    )

    parser.add_argument(
        "--model-version",
        default=DEFAULT_MODEL_VERSION,
        help=(
            "Versão do modelo. "
            f"Predefinição: {DEFAULT_MODEL_VERSION}."
        ),
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=(
            "Diferença máxima, em pontos percentuais, "
            "para utilizar dupla possibilidade. "
            f"Predefinição: {DEFAULT_THRESHOLD}."
        ),
    )

    parser.add_argument(
        "--database-path",
        type=Path,
        default=None,
        help="Caminho opcional para a base de dados SQLite.",
    )

    return parser


def build_prudent_sign(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    threshold: float,
) -> tuple[str, float]:
    probabilities = [
        ("1", home_probability),
        ("X", draw_probability),
        ("2", away_probability),
    ]

    probabilities.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    first_sign, first_probability = probabilities[0]
    second_sign, second_probability = probabilities[1]

    difference = (
        first_probability
        - second_probability
    ) * 100

    if difference > threshold:
        return first_sign, difference

    sign_order = {
        "1": 1,
        "X": 2,
        "2": 3,
    }

    prudent_sign = "".join(
        sorted(
            [first_sign, second_sign],
            key=lambda sign: sign_order[sign],
        )
    )

    return prudent_sign, difference


def main() -> None:
    args = build_parser().parse_args()

    if args.round_number < 1:
        raise SystemExit(
            "--round deve ser igual ou superior a 1."
        )

    if args.threshold < 0:
        raise SystemExit(
            "--threshold não pode ser negativo."
        )

    league_id = args.league.strip().upper()

    result = predict_and_store_matches(
        season_label=args.season,
        league_id=league_id,
        round_number=args.round_number,
        model_version=args.model_version,
        database_path=args.database_path,
    )

    connection = connect_database(
        args.database_path
    )

    try:
        rows = connection.execute(
            """
            SELECT
                m.match_date,
                ht.team_name AS home_team,
                at.team_name AS away_team,
                p.home_win_probability AS p1,
                p.draw_probability AS px,
                p.away_win_probability AS p2
            FROM match_predictions p
            INNER JOIN matches m
                ON m.match_id = p.match_id
            INNER JOIN teams ht
                ON ht.team_id = m.home_team_id
            INNER JOIN teams at
                ON at.team_id = m.away_team_id
            WHERE m.league_id = ?
              AND m.season_label = ?
              AND m.round_number = ?
              AND p.model_version = ?
            ORDER BY
                m.match_date,
                m.match_id
            """,
            (
                league_id,
                args.season,
                args.round_number,
                args.model_version,
            ),
        ).fetchall()

    finally:
        connection.close()

    if not rows:
        raise SystemExit(
            "Não foram encontrados prognósticos "
            "para os filtros indicados."
        )

    print()
    print("=" * 100)
    print(
        f"FOOTWIN SPORTS — {league_id} — "
        f"JORNADA {args.round_number} — "
        "PROGNÓSTICOS 1X2 PRUDENTES"
    )
    print("=" * 100)
    print(
        "Regra: dupla possibilidade quando a diferença "
        f"entre as duas opções mais prováveis é até "
        f"{args.threshold:.2f} pontos percentuais."
    )
    print("-" * 100)

    final_signs: list[str] = []

    for row in rows:
        prudent_sign, difference = build_prudent_sign(
            home_probability=float(row["p1"]),
            draw_probability=float(row["px"]),
            away_probability=float(row["p2"]),
            threshold=args.threshold,
        )

        final_signs.append(
            prudent_sign
        )

        print(
            f"{row['home_team']} vs {row['away_team']} | "
            f"1: {float(row['p1']) * 100:.2f}% | "
            f"X: {float(row['px']) * 100:.2f}% | "
            f"2: {float(row['p2']) * 100:.2f}% | "
            f"Prudente: {prudent_sign} | "
            f"Diferença: {difference:.2f} pp"
        )

    print("-" * 100)
    print(
        "CHAVE FINAL:",
        ", ".join(final_signs),
    )
    print("-" * 100)
    print(
        "Jogos processados:",
        result.matches_processed,
    )
    print(
        "Atualizados:",
        result.updated,
    )
    print(
        "Sem alterações:",
        result.unchanged,
    )
    print(
        "Erros:",
        result.errors,
    )
    print("=" * 100)


if __name__ == "__main__":
    main()
