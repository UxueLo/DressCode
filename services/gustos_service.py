"""Perfil de gusto: vector = media(likes) - PESO_DISLIKE * media(dislikes).

Los swipes sobre fotos (Pinterest/otras) y el feedback sobre outfits propios se guardan con
su vector FashionCLIP. Aquí se combinan en un único "vector de gusto" con el que luego se
compara (coseno) cada outfit candidato.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

import config
from models.ropa import Prenda


def _unit(v: np.ndarray) -> Optional[np.ndarray]:
    n = float(np.linalg.norm(v))
    return None if n < 1e-9 else (v / n).astype(np.float32)


def vector_medio(vectores: list[np.ndarray], pesos: Optional[list[float]] = None) -> Optional[np.ndarray]:
    """Media ponderada normalizada (None si no hay vectores)."""
    if not vectores:
        return None
    m = np.average(np.stack(vectores), axis=0, weights=pesos if pesos else None)
    return _unit(m)


def coseno(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> Optional[float]:
    if a is None or b is None or a.shape != b.shape:
        return None
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def vector_outfit(prendas: Iterable[Prenda], embedder: str) -> Optional[np.ndarray]:
    """Vector de un outfit = media de los vectores de sus prendas (solo del mismo embedder)."""
    vs = [p.vector for p in prendas if p.vector is not None and p.embedder == embedder]
    return vector_medio(vs)


@dataclass
class PerfilGusto:
    vector: Optional[np.ndarray] = None          # likes - w * dislikes (normalizado)
    media_likes: Optional[np.ndarray] = None
    media_dislikes: Optional[np.ndarray] = None
    n_likes: int = 0
    n_dislikes: int = 0
    embedder: str = ""

    @property
    def conocido(self) -> bool:
        """¿Hay suficientes swipes para fiarse del perfil? (si no, afinidad neutra)"""
        return self.vector is not None and (self.n_likes + self.n_dislikes) >= config.MIN_SWIPES

    def similitud(self, v: Optional[np.ndarray]) -> Optional[float]:
        return coseno(v, self.vector)

    def resumen(self) -> dict:
        return {"likes": self.n_likes, "dislikes": self.n_dislikes, "conocido": self.conocido,
                "min_swipes": config.MIN_SWIPES}


def calcular_perfil(db, embedder: str = config.EMBEDDER) -> PerfilGusto:
    """Lee los swipes de la BD y construye el perfil (ignora vectores de otros embedders)."""
    swipes = db.obtener_swipes(embedder)
    likes = [s for s in swipes if s["liked"]]
    dislikes = [s for s in swipes if not s["liked"]]
    ml = vector_medio([s["vector"] for s in likes], [s["peso"] for s in likes])
    md = vector_medio([s["vector"] for s in dislikes], [s["peso"] for s in dislikes])

    combinado: Optional[np.ndarray] = None
    if ml is not None:
        combinado = config.PESO_LIKE * ml
    if md is not None:
        combinado = (-config.PESO_DISLIKE * md) if combinado is None else combinado - config.PESO_DISLIKE * md
    return PerfilGusto(vector=None if combinado is None else _unit(combinado),
                       media_likes=ml, media_dislikes=md, n_likes=len(likes),
                       n_dislikes=len(dislikes), embedder=embedder)
