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
async def cmd_start(message: Message):
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
async def handle_message(message: Message, youtube_service: YouTubeService):
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

    try:
        # Send processing message
        status_msg = await message.answer("⏳ Проверяю видео...")

        # Check video duration
        is_valid, duration = youtube_service.check_duration(url)

        if not is_valid:
            minutes = duration // 60 if duration else 0
            await status_msg.edit_text(
                f"❌ Видео слишком длинное ({minutes} мин).\n"
                f"Максимальная длительность: 30 минут."
            )
            return

        # Download and convert
        await status_msg.edit_text("⏳ Загружаю и конвертирую видео...")
        mp3_file = youtube_service.download_and_convert(url)

        # Send MP3 file
        await status_msg.edit_text("⏳ Отправляю MP3 файл...")

        audio_file = FSInputFile(mp3_file)
        await message.answer_audio(
            audio=audio_file,
            caption="✅ Готово! Вот твой MP3 файл."
        )

        # Cleanup
        youtube_service.cleanup_file(mp3_file)
        await status_msg.delete()

        logger.info(f"Successfully processed video for user {message.from_user.id}")

    except Exception as e:
        logger.error(f"Error processing video: {e}")
        await message.answer(
            "❌ Произошла ошибка при обработке видео.\n"
            "Пожалуйста, попробуй другую ссылку или повтори попытку позже."
        )
