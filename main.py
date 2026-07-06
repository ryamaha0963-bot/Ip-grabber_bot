from __future__ import annotations
import asyncio, logging, sys
from pyrogram import Client, idle
from config import Config
from attack_engine import AttackEngine
from vc_detector import VCDetector
from bot_handler import BotHandler   # <-- YEH LINE FIX

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler()])
LOGGER = logging.getLogger(__name__)

async def amain():
    cfg = Config.from_env()
    bot = Client("vc_bot", api_id=cfg.api_id, api_hash=cfg.api_hash, bot_token=cfg.bot_token)
    user = Client("vc_user", api_id=cfg.api_id, api_hash=cfg.api_hash, session_string=cfg.session_string)
    engine = AttackEngine(threads=cfg.max_threads, max_dur=cfg.max_duration, safety=False)
    await bot.start(); await user.start()
    detector = VCDetector(user, cooldown=cfg.scan_cooldown)
    handler = BotHandler(bot, detector, engine, cfg.admin_id, cfg.max_duration, cfg.scan_limit)
    LOGGER.info("✅ ONLINE – commands: /scan, /attack, /nuke, /loop, /stop, /status")
    await idle()
    engine.stop()
    await user.stop(); await bot.stop()

def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
