import os
from dataclasses import dataclass


@dataclass
class Config:
    """Bot configuration from environment variables"""
    bot_token: str
    max_video_duration: int = 1800  # 30 minutes in seconds
    audio_quality: str = "320"  # kbps

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables"""
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise ValueError("BOT_TOKEN environment variable is required")

        return cls(bot_token=bot_token)
