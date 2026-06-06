from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import get_current_user
from app.schemas.market import MarketPricePoint, MarketQuote
from app.services.market_service import get_market_history, get_quote, search_market

router = APIRouter(prefix="/market", tags=["market"])

RangeType = Literal["1h", "1d", "1w", "30d", "1y"]


@router.get("/search", response_model=list[MarketQuote])
async def market_search(
    q: str = Query(min_length=1),
    _user=Depends(get_current_user),
):
    """Busca instrumentos en Yahoo Finance (acciones, CEDEARs, cripto, bonos…)."""
    return await search_market(q)


@router.get("/{ticker}/quote", response_model=MarketQuote)
async def market_quote(
    ticker: str,
    _user=Depends(get_current_user),
):
    """Cotización actual de un instrumento."""
    result = await get_quote(ticker)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' no encontrado")
    return result


@router.get("/{ticker}/history", response_model=list[MarketPricePoint])
async def market_history(
    ticker: str,
    _user=Depends(get_current_user),
    range: RangeType = Query(default="30d"),
):
    """Historial de precios de un instrumento del mercado."""
    return await get_market_history(ticker, range)
