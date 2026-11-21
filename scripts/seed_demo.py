"""Datos de demostración para probar DressCode sin hardware ni API keys.

    python scripts/seed_demo.py            # (con EMBEDDER=color-hist para no descargar FashionCLIP)

Crea 16 prendas de ejemplo (dibujos simples) y 24 "fotos de inspiración" abstractas en
data/inspiration/. Con fotos reales de Pinterest en esa carpeta el swipe funciona igual.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

import config  # noqa: E402
from database.db import ArmarioDB  # noqa: E402
from models.ropa import COLORS, Prenda  # noqa: E402
from services.embedding_service import get_embedder  # noqa: E402

# (tag, categoría, subcategoría, color, formalidad, t_min, t_max, estilos, corte, protege, eventos)
DEMO = [
    ("D-CAM-BL", "Top", "Camiseta básica", "Blanco", 2, 14, 35, ["Casual", "Minimalista"], "Regular", [], ["casual", "universidad"]),
    ("D-CAM-NG", "Top", "Camiseta oversize", "Negro", 2, 14, 35, ["Streetwear", "Casual"], "Oversize", [], ["casual", "fiesta"]),
    ("D-CAMISA", "Top", "Camisa de algodón", "Azul claro", 4, 10, 30, ["Smart Casual", "Clásico / Atemporal"], "Regular", [], ["trabajo", "cita"]),
    ("D-JERSEY", "Top", "Jersey de punto", "Gris", 3, 2, 17, ["Casual", "Minimalista"], "Regular", ["Frío"], ["casual", "trabajo"]),
    ("D-SUDA", "Top", "Sudadera con capucha", "Azul marino", 1, 3, 18, ["Streetwear", "Casual"], "Holgado", ["Frío"], ["casual", "universidad"]),
    ("D-VAQ", "Bottom", "Vaqueros rectos", "Denim", 2, 0, 28, ["Casual"], "Recto", [], ["casual", "universidad"]),
    ("D-PANT-NG", "Bottom", "Pantalón de vestir", "Negro", 4, 0, 30, ["Smart Casual", "Formal"], "Ajustado", [], ["trabajo", "entrevista", "cita"]),
    ("D-CHINO", "Bottom", "Chinos", "Beige", 3, 8, 30, ["Smart Casual", "Preppy"], "Regular", [], ["trabajo", "casual"]),
    ("D-ANCHO", "Bottom", "Pantalón ancho", "Beige", 2, 8, 30, ["Streetwear", "Minimalista"], "Holgado", [], ["casual", "fiesta"]),
    ("D-CAZ-VAQ", "Outerwear", "Cazadora vaquera", "Denim", 2, 10, 20, ["Casual", "Vintage / Retro"], "Regular", ["Viento"], ["casual"]),
    ("D-ABRIGO", "Outerwear", "Abrigo largo", "Negro", 4, -5, 14, ["Clásico / Atemporal", "Elegante / Gala"], "Regular", ["Frío", "Lluvia", "Viento"], ["trabajo", "cita"]),
    ("D-GABA", "Outerwear", "Gabardina", "Camel", 4, 6, 18, ["Clásico / Atemporal", "Smart Casual"], "Regular", ["Lluvia", "Viento"], ["trabajo", "cita"]),
    ("D-ZAPAS", "Footwear", "Zapatillas blancas", "Blanco", 2, -5, 32, ["Casual", "Streetwear"], "Regular", [], ["casual", "universidad"]),
    ("D-BOTAS", "Footwear", "Botas impermeables", "Marrón", 3, -5, 18, ["Casual", "Workwear / Utilitario"], "Regular", ["Lluvia", "Nieve"], ["casual", "viaje"]),
    ("D-ZAPATOS", "Footwear", "Zapatos de piel", "Negro", 5, 0, 32, ["Formal", "Clásico / Atemporal"], "Regular", [], ["trabajo", "entrevista", "boda"]),
    ("D-BUFANDA", "Accessory", "Bufanda de lana", "Gris", 3, -5, 11, ["Casual", "Minimalista"], "Regular", ["Frío"], ["casual"]),
]


def dibujar_prenda(cat: str, hexa: str, ruta: Path) -> None:
    img = Image.new("RGB", (480, 600), "#EDEFF2")
    d = ImageDraw.Draw(img)
    c = hexa
    if cat == "Top":
        d.polygon([(130, 120), (210, 90), (270, 90), (350, 120), (430, 220), (370, 260), (350, 220),
                   (350, 500), (130, 500), (130, 220), (110, 260), (50, 220)], fill=c)
    elif cat == "Outerwear":
        d.polygon([(120, 100), (210, 80), (270, 80), (360, 100), (440, 230), (430, 540), (350, 540),
                   (350, 260), (130, 260), (130, 540), (50, 540), (40, 230)], fill=c)
        d.line([(240, 85), (240, 540)], fill="#00000055", width=4)
    elif cat == "Bottom":
        d.polygon([(130, 80), (350, 80), (370, 540), (270, 540), (240, 240), (210, 540), (110, 540)], fill=c)
    elif cat == "Footwear":
        d.rounded_rectangle([90, 330, 400, 460], 50, fill=c)
        d.rectangle([90, 440, 400, 470], fill="#222222")
    else:
        d.ellipse([140, 190, 340, 390], fill=c)
    img.save(ruta, "JPEG", quality=90)


def crear_inspiracion(n: int = 24) -> None:
    rnd = random.Random(7)
    paletas = [("Blanco", "Denim", "Blanco"), ("Negro", "Negro", "Negro"), ("Beige", "Crema", "Marrón"),
               ("Azul marino", "Beige", "Blanco"), ("Gris", "Negro", "Blanco"), ("Rojo", "Negro", "Negro"),
               ("Verde oliva", "Caqui", "Marrón"), ("Rosa", "Blanco", "Plata")]
    for i in range(n):
        arriba, abajo, zapato = paletas[i % len(paletas)]
        img = Image.new("RGB", (480, 720), COLORS[rnd.choice(["Gris", "Crema", "Blanco"])])
        d = ImageDraw.Draw(img)
        d.rectangle([140, 90, 340, 360], fill=COLORS[arriba])
        d.rectangle([150, 360, 330, 640], fill=COLORS[abajo])
        d.rectangle([140, 640, 340, 690], fill=COLORS[zapato])
        img.save(config.INSPIRATION_DIR / f"demo_{i:02d}.jpg", "JPEG", quality=88)


def main() -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.INSPIRATION_DIR.mkdir(parents=True, exist_ok=True)
    db, emb = ArmarioDB(), get_embedder()
    for tag, cat, sub, color, formal, tmin, tmax, estilos, corte, protege, eventos in DEMO:
        ruta = config.UPLOAD_DIR / f"{tag}.jpg"
        dibujar_prenda(cat, COLORS[color], ruta)
        db.guardar_prenda(Prenda(
            tag_id=tag, image_path=str(ruta), main_category=cat, sub_category=sub, primary_color=color,
            formality_level=formal, temperature_min=tmin, temperature_max=tmax, style_aesthetics=estilos,
            fit_type=corte, protects_against=protege, recommended_events=eventos,
            fabric_weight="Pesado" if tmax < 20 else "Ligero", vector=emb.embed(ruta), embedder=emb.nombre))
    crear_inspiracion()
    print(f"{len(DEMO)} prendas de demo y 24 fotos de inspiración creadas en {config.DATA_DIR}")


if __name__ == "__main__":
    main()
