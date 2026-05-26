import json
import sqlite3
from pathlib import Path
from typing import Any

from app.core.paths import DB_PATH, ensure_data_dirs


def get_connection() -> sqlite3.Connection:
    ensure_data_dirs()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_workspace_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '默认',
                custom_prompt TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                local_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                thumbnail_path TEXT NOT NULL DEFAULT '',
                duration_seconds REAL NOT NULL DEFAULT 0,
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                fps REAL NOT NULL DEFAULT 0,
                transcript TEXT NOT NULL DEFAULT '',
                transcript_segments TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'imported',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                video_id INTEGER NOT NULL,
                segment_index TEXT NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                semantic_type TEXT NOT NULL DEFAULT '过渡',
                position_type TEXT NOT NULL DEFAULT '中间',
                visual_description TEXT NOT NULL DEFAULT '',
                thumbnail_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(video_id) REFERENCES videos(id)
            );

            CREATE TABLE IF NOT EXISTS mix_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                target_duration REAL NOT NULL DEFAULT 30,
                style TEXT NOT NULL DEFAULT '',
                target_audience TEXT NOT NULL DEFAULT '',
                narrative_structure TEXT NOT NULL DEFAULT '',
                strategy_description TEXT NOT NULL DEFAULT '',
                strategy_reasoning TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS mix_schemes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                strategy_id INTEGER,
                name TEXT NOT NULL,
                scheme_description TEXT NOT NULL DEFAULT '',
                estimated_duration REAL NOT NULL DEFAULT 0,
                style TEXT NOT NULL DEFAULT '',
                target_audience TEXT NOT NULL DEFAULT '',
                narrative_structure TEXT NOT NULL DEFAULT '',
                differentiation TEXT NOT NULL DEFAULT '',
                strategy_reasoning TEXT NOT NULL DEFAULT '',
                variation_index INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(strategy_id) REFERENCES mix_strategies(id)
            );

            CREATE TABLE IF NOT EXISTS scheme_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scheme_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                reasoning TEXT NOT NULL DEFAULT '',
                position_reasoning TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(scheme_id) REFERENCES mix_schemes(id),
                FOREIGN KEY(segment_id) REFERENCES segments(id)
            );
            """
        )
        _ensure_column(connection, "projects", "category", "TEXT NOT NULL DEFAULT '默认'")
        _ensure_column(connection, "videos", "transcript_segments", "TEXT NOT NULL DEFAULT '[]'")
        _seed_settings(connection)


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _seed_settings(connection: sqlite3.Connection) -> None:
    default_whisper_model_path = Path.home() / "Library/Caches/ai-video-editor/whisper-models/ggml-large-v3-turbo.bin"
    defaults = {
        "ai_provider": "compatible",
        "ai_preset": "deepseek",
        "ai_base_url": "https://api.deepseek.com",
        "ai_api_key": "",
        "ai_model": "deepseek-chat",
        "ai_json_mode": "true",
        "asr_provider": "local_whisper",
        "asr_base_url": "",
        "asr_api_key": "",
        "asr_model": "",
        "local_whisper_binary_path": "",
        "local_whisper_model_path": str(default_whisper_model_path) if default_whisper_model_path.exists() else "",
        "local_whisper_language": "zh",
        "aliyun_access_key_id": "",
        "aliyun_access_key_secret": "",
        "aliyun_app_key": "",
        "aliyun_region": "cn-shanghai",
    }
    for key, value in defaults.items():
        connection.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    current_asr = connection.execute("SELECT value FROM settings WHERE key = 'asr_provider'").fetchone()
    has_asr_config = any(
        connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()["value"]
        for key in ("asr_api_key", "aliyun_access_key_id", "aliyun_access_key_secret", "aliyun_app_key")
    )
    if current_asr and current_asr["value"] == "manual_transcript" and not has_asr_config:
        connection.execute("UPDATE settings SET value = 'local_whisper' WHERE key = 'asr_provider'")
    connection.execute("UPDATE settings SET value = 'compatible' WHERE key = 'ai_provider' AND value = 'openai_compatible'")
    current_asr = connection.execute("SELECT value FROM settings WHERE key = 'asr_provider'").fetchone()
    if current_asr and current_asr["value"] == "aliyun_nls" and not has_asr_config:
        connection.execute("UPDATE settings SET value = 'local_whisper' WHERE key = 'asr_provider'")
    current_asr = connection.execute("SELECT value FROM settings WHERE key = 'asr_provider'").fetchone()
    if current_asr and current_asr["value"] in {"aliyun_nls", "local_whisper"}:
        connection.execute("UPDATE settings SET value = '' WHERE key = 'asr_base_url' AND value LIKE '%openai%'")
        connection.execute("UPDATE settings SET value = '' WHERE key = 'asr_model' AND value = 'whisper-1'")
    connection.execute("UPDATE settings SET value = 'whisper_compatible' WHERE key = 'asr_provider' AND value = 'openai_whisper_compatible'")
    if default_whisper_model_path.exists():
        connection.execute(
            "UPDATE settings SET value = ? WHERE key = 'local_whisper_model_path' AND value = ''",
            (str(default_whisper_model_path),),
        )


def get_settings(*, masked: bool = False) -> dict[str, str]:
    init_workspace_db()
    with get_connection() as connection:
        rows = connection.execute("SELECT key, value FROM settings").fetchall()
    values = {str(row["key"]): str(row["value"]) for row in rows}
    if masked:
        for key in ("ai_api_key", "asr_api_key", "aliyun_access_key_secret"):
            values[key] = _mask_secret(values.get(key, ""))
        values["aliyun_access_key_id"] = _mask_secret(values.get("aliyun_access_key_id", ""))
    return values


def update_settings(values: dict[str, str]) -> dict[str, str]:
    init_workspace_db()
    allowed = set(get_settings(masked=False))
    with get_connection() as connection:
        for key, value in values.items():
            if key not in allowed:
                continue
            if value == "********":
                continue
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
    return get_settings(masked=True)


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}****{value[-4:]}"


def create_project(name: str, custom_prompt: str = "", category: str = "默认") -> dict[str, Any]:
    init_workspace_db()
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO projects (name, custom_prompt, category) VALUES (?, ?, ?)",
            (name, custom_prompt, category or "默认"),
        )
        project_id = int(cursor.lastrowid)
    return get_project(project_id) or {}


def update_project(project_id: int, **values: Any) -> dict[str, Any] | None:
    allowed = {"name", "category", "custom_prompt", "status"}
    clean = {key: value for key, value in values.items() if key in allowed}
    if clean:
        clean["updated_at"] = "CURRENT_TIMESTAMP"
        assignments = []
        params: list[Any] = []
        for key, value in clean.items():
            if key == "updated_at":
                assignments.append("updated_at = CURRENT_TIMESTAMP")
            else:
                assignments.append(f"{key} = ?")
                params.append(value)
        params.append(project_id)
        with get_connection() as connection:
            connection.execute(f"UPDATE projects SET {', '.join(assignments)} WHERE id = ?", tuple(params))
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    init_workspace_db()
    with get_connection() as connection:
        exists = connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not exists:
            return False
        connection.execute(
            "DELETE FROM scheme_segments WHERE scheme_id IN (SELECT id FROM mix_schemes WHERE project_id = ?)",
            (project_id,),
        )
        connection.execute("DELETE FROM mix_schemes WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM mix_strategies WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM segments WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM videos WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return True


def list_projects() -> list[dict[str, Any]]:
    init_workspace_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                p.*,
                COUNT(DISTINCT v.id) AS video_count,
                COUNT(DISTINCT s.id) AS segment_count,
                COUNT(DISTINCT ms.id) AS scheme_count
            FROM projects p
            LEFT JOIN videos v ON v.project_id = p.id
            LEFT JOIN segments s ON s.project_id = p.id
            LEFT JOIN mix_schemes ms ON ms.project_id = p.id
            GROUP BY p.id
            ORDER BY p.updated_at DESC, p.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_project(project_id: int) -> dict[str, Any] | None:
    init_workspace_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                p.*,
                COUNT(DISTINCT v.id) AS video_count,
                COUNT(DISTINCT s.id) AS segment_count,
                COUNT(DISTINCT ms.id) AS scheme_count
            FROM projects p
            LEFT JOIN videos v ON v.project_id = p.id
            LEFT JOIN segments s ON s.project_id = p.id
            LEFT JOIN mix_schemes ms ON ms.project_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
            """,
            (project_id,),
        ).fetchone()
    return dict(row) if row else None


