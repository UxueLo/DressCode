"""Envía la foto de una prenda a Gemini y recibe sus características en JSON."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
from pathlib import Path

import config
from models.garment import (FABRIC_WEIGHTS, FIT_TYPES, MAIN_CATEGORIES, PATTERNS,
                            STYLES, TEMP_LEVELS)

log = logging.getLogger(__name__)

PROMPT = f"""Analiza la prenda de ropa de la imagen y responde SOLO con un JSON válido, sin texto extra,
con exactamente esta estructura:
{{"garment": {{
  "main_category": uno de {MAIN_CATEGORIES},
  "sub_category": "nombre concreto en español (p. ej. Chaqueta de Cuero)",
  "visuals": {{
    "primary_color": "color principal en español",
    "secondary_color": "color secundario en español o null",
    "pattern": uno de {PATTERNS},
    "fit_type": uno de {FIT_TYPES},
    "style_aesthetics": lista de 1 a 3 valores de {STYLES}
  }},
  "context": {{
    "formality_level": entero de 1 (muy informal) a 5 (muy formal),
    "recommended_events": lista de 1 a 3 eventos en español,
    "weather": {{
      "temperature_category": uno de {TEMP_LEVELS},
      "fabric_weight": uno de {FABRIC_WEIGHTS},
      "protects_against": lista que puede contener "Lluvia", "Viento", "Frío", "Sol" (o vacía)
    }}
  }}
}}}}"""


class GeminiError(Exception):
    pass


class GeminiService:
    def __init__(self, api_key: str = config.GEMINI_API_KEY, model: str = config.GEMINI_MODEL):
        self._api_key, self._model = api_key, model
        self._client = None  # creación perezosa: la app arranca aunque falte la clave

    def _get_client(self):
        if self._client is None:
            if not self._api_key:
                raise GeminiError("Falta GEMINI_API_KEY en el fichero .env")
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def analyze(self, image_path: str, retries: int = 2) -> dict:
        from google.genai import types
        path = Path(image_path)
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        image = types.Part.from_bytes(data=path.read_bytes(), mime_type=mime)

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                resp = self._get_client().models.generate_content(
                    model=self._model,
                    contents=[image, PROMPT],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json", temperature=0.2),
                )
                text = re.sub(r"^```(?:json)?|```$", "", resp.text.strip(), flags=re.M).strip()
                return json.loads(text)
            except GeminiError:
                raise
            except Exception as e:  # red, cuota, JSON mal formado...
                last_error = e
                log.warning("Gemini intento %d/%d falló: %s", attempt, retries, e)
        raise GeminiError(f"Gemini no devolvió un JSON válido: {last_error}")
