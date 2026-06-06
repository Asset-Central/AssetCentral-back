-- =============================================================================
-- 004: Fix security advisors y performance (RLS, search_path, permisos, índices)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. ERROR: llm_user_account_balances_view — Security Definer View
--    Las vistas heredan permisos del creador; usar security_invoker para que
--    respeten los permisos y RLS del usuario que consulta.
-- ---------------------------------------------------------------------------
ALTER VIEW public.llm_user_account_balances_view SET (security_invoker = on);

-- ---------------------------------------------------------------------------
-- 2. WARN: get_latest_balances y get_portfolio_balances — search_path mutable
--    Agregar SET search_path = public para evitar ataques de path injection.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.get_latest_balances(p_user_id UUID)
RETURNS TABLE (
    account_id UUID, asset_ticker VARCHAR, quantity NUMERIC, unit_price NUMERIC,
    total_valuation NUMERIC, recorded_at TIMESTAMPTZ,
    external_name VARCHAR, asset_type asset_class_type, currency currency_type, platform platform_type
) LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT DISTINCT ON (hb.account_id, a.ticker)
        hb.account_id, a.ticker AS asset_ticker, hb.quantity, hb.unit_price,
        hb.total_valuation, hb.recorded_at,
        a.external_name, a.asset_type, a.currency, a.platform
    FROM public.historical_balances hb
    JOIN public.assets a ON a.id = hb.asset_id
    JOIN public.account acc ON acc.id = hb.account_id
    WHERE acc.user_id = p_user_id
    ORDER BY hb.account_id, a.ticker, hb.recorded_at DESC;
$$;
REVOKE EXECUTE ON FUNCTION public.get_latest_balances(UUID) FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.get_portfolio_balances(p_portfolio_id UUID, p_user_id UUID)
RETURNS TABLE (
    asset_ticker VARCHAR, external_name VARCHAR, asset_type asset_class_type,
    currency currency_type, platform platform_type,
    total_quantity NUMERIC, unit_price NUMERIC, total_valuation NUMERIC,
    target_share NUMERIC
) LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        a.ticker AS asset_ticker, a.external_name, a.asset_type, a.currency, a.platform,
        COALESCE(SUM(latest.quantity), 0),
        AVG(latest.unit_price),
        COALESCE(SUM(latest.total_valuation), 0),
        pa.target_share
    FROM public.portfolio_assets pa
    JOIN public.assets a ON a.id = pa.asset_id
    LEFT JOIN LATERAL (
        SELECT hb.quantity, hb.unit_price, hb.total_valuation
        FROM public.historical_balances hb
        JOIN public.account acc ON acc.id = hb.account_id
        WHERE acc.user_id = p_user_id AND hb.asset_id = a.id
        ORDER BY hb.recorded_at DESC LIMIT 1
    ) latest ON TRUE
    WHERE pa.portfolio_id = p_portfolio_id
      AND EXISTS (SELECT 1 FROM public.portfolios p WHERE p.id = p_portfolio_id AND p.user_id = p_user_id)
    GROUP BY a.ticker, a.external_name, a.asset_type, a.currency, a.platform, pa.target_share;
$$;
REVOKE EXECUTE ON FUNCTION public.get_portfolio_balances(UUID, UUID) FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. WARN: get_schema_metadata y handle_new_user
--    - search_path mutable en get_schema_metadata
--    - anon/authenticated pueden invocarlas vía RPC (son internas/triggers)
--    REVOKE desde PUBLIC ya que el grant heredable viene de ahí.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.get_schema_metadata()
RETURNS TABLE(table_name text, column_name text, data_type text, description text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  SELECT
    c.table_name::text,
    c.column_name::text,
    c.data_type::text,
    pgd.description::text
  FROM information_schema.columns c
  JOIN pg_class pgc ON c.table_name = pgc.relname
  JOIN pg_namespace nsp ON nsp.oid = pgc.relnamespace
  LEFT JOIN pg_description pgd ON pgd.objoid = pgc.oid AND pgd.objsubid = c.ordinal_position
  WHERE c.table_schema = 'public' AND nsp.nspname = 'public';
END;
$$;
REVOKE EXECUTE ON FUNCTION public.get_schema_metadata() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- 4. INFO (PERFORMANCE): portfolio_assets.asset_id — FK sin índice cubriente
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_portfolio_assets_asset_id ON public.portfolio_assets(asset_id);

-- ---------------------------------------------------------------------------
-- 5. WARN (PERFORMANCE): Auth RLS Initialization Plan
--    Reemplazar auth.uid()/auth.role() con (select auth.uid())/(select auth.role())
--    para que PostgreSQL evalúe la función una sola vez por query.
-- ---------------------------------------------------------------------------

-- users
DROP POLICY IF EXISTS "users: solo el dueño" ON public.users;
CREATE POLICY "users: solo el dueño" ON public.users
    FOR ALL USING ((select auth.uid()) = id);

-- account
DROP POLICY IF EXISTS "account: solo el dueño" ON public.account;
CREATE POLICY "account: solo el dueño" ON public.account
    FOR ALL USING ((select auth.uid()) = user_id);

-- assets
DROP POLICY IF EXISTS "assets: lectura autenticados" ON public.assets;
CREATE POLICY "assets: lectura autenticados" ON public.assets
    FOR SELECT USING ((select auth.role()) = 'authenticated');

-- portfolios
DROP POLICY IF EXISTS "portfolios: solo el dueño" ON public.portfolios;
CREATE POLICY "portfolios: solo el dueño" ON public.portfolios
    FOR ALL USING ((select auth.uid()) = user_id);

-- portfolio_assets
DROP POLICY IF EXISTS "portfolio_assets: solo el dueño" ON public.portfolio_assets;
CREATE POLICY "portfolio_assets: solo el dueño" ON public.portfolio_assets
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.portfolios p
            WHERE p.id = portfolio_id AND p.user_id = (select auth.uid())
        )
    );

-- historical_balances
DROP POLICY IF EXISTS "historical_balances: solo el dueño" ON public.historical_balances;
CREATE POLICY "historical_balances: solo el dueño" ON public.historical_balances
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.account a
            WHERE a.id = account_id AND a.user_id = (select auth.uid())
        )
    );
