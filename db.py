import aiosqlite
from typing import List, Dict, Optional
from config import Config

DB_PATH = Config.DATABASE_URL.replace("sqlite:///", "")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                string TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS approved (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

# ---------- SESSIONS ----------
async def add_session(name: str, string: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO sessions (name, string) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET string=excluded.string",
            (name, string)
        )
        await db.commit()
        return cursor.lastrowid

async def get_session(name: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, string FROM sessions WHERE name = ?", (name,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"id": row[0], "name": row[1], "string": row[2]}
    return None

async def get_all_sessions() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, string FROM sessions") as cursor:
            rows = await cursor.fetchall()
            return [{"id": r[0], "name": r[1], "string": r[2]} for r in rows]

async def delete_session(name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM sessions WHERE name = ?", (name,))
        await db.commit()
        return cursor.rowcount > 0

async def clear_sessions():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sessions")
        await db.commit()

async def export_sessions() -> List[Dict]:
    return await get_all_sessions()

# ---------- APPROVED USERS ----------
async def is_approved(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM approved WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def approve_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO approved (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def remove_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM approved WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_approved_users() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM approved") as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]
