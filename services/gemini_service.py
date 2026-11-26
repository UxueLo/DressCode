"""Envía la foto de una prenda a Gemini y recibe sus características en JSON.

Optimizaciones (la versión inicial tardaba mucho y a veces fallaba sin más):
  * Salida estructurada (`response_schema`, ver gemini_schema.py): JSON siempre válido y con
    valores del vocabulario -> casi no hay reintentos por JSON roto.
  * Razonamiento ("thinking") al mínimo: gemini-2.5-flash piensa por defecto y eso era lo que
    más tardaba para una tarea tan simple como clasificar una prenda.
  * Foto reducida (768 px) y con la orientación EXIF corregida.
  * Timeout propio y reintentos SOLO ante errores temporales (429 / 5xx / red), con jitter.
  * Si el modelo principal falla o está saturado se prueba el de reserva (GEMINI_MODEL_FALLBACK).

`FakeGeminiService` (GEMINI_MODE=fake) deduce una ficha plausible a partir del nombre del
fichero y del color medio de la foto: sirve para probar toda la app sin API key.
"""
from __future__ import annotations

import io
import json
import logging
import random
import re
import threading
import time
from pathlib import Path

import config
from models.ropa import (COLORS, FABRIC_WEIGHTS, FIT_TYPES, MAIN_CATEGORIES, PATTERNS,
                         PROTECTIONS, STYLES, norm)

log = logging.getLogger(__name__)

_PLANTILLA = {"garment": {
    "main_category": f"uno de {MAIN_CATEGORIES}",
    "sub_category": "nombre concreto en español (p. ej. 'Chaqueta de cuero', 'Vaqueros rectos')",
    "visuals": {
        "primary_color": f"uno de {list(COLORS)}",
        "secondary_color": f"uno de {list(COLORS)} o null",
        "pattern": f"uno de {PATTERNS}",
        "fit_type": f"uno de {FIT_TYPES}",
        "style_aesthetics": f"lista de 1 a 3 valores de {STYLES}",
    },
    "context": {
        "formality_level": "entero de 1 (muy informal) a 5 (muy formal)",
        "recommended_events": "lista de 1 a 3 eventos en español (p. ej. 'trabajo', 'universidad', 'cita')",
        "weather": {
            "temperature_min": "número en °C: temperatura ambiente MÍNIMA a la que es cómodo llevarla",
            "temperature_max": "número en °C: temperatura ambiente MÁXIMA a la que es cómodo llevarla",
            "fabric_weight": f"uno de {FABRIC_WEIGHTS}",
            "protects_against": f"lista (puede estar vacía) con valores de {PROTECTIONS}",
        },
    },
}}

# Plantilla en texto: solo se usa si el modelo rechaza el esquema estructurado (modo degradado).
PROMPT_PLANTILLA = ("Cataloga la prenda de la imagen. Responde SOLO con un JSON válido, sin texto extra "
                    "ni markdown, con exactamente esta estructura (sustituye cada descripción por su "
                    "valor; usa SIEMPRE los valores exactos de las listas):\n"
                    + json.dumps(_PLANTILLA, ensure_ascii=False, indent=2))
PROMPT_CORTO = "Cataloga la prenda de esta imagen."

SISTEMA = (
    "Eres un estilista que cataloga las prendas de un armario a partir de una foto. "
    "Analiza SOLO la prenda principal (la más grande o central). Si la foto muestra a una persona "
    "o varias prendas, ignora las demás y describe únicamente la prenda protagonista. "
    "Si la foto viene de internet y tiene fondo, marcas o texto, ignóralos. "
    "Usa siempre valores exactos de las listas permitidas. "
    "sub_category: nombre concreto en español (p. ej. 'Chaqueta de cuero', 'Vaqueros rectos'). "
    "formality_level: entero de 1 (muy informal) a 5 (muy formal). "
    "recommended_events: de 1 a 3 eventos en español (trabajo, universidad, cita, fiesta, deporte...). "
    "temperature_min / temperature_max: rango de temperatura ambiente en °C en el que es cómodo "
    "llevarla (camiseta de algodón ~16-35, jersey grueso ~4-18, abrigo ~-5-12). "
    "style_aesthetics: de 1 a 3 estilos. protects_against: lista vacía si no protege de nada."
)

_TRANSITORIOS = {408, 429, 500, 502, 503, 504}
try:                                           # errores de red/timeout del cliente HTTP del SDK
    import httpx
    _ERRORES_RED: tuple = (httpx.TransportError, TimeoutError, ConnectionError)
except ImportError:  # pragma: no cover
    _ERRORES_RED = (TimeoutError, ConnectionError)


class GeminiError(Exception):
    """`fatal=True`: no tiene sentido reintentar ni probar otro modelo (p. ej. API key mala)."""

    def __init__(self, mensaje: str, fatal: bool = False) -> None:
        super().__init__(mensaje)
        self.fatal = fatal


def _mensaje(e: Exception | None) -> str:
    """Texto corto y entendible para mostrar en la web."""
    codigo = getattr(e, "code", None)
    if codigo == 429:
        return "Gemini rechazó la petición por límite de uso (cuota). Espera un minuto y reinténtalo."
    if codigo in (500, 502, 503, 504):
        return "Gemini está saturado en este momento. Reinténtalo en unos segundos."
    if codigo in (401, 403):
        return "La API key de Gemini no es válida o no tiene permiso. Revisa GEMINI_API_KEY en .env."
    if codigo == 404:
        return "El modelo de Gemini configurado no está disponible para tu cuenta (revisa GEMINI_MODEL)."
    if isinstance(e, _ERRORES_RED):
        return f"No se pudo contactar con Gemini (red o más de {config.GEMINI_TIMEOUT:.0f} s de espera)."
    if isinstance(e, ValueError):
        return f"Gemini devolvió una respuesta que no se pudo leer: {e}"
    return f"Error de Gemini: {str(e)[:200]}"


