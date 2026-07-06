import asyncio
import logging
from pyrogram import Client, idle
from config import Config
from db import init_db, get_all_sessions
from session_manager import SessionManager
from handlers import Handlers
from web import start_web

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def main():
    Config.validate()
    await init_db()

    app = Client(
        "ip_grabber_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        in_memory=True,
    )

    manager = SessionManager()
    sessions = await get_all_sessions()
    for s in sessions:
        await manager.start_session(s['name'], s['string'])
    logger.info(f"Loaded {len(sessions)} sessions")

    handlers = Handlers(app, manager)   # registers commands

    await app.start()
    logger.info("Bot started")

    # Start web server and idle concurrently
    await asyncio.gather(
        start_web(),
        idle()  # blocks until bot stops
    )

if __name__ == "__main__":
    asyncio.run(main())
