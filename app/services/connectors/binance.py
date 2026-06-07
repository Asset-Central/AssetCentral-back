"""
Conector Binance — obtiene balances spot via REST API v3.
Autenticación: HMAC-SHA256 con api_key + api_secret.
"""

import hashlib
import hmac
import time

import httpx

from app.schemas.account import Platform
from app.schemas.asset import AssetType, Currency

from .base import BaseConnector, ConnectorError, Holding

BINANCE_BASE = "https://api.binance.com"

# Stablecoins que cotizan 1:1 con USD
_STABLE_USD = {"USDT", "BUSD", "USDC", "TUSD", "FDUSD", "DAI", "USDP"}

# Ignorar posiciones con valor < 0.001 USD (dust absoluto)
_MIN_USD = 0.001


def _sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


class BinanceConnector(BaseConnector):

    async def get_holdings(self) -> list[Holding]:
        api_key = self.credentials.get("api_key", "")
        api_secret = self.credentials.get("api_secret", "")
        if not api_key or not api_secret:
            raise ConnectorError("Faltan api_key o api_secret")

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                account = await self._signed_get(client, api_key, api_secret, "/api/v3/account")
                raw_balances = account.get("balances", [])

                # Solo activos con saldo > 0
                nonzero = [
                    (b["asset"], float(b["free"]) + float(b["locked"]))
                    for b in raw_balances
                    if float(b["free"]) + float(b["locked"]) > 0
                ]
                if not nonzero:
                    return []

                # Precios de todos los pares en una sola llamada
                prices_resp = await client.get(f"{BINANCE_BASE}/api/v3/ticker/price")
                prices_resp.raise_for_status()
                price_map: dict[str, float] = {
                    p["symbol"]: float(p["price"]) for p in prices_resp.json()
                }

                holdings: list[Holding] = []
                for asset, qty in nonzero:
                    if asset in _STABLE_USD:
                        unit_price = 1.0
                    else:
                        unit_price = (
                            price_map.get(f"{asset}USDT")
                            or price_map.get(f"{asset}BUSD")
                            or price_map.get(f"{asset}USDC")
                            or 0.0  # sin par USD (token delistado, etc.)
                        )

                    total = qty * unit_price
                    if total < _MIN_USD and unit_price > 0:
                        continue  # dust con precio conocido

                    holdings.append(Holding(
                        ticker=f"BIN-{asset}",
                        external_name=asset,
                        asset_type=AssetType.CRYPTO,
                        currency=Currency.USD,
                        platform=Platform.BINANCE,
                        quantity=qty,
                        unit_price=unit_price,
                        total_valuation=total,
                    ))

                return sorted(holdings, key=lambda h: -h.total_valuation)

        except ConnectorError:
            raise
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                raise ConnectorError("API Key o Secret inválidos") from exc
            raise ConnectorError(f"Binance API error {code}: {exc.response.text[:200]}") from exc
        except httpx.RequestError as exc:
            raise ConnectorError(f"Error de red al conectar con Binance: {exc}") from exc
        except Exception as exc:
            raise ConnectorError(f"Error inesperado al procesar respuesta de Binance: {exc}") from exc

    async def validate_credentials(self) -> bool:
        api_key = self.credentials.get("api_key", "")
        api_secret = self.credentials.get("api_secret", "")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                await self._signed_get(client, api_key, api_secret, "/api/v3/account")
            return True
        except ConnectorError:
            return False

    @staticmethod
    async def _signed_get(
        client: httpx.AsyncClient, api_key: str, secret: str, path: str
    ) -> dict:
        ts = int(time.time() * 1000)
        query = f"timestamp={ts}"
        sig = _sign(secret, query)
        url = f"{BINANCE_BASE}{path}?{query}&signature={sig}"
        resp = await client.get(url, headers={"X-MBX-APIKEY": api_key})
        resp.raise_for_status()
        return resp.json()
