import time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_user
from app.schemas.asset import Asset, InflationPoint, PerformancePoint, PricePoint, ValuePoint
from app.services.asset_service import AssetService
from app.services.inflation_service import get_inflation

router = APIRouter(prefix="/assets", tags=["assets"])

_usd_rate_cache: dict = {"rate": None, "ts": 0.0}
_USD_RATE_TTL = 300  # 5 min

RangeType = Literal["1h", "1d", "1w", "30d", "1y"]


@router.get("/usd-rate")
async def usd_rate(_user=Depends(get_current_user)):
    """Tipo de cambio dólar blue venta (ARS por 1 USD), con caché de 5 minutos."""
    now = time.time()
    if _usd_rate_cache["rate"] is not None and now - _usd_rate_cache["ts"] < _USD_RATE_TTL:
        return {"rate": _usd_rate_cache["rate"]}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://dolarapi.com/v1/dolares/blue")
            resp.raise_for_status()
            data = resp.json()
            rate = float(data["venta"])
    except Exception:
        if _usd_rate_cache["rate"] is not None:
            return {"rate": _usd_rate_cache["rate"]}
        return {"rate": 1000.0}
    _usd_rate_cache["rate"] = rate
    _usd_rate_cache["ts"] = now
    return {"rate": rate}


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


@router.get("/performance", response_model=list[PerformancePoint])
async def performance(
    user=Depends(get_current_user),
    range: RangeType = Query(default="30d"),
):
    """Descomposición de rendimiento: market P&L vs flujos de capital por período."""
    return await AssetService.get_performance(user_id=user.id, range=range)


@router.get("/inflation", response_model=list[InflationPoint])
async def inflation(
    _user=Depends(get_current_user),
    currency: str = Query(default="ARS"),
):
    """Inflación mensual para ARS (INDEC) o USD (BLS CPI)."""
    return await get_inflation(currency)


@router.get("/{ticker}/history", response_model=list[PricePoint])
async def asset_history(
    ticker: str,
    user=Depends(get_current_user),
    range: RangeType = Query(default="30d"),
):
    """Historial de precio de un activo específico."""
    return await AssetService.get_asset_history(user_id=user.id, ticker=ticker, range=range)
