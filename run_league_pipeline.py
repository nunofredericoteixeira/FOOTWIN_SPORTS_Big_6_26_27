# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.services.league_prediction_pipeline import (
    LeaguePredictionPipelineError,
    print_pipeline_summary,
    run_league_prediction_pipeline,
)
from src.utils.logger import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Executa previsões, simulação Monte Carlo "
            "e exportação Excel de uma liga."
        )
    )

    parser.add_argument(
        "--league",
        required=True,
        help="Identificador da liga. Exemplo: ENG1",
    )

    parser.add_argument(
        "--season",
        default="2026/27",
        help="Época desportiva.",
    )

    parser.add_argument(
        "--model-version",
        default="MODEL_0_1",
        help="Versão do modelo.",
    )

    parser.add_argument(
        "--dataset-version",
        default=None,
        help="Dataset específico dos jogos.",
    )

    parser.add_argument(
        "--simulations",
        type=int,
        default=10_000,
        help="Número de simulações Monte Carlo.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=202627,
        help="Seed aleatória reproduzível.",
    )

    parser.add_argument(
        "--europe-places",
        type=int,
        default=4,
        help="Número de lugares europeus.",
    )

    parser.add_argument(
        "--relegation-places",
        type=int,
        default=3,
        help="Número de lugares de descida direta.",
    )

    parser.add_argument(
        "--playoff-places",
        type=int,
        default=0,
        help="Número de lugares de playoff.",
    )

    parser.add_argument(
        "--max-goals",
        type=int,
        default=12,
        help="Máximo de golos da matriz de Poisson.",
    )

    parser.add_argument(
        "--score-limit",
        type=int,
        default=10,
        help="Número de marcadores prováveis guardados.",
    )

    parser.add_argument(
        "--output-directory",
        default="outputs/simulations",
        help="Diretório do ficheiro Excel.",
    )

    parser.add_argument(
        "--output-filename",
        default=None,
        help="Nome personalizado do ficheiro Excel.",
    )

    parser.add_argument(
        "--database-path",
        default=None,
        help="Caminho alternativo da base SQLite.",
    )

    return parser


def main() -> int:
    configure_logging()

    parser = build_parser()
    args = parser.parse_args()

    try:
        result = run_league_prediction_pipeline(
            league_id=args.league,
            season_label=args.season,
            model_version=args.model_version,
            dataset_version=(
                args.dataset_version
            ),
            simulation_count=(
                args.simulations
            ),
            random_seed=args.seed,
            europe_places=(
                args.europe_places
            ),
            relegation_places=(
                args.relegation_places
            ),
            playoff_places=(
                args.playoff_places
            ),
            max_goals=args.max_goals,
            score_limit=args.score_limit,
            output_directory=Path(
                args.output_directory
            ),
            output_filename=(
                args.output_filename
            ),
            database_path=(
                args.database_path
            ),
        )

        print_pipeline_summary(
            result
        )

        return 0

    except LeaguePredictionPipelineError as exc:
        print()
        print("=" * 100)
        print("❌ PIPELINE INTERROMPIDO")
        print("=" * 100)
        print(exc)
        print("=" * 100)

        return 1

    except KeyboardInterrupt:
        print()
        print("⚠️ Execução interrompida pelo utilizador.")

        return 130

    except Exception as exc:
        print()
        print("=" * 100)
        print("❌ ERRO INESPERADO")
        print("=" * 100)
        print(exc)
        print("=" * 100)

        return 1


if __name__ == "__main__":
    sys.exit(
        main()
    )
