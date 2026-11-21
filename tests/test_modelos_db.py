from datetime import date

import numpy as np
import pytest

from models.ropa import Prenda
from tests.factory import prenda


def test_from_json_corrige_erratas_y_rangos():
    p = Prenda.from_json({"garment": {
        "main_category": "top", "sub_category": "Camiseta",
        "visuals": {"primary_color": "marron", "pattern": "liso", "fit_type": "oversise",
                    "style_aesthetics": ["casual", "inventado", "Streetwear"]},
        "context": {"formality_level": 9, "recommended_events": ["universidad"],
                    "weather": {"temperature_min": "30", "temperature_max": "10",
                                "fabric_weight": "ligero", "protects_against": ["lluvia", "x"]}}}},
        image_path="a.jpg", tag_id="A")
    assert (p.main_category, p.primary_color, p.fit_type) == ("Top", "Marrón", "Oversize")
    assert p.style_aesthetics == ["Casual", "Streetwear"]
    assert p.formality_level == 5 and (p.temperature_min, p.temperature_max) == (10, 30)
    assert p.protects_against == ["Lluvia"]


def test_categoria_invalida_falla():
    with pytest.raises(ValueError):
        Prenda.from_json({"garment": {"main_category": "Sombrero"}}, "a.jpg", "A")


def test_db_prenda_vector_y_toggle(db):
    p = prenda(vec=np.arange(4), tag="A", protege=["Lluvia"], estilos=["Casual", "Streetwear"])
    db.guardar_prenda(p)
    q = db.obtener_prenda("A")
    assert np.allclose(q.vector, p.vector) and q.style_aesthetics == ["Casual", "Streetwear"]
    assert q.protects_against == ["Lluvia"] and q.disponible
    assert db.alternar_estado_uso("A") is True and db.obtener_todas(solo_disponibles=True) == []
    assert db.alternar_estado_uso("A") is False
    assert db.alternar_estado_uso("nada") is None


def test_db_swipes_upsert_y_deshacer(db):
    v = np.ones(3, dtype=np.float32)
    db.guardar_swipe("feed", "r1", True, v, "color-hist")
    db.guardar_swipe("feed", "r1", False, v, "color-hist")        # reemplaza
    db.guardar_swipe("outfit", "o1", True, v, "color-hist", reemplazar=False)
    db.guardar_swipe("outfit", "o1", False, v, "color-hist", reemplazar=False)   # se ignora
    assert db.contar_swipes() == {"likes": 1, "dislikes": 1, "total": 2}
    assert db.deshacer_ultimo_swipe("feed") == "r1"
    assert db.refs_vistos("feed") == set()


def test_db_historial_ventana(db):
    i = db.guardar_outfit(["A", "B"], date(2026, 11, 18), None, 0.8, {}, "usado")
    db.guardar_outfit(["C"], date(2026, 10, 1), None, 0.8, {}, "usado")          # fuera de ventana
    db.guardar_outfit(["D"], date(2026, 11, 19), None, 0.8, {}, "sugerido")      # no cuenta
    h = db.historial_outfits(14, hoy=date(2026, 11, 20))
    assert [x["id"] for x in h] == [i] and h[0]["tag_ids"] == {"A", "B"}
