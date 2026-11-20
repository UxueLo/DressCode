"""Cliente de Open-Meteo (geocoding + previsión diaria). No requiere API key."""
from __future__ import annotations

from datetime import date
from functools import lru_cache

import requests

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}


class WeatherError(Exception):
    pass


@lru_cache(maxsize=64)
def _geocode(city_key: str) -> tuple[float, float, str]:
    try:
        r = requests.get(GEO_URL, params={"name": city_key, "count": 1,
                                          "language": "es", "format": "json"}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        raise WeatherError(f"No se pudo contactar con Open-Meteo: {e}") from e
    results = r.json().get("results")
    if not results:
        raise WeatherError(f"No se encontró la ciudad «{city_key}»")
    top = results[0]
    return top["latitude"], top["longitude"], top["name"]


def temperature_category(t: float) -> str:
    if t < 8:
        return "Frío"
    if t < 15:
        return "Fresco"
    if t < 22:
        return "Templado"
    if t < 28:
        return "Cálido"
    return "Caluroso"


def get_weather(city: str, target: date) -> dict:
    lat, lon, name = _geocode(city.strip().lower())
    try:
        r = requests.get(FORECAST_URL, params={
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "start_date": target.isoformat(), "end_date": target.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                     "wind_speed_10m_max,weather_code",
        }, timeout=10)
    except requests.RequestException as e:
        raise WeatherError(f"No se pudo contactar con Open-Meteo: {e}") from e
    if r.status_code == 400:
        raise WeatherError(r.json().get("reason", "Fecha fuera del rango de previsión (máx. 16 días)"))
    r.raise_for_status()

    d = r.json()["daily"]
    t_max, t_min = d["temperature_2m_max"][0], d["temperature_2m_min"][0]
    rain_prob = d["precipitation_probability_max"][0] or 0
    wind = d["wind_speed_10m_max"][0] or 0
    t_avg = (t_max + t_min) / 2
    return {
        "city": name, "date": target.isoformat(),
        "t_min": round(t_min, 1), "t_max": round(t_max, 1), "t_avg": round(t_avg, 1),
        "category": temperature_category(t_avg),
        "rain_prob": rain_prob, "wind_kmh": wind,
        "rainy": rain_prob >= 50 or d["weather_code"][0] in RAIN_CODES,
        "windy": wind >= 25,
    }
