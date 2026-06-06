"""
FastAPI dependencies reutilizables.

get_current_user: extrae y valida el JWT de Supabase del header Authorization.
get_current_user_dek: además devuelve el DEK descifrado del usuario (para ops con credenciales).
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .security import decrypt_dek
from .supabase import supabase_admin

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    Valida el JWT de Supabase y devuelve el usuario.
    Lanza 401 si el token es inválido o expirado.
    """
    token = credentials.credentials
    try:
        response = supabase_admin.auth.get_user(token)
        if response.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido o expirado",
            )
        return response.user
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )


async def get_current_user_dek(
    user=Depends(get_current_user),
) -> tuple[dict, bytes]:
    """
    Devuelve (user, dek) para endpoints que necesitan descifrar/cifrar credenciales.
    """
    user_id = user.id
    result = (
        supabase_admin.table("user_vaults")
        .select("dek_encrypted")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault del usuario no encontrado",
        )
    dek = decrypt_dek(result.data["dek_encrypted"])
    return user, dek
