"""Modelos de dominio: vocabulario controlado, Prenda y Outfit.

El vocabulario se le pasa a Gemini en el prompt y, además, `Prenda.from_json` lo
"normaliza" (ignora mayúsculas/acentos y corrige erratas leves) para que una respuesta
casi correcta de la IA no tire abajo el registro de una prenda.
"""
from __future__ import annotations

import colorsys
import difflib
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

# ------------------------------------------------------------------ vocabulario
MAIN_CATEGORIES = ["Top", "Bottom", "Dress", "Outerwear", "Footwear", "Accessory"]
PATTERNS = ["Liso", "Rayas", "Cuadros", "Estampado", "Floral", "Animal Print", "Circulos", "Otro"]
FIT_TYPES = ["Compresión", "Ajustado", "Regular", "Holgado", "Oversize", "Recto",
             "Acampanado", "Cropped", "Otro"]
STYLES = ["Casual", "Smart Casual", "Formal", "Elegante / Gala", "Deportivo", "Athleisure",
          "Streetwear", "Minimalista", "Clásico / Atemporal", "Vintage / Retro", "Boho",
          "Romántico", "Preppy", "Rock", "Punk / Grunge", "Gótico", "Workwear / Utilitario", "Otro"]
FABRIC_WEIGHTS = ["Ligero", "Medio", "Pesado"]
PROTECTIONS = ["Lluvia", "Viento", "Frío", "Sol", "Nieve"]

# Colores permitidos -> hex (para calcular el tono y comparar colores entre prendas)
COLORS: dict[str, str] = {
    "Negro": "#151515", "Blanco": "#F5F5F5", "Gris": "#8A8D91", "Beige": "#D9C8A9",
    "Crema": "#F2E8CF", "Marrón": "#6B4423", "Azul marino": "#1F2F54", "Azul": "#2F63C8",
    "Azul claro": "#8DB7E8", "Denim": "#4A6A94", "Verde": "#2E8B57", "Verde oliva": "#6B7230",
    "Caqui": "#A39B6D", "Rojo": "#C0272D", "Burdeos": "#6D1F2F", "Rosa": "#E88CA5",
    "Naranja": "#E8782A", "Amarillo": "#F0C93A", "Morado": "#7B4BA8", "Camel": "#B98A55",
    "Plata": "#C0C3C7", "Dorado": "#C9A24B", "Multicolor": "#999999",
}
NEUTRAL_COLORS = {"Negro", "Blanco", "Gris", "Beige", "Crema", "Marrón", "Azul marino",
                  "Denim", "Plata", "Camel", "Caqui"}

SLOT_POR_CATEGORIA = {"Top": "arriba", "Bottom": "abajo", "Dress": "vestido",
                      "Outerwear": "chaqueta", "Footwear": "zapatos", "Accessory": "complemento"}


def norm(s: Any) -> str:
    """minúsculas y sin acentos: 'Marrón' -> 'marron'."""
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def tono_color(nombre: str) -> float:
    """Tono (0-360°) del color, para medir su diferencia con otro color."""
    h, _, _ = colorsys.rgb_to_hsv(*[int(COLORS[nombre][i:i + 2], 16) / 255 for i in (1, 3, 5)])
    return h * 360


def _ajustar(valor: Any, validos: list[str], defecto: Optional[str] = None) -> Optional[str]:
    """Devuelve el valor del vocabulario que mejor encaja (o `defecto`)."""
    if valor is None:
        return defecto
    mapa = {norm(v): v for v in validos}
    n = norm(valor)
    if n in mapa:
        return mapa[n]
    cerca = difflib.get_close_matches(n, list(mapa), n=1, cutoff=0.75)
    return mapa[cerca[0]] if cerca else defecto


def _lista_ajustada(valores: Any, validos: list[str]) -> list[str]:
    if isinstance(valores, str):
        valores = [valores]
    salida: list[str] = []
    for v in valores or []:
        a = _ajustar(v, validos)
        if a and a not in salida:
            salida.append(a)
    return salida


def _num(valor: Any, defecto: float) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return defecto


