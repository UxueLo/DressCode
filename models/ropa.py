from __future__ import annotations

import unicodedata
import json
from dataclasses import dataclass, field
from typing import Any, Optional

# --- Vocabulario controlado (se le pasa a Gemini y se valida al crear el objeto) ---
MAIN_CATEGORIES = ["Top", "Bottom", "Dress", "Outerwear", "Footwear"]
PATTERNS = ["Liso", "Rayas", "Cuadros", "Estampado", "Floral", "Otro"]
FIT_TYPES = ["Ajustado", "Regular", "Holgado", "Oversize"]
STYLES = ["Casual", "Streetwear", "Rock", "Elegante", "Formal",
          "Deportivo", "Minimalista", "Vintage", "Boho"]
TEMP_LEVELS = ["Frío", "Fresco", "Templado", "Cálido", "Caluroso"]
FABRIC_WEIGHTS = ["Ligero", "Medio", "Pesado"]
PROTECTIONS = ["Lluvia", "Viento", "Frío", "Sol" ]

# --- Clases para gestion
@dataclass
class Prenda:

    # ---Atributos de la clase
    # Datos que no vienen de Gemini
    tag_id: str     # id de la tarjeta RFID (clave primaria en la BD)
    image_path: str  # nombre del fichero en data/uploads
    in_use: bool = False              # False = en el armario, True = fuera
   
    #Datos principales
    main_category: str
    sub_category: str
   
    #Visuals 
    primary_color: str = "Negro"
    secondary_color: Optional[str] = None
    pattern: str = "Liso"
    fit_type: str = "Regular"
    style_aesthetics: list[str] = field(default_factory=lambda: ["Casual"])
    
    #Context
    formality_level: int = 3
    recommended_events: list[str] = field(default_factory=list)
    
    #Info clima
    temperature_category: str = "Templado"
    fabric_weight: str = "Medio"
    protects_against: list[str] = field(default_factory=list)

    #--Constructor a traves del json
    @classmethod
    def from_json(cls, json_data: str | dict[str, Any], image_path: str, tag_id: str, in_use: bool = False) -> Prenda:
        """
        Construye una instancia de Prenda a partir de un string JSON o un diccionario,
        junto con el path de la imagen y el id de la etiqueta.
        """
        # Si llega como cadena de texto, lo parseamos a diccionario
        if isinstance(json_data, str):
            data = json.loads(json_data)
        else:
            data = json_data

        # Extraemos los bloques principales del JSON
        garment = data.get("garment", data)
        visuals = garment.get("visuals", {})
        context = garment.get("context", {})
        weather = context.get("weather", {})

        return cls(
            main_category=garment["main_category"],
            sub_category=garment["sub_category"],
            tag_id=tag_id,
            image_path=image_path,
            in_use=in_use,
            primary_color=visuals.get("primary_color", "Negro"),
            secondary_color=visuals.get("secondary_color"),
            pattern=visuals.get("pattern", "Liso"),
            fit_type=visuals.get("fit_type", "Regular"),
            style_aesthetics=visuals.get("style_aesthetics", ["Casual"]),
            formality_level=int(context.get("formality_level", 3)),
            recommended_events=context.get("recommended_events", []),
            temperature_category=weather.get("temperature_category", "Templado"),
            fabric_weight=weather.get("fabric_weight", "Medio"),
            protects_against=weather.get("protects_against", [])
        )

    # --Funcion que valida si los valores son validos
    def __post_init__(self) -> None:
        """Valida que los campos pertenezcan al vocabulario controlado."""
        if self.main_category not in MAIN_CATEGORIES:
            raise ValueError(f"main_category inválida: {self.main_category}")
        if self.pattern not in PATTERNS:
            raise ValueError(f"pattern inválido: {self.pattern}")
        if self.fit_type not in FIT_TYPES:
            raise ValueError(f"fit_type inválido: {self.fit_type}")
        if not all(s in STYLES for s in self.style_aesthetics):
            raise ValueError(f"style_aesthetics contiene valores inválidos: {self.style_aesthetics}")
        if self.temperature_category not in TEMP_LEVELS:
            raise ValueError(f"temperature_category inválida: {self.temperature_category}")
        if self.fabric_weight not in FABRIC_WEIGHTS:
            raise ValueError(f"fabric_weight inválido: {self.fabric_weight}")
        if not all(p in PROTECTIONS for p in self.protects_against):
            raise ValueError(f"protects_against contiene valores inválidos: {self.protects_against}")
        if not (1 <= self.formality_level <= 5):
            raise ValueError(f"formality_level debe estar entre 1 y 5, recibido: {self.formality_level}")

@dataclass
class Ouftit:

    # ---Atributos de la clase
    #Elementos
    chaqueta: Prenda
    parte_arriba: Prenda
    parte_abajo: Prenda
    zapatos: Prenda
    complemento: Prenda

    #Extras
    estilo: str
    colorimetria: str
    temporada: str
    formality_level: str

    # ---Constructor
    @classmethod
    def __new__(cls, chaqueta:Prenda, p_arr:Prenda, p_ab:Prenda, zapatos:Prenda, complemento:Prenda):
        cls.chaqueta = chaqueta
        cls.parte_arriba = p_arr
        cls.parte_abajo = p_ab
        cls.zapatos = zapatos
        cls.complemento = complemento

    #TODO hacer que si recibe like se guarda en la BD



