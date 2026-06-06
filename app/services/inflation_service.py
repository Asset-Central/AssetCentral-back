"""
Servicio de inflación — obtiene datos mensuales de:
  - ARS: API de datos.gob.ar (INDEC IPC variación mensual)
  - USD: BLS CPI All Urban Consumers (v1, sin API key)
"""

import logging
from typing import Any

import httpx

log = logging.getLogger("inflation_service")


async def get_inflation(currency: str) -> list[dict]:
    c = currency.upper()
    if c == "ARS":
        return await _fetch_ars()
    if c == "USD":
        return await _fetch_usd()
    return []


async def _fetch_ars() -> list[dict]:
    """INDEC IPC — calcula variación mensual desde el índice de precios (últimos 36 meses)."""
    url = "https://apis.datos.gob.ar/series/api/series/"
    params = {
        "ids": "148.3_INIVELNAL_DICI_M_26",
        "limit": 37,   # +1 para poder calcular el primer cambio
        "format": "json",
        "sort": "desc",  # más recientes primero, para que limit traiga los últimos
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        data: Any = resp.json()
        rows = data.get("data") or []
        clean = sorted(
            [(str(r[0])[:7], float(r[1])) for r in rows if len(r) >= 2 and r[1] is not None],
            key=lambda x: x[0],
        )
        points = []
        for i in range(1, len(clean)):
            _, prev_val = clean[i - 1]
            curr_date, curr_val = clean[i]
            if prev_val:
                rate = (curr_val - prev_val) / prev_val * 100
                points.append({"date": curr_date, "rate": round(rate, 4)})
        return points
    except Exception as exc:
        log.warning("ARS inflation fetch failed: %s", exc)
        return []


async def _fetch_usd() -> list[dict]:
    """BLS CPI All Urban Consumers (CUUR0000SA0) — calcula variación mensual."""
    url = "https://api.bls.gov/publicAPI/v1/timeseries/data/"  # POST endpoint sin series en path
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"seriesid": ["CUUR0000SA0"]})
            resp.raise_for_status()
        series_list = resp.json().get("Results", {}).get("series", [])
        if not series_list:
            return []
        items: list[dict] = series_list[0].get("data", [])
        monthly = [i for i in items if i.get("period", "").startswith("M")]
        monthly.sort(key=lambda x: (x["year"], x["period"]))
        points = []
        prev_val: float | None = None
        for item in monthly:
            month = int(item["period"][1:])
            val = float(item["value"])
            date = f"{item['year']}-{month:02d}"
            if prev_val is not None:
                rate = (val - prev_val) / prev_val * 100
                points.append({"date": date, "rate": round(rate, 4)})
            prev_val = val
        return points[-36:]
    except Exception as exc:
        log.warning("USD inflation fetch failed: %s", exc)
        return []
