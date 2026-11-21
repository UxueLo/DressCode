"""Arranque de DressCode: proceso de Gemini+FashionCLIP, hilo planificador y web.

    python main.py            # http://127.0.0.1:5000
"""
from __future__ import annotations

import logging

import config
from app import crear_app
from database.db import ArmarioDB
from services.feed_service import FeedService
from workers.gemini_hilo import ProcesadorPrendas
from workers.meteo_hilo import PlanificadorOutfits


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.INSPIRATION_DIR.mkdir(parents=True, exist_ok=True)

    db = ArmarioDB()
    procesador = ProcesadorPrendas()            # Gemini + FashionCLIP (proceso aparte)
    planificador = PlanificadorOutfits(db.kv_get("ciudad", config.CIUDAD_POR_DEFECTO))
    procesador.iniciar()
    planificador.iniciar()
    planificador.asegurar_diario(db)            # outfit de hoy si todavía no existe

    app = crear_app(db, procesador, planificador, FeedService(db))
    try:
        # use_reloader=False: el reloader de Flask duplicaría procesos e hilos
        app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        print("\nPrograma interrumpido.")
    finally:
        planificador.cerrar()
        procesador.cerrar()


if __name__ == "__main__":
    main()
