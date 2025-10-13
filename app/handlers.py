import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

from app.config import Config
from app.database import DatabaseService
from app.services.youtube import (
    YouTubeService,
    VideoUnavailableError,
    VideoRestrictedError,
    VideoDownloadError,
    YouTubeServiceError,
)


logger = logging.getLogger(__name__)
router = Router()

# YouTube URL patterns
YOUTUBE_PATTERNS = [
    r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[\w-]+',
    r'(https?://)?(www\.)?youtube\.com/watch\?.*v=[\w-]+',
]


def is_youtube_url(text: str) -> bool:
    """Check if text contains YouTube URL"""
    for pattern in YOUTUBE_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def clean_youtube_url(url: str) -> str:
    """
    Clean YouTube URL by removing playlist and extra parameters
    Extract video ID and return clean URL

    Examples:
        https://www.youtube.com/watch?v=VIDEO_ID&list=...&index=3
        -> https://www.youtube.com/watch?v=VIDEO_ID

        https://youtu.be/VIDEO_ID?list=...
        -> https://www.youtube.com/watch?v=VIDEO_ID
    """
    # Parse the URL
    parsed = urlparse(url)

    # Extract video ID
    video_id = None

    # Case 1: youtu.be/VIDEO_ID
    if 'youtu.be' in parsed.netloc:
        video_id = parsed.path.strip('/')

    # Case 2: youtube.com/watch?v=VIDEO_ID
    elif 'youtube.com' in parsed.netloc:
        query_params = parse_qs(parsed.query)
        if 'v' in query_params:
            video_id = query_params['v'][0]

    # Return clean URL with only video ID
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    # If we couldn't extract video ID, return original URL
    return url


@router.message(Command("start"))
async def cmd_start(message: Message, db_service: DatabaseService) -> None:
    """Handle /start command"""
    # Track user
    try:
        await db_service.upsert_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
    except Exception as e:
        logger.error(f"Failed to track user {message.from_user.id}: {e}")

    welcome_text = (
        "👋 Привет! Я бот для скачивания аудио из YouTube.\n\n"
        "📝 Как использовать:\n"
        "Просто отправь мне ссылку на YouTube видео, и я скачаю аудио.\n\n"
        "⚠️ Ограничения:\n"
        "• Максимальная длительность видео: 30 минут\n"
        "• Формат: M4A (высокое качество)\n"
        "• Только одиночные видео (плейлисты не поддерживаются)\n\n"
        "Отправь ссылку, чтобы начать!"
    )
    await message.answer(welcome_text)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db_service: DatabaseService, config: Config) -> None:
    """Handle /stats command (admin only)"""
    # Check if user is admin
    if not config.admin_user_ids or message.from_user.id not in config.admin_user_ids:
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return

    stats = await db_service.get_stats()

    stats_text = (
        "📊 <b>Статистика бота:</b>\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"✅ Успешных загрузок: {stats['total_downloads']}\n"
        f"📊 Всего запросов: {stats['total_requests']}\n"
    )

    await message.answer(stats_text)


