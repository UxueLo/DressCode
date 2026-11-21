"""Cliente de Open-Meteo (geocoding + previsión). No requiere API key.

`t_ref` es la temperatura que usa el algoritmo: media de las horas "de calle" (8:00-22:00),
más representativa para vestirse que la media de máx/mín del día.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Optional

import requests

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SNOW_CODES = {71, 73, 75, 77, 85, 86}
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
HORAS_CALLE = range(8, 23)


class WeatherError(Exception):
    pass


@lru_cache(maxsize=64)
def _geocode(ciudad: str) -> tuple[float, float, str]:
    try:
        r = requests.get(GEO_URL, params={"name": ciudad, "count": 1, "language": "es", "format": "json"},
                         timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        raise WeatherError(f"No se pudo contactar con Open-Meteo: {e}") from e
    resultados = r.json().get("results")
    if not resultados:
        raise WeatherError(f"No se encontró la ciudad «{ciudad}»")
    top = resultados[0]
    return top["latitude"], top["longitude"], top["name"]


def _resumen(c: dict) -> str:
    extra = [txt for ok, txt in ((c["snowy"], "nieve"), (c["rainy"], "lluvia"), (c["windy"], "viento")) if ok]
    return f"{c['t_ref']:.0f} °C (mín {c['t_min']:.0f} / máx {c['t_max']:.0f})" + (", " + ", ".join(extra) if extra else "")


def clima_manual(t_ref: float, lluvia: bool = False, nieve: bool = False, viento: bool = False,
                 ciudad: str = "manual", fecha: Optional[date] = None) -> dict:
    """Clima introducido a mano (sin red) con el mismo formato que `get_weather`."""
    c = {"city": ciudad, "date": (fecha or date.today()).isoformat(), "t_min": t_ref, "t_max": t_ref,
         "t_avg": t_ref, "t_ref": float(t_ref), "rain_prob": 100 if lluvia else 0,
         "wind_kmh": 30 if viento else 0, "rainy": lluvia, "snowy": nieve, "windy": viento,
         "fuente": "manual"}
    c["resumen"] = _resumen(c)
    return c


def get_weather(city: str, target: Optional[date] = None) -> dict:
    target = target or date.today()
    lat, lon, nombre = _geocode(city.strip().lower())
    try:
        r = requests.get(FORECAST_URL, params={
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "start_date": target.isoformat(), "end_date": target.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                     "wind_speed_10m_max,weather_code",
            "hourly": "temperature_2m",
        }, timeout=10)
    except requests.RequestException as e:
        raise WeatherError(f"No se pudo contactar con Open-Meteo: {e}") from e
    if r.status_code == 400:
        raise WeatherError(r.json().get("reason", "Fecha fuera del rango de previsión (máx. 16 días)"))
    try:
        r.raise_for_status()
        d, h = r.json()["daily"], r.json()["hourly"]["temperature_2m"]
    except (requests.RequestException, KeyError, ValueError) as e:
        raise WeatherError(f"Respuesta inesperada de Open-Meteo: {e}") from e

    t_max, t_min = d["temperature_2m_max"][0], d["temperature_2m_min"][0]
    if t_max is None or t_min is None:
        raise WeatherError("Open-Meteo no tiene previsión para esa fecha")
    horas = [h[i] for i in HORAS_CALLE if i < len(h) and h[i] is not None]
    t_avg = (t_max + t_min) / 2
    codigo = (d["weather_code"][0] if d.get("weather_code") else None)
    prob = d["precipitation_probability_max"][0] or 0
    viento = d["wind_speed_10m_max"][0] or 0
    c = {
        "city": nombre, "date": target.isoformat(),
        "t_min": round(t_min, 1), "t_max": round(t_max, 1), "t_avg": round(t_avg, 1),
        "t_ref": round(sum(horas) / len(horas), 1) if horas else round(t_avg, 1),
        "rain_prob": prob, "wind_kmh": viento,
        "snowy": codigo in SNOW_CODES,
        "rainy": prob >= 50 or codigo in RAIN_CODES,
        "windy": viento >= 25, "fuente": "open-meteo",
    }
    c["resumen"] = _resumen(c)
    return c
