-- =============================================================================
-- AssetCentral — Schema completo
-- Refleja el estado real de la base de datos en Supabase.
-- Ejecutar en orden en un proyecto nuevo (el proyecto de producción ya lo tiene aplicado).
-- =============================================================================

-- Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "supabase_vault";

-- =============================================================================
-- Enums
-- =============================================================================
CREATE TYPE platform_type         AS ENUM ('cocos', 'iol', 'mercadopago', 'nacion');
CREATE TYPE connection_status_type AS ENUM ('active', 'requires_reauthentication', 'error');
CREATE TYPE asset_class_type      AS ENUM ('cedear', 'bono', 'fci', 'cash', 'crypto', 'stock');
CREATE TYPE currency_type         AS ENUM ('ARS', 'USD');

-- =============================================================================
-- 1. users — perfil extendido de auth.users
-- =============================================================================
CREATE TABLE public.users (
    id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name  VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users: solo el dueño" ON public.users FOR ALL USING (auth.uid() = id);

-- =============================================================================
-- 2. account — cuentas de brokers vinculadas
--    Credenciales almacenadas en Supabase Vault (vault.secrets) via secret_id.
-- =============================================================================
CREATE TABLE public.account (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    platform          platform_type NOT NULL,
    connection_status connection_status_type NOT NULL DEFAULT 'active',
    secret_id         UUID REFERENCES vault.secrets(id) ON DELETE SET NULL,
    label             VARCHAR(255),
    error_message     TEXT,
    last_sync         TIMESTAMPTZ DEFAULT now(),
    created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_account_user_id ON public.account(user_id);

ALTER TABLE public.account ENABLE ROW LEVEL SECURITY;
CREATE POLICY "account: solo el dueño" ON public.account FOR ALL USING (auth.uid() = user_id);

-- =============================================================================
-- 3. assets — catálogo global de activos negociables
--    Hybrid Search: vector (embedding) + BM25 (search_vector)
-- =============================================================================
CREATE TABLE public.assets (
    ticker        VARCHAR PRIMARY KEY,
    platform      platform_type,
    external_name VARCHAR,
    asset_type    asset_class_type,
    currency      currency_type,
    embedding     vector,
    search_vector tsvector,
    created_at    TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.assets ENABLE ROW LEVEL SECURITY;
CREATE POLICY "assets: lectura autenticados" ON public.assets FOR SELECT
    USING (auth.role() = 'authenticated');

-- =============================================================================
-- 4. portfolios — agrupaciones personalizadas del usuario
-- =============================================================================
CREATE TABLE public.portfolios (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    name        VARCHAR NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_portfolios_user_id ON public.portfolios(user_id);

ALTER TABLE public.portfolios ENABLE ROW LEVEL SECURITY;
CREATE POLICY "portfolios: solo el dueño" ON public.portfolios FOR ALL USING (auth.uid() = user_id);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
   SECURITY DEFINER
   SET search_path = public;

CREATE TRIGGER portfolios_updated_at
    BEFORE UPDATE ON public.portfolios
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- =============================================================================
-- 5. portfolio_assets — relación portfolio ↔ ticker del catálogo
-- =============================================================================
CREATE TABLE public.portfolio_assets (
    portfolio_id UUID    NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    asset_ticker VARCHAR NOT NULL REFERENCES public.assets(ticker) ON DELETE CASCADE,
    target_share NUMERIC(5,2),
    assigned_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (portfolio_id, asset_ticker),
    CONSTRAINT target_share_range CHECK (target_share IS NULL OR (target_share > 0 AND target_share <= 100))
);

ALTER TABLE public.portfolio_assets ENABLE ROW LEVEL SECURITY;
CREATE POLICY "portfolio_assets: solo el dueño" ON public.portfolio_assets FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.portfolios p
            WHERE p.id = portfolio_id AND p.user_id = auth.uid()
        )
    );

-- Trigger deferrable: valida suma = 100 al final de la transacción
CREATE OR REPLACE FUNCTION public.check_portfolio_shares()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE
    v_pid UUID := COALESCE(NEW.portfolio_id, OLD.portfolio_id);
    v_total NUMERIC; v_null_cnt INTEGER; v_asset_cnt INTEGER;
BEGIN
    SELECT COUNT(*), COUNT(*) FILTER (WHERE target_share IS NULL), COALESCE(SUM(target_share), 0)
    INTO v_asset_cnt, v_null_cnt, v_total FROM portfolio_assets WHERE portfolio_id = v_pid;
    IF v_null_cnt = v_asset_cnt THEN RETURN NEW; END IF;
    IF v_null_cnt > 0 THEN
        RAISE EXCEPTION 'target_share debe definirse en todos los activos o en ninguno del portfolio';
    END IF;
    IF ABS(v_total - 100) > 0.01 THEN
        RAISE EXCEPTION 'La suma de target_share debe ser 100 (suma actual: %)', ROUND(v_total, 2);
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER validate_portfolio_shares
    AFTER INSERT OR UPDATE OR DELETE ON public.portfolio_assets
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.check_portfolio_shares();

-- =============================================================================
-- 6. historical_balances — serie temporal de posiciones por cuenta
-- =============================================================================
CREATE TABLE public.historical_balances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID    NOT NULL REFERENCES public.account(id) ON DELETE CASCADE,
    asset_ticker    VARCHAR NOT NULL REFERENCES public.assets(ticker),
    quantity        NUMERIC NOT NULL,
    unit_price      NUMERIC,
    total_valuation NUMERIC,
    recorded_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_historical_balances_account    ON public.historical_balances(account_id);
CREATE INDEX idx_historical_balances_ticker     ON public.historical_balances(asset_ticker);
CREATE INDEX idx_historical_balances_recorded   ON public.historical_balances(recorded_at DESC);

ALTER TABLE public.historical_balances ENABLE ROW LEVEL SECURITY;
CREATE POLICY "historical_balances: solo el dueño" ON public.historical_balances FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.account a
            WHERE a.id = account_id AND a.user_id = auth.uid()
        )
    );

