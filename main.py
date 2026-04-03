import asyncio
import logging

from aiogram.types import BotCommand, BotCommandScopeChat

from app.bot import create_bot, create_dispatcher
from app.config import Config
from app.database import DatabaseService


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the bot"""
    db_service = None
    try:
        # Load configuration
        config = Config.from_env()
        logger.info("Configuration loaded successfully")

        # Initialize database
        db_service = DatabaseService(config.database_url)
        await db_service.init_db()
        logger.info("Database initialized successfully")

        # Create bot and dispatcher
        bot = create_bot(config)
        dp = create_dispatcher(config, db_service)

        # Setup bot commands menu (public)
        commands = [
            BotCommand(command="start", description="Начать работу с ботом"),
        ]
        await bot.set_my_commands(commands)

        # Admin commands (visible only to admins)
        if config.admin_user_ids:
            admin_commands = [
                BotCommand(command="start", description="Начать работу с ботом"),
                BotCommand(command="stats", description="Статистика бота"),
                BotCommand(command="broadcast", description="Рассылка сообщений"),
            ]
            for admin_id in config.admin_user_ids:
                try:
                    await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
                except Exception as e:
                    logger.warning(f"Failed to set admin commands for {admin_id}: {e}")

        logger.info("Bot commands menu configured")

        logger.info("Bot started. Press Ctrl+C to stop.")

        # Start polling
        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise
    finally:
        # Cleanup
        if db_service:
            await db_service.close()


if __name__ == "__main__":
    asyncio.run(main())
