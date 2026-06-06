from enum import Enum

from pydantic import BaseModel

from .account import Platform


class AssetType(str, Enum):
    CEDEAR = "CEDEAR"
    BONO = "BONO"
    FCI = "FCI"
    USD = "USD"
    ACCION = "ACCION"
    CRYPTO = "CRYPTO"
    OTRO = "OTRO"


class Asset(BaseModel):
    id: str
    ticker: str
    name: str
    type: AssetType
    platform: Platform
    quantity: float
    price_ars: float
    price_usd: float | None = None
    total_ars: float
    total_usd: float | None = None
    daily_change_percent: float
