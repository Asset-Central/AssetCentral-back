-- Agrega el valor 'caucion' al enum asset_class_type
-- Necesario para persistir cauciones colocadas de IOL.
ALTER TYPE asset_class_type ADD VALUE IF NOT EXISTS 'caucion';