# ---------------------------------------------------------------------- Prenda
@dataclass(eq=False)  # eq=False: el vector (ndarray) no se puede comparar con ==
class Prenda:
    # Datos que no vienen de Gemini
    tag_id: str            # id de la etiqueta NFC/RFID (clave primaria)
    image_path: str        # ruta de la foto (data/uploads/...)
    # Datos principales
    main_category: str
    sub_category: str
    in_use: bool = False   # False = en el armario, True = fuera (puesta / lavando...)
    # Visuales
    primary_color: str = "Negro"
    secondary_color: Optional[str] = None
    pattern: str = "Liso"
    fit_type: str = "Regular"
    style_aesthetics: list[str] = field(default_factory=lambda: ["Casual"])
    # Contexto
    formality_level: int = 3
    recommended_events: list[str] = field(default_factory=list)
    # Clima
    temperature_min: float = 5.0
    temperature_max: float = 20.0
    fabric_weight: str = "Medio"
    protects_against: list[str] = field(default_factory=list)
    # Embedding FashionCLIP (normalizado) y modelo que lo generó
    vector: Optional[np.ndarray] = None
    embedder: Optional[str] = None
    created_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.main_category not in MAIN_CATEGORIES:
            raise ValueError(f"main_category inválida: {self.main_category}")
        if self.primary_color not in COLORS:
            raise ValueError(f"primary_color inválido: {self.primary_color}")
        if self.secondary_color is not None and self.secondary_color not in COLORS:
            raise ValueError(f"secondary_color inválido: {self.secondary_color}")
        if self.pattern not in PATTERNS:
            raise ValueError(f"pattern inválido: {self.pattern}")
        if self.fit_type not in FIT_TYPES:
            raise ValueError(f"fit_type inválido: {self.fit_type}")
        if not self.style_aesthetics or not all(s in STYLES for s in self.style_aesthetics):
            raise ValueError(f"style_aesthetics inválido: {self.style_aesthetics}")
        if self.fabric_weight not in FABRIC_WEIGHTS:
            raise ValueError(f"fabric_weight inválido: {self.fabric_weight}")
        if not all(p in PROTECTIONS for p in self.protects_against):
            raise ValueError(f"protects_against inválido: {self.protects_against}")
        if not (1 <= self.formality_level <= 5):
            raise ValueError(f"formality_level debe estar entre 1 y 5: {self.formality_level}")
        if self.temperature_min > self.temperature_max:
            raise ValueError("temperature_min no puede ser mayor que temperature_max")

    # ------------------------------------------------------------ constructores
    @classmethod
    def from_json(cls, json_data: str | dict[str, Any], image_path: str, tag_id: str,
                  in_use: bool = False, vector: Optional[np.ndarray] = None,
                  embedder: Optional[str] = None) -> "Prenda":
        """Construye la prenda desde la respuesta de Gemini (str JSON o dict)."""
        data = json.loads(json_data) if isinstance(json_data, str) else json_data
        garment = data.get("garment", data)
        visuals = garment.get("visuals", {}) or {}
        context = garment.get("context", {}) or {}
        weather = context.get("weather", {}) or {}

        categoria = _ajustar(garment.get("main_category"), MAIN_CATEGORIES)
        if categoria is None:
            raise ValueError(f"main_category inválida: {garment.get('main_category')}")

        t_min = _num(weather.get("temperature_min"), 5.0)
        t_max = _num(weather.get("temperature_max"), 20.0)
        if t_min > t_max:
            t_min, t_max = t_max, t_min

        return cls(
            tag_id=tag_id, image_path=image_path, in_use=in_use,
            main_category=categoria,
            sub_category=str(garment.get("sub_category") or categoria).strip(),
            primary_color=_ajustar(visuals.get("primary_color"), list(COLORS), "Gris"),
            secondary_color=_ajustar(visuals.get("secondary_color"), list(COLORS)),
            pattern=_ajustar(visuals.get("pattern"), PATTERNS, "Liso"),
            fit_type=_ajustar(visuals.get("fit_type"), FIT_TYPES, "Regular"),
            style_aesthetics=_lista_ajustada(visuals.get("style_aesthetics"), STYLES)[:3] or ["Casual"],
            formality_level=int(min(5, max(1, round(_num(context.get("formality_level"), 3))))),
            recommended_events=[str(e).strip() for e in (context.get("recommended_events") or [])][:5],
            temperature_min=max(-30.0, t_min), temperature_max=min(50.0, t_max),
            fabric_weight=_ajustar(weather.get("fabric_weight"), FABRIC_WEIGHTS, "Medio"),
            protects_against=_lista_ajustada(weather.get("protects_against"), PROTECTIONS),
            vector=vector, embedder=embedder,
        )

    # --------------------------------------------------------------- utilidades
    @property
    def disponible(self) -> bool:
        return not self.in_use

    @property
    def nombre(self) -> str:
        return f"{self.sub_category} {self.primary_color.lower()}"

    def to_card(self) -> dict[str, Any]:
        """Representación ligera para la API/UI (sin el vector)."""
        return {
            "tag_id": self.tag_id, "nombre": self.nombre, "categoria": self.main_category,
            "sub_category": self.sub_category, "color": self.primary_color,
            "color_hex": COLORS[self.primary_color], "color_secundario": self.secondary_color,
            "patron": self.pattern, "corte": self.fit_type, "estilos": self.style_aesthetics,
            "formalidad": self.formality_level, "eventos": self.recommended_events,
            "temp_min": self.temperature_min, "temp_max": self.temperature_max,
            "tejido": self.fabric_weight, "protege": self.protects_against,
            "en_uso": self.in_use, "tiene_vector": self.vector is not None,
            "imagen": f"/uploads/{Path(self.image_path).name}",
        }


# ---------------------------------------------------------------------- Outfit
@dataclass
class Outfit:
    prendas: list[Prenda]
    score: float = 0.0
    coherencia: float = 0.0
    afinidad: float = 0.0
    novedad: float = 1.0
    razones: list[str] = field(default_factory=list)
    detalle: dict[str, Any] = field(default_factory=dict)   # sub-puntuaciones para depurar
    evento: Optional[str] = None
    fecha: Optional[str] = None
    estado: str = "sugerido"   # sugerido | guardado | usado | descartado
    id: Optional[int] = None

    @property
    def tag_ids(self) -> list[str]:
        return sorted(p.tag_id for p in self.prendas)

    def por_slot(self) -> dict[str, Prenda]:
        return {SLOT_POR_CATEGORIA[p.main_category]: p for p in self.prendas}

    def to_dict(self) -> dict[str, Any]:
        orden = {c: i for i, c in enumerate(["Outerwear", "Top", "Dress", "Bottom", "Footwear", "Accessory"])}
        return {
            "id": self.id, "estado": self.estado, "evento": self.evento, "fecha": self.fecha,
            "score": self.score, "coherencia": self.coherencia, "afinidad": self.afinidad,
            "novedad": self.novedad, "razones": self.razones, "detalle": self.detalle,
            "prendas": [p.to_card() for p in sorted(self.prendas, key=lambda p: orden[p.main_category])],
        }
