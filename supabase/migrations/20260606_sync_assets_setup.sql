-- Extensiones necesarias para el cron job y las requests HTTP
create extension if not exists pg_cron with schema extensions;
create extension if not exists pg_net  with schema extensions;

-- ---------------------------------------------------------------------------
-- RPC: get_decrypted_vault
-- Devuelve las credenciales desencriptadas de las cuentas que no están
-- desconectadas manualmente. Las cuentas con requires_reauthentication se
-- incluyen para que el cron intente reconectarlas automáticamente.
-- security definer permite acceder a vault.decrypted_secrets sin exponer
-- la vista directamente a roles no privilegiados.
-- ---------------------------------------------------------------------------
create or replace function public.get_decrypted_vault()
returns table (
  account_id  uuid,
  platform    character varying,
  credentials text
)
language sql
security definer
set search_path = public
as $$
  select
    a.id                  as account_id,
    a.platform,
    vs.decrypted_secret   as credentials
  from public.account a
  join vault.decrypted_secrets vs on vs.id = a.secret_id
  where a.connection_status <> 'disconnected'
    and a.secret_id is not null;
$$;

-- Solo service_role puede invocar esta función
revoke execute on function public.get_decrypted_vault() from public;
grant  execute on function public.get_decrypted_vault() to service_role;

-- ---------------------------------------------------------------------------
-- Cron job: disparar sync-assets cada 15 minutos
-- Reemplaza <tu-project-ref> y <tu-anon-key> antes de ejecutar este script.
-- ---------------------------------------------------------------------------
select cron.schedule(
  'sync-assets-15min',
  '*/15 * * * *',
  $$
  select net.http_post(
    url     := 'https://geqltnpxydhpwysapexz.supabase.co/functions/v1/sync-assets',
    headers := jsonb_build_object(
                 'Authorization', 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdlcWx0bnB4eWRocHd5c2FwZXh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA2OTY3NTksImV4cCI6MjA5NjI3Mjc1OX0.-r1lqcnIZGjyAMcWHUpZQz_Bw7qknFk3CNuE_5wJVNs',
                 'Content-Type',  'application/json'
               ),
    body    := '{}'::jsonb
  ) as request_id;
  $$
);