def _preparar_imagen(path: Path, lado_max: int = config.GEMINI_IMG_LADO) -> tuple[bytes, str]:
    """Reduce la foto (menos tokens y subida más rápida) y la devuelve como JPEG."""
    from PIL import Image, ImageOps
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")   # fotos de móvil giradas
        img.thumbnail((lado_max, lado_max))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def _thinking(modelo: str):
    """Razonamiento mínimo. 2.5 usa `thinking_budget`; la familia 3.x usa `thinking_level`."""
    from google.genai import types
    m = modelo.lower()
    if m.startswith("gemini-2.5"):
        return types.ThinkingConfig(thinking_budget=0)
    if m.startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level="minimal")
    return None


def _parsear(resp) -> dict:
    texto = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.M).strip()
    if not texto:
        raise ValueError("respuesta vacía (¿bloqueada por los filtros del modelo?)")
    data = json.loads(texto)
    if not isinstance(data, dict) or not ("garment" in data or "main_category" in data):
        raise ValueError("el JSON no tiene la clave 'garment'")
    return data


class GeminiService:
    def __init__(self, api_key: str = config.GEMINI_API_KEY, model: str = config.GEMINI_MODEL,
                 fallback: str = config.GEMINI_MODEL_FALLBACK):
        self._api_key, self._model, self._fallback = api_key, model, fallback
        self._client = None  # creación perezosa: la app arranca aunque falte la clave
        self._lock = threading.Lock()

    def _get_client(self):
        with self._lock:                       # el worker llama desde varios hilos
            if self._client is None:
                if not self._api_key:
                    raise GeminiError("Falta GEMINI_API_KEY en el fichero .env (o usa GEMINI_MODE=fake)",
                                      fatal=True)
                from google import genai
                from google.genai import types
                self._client = genai.Client(api_key=self._api_key, http_options=types.HttpOptions(
                    timeout=int(config.GEMINI_TIMEOUT * 1000)))   # ms; sin esto una llamada colgada no acaba
            return self._client

    def _config(self, modelo: str, thinking: bool, schema: bool):
        from google.genai import types
        kw: dict = {"response_mime_type": "application/json", "system_instruction": SISTEMA,
                    "max_output_tokens": 2048}
        if schema:
            from services.gemini_schema import FichaPrenda
            kw["response_schema"] = FichaPrenda
        if not modelo.lower().startswith("gemini-3"):   # en 3.x no se recomienda tocar la temperatura
            kw["temperature"] = 0.2
        if thinking and (tc := _thinking(modelo)) is not None:
            kw["thinking_config"] = tc
        return types.GenerateContentConfig(**kw)

    def analyze(self, image_path: str, retries: int = 3) -> dict:
        datos, mime = _preparar_imagen(Path(image_path))
        modelos = list(dict.fromkeys(m for m in (self._model, self._fallback) if m))
        ultimo: GeminiError | None = None
        for i, modelo in enumerate(modelos):
            try:
                return self._analizar(modelo, datos, mime, retries)
            except GeminiError as e:
                if e.fatal:
                    raise
                ultimo = e
                if i + 1 < len(modelos):
                    log.warning("%s falló (%s); pruebo con %s", modelo, e, modelos[i + 1])
        raise ultimo  # type: ignore[misc]

    def _analizar(self, modelo: str, datos: bytes, mime: str, retries: int) -> dict:
        from google.genai import errors, types
        cliente = self._get_client()
        imagen = types.Part.from_bytes(data=datos, mime_type=mime)
        thinking, schema = True, True            # se desactivan si el modelo las rechaza (HTTP 400)
        intento, ultimo = 0, None
        while intento < retries:
            try:
                t0 = time.perf_counter()
                resp = cliente.models.generate_content(
                    model=modelo, contents=[imagen, PROMPT_CORTO if schema else PROMPT_PLANTILLA],
                    config=self._config(modelo, thinking, schema))
                data = _parsear(resp)
                log.info("Gemini %s respondió en %.1f s", modelo, time.perf_counter() - t0)
                return data
            except errors.APIError as e:
                ultimo = e
                if e.code in (401, 403):
                    raise GeminiError(_mensaje(e), fatal=True) from e
                if e.code == 400:                # parámetro no soportado por este modelo: se degrada
                    if thinking and _thinking(modelo) is not None:
                        thinking = False
                        log.warning("%s rechazó la config de thinking; reintento sin ella", modelo)
                        continue                 # no gasta intento
                    if schema:
                        schema = False
                        log.warning("%s rechazó el esquema; reintento con plantilla en el prompt", modelo)
                        continue
                    raise GeminiError(_mensaje(e)) from e
                if e.code not in _TRANSITORIOS:   # 404 u otros: no se reintenta con este modelo
                    raise GeminiError(_mensaje(e)) from e
            except (ValueError, *_ERRORES_RED) as e:      # JSON roto / respuesta vacía / red
                ultimo = e
            log.warning("Gemini (%s) intento %d/%d falló: %s", modelo, intento + 1, retries, ultimo)
            intento += 1
            if intento < retries:
                time.sleep(min(8.0, 1.5 ** intento + random.random()))   # backoff con jitter
        raise GeminiError(_mensaje(ultimo))


def get_gemini_service():
    return GeminiService()
