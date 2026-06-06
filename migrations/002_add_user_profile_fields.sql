-- =============================================================================
-- Migration 002: Campos de perfil extendido en public.users
-- =============================================================================

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS nombre   VARCHAR(100),
  ADD COLUMN IF NOT EXISTS apellido VARCHAR(100),
  ADD COLUMN IF NOT EXISTS dni      VARCHAR(20);
