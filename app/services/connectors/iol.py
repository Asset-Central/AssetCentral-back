"""
Conector para InvertirOnline (IOL) API.
Referencia: https://api.invertironline.com
"""

import httpx

from app.schemas.account import Platform
from app.schemas.asset import AssetType, Currency

from .base import BaseConnector, ConnectorError, Holding

IOL_BASE = "https://api.invertironline.com"
_TIMEOUT = httpx.Timeout(30.0)

_CURRENCY_MAP = {
    "peso_argentino": Currency.ARS,
    "dolar_estadounidense": Currency.USD,
    "pesos": Currency.ARS,
    "dolares": Currency.USD,
}

_ASSET_TYPE_MAP = {
    "acciones": AssetType.STOCK,
    "cedears": AssetType.CEDEAR,
    "bonos": AssetType.BONO,
    "letras": AssetType.BONO,
    "obligaciones_negociables": AssetType.BONO,
    "fondos_comunes_de_inversion": AssetType.FCI,
    "fci": AssetType.FCI,
    "opciones": AssetType.STOCK,
    # Cauciones: aparecen en estadocuenta, no en portafolio
    "cauciones": AssetType.CAUCION,
}


class IolConnector(BaseConnector):
    """
    Implementa el flujo de IOL:
        autenticar → obtener portafolio + estado de cuenta → refrescar token si expira.
    """

    async def get_holdings(self) -> list[Holding]:
        token = await self._authenticate()
        holdings = []
        holdings += await self._fetch_portfolio(token)
        holdings += await self._fetch_cash(token)
        return holdings

    async def validate_credentials(self) -> bool:
        try:
            await self._authenticate()
            return True
        except ConnectorError:
            return False

    # ------------------------------------------------------------------ #
    #  Helpers privados                                                    #
    # ------------------------------------------------------------------ #

    async def _authenticate(self) -> str:
        """POST /token → devuelve el access_token Bearer."""
        payload = {
            "username": self.credentials["username"],
            "password": self.credentials["password"],
            "grant_type": "password",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{IOL_BASE}/token",
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(
                f"IOL login HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise ConnectorError(f"Error de red al conectar con IOL: {exc}") from exc

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise ConnectorError("IOL no devolvió access_token tras el login.")
        return token

    async def _fetch_portfolio(self, token: str) -> list[Holding]:
        """GET /api/v2/portafolio/argentina → posiciones de títulos."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{IOL_BASE}/api/v2/portafolio/argentina",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(
                f"IOL portafolio HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        data = resp.json()
        activos = data.get("activos") or []

        holdings: list[Holding] = []
        for activo in activos:
            titulo = activo.get("titulo") or {}
            simbolo = titulo.get("simbolo") or "?"
            descripcion = titulo.get("descripcion") or simbolo
            tipo_raw = (titulo.get("tipo") or "").lower()
            moneda_raw = (titulo.get("moneda") or "").lower()

            currency = _CURRENCY_MAP.get(moneda_raw, Currency.ARS)
            asset_type = _ASSET_TYPE_MAP.get(tipo_raw, AssetType.STOCK)

            cantidad = float(activo.get("cantidad") or 0)
            ultimo_precio = float(activo.get("ultimoPrecio") or 0)
            valorizado = float(activo.get("valorizado") or cantidad * ultimo_precio)

            if cantidad <= 0:
                continue

            holdings.append(
                Holding(
                    ticker=f"IOL_{simbolo}",
                    external_name=descripcion,
                    asset_type=asset_type,
                    currency=currency,
                    platform=Platform.IOL,
                    quantity=cantidad,
                    unit_price=ultimo_precio if ultimo_precio else None,
                    total_valuation=valorizado,
                )
            )

        return holdings

    async def _fetch_cash(self, token: str) -> list[Holding]:
        """GET /api/v2/estadocuenta → saldos disponibles en efectivo."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{IOL_BASE}/api/v2/estadocuenta",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Estado de cuenta es best-effort: si falla no interrumpimos el portafolio
            return []

        data = resp.json()
        cuentas = data.get("cuentas") or []

        holdings: list[Holding] = []
        seen_currencies: set[str] = set()

        for cuenta in cuentas:
            moneda_raw = (cuenta.get("moneda") or "").lower()
            currency = _CURRENCY_MAP.get(moneda_raw)
            if not currency:
                continue

            # ── Efectivo disponible ──
            disponible = float(cuenta.get("disponible") or 0)
            if disponible > 0 and currency.value not in seen_currencies:
                seen_currencies.add(currency.value)
                holdings.append(
                    Holding(
                        ticker=f"IOL_CASH_{currency.value}",
                        external_name=f"Efectivo IOL ({currency.value})",
                        asset_type=AssetType.CASH,
                        currency=currency,
                        platform=Platform.IOL,
                        quantity=disponible,
                        unit_price=1.0,
                        total_valuation=disponible,
                    )
                )

            # ── Cauciones colocadas (dinero prestado, genera interés) ──
            caucion = float(cuenta.get("caucionColocada") or 0)
            if caucion > 0:
                holdings.append(
                    Holding(
                        ticker=f"IOL_CAUCION_{currency.value}",
                        external_name=f"Caución colocada IOL ({currency.value})",
                        asset_type=AssetType.CAUCION,
                        currency=currency,
                        platform=Platform.IOL,
                        quantity=caucion,
                        unit_price=1.0,
                        total_valuation=caucion,
                    )
                )

        return holdings
