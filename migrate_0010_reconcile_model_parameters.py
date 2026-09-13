from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = (
    BASE_DIR
    / "database"
    / "footwin_sports.db"
)

MIGRATION_ID = (
    "0010_reconcile_model_parameters"
)

DESCRIPTION = (
    "Reconstruir model_parameters ausentes "
    "dos modelos league-scoped a partir do "
    "parameters_json histórico"
)


def extract_active_parameters(
    config: dict,
) -> dict[str, float]:
    weights = config["weights"]
    performance = weights["performance"]
    promotion = weights["promotion"]
    operational = weights["operational"]

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
            performance[
                "goal_difference_weight"
            ]
        ),
        "promotion.general.champion_factor": float(
            promotion["general"][
                "champion_factor"
            ]
        ),
        "promotion.general.direct_factor": float(
            promotion["general"][
                "direct_factor"
            ]
        ),
        "promotion.general.playoff_factor": float(
            promotion["general"][
                "playoff_factor"
            ]
        ),
        "promotion.attack.champion_factor": float(
            promotion["attack"][
                "champion_factor"
            ]
        ),
        "promotion.attack.direct_factor": float(
            promotion["attack"][
                "direct_factor"
            ]
        ),
        "promotion.attack.playoff_factor": float(
            promotion["attack"][
                "playoff_factor"
            ]
        ),
        "promotion.defence.champion_factor": float(
            promotion["defence"][
                "champion_factor"
            ]
        ),
        "promotion.defence.direct_factor": float(
            promotion["defence"][
                "direct_factor"
            ]
        ),
        "promotion.defence.playoff_factor": float(
            promotion["defence"][
                "playoff_factor"
            ]
        ),
        (
            "promotion."
            "first_division_regression_weight"
        ): float(
            promotion[
                "first_division_regression_weight"
            ]
        ),
        (
            "promotion."
            "lower_table_reference_percentage"
        ): float(
            promotion[
                "lower_table_reference_percentage"
            ]
        ),
        "operational.strength_spread": float(
            operational["strength_spread"]
        ),
        (
            "operational."
            "fallback_home_goals_average"
        ): float(
            operational[
                "fallback_home_goals_average"
            ]
        ),
        (
            "operational."
            "fallback_away_goals_average"
        ): float(
            operational[
                "fallback_away_goals_average"
            ]
        ),
    }


def reconcile_model(
    connection: sqlite3.Connection,
    *,
    model_version: str,
    parameter_hash: str,
    parameters_json: str,
) -> int:
    calculated_hash = hashlib.sha256(
        parameters_json.encode("utf-8")
    ).hexdigest()

    if calculated_hash != parameter_hash:
        raise RuntimeError(
            f"{model_version}: parameter_hash "
            "não corresponde ao parameters_json."
        )

    config = json.loads(parameters_json)

    expected = extract_active_parameters(
        config
    )

    if len(expected) != 18:
        raise RuntimeError(
            f"{model_version}: esperados 18 "
            f"parâmetros ativos; encontrados "
            f"{len(expected)}."
        )

    rows = connection.execute(
        """
        SELECT
            parameter_name,
            parameter_value
        FROM model_parameters
        WHERE model_version = ?
        """,
        (model_version,),
    ).fetchall()

    stored = {
        str(row["parameter_name"]): float(
            row["parameter_value"]
        )
        for row in rows
    }

    extra = sorted(
        set(stored)
        - set(expected)
    )

    if extra:
        raise RuntimeError(
            f"{model_version}: existem parâmetros "
            f"extra inesperados: {extra}"
        )

    different = sorted(
        name
        for name in (
            set(stored)
            & set(expected)
        )
        if float(stored[name])
        != float(expected[name])
    )

    if different:
        raise RuntimeError(
            f"{model_version}: existem valores "
            f"divergentes: {different}"
        )

    missing = sorted(
        set(expected)
        - set(stored)
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
                name,
                expected[name],
            )
            for name in missing
        ],
    )

    return len(missing)


def main() -> None:
    with sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        connection.execute(
            "PRAGMA busy_timeout = 30000"
        )

        migration_exists = connection.execute(
            """
            SELECT 1
            FROM schema_migrations
            WHERE migration_id = ?
            """,
            (MIGRATION_ID,),
        ).fetchone()

        if migration_exists is not None:
            print(
                "Migração 0010 já aplicada."
            )
            return

        models = connection.execute(
            """
            SELECT
                model_version,
                parameter_hash,
                parameters_json
            FROM model_versions
            WHERE league_id IS NOT NULL
            ORDER BY
                league_id,
                created_at,
                model_version
            """
        ).fetchall()

        if not models:
            raise RuntimeError(
                "Não existem modelos "
                "league-scoped para reconciliar."
            )

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        try:
            inserted_total = 0

            for row in models:
                model_version = str(
                    row["model_version"]
                )

                inserted = reconcile_model(
                    connection,
                    model_version=(
                        model_version
                    ),
                    parameter_hash=str(
                        row["parameter_hash"]
                    ),
                    parameters_json=str(
                        row["parameters_json"]
                    ),
                )

                inserted_total += inserted

                print(
                    model_version,
                    "| inseridos =",
                    inserted,
                )

            connection.execute(
                """
                INSERT INTO schema_migrations (
                    migration_id,
                    description
                )
                VALUES (?, ?)
                """,
                (
                    MIGRATION_ID,
                    DESCRIPTION,
                ),
            )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        print(
            "TOTAL INSERIDOS =",
            inserted_total,
        )

        print(
            "INTEGRITY =",
            connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0],
        )

        print(
            "FOREIGN_KEYS =",
            connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall(),
        )


if __name__ == "__main__":
    main()
