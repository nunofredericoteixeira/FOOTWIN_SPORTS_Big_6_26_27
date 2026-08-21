from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"

MIGRATION_ID = "0008_reconcile_league_models"
DESCRIPTION = (
    "Garantir modelos ACTIVE iniciais e ratings das seis ligas "
    "na época 2026/27"
)

SEASON_LABEL = "2026/27"

LEAGUE_MODELS = {
    "POR1": {
        "model_version": "POR1_MODEL_0_1",
        "spread": 0.60,
        "home_avg": 1.55,
        "away_avg": 1.25,
    },
    "ESP1": {
        "model_version": "ESP1_MODEL_0_1",
        "spread": 0.40,
        "home_avg": 1.55,
        "away_avg": 1.25,
    },
    "ENG1": {
        "model_version": "ENG1_MODEL_0_1",
        "spread": 0.40,
        "home_avg": 1.55,
        "away_avg": 1.25,
    },
    "FRA1": {
        "model_version": "FRA1_MODEL_0_1",
        "spread": 0.40,
        "home_avg": 1.55,
        "away_avg": 1.25,
    },
    "ITA1": {
        "model_version": "ITA1_MODEL_0_1",
        "spread": 0.40,
        "home_avg": 1.55,
        "away_avg": 1.25,
    },
    "GER1": {
        "model_version": "GER1_MODEL_0_1",
        "spread": 0.40,
        "home_avg": 1.55,
        "away_avg": 1.25,
    },
}


def canonical_json(data: dict) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def extract_active_parameters(config: dict) -> dict[str, float]:
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
        "operational.strength_spread": float(
            operational["strength_spread"]
        ),
        "operational.fallback_home_goals_average": float(
            operational["fallback_home_goals_average"]
        ),
        "operational.fallback_away_goals_average": float(
            operational["fallback_away_goals_average"]
        ),
    }


def build_expected_config(
    parent_parameters_json: str,
    *,
    model_version: str,
    league_id: str,
    spread: float,
    home_avg: float,
    away_avg: float,
) -> tuple[str, str, dict[str, float]]:
    config = copy.deepcopy(
        json.loads(parent_parameters_json)
    )

    config["version"]["model_version"] = model_version
    config["version"]["created_for"] = (
        f"{league_id} — league-scoped model"
    )

    config["weights"].setdefault(
        "operational",
        {},
    )
    config["weights"]["operational"] = {
        "strength_spread": spread,
        "fallback_home_goals_average": home_avg,
        "fallback_away_goals_average": away_avg,
    }

    parameters_json = canonical_json(config)
    parameter_hash = hashlib.sha256(
        parameters_json.encode("utf-8")
    ).hexdigest()

    return (
        parameters_json,
        parameter_hash,
        extract_active_parameters(config),
    )


def ensure_initial_model(
    connection: sqlite3.Connection,
    *,
    parent_parameters_json: str,
    league_id: str,
    model_version: str,
    spread: float,
    home_avg: float,
    away_avg: float,
) -> None:
    (
        parameters_json,
        parameter_hash,
        active_parameters,
    ) = build_expected_config(
        parent_parameters_json,
        model_version=model_version,
        league_id=league_id,
        spread=spread,
        home_avg=home_avg,
        away_avg=away_avg,
    )

    existing = connection.execute(
        """
        SELECT
            model_version,
            league_id,
            season_label,
            parent_model_version,
            version_status,
            parameter_hash,
            parameters_json
        FROM model_versions
        WHERE model_version = ?
        """,
        (model_version,),
    ).fetchone()

    if existing is None:
        other_active = connection.execute(
            """
            SELECT model_version
            FROM model_versions
            WHERE league_id = ?
              AND season_label = ?
              AND version_status = 'ACTIVE'
            """,
            (league_id, SEASON_LABEL),
        ).fetchone()

        if other_active is not None:
            raise RuntimeError(
                f"{league_id} já possui ACTIVE diferente: "
                f"{other_active['model_version']}"
            )

        connection.execute(
            """
            INSERT INTO model_versions (
                model_version,
                league_id,
                season_label,
                parent_model_version,
                version_status,
                parameter_hash,
                parameters_json,
                activated_at,
                notes
            )
            VALUES (
                ?, ?, ?, 'MODEL_0_1', 'ACTIVE',
                ?, ?, CURRENT_TIMESTAMP, ?
            )
            """,
            (
                model_version,
                league_id,
                SEASON_LABEL,
                parameter_hash,
                parameters_json,
                (
                    "Versão inicial específica reconciliada "
                    f"para {league_id}; parâmetros históricos "
                    "preservados."
                ),
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
                    name,
                    value,
                )
                for name, value
                in sorted(active_parameters.items())
            ],
        )

    else:
        if str(existing["league_id"]) != league_id:
            raise RuntimeError(
                f"{model_version}: league_id inesperado."
            )

        if str(existing["season_label"]) != SEASON_LABEL:
            raise RuntimeError(
                f"{model_version}: season_label inesperado."
            )

        if (
            str(existing["parent_model_version"])
            != "MODEL_0_1"
        ):
            raise RuntimeError(
                f"{model_version}: parent inesperado."
            )

        if str(existing["parameter_hash"]) != parameter_hash:
            raise RuntimeError(
                f"{model_version}: parameter_hash diferente."
            )

        if str(existing["parameters_json"]) != parameters_json:
            raise RuntimeError(
                f"{model_version}: parameters_json diferente."
            )

        if str(existing["version_status"]) != "ACTIVE":
            other_active = connection.execute(
                """
                SELECT model_version
                FROM model_versions
                WHERE league_id = ?
                  AND season_label = ?
                  AND version_status = 'ACTIVE'
                  AND model_version <> ?
                """,
                (
                    league_id,
                    SEASON_LABEL,
                    model_version,
                ),
            ).fetchone()

            if other_active is not None:
                raise RuntimeError(
                    f"{league_id} possui ACTIVE mais recente "
                    f"{other_active['model_version']}; "
                    "a 0008 não o deve substituir."
                )

            connection.execute(
                """
                UPDATE model_versions
                SET
                    version_status = 'ACTIVE',
                    activated_at = COALESCE(
                        activated_at,
                        CURRENT_TIMESTAMP
                    ),
                    retired_at = NULL
                WHERE model_version = ?
                """,
                (model_version,),
            )

        stored_parameters = connection.execute(
            """
            SELECT COUNT(*)
            FROM model_parameters
            WHERE model_version = ?
            """,
            (model_version,),
        ).fetchone()[0]

        if int(stored_parameters) == 0:
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
                        value,
                    )
                    for name, value
                    in sorted(active_parameters.items())
                ],
            )
        elif int(stored_parameters) != len(
            active_parameters
        ):
            raise RuntimeError(
                f"{model_version}: parâmetros armazenados="
                f"{stored_parameters}; esperados="
                f"{len(active_parameters)}."
            )