def touch_project(project_id: int, status: str | None = None) -> None:
    with get_connection() as connection:
        if status:
            connection.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP, status = ? WHERE id = ?",
                (status, project_id),
            )
        else:
            connection.execute("UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))


def add_video(project_id: int, data: dict[str, Any]) -> dict[str, Any]:
    init_workspace_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO videos (
                project_id, name, local_path, content_hash, thumbnail_path,
                duration_seconds, width, height, fps, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                data["name"],
                data["local_path"],
                data["content_hash"],
                data.get("thumbnail_path", ""),
                data.get("duration_seconds", 0),
                data.get("width", 0),
                data.get("height", 0),
                data.get("fps", 0),
                data.get("status", "imported"),
            ),
        )
        video_id = int(cursor.lastrowid)
    touch_project(project_id)
    return get_video(video_id) or {}


def list_videos(project_id: int) -> list[dict[str, Any]]:
    init_workspace_db()
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM videos WHERE project_id = ? ORDER BY created_at DESC, id DESC",
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_video(video_id: int) -> dict[str, Any] | None:
    init_workspace_db()
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    return dict(row) if row else None


def update_video(video_id: int, **values: Any) -> dict[str, Any]:
    if not values:
        video = get_video(video_id)
        return video or {}
    assignments = ", ".join(f"{key} = ?" for key in values)
    params = [str(value) if isinstance(value, Path) else value for value in values.values()]
    params.append(video_id)
    with get_connection() as connection:
        connection.execute(f"UPDATE videos SET {assignments} WHERE id = ?", tuple(params))
    video = get_video(video_id)
    if video:
        touch_project(int(video["project_id"]))
    return video or {}


