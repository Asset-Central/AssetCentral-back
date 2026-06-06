from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .supabase import supabase_admin

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    Valida el JWT de Supabase y sincroniza el perfil en public.users.
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
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )

    user = response.user
    _sync_user_profile(user)
    return user


def _sync_user_profile(user) -> None:
    """Upsert del perfil en public.users para usuarios nuevos."""
    meta = user.user_metadata or {}
    data: dict = {"id": user.id, "full_name": _extract_full_name(user)}
    # Solo sobreescribir si el valor existe en metadata (no pisar datos ya guardados con null)
    for field in ("nombre", "apellido", "dni"):
        if meta.get(field):
            data[field] = meta[field]
    supabase_admin.table("users").upsert(data, on_conflict="id").execute()


def _extract_full_name(user) -> str | None:
    if user.user_metadata:
        return (
            user.user_metadata.get("full_name")
            or user.user_metadata.get("name")
        )
    return None
