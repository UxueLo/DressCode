"""Persistencia SQLite: prendas, swipes (gustos), outfits e historial.

Cada operación abre y CIERRA su propia conexión (seguro con hilos y con el proceso de
Gemini). WAL + timeout evitan "database is locked" cuando escriben varios a la vez.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np

import config
from models.ropa import Prenda


def _vec_a_bytes(v: Optional[np.ndarray]) -> Optional[bytes]:
    return None if v is None else np.asarray(v, dtype=np.float32).tobytes()


def _bytes_a_vec(b: Optional[bytes]) -> Optional[np.ndarray]:
    return None if b is None else np.frombuffer(b, dtype=np.float32).copy()


class ArmarioDB:
    def __init__(self, db_path: str = config.DB_PATH) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._crear_tablas()

    # ------------------------------------------------------------- infraestructura
    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _crear_tablas(self) -> None:
        with self._tx() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS prendas (
                tag_id TEXT PRIMARY KEY,
                image_path TEXT NOT NULL,
                in_use INTEGER NOT NULL DEFAULT 0,
                main_category TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                primary_color TEXT NOT NULL,
                secondary_color TEXT,
                pattern TEXT NOT NULL,
                fit_type TEXT NOT NULL,
                style_aesthetics TEXT NOT NULL,
                formality_level INTEGER NOT NULL,
                recommended_events TEXT NOT NULL,
                temperature_min REAL NOT NULL,
                temperature_max REAL NOT NULL,
                fabric_weight TEXT NOT NULL,
                protects_against TEXT NOT NULL,
                vector BLOB,
                embedder TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS swipes (          -- likes/dislikes que forman el perfil de gusto
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fuente TEXT NOT NULL,                    -- 'feed' (foto) | 'outfit' (outfit propio)
                ref TEXT NOT NULL,
                image_url TEXT,
                liked INTEGER NOT NULL,
                peso REAL NOT NULL DEFAULT 1.0,
                vector BLOB NOT NULL,
                embedder TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (fuente, ref)
            );
            CREATE TABLE IF NOT EXISTS outfits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                tag_ids TEXT NOT NULL,                   -- JSON ordenado
                evento TEXT,
                score REAL NOT NULL,
                detalle TEXT NOT NULL,                   -- JSON con puntuaciones y razones
                estado TEXT NOT NULL DEFAULT 'sugerido', -- sugerido|guardado|usado|descartado
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS kv (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
            """)

    # ---------------------------------------------------------------------- prendas
    def guardar_prenda(self, prenda: Prenda) -> None:
        """Inserta la prenda o la reemplaza si el tag_id ya existe."""
        with self._tx() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO prendas (
                tag_id, image_path, in_use, main_category, sub_category, primary_color,
                secondary_color, pattern, fit_type, style_aesthetics, formality_level,
                recommended_events, temperature_min, temperature_max, fabric_weight,
                protects_against, vector, embedder
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                prenda.tag_id, prenda.image_path, int(prenda.in_use), prenda.main_category,
                prenda.sub_category, prenda.primary_color, prenda.secondary_color,
                prenda.pattern, prenda.fit_type,
                json.dumps(prenda.style_aesthetics, ensure_ascii=False), prenda.formality_level,
                json.dumps(prenda.recommended_events, ensure_ascii=False),
                prenda.temperature_min, prenda.temperature_max, prenda.fabric_weight,
                json.dumps(prenda.protects_against, ensure_ascii=False),
                _vec_a_bytes(prenda.vector), prenda.embedder,
            ))

    @staticmethod
    def _fila_a_prenda(row: sqlite3.Row) -> Prenda:
        return Prenda(
            tag_id=row["tag_id"], image_path=row["image_path"], in_use=bool(row["in_use"]),
            main_category=row["main_category"], sub_category=row["sub_category"],
            primary_color=row["primary_color"], secondary_color=row["secondary_color"],
            pattern=row["pattern"], fit_type=row["fit_type"],
            style_aesthetics=json.loads(row["style_aesthetics"]),
            formality_level=row["formality_level"],
            recommended_events=json.loads(row["recommended_events"]),
            temperature_min=row["temperature_min"], temperature_max=row["temperature_max"],
            fabric_weight=row["fabric_weight"],
            protects_against=json.loads(row["protects_against"]),
            vector=_bytes_a_vec(row["vector"]), embedder=row["embedder"],
            created_at=row["created_at"],
        )

    def obtener_prenda(self, tag_id: str) -> Optional[Prenda]:
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM prendas WHERE tag_id = ?", (tag_id,)).fetchone()
        return self._fila_a_prenda(row) if row else None

    def obtener_todas(self, solo_disponibles: bool = False) -> list[Prenda]:
        query = "SELECT * FROM prendas" + (" WHERE in_use = 0" if solo_disponibles else "")
        with self._tx() as conn:
            rows = conn.execute(query + " ORDER BY created_at, tag_id").fetchall()
        return [self._fila_a_prenda(r) for r in rows]

    def obtener_por_ids(self, tag_ids: list[str]) -> list[Prenda]:
        if not tag_ids:
            return []
        marcas = ",".join("?" * len(tag_ids))
        with self._tx() as conn:
            rows = conn.execute(f"SELECT * FROM prendas WHERE tag_id IN ({marcas})", tag_ids).fetchall()
        return [self._fila_a_prenda(r) for r in rows]

    def cambiar_estado_uso(self, tag_id: str, in_use: bool) -> bool:
        with self._tx() as conn:
            cur = conn.execute("UPDATE prendas SET in_use = ? WHERE tag_id = ?", (int(in_use), tag_id))
            return cur.rowcount > 0

    def alternar_estado_uso(self, tag_id: str) -> Optional[bool]:
        """Invierte in_use en una sola sentencia (atómico). Devuelve el nuevo estado o None."""
        with self._tx() as conn:
            cur = conn.execute("UPDATE prendas SET in_use = 1 - in_use WHERE tag_id = ?", (tag_id,))
            if cur.rowcount == 0:
                return None
            return bool(conn.execute("SELECT in_use FROM prendas WHERE tag_id = ?", (tag_id,)).fetchone()[0])

    def borrar_prenda(self, tag_id: str) -> Optional[str]:
        """Borra la prenda y devuelve la ruta de su foto (para borrar el fichero) o None."""
        with self._tx() as conn:
            row = conn.execute("SELECT image_path FROM prendas WHERE tag_id = ?", (tag_id,)).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM prendas WHERE tag_id = ?", (tag_id,))
            return row["image_path"]

    def prendas_sin_vector(self) -> list[Prenda]:
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM prendas WHERE vector IS NULL").fetchall()
        return [self._fila_a_prenda(r) for r in rows]

    def actualizar_vector(self, tag_id: str, vector: np.ndarray, embedder: str) -> None:
        with self._tx() as conn:
            conn.execute("UPDATE prendas SET vector = ?, embedder = ? WHERE tag_id = ?",
                         (_vec_a_bytes(vector), embedder, tag_id))

    # ----------------------------------------------------------------------- swipes
    def guardar_swipe(self, fuente: str, ref: str, liked: bool, vector: np.ndarray, embedder: str,
                      peso: float = 1.0, image_url: Optional[str] = None,
                      reemplazar: bool = True) -> None:
        """Guarda un like/dislike. Si (fuente, ref) ya existe, lo reemplaza o lo ignora."""
        conflicto = ("DO UPDATE SET liked=excluded.liked, peso=excluded.peso, vector=excluded.vector, "
                     "embedder=excluded.embedder, image_url=excluded.image_url, created_at=CURRENT_TIMESTAMP"
                     if reemplazar else "DO NOTHING")
        with self._tx() as conn:
            conn.execute(f"""
            INSERT INTO swipes (fuente, ref, image_url, liked, peso, vector, embedder)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT (fuente, ref) {conflicto}""",
                         (fuente, ref, image_url, int(liked), peso, _vec_a_bytes(vector), embedder))

    def obtener_swipes(self, embedder: Optional[str] = None) -> list[dict[str, Any]]:
        query, args = "SELECT * FROM swipes", ()
        if embedder:
            query, args = query + " WHERE embedder = ?", (embedder,)
        with self._tx() as conn:
            rows = conn.execute(query, args).fetchall()
        return [{"id": r["id"], "fuente": r["fuente"], "ref": r["ref"], "liked": bool(r["liked"]),
                 "peso": r["peso"], "vector": _bytes_a_vec(r["vector"])} for r in rows]

    def contar_swipes(self) -> dict[str, int]:
        with self._tx() as conn:
            r = conn.execute("SELECT COALESCE(SUM(liked),0) AS l, COUNT(*) AS t FROM swipes").fetchone()
        return {"likes": int(r["l"]), "dislikes": int(r["t"] - r["l"]), "total": int(r["t"])}

    def refs_vistos(self, fuente: str = "feed") -> set[str]:
        with self._tx() as conn:
            rows = conn.execute("SELECT ref FROM swipes WHERE fuente = ?", (fuente,)).fetchall()
        return {r["ref"] for r in rows}

    def deshacer_ultimo_swipe(self, fuente: str = "feed") -> Optional[str]:
        """Borra el último swipe de esa fuente y devuelve su ref (para volver a mostrarlo)."""
        with self._tx() as conn:
            row = conn.execute("SELECT id, ref FROM swipes WHERE fuente = ? ORDER BY id DESC LIMIT 1",
                               (fuente,)).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM swipes WHERE id = ?", (row["id"],))
            return row["ref"]

    # ---------------------------------------------------------------------- outfits
    def guardar_outfit(self, tag_ids: list[str], fecha: date, evento: Optional[str], score: float,
                       detalle: dict[str, Any], estado: str = "sugerido") -> int:
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO outfits (fecha, tag_ids, evento, score, detalle, estado) VALUES (?,?,?,?,?,?)",
                (fecha.isoformat(), json.dumps(sorted(tag_ids)), evento, score,
                 json.dumps(detalle, ensure_ascii=False), estado))
            return int(cur.lastrowid)

    @staticmethod
    def _fila_a_outfit(r: sqlite3.Row) -> dict[str, Any]:
        return {"id": r["id"], "fecha": date.fromisoformat(r["fecha"]), "tag_ids": json.loads(r["tag_ids"]),
                "evento": r["evento"], "score": r["score"], "detalle": json.loads(r["detalle"]),
                "estado": r["estado"]}

    def obtener_outfit(self, outfit_id: int) -> Optional[dict[str, Any]]:
        with self._tx() as conn:
            r = conn.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        return self._fila_a_outfit(r) if r else None

    def actualizar_estado_outfit(self, outfit_id: int, estado: str, fecha: Optional[date] = None) -> bool:
        with self._tx() as conn:
            if fecha:
                cur = conn.execute("UPDATE outfits SET estado = ?, fecha = ? WHERE id = ?",
                                   (estado, fecha.isoformat(), outfit_id))
            else:
                cur = conn.execute("UPDATE outfits SET estado = ? WHERE id = ?", (estado, outfit_id))
            return cur.rowcount > 0

    def historial_outfits(self, dias: int = config.NOVEDAD_DIAS,
                          estados: tuple[str, ...] = ("usado", "guardado"),
                          hoy: Optional[date] = None) -> list[dict[str, Any]]:
        """Outfits usados/guardados en los últimos `dias` (para penalizar repeticiones)."""
        hoy = hoy or date.today()
        marcas = ",".join("?" * len(estados))
        with self._tx() as conn:
            rows = conn.execute(f"SELECT * FROM outfits WHERE estado IN ({marcas}) ORDER BY fecha DESC",
                                estados).fetchall()
        salida = []
        for r in rows:
            o = self._fila_a_outfit(r)
            if 0 <= (hoy - o["fecha"]).days < dias:
                o["tag_ids"] = set(o["tag_ids"])
                salida.append(o)
        return salida

    def listar_outfits(self, limite: int = 30) -> list[dict[str, Any]]:
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM outfits WHERE estado != 'sugerido' "
                                "ORDER BY fecha DESC, id DESC LIMIT ?", (limite,)).fetchall()
        return [self._fila_a_outfit(r) for r in rows]

    # --------------------------------------------------------------------------- kv
    def kv_get(self, clave: str, defecto: Any = None) -> Any:
        with self._tx() as conn:
            r = conn.execute("SELECT valor FROM kv WHERE clave = ?", (clave,)).fetchone()
        return json.loads(r["valor"]) if r else defecto

    def kv_set(self, clave: str, valor: Any) -> None:
        with self._tx() as conn:
            conn.execute("INSERT INTO kv (clave, valor) VALUES (?, ?) "
                         "ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor",
                         (clave, json.dumps(valor, ensure_ascii=False)))