@router.message(F.text)
async def handle_message(message: Message, youtube_service: YouTubeService, db_service: DatabaseService) -> None:
    """Handle text messages with YouTube URLs"""
    if not message.text:
        return

    # Check if message contains YouTube URL
    if not is_youtube_url(message.text):
        await message.answer(
            "❌ Пожалуйста, отправь корректную ссылку на YouTube видео."
        )
        return

    # Clean URL from playlist and extra parameters
    url = clean_youtube_url(message.text.strip())
    logger.info(f"Cleaned URL: {url}")
    audio_file_path = None

    try:
        # Send processing message
        status_msg = await message.answer("⏳ Проверяю видео...")

        # Check video duration
        is_valid, duration = youtube_service.check_duration(url)

        if not is_valid:
            if duration:
                minutes = duration // 60
                await status_msg.edit_text(
                    f"❌ Видео слишком длинное ({minutes} мин).\n"
                    f"Максимальная длительность: 30 минут."
                )
            else:
                await status_msg.edit_text(
                    "❌ Не удалось определить длительность видео.\n"
                    "Возможно, это прямая трансляция или премьера."
                )
            return

        # Download audio
        await status_msg.edit_text("⏳ Загружаю аудио...")
        audio_file_path, video_title, audio_duration = youtube_service.download_and_convert(url)

        # Check file size (Telegram limit is 50MB)
        file_size = audio_file_path.stat().st_size
        max_size = 50 * 1024 * 1024  # 50MB in bytes

        if file_size > max_size:
            await status_msg.edit_text(
                f"❌ Аудио файл слишком большой ({file_size / (1024 * 1024):.1f} MB).\n"
                f"Максимальный размер: 50 MB."
            )
            return

        # Send audio file
        await status_msg.edit_text("⏳ Отправляю аудио...")

        # Get file extension
        file_ext = audio_file_path.suffix
        audio_file = FSInputFile(audio_file_path, filename=f"{video_title}{file_ext}")
        await message.answer_audio(
            audio=audio_file,
            title=video_title,
            duration=audio_duration
        )

        # Track successful download
        try:
            await db_service.add_download(
                user_id=message.from_user.id,
                url=url,
                title=video_title,
                file_size=file_size,
                duration=audio_duration
            )
        except Exception as e:
            logger.error(f"Failed to track download for user {message.from_user.id}: {e}")

        # Wait a bit to ensure Telegram has read the file
        await asyncio.sleep(1)

        # Delete both messages
        try:
            await status_msg.delete()
            await message.delete()
        except Exception as e:
            logger.warning(f"Could not delete messages: {e}")

        logger.info(f"Successfully processed video for user {message.from_user.id}")

    except VideoUnavailableError as e:
        logger.warning(f"Video unavailable for user {message.from_user.id}: {e}")
        try:
            await db_service.add_error(
                user_id=message.from_user.id,
                url=url,
                error_type="VideoUnavailableError",
                error_message=str(e)
            )
        except Exception as db_error:
            logger.error(f"Failed to track error for user {message.from_user.id}: {db_error}")
        await message.answer(f"❌ {str(e)}")
    except VideoRestrictedError as e:
        logger.warning(f"Video restricted for user {message.from_user.id}: {e}")
        try:
            await db_service.add_error(
                user_id=message.from_user.id,
                url=url,
                error_type="VideoRestrictedError",
                error_message=str(e)
            )
        except Exception as db_error:
            logger.error(f"Failed to track error for user {message.from_user.id}: {db_error}")
        await message.answer(
            f"❌ {str(e)}\n\n"
            "💡 Попробуйте другое видео без ограничений."
        )
    except VideoDownloadError as e:
        logger.warning(f"Video download error for user {message.from_user.id}: {e}")
        try:
            await db_service.add_error(
                user_id=message.from_user.id,
                url=url,
                error_type="VideoDownloadError",
                error_message=str(e)
            )
        except Exception as db_error:
            logger.error(f"Failed to track error for user {message.from_user.id}: {db_error}")
        await message.answer(
            f"❌ {str(e)}\n\n"
            "💡 Рекомендации:\n"
            "• Попробуйте другое видео\n"
            "• Убедитесь, что видео доступно публично\n"
            "• Проверьте, что видео не защищено авторскими правами"
        )
    except YouTubeServiceError as e:
        logger.error(f"YouTube service error for user {message.from_user.id}: {e}")
        try:
            await db_service.add_error(
                user_id=message.from_user.id,
                url=url,
                error_type="YouTubeServiceError",
                error_message=str(e)
            )
        except Exception as db_error:
            logger.error(f"Failed to track error for user {message.from_user.id}: {db_error}")
        await message.answer(f"❌ {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error processing video for user {message.from_user.id}: {e}")
        try:
            await db_service.add_error(
                user_id=message.from_user.id,
                url=url,
                error_type="UnexpectedError",
                error_message=str(e)
            )
        except Exception as db_error:
            logger.error(f"Failed to track error for user {message.from_user.id}: {db_error}")
        await message.answer(
            "❌ Произошла непредвиденная ошибка.\n"
            "Пожалуйста, попробуй другую ссылку или повтори попытку позже."
        )
    finally:
        # Always cleanup the file
        if audio_file_path:
            youtube_service.cleanup_file(audio_file_path)
