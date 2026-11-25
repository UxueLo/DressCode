"""Hilo del sensor RFID: alterna in_use si la prenda existe; si no, pide la foto y la manda a Gemini."""
from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Thread
from typing import Callable, Optional

from database.db import ArmarioDB
from workers.gemini_hilo import ProcesadorPrendas

log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. FUNCION TRABAJADORA
# -----------------------------------------------------------------------------

def trabajador(procesador: ProcesadorPrendas, pedir_foto: Callable[[str], Optional[str]],
               terminar: Event, lector=None) -> None:
    if lector is None: # import diferido para que el projecto funcione fuera de la Raspberry
        from mfrc522_i2c import MFRC522
        lector = MFRC522(1, 0x28)
    db = ArmarioDB()
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="foto")  # pedir_foto espera al usuario: no en este hilo
    pendientes: set[str] = set() # etiquetas cuya foto ya se ha pedido
    ultimo = None

    def foto_lista(tag_id: str, futuro: Future) -> None: #se ejecuta al terminar pedir_foto
        pendientes.discard(tag_id)
        try:
            ruta = futuro.result()
        except Exception as e:
            log.error("No se pudo obtener la foto de %s: %s", tag_id, e)
            return
        if ruta:
            procesador.enviar(tag_id, ruta)

    while not terminar.wait(0.1):
        estado, *_ = lector.scan()
        if estado != lector.MIFARE_OK:
            ultimo = None # si no hay tarjeta la siguiente cuenta como lectura nueva
            continue
        estado, uid, *_ = lector.identify()
        tag_id = "".join(f"{b:02X}" for b in uid[:4])
        if estado != lector.MIFARE_OK or tag_id == ultimo:
            continue  # lectura fallida o la misma tarjeta sigue pegada al lector
        ultimo = tag_id

        if db.alternar_estado_uso(tag_id) is not None: #si la prenda existe se cambia su estado
            log.info("Prenda %s alternada", tag_id)
        elif tag_id not in pendientes: #si la prenda no existe y no se ha pedido su foto
            pendientes.add(tag_id)
            pool.submit(pedir_foto, tag_id).add_done_callback(lambda f, t=tag_id: foto_lista(t, f))

    pool.shutdown(wait=False, cancel_futures=True)  # no espera a una foto que nunca llega


# -----------------------------------------------------------------------------
# 2. GESTOR DEL HILO
# -----------------------------------------------------------------------------

class SensorPrendas:
    def __init__(self, procesador: ProcesadorPrendas, pedir_foto: Callable[[str], Optional[str]]) -> None:
        self._terminar = Event()
        self._hilo = Thread(target=trabajador, args=(procesador, pedir_foto, self._terminar),
                            name="sensor-rfid", daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def cerrar(self) -> None:
        self._terminar.set()
        self._hilo.join(timeout=5)

#TODO hacer que el main utilize este hilo