"""
Conector para Prometeo Open Banking (Sandbox).
Referencia: https://banking.sandbox.prometeoapi.com
"""

import httpx

from app.core.config import settings
from app.schemas.account import Platform
from app.schemas.asset import AssetType, Currency

from .base import BaseConnector, ConnectorError, Holding

PROMETEO_BASE = "https://banking.sandbox.prometeoapi.com"

# Timeout conservador para el sandbox (a veces lento)
_TIMEOUT = httpx.Timeout(30.0)


class PrometeoConnector(BaseConnector):
    """
    Implementa el flujo stateless de Prometeo:
        login → query → logout
    Cada llamada a get_holdings() abre y cierra su propia sesión.
    """

    async def get_holdings(self) -> list[Holding]:
        key = await self._login()
        try:
            return await self._fetch_holdings(key)
        finally:
            # Logout es best-effort: nunca debe romper el flujo principal
            await self._logout(key)

    async def validate_credentials(self) -> bool:
        try:
            key = await self._login()
            await self._logout(key)
            return True
        except ConnectorError:
            return False

    # ------------------------------------------------------------------ #
    #  Helpers privados                                                    #
    # ------------------------------------------------------------------ #

    async def _login(self) -> str:
        """
        POST /login/ → devuelve la session key de Prometeo.
        Lanza ConnectorError si las credenciales son inválidas o el provider no responde.
        """
        payload = {
            "provider": self.credentials.get("provider", "test"),
            "username": self.credentials["username"],
            "password": self.credentials["password"],
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{PROMETEO_BASE}/login/",
                    headers={"X-API-Key": settings.prometeo_api_key},
                    json=payload,
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(
                f"Prometeo login HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise ConnectorError(f"Error de red al conectar con Prometeo: {exc}") from exc

        data = resp.json()

        # La API sandbox responde "logged_in"; guard para variantes del sandbox
        status = data.get("status", "")
        if status not in ("logged_in", "success"):
            raise ConnectorError(
                f"Login rechazado por Prometeo (status={status!r}). "
                "Verifica usuario, contraseña y provider."
            )

        key = data.get("key")
        if not key:
            raise ConnectorError("Prometeo no devolvió session key tras el login.")

        return key

    async def _fetch_holdings(self, key: str) -> list[Holding]:
        """
        GET /account/balances/?key=<key>
        Convierte cada cuenta bancaria en un Holding de tipo CASH.
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{PROMETEO_BASE}/account/",
                    headers={"X-API-Key": settings.prometeo_api_key},
                    params={"key": key},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(
                f"Prometeo balances HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        data = resp.json()
        accounts: list[dict] = data.get("accounts", [])

        holdings: list[Holding] = []
        for account in accounts:
            currency_str = account.get("currency", "").upper()

            # Solo procesamos monedas que existen en nuestro enum
            try:
                currency = Currency(currency_str)
            except ValueError:
                continue

            balance = float(account.get("balance", 0) or 0)
            number = account.get("number") or account.get("id") or "?"

            currency_label = "ARS" if currency_str == "ARS" else "USD"
            holdings.append(
                Holding(
                    ticker=f"PROMETEO_{currency_str}",
                    external_name=f"Banco Nación - {currency_label}",
                    asset_type=AssetType.CASH,
                    currency=currency,
                    platform=Platform.NACION,
                    quantity=balance,
                    unit_price=1.0,
                    total_valuation=balance,
                )
            )

        return holdings

    async def _logout(self, key: str) -> None:
        """POST /logout/ — invalida la session key en Prometeo."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                await client.post(
                    f"{PROMETEO_BASE}/logout/",
                    headers={"X-API-Key": settings.prometeo_api_key},
                    json={"key": key},
                )
        except Exception:
            # Logout best-effort: un fallo aquí no es crítico
            pass
