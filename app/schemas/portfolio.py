from datetime import datetime

from pydantic import BaseModel

from .asset import Asset, Currency


class Portfolio(BaseModel):
    id: str
    name: str
    description: str | None = None
    asset_tickers: list[str]
    created_at: datetime
    updated_at: datetime


class PortfolioAssetSummary(BaseModel):
    ticker: str
    name: str | None = None
    asset_type: str | None = None
    currency: Currency | None = None
    platform: str | None = None
    total_quantity: float
    unit_price: float | None = None
    total_valuation: float


class PortfolioSummary(BaseModel):
    portfolio: Portfolio
    assets: list[PortfolioAssetSummary]
    total_ars: float
    total_usd: float


class CreatePortfolioRequest(BaseModel):
    name: str
    description: str | None = None
    asset_tickers: list[str] = []


class UpdatePortfolioRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    asset_tickers: list[str] | None = None
