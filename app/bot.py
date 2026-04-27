import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import Config
from app.database import DatabaseService
from app.handlers import router
from app.services.shazam import ShazamService
from app.services.youtube import YouTubeService


logger = logging.getLogger(__name__)


def create_bot(config: Config) -> Bot:
    """Create and configure bot instance"""
    return Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


def create_dispatcher(config: Config, db_service: DatabaseService) -> Dispatcher:
    """Create and configure dispatcher with handlers"""
    dp = Dispatcher()

    # Create YouTube service instance
    youtube_service = YouTubeService(
        max_duration=config.max_video_duration,
        api_key=config.youtube_api_key,
    )

    # Create Shazam service instance
    shazam_service = ShazamService()

    # Pass dependencies via workflow_data
    dp.workflow_data.update({
        "youtube_service": youtube_service,
        "shazam_service": shazam_service,
        "db_service": db_service,
        "config": config,
    })
    dp.include_router(router)

    return dp
