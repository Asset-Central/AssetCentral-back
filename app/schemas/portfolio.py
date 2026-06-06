from datetime import datetime

from pydantic import BaseModel

from .asset import Asset


class Portfolio(BaseModel):
    id: str
    name: str
    description: str | None = None
    asset_ids: list[str]
    created_at: datetime
    updated_at: datetime


class PortfolioSummary(BaseModel):
    portfolio: Portfolio
    assets: list[Asset]
    total_ars: float
    total_usd: float | None = None
    daily_change_percent: float


class CreatePortfolioRequest(BaseModel):
    name: str
    description: str | None = None
    asset_ids: list[str] = []


class UpdatePortfolioRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    asset_ids: list[str] | None = None
