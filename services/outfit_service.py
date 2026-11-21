"""Orquesta la creación de outfits: BD + perfil de gusto + historial + algoritmo puro.

Es lo que llaman el hilo planificador (`workers/meteo_hilo.py`) y la web.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import config
from database.db import ArmarioDB
from models.ropa import Outfit
from services import creador_outfits
from services.gustos_service import calcular_perfil, vector_outfit

log = logging.getLogger(__name__)
ACCIONES = {"like", "dislike", "usar"}


def crear_outfit(clima: dict, evento: Optional[str] = None, *, ancla: Optional[str] = None,
                 n: int = config.OUTFITS_POR_PETICION, db: Optional[ArmarioDB] = None,
                 guardar: bool = True, hoy: Optional[date] = None) -> dict[str, Any]:
    """Genera `n` outfits para el clima/evento dado y (opcional) los registra como 'sugerido'."""
    db = db or ArmarioDB()
    hoy = hoy or (date.fromisoformat(clima["date"]) if clima.get("date") else date.today())
    perfil = calcular_perfil(db, config.EMBEDDER)
    historial = db.historial_outfits(config.NOVEDAD_DIAS, hoy=hoy)
    outfits, notas = creador_outfits.generar(
        db.obtener_todas(), clima, perfil=perfil, historial=historial, evento=evento,
        ancla_tag=ancla, n=n, hoy=hoy, embedder=config.EMBEDDER)

    if guardar:
        for o in outfits:
            o.id = db.guardar_outfit(o.tag_ids, hoy, o.evento, o.score,
                                     {"razones": o.razones, "coherencia": o.coherencia,
                                      "afinidad": o.afinidad, "novedad": o.novedad, **o.detalle})
    return {"outfits": [o.to_dict() for o in outfits], "notas": notas, "clima": clima,
            "perfil": perfil.resumen()}


def registrar_feedback_outfit(db: ArmarioDB, outfit_id: int, accion: str) -> dict[str, Any]:
    """like/dislike/usar sobre un outfit sugerido: actualiza su estado y alimenta el perfil de gusto.

    like y dislike suman/restan al vector de gusto con más peso que un pin (es ropa tuya real).
    'usar' lo marca como llevado hoy (alimenta la penalización de novedad) y cuenta como like
    suave si todavía no habías opinado.
    """
    if accion not in ACCIONES:
        raise ValueError(f"acción inválida: {accion}")
    o = db.obtener_outfit(outfit_id)
    if o is None:
        raise KeyError(outfit_id)

    prendas = db.obtener_por_ids(o["tag_ids"])
    vec = vector_outfit(prendas, config.EMBEDDER)
    ref = f"outfit:{outfit_id}"

    if accion == "usar":
        db.actualizar_estado_outfit(outfit_id, "usado", date.today())
        if vec is not None:
            db.guardar_swipe("outfit", ref, True, vec, config.EMBEDDER, peso=config.PESO_LIKE, reemplazar=False)
    else:
        like = accion == "like"
        db.actualizar_estado_outfit(outfit_id, "guardado" if like else "descartado")
        if vec is not None:
            db.guardar_swipe("outfit", ref, like, vec, config.EMBEDDER, peso=config.PESO_FEEDBACK_OUTFIT)
    return {"ok": True, "estado": db.obtener_outfit(outfit_id)["estado"],
            "perfil": calcular_perfil(db, config.EMBEDDER).resumen(), "aprendido": vec is not None}
