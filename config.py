"""Configuración central de DressCode.

Todo lo "ajustable" vive aquí: rutas, claves (vía .env) y los pesos del algoritmo
descrito en DECISION_DE_OUFITS.pdf. Así se puede afinar sin tocar la lógica.
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv es opcional: si no está, se usan las variables de entorno
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent


def _env(nombre: str, defecto: str = "") -> str:
    return os.getenv(nombre, defecto).strip()


# --------------------------------------------------------------------- rutas
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"            # fotos de las prendas del armario
INSPIRATION_DIR = DATA_DIR / "inspiration"   # fotos locales para el swipe
DB_PATH = str(DATA_DIR / "armario.db")

# ----------------------------------------------------------------- servicios
GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MODE = _env("GEMINI_MODE", "real")    # "real" | "fake" (demo sin API key)

# "fashion-clip" (patrickjohncyh/fashion-clip) | "color-hist" (ligero, solo pruebas/demo)
EMBEDDER = _env("EMBEDDER", "fashion-clip")
FASHIONCLIP_MODEL = _env("FASHIONCLIP_MODEL", "patrickjohncyh/fashion-clip")

CIUDAD_POR_DEFECTO = _env("CIUDAD", "Bilbao")

# Fuentes de fotos para el swipe: local, pinterest, unsplash (separadas por comas)
FEED_SOURCES = [s.strip() for s in _env("FEED_SOURCES", "local").split(",") if s.strip()]
PINTEREST_TOKEN = _env("PINTEREST_TOKEN")
PINTEREST_BOARD_IDS = [s.strip() for s in _env("PINTEREST_BOARD_IDS").split(",") if s.strip()]
UNSPLASH_ACCESS_KEY = _env("UNSPLASH_ACCESS_KEY")
UNSPLASH_QUERIES = [s.strip() for s in _env(
    "UNSPLASH_QUERIES",
    "street style outfit,smart casual outfit,minimalist outfit,vintage outfit,"
    "casual outfit men women,elegant outfit,sporty outfit").split(",") if s.strip()]

WEB_HOST = _env("WEB_HOST", "127.0.0.1")
WEB_PORT = int(_env("WEB_PORT", "5000"))

# -------------------------------------------- pesos del documento (ScoreTotal)
W_COHERENCIA = 0.4
W_AFINIDAD = 0.4
W_NOVEDAD = 0.2

# Coherencia = (1 - W_CONTEXTO) * estética + W_CONTEXTO * contexto (clima + evento)
W_CONTEXTO = 0.20
# Estética = suma ponderada de reglas (color, formalidad, estilo, estampados, proporciones)
W_ESTETICA = {"color": 0.32, "formalidad": 0.22, "estilo": 0.22, "estampados": 0.12, "proporcion": 0.12}

# ------------------------------------------------------------- gustos (swipe)
PESO_LIKE = 1.0
PESO_DISLIKE = 0.5          # "CUENTA MENOS": el vector de dislikes resta con la mitad de fuerza
PESO_FEEDBACK_OUTFIT = 1.5  # like/dislike sobre un outfit real de tu armario pesa más que un pin
MIN_SWIPES = 8              # por debajo, la afinidad es neutra (0.5) para no inventar gustos
DISLIKE_PENAL_ESCALA = 5.0  # penalización si el outfit se parece más a los dislikes que a los likes
DISLIKE_PENAL_MAX = 0.4

# ----------------------------------------------------------- selección outfits
OUTFITS_POR_PETICION = 3
SOCIOS_POR_SLOT = 5         # por cada ancla se prueban los N mejores socios por color/formalidad
MAX_DIF_FORMALIDAD = 2      # diferencia de formalidad máxima entre ancla y socio
TOLERANCIAS_TEMP = (0.0, 3.0, 6.0)   # °C extra que se admiten si una categoría se queda sin prendas
T_CHAQUETA_OBLIGATORIA = 14.0        # por debajo: chaqueta sí o sí (si hay)
T_CHAQUETA_OPCIONAL = 20.0           # entre ambos umbrales se prueban ambas opciones
NOVEDAD_DIAS = 14           # ventana para penalizar outfits repetidos

# Eventos: rango de formalidad (1-5), estilos afines y palabras clave que se buscan en
# los "recommended_events" que Gemini asignó a cada prenda.
EVENTOS: dict[str, dict] = {
    "casual":      {"nombre": "Día a día / casual", "formalidad": (1, 3),
                    "estilos": ["Casual", "Streetwear", "Smart Casual", "Minimalista"],
                    "claves": ["casual", "diario", "paseo", "amigos", "compras"]},
    "universidad": {"nombre": "Universidad / clase", "formalidad": (1, 3),
                    "estilos": ["Casual", "Streetwear", "Smart Casual", "Athleisure"],
                    "claves": ["universidad", "clase", "estudio", "casual", "diario"]},
    "trabajo":     {"nombre": "Trabajo / oficina", "formalidad": (3, 4),
                    "estilos": ["Smart Casual", "Formal", "Clásico / Atemporal", "Minimalista"],
                    "claves": ["trabajo", "oficina", "reunion", "profesional"]},
    "entrevista":  {"nombre": "Entrevista / reunión importante", "formalidad": (4, 5),
                    "estilos": ["Formal", "Clásico / Atemporal", "Elegante / Gala", "Smart Casual"],
                    "claves": ["entrevista", "formal", "reunion", "trabajo"]},
    "cita":        {"nombre": "Cita / cena", "formalidad": (3, 4),
                    "estilos": ["Smart Casual", "Elegante / Gala", "Romántico", "Clásico / Atemporal"],
                    "claves": ["cita", "cena", "restaurante", "romantic"]},
    "fiesta":      {"nombre": "Fiesta / salir de noche", "formalidad": (2, 5),
                    "estilos": ["Elegante / Gala", "Streetwear", "Rock", "Romántico", "Smart Casual"],
                    "claves": ["fiesta", "noche", "salir", "copas", "discoteca"]},
    "boda":        {"nombre": "Boda / evento formal", "formalidad": (4, 5),
                    "estilos": ["Elegante / Gala", "Formal", "Clásico / Atemporal"],
                    "claves": ["boda", "gala", "ceremonia", "formal", "evento"]},
    "deporte":     {"nombre": "Deporte", "formalidad": (1, 2),
                    "estilos": ["Deportivo", "Athleisure"],
                    "claves": ["deporte", "gimnasio", "correr", "entrenamiento", "gym"]},
    "viaje":       {"nombre": "Viaje / cómodo", "formalidad": (1, 3),
                    "estilos": ["Casual", "Athleisure", "Minimalista"],
                    "claves": ["viaje", "aeropuerto", "turismo", "casual"]},
}
