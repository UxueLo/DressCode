"""Flujo completo con el proceso real (Gemini falso + embedder color-hist) y clima manual."""
import io
import subprocess
import sys
import time
from pathlib import Path

import pytest

import config
from app import crear_app
from database.db import ArmarioDB
from services.feed_service import FeedService
from workers.gemini_hilo import ProcesadorPrendas
from workers.meteo_hilo import PlanificadorOutfits

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cliente():
    subprocess.run([sys.executable, str(RAIZ / "scripts" / "seed_demo.py")], check=True, env={
        **__import__("os").environ})
    db = ArmarioDB()
    proc, plan = ProcesadorPrendas(), PlanificadorOutfits("Bilbao")
    proc.iniciar(); plan.iniciar()
    app = crear_app(db, proc, plan, FeedService(db))
    yield app.test_client(), db, proc
    plan.cerrar(); proc.cerrar()


def test_estado_y_armario(cliente):
    c, _, _ = cliente
    e = c.get("/api/estado").get_json()
    assert e["prendas"] == 16 and len(e["eventos"]) >= 5
    assert len(c.get("/api/prendas").get_json()["prendas"]) == 16


def test_subir_prenda_pasa_por_gemini_y_embedding(cliente):
    c, db, proc = cliente
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (300, 300), "#C0272D").save(buf, "JPEG"); buf.seek(0)
    r = c.post("/api/prendas", data={"foto": (buf, "camiseta_roja.jpg"), "tag_id": "NFC-0001"},
               content_type="multipart/form-data")
    assert r.status_code == 202
    for _ in range(100):
        if proc.estados.get("NFC-0001", {}).get("estado") != "procesando":
            break
        time.sleep(0.1)
    assert proc.estados["NFC-0001"]["estado"] == "ok"
    p = db.obtener_prenda("NFC-0001")
    assert p.main_category == "Top" and p.primary_color == "Rojo" and p.vector is not None
    assert c.post("/api/prendas", data={"foto": (io.BytesIO(b"no soy imagen"), "x.jpg")},
                  content_type="multipart/form-data").status_code == 400


def test_swipe_aprende_el_perfil(cliente):
    c, db, _ = cliente
    for i in range(10):
        foto = c.get("/api/feed?n=1").get_json()["fotos"][0]
        r = c.post("/api/swipe", json={"ref": foto["ref"], "liked": i % 3 != 0})
        assert r.status_code == 200
    perfil = c.get("/api/estado").get_json()["perfil"]
    assert perfil["likes"] + perfil["dislikes"] == 10 and perfil["conocido"]
    assert c.post("/api/swipe", json={"ref": "pin:inventado", "liked": True}).status_code == 410
    assert c.post("/api/swipe/deshacer").get_json()["ref"]


def test_generar_outfits_y_feedback(cliente):
    c, db, _ = cliente
    r = c.post("/api/outfits/generar", json={"temperatura": 9, "evento": "trabajo"})
    assert r.status_code == 200
    d = r.get_json()
    assert len(d["outfits"]) == 3 and d["clima"]["fuente"] == "manual"
    o = d["outfits"][0]
    assert o["id"] and {p["categoria"] for p in o["prendas"]} >= {"Top", "Bottom", "Outerwear"}
    assert 0 <= o["score"] <= 1 and o["razones"]

    antes = c.get("/api/estado").get_json()["perfil"]
    f = c.post(f"/api/outfits/{o['id']}/feedback", json={"accion": "like"}).get_json()
    assert f["estado"] == "guardado" and f["aprendido"]
    assert f["perfil"]["likes"] == antes["likes"] + 1
    assert c.post(f"/api/outfits/{o['id']}/feedback", json={"accion": "usar"}).get_json()["estado"] == "usado"
    assert c.post("/api/outfits/9999/feedback", json={"accion": "like"}).status_code == 404
    assert c.post(f"/api/outfits/{o['id']}/feedback", json={"accion": "x"}).status_code == 400

    # lo que me puse hoy se penaliza en la siguiente tanda (novedad)
    d2 = c.post("/api/outfits/generar", json={"temperatura": 9, "evento": "trabajo"}).get_json()
    ids1 = {p["tag_id"] for p in o["prendas"]}
    mismo = [x for x in d2["outfits"] if {p["tag_id"] for p in x["prendas"]} == ids1]
    assert not mismo or mismo[0]["novedad"] < 1


def test_toggle_nfc_simulado_y_disponibilidad(cliente):
    c, db, _ = cliente
    assert c.post("/api/prendas/D-ABRIGO/toggle").get_json()["en_uso"] is True
    d = c.post("/api/outfits/generar", json={"temperatura": 5}).get_json()
    assert all("D-ABRIGO" not in {p["tag_id"] for p in o["prendas"]} for o in d["outfits"])
    assert any("fuera del armario" in n for n in d["notas"])
    assert c.post("/api/prendas/D-ABRIGO/toggle").get_json()["en_uso"] is False
    assert c.post("/api/prendas/NOEXISTE/toggle").status_code == 404


def test_ancla_y_borrado(cliente):
    c, db, _ = cliente
    d = c.post("/api/outfits/generar", json={"temperatura": 20, "ancla": "D-VAQ"}).get_json()
    assert d["outfits"] and all("D-VAQ" in {p["tag_id"] for p in o["prendas"]} for o in d["outfits"])
    assert c.delete("/api/prendas/NFC-0001").status_code == 200
    assert c.delete("/api/prendas/NFC-0001").status_code == 404
