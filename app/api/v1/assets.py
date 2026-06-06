from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user_dek
from app.schemas.asset import Asset
from app.services.asset_service import AssetService

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[Asset])
async def list_assets(user_and_dek=Depends(get_current_user_dek)):
    """
    Devuelve los activos consolidados de todas las cuentas vinculadas.
    Sincroniza con los brokers en tiempo real y actualiza el snapshot.
    """
    user, dek = user_and_dek
    return await AssetService.get_assets(user_id=user.id, dek=dek)
