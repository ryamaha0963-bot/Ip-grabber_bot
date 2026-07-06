import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID", 0))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    OWNER_ID = int(os.getenv("OWNER_ID", 0))
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")
    WEB_PORT = int(os.getenv("PORT", 8080))  # Railway uses PORT

    @classmethod
    def validate(cls):
        if not all([cls.API_ID, cls.API_HASH, cls.BOT_TOKEN, cls.OWNER_ID]):
            raise ValueError("Missing required environment variables")
