import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import Config
from app.handlers import router
from app.services.youtube import YouTubeService


logger = logging.getLogger(__name__)


def create_bot(config: Config) -> Bot:
    """Create and configure bot instance"""
    return Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


def create_dispatcher(config: Config) -> Dispatcher:
    """Create and configure dispatcher with handlers"""
    dp = Dispatcher()

    # Create YouTube service instance
    youtube_service = YouTubeService(
        max_duration=config.max_video_duration,
        audio_quality=config.audio_quality
    )

    # Register router with dependency injection
    router["youtube_service"] = youtube_service
    dp.include_router(router)

    return dp
