"""Envía la foto de una prenda a Gemini y recibe sus características en JSON.

`FakeGeminiService` (GEMINI_MODE=fake) deduce una ficha plausible a partir del nombre del
fichero y del color medio de la foto: sirve para probar toda la app sin API key.
"""
from __future__ import annotations

import io
import json
import logging
import re
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

PROMPT = ("Analiza la prenda de ropa de la imagen. Responde SOLO con un JSON válido, sin texto extra "
          "ni markdown, con exactamente esta estructura (sustituye cada descripción por su valor; "
          "usa SIEMPRE los valores exactos de las listas):\n"
          + json.dumps(_PLANTILLA, ensure_ascii=False, indent=2))


class GeminiError(Exception):
    pass


def _preparar_imagen(path: Path, lado_max: int = 1024) -> tuple[bytes, str]:
    """Reduce la foto (menos tokens y subida más rápida) y la devuelve como JPEG."""
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((lado_max, lado_max))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"


class GeminiService:
    def __init__(self, api_key: str = config.GEMINI_API_KEY, model: str = config.GEMINI_MODEL):
        self._api_key, self._model = api_key, model
        self._client = None  # creación perezosa: la app arranca aunque falte la clave

    def _get_client(self):
        if self._client is None:
            if not self._api_key:
                raise GeminiError("Falta GEMINI_API_KEY en el fichero .env (o usa GEMINI_MODE=fake)")
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def analyze(self, image_path: str, retries: int = 3) -> dict:
        from google.genai import types
        datos, mime = _preparar_imagen(Path(image_path))
        imagen = types.Part.from_bytes(data=datos, mime_type=mime)

        ultimo_error: Exception | None = None
        for intento in range(1, retries + 1):
            try:
                resp = self._get_client().models.generate_content(
                    model=self._model, contents=[imagen, PROMPT],
                    config=types.GenerateContentConfig(response_mime_type="application/json",
                                                       temperature=0.2))
                texto = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.M).strip()
                data = json.loads(texto)
                if not isinstance(data, dict) or "garment" not in data and "main_category" not in data:
                    raise ValueError("JSON sin la clave 'garment'")
                return data
            except GeminiError:
                raise
            except Exception as e:  # red, cuota, JSON mal formado...
                ultimo_error = e
                log.warning("Gemini intento %d/%d falló: %s", intento, retries, e)
                if intento < retries:
                    time.sleep(2 ** intento)   # backoff: 2 s, 4 s...
        raise GeminiError(f"Gemini no devolvió un JSON válido: {ultimo_error}")


class FakeGeminiService:
    """Sustituto sin red para demo/tests."""

    _PISTAS = [  # (palabras en el nombre del fichero, categoría, subcategoría, formalidad, t_min, t_max, peso)
        (("camiseta", "tshirt", "top"), "Top", "Camiseta", 2, 16, 35, "Ligero"),
        (("camisa", "shirt"), "Top", "Camisa", 4, 12, 30, "Ligero"),
        (("jersey", "sudadera", "sweater"), "Top", "Jersey", 2, 4, 18, "Pesado"),
        (("pantalon", "vaquero", "jean", "pants"), "Bottom", "Pantalón", 3, 5, 28, "Medio"),
        (("falda", "skirt"), "Bottom", "Falda", 3, 14, 32, "Ligero"),
        (("vestido", "dress"), "Dress", "Vestido", 4, 15, 34, "Ligero"),
        (("chaqueta", "abrigo", "coat", "jacket"), "Outerwear", "Chaqueta", 3, -5, 17, "Pesado"),
        (("zapat", "bota", "shoe", "sneaker", "zapatilla"), "Footwear", "Zapatillas", 2, -5, 35, "Medio"),
        (("bolso", "gorro", "bufanda", "cinturon", "bag"), "Accessory", "Complemento", 3, -5, 35, "Ligero"),
    ]

    def analyze(self, image_path: str, retries: int = 1) -> dict:
        from PIL import Image
        nombre = norm(Path(image_path).stem)
        pista = next((p for p in self._PISTAS if any(k in nombre for k in p[0])), self._PISTAS[0])
        _, cat, sub, formal, tmin, tmax, peso = pista
        with Image.open(image_path) as img:
            r, g, b = img.convert("RGB").resize((1, 1)).getpixel((0, 0))

        def distancia(hexa: str) -> int:
            return sum((int(hexa[i:i + 2], 16) - c) ** 2 for i, c in zip((1, 3, 5), (r, g, b)))
        color = min((c for c in COLORS if c != "Multicolor"), key=lambda c: distancia(COLORS[c]))
        proteccion = ["Lluvia", "Viento"] if cat == "Outerwear" else []
        return {"garment": {
            "main_category": cat, "sub_category": sub,
            "visuals": {"primary_color": color, "secondary_color": None, "pattern": "Liso",
                        "fit_type": "Regular", "style_aesthetics": ["Casual"] if formal <= 3 else ["Smart Casual"]},
            "context": {"formality_level": formal, "recommended_events": ["casual"] if formal <= 3 else ["trabajo"],
                        "weather": {"temperature_min": tmin, "temperature_max": tmax,
                                    "fabric_weight": peso, "protects_against": proteccion}}}}


def get_gemini_service():
    return FakeGeminiService() if config.GEMINI_MODE == "fake" else GeminiService()