def replace_video_segments(video_id: int, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    video = get_video(video_id)
    if not video:
        return []
    project_id = int(video["project_id"])
    with get_connection() as connection:
        connection.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        for index, segment in enumerate(segments, start=1):
            connection.execute(
                """
                INSERT INTO segments (
                    project_id, video_id, segment_index, start_seconds, end_seconds,
                    text, semantic_type, position_type,
                    visual_description, thumbnail_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    video_id,
                    segment.get("segment_index") or f"seg_{index:03d}",
                    float(segment["start_seconds"]),
                    float(segment["end_seconds"]),
                    segment.get("text", ""),
                    segment.get("semantic_type", "过渡"),
                    segment.get("position_type", "中间"),
                    segment.get("visual_description", ""),
                    segment.get("thumbnail_path", ""),
                ),
            )
    touch_project(project_id)
    return list_segments(project_id)


def list_segments(
    project_id: int,
    *,
    semantic_type: str = "",
    position_type: str = "",
    video_id: int | None = None,
) -> list[dict[str, Any]]:
    init_workspace_db()
    clauses = ["s.project_id = ?"]
    params: list[Any] = [project_id]
    if semantic_type:
        clauses.append("s.semantic_type = ?")
        params.append(semantic_type)
    if position_type:
        clauses.append("s.position_type = ?")
        params.append(position_type)
    if video_id:
        clauses.append("s.video_id = ?")
        params.append(video_id)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                s.id, s.project_id, s.video_id, s.segment_index,
                s.start_seconds, s.end_seconds, s.text,
                s.semantic_type, s.position_type, s.visual_description,
                s.thumbnail_path, s.created_at,
                v.name AS video_name, v.local_path AS video_path,
                p.name AS project_name
            FROM segments s
            JOIN videos v ON v.id = s.video_id
            JOIN projects p ON p.id = s.project_id
            WHERE {' AND '.join(clauses)}
            ORDER BY s.video_id ASC, s.start_seconds ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def get_segment(segment_id: int) -> dict[str, Any] | None:
    init_workspace_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                s.id, s.project_id, s.video_id, s.segment_index,
                s.start_seconds, s.end_seconds, s.text,
                s.semantic_type, s.position_type, s.visual_description,
                s.thumbnail_path, s.created_at,
                v.name AS video_name, v.local_path AS video_path,
                p.name AS project_name
            FROM segments s
            JOIN videos v ON v.id = s.video_id
            JOIN projects p ON p.id = s.project_id
            WHERE s.id = ?
            """,
            (segment_id,),
        ).fetchone()
    return dict(row) if row else None


def get_segments_by_ids(segment_ids: list[int]) -> list[dict[str, Any]]:
    init_workspace_db()
    if not segment_ids:
        return []
    placeholders = ", ".join("?" for _ in segment_ids)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                s.id, s.project_id, s.video_id, s.segment_index,
                s.start_seconds, s.end_seconds, s.text,
                s.semantic_type, s.position_type, s.visual_description,
                s.thumbnail_path, s.created_at,
                v.name AS video_name, v.local_path AS video_path,
                p.name AS project_name
            FROM segments s
            JOIN videos v ON v.id = s.video_id
            JOIN projects p ON p.id = s.project_id
            WHERE s.id IN ({placeholders})
            """,
            tuple(segment_ids),
        ).fetchall()
    by_id = {int(row["id"]): dict(row) for row in rows}
    return [by_id[segment_id] for segment_id in segment_ids if segment_id in by_id]


def update_segment(segment_id: int, **values: Any) -> dict[str, Any] | None:
    allowed = {
        "start_seconds",
        "end_seconds",
        "text",
        "semantic_type",
        "position_type",
        "visual_description",
    }
    clean = {key: value for key, value in values.items() if key in allowed}
    if clean:
        assignments = ", ".join(f"{key} = ?" for key in clean)
        params = list(clean.values())
        params.append(segment_id)
        with get_connection() as connection:
            connection.execute(f"UPDATE segments SET {assignments} WHERE id = ?", tuple(params))
    return get_segment(segment_id)


def split_segment(segment_id: int, segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    original = get_segment(segment_id)
    if not original or not segments:
        return None
    project_id = int(original["project_id"])
    video_id = int(original["video_id"])
    created_ids: list[int] = []
    with get_connection() as connection:
        source_rows = connection.execute(
            """
            SELECT id, scheme_id, position, reasoning, position_reasoning
            FROM scheme_segments
            WHERE segment_id = ?
            ORDER BY scheme_id ASC, position DESC
            """,
            (segment_id,),
        ).fetchall()
        for index, segment in enumerate(segments, start=1):
            cursor = connection.execute(
                """
                INSERT INTO segments (
                    project_id, video_id, segment_index, start_seconds, end_seconds,
                    text, semantic_type, position_type,
                    visual_description, thumbnail_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    video_id,
                    segment.get("segment_index") or f"{original['segment_index']}_split_{index:02d}",
                    float(segment["start_seconds"]),
                    float(segment["end_seconds"]),
                    segment.get("text", ""),
                    segment.get("semantic_type", original["semantic_type"]),
                    segment.get("position_type", original["position_type"]),
                    segment.get("visual_description", original.get("visual_description", "")),
                    segment.get("thumbnail_path", ""),
                ),
            )
            created_ids.append(int(cursor.lastrowid))

        for row in source_rows:
            scheme_id = int(row["scheme_id"])
            position = int(row["position"])
            connection.execute("DELETE FROM scheme_segments WHERE id = ?", (int(row["id"]),))
            if len(created_ids) > 1:
                connection.execute(
                    "UPDATE scheme_segments SET position = position + ? WHERE scheme_id = ? AND position > ?",
                    (len(created_ids) - 1, scheme_id, position),
                )
            for offset, new_segment_id in enumerate(created_ids):
                connection.execute(
                    """
                    INSERT INTO scheme_segments (
                        scheme_id, segment_id, position, reasoning, position_reasoning
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        scheme_id,
                        new_segment_id,
                        position + offset,
                        row["reasoning"],
                        row["position_reasoning"],
                    ),
                )
            _renumber_scheme_segments(connection, scheme_id)

        connection.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
    touch_project(project_id)
    return {
        "removed_segment_id": segment_id,
        "created_segments": get_segments_by_ids(created_ids),
        "segments": list_segments(project_id),
    }


def delete_segments(segment_ids: list[int]) -> int:
    if not segment_ids:
        return 0
    placeholders = ", ".join("?" for _ in segment_ids)
    with get_connection() as connection:
        scheme_rows = connection.execute(
            f"SELECT DISTINCT scheme_id FROM scheme_segments WHERE segment_id IN ({placeholders})",
            tuple(segment_ids),
        ).fetchall()
        connection.execute(f"DELETE FROM scheme_segments WHERE segment_id IN ({placeholders})", tuple(segment_ids))
        cursor = connection.execute(f"DELETE FROM segments WHERE id IN ({placeholders})", tuple(segment_ids))
        affected = int(cursor.rowcount or 0)
        for row in scheme_rows:
            _renumber_scheme_segments(connection, int(row["scheme_id"]))
    return affected


def create_scheme_set(project_id: int, schemes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    init_workspace_db()
    created: list[int] = []
    with get_connection() as connection:
        connection.execute("DELETE FROM scheme_segments WHERE scheme_id IN (SELECT id FROM mix_schemes WHERE project_id = ?)", (project_id,))
        connection.execute("DELETE FROM mix_schemes WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM mix_strategies WHERE project_id = ?", (project_id,))
        strategy_cache: dict[str, int] = {}
        for scheme_index, scheme in enumerate(schemes, start=1):
            strategy = scheme.get("strategy", {})
            strategy_group = str(
                scheme.get("strategy_group_index")
                or strategy.get("name")
                or scheme.get("name")
                or scheme_index
            )
            if strategy_group in strategy_cache:
                strategy_id = strategy_cache[strategy_group]
            else:
                strategy_cursor = connection.execute(
                    """
                    INSERT INTO mix_strategies (
                        project_id, name, target_duration, style, target_audience,
                        narrative_structure, strategy_description, strategy_reasoning
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        strategy.get("name") or scheme.get("name") or f"策略 {scheme_index}",
                        float(strategy.get("target_duration") or scheme.get("estimated_duration") or 30),
                        strategy.get("style") or scheme.get("style", ""),
                        strategy.get("target_audience") or scheme.get("target_audience", ""),
                        strategy.get("narrative_structure") or scheme.get("narrative_structure", ""),
                        strategy.get("description") or scheme.get("scheme_description", ""),
                        strategy.get("reasoning") or scheme.get("strategy_reasoning", ""),
                    ),
                )
                strategy_id = int(strategy_cursor.lastrowid)
                strategy_cache[strategy_group] = strategy_id
            scheme_cursor = connection.execute(
                """
                INSERT INTO mix_schemes (
                    project_id, strategy_id, name, scheme_description, estimated_duration,
                    style, target_audience, narrative_structure, differentiation,
                    strategy_reasoning, variation_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    strategy_id,
                    scheme.get("name") or f"方案 {scheme_index}",
                    scheme.get("scheme_description", ""),
                    float(scheme.get("estimated_duration", 0)),
                    scheme.get("style", ""),
                    scheme.get("target_audience", ""),
                    scheme.get("narrative_structure", ""),
                    scheme.get("differentiation", ""),
                    scheme.get("strategy_reasoning", ""),
                    int(scheme.get("variation_index", scheme_index)),
                ),
            )
            scheme_id = int(scheme_cursor.lastrowid)
            created.append(scheme_id)
            for position, item in enumerate(scheme.get("segments", []), start=1):
                connection.execute(
                    """
                    INSERT INTO scheme_segments (
                        scheme_id, segment_id, position, reasoning, position_reasoning
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        scheme_id,
                        int(item["segment_id"]),
                        position,
                        item.get("reasoning", ""),
                        item.get("position_reasoning", ""),
                    ),
                )
    touch_project(project_id)
    return [get_scheme(scheme_id) for scheme_id in created if get_scheme(scheme_id)]


