"""Esquema de la ficha de una prenda para la salida estructurada de Gemini.

Con `response_schema` Gemini devuelve siempre un JSON válido y solo con valores del
vocabulario (categorías, colores, estilos...), así que casi desaparecen los errores de
"JSON mal formado" y los reintentos. El módulo NO usa `from __future__ import annotations`
a propósito: pydantic necesita resolver los tipos en tiempo de definición.
"""
from typing import Literal, Optional

from pydantic import BaseModel

from models.ropa import (COLORS, FABRIC_WEIGHTS, FIT_TYPES, MAIN_CATEGORIES, PATTERNS,
                         PROTECTIONS, STYLES)

Categoria = Literal[tuple(MAIN_CATEGORIES)]
Color = Literal[tuple(COLORS)]
Patron = Literal[tuple(PATTERNS)]
Corte = Literal[tuple(FIT_TYPES)]
Estilo = Literal[tuple(STYLES)]
Peso = Literal[tuple(FABRIC_WEIGHTS)]
Proteccion = Literal[tuple(PROTECTIONS)]


class Clima(BaseModel):
    temperature_min: float
    temperature_max: float
    fabric_weight: Peso
    protects_against: list[Proteccion]


class Contexto(BaseModel):
    formality_level: int
    recommended_events: list[str]
    weather: Clima


class Visuales(BaseModel):
    primary_color: Color
    secondary_color: Optional[Color] = None
    pattern: Patron
    fit_type: Corte
    style_aesthetics: list[Estilo]


class Prenda(BaseModel):
    main_category: Categoria
    sub_category: str
    visuals: Visuales
    context: Contexto


class FichaPrenda(BaseModel):
    garment: Prenda
