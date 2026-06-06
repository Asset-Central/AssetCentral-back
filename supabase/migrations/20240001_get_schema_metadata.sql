-- Returns the full public schema with COMMENT ON semantic metadata.
-- Called by the MCP server's docs://schema/assetcentral resource and
-- the get_database_schema tool.

-- Drop first so we can change the return type if the function already exists.
DROP FUNCTION IF EXISTS public.get_schema_metadata();

CREATE OR REPLACE FUNCTION public.get_schema_metadata()
RETURNS TABLE (
  schema_name    text,
  object_type    text,
  object_name    text,
  table_comment  text,
  column_name    text,
  data_type      text,
  is_nullable    text,
  column_comment text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    n.nspname::text                                               AS schema_name,
    CASE c.relkind
      WHEN 'r' THEN 'table'
      WHEN 'v' THEN 'view'
      WHEN 'm' THEN 'materialized_view'
    END                                                           AS object_type,
    c.relname::text                                               AS object_name,
    COALESCE(obj_description(c.oid, 'pg_class'), '')              AS table_comment,
    a.attname::text                                               AS column_name,
    pg_catalog.format_type(a.atttypid, a.atttypmod)::text         AS data_type,
    CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END               AS is_nullable,
    COALESCE(col_description(a.attrelid, a.attnum), '')           AS column_comment
  FROM pg_attribute   a
  JOIN pg_class       c ON a.attrelid = c.oid
  JOIN pg_namespace   n ON c.relnamespace = n.oid
  WHERE n.nspname = 'public'
    AND c.relkind IN ('r', 'v', 'm')
    AND a.attnum > 0
    AND NOT a.attisdropped
  ORDER BY c.relname, a.attnum;
$$;

GRANT EXECUTE ON FUNCTION public.get_schema_metadata()
  TO anon, authenticated, service_role;
