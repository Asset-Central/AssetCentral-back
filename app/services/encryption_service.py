"""
Gestión del vault por usuario.

Al primer login del usuario se debe llamar a ensure_vault_exists()
para generar y persistir su DEK cifrado.
"""

from app.core.security import decrypt_dek, encrypt_dek, generate_dek
from app.core.supabase import supabase_admin


async def ensure_vault_exists(user_id: str) -> None:
    """
    Crea el vault del usuario si no existe todavía.
    Llamar en el flujo de post-registro / primer login.
    """
    existing = (
        supabase_admin.table("user_vaults")
        .select("user_id")
        .eq("user_id", user_id)
        .execute()
    )
    if existing.data:
        return

    dek = generate_dek()
    dek_encrypted = encrypt_dek(dek)
    supabase_admin.table("user_vaults").insert(
        {"user_id": user_id, "dek_encrypted": dek_encrypted}
    ).execute()


async def get_user_dek(user_id: str) -> bytes:
    """Obtiene y descifra el DEK del usuario."""
    result = (
        supabase_admin.table("user_vaults")
        .select("dek_encrypted")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return decrypt_dek(result.data["dek_encrypted"])
