
import json
import sqlite3
from pathlib import Path
from typing import Optional
import models
from models.ropa import Prenda

# --- Gestión de Base de Datos SQLite ---
class ArmarioDB:
    def __init__(self, db_path: str = "data/armario.db") -> None:
        self.db_path = db_path
        # Asegura que el directorio exista antes de crear el archivo .db
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._crear_tabla()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Permite acceder a columnas por nombre
        return conn

    def _crear_tabla(self) -> None:
        #Crea la tabla de prendas si no existe
        query = """
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
            temperature_category TEXT NOT NULL,
            fabric_weight TEXT NOT NULL,
            protects_against TEXT NOT NULL
        )
        """
        with self._conectar() as conn:
            conn.execute(query)

    def guardar_prenda(self, prenda: Prenda) -> None:
        #Guarda una prenda nueva o actualiza sus datos si el tag_id ya existe.
        query = """
        INSERT OR REPLACE INTO prendas (
            tag_id, image_path, in_use, main_category, sub_category,
            primary_color, secondary_color, pattern, fit_type,
            style_aesthetics, formality_level, recommended_events,
            temperature_category, fabric_weight, protects_against
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Las listas de Python se serializan a texto JSON para guardarlas en SQLite
        valores = (
            prenda.tag_id,
            prenda.image_path,
            int(prenda.in_use),  # SQLite guarda booleanos como 0 o 1
            prenda.main_category,
            prenda.sub_category,
            prenda.primary_color,
            prenda.secondary_color,
            prenda.pattern,
            prenda.fit_type,
            json.dumps(prenda.style_aesthetics, ensure_ascii=False),
            prenda.formality_level,
            json.dumps(prenda.recommended_events, ensure_ascii=False),
            prenda.temperature_category,
            prenda.fabric_weight,
            json.dumps(prenda.protects_against, ensure_ascii=False),
        )
        with self._conectar() as conn:
            conn.execute(query, valores)

    def obtener_prenda(self, tag_id: str) -> Optional[Prenda]:
        """Recupera una prenda concreta por su RFID (tag_id). Devuelve None si no existe."""
        query = "SELECT * FROM prendas WHERE tag_id = ?"
        with self._conectar() as conn:
            row = conn.execute(query, (tag_id,)).fetchone()
            return self._fila_a_prenda(row) if row else None

    def obtener_todas(self, solo_disponibles: bool = False) -> list[Prenda]:
        """
        Recupera todas las prendas del armario.
        Si solo_disponibles=True, devuelve únicamente las que tienen in_use = False.
        """
        if solo_disponibles:
            query = "SELECT * FROM prendas WHERE in_use = 0"
        else:
            query = "SELECT * FROM prendas"

        with self._conectar() as conn:
            rows = conn.execute(query).fetchall()
            return [self._fila_a_prenda(row) for row in rows]

    def cambiar_estado_uso(self, tag_id: str, in_use: bool) -> bool:
        """
        Establece explícitamente el estado in_use (True o False) de una prenda.
        Devuelve True si se actualizó correctamente, False si el tag_id no existe.
        """
        query = "UPDATE prendas SET in_use = ? WHERE tag_id = ?"
        with self._conectar() as conn:
            cursor = conn.execute(query, (int(in_use), tag_id))
            return cursor.rowcount > 0

    def alternar_estado_uso(self, tag_id: str) -> Optional[bool]:
        """
        Invierte el booleano actual (si estaba en False pasa a True y viceversa).
        Ideal para cuando pasas la tarjeta RFID por el lector al entrar/salir.
        Devuelve el nuevo estado booleano, o None si el tag_id no existe.
        """
        prenda = self.obtener_prenda(tag_id)
        if prenda is None:
            return None
        nuevo_estado = not prenda.in_use
        self.cambiar_estado_uso(tag_id, nuevo_estado)
        return nuevo_estado