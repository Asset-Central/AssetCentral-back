from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.schemas.profile import UpsertFinancialProfileRequest, UserFinancialProfile, FinancialProfileData
from app.services.profile_service import get_profile, upsert_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserFinancialProfile)
async def read_profile(user=Depends(get_current_user)):
    """Retorna el perfil financiero del usuario autenticado."""
    data = await get_profile(user.id)
    return UserFinancialProfile(profile=FinancialProfileData(**data))


@router.put("", response_model=UserFinancialProfile)
async def write_profile(body: UpsertFinancialProfileRequest, user=Depends(get_current_user)):
    """Guarda (merge) el perfil financiero del usuario autenticado."""
    merged = await upsert_profile(user.id, body.profile.model_dump(exclude_none=True))
    return UserFinancialProfile(profile=FinancialProfileData(**merged))
