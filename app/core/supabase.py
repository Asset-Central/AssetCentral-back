from supabase import create_client, Client
from .config import settings

# Cliente con anon key + RLS activo (para operaciones del usuario autenticado)
supabase: Client = create_client(settings.supabase_url, settings.supabase_anon_key)

# Cliente con service role key (bypasea RLS — solo para operaciones internas del backend)
supabase_admin: Client = create_client(
    settings.supabase_url, settings.supabase_service_role_key
)
