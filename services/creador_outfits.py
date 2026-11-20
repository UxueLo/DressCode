"""Algoritmo de creación de outfits (puro: sin BD, sin red; fácil de probar).

1) Filtra prendas aptas para el clima.  2) Combina por categorías.
3) Puntúa color, estampados, estilo, formalidad y clima.  4) Elige los mejores y variados.
"""
from __future__ import annotations

import itertools
import config
from models.garment import FABRIC_WEIGHTS, TEMP_LEVELS, Garment, norm

NEUTRALS = {"negro", "blanco", "gris", "beige", "crema", "marron", "azul marino",
            "denim", "plata", "camel", "caqui"}
HARMONY = {frozenset(p) for p in [
    ("azul", "naranja"), ("azul", "beige"), ("verde", "marron"), ("rojo", "azul marino"),
    ("rosa", "gris"), ("amarillo", "gris"), ("verde", "beige"), ("morado", "gris"),
    ("rojo", "negro"), ("azul", "amarillo"), ("rosa", "verde"),
]}
IDEAL_WEIGHT = [2.0, 1.5, 1.0, 0.5, 0.0]  # peso de tela ideal por nivel de temperatura


# ------------------------------------------------------------------ métricas
def color_compat(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if a in NEUTRALS or b in NEUTRALS:
        return 0.95
    if a == b:
        return 0.85
    if frozenset((a, b)) in HARMONY:
        return 0.9
    return 0.35


def weather_fit(g: Garment, w: dict) -> float:
    """0 = no apta; 1 = ideal para el clima del día."""
    day = TEMP_LEVELS.index(w["category"])
    gw = g.context.weather
    dist = abs(TEMP_LEVELS.index(gw.temperature_category) - day)
    if dist > 1:
        return 0.0
    base = 1.0 if dist == 0 else 0.6
    fabric = 1 - min(1.0, abs(FABRIC_WEIGHTS.index(gw.fabric_weight) - IDEAL_WEIGHT[day]) / 2)
    score = 0.7 * base + 0.3 * fabric
    protects = " ".join(norm(p) for p in gw.protects_against)
    if w["rainy"] and "lluvia" in protects:
        score += 0.2
    if w["windy"] and "viento" in protects:
        score += 0.1
    return min(1.0, score)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 1.0


def _overlap(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def score_outfit(items: list[Garment], w: dict, style: str | None) -> tuple[float, list[str]]:
    pairs = list(itertools.combinations(items, 2))
    color = _mean([color_compat(a.visuals.primary_color, b.visuals.primary_color) for a, b in pairs])
    patterned = sum(1 for g in items if norm(g.visuals.pattern) != "liso")
    pattern = 1.0 if patterned <= 1 else 0.4
    style_coh = _mean([_overlap(a.styles, b.styles) for a, b in pairs])
    levels = [g.context.formality_level for g in items]
    formality = 1 - (max(levels) - min(levels)) / 4
    weather = _mean([weather_fit(g, w) for g in items])

    if style:
        req = sum(1 for g in items if g.has_style(style)) / len(items)
        total = (0.22 * color + 0.08 * pattern + 0.15 * style_coh +
                 0.10 * formality + 0.15 * weather + 0.30 * req)
    else:
        total = 0.30 * color + 0.10 * pattern + 0.25 * style_coh + 0.15 * formality + 0.20 * weather

    reasons: list[str] = []
    if color >= 0.85:
        reasons.append("Paleta de colores armoniosa")
    if patterned > 1:
        reasons.append("Combina varios estampados (puede resultar recargado)")
    common = set.intersection(*(g.styles for g in items)) if items else set()
    if common:
        reasons.append("Estilo común: " + ", ".join(s.capitalize() for s in sorted(common)))
    if formality >= 0.75:
        reasons.append("Nivel de formalidad homogéneo")
    reasons.append(f"Adecuado para {w['t_avg']:.0f} °C ({w['category'].lower()})")
    if w["rainy"] and any("lluvia" in norm(" ".join(g.context.weather.protects_against)) for g in items):
        reasons.append("Protege de la lluvia")
    if style and any(g.has_style(style) for g in items):
        reasons.append(f"Encaja con el estilo {style}")
    return round(total, 3), reasons


# ------------------------------------------------------------------ generación
def _select_diverse(scored: list[dict], n: int) -> list[dict]:
    """Prefiere outfits que no repitan la misma prenda base; relaja el límite si faltan."""
    chosen: list[dict] = []
    for max_reuse in (1, 2, 99):
        usage: dict[str, int] = {}
        chosen = []
        for cand in scored:
            base_ids = [g.tag_id for g in cand["garments"] if g.main_category in ("Top", "Bottom", "Dress")]
            if all(usage.get(i, 0) < max_reuse for i in base_ids):
                chosen.append(cand)
                for i in base_ids:
                    usage[i] = usage.get(i, 0) + 1
            if len(chosen) == n:
                return chosen
    return chosen


def generate(garments: list[Garment], w: dict, style: str | None = None,
             n: int = config.OUTFITS_PER_REQUEST) -> dict:
    """Devuelve {"outfits": [...], "notes": [...]} con las mejores combinaciones."""
    notes: list[str] = []
    if not garments:
        return {"outfits": [], "notes": ["No hay prendas en el armario (todas están fuera o no hay registradas)."]}

    day = TEMP_LEVELS.index(w["category"])
    by_cat: dict[str, list[Garment]] = {}
    for g in garments:
        if weather_fit(g, w) > 0:
            by_cat.setdefault(g.main_category, []).append(g)

    def rank(g: Garment) -> float:
        return weather_fit(g, w) + (0.3 if style and g.has_style(style) else 0.0)

    for cat in by_cat:  # poda para que el producto cartesiano sea manejable
        by_cat[cat] = sorted(by_cat[cat], key=rank, reverse=True)[:config.MAX_PER_CATEGORY]

    tops, bottoms = by_cat.get("Top", []), by_cat.get("Bottom", [])
    bases = [(t, b) for t in tops for b in bottoms] + [(d,) for d in by_cat.get("Dress", [])]
    if not bases:
        return {"outfits": [], "notes": ["No hay prendas aptas para este clima que permitan "
                                          "formar una base (top + bottom o vestido)."]}

    shoes_opts = by_cat.get("Footwear") or [None]
    if shoes_opts == [None]:
        notes.append("No hay calzado apto disponible: los outfits no incluyen calzado.")

    outer = by_cat.get("Outerwear", [])
    needs_outer = day <= 1 or w["rainy"] or w["windy"]
    if needs_outer:
        outer_opts = outer or [None]
        if not outer:
            notes.append("Hace falta abrigo pero no tienes ninguna prenda de abrigo apta disponible.")
    elif day == 2:
        outer_opts = [None] + outer
    else:
        outer_opts = [None]

    scored: list[dict] = []
    for base, shoes, jacket in itertools.product(bases, shoes_opts, outer_opts):
        items = [*base] + ([shoes] if shoes else []) + ([jacket] if jacket else [])
        if style and not any(g.has_style(style) for g in items):
            continue
        score, reasons = score_outfit(items, w, style)
        scored.append({"score": score, "reasons": reasons, "garments": items})

    scored.sort(key=lambda c: c["score"], reverse=True)
    best = _select_diverse(scored, n)
    if style and not best:
        notes.append(f"Ninguna prenda disponible encaja con el estilo «{style}».")
    outfits = [{"score": c["score"], "reasons": c["reasons"],
                "items": [g.to_card() for g in c["garments"]]} for c in best]
    return {"outfits": outfits, "notes": notes}
