import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
import aiosqlite

from .config import settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,
    shared_constraints TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_index INTEGER NOT NULL,
    mode TEXT NOT NULL,
    prompt TEXT NOT NULL,
    shared_constraints TEXT,
    models_json TEXT NOT NULL,
    chairman_spec TEXT,
    resolved_chairman TEXT,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    final_markdown TEXT DEFAULT '',
    consensus_status TEXT,
    slot_mapping_json TEXT DEFAULT '{}',
    attachments_json TEXT DEFAULT '[]',
    metrics_json TEXT DEFAULT '{}',
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id, run_index);

CREATE TABLE IF NOT EXISTS mode1_responses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    slot_index INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    status TEXT NOT NULL,
    content TEXT DEFAULT '',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    latency_ms INTEGER DEFAULT 0,
    avg_accuracy REAL,
    avg_insight REAL,
    avg_total REAL,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_m1_resp_run ON mode1_responses(run_id, slot_index);

CREATE TABLE IF NOT EXISTS mode1_ratings (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    reviewer_model_id TEXT NOT NULL,
    target_model_id TEXT NOT NULL,
    anon_label TEXT NOT NULL,
    accuracy REAL NOT NULL,
    insight REAL NOT NULL,
    critique TEXT DEFAULT '',
    latency_ms INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_m1_rat_run ON mode1_ratings(run_id);

CREATE TABLE IF NOT EXISTS mode2_turns (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    slot_number INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    is_tie_break INTEGER DEFAULT 0,
    agreed INTEGER DEFAULT 0,
    plan_version INTEGER DEFAULT 1,
    revision_notes TEXT DEFAULT '',
    plan_markdown TEXT DEFAULT '',
    raw_output TEXT DEFAULT '',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    latency_ms INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_m2_turns_run ON mode2_turns(run_id, turn_number);

CREATE TABLE IF NOT EXISTS presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    models_json TEXT NOT NULL,
    chairman_model TEXT DEFAULT 'auto',
    shared_constraints TEXT,
    created_at TEXT NOT NULL
);
"""


async def get_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(str(settings.db_path))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON;")
    return conn


async def init_db() -> None:
    conn = await get_db()
    try:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
    finally:
        await conn.close()


def _make_title(prompt: str) -> str:
    first_line = prompt.strip().splitlines()[0] if prompt.strip() else "Untitled Session"
    cleaned = " ".join(first_line.split())
    return cleaned[:90] + ("…" if len(cleaned) > 90 else "")


async def create_session_and_run(
    *,
    session_id: Optional[str],
    mode: str,
    prompt: str,
    models: list[str],
    chairman_spec: Optional[str],
    shared_constraints: Optional[str],
    attachments: list[dict[str, Any]],
) -> tuple[str, str, int]:
    conn = await get_db()
    try:
        now = utc_now_iso()
        if session_id:
            cur = await conn.execute(
                "SELECT id, mode FROM sessions WHERE id = ?", (session_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"Session {session_id} not found")
            if row["mode"] != mode:
                raise ValueError(
                    f"Session mode is '{row['mode']}', cannot run '{mode}' inside it"
                )
            cur_idx = await conn.execute(
                "SELECT COALESCE(MAX(run_index), 0) AS max_idx FROM runs WHERE session_id = ?",
                (session_id,),
            )
            idx_row = await cur_idx.fetchone()
            run_index = int(idx_row["max_idx"]) + 1
            await conn.execute(
                "UPDATE sessions SET updated_at = ?, shared_constraints = COALESCE(?, shared_constraints) WHERE id = ?",
                (now, shared_constraints, session_id),
            )
        else:
            session_id = str(uuid.uuid4())
            run_index = 1
            await conn.execute(
                """
                INSERT INTO sessions (id, title, mode, shared_constraints, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, _make_title(prompt), mode, shared_constraints, now, now),
            )

        run_id = str(uuid.uuid4())
        initial_stage = "stage1_opinions" if mode == "council" else "round_1"
        await conn.execute(
            """
            INSERT INTO runs (
                id, session_id, run_index, mode, prompt, shared_constraints,
                models_json, chairman_spec, status, stage, attachments_json,
                metrics_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, '{}', ?)
            """,
            (
                run_id,
                session_id,
                run_index,
                mode,
                prompt,
                shared_constraints,
                json.dumps(models),
                chairman_spec,
                initial_stage,
                json.dumps(attachments),
                now,
            ),
        )
        await conn.commit()
        return session_id, run_id, run_index
    finally:
        await conn.close()