def list_schemes(project_id: int) -> list[dict[str, Any]]:
    init_workspace_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                ms.*,
                COUNT(ss.id) AS segment_count,
                COALESCE(SUM(MAX(0, s.end_seconds - s.start_seconds)), ms.estimated_duration) AS actual_duration,
                GROUP_CONCAT(s.id) AS segment_ids
            FROM mix_schemes ms
            LEFT JOIN scheme_segments ss ON ss.scheme_id = ms.id
            LEFT JOIN segments s ON s.id = ss.segment_id
            WHERE ms.project_id = ?
            GROUP BY ms.id
            ORDER BY ms.variation_index ASC, ms.id ASC
            """,
            (project_id,),
        ).fetchall()
    return _rank_scheme_rows([dict(row) for row in rows])


def get_scheme(scheme_id: int) -> dict[str, Any] | None:
    init_workspace_db()
    with get_connection() as connection:
        scheme = connection.execute("SELECT * FROM mix_schemes WHERE id = ?", (scheme_id,)).fetchone()
        if not scheme:
            return None
        segments = connection.execute(
            """
            SELECT ss.id AS scheme_segment_id, ss.position, ss.reasoning, ss.position_reasoning,
                   s.*, v.name AS video_name, v.local_path AS video_path
            FROM scheme_segments ss
            JOIN segments s ON s.id = ss.segment_id
            JOIN videos v ON v.id = s.video_id
            WHERE ss.scheme_id = ?
            ORDER BY ss.position ASC
            """,
            (scheme_id,),
        ).fetchall()
    result = dict(scheme)
    result["segments"] = [dict(row) for row in segments]
    result["segment_count"] = len(result["segments"])
    result["actual_duration"] = sum(
        max(0, float(segment["end_seconds"]) - float(segment["start_seconds"]))
        for segment in result["segments"]
    )
    ranked = next((item for item in list_schemes(int(result["project_id"])) if int(item["id"]) == scheme_id), None)
    if ranked:
        result["repeat_rate"] = ranked.get("repeat_rate", 0)
        result["recommendation_score"] = ranked.get("recommendation_score", 100)
        result["is_recommended"] = ranked.get("is_recommended", False)
    return result


def _rank_scheme_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segment_sets: dict[int, set[int]] = {}
    for row in rows:
        raw_ids = str(row.pop("segment_ids", "") or "")
        segment_sets[int(row["id"])] = {int(item) for item in raw_ids.split(",") if item.strip().isdigit()}

    for row in rows:
        scheme_id = int(row["id"])
        current = segment_sets.get(scheme_id, set())
        repeat_rate = 0.0
        if current:
            for other_id, other in segment_sets.items():
                if other_id == scheme_id or not other:
                    continue
                repeat_rate = max(repeat_rate, len(current & other) / len(current))
        row["repeat_rate"] = round(repeat_rate, 3)
        row["recommendation_score"] = round((1 - repeat_rate) * 100, 1)

    ranked_ids = {
        int(row["id"])
        for row in sorted(rows, key=lambda item: (-float(item["recommendation_score"]), int(item["variation_index"]), int(item["id"])))[:3]
    }
    for row in rows:
        row["is_recommended"] = int(row["id"]) in ranked_ids
    return sorted(rows, key=lambda item: (not bool(item["is_recommended"]), -float(item["recommendation_score"]), int(item["variation_index"]), int(item["id"])))


def update_scheme_segment(scheme_segment_id: int, segment_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT scheme_id FROM scheme_segments WHERE id = ?",
            (scheme_segment_id,),
        ).fetchone()
        if not row:
            return None
        scheme_id = int(row["scheme_id"])
        connection.execute(
            "UPDATE scheme_segments SET segment_id = ? WHERE id = ?",
            (segment_id, scheme_segment_id),
        )
    return get_scheme(scheme_id)


def delete_scheme_segment(scheme_segment_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT scheme_id FROM scheme_segments WHERE id = ?",
            (scheme_segment_id,),
        ).fetchone()
        if not row:
            return None
        scheme_id = int(row["scheme_id"])
        connection.execute("DELETE FROM scheme_segments WHERE id = ?", (scheme_segment_id,))
        _renumber_scheme_segments(connection, scheme_id)
    return get_scheme(scheme_id)


def move_scheme_segment(scheme_segment_id: int, direction: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT scheme_id, position FROM scheme_segments WHERE id = ?",
            (scheme_segment_id,),
        ).fetchone()
        if not row:
            return None
        scheme_id = int(row["scheme_id"])
        position = int(row["position"])
        target = position + direction
        other = connection.execute(
            "SELECT id FROM scheme_segments WHERE scheme_id = ? AND position = ?",
            (scheme_id, target),
        ).fetchone()
        if other:
            connection.execute("UPDATE scheme_segments SET position = ? WHERE id = ?", (target, scheme_segment_id))
            connection.execute("UPDATE scheme_segments SET position = ? WHERE id = ?", (position, int(other["id"])))
    return get_scheme(scheme_id)


def _renumber_scheme_segments(connection: sqlite3.Connection, scheme_id: int) -> None:
    rows = connection.execute(
        "SELECT id FROM scheme_segments WHERE scheme_id = ? ORDER BY position ASC",
        (scheme_id,),
    ).fetchall()
    for index, row in enumerate(rows, start=1):
        connection.execute("UPDATE scheme_segments SET position = ? WHERE id = ?", (index, int(row["id"])))


def scheme_segment_ids(scheme_id: int) -> list[int]:
    scheme = get_scheme(scheme_id)
    if not scheme:
        return []
    return [int(item["id"]) for item in scheme["segments"]]


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
