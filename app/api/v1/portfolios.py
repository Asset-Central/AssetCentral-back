from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_current_user
from app.schemas.asset import ValuePoint
from app.schemas.portfolio import (
    CreatePortfolioRequest,
    Portfolio,
    PortfolioSummary,
    UpdatePortfolioRequest,
)
from app.services.portfolio_service import PortfolioService

RangeType = Literal["1h", "1d", "1w", "30d", "1y"]

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


@router.get("", response_model=list[Portfolio])
async def list_portfolios(user=Depends(get_current_user)):
    return await PortfolioService.list_portfolios(user_id=user.id)


@router.post("", response_model=Portfolio, status_code=status.HTTP_201_CREATED)
async def create_portfolio(body: CreatePortfolioRequest, user=Depends(get_current_user)):
    return await PortfolioService.create_portfolio(user_id=user.id, data=body)


@router.get("/{portfolio_id}/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(portfolio_id: str, user=Depends(get_current_user)):
    return await PortfolioService.get_summary(user_id=user.id, portfolio_id=portfolio_id)


@router.patch("/{portfolio_id}", response_model=Portfolio)
async def update_portfolio(
    portfolio_id: str,
    body: UpdatePortfolioRequest,
    user=Depends(get_current_user),
):
    return await PortfolioService.update_portfolio(
        user_id=user.id, portfolio_id=portfolio_id, data=body
    )


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(portfolio_id: str, user=Depends(get_current_user)):
    await PortfolioService.delete_portfolio(user_id=user.id, portfolio_id=portfolio_id)


@router.get("/{portfolio_id}/value-history", response_model=list[ValuePoint])
async def portfolio_value_history(
    portfolio_id: str,
    user=Depends(get_current_user),
    range: RangeType = Query(default="30d"),
):
    """Valuación histórica de los activos de un portfolio específico."""
    return await PortfolioService.get_value_history(
        portfolio_id=portfolio_id, user_id=user.id, range=range
    )