async def get_prior_completed_runs(session_id: str, before_run_index: int) -> list[dict[str, Any]]:
    conn = await get_db()
    try:
        cur = await conn.execute(
            """
            SELECT id, run_index, mode, prompt, final_markdown, consensus_status
            FROM runs
            WHERE session_id = ? AND run_index < ? AND status = 'completed'
            ORDER BY run_index ASC
            """,
            (session_id, before_run_index),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def update_run_fields(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    vals = list(fields.values()) + [run_id]
    conn = await get_db()
    try:
        await conn.execute(f"UPDATE runs SET {cols} WHERE id = ?", vals)
        if "status" in fields or "final_markdown" in fields:
            await conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = (SELECT session_id FROM runs WHERE id = ?)",
                (utc_now_iso(), run_id),
            )
        await conn.commit()
    finally:
        await conn.close()


async def list_sessions(search: Optional[str] = None) -> list[dict[str, Any]]:
    conn = await get_db()
    try:
        if search and search.strip():
            q = f"%{search.strip()}%"
            cur = await conn.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*) FROM runs r WHERE r.session_id = s.id) AS run_count,
                       (SELECT r.status FROM runs r WHERE r.session_id = s.id ORDER BY r.run_index DESC LIMIT 1) AS latest_status
                FROM sessions s
                WHERE s.title LIKE ? OR EXISTS (
                    SELECT 1 FROM runs r WHERE r.session_id = s.id AND (r.prompt LIKE ? OR r.final_markdown LIKE ?)
                )
                ORDER BY s.updated_at DESC
                LIMIT 100
                """,
                (q, q, q),
            )
        else:
            cur = await conn.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*) FROM runs r WHERE r.session_id = s.id) AS run_count,
                       (SELECT r.status FROM runs r WHERE r.session_id = s.id ORDER BY r.run_index DESC LIMIT 1) AS latest_status
                FROM sessions s
                ORDER BY s.updated_at DESC
                LIMIT 100
                """
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_session_detail(session_id: str) -> Optional[dict[str, Any]]:
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        s_row = await cur.fetchone()
        if not s_row:
            return None
        session = dict(s_row)

        r_cur = await conn.execute(
            "SELECT * FROM runs WHERE session_id = ? ORDER BY run_index ASC",
            (session_id,),
        )
        run_rows = await r_cur.fetchall()
        runs = []
        for r in run_rows:
            rd = dict(r)
            rd["models"] = json.loads(rd.pop("models_json") or "[]")
            rd["slot_mapping"] = json.loads(rd.pop("slot_mapping_json") or "{}")
            rd["attachments"] = json.loads(rd.pop("attachments_json") or "[]")
            rd["metrics"] = json.loads(rd.pop("metrics_json") or "{}")

            if rd["mode"] == "council":
                m1_cur = await conn.execute(
                    "SELECT * FROM mode1_responses WHERE run_id = ? ORDER BY slot_index ASC",
                    (rd["id"],),
                )
                rd["responses"] = [dict(x) for x in await m1_cur.fetchall()]

                rat_cur = await conn.execute(
                    "SELECT * FROM mode1_ratings WHERE run_id = ? ORDER BY reviewer_model_id, anon_label",
                    (rd["id"],),
                )
                rd["ratings"] = [dict(x) for x in await rat_cur.fetchall()]
                rd["turns"] = []
            else:
                t_cur = await conn.execute(
                    "SELECT * FROM mode2_turns WHERE run_id = ? ORDER BY turn_number ASC",
                    (rd["id"],),
                )
                turns = []
                for t in await t_cur.fetchall():
                    td = dict(t)
                    td["agreed"] = bool(td["agreed"])
                    td["is_tie_break"] = bool(td["is_tie_break"])
                    turns.append(td)
                rd["turns"] = turns
                rd["responses"] = []
                rd["ratings"] = []

            runs.append(rd)

        session["runs"] = runs
        return session
    finally:
        await conn.close()


async def get_run_detail(run_id: str) -> Optional[dict[str, Any]]:
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT session_id FROM runs WHERE id = ?", (run_id,))
        row = await cur.fetchone()
        if not row:
            return None
    finally:
        await conn.close()

    session = await get_session_detail(row["session_id"])
    if not session:
        return None
    for r in session["runs"]:
        if r["id"] == run_id:
            return r
    return None


async def delete_session(session_id: str) -> bool:
    conn = await get_db()
    try:
        cur = await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await conn.commit()
        return cur.rowcount > 0
    finally:
        await conn.close()


async def rename_session(session_id: str, title: str) -> bool:
    conn = await get_db()
    try:
        cur = await conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title.strip(), utc_now_iso(), session_id),
        )
        await conn.commit()
        return cur.rowcount > 0
    finally:
        await conn.close()


async def list_presets() -> list[dict[str, Any]]:
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT * FROM presets ORDER BY created_at DESC")
        rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["models"] = json.loads(d.pop("models_json") or "[]")
            out.append(d)
        return out
    finally:
        await conn.close()


async def create_preset(
    *,
    name: str,
    mode: str,
    models: list[str],
    chairman_model: Optional[str],
    shared_constraints: Optional[str],
) -> dict[str, Any]:
    preset_id = str(uuid.uuid4())
    now = utc_now_iso()
    conn = await get_db()
    try:
        await conn.execute(
            """
            INSERT INTO presets (id, name, mode, models_json, chairman_model, shared_constraints, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preset_id,
                name.strip(),
                mode,
                json.dumps(models),
                chairman_model or "auto",
                shared_constraints,
                now,
            ),
        )
        await conn.commit()
        return {
            "id": preset_id,
            "name": name.strip(),
            "mode": mode,
            "models": models,
            "chairman_model": chairman_model or "auto",
            "shared_constraints": shared_constraints,
            "created_at": now,
        }
    finally:
        await conn.close()


async def delete_preset(preset_id: str) -> bool:
    conn = await get_db()
    try:
        cur = await conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        await conn.commit()
        return cur.rowcount > 0
    finally:
        await conn.close()
