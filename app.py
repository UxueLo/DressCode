"""API + interfaz web de DressCode (Flask).

`crear_app` recibe las dependencias ya construidas (BD, procesador de prendas, planificador,
feed) para poder probarla con piezas falsas.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from PIL import Image, UnidentifiedImageError

import config
from services.feed_service import FeedError
from services.gustos_service import calcular_perfil
from services.meteo_service import WeatherError
from services.outfit_service import registrar_feedback_outfit
from workers.meteo_hilo import CLAVE_DIARIO

log = logging.getLogger(__name__)
TAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _error(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def crear_app(db, procesador, planificador, feed) -> Flask:
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.INSPIRATION_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ páginas
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/uploads/<path:nombre>")
    def uploads(nombre):
        return send_from_directory(config.UPLOAD_DIR, nombre)

    @app.get("/inspiration/<path:nombre>")
    def inspiration(nombre):
        return send_from_directory(config.INSPIRATION_DIR, nombre)

    # ------------------------------------------------------------------- estado
    @app.get("/api/estado")
    def estado():
        prendas = db.obtener_todas()
        return jsonify({
            "prendas": len(prendas), "disponibles": sum(p.disponible for p in prendas),
            "ciudad": db.kv_get("ciudad", config.CIUDAD_POR_DEFECTO),
            "perfil": calcular_perfil(db, config.EMBEDDER).resumen(),
            "embedder": config.EMBEDDER, "gemini": config.GEMINI_MODE,
            "fuentes_feed": config.FEED_SOURCES,
            "eventos": [{"id": k, "nombre": v["nombre"]} for k, v in config.EVENTOS.items()],
        })

    @app.post("/api/ajustes")
    def ajustes():
        ciudad = (request.get_json(silent=True) or {}).get("ciudad", "").strip()
        if not ciudad:
            return _error("Indica una ciudad")
        db.kv_set("ciudad", ciudad)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ armario
    @app.get("/api/prendas")
    def listar_prendas():
        return jsonify({"prendas": [p.to_card() for p in db.obtener_todas()],
                        "jobs": procesador.estados})

    @app.post("/api/prendas")
    def subir_prenda():
        archivo = request.files.get("foto")
        if archivo is None:
            return _error("Falta la foto (campo 'foto')")
        tag_id = (request.form.get("tag_id") or "").strip() or f"MANUAL-{uuid.uuid4().hex[:8]}"
        if not TAG_RE.match(tag_id):
            return _error("tag_id: solo letras, números, '-' y '_' (máx. 40)")
        try:   # se valida y normaliza la foto: JPEG de hasta 1280 px
            img = Image.open(io.BytesIO(archivo.read())).convert("RGB")
        except (UnidentifiedImageError, OSError):
            return _error("El fichero no es una imagen válida")
        img.thumbnail((1280, 1280))
        ruta = config.UPLOAD_DIR / f"{tag_id}_{uuid.uuid4().hex[:6]}.jpg"
        img.save(ruta, "JPEG", quality=90)
        procesador.enviar(tag_id, str(ruta))   # Gemini + FashionCLIP en el proceso trabajador
        return jsonify({"tag_id": tag_id, "estado": "procesando"}), 202

    @app.delete("/api/prendas/<tag_id>")
    def borrar_prenda(tag_id):
        ruta = db.borrar_prenda(tag_id)
        if ruta is None:
            return _error("No existe esa prenda", 404)
        Path(ruta).unlink(missing_ok=True)
        procesador.estados.pop(tag_id, None)
        return jsonify({"ok": True})

    @app.post("/api/prendas/<tag_id>/toggle")
    def alternar(tag_id):
        """Equivale a pasar la etiqueta por el lector NFC: dentro <-> fuera del armario."""
        nuevo = db.alternar_estado_uso(tag_id)
        if nuevo is None:
            return _error("No existe esa prenda", 404)
        return jsonify({"tag_id": tag_id, "en_uso": nuevo})

    @app.post("/api/prendas/reindexar")
    def reindexar():
        pendientes = db.prendas_sin_vector()
        for p in pendientes:
            procesador.enviar(p.tag_id, p.image_path, reindexar=True)
        return jsonify({"encoladas": len(pendientes)})

    # -------------------------------------------------------------- swipe/gustos
    @app.get("/api/feed")
    def feed_siguiente():
        n = min(max(int(request.args.get("n", 8)), 1), 20)
        fotos = feed.siguiente(n)
        aviso = None
        if not fotos:
            aviso = ("No quedan fotos nuevas. Copia imágenes en data/inspiration/ o configura "
                     "Pinterest/Unsplash en el .env.")
        return jsonify({"fotos": fotos, "aviso": aviso, "perfil": calcular_perfil(db, config.EMBEDDER).resumen()})

    @app.post("/api/swipe")
    def swipe():
        datos = request.get_json(silent=True) or {}
        ref, liked = datos.get("ref"), datos.get("liked")
        if not isinstance(ref, str) or not isinstance(liked, bool):
            return _error("Se esperaba {ref: str, liked: bool}")
        try:
            imagen = feed.bytes_de(ref)
        except KeyError:
            return _error("Esa foto ya no está disponible; recarga el feed", 410)
        except FeedError as e:
            return _error(str(e), 502)
        try:
            vec = procesador.embed_bytes(imagen)
        except RuntimeError as e:
            return _error(f"No se pudo calcular el vector de la foto: {e}", 503)
        db.guardar_swipe("feed", ref, liked, vec, config.EMBEDDER, peso=1.0, image_url=feed.url_de(ref))
        return jsonify({"ok": True, "perfil": calcular_perfil(db, config.EMBEDDER).resumen()})

    @app.post("/api/swipe/deshacer")
    def deshacer():
        ref = db.deshacer_ultimo_swipe("feed")
        return jsonify({"ref": ref, "perfil": calcular_perfil(db, config.EMBEDDER).resumen()})

    # ------------------------------------------------------------------ outfits
    @app.post("/api/outfits/generar")
    def generar():
        d = request.get_json(silent=True) or {}
        try:
            fecha = date.fromisoformat(d["fecha"]) if d.get("fecha") else date.today()
            temperatura = float(d["temperatura"]) if d.get("temperatura") not in (None, "") else None
        except (ValueError, TypeError):
            return _error("Fecha o temperatura no válidas")
        ciudad = (d.get("ciudad") or "").strip() or db.kv_get("ciudad", config.CIUDAD_POR_DEFECTO)
        futuro = planificador.solicitar(ciudad=ciudad, evento=d.get("evento") or None,
                                        ancla=d.get("ancla") or None, fecha=fecha, temperatura=temperatura)
        try:
            return jsonify(futuro.result(timeout=60))
        except WeatherError as e:
            return _error(f"{e}. Puedes escribir la temperatura a mano.", 502)
        except FutureTimeout:
            return _error("Tiempo agotado generando outfits", 504)
        except Exception as e:
            log.exception("generar")
            return _error(str(e), 500)

    @app.get("/api/outfits/diario")
    def diario():
        d = db.kv_get(CLAVE_DIARIO)
        if not d or (d.get("clima") or {}).get("date") != date.today().isoformat():
            return jsonify({"outfits": [], "pendiente": True})
        return jsonify(d)

    @app.post("/api/outfits/<int:outfit_id>/feedback")
    def feedback(outfit_id):
        accion = (request.get_json(silent=True) or {}).get("accion")
        try:
            return jsonify(registrar_feedback_outfit(db, outfit_id, accion))
        except ValueError as e:
            return _error(str(e))
        except KeyError:
            return _error("No existe ese outfit", 404)

    @app.get("/api/outfits/historial")
    def historial():
        salida = []
        for o in db.listar_outfits(30):
            prendas = db.obtener_por_ids(o["tag_ids"])
            salida.append({"id": o["id"], "fecha": o["fecha"].isoformat(), "estado": o["estado"],
                           "score": o["score"], "prendas": [p.to_card() for p in prendas]})
        return jsonify({"outfits": salida})

    return app
