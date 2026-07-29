# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset_version TEXT PRIMARY KEY,
    season_label TEXT NOT NULL,
    file_path TEXT,
    checksum_sha256 TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    validated_at TEXT
);

CREATE TABLE IF NOT EXISTS leagues (
    league_id TEXT PRIMARY KEY,
    league_name TEXT NOT NULL,
    country TEXT NOT NULL,
    country_code TEXT NOT NULL,
    season_label TEXT NOT NULL,
    team_count INTEGER NOT NULL,
    matches_per_team INTEGER NOT NULL,
    total_matches INTEGER NOT NULL,
    league_strength_factor REAL NOT NULL,
    relegation_places INTEGER NOT NULL DEFAULT 0,
    playoff_places INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (team_count > 1),
    CHECK (matches_per_team > 0),
    CHECK (total_matches > 0),
    CHECK (league_strength_factor > 0),
    CHECK (relegation_places >= 0),
    CHECK (playoff_places >= 0),
    CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY,
    team_name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    league_id TEXT NOT NULL,
    country TEXT NOT NULL,
    season_label TEXT NOT NULL,
    promoted INTEGER NOT NULL DEFAULT 0,
    promotion_method TEXT,
    previous_division TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    dataset_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (league_id)
        REFERENCES leagues (league_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (dataset_version)
        REFERENCES dataset_versions (dataset_version)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    CHECK (promoted IN (0, 1)),
    CHECK (active IN (0, 1)),
    CHECK (
        promotion_method IS NULL
        OR promotion_method IN ('CHAMPION', 'DIRECT', 'PLAYOFF')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_league_normalized_name
ON teams (league_id, normalized_name);

CREATE INDEX IF NOT EXISTS idx_teams_league_id
ON teams (league_id);

CREATE TABLE IF NOT EXISTS team_season_performance (
    performance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL,
    source_league_id TEXT NOT NULL,
    target_league_id TEXT NOT NULL,
    season_label TEXT NOT NULL,
    position INTEGER NOT NULL,
    played INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    draws INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    goals_for INTEGER NOT NULL,
    goals_against INTEGER NOT NULL,
    goal_difference INTEGER NOT NULL,
    points INTEGER NOT NULL,
    points_adjustment INTEGER NOT NULL DEFAULT 0,
    promoted INTEGER NOT NULL DEFAULT 0,
    promotion_method TEXT,
    source_status TEXT NOT NULL,
    data_confidence REAL NOT NULL,
    source_url TEXT,
    accessed_at TEXT,
    dataset_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (team_id)
        REFERENCES teams (team_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (target_league_id)
        REFERENCES leagues (league_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (dataset_version)
        REFERENCES dataset_versions (dataset_version)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    UNIQUE (team_id, season_label, source_league_id),

    CHECK (position > 0),
    CHECK (played >= 0),
    CHECK (wins >= 0),
    CHECK (draws >= 0),
    CHECK (losses >= 0),
    CHECK (goals_for >= 0),
    CHECK (goals_against >= 0),
    CHECK (promoted IN (0, 1)),
    CHECK (data_confidence >= 0 AND data_confidence <= 1),
    CHECK (
        promotion_method IS NULL
        OR promotion_method IN ('CHAMPION', 'DIRECT', 'PLAYOFF')
    )
);

CREATE INDEX IF NOT EXISTS idx_performance_team_id
ON team_season_performance (team_id);

CREATE INDEX IF NOT EXISTS idx_performance_target_league
ON team_season_performance (target_league_id);

CREATE TABLE IF NOT EXISTS team_ratings (
    rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    season_label TEXT NOT NULL,
    model_version TEXT NOT NULL,
    run_id TEXT,
    points_per_game REAL NOT NULL,
    goals_for_per_game REAL NOT NULL,
    goals_against_per_game REAL NOT NULL,
    goal_difference_per_game REAL NOT NULL,
    ppg_rating REAL NOT NULL,
    attack_rating REAL NOT NULL,
    defence_rating REAL NOT NULL,
    goal_difference_rating REAL NOT NULL,
    performance_rating REAL NOT NULL,
    absolute_rating REAL NOT NULL,
    league_relative_rating REAL NOT NULL,
    rating_confidence REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (team_id)
        REFERENCES teams (team_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (league_id)
        REFERENCES leagues (league_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    UNIQUE (team_id, season_label, model_version, run_id),

    CHECK (rating_confidence >= 0 AND rating_confidence <= 1)
);

CREATE INDEX IF NOT EXISTS idx_team_ratings_team
ON team_ratings (team_id);

CREATE INDEX IF NOT EXISTS idx_team_ratings_league
ON team_ratings (league_id);

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    league_id TEXT NOT NULL,
    season_label TEXT NOT NULL,
    round_number INTEGER,
    match_date TEXT,
    home_team_id TEXT NOT NULL,
    away_team_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED',
    home_goals INTEGER,
    away_goals INTEGER,
    schedule_type TEXT NOT NULL DEFAULT 'OFFICIAL',
    source_url TEXT,
    dataset_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (league_id)
        REFERENCES leagues (league_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (home_team_id)
        REFERENCES teams (team_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (away_team_id)
        REFERENCES teams (team_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (dataset_version)
        REFERENCES dataset_versions (dataset_version)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    CHECK (home_team_id <> away_team_id),
    CHECK (
        status IN (
            'SCHEDULED',
            'PLAYED',
            'POSTPONED',
            'CANCELLED',
            'ABANDONED',
            'AWARDED'
        )
    ),
    CHECK (schedule_type IN ('OFFICIAL', 'SYNTHETIC'))
);

CREATE INDEX IF NOT EXISTS idx_matches_league
ON matches (league_id);

CREATE INDEX IF NOT EXISTS idx_matches_date
ON matches (match_date);

CREATE INDEX IF NOT EXISTS idx_matches_home_team
ON matches (home_team_id);

CREATE INDEX IF NOT EXISTS idx_matches_away_team
ON matches (away_team_id);

CREATE TABLE IF NOT EXISTS match_predictions (
    prediction_id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    run_id TEXT,
    prediction_timestamp TEXT NOT NULL,
    data_cutoff TEXT,
    lambda_home REAL NOT NULL,
    lambda_away REAL NOT NULL,
    home_win_probability REAL NOT NULL,
    draw_probability REAL NOT NULL,
    away_win_probability REAL NOT NULL,
    most_likely_score TEXT,
    second_likely_score TEXT,
    third_likely_score TEXT,
    over_2_5_probability REAL,
    btts_probability REAL,
    data_confidence REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (match_id)
        REFERENCES matches (match_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    CHECK (lambda_home > 0),
    CHECK (lambda_away > 0),
    CHECK (home_win_probability >= 0 AND home_win_probability <= 1),
    CHECK (draw_probability >= 0 AND draw_probability <= 1),
    CHECK (away_win_probability >= 0 AND away_win_probability <= 1),
    CHECK (data_confidence >= 0 AND data_confidence <= 1)
);

CREATE INDEX IF NOT EXISTS idx_predictions_match
ON match_predictions (match_id);

CREATE TABLE IF NOT EXISTS league_simulations (
    simulation_id TEXT PRIMARY KEY,
    league_id TEXT NOT NULL,
    season_label TEXT NOT NULL,
    model_version TEXT NOT NULL,
    run_id TEXT,
    simulation_count INTEGER NOT NULL,
    random_seed INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,

    FOREIGN KEY (league_id)
        REFERENCES leagues (league_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CHECK (simulation_count > 0),
    CHECK (
        status IN (
            'PENDING',
            'RUNNING',
            'SUCCESS',
            'PARTIAL',
            'FAILED'
        )
    )
);

CREATE TABLE IF NOT EXISTS league_simulation_results (
    simulation_result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    average_position REAL NOT NULL,
    median_position REAL NOT NULL,
    average_points REAL NOT NULL,
    average_goals_for REAL NOT NULL,
    average_goals_against REAL NOT NULL,
    average_goal_difference REAL NOT NULL,
    title_probability REAL NOT NULL,
    europe_probability REAL NOT NULL,
    relegation_probability REAL NOT NULL,
    playoff_probability REAL NOT NULL,
    points_p10 REAL NOT NULL,
    points_p25 REAL NOT NULL,
    points_p50 REAL NOT NULL,
    points_p75 REAL NOT NULL,
    points_p90 REAL NOT NULL,

    FOREIGN KEY (simulation_id)
        REFERENCES league_simulations (simulation_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (team_id)
        REFERENCES teams (team_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE (simulation_id, team_id)
);

CREATE TABLE IF NOT EXISTS position_probabilities (
    position_probability_id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    probability REAL NOT NULL,

    FOREIGN KEY (simulation_id)
        REFERENCES league_simulations (simulation_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    FOREIGN KEY (team_id)
        REFERENCES teams (team_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE (simulation_id, team_id, position),

    CHECK (position > 0),
    CHECK (probability >= 0 AND probability <= 1)
);

CREATE TABLE IF NOT EXISTS execution_runs (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    model_version TEXT,
    dataset_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    hostname TEXT,
    process_id INTEGER,
    error_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (
        status IN (
            'PENDING',
            'RUNNING',
            'SUCCESS',
            'PARTIAL',
            'FAILED',
            'SKIPPED',
            'CANCELLED'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_execution_runs_started_at
ON execution_runs (started_at);

CREATE TABLE IF NOT EXISTS validation_issues (
    issue_id TEXT PRIMARY KEY,
    run_id TEXT,
    dataset_version TEXT,
    severity TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    field_name TEXT,
    expected_value TEXT,
    actual_value TEXT,
    message TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution_note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,

    FOREIGN KEY (run_id)
        REFERENCES execution_runs (run_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    CHECK (severity IN ('ERROR', 'WARNING', 'INFO')),
    CHECK (resolved IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_validation_issues_run
ON validation_issues (run_id);

CREATE INDEX IF NOT EXISTS idx_validation_issues_severity
ON validation_issues (severity);
"""


def create_schema(connection: sqlite3.Connection) -> None:
    """
    Cria todas as tabelas e índices do esquema inicial.

    A função é idempotente: pode ser executada várias vezes.
    """

    connection.executescript(SCHEMA_SQL)


def get_expected_tables() -> set[str]:
    """Devolve os nomes das tabelas principais esperadas."""

    return {
        "schema_migrations",
        "dataset_versions",
        "leagues",
        "teams",
        "team_season_performance",
        "team_ratings",
        "matches",
        "match_predictions",
        "league_simulations",
        "league_simulation_results",
        "position_probabilities",
        "execution_runs",
        "validation_issues",
    }


def database_file_exists(database_path: str | Path) -> bool:
    """Confirma se o ficheiro SQLite já existe."""

    return Path(database_path).expanduser().resolve().exists()
