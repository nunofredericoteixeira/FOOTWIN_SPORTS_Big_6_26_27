# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from src.config.model_config import load_full_model_config
from src.database.init_database import get_database_path


MODEL_NOTES = (
    "Versão inicial imutável do modelo coletivo FOOTWIN SPORTS. "
    "Registada a partir da configuração oficial existente."
)


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def extract_active_parameters(
    config: dict[str, Any],
) -> dict[str, float]:
    weights = config["weights"]
    performance = weights["performance"]
    promotion = weights["promotion"]

    return {
        "performance.ppg_weight": float(
            performance["ppg_weight"]
        ),
        "performance.attack_weight": float(
            performance["attack_weight"]
        ),
        "performance.defence_weight": float(
            performance["defence_weight"]
        ),
        "performance.goal_difference_weight": float(
            performance["goal_difference_weight"]
        ),
        "promotion.general.champion_factor": float(
            promotion["general"]["champion_factor"]
        ),
        "promotion.general.direct_factor": float(
            promotion["general"]["direct_factor"]
        ),
        "promotion.general.playoff_factor": float(
            promotion["general"]["playoff_factor"]
        ),
        "promotion.attack.champion_factor": float(
            promotion["attack"]["champion_factor"]
        ),
        "promotion.attack.direct_factor": float(
            promotion["attack"]["direct_factor"]
        ),
        "promotion.attack.playoff_factor": float(
            promotion["attack"]["playoff_factor"]
        ),
        "promotion.defence.champion_factor": float(
            promotion["defence"]["champion_factor"]
        ),
        "promotion.defence.direct_factor": float(
            promotion["defence"]["direct_factor"]
        ),
        "promotion.defence.playoff_factor": float(
            promotion["defence"]["playoff_factor"]
        ),
        "promotion.first_division_regression_weight": float(
            promotion["first_division_regression_weight"]
        ),
        "promotion.lower_table_reference_percentage": float(
            promotion["lower_table_reference_percentage"]
        ),
    }


def main() -> None:
    config = load_full_model_config()
    version_config = config["version"]

    model_version = str(version_config["model_version"])
    season_label = str(version_config["season_label"])
    parameters_json = canonical_json(config)
    parameter_hash = hashlib.sha256(
        parameters_json.encode("utf-8")
    ).hexdigest()
    active_parameters = extract_active_parameters(config)

    database_path = get_database_path()
    connection = sqlite3.connect(
        database_path,
        timeout=30,
    )
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("BEGIN IMMEDIATE")

        existing = connection.execute(
            """
            SELECT
                model_version,
                season_label,
                version_status,
                parameter_hash,
                parameters_json
            FROM model_versions
            WHERE model_version = ?
            """,
            (model_version,),
        ).fetchone()

        if existing is not None:
            if (
                str(existing["season_label"]) != season_label
                or str(existing["parameter_hash"]) != parameter_hash
                or str(existing["parameters_json"]) != parameters_json
            ):
                raise RuntimeError(
                    f"{model_version} já existe com configuração diferente."
                )

            stored_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM model_parameters
                WHERE model_version = ?
                """,
                (model_version,),
            ).fetchone()[0]

            if int(stored_count) != len(active_parameters):
                raise RuntimeError(
                    f"{model_version} já existe, mas tem "
                    f"{stored_count} parâmetros em vez de "
                    f"{len(active_parameters)}."
                )

            connection.rollback()
            print(
                f"{model_version} já está registado corretamente. "
                "Nenhuma alteração efetuada."
            )
            return

        connection.execute(
            """
            INSERT INTO model_versions (
                model_version,
                season_label,
                parent_model_version,
                version_status,
                parameter_hash,
                parameters_json,
                activated_at,
                notes
            )
            VALUES (?, ?, NULL, 'ACTIVE', ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                model_version,
                season_label,
                parameter_hash,
                parameters_json,
                MODEL_NOTES,
            ),
        )

        connection.executemany(
            """
            INSERT INTO model_parameters (
                model_version,
                parameter_name,
                parameter_value
            )
            VALUES (?, ?, ?)
            """,
            [
                (
                    model_version,
                    parameter_name,
                    parameter_value,
                )
                for parameter_name, parameter_value
                in sorted(active_parameters.items())
            ],
        )

        connection.commit()

        print(f"Modelo registado: {model_version}")
        print(f"Época: {season_label}")
        print("Estado: ACTIVE")
        print(f"Hash: {parameter_hash}")
        print(f"Parâmetros ativos: {len(active_parameters)}")

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
