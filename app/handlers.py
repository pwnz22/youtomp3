import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

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

# Limit concurrent downloads to prevent server overload
MAX_CONCURRENT_DOWNLOADS = 15
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# Search results cache: {message_id: [videos]}
SEARCH_RESULTS_PER_PAGE = 10
search_cache: dict[int, list[dict]] = {}


class BroadcastState(StatesGroup):
    waiting_message = State()

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
async def cmd_start(message: Message, db_service: DatabaseService, config: Config) -> None:
    """Handle /start command"""
    # Track user
    try:
        user, is_new = await db_service.upsert_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )

        # Notify admins about new user
        if is_new and config.admin_user_ids:
            if message.from_user.username:
                username = f'<a href="tg://user?id={message.from_user.id}">@{message.from_user.username}</a>'
            else:
                username = "нет"
            notify_text = (
                f"👤 <b>Новый пользователь!</b>\n\n"
                f"Имя: {message.from_user.first_name or '—'}\n"
                f"Username: {username}\n"
                f"ID: <code>{message.from_user.id}</code>"
            )
            for admin_id in config.admin_user_ids:
                try:
                    await message.bot.send_message(admin_id, notify_text)
                except Exception as e:
                    logger.error(f"Failed to send notification to admin {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Failed to track user {message.from_user.id}: {e}")

    welcome_text = (
        "👋 Привет! Я бот для скачивания аудио из YouTube.\n\n"
        "📝 Как использовать:\n"
        "• Отправь <b>ссылку</b> на YouTube видео\n"
        "• Или напиши <b>название</b> для поиска\n\n"
        "⚠️ Ограничения:\n"
        "• Максимальная длительность видео: 30 минут\n"
        "• Формат: M4A (высокое качество)\n\n"
        "Отправь ссылку или название, чтобы начать!"
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


# --- Broadcast (admin only) ---

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext, config: Config) -> None:
    """Start broadcast dialog"""
    if not config.admin_user_ids or message.from_user.id not in config.admin_user_ids:
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return

    await state.set_state(BroadcastState.waiting_message)
    await message.answer(
        "📨 Отправь сообщение для рассылки (текст, фото или видео).\n"
        "/cancel — отмена"
    )


