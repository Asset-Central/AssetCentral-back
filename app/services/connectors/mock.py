"""
Conector mock — devuelve datos hardcodeados.
Usar mientras no esté implementado el conector real de una plataforma.
"""

import uuid

from app.schemas.account import Platform
from app.schemas.asset import Asset, AssetType

from .base import BaseConnector

MOCK_DATA: dict[str, list[dict]] = {
    "COCOS": [
        {"ticker": "GGAL", "name": "Grupo Financiero Galicia", "type": "CEDEAR",
         "quantity": 10, "price_ars": 4200, "daily_change_pct": 1.5},
        {"ticker": "AAPL", "name": "Apple Inc.", "type": "CEDEAR",
         "quantity": 5, "price_ars": 8500, "daily_change_pct": -0.3},
    ],
    "IOL": [
        {"ticker": "AL30", "name": "Bono AL30", "type": "BONO",
         "quantity": 100, "price_ars": 620, "daily_change_pct": 0.8},
        {"ticker": "FCI-PREMIER", "name": "FCI Premier Renta", "type": "FCI",
         "quantity": 1000, "price_ars": 105, "daily_change_pct": 0.05},
    ],
    "MERCADO_PAGO": [
        {"ticker": "USD", "name": "Dólar MEP", "type": "USD",
         "quantity": 500, "price_ars": 1250, "daily_change_pct": 0.2},
    ],
    "PROMETEO": [
        {"ticker": "BTC", "name": "Bitcoin", "type": "CRYPTO",
         "quantity": 0.01, "price_ars": 120_000_000, "daily_change_pct": 3.2},
    ],
}


class MockConnector(BaseConnector):

    async def get_assets(self) -> list[Asset]:
        platform_key = self.credentials.get("_mock_platform", "COCOS")
        items = MOCK_DATA.get(platform_key, [])
        return [
            Asset(
                id=str(uuid.uuid4()),
                ticker=item["ticker"],
                name=item["name"],
                type=AssetType(item["type"]),
                platform=Platform(platform_key),
                quantity=item["quantity"],
                price_ars=item["price_ars"],
                total_ars=item["quantity"] * item["price_ars"],
                daily_change_percent=item["daily_change_pct"],
            )
            for item in items
        ]

    async def validate_credentials(self) -> bool:
        return True
