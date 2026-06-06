-- =============================================================================
-- AssetCentral — Schema inicial
-- Ejecutar en Supabase SQL Editor (como superuser)
-- =============================================================================

-- Extensión para gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- 1. user_vaults
--    Almacena el DEK cifrado de cada usuario.
--    Sin este registro, el usuario no puede operar con cuentas vinculadas.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_vaults (
    user_id      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    dek_encrypted TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 2. linked_accounts
--    Cuentas de brokers vinculadas por el usuario.
--    credentials_enc = JSON cifrado con el DEK del usuario.
-- -----------------------------------------------------------------------------
CREATE TYPE IF NOT EXISTS platform_type AS ENUM ('COCOS', 'IOL', 'MERCADO_PAGO', 'PROMETEO');
CREATE TYPE IF NOT EXISTS account_status AS ENUM ('CONNECTED', 'ERROR', 'PENDING', 'DISCONNECTED');

CREATE TABLE IF NOT EXISTS public.linked_accounts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    platform         platform_type NOT NULL,
    label            TEXT NOT NULL,
    status           account_status NOT NULL DEFAULT 'PENDING',
    credentials_enc  TEXT NOT NULL,
    last_sync_at     TIMESTAMPTZ,
    error_message    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_linked_accounts_user_id ON public.linked_accounts(user_id);

-- -----------------------------------------------------------------------------
-- 3. asset_snapshots
--    Cache de activos obtenidos de los brokers. Se reemplaza en cada sync.
-- -----------------------------------------------------------------------------
CREATE TYPE IF NOT EXISTS asset_type AS ENUM ('CEDEAR', 'BONO', 'FCI', 'USD', 'ACCION', 'CRYPTO', 'OTRO');

CREATE TABLE IF NOT EXISTS public.asset_snapshots (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id        UUID NOT NULL REFERENCES public.linked_accounts(id) ON DELETE CASCADE,
    ticker            TEXT NOT NULL,
    name              TEXT NOT NULL,
    asset_type        asset_type NOT NULL,
    quantity          NUMERIC(20, 8) NOT NULL,
    price_ars         NUMERIC(20, 4) NOT NULL,
    price_usd         NUMERIC(20, 4),
    total_ars         NUMERIC(20, 4) NOT NULL,
    total_usd         NUMERIC(20, 4),
    platform          platform_type NOT NULL,
    daily_change_pct  NUMERIC(10, 4) NOT NULL DEFAULT 0,
    snapshot_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_asset_snapshots_user_id    ON public.asset_snapshots(user_id);
CREATE INDEX IF NOT EXISTS idx_asset_snapshots_account_id ON public.asset_snapshots(account_id);

-- -----------------------------------------------------------------------------
-- 4. portfolios
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.portfolios (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON public.portfolios(user_id);

-- -----------------------------------------------------------------------------
-- 5. portfolio_assets (relación portfolio <-> asset_snapshot)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.portfolio_assets (
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    asset_id     UUID NOT NULL REFERENCES public.asset_snapshots(id) ON DELETE CASCADE,
    PRIMARY KEY (portfolio_id, asset_id)
);

-- -----------------------------------------------------------------------------
-- 6. Row Level Security
--    Cada usuario solo puede ver y modificar sus propias filas.
-- -----------------------------------------------------------------------------
ALTER TABLE public.user_vaults       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.linked_accounts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.asset_snapshots   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.portfolios        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.portfolio_assets  ENABLE ROW LEVEL SECURITY;

-- user_vaults
CREATE POLICY "user_vaults: solo el dueño" ON public.user_vaults
    FOR ALL USING (auth.uid() = user_id);

-- linked_accounts
CREATE POLICY "linked_accounts: solo el dueño" ON public.linked_accounts
    FOR ALL USING (auth.uid() = user_id);

-- asset_snapshots
CREATE POLICY "asset_snapshots: solo el dueño" ON public.asset_snapshots
    FOR ALL USING (auth.uid() = user_id);

-- portfolios
CREATE POLICY "portfolios: solo el dueño" ON public.portfolios
    FOR ALL USING (auth.uid() = user_id);

-- portfolio_assets: acceso via portfolios del usuario
CREATE POLICY "portfolio_assets: solo el dueño" ON public.portfolio_assets
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.portfolios p
            WHERE p.id = portfolio_id AND p.user_id = auth.uid()
        )
    );

-- -----------------------------------------------------------------------------
-- 7. Trigger: updated_at automático en portfolios
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER portfolios_updated_at
    BEFORE UPDATE ON public.portfolios
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
