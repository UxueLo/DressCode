"""Algoritmo de creación de outfits (puro: sin BD ni red; fácil de probar).

Sigue DECISION_DE_OUFITS.pdf:
  1. Filtros: disponibilidad, temperatura (temp_min <= T <= temp_max), evento, lluvia/nieve.
  2. Prenda ancla (la elige el usuario o se prueban todas) + socios compatibles por
     color y formalidad.
  3. Decidir si se añade chaqueta (temperatura / lluvia / viento).
  4. ScoreTotal = 0.4·Coherencia + 0.4·Afinidad + 0.2·Novedad (pesos en config.py).
  5. Se eligen los N mejores evitando repetir la misma prenda base.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Sequence

import config
from models.ropa import COLORS, NEUTRAL_COLORS, Outfit, Prenda, norm, tono_color
from services.gustos_service import PerfilGusto, coseno, vector_outfit

# ============================================================== reglas de estética
_CHOQUE_NEUTROS = {frozenset(p): v for p, v in [
    (("Negro", "Azul marino"), 0.60), (("Negro", "Marrón"), 0.65),
    (("Azul marino", "Marrón"), 0.80), (("Denim", "Azul marino"), 0.70)]}

_FAMILIAS_ESTILO = [
    {"Casual", "Streetwear", "Athleisure", "Deportivo", "Workwear / Utilitario", "Punk / Grunge"},
    {"Smart Casual", "Minimalista", "Clásico / Atemporal", "Preppy", "Formal", "Elegante / Gala"},
    {"Boho", "Romántico", "Vintage / Retro"},
    {"Rock", "Punk / Grunge", "Gótico"},
]
_VOLUMEN = {"Compresión": 0, "Ajustado": 0, "Cropped": 0, "Regular": 1, "Recto": 1, "Otro": 1,
            "Holgado": 2, "Oversize": 2, "Acampanado": 2}


def color_compat(a: str, b: str) -> float:
    """Compatibilidad de dos colores (0-1) según la DIFERENCIA de tono (rueda cromática)."""
    if "Multicolor" in (a, b):
        return 0.70
    na, nb = a in NEUTRAL_COLORS, b in NEUTRAL_COLORS
    if na and nb:
        return _CHOQUE_NEUTROS.get(frozenset((a, b)), 0.90)
    if na or nb:
        return 0.92
    d = abs(tono_color(a) - tono_color(b))
    d = min(d, 360 - d)
    if d <= 15:
        return 0.85      # monocromo
    if d <= 45:
        return 0.90      # análogos
    if d <= 75:
        return 0.60
    if d <= 110:
        return 0.45
    if d <= 140:
        return 0.55      # tríada
    return 0.75          # complementarios


def formalidad_compat(a: Prenda, b: Prenda) -> float:
    return 1 - abs(a.formality_level - b.formality_level) / 4


def estilo_compat(a: Prenda, b: Prenda) -> float:
    sa, sb = set(a.style_aesthetics), set(b.style_aesthetics)
    if sa & sb:
        return 1.0
    if any(sa & f and sb & f for f in _FAMILIAS_ESTILO):
        return 0.7
    return 0.3


def compat_pareja(a: Prenda, b: Prenda) -> float:
    """Compatibilidad rápida (color + formalidad) para preseleccionar socios del ancla."""
    return 0.6 * color_compat(a.primary_color, b.primary_color) + 0.4 * formalidad_compat(a, b)


def _media(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 1.0


def _patron_score(prendas: Sequence[Prenda]) -> float:
    con = [p.pattern for p in prendas if p.pattern != "Liso" and p.main_category != "Accessory"]
    if len(con) <= 1:
        return 1.0
    if len(con) == 2:
        return 0.35 if con[0] == con[1] else 0.5
    return 0.2


def _proporcion_score(prendas: Sequence[Prenda]) -> float:
    arriba = next((p for p in prendas if p.main_category == "Top"), None)
    abajo = next((p for p in prendas if p.main_category == "Bottom"), None)
    if not arriba or not abajo:
        return 1.0   # vestido: no hay proporción arriba/abajo que equilibrar
    va, vb = _VOLUMEN[arriba.fit_type], _VOLUMEN[abajo.fit_type]
    if {va, vb} == {0, 2}:
        return 1.0                                   # ajustado + amplio: equilibrio clásico
    if va == vb == 2:
        streetwear = "Streetwear" in arriba.style_aesthetics and "Streetwear" in abajo.style_aesthetics
        return 0.85 if streetwear else 0.55
    if va == vb == 0:
        return 0.8
    return 0.9


def puntuar_estetica(prendas: Sequence[Prenda]) -> tuple[float, dict[str, float]]:
    pares = list(itertools.combinations(prendas, 2))
    partes = {
        "color": _media([color_compat(a.primary_color, b.primary_color) for a, b in pares]),
        "formalidad": 1 - (max(p.formality_level for p in prendas) - min(p.formality_level for p in prendas)) / 4,
        "estilo": _media([estilo_compat(a, b) for a, b in pares]),
        "estampados": _patron_score(prendas),
        "proporcion": _proporcion_score(prendas),
    }
    total = sum(config.W_ESTETICA[k] * v for k, v in partes.items())
    return total, partes


# =================================================================== contexto
@dataclass
class Contexto:
    clima: dict
    t: float
    evento: Optional[str] = None
    perfil: Optional[PerfilGusto] = None
    historial: Sequence[dict] = ()
    hoy: date = field(default_factory=date.today)
    embedder: str = config.EMBEDDER


def clima_fit(prendas: Sequence[Prenda], ctx: Contexto) -> float:
    """0-1: lo centradas que están las prendas en su rango + protección contra lluvia/nieve/viento."""
    cent = []
    for p in prendas:
        mitad = max((p.temperature_max - p.temperature_min) / 2, 1.0)
        mid = (p.temperature_max + p.temperature_min) / 2
        cent.append(0.5 + 0.5 * max(0.0, 1 - abs(ctx.t - mid) / mitad))
    score = _media(cent)
    protege = {x for p in prendas if p.main_category in ("Outerwear", "Footwear") for x in p.protects_against}
    if ctx.clima.get("rainy"):
        score += 0.15 if "Lluvia" in protege else -0.10
    if ctx.clima.get("snowy"):
        score += 0.15 if ({"Nieve", "Lluvia"} & protege) else -0.10
    if ctx.clima.get("windy") and "Viento" in protege:
        score += 0.05
    return max(0.0, min(1.0, score))


def evento_fit(prendas: Sequence[Prenda], evento: Optional[str]) -> Optional[float]:
    if not evento or evento not in config.EVENTOS:
        return None
    ev = config.EVENTOS[evento]
    fmin, fmax = ev["formalidad"]
    puntos = []
    for p in prendas:
        if p.main_category == "Accessory":
            continue
        fuera = max(fmin - p.formality_level, p.formality_level - fmax, 0)
        f = 1.0 if fuera == 0 else (0.5 if fuera == 1 else 0.0)
        s = 1.0 if set(ev["estilos"]) & set(p.style_aesthetics) else 0.0
        texto = norm(" ".join(p.recommended_events))
        k = 1.0 if any(norm(c) in texto for c in ev["claves"]) else 0.0
        puntos.append(0.5 * f + 0.25 * s + 0.25 * k)
    return _media(puntos)


def novedad(prendas: Sequence[Prenda], ctx: Contexto) -> float:
    """1 = nada repetido. Penaliza solapamiento (Jaccard) con outfits usados/guardados hace poco."""
    ids = {p.tag_id for p in prendas}
    pen = 0.0
    for h in ctx.historial:
        dias = (ctx.hoy - h["fecha"]).days
        if not 0 <= dias < config.NOVEDAD_DIAS:
            continue
        jac = len(ids & h["tag_ids"]) / len(ids | h["tag_ids"])
        peso = 1.0 if h["estado"] == "usado" else 0.6
        pen = max(pen, jac * (1 - dias / config.NOVEDAD_DIAS) * peso)
    return 1 - pen


# ============================================================== construcción
def _apta_temp(p: Prenda, t: float, tol: float = 0.0) -> bool:
    return p.temperature_min - tol <= t <= p.temperature_max + tol


def _modo_chaqueta(ctx: Contexto) -> str:
    c = ctx.clima
    if ctx.t < config.T_CHAQUETA_OBLIGATORIA or c.get("rainy") or c.get("snowy") or c.get("windy"):
        return "obligatoria"
    return "opcional" if ctx.t < config.T_CHAQUETA_OPCIONAL else "ninguna"


def _preparar_pools(prendas: list[Prenda], ctx: Contexto, notas: list[str]) -> dict[str, list[Prenda]]:
    """Filtra por disponibilidad, evento, temperatura (con relajación gradual) y lluvia/nieve."""
    disponibles = [p for p in prendas if p.disponible]
    if len(disponibles) < len(prendas):
        notas.append(f"{len(prendas) - len(disponibles)} prenda(s) fuera del armario no se han tenido en cuenta.")
    ev = config.EVENTOS.get(ctx.evento or "")
    modo = _modo_chaqueta(ctx)

    pools: dict[str, list[Prenda]] = {}
    for cat in ("Top", "Bottom", "Dress", "Outerwear", "Footwear", "Accessory"):
        de_cat = [p for p in disponibles if p.main_category == cat]
        if ev and cat != "Accessory":   # formalidad dentro del rango del evento ±1
            fmin, fmax = ev["formalidad"]
            filtradas = [p for p in de_cat if fmin - 1 <= p.formality_level <= fmax + 1]
            if filtradas or not de_cat:
                de_cat = filtradas
            else:
                notas.append(f"Ninguna prenda de «{cat}» encaja en formalidad con el evento; se ignora ese filtro.")
        pool: list[Prenda] = []
        # vestidos y complementos no relajan; la chaqueta solo si es imprescindible. Top/Bottom/Calzado relajan el rango si son imprescindibles
        tolerancias = config.TOLERANCIAS_TEMP[:1] if cat in ("Accessory", "Dress") or (
            cat == "Outerwear" and modo != "obligatoria") else config.TOLERANCIAS_TEMP
        for tol in tolerancias:
            pool = [p for p in de_cat if _apta_temp(p, ctx.t, tol)]
            if pool:
                if pool and tol > 0:
                    notas.append(f"«{cat}»: nada en el rango exacto de {ctx.t:.0f} °C; se admite ±{tol:.0f} °C.")
                break
        pools[cat] = pool

    # lluvia / nieve: la prenda de abrigo debe protegerse si existe alguna que lo haga
    for activo, clave, texto in ((ctx.clima.get("rainy"), "Lluvia", "lluvia"), (ctx.clima.get("snowy"), "Nieve", "nieve")):
        if activo and pools["Outerwear"]:
            protegen = [p for p in pools["Outerwear"] if clave in p.protects_against
                        or (clave == "Nieve" and "Lluvia" in p.protects_against)]
            if protegen:
                pools["Outerwear"] = protegen
            else:
                notas.append(f"Se espera {texto} pero ninguna chaqueta disponible protege de ella.")
    return pools


def _mejores(ancla_o_base: Sequence[Prenda], candidatas: list[Prenda], k: int) -> list[Prenda]:
    def puntuacion(x: Prenda) -> float:
        return _media([compat_pareja(a, x) for a in ancla_o_base])
    utiles = [x for x in candidatas
              if all(abs(a.formality_level - x.formality_level) <= config.MAX_DIF_FORMALIDAD for a in ancla_o_base)]
    return sorted(utiles or candidatas, key=puntuacion, reverse=True)[:k]


def _combinaciones(ancla: Prenda, pools: dict[str, list[Prenda]], modo: str):
    """Genera listas de prendas alrededor de un ancla."""
    k = config.SOCIOS_POR_SLOT
    tops, bottoms, dresses = pools["Top"], pools["Bottom"], pools["Dress"]
    cat = ancla.main_category

    if cat == "Dress":
        bases = [(ancla,)]
    elif cat == "Top":
        bases = [(ancla, b) for b in _mejores([ancla], bottoms, k)]
    elif cat == "Bottom":
        bases = [(t, ancla) for t in _mejores([ancla], tops, k)]
    else:   # chaqueta / calzado / complemento como ancla: se busca la mejor base alrededor
        todas = [(t, b) for t in tops for b in bottoms] + [(d,) for d in dresses]
        bases = sorted(todas, key=lambda base: _media([compat_pareja(ancla, x) for x in base]) +
                       (compat_pareja(*base) if len(base) == 2 else 0), reverse=True)[:2 * k]

    for base in bases:
        zapatos = [ancla] if cat == "Footwear" else (_mejores(base, pools["Footwear"], k) or [None])
        if cat == "Outerwear":
            chaquetas: list[Optional[Prenda]] = [ancla]
        elif modo == "obligatoria":
            chaquetas = _mejores(base, pools["Outerwear"], k) or [None]
        elif modo == "opcional":
            chaquetas = [None] + _mejores(base, pools["Outerwear"], 3)
        else:
            chaquetas = [None]
        complementos = [ancla] if cat == "Accessory" else [None] + _mejores(base, pools["Accessory"], 2)
        for z, ch, co in itertools.product(zapatos, chaquetas, complementos):
            yield [*base, *(x for x in (z, ch, co) if x is not None)]


# ================================================================ puntuación
def _razones(prendas: list[Prenda], partes: dict, ctx: Contexto, ev_fit: Optional[float],
             nov: float, sim: Optional[dict]) -> list[str]:
    r: list[str] = []
    if partes["color"] >= 0.85:
        r.append("Paleta de colores armoniosa")
    elif partes["color"] < 0.6:
        r.append("Los colores contrastan bastante")
    if partes["formalidad"] >= 0.75:
        r.append("Nivel de formalidad homogéneo")
    comunes = set.intersection(*(set(p.style_aesthetics) for p in prendas))
    if comunes:
        r.append("Estilo común: " + ", ".join(sorted(comunes)))
    if partes["estampados"] < 0.6:
        r.append("Mezcla varios estampados (puede recargar)")
    if partes["proporcion"] >= 0.95:
        r.append("Proporciones equilibradas (ajustado + amplio)")
    r.append(f"Adecuado para {ctx.t:.0f} °C")
    if any(p.main_category == "Outerwear" for p in prendas):
        motivo = "lluvia" if ctx.clima.get("rainy") else "nieve" if ctx.clima.get("snowy") else \
                 "viento" if ctx.clima.get("windy") else f"{ctx.t:.0f} °C"
        r.append(f"Incluye chaqueta por {motivo}")
    if ev_fit is not None and ev_fit >= 0.75:
        r.append(f"Encaja con «{config.EVENTOS[ctx.evento]['nombre']}»")
    if sim and sim.get("excede_dislike"):
        r.append("Se parece a looks que descartaste (penalizado)")
    elif sim and sim.get("alto"):
        r.append("Se parece a los looks que te gustan")
    if nov >= 0.999:
        r.append("No lo has llevado últimamente")
    elif nov < 0.6:
        r.append("Repite prendas de un outfit reciente")
    return r


def generar(prendas: list[Prenda], clima: dict, *, perfil: Optional[PerfilGusto] = None,
            historial: Sequence[dict] = (), evento: Optional[str] = None,
            ancla_tag: Optional[str] = None, n: int = config.OUTFITS_POR_PETICION,
            hoy: Optional[date] = None, embedder: str = config.EMBEDDER) -> tuple[list[Outfit], list[str]]:
    """Devuelve (outfits ordenados por puntuación, notas explicativas para el usuario)."""
    notas: list[str] = []
    if not prendas:
        return [], ["No hay prendas registradas todavía."]
    ctx = Contexto(clima=clima, t=float(clima["t_ref"]), evento=evento or None, perfil=perfil,
                   historial=historial, hoy=hoy or date.today(), embedder=embedder)
    if ctx.evento and ctx.evento not in config.EVENTOS:
        notas.append(f"Evento desconocido «{ctx.evento}»: se ignora.")
        ctx.evento = None

    pools = _preparar_pools(prendas, ctx, notas)
    modo = _modo_chaqueta(ctx)
    if modo == "obligatoria" and not pools["Outerwear"]:
        notas.append("Hace falta chaqueta pero no hay ninguna adecuada disponible.")
    if not pools["Footwear"]:
        notas.append("No hay calzado adecuado disponible: los outfits no incluyen calzado.")

    # --- ancla: elegida por el usuario, o se prueban todas las prendas "base"
    anclas: list[Prenda]
    if ancla_tag:
        a = next((p for p in prendas if p.tag_id == ancla_tag), None)
        if a is None:
            notas.append("La prenda ancla elegida no existe; se ha ignorado.")
        elif not a.disponible:
            notas.append(f"«{a.nombre}» no está en el armario ahora mismo; se ha ignorado como ancla.")
            a = None
        elif not _apta_temp(a, ctx.t):
            notas.append(f"«{a.nombre}» está fuera de su rango recomendado para {ctx.t:.0f} °C.")
        anclas = [a] if a else []
        if a:   # el ancla ocupa su categoría aunque el filtro la hubiera descartado
            pools[a.main_category] = [a]
    else:
        anclas = []
    if not anclas:
        anclas = pools["Top"] + pools["Dress"]
        if not anclas:
            notas.append("Con este clima/evento no hay camisetas, jerséis ni vestidos aptos disponibles.")
            return [], notas

    # --- candidatos (sin duplicados)
    vistos: set[frozenset[str]] = set()
    candidatos: list[list[Prenda]] = []
    for a in anclas:
        for combo in _combinaciones(a, pools, modo):
            clave = frozenset(p.tag_id for p in combo)
            tiene_base = any(p.main_category == "Dress" for p in combo) or \
                {"Top", "Bottom"} <= {p.main_category for p in combo}
            if clave not in vistos and tiene_base:
                vistos.add(clave)
                candidatos.append(combo)
    if not candidatos:
        notas.append("No se pudo formar ningún conjunto completo (falta parte de arriba o de abajo).")
        return [], notas

    # --- puntuar: pasada 1 (coherencia, novedad, similitud cruda)
    filas = []
    for combo in candidatos:
        est, partes = puntuar_estetica(combo)
        ev_fit = evento_fit(combo, ctx.evento)
        contexto = _media([clima_fit(combo, ctx)] + ([ev_fit] if ev_fit is not None else []))
        coh = (1 - config.W_CONTEXTO) * est + config.W_CONTEXTO * contexto

        vec = vector_outfit(combo, ctx.embedder)
        sim_p = perfil.similitud(vec) if perfil and perfil.conocido else None
        sim_l = coseno(vec, perfil.media_likes) if perfil and perfil.conocido else None
        sim_d = coseno(vec, perfil.media_dislikes) if perfil and perfil.conocido else None
        filas.append({"combo": combo, "coh": coh, "partes": partes, "ev_fit": ev_fit,
                      "nov": novedad(combo, ctx), "sim_p": sim_p, "sim_l": sim_l, "sim_d": sim_d})

    # --- pasada 2: afinidad. El coseno CLIP entre fotos de moda ocupa un rango estrecho, así
    # que se reescala (min-max) entre los candidatos de ESTA petición para que 0-1 discrimine.
    crudas = [f["sim_p"] for f in filas if f["sim_p"] is not None]
    lo, hi = (min(crudas), max(crudas)) if crudas else (0.0, 0.0)
    for f in filas:
        if f["sim_p"] is None or hi - lo < 1e-6:
            f["afi"], f["sim_info"] = 0.5, {}
            continue
        afi = (f["sim_p"] - lo) / (hi - lo)
        excede = f["sim_l"] is not None and f["sim_d"] is not None and f["sim_d"] > f["sim_l"]
        if excede:   # se parece más a lo que descartaste que a lo que te gusta
            afi -= min(config.DISLIKE_PENAL_MAX, (f["sim_d"] - f["sim_l"]) * config.DISLIKE_PENAL_ESCALA)
        f["afi"] = max(0.0, afi)
        f["sim_info"] = {"excede_dislike": excede, "alto": afi >= 0.75}
    if perfil is not None and not perfil.conocido:
        notas.append(f"Aún no conozco bien tus gustos ({perfil.n_likes + perfil.n_dislikes}/{config.MIN_SWIPES} "
                     "swipes): la afinidad es neutra. Desliza más fotos en «Gustos».")
    elif perfil is not None and not crudas:
        notas.append("Las prendas no tienen vector FashionCLIP: la afinidad es neutra.")

    for f in filas:
        f["total"] = (config.W_COHERENCIA * f["coh"] + config.W_AFINIDAD * f["afi"] + config.W_NOVEDAD * f["nov"])
    filas.sort(key=lambda f: f["total"], reverse=True)

    # --- selección diversa: no repetir la misma prenda base (relaja si faltan outfits)
    elegidas: list[dict] = []
    for max_uso in (1, 2, 99):
        uso: dict[str, int] = {}
        elegidas = []
        for f in filas:
            base_ids = [p.tag_id for p in f["combo"] if p.main_category in ("Top", "Bottom", "Dress")]
            if all(uso.get(i, 0) < max_uso for i in base_ids):
                elegidas.append(f)
                for i in base_ids:
                    uso[i] = uso.get(i, 0) + 1
            if len(elegidas) == n:
                break
        if len(elegidas) == n:
            break

    outfits = []
    for f in elegidas:
        outfits.append(Outfit(
            prendas=f["combo"], score=round(f["total"], 3), coherencia=round(f["coh"], 3),
            afinidad=round(f["afi"], 3), novedad=round(f["nov"], 3), evento=ctx.evento,
            fecha=ctx.hoy.isoformat(),
            razones=_razones(f["combo"], f["partes"], ctx, f["ev_fit"], f["nov"], f["sim_info"]),
            detalle={"estetica": {k: round(v, 3) for k, v in f["partes"].items()},
                     "evento": None if f["ev_fit"] is None else round(f["ev_fit"], 3),
                     "similitud_perfil": None if f["sim_p"] is None else round(f["sim_p"], 4)}))
    return outfits, notas
