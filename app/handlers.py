import asyncio
import logging
import re
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

from app.services.youtube import YouTubeService


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


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle /start command"""
    welcome_text = (
        "👋 Привет! Я бот для конвертации YouTube видео в MP3.\n\n"
        "📝 Как использовать:\n"
        "Просто отправь мне ссылку на YouTube видео, и я конвертирую его в MP3.\n\n"
        "⚠️ Ограничения:\n"
        "• Максимальная длительность видео: 30 минут\n"
        "• Качество аудио: 320 kbps\n"
        "• Только одиночные видео (плейлисты не поддерживаются)\n\n"
        "Отправь ссылку, чтобы начать!"
    )
    await message.answer(welcome_text)


@router.message(F.text)
async def handle_message(message: Message, youtube_service: YouTubeService) -> None:
    """Handle text messages with YouTube URLs"""
    if not message.text:
        return

    # Check if message contains YouTube URL
    if not is_youtube_url(message.text):
        await message.answer(
            "❌ Пожалуйста, отправь корректную ссылку на YouTube видео."
        )
        return

    url = message.text.strip()
    mp3_file = None

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

        # Download and convert
        await status_msg.edit_text("⏳ Загружаю и конвертирую видео...")
        mp3_file = youtube_service.download_and_convert(url)

        # Check file size (Telegram limit is 50MB)
        file_size = mp3_file.stat().st_size
        max_size = 50 * 1024 * 1024  # 50MB in bytes

        if file_size > max_size:
            await status_msg.edit_text(
                f"❌ MP3 файл слишком большой ({file_size / (1024 * 1024):.1f} MB).\n"
                f"Максимальный размер: 50 MB."
            )
            return

        # Send MP3 file
        await status_msg.edit_text("⏳ Отправляю MP3 файл...")

        audio_file = FSInputFile(mp3_file)
        await message.answer_audio(
            audio=audio_file,
            caption="✅ Готово! Вот твой MP3 файл."
        )

        # Wait a bit to ensure Telegram has read the file
        await asyncio.sleep(1)

        # Try to delete status message
        try:
            await status_msg.delete()
        except Exception as e:
            logger.warning(f"Could not delete status message: {e}")

        logger.info(f"Successfully processed video for user {message.from_user.id}")

    except Exception as e:
        logger.error(f"Error processing video: {e}")
        await message.answer(
            "❌ Произошла ошибка при обработке видео.\n"
            "Пожалуйста, попробуй другую ссылку или повтори попытку позже."
        )
    finally:
        # Always cleanup the file
        if mp3_file:
            youtube_service.cleanup_file(mp3_file)
