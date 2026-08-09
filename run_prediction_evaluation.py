# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse

from src.services.prediction_evaluation_service import (
    run_prediction_evaluation,
)
from src.utils.logger import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Avalia previsões oficiais de jogos concluídos "
            "e grava as métricas na base de dados."
        )
    )

    parser.add_argument(
        "--league",
        dest="league_id",
        help="Filtrar por liga, por exemplo POR1.",
    )

    parser.add_argument(
        "--season",
        dest="season_label",
        default="2026/27",
        help="Época a avaliar. Predefinição: 2026/27.",
    )

    parser.add_argument(
        "--model-version",
        dest="model_version",
        default="MODEL_0_1",
        help="Versão do modelo. Predefinição: MODEL_0_1.",
    )

    return parser


def main() -> None:
    configure_logging()

    arguments = build_parser().parse_args()

    summary = run_prediction_evaluation(
        league_id=arguments.league_id,
        season_label=arguments.season_label,
        model_version=arguments.model_version,
    )

    print()
    print("=" * 72)
    print("AVALIAÇÃO DE PREVISÕES")
    print("=" * 72)
    print(
        "Previsões elegíveis: "
        f"{summary.eligible_predictions}"
    )
    print(
        "Avaliações gravadas: "
        f"{summary.inserted_evaluations}"
    )
    print(
        "Avaliações já existentes: "
        f"{summary.existing_evaluations}"
    )
    print(
        "Falhas: "
        f"{summary.failed_evaluations}"
    )


if __name__ == "__main__":
    main()
