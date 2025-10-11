import asyncio
import logging

from app.bot import create_bot, create_dispatcher
from app.config import Config


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the bot"""
    try:
        # Load configuration
        config = Config.from_env()
        logger.info("Configuration loaded successfully")

        # Create bot and dispatcher
        bot = create_bot(config)
        dp = create_dispatcher(config)

        logger.info("Bot started. Press Ctrl+C to stop.")

        # Start polling
        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