def ensure_ratings(
    connection: sqlite3.Connection,
    *,
    league_id: str,
    target_model: str,
) -> None:
    target_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM team_ratings
            WHERE model_version = ?
              AND league_id = ?
              AND season_label = ?
            """,
            (
                target_model,
                league_id,
                SEASON_LABEL,
            ),
        ).fetchone()[0]
    )

    source_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM team_ratings
            WHERE model_version = 'MODEL_0_1'
              AND league_id = ?
              AND season_label = ?
            """,
            (
                league_id,
                SEASON_LABEL,
            ),
        ).fetchone()[0]
    )

    if source_count <= 0:
        raise RuntimeError(
            f"{league_id}: MODEL_0_1 sem ratings."
        )

    if target_count == source_count:
        return

    if target_count != 0:
        raise RuntimeError(
            f"{league_id}: {target_model} tem "
            f"{target_count} ratings mas MODEL_0_1 tem "
            f"{source_count}; não será feita reparação parcial."
        )

    connection.execute(
        """
        INSERT INTO team_ratings (
            team_id,
            league_id,
            season_label,
            model_version,
            run_id,
            points_per_game,
            goals_for_per_game,
            goals_against_per_game,
            goal_difference_per_game,
            ppg_rating,
            attack_rating,
            defence_rating,
            goal_difference_rating,
            performance_rating,
            absolute_rating,
            league_relative_rating,
            rating_confidence,
            created_at
        )
        SELECT
            team_id,
            league_id,
            season_label,
            ?,
            run_id,
            points_per_game,
            goals_for_per_game,
            goals_against_per_game,
            goal_difference_per_game,
            ppg_rating,
            attack_rating,
            defence_rating,
            goal_difference_rating,
            performance_rating,
            absolute_rating,
            league_relative_rating,
            rating_confidence,
            CURRENT_TIMESTAMP
        FROM team_ratings
        WHERE model_version = 'MODEL_0_1'
          AND league_id = ?
          AND season_label = ?
        """,
        (
            target_model,
            league_id,
            SEASON_LABEL,
        ),
    )


def main() -> None:
    with sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")

        migration_exists = connection.execute(
            """
            SELECT 1
            FROM schema_migrations
            WHERE migration_id = ?
            """,
            (MIGRATION_ID,),
        ).fetchone()

        if migration_exists is not None:
            print("Migração 0008 já aplicada.")
            return

        parent = connection.execute(
            """
            SELECT parameters_json
            FROM model_versions
            WHERE model_version = 'MODEL_0_1'
              AND league_id IS NULL
              AND season_label = ?
            """,
            (SEASON_LABEL,),
        ).fetchone()

        if parent is None:
            raise RuntimeError(
                "MODEL_0_1 global não encontrado."
            )

        connection.execute("BEGIN IMMEDIATE")

        try:
            for league_id, definition in (
                LEAGUE_MODELS.items()
            ):
                ensure_initial_model(
                    connection,
                    parent_parameters_json=parent[
                        "parameters_json"
                    ],
                    league_id=league_id,
                    model_version=definition[
                        "model_version"
                    ],
                    spread=definition["spread"],
                    home_avg=definition["home_avg"],
                    away_avg=definition["away_avg"],
                )

                ensure_ratings(
                    connection,
                    league_id=league_id,
                    target_model=definition[
                        "model_version"
                    ],
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

        print("=== VALIDACAO 0008 ===")

        for league_id, definition in (
            LEAGUE_MODELS.items()
        ):
            model_version = definition["model_version"]

            model = connection.execute(
                """
                SELECT
                    model_version,
                    league_id,
                    version_status
                FROM model_versions
                WHERE model_version = ?
                """,
                (model_version,),
            ).fetchone()

            params = connection.execute(
                """
                SELECT COUNT(*)
                FROM model_parameters
                WHERE model_version = ?
                """,
                (model_version,),
            ).fetchone()[0]

            ratings = connection.execute(
                """
                SELECT COUNT(*)
                FROM team_ratings
                WHERE model_version = ?
                  AND league_id = ?
                  AND season_label = ?
                """,
                (
                    model_version,
                    league_id,
                    SEASON_LABEL,
                ),
            ).fetchone()[0]

            print(
                dict(model),
                "| params =", params,
                "| ratings =", ratings,
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
