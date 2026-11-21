"""Fuentes de fotos para el swipe tipo Tinder.

- local:     imágenes que tú copies en data/inspiration/ (por ejemplo pines guardados de Pinterest).
- pinterest: API oficial v5 (necesita PINTEREST_TOKEN y PINTEREST_BOARD_IDS de tus tableros).
- unsplash:  API oficial de Unsplash (necesita UNSPLASH_ACCESS_KEY, gratuita).

No se hace scraping de Pinterest: va contra sus condiciones de uso. El navegador solo conoce
el `ref` de cada foto; la descarga la hace el servidor a partir de una URL que él mismo
sirvió antes (evita que alguien le haga pedir URLs arbitrarias).
"""
from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Optional

import requests

import config

log = logging.getLogger(__name__)
EXT_IMG = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 8 * 1024 * 1024


class FeedError(Exception):
    pass


class _Local:
    nombre = "local"

    def candidatos(self, n: int) -> list[dict]:
        ficheros = sorted(f for f in config.INSPIRATION_DIR.glob("*") if f.suffix.lower() in EXT_IMG)
        return [{"ref": f"local:{f.name}", "url": f"/inspiration/{f.name}", "fuente": "local",
                 "_origen": str(f)} for f in ficheros]


class _Pinterest:
    nombre = "pinterest"

    def __init__(self) -> None:
        self._cola: list[dict] = []
        self._bookmark: dict[str, Optional[str]] = {b: "" for b in config.PINTEREST_BOARD_IDS}

    def _rellenar(self) -> None:
        for board, bookmark in list(self._bookmark.items()):
            if bookmark is None:        # tablero agotado
                continue
            params = {"page_size": 50, **({"bookmark": bookmark} if bookmark else {})}
            try:
                r = requests.get(f"https://api.pinterest.com/v5/boards/{board}/pins", params=params,
                                 headers={"Authorization": f"Bearer {config.PINTEREST_TOKEN}"}, timeout=10)
                r.raise_for_status()
            except requests.RequestException as e:
                log.warning("Pinterest (%s): %s", board, e)
                continue
            datos = r.json()
            self._bookmark[board] = datos.get("bookmark")
            for pin in datos.get("items", []):
                imgs = ((pin.get("media") or {}).get("images")) or {}
                url = next((imgs[k]["url"] for k in ("600x", "400x300", "1200x", "originals") if k in imgs), None)
                if url:
                    self._cola.append({"ref": f"pin:{pin['id']}", "url": url, "fuente": "pinterest",
                                       "_origen": url})

    def candidatos(self, n: int) -> list[dict]:
        if not config.PINTEREST_TOKEN or not config.PINTEREST_BOARD_IDS:
            return []
        if len(self._cola) < n:
            self._rellenar()
        salida, self._cola = self._cola[:n * 3], self._cola[n * 3:]
        return salida


class _Unsplash:
    nombre = "unsplash"

    def candidatos(self, n: int) -> list[dict]:
        if not config.UNSPLASH_ACCESS_KEY:
            return []
        try:
            r = requests.get("https://api.unsplash.com/search/photos", timeout=10,
                             headers={"Authorization": f"Client-ID {config.UNSPLASH_ACCESS_KEY}"},
                             params={"query": random.choice(config.UNSPLASH_QUERIES),
                                     "per_page": 30, "page": random.randint(1, 5), "orientation": "portrait"})
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Unsplash: %s", e)
            return []
        return [{"ref": f"unsplash:{f['id']}", "url": f["urls"]["regular"], "fuente": "unsplash",
                 "_origen": f["urls"]["regular"]} for f in r.json().get("results", [])]


_PROVEEDORES = {"local": _Local, "pinterest": _Pinterest, "unsplash": _Unsplash}


class FeedService:
    def __init__(self, db, fuentes: Optional[list[str]] = None) -> None:
        self.db = db
        self._prov = [_PROVEEDORES[f]() for f in (fuentes or config.FEED_SOURCES) if f in _PROVEEDORES]
        self._origen: dict[str, str] = {}      # ref -> ruta local o URL (solo lo ya servido)

    def siguiente(self, n: int = 8) -> list[dict]:
        """Hasta `n` fotos no vistas, mezclando las fuentes activas."""
        vistos = self.db.refs_vistos("feed")
        pool: list[dict] = []
        for p in self._prov:
            pool += [c for c in p.candidatos(n) if c["ref"] not in vistos]
        random.shuffle(pool)
        salida, refs = [], set()
        for c in pool:
            if c["ref"] in refs:
                continue
            refs.add(c["ref"])
            self._origen[c["ref"]] = c.pop("_origen")
            salida.append(c)
            if len(salida) == n:
                break
        return salida

    def url_de(self, ref: str) -> Optional[str]:
        return self._origen.get(ref)

    def bytes_de(self, ref: str) -> bytes:
        """Descarga/lee la foto de un ref ya servido. Lanza KeyError si no se sirvió antes."""
        origen = self._origen.get(ref)
        if origen is None and ref.startswith("local:"):       # sobrevive a reinicios del servidor
            origen = str(config.INSPIRATION_DIR / Path(ref[6:]).name)
        if origen is None:
            raise KeyError(ref)
        if not origen.startswith("http"):
            return Path(origen).read_bytes()
        try:
            r = requests.get(origen, timeout=15, stream=True)
            r.raise_for_status()
            datos = r.raw.read(MAX_BYTES + 1, decode_content=True)
        except requests.RequestException as e:
            raise FeedError(f"No se pudo descargar la imagen: {e}") from e
        if len(datos) > MAX_BYTES:
            raise FeedError("Imagen demasiado grande")
        return datos
