from app.core.supabase import supabase_admin


async def get_profile(user_id: str) -> dict:
    result = (
        supabase_admin.table("users")
        .select("financial_profile")
        .eq("id", user_id)
        .single()
        .execute()
    )
    return result.data.get("financial_profile") or {}


async def upsert_profile(user_id: str, data: dict) -> dict:
    # Cargar perfil existente y hacer merge para no pisar campos no enviados
    existing = await get_profile(user_id)
    # Eliminar keys con valor None para no sobreescribir con nulls
    cleaned = {k: v for k, v in data.items() if v is not None}
    merged = {**existing, **cleaned}

    supabase_admin.table("users").update({"financial_profile": merged}).eq("id", user_id).execute()
    return merged
