import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class Config:
    """Bot configuration from environment variables"""
    bot_token: str
    max_video_duration: int = 1800  # 30 minutes in seconds
    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    admin_user_ids: list[int] = None  # Admin user IDs for /stats and notifications
    youtube_api_key: str = None  # YouTube Data API v3 key for search

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables"""
        load_dotenv()  # Load .env file

        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise ValueError("BOT_TOKEN environment variable is required")

        # Ensure data directory exists
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)

        # Get database URL from env or use default
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db")

        # Optional: admin user IDs (comma-separated)
        admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
        admin_user_ids = [int(uid.strip()) for uid in admin_ids_str.split(",") if uid.strip()] if admin_ids_str else []

        youtube_api_key = os.getenv("YOUTUBE_API_KEY", "").strip() or None

        return cls(
            bot_token=bot_token,
            database_url=database_url,
            admin_user_ids=admin_user_ids or None,
            youtube_api_key=youtube_api_key,
        )
