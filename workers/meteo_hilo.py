"""Hilo planificador de outfits.

- Genera el outfit del día solo, a las 00:00 (y una vez al arrancar si aún no hay).
- Atiende peticiones bajo demanda de la web y devuelve el resultado por un `Future`.
"""
from __future__ import annotations

import logging
from concurrent.futures import Future
from datetime import date, datetime, time, timedelta
from queue import Empty, Queue
from threading import Thread
from typing import Any, Optional

import config
from database.db import ArmarioDB
from services.meteo_service import WeatherError, clima_manual, get_weather
from services.outfit_service import crear_outfit

log = logging.getLogger(__name__)
CLAVE_DIARIO = "outfit_diario"


# -----------------------------------------------------------------------------
# 1. FUNCION TRABAJADORA
# -----------------------------------------------------------------------------

def segundos_hasta_medianoche() -> float:
    """Segundos que faltan para las 00:00 del día siguiente (+1 s de margen)."""
    manana = datetime.combine(date.today() + timedelta(days=1), time.min)
    return (manana - datetime.now()).total_seconds() + 1


def generar_outfit(ciudad: str, evento: Optional[str] = None, ancla: Optional[str] = None,
                   fecha: Optional[date] = None, temperatura: Optional[float] = None,
                   n: int = config.OUTFITS_POR_PETICION, db: Optional[ArmarioDB] = None) -> dict[str, Any]:
    """Obtiene el clima (de Open-Meteo o manual) y se lo pasa al creador de outfits."""
    fecha = fecha or date.today()
    if temperatura is not None:
        clima = clima_manual(temperatura, ciudad=ciudad, fecha=fecha)
    else:
        clima = get_weather(ciudad, fecha)
    return crear_outfit(clima, evento, ancla=ancla, n=n, db=db)


def trabajador(cola_tareas: Queue, cola_resultados: Queue, ciudad: str) -> None:
    """
    Consumidor con centinela y temporizador integrado:
      - Llega ("GENERAR", {params}, future) desde la web -> genera y resuelve el future.
      - Pasa el tiempo hasta las 00:00 sin mensajes -> genera el outfit diario.
      - Llega None (centinela) -> termina.
    """
    db = ArmarioDB()
    while True:
        future: Optional[Future] = None
        try:
            tarea = cola_tareas.get(timeout=segundos_hasta_medianoche())   # despierta a medianoche
        except Empty:
            origen, params = "DIARIO", {"ciudad": ciudad}
        else:
            if tarea is None:                                              # centinela
                break
            _, params, future = tarea
            origen = params.pop("origen", "MANUAL")

        try:
            resultado = generar_outfit(params.get("ciudad") or ciudad, params.get("evento"),
                                       params.get("ancla"), params.get("fecha"),
                                       params.get("temperatura"), params.get("n", config.OUTFITS_POR_PETICION), db)
            if origen == "DIARIO":
                db.kv_set(CLAVE_DIARIO, resultado)
            cola_resultados.put(("OK", origen, resultado))
            if future:
                future.set_result(resultado)
        except WeatherError as e:
            log.error("Clima no disponible: %s", e)
            cola_resultados.put(("ERROR", origen, str(e)))
            if future:
                future.set_exception(e)
        except Exception as e:                      # fallo del creador de outfits, etc.
            log.exception("Error generando outfit")
            cola_resultados.put(("ERROR", origen, str(e)))
            if future:
                future.set_exception(e)


# -----------------------------------------------------------------------------
# 2. GESTOR DEL HILO
# -----------------------------------------------------------------------------

class PlanificadorOutfits:
    def __init__(self, ciudad: str = config.CIUDAD_POR_DEFECTO) -> None:
        self.ciudad = ciudad
        self.cola_tareas: Queue = Queue()
        self.cola_resultados: Queue = Queue()     # (estado, origen, resultado|error): log de lo generado
        self._hilo = Thread(target=trabajador, args=(self.cola_tareas, self.cola_resultados, ciudad),
                            name="planificador-outfits", daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def solicitar(self, ciudad: Optional[str] = None, evento: Optional[str] = None,
                  ancla: Optional[str] = None, fecha: Optional[date] = None,
                  temperatura: Optional[float] = None, n: int = config.OUTFITS_POR_PETICION,
                  origen: str = "MANUAL") -> Future:
        """Petición bajo demanda. Devuelve un Future: `.result(timeout)` da el dict con los outfits."""
        futuro: Future = Future()
        self.cola_tareas.put(("GENERAR", {"ciudad": ciudad, "evento": evento, "ancla": ancla, "fecha": fecha,
                                          "temperatura": temperatura, "n": n, "origen": origen}, futuro))
        return futuro

    def asegurar_diario(self, db: ArmarioDB) -> None:
        """Al arrancar: si todavía no hay outfit de hoy, se pide uno."""
        guardado = db.kv_get(CLAVE_DIARIO)
        if not guardado or (guardado.get("clima") or {}).get("date") != date.today().isoformat():
            self.solicitar(origen="DIARIO")

    def cerrar(self) -> None:
        """Cierre ordenado: centinela + join."""
        self.cola_tareas.put(None)
        self._hilo.join(timeout=30)
