import asyncio
import logging
import threading
from pyrogram import Client
from config import Config
from db import init_db, get_all_sessions
from session_manager import SessionManager
from handlers import Handlers
from web import start_web

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def main():
    # Validate config
    Config.validate()

    # Init DB
    await init_db()

    # Create bot client
    app = Client(
        "ip_grabber_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        in_memory=True,
    )

    # Session manager
    manager = SessionManager()

    # Load existing sessions from DB and start them
    sessions = await get_all_sessions()
    for s in sessions:
        await manager.start_session(s['name'], s['string'])
    logger.info(f"Loaded {len(sessions)} sessions")

    # Register handlers
    handlers = Handlers(app, manager)

    # Start bot
    await app.start()
    logger.info("Bot started")

    # Start web server in a separate thread (non‑blocking)
    threading.Thread(target=start_web, daemon=True).start()
    logger.info(f"Web server running on port {Config.WEB_PORT}")

    # Keep bot running
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
