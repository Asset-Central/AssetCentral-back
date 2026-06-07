-- Agrega 'binance' al enum platform_type para soportar cuentas Binance
ALTER TYPE platform_type ADD VALUE IF NOT EXISTS 'binance';
