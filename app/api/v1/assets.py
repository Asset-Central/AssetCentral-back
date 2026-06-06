from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.schemas.asset import Asset
from app.services.asset_service import AssetService

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[Asset])
async def list_assets(user=Depends(get_current_user)):
    """
    Sincroniza con los brokers vinculados y devuelve el balance más reciente
    de todos los activos del usuario.
    """
    return await AssetService.get_assets(user_id=user.id)
