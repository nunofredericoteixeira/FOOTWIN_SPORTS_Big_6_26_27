-- FOOTWIN SPORTS
-- Estado persistente dos jogos.
--
-- A SQLite continua a conter o calendário/base original.
-- Esta tabela guarda apenas o estado mutável em runtime,
-- sobrevivendo a deploys/restarts do Render.
--
-- Leitura e escrita serão efetuadas exclusivamente pelos
-- processos internos usando SUPABASE_SERVICE_ROLE_KEY.

CREATE TABLE IF NOT EXISTS public.match_runtime_state (
    match_id text PRIMARY KEY,

    league_id text NOT NULL,

    match_date timestamptz NOT NULL,

    status text NOT NULL
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

    home_goals integer
        CHECK (
            home_goals IS NULL
            OR home_goals >= 0
        ),

    away_goals integer
        CHECK (
            away_goals IS NULL
            OR away_goals >= 0
        ),

    source_url text NOT NULL,

    created_at timestamptz NOT NULL
        DEFAULT now(),

    updated_at timestamptz NOT NULL
        DEFAULT now(),

    CHECK (
        (
            status = 'PLAYED'
            AND home_goals IS NOT NULL
            AND away_goals IS NOT NULL
        )
        OR status <> 'PLAYED'
    )
);

ALTER TABLE public.match_runtime_state
ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS
    match_runtime_state_league_date_idx
ON public.match_runtime_state (
    league_id,
    match_date
);

CREATE INDEX IF NOT EXISTS
    match_runtime_state_status_idx
ON public.match_runtime_state (
    status
);
