from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from queue import Empty, Queue
from threading import Thread
from typing import Optional

from services.meteo_service import WeatherError, get_weather
from services.outfit_service import crear_outfit   # pendiente de crear: crear_outfit(clima: dict, estilo: str | None)

log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. FUNCION TRABAJADORA
# -----------------------------------------------------------------------------

def segundos_hasta_medianoche() -> float:
    """Segundos que faltan para las 00:00 del día siguiente."""
    manana = datetime.combine(date.today() + timedelta(days=1), time.min)
    return (manana - datetime.now()).total_seconds()


def generar_outfit(ciudad: str, estilo: Optional[str]):
    """Obtiene el clima de hoy y se lo pasa al creador de outfits."""
    clima = get_weather(ciudad, date.today())
    return crear_outfit(clima, estilo)


def trabajador(cola_tareas: Queue, cola_resultados: Queue, ciudad: str) -> None:
    """
    Consumidor con centinela y temporizador integrado:
      - Si llega ("GENERAR", ciudad, estilo) desde el HTML, genera un outfit.
      - Si pasa el tiempo hasta las 00:00 sin mensajes, genera el outfit diario.
      - Si llega None (centinela), termina.
    """
    while True:
        try:
            # get() con timeout: despierta solo si llega una tarea o llega medianoche
            tarea = cola_tareas.get(timeout=segundos_hasta_medianoche())
        except Empty:
            origen, ciudad_tarea, estilo = "DIARIO", ciudad, None
        else:
            if tarea is None: # centinela: orden de terminar
                break
            origen = "MANUAL"
            _, ciudad_tarea, estilo = tarea

        try:
            outfit = generar_outfit(ciudad_tarea or ciudad, estilo)
            cola_resultados.put(("OK", origen, outfit))
        except WeatherError as e:
            log.error("Clima no disponible: %s", e)
            cola_resultados.put(("ERROR", origen, str(e)))
        except Exception as e:                     # fallo del creador de outfits, etc.
            log.exception("Error generando outfit")
            cola_resultados.put(("ERROR", origen, str(e)))


# -----------------------------------------------------------------------------
# 2. GESTOR DEL HILO
# -----------------------------------------------------------------------------

class PlanificadorOutfits:
    def __init__(self, ciudad: str) -> None:
        self.cola_tareas: Queue = Queue()
        self.cola_resultados: Queue = Queue()
        self._hilo = Thread(
            target=trabajador,
            args=(self.cola_tareas, self.cola_resultados, ciudad),
            name="planificador-outfits",
        )

    def iniciar(self) -> None:
        self._hilo.start()

    def solicitar(self, ciudad: Optional[str] = None, estilo: Optional[str] = None) -> None:
        """Petición bajo demanda (la llamará el HTML). estilo=None no filtra por estilo."""
        self.cola_tareas.put(("GENERAR", ciudad, estilo))

    def cerrar(self) -> None:
        """Cierre ordenado: centinela + join."""
        self.cola_tareas.put(None)
        self._hilo.join()