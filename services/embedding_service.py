"""Embeddings de imagen. Todos los vectores salen normalizados (norma 1).

- FashionClipEmbedder: modelo `patrickjohncyh/fashion-clip` (transformers + torch).
- ColorHistEmbedder: histograma HSV de 512 dimensiones. NO entiende de moda; existe solo
  para desarrollar/probar sin descargar ~600 MB (EMBEDDER=color-hist).

Cada vector se guarda con el nombre del embedder que lo generó y nunca se mezclan
vectores de embedders distintos (tienen significados incompatibles).
"""
from __future__ import annotations

import io
import logging
import threading
from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image

import config

log = logging.getLogger(__name__)
Fuente = Union[bytes, str, Path, Image.Image]


def cargar_imagen(fuente: Fuente) -> Image.Image:
    """Abre bytes / ruta / PIL y devuelve la imagen en RGB."""
    if isinstance(fuente, Image.Image):
        img = fuente
    elif isinstance(fuente, (bytes, bytearray)):
        img = Image.open(io.BytesIO(fuente))
    else:
        img = Image.open(fuente)
    return img.convert("RGB")


def _normalizar(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return (m / np.maximum(n, 1e-12)).astype(np.float32)


class ColorHistEmbedder:
    nombre = "color-hist"

    def embed_images(self, imgs: list[Image.Image]) -> np.ndarray:
        salida = []
        for img in imgs:
            hsv = np.asarray(img.resize((64, 64)).convert("HSV"), dtype=np.int32)
            idx = (hsv[..., 0] // 32) * 64 + (hsv[..., 1] // 32) * 8 + (hsv[..., 2] // 32)
            hist = np.bincount(idx.ravel(), minlength=512).astype(np.float32)
            salida.append(np.sqrt(hist / hist.sum()))   # raíz: mejor comportamiento con coseno
        return _normalizar(np.stack(salida))


class FashionClipEmbedder:
    nombre = "fashion-clip"

    def __init__(self, model_id: str = config.FASHIONCLIP_MODEL, device: str | None = None) -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor
        self._torch = torch
        if device is None:
            device = ("cuda" if torch.cuda.is_available()
                      else "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
                      else "cpu")
        self.device = device
        log.info("Cargando %s en %s ...", model_id, device)
        self.model = CLIPModel.from_pretrained(model_id).to(device).eval()
        self.processor = CLIPProcessor.from_pretrained(model_id)

    def embed_images(self, imgs: list[Image.Image]) -> np.ndarray:
        torch = self._torch
        inputs = self.processor(images=imgs, return_tensors="pt").to(self.device)
        with torch.no_grad():
            feats = self.model.get_image_features(**inputs)
        if not isinstance(feats, torch.Tensor):          # versiones nuevas de transformers
            feats = getattr(feats, "pooler_output", feats[0])
        return _normalizar(feats.cpu().numpy())


class Embedder:
    """Fachada: acepta bytes/ruta/PIL y devuelve vectores float32 normalizados."""

    def __init__(self, backend) -> None:
        self._b = backend
        self.nombre: str = backend.nombre

    def embed(self, fuente: Fuente) -> np.ndarray:
        return self._b.embed_images([cargar_imagen(fuente)])[0]

    def embed_many(self, fuentes: list[Fuente]) -> np.ndarray:
        return self._b.embed_images([cargar_imagen(f) for f in fuentes])


_instancia: dict[str, Embedder] = {}
_lock = threading.Lock()


def get_embedder(nombre: str | None = None) -> Embedder:
    """Singleton por proceso (el modelo pesa: se carga una sola vez)."""
    nombre = nombre or config.EMBEDDER
    with _lock:
        if nombre not in _instancia:
            if nombre == "fashion-clip":
                _instancia[nombre] = Embedder(FashionClipEmbedder())
            elif nombre == "color-hist":
                _instancia[nombre] = Embedder(ColorHistEmbedder())
            else:
                raise ValueError(f"EMBEDDER desconocido: {nombre} (usa 'fashion-clip' o 'color-hist')")
        return _instancia[nombre]
