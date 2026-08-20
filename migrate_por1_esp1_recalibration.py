from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"

MIGRATION_ID = "0007_por1_esp1_recalibration"
DESCRIPTION = "Registar recalibracao POR1 e candidato ESP1 com modelos por liga"

def canonical_json(data: dict) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def extract_active_parameters(config: dict) -> dict[str, float]:
    w = config["weights"]
    p = w["performance"]
    pr = w["promotion"]
    op = w["operational"]

    return {
        "performance.ppg_weight": float(p["ppg_weight"]),
        "performance.attack_weight": float(p["attack_weight"]),
        "performance.defence_weight": float(p["defence_weight"]),
        "performance.goal_difference_weight": float(p["goal_difference_weight"]),
        "promotion.general.champion_factor": float(pr["general"]["champion_factor"]),
        "promotion.general.direct_factor": float(pr["general"]["direct_factor"]),
        "promotion.general.playoff_factor": float(pr["general"]["playoff_factor"]),
        "promotion.attack.champion_factor": float(pr["attack"]["champion_factor"]),
        "promotion.attack.direct_factor": float(pr["attack"]["direct_factor"]),
        "promotion.attack.playoff_factor": float(pr["attack"]["playoff_factor"]),
        "promotion.defence.champion_factor": float(pr["defence"]["champion_factor"]),
        "promotion.defence.direct_factor": float(pr["defence"]["direct_factor"]),
        "promotion.defence.playoff_factor": float(pr["defence"]["playoff_factor"]),
        "promotion.first_division_regression_weight": float(
            pr["first_division_regression_weight"]
        ),
        "promotion.lower_table_reference_percentage": float(
            pr["lower_table_reference_percentage"]
        ),
        "operational.strength_spread": float(op["strength_spread"]),
        "operational.fallback_home_goals_average": float(
            op["fallback_home_goals_average"]
        ),
        "operational.fallback_away_goals_average": float(
            op["fallback_away_goals_average"]
        ),
    }

