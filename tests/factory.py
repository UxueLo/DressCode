"""Prendas sintéticas para los tests."""
import numpy as np

from models.ropa import Prenda

_n = 0


def prenda(cat="Top", color="Blanco", tmin=5, tmax=30, formal=3, estilos=("Casual",), fit="Regular",
           pattern="Liso", protege=(), vec=None, tag=None, eventos=(), in_use=False, emb="color-hist"):
    global _n
    _n += 1
    return Prenda(tag_id=tag or f"T{_n}", image_path=f"x{_n}.jpg", main_category=cat, sub_category=cat,
                  primary_color=color, temperature_min=tmin, temperature_max=tmax, formality_level=formal,
                  style_aesthetics=list(estilos), fit_type=fit, pattern=pattern,
                  protects_against=list(protege), recommended_events=list(eventos), in_use=in_use,
                  vector=None if vec is None else np.asarray(vec, dtype=np.float32),
                  embedder=emb if vec is not None else None)


def clima(t=18, lluvia=False, viento=False, nieve=False):
    return {"t_ref": t, "rainy": lluvia, "windy": viento, "snowy": nieve, "date": "2026-11-20"}
