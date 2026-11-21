"""Proceso trabajador: Gemini (ficha de la prenda) + FashionCLIP (vector).

Corre en un `Process` aparte, así el modelo de embeddings y las llamadas a la API no
bloquean la web. Un único proceso atiende dos tipos de tarea:
  ("PRENDA", tag_id, image_path)   -> Gemini + embedding + guardar en BD
  ("REEMBED", tag_id, image_path)  -> solo recalcula el vector de una prenda ya guardada
  ("EMBED", req_id, bytes)         -> embedding de una foto de swipe (resultado por cola_embeds)
Así la web y las prendas comparten UNA sola copia del modelo en memoria.

Rendimiento: las prendas se atienden en un pool de hilos (varias fotos a la vez: esperar a Gemini es
tiempo de red, no de CPU) y, dentro de cada prenda, Gemini y FashionCLIP corren en paralelo. El modelo
se precarga en segundo plano para que la primera llamada a Gemini no espere a torch.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Process, Queue
from typing import Optional

import numpy as np

import config
from database.db import ArmarioDB
from models.ropa import Prenda
from services.embedding_service import Embedder, get_embedder
from services.gemini_service import get_gemini_service

log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. FUNCIONES TRABAJADORAS (nivel superior del módulo, argumentos serializables)
# -----------------------------------------------------------------------------

def procesar_prenda(gemini, embeber, db: ArmarioDB, tag_id: str,
                    image_path: str) -> tuple[Prenda, Optional[str]]:
    """Gemini + FashionCLIP (en paralelo) -> Prenda -> BD. Devuelve (prenda, aviso).

    `embeber(ruta) -> (vector, nombre_embedder)` puede lanzar excepción. Si falla, la prenda se
    guarda igualmente (sin vector) y se avisa: ya se gastó la llamada a Gemini y se puede
    reintentar luego con REEMBED.
    """
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="embed") as ex:
        futuro_vector = ex.submit(embeber, image_path)     # mientras Gemini responde (red)
        data = gemini.analyze(image_path)
        prenda = Prenda.from_json(data, image_path=image_path, tag_id=tag_id)
        aviso = None
        try:
            prenda.vector, prenda.embedder = futuro_vector.result()
        except Exception as e:
            log.warning("Embedding de %s falló: %s", tag_id, e)
            aviso = f"Guardada sin vector de estilo ({e}). Se puede reindexar más tarde."
    db.guardar_prenda(prenda)
    return prenda, aviso


def trabajador(cola_tareas: Queue, cola_resultados: Queue, cola_embeds: Queue) -> None:
    """Consumidor con centinela: procesa tareas hasta recibir None."""
    # Todo se crea aquí, dentro del proceso hijo (el cliente de Gemini y el modelo no se
    # comparten entre procesos; SQLite abre una conexión por operación).
    gemini = get_gemini_service()
    db = ArmarioDB()
    embedder: Optional[Embedder] = None
    lock_carga = threading.Lock()      # una sola carga del modelo aunque lo pidan varios hilos
    lock_infer = threading.Lock()      # una inferencia de torch a la vez (la CPU/GPU es una sola)

    def obtener_embedder() -> Embedder:
        nonlocal embedder
        with lock_carga:
            if embedder is None:
                embedder = get_embedder()
            return embedder

    def embeber(fuente) -> tuple[np.ndarray, str]:
        emb = obtener_embedder()
        with lock_infer:
            return emb.embed(fuente), emb.nombre

    def precargar() -> None:           # en segundo plano: Gemini no espera a que cargue torch
        try:
            obtener_embedder()
        except Exception as e:
            log.error("No se pudo cargar el embedder (%s). Se reintentará con cada tarea.", e)

    threading.Thread(target=precargar, name="precarga-embedder", daemon=True).start()

    def tarea_prenda(tipo: str, tag_id: str, image_path: str) -> None:
        try:
            if tipo == "REEMBED":
                vec, nombre = embeber(image_path)
                db.actualizar_vector(tag_id, vec, nombre)
                cola_resultados.put(("OK", tag_id, {"aviso": None, "reindexada": True}))
            else:
                prenda, aviso = procesar_prenda(gemini, embeber, db, tag_id, image_path)
                cola_resultados.put(("OK", tag_id, {"aviso": aviso, "prenda": prenda.to_card()}))
        except Exception as e:          # GeminiError, ValueError, KeyError...
            log.error("No se pudo procesar %s: %s", tag_id, e)
            cola_resultados.put(("ERROR", tag_id, str(e)))

    pool = ThreadPoolExecutor(max_workers=max(1, config.GEMINI_CONCURRENCIA), thread_name_prefix="prenda")
    while True:
        tarea = cola_tareas.get()           # bloquea sin consumir CPU
        if tarea is None:                   # centinela: orden de terminar
            break
        tipo = tarea[0]

        if tipo == "EMBED":                 # swipe: rápido, se atiende en el momento (no espera a Gemini)
            _, req_id, datos = tarea
            try:
                cola_embeds.put((req_id, embeber(datos)[0], None))
            except Exception as e:
                cola_embeds.put((req_id, None, str(e)))
            continue

        _, tag_id, image_path = tarea
        pool.submit(tarea_prenda, tipo, tag_id, image_path)   # varias prendas a la vez
    pool.shutdown(wait=True)


# -----------------------------------------------------------------------------
# 2. GESTOR DEL PROCESO (se usa desde el programa principal)
# -----------------------------------------------------------------------------

class ProcesadorPrendas:
    def __init__(self) -> None:
        self.cola_tareas: Queue = Queue()
        self.cola_resultados: Queue = Queue()
        self._cola_embeds: Queue = Queue()
        self._proceso = Process(target=trabajador, name="procesador-prendas", daemon=True,
                                args=(self.cola_tareas, self.cola_resultados, self._cola_embeds))
        self._lock = threading.Lock()
        self.estados: dict[str, dict] = {}                # tag_id -> {"estado": ..., "mensaje": ...}
        self._esperas: dict[int, dict] = {}               # req_id -> {"evento", "vec", "error"}
        self._sig_req = 0
        self._recolectores: list[threading.Thread] = []

    def iniciar(self) -> None:
        self._proceso.start()
        for fn in (self._recolectar_prendas, self._recolectar_embeds):
            t = threading.Thread(target=fn, daemon=True, name=fn.__name__)
            t.start()
            self._recolectores.append(t)

    # ---------------------------------------------------------------- prendas
    def enviar(self, tag_id: str, image_path: str, reindexar: bool = False) -> None:
        """Encola una prenda para analizar (no bloquea)."""
        with self._lock:
            self.estados[tag_id] = {"estado": "procesando", "mensaje": None}
        self.cola_tareas.put(("REEMBED" if reindexar else "PRENDA", tag_id, image_path))

    def _recolectar_prendas(self) -> None:
        while True:
            item = self.cola_resultados.get()
            if item is None:
                break
            tipo, tag_id, valor = item
            with self._lock:
                if tipo == "OK":
                    self.estados[tag_id] = {"estado": "ok", "mensaje": valor.get("aviso")}
                else:
                    self.estados[tag_id] = {"estado": "error", "mensaje": valor}

    # ------------------------------------------------------------- embeddings
    def embed_bytes(self, datos: bytes, timeout: float = 60.0) -> np.ndarray:
        """Embedding síncrono de una imagen (lo usa el swipe). Lanza RuntimeError si falla."""
        with self._lock:
            self._sig_req += 1
            req_id = self._sig_req
            espera = self._esperas[req_id] = {"evento": threading.Event(), "vec": None, "error": None}
        self.cola_tareas.put(("EMBED", req_id, datos))
        if not espera["evento"].wait(timeout):
            with self._lock:
                self._esperas.pop(req_id, None)
            raise RuntimeError("Tiempo agotado esperando el embedding")
        with self._lock:
            self._esperas.pop(req_id, None)
        if espera["error"]:
            raise RuntimeError(espera["error"])
        return espera["vec"]

    def _recolectar_embeds(self) -> None:
        while True:
            item = self._cola_embeds.get()
            if item is None:
                break
            req_id, vec, error = item
            with self._lock:
                espera = self._esperas.get(req_id)
            if espera:
                espera["vec"], espera["error"] = vec, error
                espera["evento"].set()

    def cerrar(self) -> None:
        """Cierre ordenado: centinela + join (sin terminate)."""
        self.cola_tareas.put(None)
        self._proceso.join(timeout=30)
        self.cola_resultados.put(None)
        self._cola_embeds.put(None)
