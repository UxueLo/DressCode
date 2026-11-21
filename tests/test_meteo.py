from datetime import date

import pytest

from services import meteo_service as m


class R:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise m.requests.HTTPError("x")


def test_get_weather_usa_media_de_horas_de_calle(monkeypatch):
    m._geocode.cache_clear()
    horas = [5.0] * 8 + [15.0] * 15 + [5.0]          # 8-22 h a 15 °C
    def fake_get(url, params=None, timeout=0):
        if "geocoding" in url:
            return R({"results": [{"latitude": 43.2, "longitude": -2.9, "name": "Bilbao"}]})
        return R({"daily": {"temperature_2m_max": [18.0], "temperature_2m_min": [6.0],
                            "precipitation_probability_max": [70], "wind_speed_10m_max": [10],
                            "weather_code": [61]}, "hourly": {"temperature_2m": horas}})
    monkeypatch.setattr(m.requests, "get", fake_get)
    c = m.get_weather("Bilbao", date(2026, 11, 20))
    assert c["t_ref"] == 15.0 and c["rainy"] and not c["snowy"] and not c["windy"]
    assert "lluvia" in c["resumen"]


def test_ciudad_inexistente(monkeypatch):
    m._geocode.cache_clear()
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: R({}))
    with pytest.raises(m.WeatherError):
        m.get_weather("zzzz")


def test_clima_manual():
    c = m.clima_manual(7, lluvia=True)
    assert c["t_ref"] == 7 and c["rainy"] and c["fuente"] == "manual"
