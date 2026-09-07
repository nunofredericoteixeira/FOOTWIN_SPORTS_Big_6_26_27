CREATE TABLE IF NOT EXISTS public.runtime_model_versions (
    model_version text PRIMARY KEY,
    league_id text,
    season_label text NOT NULL,
    parent_model_version text,
    version_status text NOT NULL,
    parameter_hash text NOT NULL,
    parameters_json text NOT NULL,
    created_at timestamptz NOT NULL,
    activated_at timestamptz,
    retired_at timestamptz,
    notes text
);

CREATE INDEX IF NOT EXISTS idx_runtime_model_versions_status
ON public.runtime_model_versions (
    season_label,
    league_id,
    version_status
);

CREATE TABLE IF NOT EXISTS public.runtime_model_parameters (
    model_version text NOT NULL,
    parameter_name text NOT NULL,
    parameter_value double precision NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (
        model_version,
        parameter_name
    )
);

CREATE INDEX IF NOT EXISTS idx_runtime_model_parameters_version
ON public.runtime_model_parameters (
    model_version
);

CREATE TABLE IF NOT EXISTS public.runtime_team_ratings (
    team_id text NOT NULL,
    league_id text NOT NULL,
    season_label text NOT NULL,
    model_version text NOT NULL,
    run_id text,
    points_per_game double precision NOT NULL,
    goals_for_per_game double precision NOT NULL,
    goals_against_per_game double precision NOT NULL,
    goal_difference_per_game double precision NOT NULL,
    ppg_rating double precision NOT NULL,
    attack_rating double precision NOT NULL,
    defence_rating double precision NOT NULL,
    goal_difference_rating double precision NOT NULL,
    performance_rating double precision NOT NULL,
    absolute_rating double precision NOT NULL,
    league_relative_rating double precision NOT NULL,
    rating_confidence double precision NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (
        team_id,
        season_label,
        model_version
    )
);

CREATE INDEX IF NOT EXISTS idx_runtime_team_ratings_model
ON public.runtime_team_ratings (
    model_version
);

CREATE TABLE IF NOT EXISTS public.runtime_model_candidates (
    candidate_model_version text PRIMARY KEY,
    parent_model_version text NOT NULL,
    league_id text,
    evaluation_scope text NOT NULL,
    sample_size integer NOT NULL,
    baseline_brier_score double precision,
    candidate_brier_score double precision,
    baseline_log_loss double precision,
    candidate_log_loss double precision,
    baseline_outcome_accuracy double precision,
    candidate_outcome_accuracy double precision,
    candidate_status text NOT NULL,
    created_at timestamptz NOT NULL,
    evaluated_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.runtime_model_promotion_decisions (
    candidate_model_version text PRIMARY KEY,
    decision text NOT NULL,
    sample_size integer NOT NULL,
    brier_improvement double precision,
    log_loss_improvement double precision,
    outcome_accuracy_improvement double precision,
    decision_reason text NOT NULL,
    decided_at timestamptz NOT NULL
);

ALTER TABLE public.runtime_model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.runtime_model_parameters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.runtime_team_ratings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.runtime_model_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.runtime_model_promotion_decisions ENABLE ROW LEVEL SECURITY;
