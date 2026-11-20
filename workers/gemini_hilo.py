from __future__ import annotations

import logging
from multiprocessing import Process, Queue

from db import ArmarioDB
from models.ropa import Prenda
from services.gemini_service import GeminiService

log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. FUNCIÓN TRABAJADORA (nivel superior del módulo, argumentos serializables)
# -----------------------------------------------------------------------------

def procesar_prenda(gemini: GeminiService, db: ArmarioDB, tag_id: str, image_path: str) -> Prenda:
    """Analiza la foto con Gemini, construye la Prenda y la guarda en la BD."""
    data = gemini.analyze(image_path)
    prenda = Prenda.from_json(data, image_path=image_path, tag_id=tag_id)
    db.guardar_prenda(prenda)
    return prenda


def trabajador(cola_tareas: Queue, cola_resultados: Queue) -> None:
    """Consumidor con centinela: procesa tareas hasta recibir None."""
    # Se crean aquí, dentro del proceso hijo: el cliente de Gemini no se
    # comparte entre procesos y SQLite abre una conexión por operación.
    gemini = GeminiService()
    db = ArmarioDB()

    while True:
        tarea = cola_tareas.get()          # bloquea sin consumir CPU
        if tarea is None:                  # centinela: orden de terminar
            break

        tag_id, image_path = tarea
        try:
            prenda = procesar_prenda(gemini, db, tag_id, image_path)
            cola_resultados.put(("OK", tag_id, prenda))
        except Exception as e:             # GeminiError, ValueError, KeyError...
            log.error("No se pudo procesar %s: %s", tag_id, e)
            cola_resultados.put(("ERROR", tag_id, str(e)))


# -----------------------------------------------------------------------------
# 2. GESTOR DEL PROCESO (se usa desde el programa principal)
# -----------------------------------------------------------------------------

class ProcesadorPrendas:
    def __init__(self) -> None:
        self.cola_tareas: Queue = Queue()
        self.cola_resultados: Queue = Queue()
        self._proceso = Process(
            target=trabajador,
            args=(self.cola_tareas, self.cola_resultados),
            name="procesador-prendas",
        )

    def iniciar(self) -> None:
        self._proceso.start()

    def enviar(self, tag_id: str, image_path: str) -> None:
        """Encola una prenda para analizar (no bloquea)."""
        self.cola_tareas.put((tag_id, image_path))

    def cerrar(self) -> None:
        """Cierre ordenado: centinela + join (sin terminate)."""
        self.cola_tareas.put(None)
        self._proceso.join()