from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_user
from app.schemas.asset import Asset, PricePoint, ValuePoint
from app.services.asset_service import AssetService

router = APIRouter(prefix="/assets", tags=["assets"])

RangeType = Literal["1h", "1d", "1w", "30d", "1y"]


@router.get("", response_model=list[Asset])
async def list_assets(user=Depends(get_current_user)):
    return await AssetService.get_assets(user_id=user.id)


@router.get("/value-history", response_model=list[ValuePoint])
async def value_history(
    user=Depends(get_current_user),
    range: RangeType = Query(default="30d"),
):
    """Valuación total del portafolio por el rango indicado."""
    return await AssetService.get_value_history(user_id=user.id, range=range)


@router.get("/{ticker}/history", response_model=list[PricePoint])
async def asset_history(
    ticker: str,
    user=Depends(get_current_user),
    range: RangeType = Query(default="30d"),
):
    """Historial de precio de un activo específico."""
    return await AssetService.get_asset_history(user_id=user.id, ticker=ticker, range=range)
