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
    """INDEC IPC variación mensual — datos.gob.ar series API."""
    url = "https://apis.datos.gob.ar/series/api/series/"
    params = {
        "ids": "148.3_INIVELNAL_DICI_M_26",
        "limit": 36,
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        data: Any = resp.json()
        rows = data.get("data") or []
        points = []
        for row in rows:
            if len(row) < 2 or row[1] is None:
                continue
            date = str(row[0])[:7]  # "YYYY-MM"
            rate = float(row[1])
            points.append({"date": date, "rate": round(rate, 4)})
        return sorted(points, key=lambda x: x["date"])
    except Exception as exc:
        log.warning("ARS inflation fetch failed: %s", exc)
        return []


async def _fetch_usd() -> list[dict]:
    """BLS CPI All Urban Consumers (CUUR0000SA0) — calcula variación mensual."""
    url = "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"seriesid": ["CUUR0000SA0"]})
            resp.raise_for_status()
        series_list = resp.json().get("Results", {}).get("series", [])
        if not series_list:
            return []
        items: list[dict] = series_list[0].get("data", [])
        # Filtrar solo meses (excluir anuales) y ordenar ascendente
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
        return points[-36:]  # últimos 3 años
    except Exception as exc:
        log.warning("USD inflation fetch failed: %s", exc)
        return []
