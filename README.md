# DressCode

Armario inteligente: sabe qué ropa tienes y genera outfits para el día según **temperatura, evento, tus gustos, si las prendas combinan y si están disponibles**.

- **Prendas nuevas** → Gemini analiza la foto (categoría, color, formalidad, rango de temperatura…) y FashionCLIP guarda su vector de estilo.
- **Gustos** → swipe tipo Tinder con fotos (carpeta local, Pinterest o Unsplash). Perfil = media(likes) − 0.5·media(dislikes), en el espacio FashionCLIP.
- **Outfits** → el algoritmo de `DECISION_DE_OUFITS.pdf` (ver abajo). El lector NFC aún no está implementado: `in_use` se cambia desde la web ("Sacar/Devolver"), que simula pasar la etiqueta.

## Puesta en marcha

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # y rellena GEMINI_API_KEY
python main.py              # http://127.0.0.1:5000
```

La primera vez FashionCLIP descarga ~600 MB de Hugging Face.

### Probarlo sin API keys ni descargas

```bash
export GEMINI_MODE=fake EMBEDDER=color-hist
python scripts/seed_demo.py   # 16 prendas de ejemplo + 24 fotos de inspiración
python main.py
```

Si no tienes internet, escribe la temperatura a mano en la pestaña **Hoy**.

### Fotos para el swipe

| Fuente | Cómo |
|---|---|
| `local` | Copia imágenes en `data/inspiration/` (p. ej. tus pines descargados). |
| `pinterest` | API oficial v5: `PINTEREST_TOKEN` + `PINTEREST_BOARD_IDS` (ids de tus tableros). Requiere una app de desarrollador de Pinterest. |
| `unsplash` | `UNSPLASH_ACCESS_KEY` (gratuita). |

Se activan con `FEED_SOURCES=local,pinterest,unsplash`. No se hace scraping de Pinterest (va contra sus condiciones).

## Cómo se generan los outfits (`services/creador_outfits.py`)

1. **Filtros**: solo prendas con `in_use = False`; `temp_min ≤ T ≤ temp_max` (si una categoría se queda vacía se relaja ±3 / ±6 °C y se avisa); formalidad dentro del rango del evento ±1; con lluvia/nieve la chaqueta debe proteger si existe alguna que lo haga.
2. **Ancla**: la eliges tú o se prueban todas las camisetas/jerséis/vestidos. Socios por **diferencia de color** (rueda cromática) y **formalidad**.
3. **Chaqueta**: obligatoria por debajo de 14 °C o con lluvia/nieve/viento; opcional entre 14 y 20 °C; ninguna por encima.
4. **Puntuación**: `Score = 0.4·Coherencia + 0.4·Afinidad + 0.2·Novedad` (pesos en `config.py`)
   - *Coherencia*: reglas de color, formalidad, estilo, estampados y proporciones (80 %) + adecuación al clima/evento (20 %).
   - *Afinidad*: coseno entre el vector del outfit (media de sus prendas) y el vector de gusto, reescalado a 0–1 entre los candidatos; se penaliza si se parece más a los dislikes que a los likes. Con menos de 8 swipes es neutra (0.5).
   - *Novedad*: penaliza solapamiento con outfits usados/guardados en los últimos 14 días.
5. **Top 3** sin repetir la misma prenda base.

Aprendizaje continuo: 👍/👎 sobre un outfit generado también actualiza el perfil (peso 1.5×) y "Me lo pongo" lo anota en el historial de novedad.

## Estructura

```
main.py                  arranque (proceso Gemini+FashionCLIP, hilo planificador, web)
app.py                   API Flask + rutas
config.py                rutas, claves, pesos del algoritmo, eventos
models/ropa.py           vocabulario, Prenda, Outfit
database/db.py           SQLite: prendas, swipes, outfits, kv
services/                gemini, embeddings, meteo, feed, gustos, creador_outfits, outfit_service
workers/gemini_hilo.py   Process: ficha (Gemini) + vector (FashionCLIP) + embeddings del swipe
workers/meteo_hilo.py    Thread: outfit del día a las 00:00 y peticiones bajo demanda
workers/sensor_hilo.py   (pendiente) lector NFC
web/                     interfaz (Hoy · Armario · Gustos)
scripts/seed_demo.py     datos de demo
tests/                   pytest
```

## Tests

```bash
pip install -r requirements-dev.txt
EMBEDDER=color-hist GEMINI_MODE=fake pytest -q
```
