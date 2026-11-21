from datetime import date

import numpy as np

import config
from models.ropa import Prenda
from services.creador_outfits import color_compat, generar
from services.gustos_service import PerfilGusto, calcular_perfil
from tests.factory import clima, prenda


def armario_basico():
    return [
        prenda("Top", "Blanco", 12, 32, tag="camiseta"), prenda("Top", "Azul marino", 2, 18, tag="jersey"),
        prenda("Bottom", "Denim", 0, 30, tag="vaqueros"), prenda("Bottom", "Negro", 0, 30, tag="negro"),
        prenda("Footwear", "Blanco", -5, 35, tag="zapas"),
        prenda("Outerwear", "Negro", -5, 17, tag="abrigo", protege=["Lluvia", "Viento"]),
        prenda("Outerwear", "Camel", 8, 19, tag="gabardina"),
    ]


def ids(o):
    return {p.tag_id for p in o.prendas}


def test_filtro_temperatura_y_chaqueta():
    frio, _ = generar(armario_basico(), clima(8))
    assert frio and all(any(p.main_category == "Outerwear" for p in o.prendas) for o in frio)  # <14 °C: chaqueta obligatoria
    assert all("camiseta" not in ids(o) for o in frio)             # camiseta: min 12 °C
    calor, _ = generar(armario_basico(), clima(26))
    assert calor and all("jersey" not in ids(o) and not any(p.main_category == "Outerwear" for p in o.prendas)
                         for o in calor)


def test_prendas_fuera_del_armario_se_excluyen():
    a = armario_basico()
    next(p for p in a if p.tag_id == "jersey").in_use = True
    outs, notas = generar(a, clima(8), n=5)
    assert all("jersey" not in ids(o) for o in outs) and any("fuera del armario" in n for n in notas)


def test_lluvia_prefiere_chaqueta_impermeable():
    outs, _ = generar(armario_basico(), clima(15, lluvia=True))
    assert outs and all("abrigo" in ids(o) for o in outs)           # la gabardina no protege


def test_ancla_elegida_por_el_usuario():
    outs, _ = generar(armario_basico(), clima(18), ancla_tag="vaqueros", n=3)
    assert outs and all("vaqueros" in ids(o) for o in outs)
    outs, notas = generar(armario_basico(), clima(18), ancla_tag="gabardina", n=2)
    assert outs and all("gabardina" in ids(o) for o in outs)


def test_ancla_no_disponible_se_avisa():
    a = armario_basico()
    a[2].in_use = True
    outs, notas = generar(a, clima(18), ancla_tag="vaqueros")
    assert any("ancla" in n for n in notas) and outs


def test_evento_filtra_formalidad():
    a = armario_basico() + [prenda("Top", "Blanco", 5, 30, formal=5, tag="camisa", estilos=["Formal"]),
                            prenda("Bottom", "Negro", 5, 30, formal=5, tag="traje", estilos=["Formal"]),
                            prenda("Footwear", "Negro", -5, 35, formal=5, tag="zapato", estilos=["Formal"])]
    outs, _ = generar(a, clima(18), evento="entrevista", n=1)
    assert ids(outs[0]) >= {"camisa", "traje"} and "zapas" not in ids(outs[0])


def test_novedad_penaliza_repetir_outfit_reciente():
    a = armario_basico()
    base, _ = generar(a, clima(22), n=1)
    top1 = base[0]
    hist = [{"fecha": date(2026, 11, 20), "tag_ids": ids(top1), "estado": "usado"}]
    de_nuevo, _ = generar(a, clima(22), n=1, historial=hist, hoy=date(2026, 11, 20))
    assert ids(de_nuevo[0]) != ids(top1)


def _vec(*x):
    v = np.array(x, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_afinidad_sigue_el_vector_de_gusto():
    """Si todos los likes son 'tipo A', gana el outfit hecho con prendas tipo A (a igualdad de reglas)."""
    A, B = _vec(1, 0.1, 0), _vec(0.1, 1, 0)
    a = [prenda("Top", "Blanco", vec=A, tag="topA"), prenda("Top", "Blanco", vec=B, tag="topB"),
         prenda("Bottom", "Negro", vec=A, tag="botA"), prenda("Bottom", "Negro", vec=B, tag="botB")]
    perfil = PerfilGusto(vector=_vec(1, -0.5, 0), media_likes=A, media_dislikes=B, n_likes=20,
                         n_dislikes=10, embedder="color-hist")
    outs, _ = generar(a, clima(20), perfil=perfil, n=4)
    assert ids(outs[0]) == {"topA", "botA"} and ids(outs[-1]) == {"topB", "botB"}
    assert outs[0].afinidad > outs[-1].afinidad


def test_perfil_resta_dislikes_y_arranque_en_frio(db):
    v = lambda *x: np.array(x, dtype=np.float32)  # noqa: E731
    for i in range(6):
        db.guardar_swipe("feed", f"l{i}", True, v(1, 0, 0), "color-hist")
    for i in range(4):
        db.guardar_swipe("feed", f"d{i}", False, v(0, 1, 0), "color-hist")
    perfil = calcular_perfil(db, "color-hist")
    assert perfil.conocido and perfil.vector[0] > 0 > perfil.vector[1]
    # los dislikes cuentan menos: |x| mayor que |y|
    assert abs(perfil.vector[0]) > abs(perfil.vector[1])
    nuevo = PerfilGusto(vector=perfil.vector, n_likes=2, n_dislikes=1)
    assert not nuevo.conocido


def test_colores():
    assert color_compat("Azul", "Azul claro") >= 0.85                              # monocromo/análogos
    assert color_compat("Azul", "Naranja") > color_compat("Rojo", "Amarillo")      # complementarios > tonos a ~50°
    assert color_compat("Negro", "Rojo") > color_compat("Rojo", "Amarillo")        # neutro + color: seguro
    assert color_compat("Negro", "Azul marino") < color_compat("Negro", "Blanco")


def test_sin_prendas_o_sin_base():
    assert generar([], clima(18))[0] == []
    solo_zapatos = [prenda("Footwear", "Negro", tag="z")]
    outs, notas = generar(solo_zapatos, clima(18))
    assert outs == [] and notas
