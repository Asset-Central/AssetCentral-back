-- Agrega columna nombre a la tabla account (nombre visible de la cuenta, ej. "Mi cuenta Binance")
ALTER TABLE public.account
    ADD COLUMN IF NOT EXISTS nombre VARCHAR(255);
