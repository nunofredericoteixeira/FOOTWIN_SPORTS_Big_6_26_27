# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from src.config.path_config import load_paths_config
from src.templates.create_dataset_template import create_dataset_template
from src.utils.logger import get_logger


logger = get_logger("templates.test_dataset")


TEST_FILENAME = "TEST_DATASET_4_TEAMS.xlsx"


def create_test_dataset(
    output_path: str | Path | None = None,
    overwrite: bool = True,
) -> Path:
    """
    Cria um dataset de teste com quatro equipas e erros propositados.

    Erros introduzidos:
    - posição duplicada;
    - pontos incorretos;
    - diferença de golos incorreta;
    - soma dos jogos incorreta;
    - equipa sem registo de desempenho;
    - equipa inexistente no calendário.
    """

    paths = load_paths_config()

    if output_path is None:
        output_file = paths["data"]["input"] / TEST_FILENAME
    else:
        output_file = Path(output_path).expanduser().resolve()

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
            "ENG1_TEST_01",
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
            "ENG1_TEST_02",
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
            "ENG1_TEST_03",
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
            "ENG1_TEST_04",
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
            "ENG1_TEST_01",
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
            "https://example.com/team-1",
            "2026-07-28 00:00",
        ],
        [
            "ENG1_TEST_02",
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
            20,
            70,
            0,
            0,
            None,
            "CONFIRMED",
            1.0,
            "https://example.com/team-2",
            "2026-07-28 00:00",
        ],
        [
            "ENG1_TEST_03",
            "ENG1",
            "ENG1",
            "2025/26",
            2,
            38,
            18,
            8,
            10,
            60,
            45,
            15,
            60,
            0,
            0,
            None,
            "CONFIRMED",
            1.0,
            "https://example.com/team-3",
            "2026-07-28 00:00",
        ],
    ]

    for row in performances:
        performance_sheet.append(row)

    fixtures = [
        [
            "TEST_MATCH_001",
            "ENG1",
            "2026/27",
            1,
            "2026-08-15 15:00",
            "ENG1_TEST_01",
            "ENG1_TEST_02",
            "SCHEDULED",
            None,
            None,
            "SYNTHETIC",
            None,
        ],
        [
            "TEST_MATCH_002",
            "ENG1",
            "2026/27",
            1,
            "2026-08-15 17:30",
            "ENG1_TEST_03",
            "ENG1_TEST_99",
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
        "Dataset de teste criado | ficheiro=%s",
        output_file,
    )

    return output_file


if __name__ == "__main__":
    path = create_test_dataset()
    print(f"✅ Dataset de teste criado: {path}")