@router.message(Command("cancel"), BroadcastState.waiting_message)
async def cmd_cancel_broadcast(message: Message, state: FSMContext) -> None:
    """Cancel broadcast"""
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@router.message(BroadcastState.waiting_message)
async def handle_broadcast_message(
    message: Message, state: FSMContext, db_service: DatabaseService
) -> None:
    """Receive broadcast message and show preview"""
    user_ids = await db_service.get_all_user_ids()

    # Store message info in FSM data
    data = {"user_count": len(user_ids)}

    if message.photo:
        data["type"] = "photo"
        data["photo_id"] = message.photo[-1].file_id
        data["caption"] = message.caption or ""
        preview = f"📷 Фото" + (f"\n{message.caption}" if message.caption else "")
    elif message.video:
        data["type"] = "video"
        data["video_id"] = message.video.file_id
        data["caption"] = message.caption or ""
        preview = f"🎬 Видео" + (f"\n{message.caption}" if message.caption else "")
    elif message.text:
        data["type"] = "text"
        data["text"] = message.text
        preview = message.text
    else:
        await message.answer("❌ Поддерживаются только текст, фото и видео.")
        return

    await state.update_data(**data)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast:confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel"),
        ]
    ])

    await message.answer(
        f"📨 <b>Превью рассылки:</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"{preview}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👥 Получателей: {len(user_ids)}",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "broadcast:confirm")
async def handle_broadcast_confirm(
    callback: CallbackQuery, state: FSMContext, db_service: DatabaseService
) -> None:
    """Send broadcast to all users"""
    data = await state.get_data()
    if not data:
        await callback.answer("Сессия истекла. Начни заново /broadcast")
        return

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    status_msg = await callback.message.answer("⏳ Рассылка началась...")

    user_ids = await db_service.get_all_user_ids()
    sent = 0
    errors = 0
    msg_type = data.get("type")

    for user_id in user_ids:
        try:
            if msg_type == "text":
                await callback.bot.send_message(user_id, data["text"])
            elif msg_type == "photo":
                await callback.bot.send_photo(user_id, data["photo_id"], caption=data.get("caption"))
            elif msg_type == "video":
                await callback.bot.send_video(user_id, data["video_id"], caption=data.get("caption"))
            sent += 1
        except Exception:
            errors += 1

        await asyncio.sleep(0.05)

    await state.clear()
    await status_msg.edit_text(
        f"✅ Рассылка завершена: {sent}/{len(user_ids)} доставлено"
        + (f", {errors} ошибок" if errors else "")
    )


@router.callback_query(F.data == "broadcast:cancel")
async def handle_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel broadcast"""
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("❌ Рассылка отменена.", reply_markup=None)


def build_search_keyboard(videos: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """Build inline keyboard for search results page"""
    start = page * SEARCH_RESULTS_PER_PAGE
    end = start + SEARCH_RESULTS_PER_PAGE
    page_videos = videos[start:end]
    total_pages = (len(videos) + SEARCH_RESULTS_PER_PAGE - 1) // SEARCH_RESULTS_PER_PAGE

    buttons = []
    for v in page_videos:
        dur = format_duration(v['duration']) if v['duration'] else "?"
        title = v['title'][:45] + "..." if len(v['title']) > 45 else v['title']
        buttons.append([
            InlineKeyboardButton(
                text=f"🎵 {title} [{dur}]",
                callback_data=f"dl:{v['id']}"
            )
        ])

    # Navigation buttons
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"page:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"page:{page + 1}"))
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def handle_search(message: Message, youtube_service: YouTubeService) -> None:
    """Search YouTube and show results as inline buttons with pagination"""
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("❌ Слишком короткий запрос. Введи название видео.")
        return

    status_msg = await message.answer("🔍 Ищу видео...")

    try:
        videos = youtube_service.search(query, max_results=30)

        if not videos:
            await status_msg.edit_text("❌ Ничего не найдено. Попробуй другой запрос.")
            return

        # Cache results for pagination
        keyboard = build_search_keyboard(videos, page=0)
        result = await status_msg.edit_text(
            f"🔍 Результаты по запросу: <b>{query}</b>",
            reply_markup=keyboard
        )
        search_cache[result.message_id] = videos

    except Exception as e:
        logger.error(f"Search error for user {message.from_user.id}: {e}")
        await status_msg.edit_text("❌ Ошибка при поиске. Попробуй позже.")


@router.callback_query(F.data.startswith("page:"))
async def handle_page_callback(callback: CallbackQuery) -> None:
    """Handle pagination buttons"""
    page = int(callback.data.split(":", 1)[1])
    msg_id = callback.message.message_id
    videos = search_cache.get(msg_id)

    if not videos:
        await callback.answer("Результаты устарели. Повтори поиск.")
        return

    keyboard = build_search_keyboard(videos, page=page)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def handle_noop_callback(callback: CallbackQuery) -> None:
    """Handle page counter button (no action)"""
    await callback.answer()


@router.callback_query(F.data.startswith("dl:"))
async def handle_download_callback(
    callback: CallbackQuery,
    youtube_service: YouTubeService,
    db_service: DatabaseService,
) -> None:
    """Handle video selection from search results"""
    video_id = callback.data.split(":", 1)[1]
    url = f"https://www.youtube.com/watch?v={video_id}"
    await callback.answer()

    # Cleanup search cache
    search_cache.pop(callback.message.message_id, None)

    # Edit the search results message to show progress (edit_text removes reply_markup)
    status_msg = callback.message
    await status_msg.edit_text("⏳ Проверяю видео...", reply_markup=None)

    audio_file_path = None

    try:
        if download_semaphore.locked():
            await status_msg.edit_text("⏳ Очередь загрузки... Подожди немного.")

        await download_semaphore.acquire()

        is_valid, duration = youtube_service.check_duration(url)

        if not is_valid:
            if duration:
                minutes = duration // 60
                await status_msg.edit_text(
                    f"❌ Видео слишком длинное ({minutes} мин). Максимум: 30 минут."
                )
            else:
                await status_msg.edit_text("❌ Не удалось определить длительность видео.")
            return

        await status_msg.edit_text("⏳ Загружаю аудио...")
        audio_file_path, video_title, audio_duration = youtube_service.download_and_convert(url)

        file_size = audio_file_path.stat().st_size
        if file_size > 50 * 1024 * 1024:
            await status_msg.edit_text(
                f"❌ Файл слишком большой ({file_size / (1024 * 1024):.1f} MB). Максимум: 50 MB."
            )
            return

        await status_msg.edit_text("⏳ Отправляю аудио...")

        file_ext = audio_file_path.suffix
        audio_file = FSInputFile(audio_file_path, filename=f"{video_title}{file_ext}")
        await callback.message.answer_audio(
            audio=audio_file,
            title=video_title,
            duration=audio_duration,
        )

        try:
            await db_service.add_download(
                user_id=callback.from_user.id,
                url=url,
                title=video_title,
                file_size=file_size,
                duration=audio_duration,
            )
        except Exception as e:
            logger.error(f"Failed to track download: {e}")

        await asyncio.sleep(1)
        try:
            await status_msg.delete()
        except Exception:
            pass

        logger.info(f"Search download complete for user {callback.from_user.id}: {video_title}")

    except (VideoUnavailableError, VideoRestrictedError, VideoDownloadError, YouTubeServiceError) as e:
        logger.warning(f"Download error from search for user {callback.from_user.id}: {e}")
        await status_msg.edit_text(f"❌ {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error from search for user {callback.from_user.id}: {e}")
        await status_msg.edit_text("❌ Произошла ошибка. Попробуй позже.")
    finally:
        download_semaphore.release()
        if audio_file_path:
            youtube_service.cleanup_file(audio_file_path)


def format_duration(seconds: int) -> str:
    """Format seconds to MM:SS"""
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


@router.message(F.text)
async def handle_message(message: Message, youtube_service: YouTubeService, db_service: DatabaseService) -> None:
    """Handle text messages - YouTube URLs or search queries"""
    if not message.text:
        return

    # If not a YouTube URL - treat as search query
    if not is_youtube_url(message.text):
        await handle_search(message, youtube_service)
        return

    # Clean URL from playlist and extra parameters
    url = clean_youtube_url(message.text.strip())
    logger.info(f"Cleaned URL: {url}")
    audio_file_path = None

    try:
        # Send processing message
        status_msg = await message.answer("⏳ Проверяю видео...")

        # Wait for available slot
        if download_semaphore.locked():
            await status_msg.edit_text("⏳ Очередь загрузки... Подожди немного.")

        await download_semaphore.acquire()

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
        download_semaphore.release()
        # Always cleanup the file
        if audio_file_path:
            youtube_service.cleanup_file(audio_file_path)