def ensure_model(
    con: sqlite3.Connection,
    *,
    model_version: str,
    league_id: str,
    parent_model_version: str,
    status: str,
    spread: float,
    home_avg: float,
    away_avg: float,
    notes: str,
) -> None:
    existing = con.execute(
        "SELECT * FROM model_versions WHERE model_version = ?",
        (model_version,),
    ).fetchone()

    if existing is not None:
        return

    parent = con.execute(
        "SELECT parameters_json FROM model_versions WHERE model_version = ?",
        (parent_model_version,),
    ).fetchone()

    if parent is None:
        raise RuntimeError(f"Modelo pai inexistente: {parent_model_version}")

    cfg = copy.deepcopy(json.loads(parent["parameters_json"]))
    cfg["version"]["model_version"] = model_version
    cfg["version"]["created_for"] = f"{league_id} — league-scoped model"
    cfg["weights"].setdefault("operational", {})
    cfg["weights"]["operational"] = {
        "strength_spread": spread,
        "fallback_home_goals_average": home_avg,
        "fallback_away_goals_average": away_avg,
    }

    parameters_json = canonical_json(cfg)
    parameter_hash = hashlib.sha256(
        parameters_json.encode("utf-8")
    ).hexdigest()

    con.execute(
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
            ?, ?, '2026/27', ?, ?, ?, ?,
            CASE WHEN ? = 'ACTIVE' THEN CURRENT_TIMESTAMP ELSE NULL END,
            ?
        )
        """,
        (
            model_version,
            league_id,
            parent_model_version,
            status,
            parameter_hash,
            parameters_json,
            status,
            notes,
        ),
    )

    active_parameters = extract_active_parameters(cfg)

    con.executemany(
        """
        INSERT INTO model_parameters (
            model_version,
            parameter_name,
            parameter_value
        )
        VALUES (?, ?, ?)
        """,
        [
            (model_version, name, value)
            for name, value in sorted(active_parameters.items())
        ],
    )

def copy_ratings(
    con: sqlite3.Connection,
    source_model: str,
    target_model: str,
    league_id: str,
) -> None:
    count = con.execute(
        """
        SELECT COUNT(*)
        FROM team_ratings
        WHERE model_version = ?
          AND league_id = ?
          AND season_label = '2026/27'
        """,
        (target_model, league_id),
    ).fetchone()[0]

    if count:
        return

    con.execute(
        """
        INSERT INTO team_ratings (
            team_id, league_id, season_label, model_version, run_id,
            points_per_game, goals_for_per_game, goals_against_per_game,
            goal_difference_per_game, ppg_rating, attack_rating,
            defence_rating, goal_difference_rating, performance_rating,
            absolute_rating, league_relative_rating, rating_confidence,
            created_at
        )
        SELECT
            team_id, league_id, season_label, ?, run_id,
            points_per_game, goals_for_per_game, goals_against_per_game,
            goal_difference_per_game, ppg_rating, attack_rating,
            defence_rating, goal_difference_rating, performance_rating,
            absolute_rating, league_relative_rating, rating_confidence,
            CURRENT_TIMESTAMP
        FROM team_ratings
        WHERE model_version = ?
          AND league_id = ?
          AND season_label = '2026/27'
        """,
        (target_model, source_model, league_id),
    )

def ensure_candidate(
    con: sqlite3.Connection,
    *,
    candidate_model_version: str,
    parent_model_version: str,
    league_id: str,
    sample_size: int,
    baseline_brier: float,
    candidate_brier: float,
    baseline_logloss: float,
    candidate_logloss: float,
    baseline_accuracy: float,
    candidate_accuracy: float,
    candidate_status: str,
    decision: str,
    reason: str,
) -> None:
    row = con.execute(
        """
        SELECT candidate_id
        FROM model_candidates
        WHERE candidate_model_version = ?
        """,
        (candidate_model_version,),
    ).fetchone()

    if row is None:
        cur = con.execute(
            """
            INSERT INTO model_candidates (
                candidate_model_version,
                parent_model_version,
                league_id,
                evaluation_scope,
                sample_size,
                baseline_brier_score,
                candidate_brier_score,
                baseline_log_loss,
                candidate_log_loss,
                baseline_outcome_accuracy,
                candidate_outcome_accuracy,
                candidate_status,
                evaluated_at
            )
            VALUES (
                ?, ?, ?, 'LEAGUE', ?,
                ?, ?, ?, ?, ?, ?,
                ?, CURRENT_TIMESTAMP
            )
            """,
            (
                candidate_model_version,
                parent_model_version,
                league_id,
                sample_size,
                baseline_brier,
                candidate_brier,
                baseline_logloss,
                candidate_logloss,
                baseline_accuracy,
                candidate_accuracy,
                candidate_status,
            ),
        )
        candidate_id = cur.lastrowid
    else:
        candidate_id = row["candidate_id"]

    decision_exists = con.execute(
        """
        SELECT 1
        FROM model_promotion_decisions
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchone()

    if decision_exists is None:
        con.execute(
            """
            INSERT INTO model_promotion_decisions (
                candidate_id,
                decision,
                sample_size,
                brier_improvement,
                log_loss_improvement,
                outcome_accuracy_improvement,
                decision_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                decision,
                sample_size,
                baseline_brier - candidate_brier,
                baseline_logloss - candidate_logloss,
                candidate_accuracy - baseline_accuracy,
                reason,
            ),
        )

with sqlite3.connect(DATABASE_PATH) as con:
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    already = con.execute(
        "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
        (MIGRATION_ID,),
    ).fetchone()

    if already is not None:
        print("Migração já aplicada.")
        raise SystemExit(0)

    con.execute("BEGIN IMMEDIATE")

    # ESP1 base específico, necessário no Render
    ensure_model(
        con,
        model_version="ESP1_MODEL_0_1",
        league_id="ESP1",
        parent_model_version="MODEL_0_1",
        status="ACTIVE",
        spread=0.40,
        home_avg=1.55,
        away_avg=1.25,
        notes="Modelo inicial específico ESP1 equivalente ao modelo coletivo de referência.",
    )
    copy_ratings(con, "MODEL_0_1", "ESP1_MODEL_0_1", "ESP1")

    # POR1 recalibrado e promovido
    ensure_model(
        con,
        model_version="POR1_MODEL_0_1",
        league_id="POR1",
        parent_model_version="MODEL_0_1",
        status="ACTIVE",
        spread=0.60,
        home_avg=1.55,
        away_avg=1.25,
        notes=(
            "Recalibração POR1 após 17 jogos: "
            "strength_spread 0.40 -> 0.60; fallbacks preservados."
        ),
    )
    copy_ratings(con, "MODEL_0_1", "POR1_MODEL_0_1", "POR1")

    ensure_candidate(
        con,
        candidate_model_version="POR1_MODEL_0_1",
        parent_model_version="MODEL_0_1",
        league_id="POR1",
        sample_size=17,
        baseline_brier=0.586214,
        candidate_brier=0.583236,
        baseline_logloss=0.976355,
        candidate_logloss=0.965985,
        baseline_accuracy=52.94,
        candidate_accuracy=52.94,
        candidate_status="PROMOTED",
        decision="PROMOTE",
        reason=(
            "Melhora Brier e log-loss sem aumentar sinais/jogo nem degradar 1X2; "
            "validado com R1 treino e R2 holdout."
        ),
    )

    # ESP1 candidato
    ensure_model(
        con,
        model_version="ESP1_MODEL_0_2",
        league_id="ESP1",
        parent_model_version="ESP1_MODEL_0_1",
        status="CANDIDATE",
        spread=0.10,
        home_avg=1.75,
        away_avg=0.95,
        notes=(
            "Candidato ESP1 após 4 jogos; leave-one-out consistente, "
            "mas amostra insuficiente para ativação."
        ),
    )
    copy_ratings(con, "ESP1_MODEL_0_1", "ESP1_MODEL_0_2", "ESP1")

    ensure_candidate(
        con,
        candidate_model_version="ESP1_MODEL_0_2",
        parent_model_version="ESP1_MODEL_0_1",
        league_id="ESP1",
        sample_size=4,
        baseline_brier=0.685286,
        candidate_brier=0.463569,
        baseline_logloss=1.130310,
        candidate_logloss=0.816407,
        baseline_accuracy=25.00,
        candidate_accuracy=75.00,
        candidate_status="EVALUATED",
        decision="INSUFFICIENT_SAMPLE",
        reason=(
            "Leave-one-out escolheu os mesmos parâmetros nos 4 folds, "
            "mas quatro jogos são insuficientes para ativar nova versão."
        ),
    )

    con.execute(
        """
        INSERT INTO schema_migrations (
            migration_id,
            description
        )
        VALUES (?, ?)
        """,
        (MIGRATION_ID, DESCRIPTION),
    )

    con.commit()

    print("=== VALIDACAO ===")
    for model in (
        "ESP1_MODEL_0_1",
        "POR1_MODEL_0_1",
        "ESP1_MODEL_0_2",
    ):
        row = con.execute(
            """
            SELECT
                model_version,
                league_id,
                parent_model_version,
                version_status
            FROM model_versions
            WHERE model_version = ?
            """,
            (model,),
        ).fetchone()

        params = con.execute(
            "SELECT COUNT(*) FROM model_parameters WHERE model_version = ?",
            (model,),
        ).fetchone()[0]

        ratings = con.execute(
            "SELECT COUNT(*) FROM team_ratings WHERE model_version = ?",
            (model,),
        ).fetchone()[0]

        print(dict(row), "| params =", params, "| ratings =", ratings)

    print("INTEGRITY =", con.execute("PRAGMA integrity_check").fetchone()[0])
    print("FOREIGN_KEYS =", con.execute("PRAGMA foreign_key_check").fetchall())
