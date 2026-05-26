import sqlite3
from pathlib import Path
from typing import Any

from app.core.paths import DB_PATH, ensure_data_dirs


def get_connection() -> sqlite3.Connection:
    ensure_data_dirs()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                source_path TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                tag TEXT NOT NULL DEFAULT '未分类',
                section TEXT NOT NULL DEFAULT '中间段',
                start_seconds REAL NOT NULL DEFAULT 0,
                end_seconds REAL NOT NULL DEFAULT 0,
                duration_seconds REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _ensure_column(connection, "materials", "source_path", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "materials", "start_seconds", "REAL NOT NULL DEFAULT 0")
        _ensure_column(connection, "materials", "end_seconds", "REAL NOT NULL DEFAULT 0")
        _ensure_column(connection, "materials", "section", "TEXT NOT NULL DEFAULT '中间段'")


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def add_material(
    *,
    source_name: str,
    file_path: Path,
    source_path: Path,
    kind: str,
    tag: str = "未分类",
    section: str = "中间段",
    start_seconds: float = 0,
    end_seconds: float = 0,
    duration_seconds: float = 0,
) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO materials (
                source_name, file_path, source_path, kind, tag, section,
                start_seconds, end_seconds, duration_seconds
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_name,
                str(file_path),
                str(source_path),
                kind,
                tag,
                section,
                start_seconds,
                end_seconds,
                duration_seconds,
            ),
        )
        return int(cursor.lastrowid)


def get_material(material_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id, source_name, file_path, source_path, kind, tag, section,
                start_seconds, end_seconds, duration_seconds, created_at
            FROM materials
            WHERE id = ?
            """,
            (material_id,),
        ).fetchone()
        return dict(row) if row else None


def get_materials_by_ids(material_ids: list[int]) -> list[dict[str, Any]]:
    if not material_ids:
        return []
    placeholders = ",".join("?" for _ in material_ids)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                id, source_name, file_path, source_path, kind, tag, section,
                start_seconds, end_seconds, duration_seconds, created_at
            FROM materials
            WHERE id IN ({placeholders})
            """,
            tuple(material_ids),
        ).fetchall()
    by_id = {int(row["id"]): dict(row) for row in rows}
    return [by_id[material_id] for material_id in material_ids if material_id in by_id]


def update_material_timing(
    *,
    material_id: int,
    file_path: Path,
    start_seconds: float,
    end_seconds: float,
    duration_seconds: float,
) -> dict[str, Any]:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE materials
            SET file_path = ?, start_seconds = ?, end_seconds = ?, duration_seconds = ?
            WHERE id = ?
            """,
            (str(file_path), start_seconds, end_seconds, duration_seconds, material_id),
        )
    material = get_material(material_id)
    if material is None:
        raise ValueError(f"Material {material_id} not found after update.")
    return material


def update_material_tag(*, material_id: int, tag: str) -> dict[str, Any]:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE materials
            SET tag = ?
            WHERE id = ?
            """,
            (tag, material_id),
        )
    material = get_material(material_id)
    if material is None:
        raise ValueError(f"Material {material_id} not found after tag update.")
    return material


def update_material_section(*, material_id: int, section: str) -> dict[str, Any]:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE materials
            SET section = ?
            WHERE id = ?
            """,
            (section, material_id),
        )
    material = get_material(material_id)
    if material is None:
        raise ValueError(f"Material {material_id} not found after section update.")
    return material


def list_materials() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id, source_name, file_path, source_path, kind, tag, section,
                start_seconds, end_seconds, duration_seconds, created_at
            FROM materials
            ORDER BY id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def list_materials_for_matching() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id, source_name, file_path, source_path, kind, tag, section,
                start_seconds, end_seconds, duration_seconds, created_at
            FROM materials
            WHERE kind = 'video_clip'
            ORDER BY id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
