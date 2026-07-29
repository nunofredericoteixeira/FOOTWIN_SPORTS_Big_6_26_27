# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from src.config.path_config import load_paths_config
from src.templates.create_dataset_template import create_dataset_template
from src.utils.logger import get_logger


logger = get_logger("templates.valid_test_dataset")


VALID_TEST_FILENAME = "TEST_DATASET_4_TEAMS_VALID.xlsx"


def create_valid_test_dataset(
    output_path: str | Path | None = None,
    overwrite: bool = True,
) -> Path:
    """
    Cria um dataset de teste válido com quatro equipas.

    Este ficheiro destina-se apenas a testes técnicos.
    Não cumpre os totais de produção de 114 equipas e 2.058 jogos,
    mas todos os seus registos individuais são coerentes.
    """

    paths = load_paths_config()

    if output_path is None:
        output_file = (
            paths["data"]["input"]
            / VALID_TEST_FILENAME
        )
    else:
        output_file = Path(
            output_path
        ).expanduser().resolve()

    if output_file.exists() and not overwrite:
        raise FileExistsError(
            f"O ficheiro já existe: {output_file}"
        )

    create_dataset_template(
        output_path=output_file,
        overwrite=True,
    )

    workbook = load_workbook(output_file)

    teams_sheet = workbook["Equipas_2026_27"]
    performance_sheet = workbook["Desempenho_2025_26"]
    fixtures_sheet = workbook["Calendario_2026_27"]

    teams = [
        [
            "ENG1_VALID_01",
            "Footwin City",
            "FW City",
            "footwin_city",
            "ENG1",
            "England",
            "2026/27",
            0,
            None,
            "ENG1",
            1,
        ],
        [
            "ENG1_VALID_02",
            "Footwin United",
            "FW United",
            "footwin_united",
            "ENG1",
            "England",
            "2026/27",
            0,
            None,
            "ENG1",
            1,
        ],
        [
            "ENG1_VALID_03",
            "Footwin Athletic",
            "FW Athletic",
            "footwin_athletic",
            "ENG1",
            "England",
            "2026/27",
            0,
            None,
            "ENG1",
            1,
        ],
        [
            "ENG1_VALID_04",
            "Footwin Rovers",
            "FW Rovers",
            "footwin_rovers",
            "ENG1",
            "England",
            "2026/27",
            0,
            None,
            "ENG1",
            1,
        ],
    ]

    for row in teams:
        teams_sheet.append(row)

    performances = [
        [
            "ENG1_VALID_01",
            "ENG1",
            "ENG1",
            "2025/26",
            1,
            38,
            25,
            8,
            5,
            80,
            30,
            50,
            83,
            0,
            0,
            None,
            "CONFIRMED",
            1.0,
            "https://example.com/valid-team-1",
            "2026-07-28 20:00",
        ],
        [
            "ENG1_VALID_02",
            "ENG1",
            "ENG1",
            "2025/26",
            2,
            38,
            20,
            10,
            8,
            65,
            40,
            25,
            70,
            0,
            0,
            None,
            "CONFIRMED",
            1.0,
            "https://example.com/valid-team-2",
            "2026-07-28 20:00",
        ],
        [
            "ENG1_VALID_03",
            "ENG1",
            "ENG1",
            "2025/26",
            3,
            38,
            18,
            10,
            10,
            60,
            45,
            15,
            64,
            0,
            0,
            None,
            "CONFIRMED",
            1.0,
            "https://example.com/valid-team-3",
            "2026-07-28 20:00",
        ],
        [
            "ENG1_VALID_04",
            "ENG1",
            "ENG1",
            "2025/26",
            4,
            38,
            15,
            10,
            13,
            52,
            48,
            4,
            55,
            0,
            0,
            None,
            "CONFIRMED",
            1.0,
            "https://example.com/valid-team-4",
            "2026-07-28 20:00",
        ],
    ]

    for row in performances:
        performance_sheet.append(row)

    fixtures = [
        [
            "VALID_MATCH_001",
            "ENG1",
            "2026/27",
            1,
            "2026-08-15 15:00",
            "ENG1_VALID_01",
            "ENG1_VALID_02",
            "SCHEDULED",
            None,
            None,
            "SYNTHETIC",
            None,
        ],
        [
            "VALID_MATCH_002",
            "ENG1",
            "2026/27",
            1,
            "2026-08-15 17:30",
            "ENG1_VALID_03",
            "ENG1_VALID_04",
            "SCHEDULED",
            None,
            None,
            "SYNTHETIC",
            None,
        ],
        [
            "VALID_MATCH_003",
            "ENG1",
            "2026/27",
            2,
            "2026-08-22 15:00",
            "ENG1_VALID_02",
            "ENG1_VALID_03",
            "SCHEDULED",
            None,
            None,
            "SYNTHETIC",
            None,
        ],
        [
            "VALID_MATCH_004",
            "ENG1",
            "2026/27",
            2,
            "2026-08-22 17:30",
            "ENG1_VALID_04",
            "ENG1_VALID_01",
            "SCHEDULED",
            None,
            None,
            "SYNTHETIC",
            None,
        ],
    ]

    for row in fixtures:
        fixtures_sheet.append(row)

    workbook.save(output_file)
    workbook.close()

    logger.info(
        "Dataset de teste válido criado | ficheiro=%s",
        output_file,
    )

    return output_file


if __name__ == "__main__":
    created_path = create_valid_test_dataset()

    print(
        f"✅ Dataset de teste válido criado: {created_path}"
    )
