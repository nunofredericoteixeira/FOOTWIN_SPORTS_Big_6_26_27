-- FOOTWIN SPORTS
-- Cache global das odds Bwin recolhidas via TipsterArea.
--
-- A escrita será efetuada por processo interno usando
-- SUPABASE_SERVICE_ROLE_KEY.
-- Os utilizadores autenticados apenas precisam de leitura.

CREATE TABLE IF NOT EXISTS public.match_bwin_odds (
    match_id text PRIMARY KEY,
    league_id text NOT NULL,
    event_date date NOT NULL,

    source text NOT NULL
        DEFAULT 'TIPSTERAREA',

    bookmaker text NOT NULL
        DEFAULT 'BWIN',

    tipsterarea_id bigint,
    canonical_url text,

    odd_1 numeric,
    odd_x numeric,
    odd_2 numeric,

    odd_1x numeric,
    odd_12 numeric,
    odd_x2 numeric,

    fetched_at timestamptz NOT NULL
        DEFAULT now(),

    created_at timestamptz NOT NULL
        DEFAULT now(),

    updated_at timestamptz NOT NULL
        DEFAULT now()
);

ALTER TABLE public.match_bwin_odds
ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS
    "Authenticated users can read Bwin odds"
ON public.match_bwin_odds;

CREATE POLICY
    "Authenticated users can read Bwin odds"
ON public.match_bwin_odds
FOR SELECT
TO authenticated
USING (true);

CREATE INDEX IF NOT EXISTS
    match_bwin_odds_league_date_idx
ON public.match_bwin_odds (
    league_id,
    event_date
);