-- =============================================================================
-- 7. Vault helper functions (requieren la extensión supabase_vault)
-- =============================================================================
CREATE OR REPLACE FUNCTION public.upsert_vault_secret(p_secret TEXT, p_name TEXT DEFAULT NULL)
RETURNS UUID LANGUAGE SQL SECURITY DEFINER SET search_path = vault, public
AS $$ SELECT vault.create_secret(p_secret, p_name); $$;
REVOKE EXECUTE ON FUNCTION public.upsert_vault_secret(TEXT, TEXT) FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.read_vault_secret(p_secret_id UUID)
RETURNS TEXT LANGUAGE SQL SECURITY DEFINER SET search_path = vault, public
AS $$ SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = p_secret_id; $$;
REVOKE EXECUTE ON FUNCTION public.read_vault_secret(UUID) FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.delete_vault_secret(p_secret_id UUID)
RETURNS VOID LANGUAGE SQL SECURITY DEFINER SET search_path = vault, public
AS $$ DELETE FROM vault.secrets WHERE id = p_secret_id; $$;
REVOKE EXECUTE ON FUNCTION public.delete_vault_secret(UUID) FROM anon, authenticated;

-- =============================================================================
-- 8. RPC functions para el backend
-- =============================================================================

-- Balance más reciente por cuenta+ticker para un usuario
CREATE OR REPLACE FUNCTION public.get_latest_balances(p_user_id UUID)
RETURNS TABLE (
    account_id UUID, asset_ticker VARCHAR, quantity NUMERIC, unit_price NUMERIC,
    total_valuation NUMERIC, recorded_at TIMESTAMPTZ,
    external_name VARCHAR, asset_type asset_class_type, currency currency_type, platform platform_type
) LANGUAGE SQL STABLE SECURITY DEFINER AS $$
    SELECT DISTINCT ON (hb.account_id, hb.asset_ticker)
        hb.account_id, hb.asset_ticker, hb.quantity, hb.unit_price,
        hb.total_valuation, hb.recorded_at,
        a.external_name, a.asset_type, a.currency, a.platform
    FROM public.historical_balances hb
    JOIN public.assets a ON a.ticker = hb.asset_ticker
    JOIN public.account acc ON acc.id = hb.account_id
    WHERE acc.user_id = p_user_id
    ORDER BY hb.account_id, hb.asset_ticker, hb.recorded_at DESC;
$$;
REVOKE EXECUTE ON FUNCTION public.get_latest_balances(UUID) FROM anon, authenticated;

-- Balances agregados para los tickers de un portfolio
CREATE OR REPLACE FUNCTION public.get_portfolio_balances(p_portfolio_id UUID, p_user_id UUID)
RETURNS TABLE (
    asset_ticker VARCHAR, external_name VARCHAR, asset_type asset_class_type,
    currency currency_type, platform platform_type,
    total_quantity NUMERIC, unit_price NUMERIC, total_valuation NUMERIC,
    target_share NUMERIC
) LANGUAGE SQL STABLE SECURITY DEFINER AS $$
    SELECT
        a.ticker, a.external_name, a.asset_type, a.currency, a.platform,
        COALESCE(SUM(latest.quantity), 0),
        AVG(latest.unit_price),
        COALESCE(SUM(latest.total_valuation), 0),
        pa.target_share
    FROM public.portfolio_assets pa
    JOIN public.assets a ON a.ticker = pa.asset_ticker
    LEFT JOIN LATERAL (
        SELECT hb.quantity, hb.unit_price, hb.total_valuation
        FROM public.historical_balances hb
        JOIN public.account acc ON acc.id = hb.account_id
        WHERE acc.user_id = p_user_id AND hb.asset_ticker = a.ticker
        ORDER BY hb.recorded_at DESC LIMIT 1
    ) latest ON TRUE
    WHERE pa.portfolio_id = p_portfolio_id
      AND EXISTS (SELECT 1 FROM public.portfolios p WHERE p.id = p_portfolio_id AND p.user_id = p_user_id)
    GROUP BY a.ticker, a.external_name, a.asset_type, a.currency, a.platform, pa.target_share;
$$;
REVOKE EXECUTE ON FUNCTION public.get_portfolio_balances(UUID, UUID) FROM anon, authenticated;
