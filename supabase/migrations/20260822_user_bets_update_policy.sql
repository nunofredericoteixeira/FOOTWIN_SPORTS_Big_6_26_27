-- FOOTWIN SPORTS
-- Permite a cada utilizador autenticado atualizar
-- apenas as suas próprias apostas em public.user_bets.
--
-- Necessário para liquidar apostas PENDING -> WON/LOST
-- e gravar profit_loss, resultado e saldo final.

ALTER TABLE public.user_bets
ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS
    "Users can update own bets"
ON public.user_bets;

CREATE POLICY
    "Users can update own bets"
ON public.user_bets
FOR UPDATE
TO authenticated
USING (
    auth.uid() = user_id
)
WITH CHECK (
    auth.uid() = user_id
);
