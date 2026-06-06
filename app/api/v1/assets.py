from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.schemas.asset import Asset, PricePoint, ValuePoint
from app.services.asset_service import AssetService

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[Asset])
async def list_assets(user=Depends(get_current_user)):
    return await AssetService.get_assets(user_id=user.id)


@router.get("/value-history", response_model=list[ValuePoint])
async def value_history(user=Depends(get_current_user)):
    """Valuación total del portafolio por día (últimos 30 días)."""
    return await AssetService.get_value_history(user_id=user.id)


@router.get("/{ticker}/history", response_model=list[PricePoint])
async def asset_history(ticker: str, user=Depends(get_current_user)):
    """Historial de precio de un activo específico."""
    return await AssetService.get_asset_history(user_id=user.id, ticker=ticker)
