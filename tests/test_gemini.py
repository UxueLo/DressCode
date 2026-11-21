"""Lógica de GeminiService (reintentos, degradación, modelo de reserva) con un cliente simulado,
y comprobación de que el worker analiza varias prendas a la vez. No usa red ni API key."""
import json
import threading
import time
from types import SimpleNamespace

import pytest
from google.genai import errors
from PIL import Image

import config
from database.db import ArmarioDB
from services import gemini_service as gs
from services.gemini_service import GeminiError, GeminiService
from workers.gemini_hilo import procesar_prenda

FICHA = {"garment": {"main_category": "Top", "sub_category": "Camiseta",
                     "visuals": {"primary_color": "Blanco", "secondary_color": None, "pattern": "Liso",
                                 "fit_type": "Regular", "style_aesthetics": ["Casual"]},
                     "context": {"formality_level": 2, "recommended_events": ["casual"],
                                 "weather": {"temperature_min": 16, "temperature_max": 35,
                                             "fabric_weight": "Ligero", "protects_against": []}}}}


def _error(codigo):
    return errors.APIError(codigo, {"error": {"code": codigo, "message": "x", "status": "X"}})


class ClienteFalso:
    """models.generate_content va devolviendo/lanzando lo que diga `guion` (una lista)."""

    def __init__(self, guion):
        self.guion, self.llamadas = list(guion), []
        self.models = self

    def generate_content(self, model, contents, config):
        self.llamadas.append({"model": model, "config": config, "prompt": contents[1]})
        paso = self.guion.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return SimpleNamespace(text=paso)


@pytest.fixture()
def foto(tmp_path):
    ruta = tmp_path / "camiseta.jpg"
    Image.new("RGB", (1600, 1200), (240, 240, 240)).save(ruta)
    return str(ruta)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr(gs.time, "sleep", lambda s: None)


def servicio(guion, fallback=""):
    s = GeminiService(api_key="x", model="gemini-3.5-flash-lite", fallback=fallback)
    s._client = ClienteFalso(guion)
    return s


def test_respuesta_correcta_y_config_rapida(foto):
    s = servicio([json.dumps(FICHA)])
    assert s.analyze(foto)["garment"]["main_category"] == "Top"
    cfg = s._client.llamadas[0]["config"]
    assert cfg.response_schema is not None                       # salida estructurada
    assert cfg.thinking_config.thinking_level.value == "MINIMAL"  # sin razonamiento largo
    assert cfg.temperature is None                                # 3.x: no se toca la temperatura


def test_modelo_25_desactiva_thinking_con_presupuesto_0(foto):
    s = GeminiService(api_key="x", model="gemini-2.5-flash", fallback="")
    s._client = ClienteFalso([json.dumps(FICHA)])
    s.analyze(foto)
    assert s._client.llamadas[0]["config"].thinking_config.thinking_budget == 0


def test_reintenta_solo_errores_temporales(foto):
    s = servicio([_error(503), _error(429), json.dumps(FICHA)])
    assert s.analyze(foto)
    assert len(s._client.llamadas) == 3


def test_json_roto_se_reintenta(foto):
    s = servicio(["{no es json", json.dumps(FICHA)])
    assert s.analyze(foto)


def test_api_key_mala_no_reintenta_ni_cambia_de_modelo(foto):
    s = servicio([_error(403)], fallback="gemini-3.5-flash")
    with pytest.raises(GeminiError) as e:
        s.analyze(foto)
    assert e.value.fatal and "GEMINI_API_KEY" in str(e.value)
    assert len(s._client.llamadas) == 1


def test_400_degrada_primero_thinking_y_luego_esquema(foto):
    s = servicio([_error(400), _error(400), json.dumps(FICHA)])
    assert s.analyze(foto)
    l = s._client.llamadas
    assert l[0]["config"].thinking_config is not None and l[0]["config"].response_schema is not None
    assert l[1]["config"].thinking_config is None and l[1]["config"].response_schema is not None
    assert l[2]["config"].response_schema is None and "estructura" in l[2]["prompt"]   # plantilla en el prompt


def test_modelo_de_reserva_cuando_el_principal_esta_saturado(foto):
    s = servicio([_error(503)] * 3 + [json.dumps(FICHA)], fallback="gemini-3.5-flash")
    assert s.analyze(foto)
    assert [c["model"] for c in s._client.llamadas] == ["gemini-3.5-flash-lite"] * 3 + ["gemini-3.5-flash"]


def test_modelo_inexistente_pasa_al_de_reserva(foto):
    s = servicio([_error(404), json.dumps(FICHA)], fallback="gemini-3.5-flash")
    assert s.analyze(foto)


def test_si_todo_falla_el_mensaje_es_legible(foto):
    s = servicio([_error(429)] * 3)
    with pytest.raises(GeminiError, match="cuota"):
        s.analyze(foto)


def test_imagen_enviada_es_pequena_y_respeta_exif(tmp_path):
    ruta = tmp_path / "giro.jpg"
    img = Image.new("RGB", (2000, 1000), (200, 10, 10))
    exif = Image.Exif()
    exif[0x0112] = 6                       # "girar 90°": la foto real es vertical
    img.save(ruta, exif=exif)
    datos, mime = gs._preparar_imagen(ruta)
    import io
    salida = Image.open(io.BytesIO(datos))
    assert mime == "image/jpeg" and max(salida.size) <= config.GEMINI_IMG_LADO
    assert salida.size[1] > salida.size[0]  # quedó vertical


def test_gemini_y_embedding_corren_en_paralelo(tmp_path, foto):
    """La prenda tarda ~max(gemini, embedding), no la suma."""
    class Lento:
        def analyze(self, ruta):
            time.sleep(0.4)
            return FICHA

    def embeber(ruta):
        time.sleep(0.4)
        import numpy as np
        return np.ones(4, dtype="float32"), "color-hist"

    db = ArmarioDB(str(tmp_path / "p.db"))
    t0 = time.perf_counter()
    prenda, aviso = procesar_prenda(Lento(), embeber, db, "P1", foto)
    assert time.perf_counter() - t0 < 0.7 and aviso is None and prenda.vector is not None


def test_si_falla_el_embedding_la_prenda_se_guarda_sin_vector(tmp_path, foto):
    class Ok:
        def analyze(self, ruta):
            return FICHA

    def roto(ruta):
        raise RuntimeError("sin torch")

    db = ArmarioDB(str(tmp_path / "q.db"))
    prenda, aviso = procesar_prenda(Ok(), roto, db, "P2", foto)
    assert prenda.vector is None and "sin vector" in aviso
