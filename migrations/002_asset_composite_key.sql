-- =============================================================================
-- 002: assets — PK UUID + UNIQUE(ticker, platform)
--
-- Problema: ticker como PK impedía almacenar el mismo ticker de plataformas
-- distintas. Ahora cada asset se identifica por un UUID y la unicidad real
-- se garantiza con UNIQUE(ticker, platform).
--
-- Tablas afectadas: assets, portfolio_assets, historical_balances
-- Vistas recreadas: llm_user_account_balances_view
-- RPCs recreadas: get_latest_balances, get_portfolio_balances
-- =============================================================================

-- Paso 1: eliminar vista que depende de historical_balances.asset_ticker
DROP VIEW IF EXISTS public.llm_user_account_balances_view;

-- Paso 2: eliminar FKs y PKs dependientes del PK de assets
ALTER TABLE public.portfolio_assets
    DROP CONSTRAINT portfolio_assets_asset_ticker_fkey,
    DROP CONSTRAINT portfolio_assets_pkey;

ALTER TABLE public.historical_balances
    DROP CONSTRAINT historical_balances_asset_ticker_fkey;

DROP INDEX IF EXISTS public.idx_historical_balances_ticker;

-- Paso 3: modificar assets
ALTER TABLE public.assets
    ADD COLUMN id UUID DEFAULT gen_random_uuid();

UPDATE public.assets SET id = gen_random_uuid() WHERE id IS NULL;

ALTER TABLE public.assets
    ALTER COLUMN id SET NOT NULL,
    ALTER COLUMN platform SET NOT NULL;

ALTER TABLE public.assets DROP CONSTRAINT assets_pkey;
ALTER TABLE public.assets ADD PRIMARY KEY (id);
ALTER TABLE public.assets ADD CONSTRAINT assets_ticker_platform_unique UNIQUE (ticker, platform);

-- Paso 4: portfolio_assets — reemplazar asset_ticker con asset_id
ALTER TABLE public.portfolio_assets
    ADD COLUMN asset_id UUID NOT NULL REFERENCES public.assets(id) ON DELETE CASCADE,
    DROP COLUMN asset_ticker;

ALTER TABLE public.portfolio_assets
    ADD PRIMARY KEY (portfolio_id, asset_id);

-- Paso 5: historical_balances — reemplazar asset_ticker con asset_id
ALTER TABLE public.historical_balances
    ADD COLUMN asset_id UUID NOT NULL REFERENCES public.assets(id),
    DROP COLUMN asset_ticker;

CREATE INDEX idx_historical_balances_asset_id ON public.historical_balances(asset_id);

-- Paso 6: recrear vista adaptada al nuevo schema
CREATE VIEW public.llm_user_account_balances_view AS
WITH latest_balances AS (
    SELECT DISTINCT ON (hb.account_id, hb.asset_id)
        hb.account_id,
        hb.asset_id,
        hb.quantity,
        hb.total_valuation,
        hb.recorded_at
    FROM public.historical_balances hb
    ORDER BY hb.account_id, hb.asset_id, hb.recorded_at DESC
)
SELECT
    a.user_id,
    lb.account_id,
    a.platform,
    ast.ticker,
    ast.external_name,
    lb.quantity,
    lb.total_valuation,
    ast.currency,
    lb.recorded_at
FROM latest_balances lb
JOIN public.account a ON lb.account_id = a.id
JOIN public.assets ast ON ast.id = lb.asset_id;

-- Paso 7: recrear get_latest_balances
CREATE OR REPLACE FUNCTION public.get_latest_balances(p_user_id UUID)
RETURNS TABLE (
    account_id UUID, asset_ticker VARCHAR, quantity NUMERIC, unit_price NUMERIC,
    total_valuation NUMERIC, recorded_at TIMESTAMPTZ,
    external_name VARCHAR, asset_type asset_class_type, currency currency_type, platform platform_type
) LANGUAGE SQL STABLE SECURITY DEFINER AS $$
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

-- Paso 8: recrear get_portfolio_balances
CREATE OR REPLACE FUNCTION public.get_portfolio_balances(p_portfolio_id UUID, p_user_id UUID)
RETURNS TABLE (
    asset_ticker VARCHAR, external_name VARCHAR, asset_type asset_class_type,
    currency currency_type, platform platform_type,
    total_quantity NUMERIC, unit_price NUMERIC, total_valuation NUMERIC,
    target_share NUMERIC
) LANGUAGE SQL STABLE SECURITY DEFINER AS $$
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
