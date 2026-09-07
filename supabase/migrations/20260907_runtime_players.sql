-- FOOTWIN SPORTS
-- Persistência dos jogadores criados dinamicamente em runtime.
--
-- Os jogadores já existentes na base seed permanecem na SQLite.
-- Esta tabela guarda apenas os jogadores adicionais descobertos
-- pelos collectors durante a época, para permitir reconstrução
-- completa após deploys/restarts do Render.
--
-- Leitura e escrita serão efetuadas exclusivamente pelos
-- processos internos usando SUPABASE_SERVICE_ROLE_KEY.

CREATE TABLE IF NOT EXISTS public.runtime_players (
    player_id text PRIMARY KEY,

    full_name text NOT NULL,
    normalized_name text NOT NULL,

    date_of_birth date,
    nationality text,

    primary_position text,

    active boolean NOT NULL
        DEFAULT true,

    created_at timestamptz NOT NULL
        DEFAULT now(),

    updated_at timestamptz NOT NULL
        DEFAULT now()
);

ALTER TABLE public.runtime_players
ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS
    runtime_players_normalized_name_idx
ON public.runtime_players (
    normalized_name
);
