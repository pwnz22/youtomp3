import asyncio
import logging
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.config import Config
from app.database import DatabaseService
from app.services.shazam import (
    ShazamService,
    ShazamServiceError,
    TrackNotRecognizedError,
)
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

# Telegram audio file size limit (50 MB)
MAX_AUDIO_FILE_SIZE = 50 * 1024 * 1024

# Voice message duration limit for Shazam recognition (seconds)
MAX_VOICE_DURATION = 30

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


async def download_and_send_audio(
    *,
    bot: Bot,
    chat_id: int,
    user_id: int,
    url: str,
    status_msg: Message,
    youtube_service: YouTubeService,
    db_service: DatabaseService,
) -> bool:
    """
    Shared YouTube → audio pipeline used by URL, search-result and voice handlers.

    Edits status_msg with progress and final error text. Tracks success in DB
    on Download, errors in DB.add_error. Returns True on success.
    """
    audio_file_path = None

    if download_semaphore.locked():
        try:
            await status_msg.edit_text("🕐 В очереди...")
        except Exception:
            pass

    async with download_semaphore:
        try:
            is_valid, duration = youtube_service.check_duration(url)
            if not is_valid:
                if duration:
                    minutes = duration // 60
                    await status_msg.edit_text(
                        f"❌ Трек слишком длинный ({minutes} мин).\n"
                        f"Максимум: 30 минут."
                    )
                else:
                    await status_msg.edit_text(
                        "❌ Не получилось обработать. Попробуй другой трек."
                    )
                return False

            audio_file_path, video_title, audio_duration = (
                youtube_service.download_and_convert(url)
            )

            file_size = audio_file_path.stat().st_size
            if file_size > MAX_AUDIO_FILE_SIZE:
                await status_msg.edit_text(
                    f"❌ Файл слишком большой ({file_size / (1024 * 1024):.1f} MB).\n"
                    f"Максимум: 50 MB."
                )
                return False

            await status_msg.edit_text("📤 Отправляю...")
            file_ext = audio_file_path.suffix
            audio_file = FSInputFile(audio_file_path, filename=f"{video_title}{file_ext}")
            await bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                title=video_title,
                duration=audio_duration,
            )

            try:
                await db_service.add_download(
                    user_id=user_id,
                    url=url,
                    title=video_title,
                    file_size=file_size,
                    duration=audio_duration,
                )
            except Exception as e:
                logger.error(f"Failed to track download for user {user_id}: {e}")

            logger.info(f"Successfully sent audio to user {user_id}: {video_title}")
            return True

        except (VideoUnavailableError, VideoRestrictedError, VideoDownloadError, YouTubeServiceError) as e:
            error_type = type(e).__name__
            logger.warning(f"{error_type} for user {user_id}: {e}")
            try:
                await db_service.add_error(
                    user_id=user_id,
                    url=url,
                    error_type=error_type,
                    error_message=str(e),
                )
            except Exception as db_error:
                logger.error(f"Failed to track error for user {user_id}: {db_error}")

            if isinstance(e, VideoRestrictedError):
                text = f"❌ {e}\n\n💡 Попробуйте другое видео без ограничений."
            elif isinstance(e, VideoDownloadError):
                text = (
                    f"❌ {e}\n\n"
                    "💡 Рекомендации:\n"
                    "• Попробуйте другое видео\n"
                    "• Убедитесь, что видео доступно публично\n"
                    "• Проверьте, что видео не защищено авторскими правами"
                )
            else:
                text = f"❌ {e}"

            try:
                await status_msg.edit_text(text)
            except Exception:
                await bot.send_message(chat_id, text)
            return False

        except Exception as e:
            logger.error(f"Unexpected error for user {user_id}: {e}")
            try:
                await db_service.add_error(
                    user_id=user_id,
                    url=url,
                    error_type="UnexpectedError",
                    error_message=str(e),
                )
            except Exception as db_error:
                logger.error(f"Failed to track error for user {user_id}: {db_error}")
            try:
                await status_msg.edit_text(
                    "❌ Произошла непредвиденная ошибка.\n"
                    "Пожалуйста, попробуй позже."
                )
            except Exception:
                pass
            return False

        finally:
            if audio_file_path:
                youtube_service.cleanup_file(audio_file_path)


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
        "• Или напиши <b>название</b> для поиска\n"
        "• Или запиши <b>голосовое</b> с фрагментом трека — я найду его через Shazam\n\n"
        "⚠️ Ограничения:\n"
        "• Максимальная длительность видео: 30 минут\n"
        "• Голосовое для распознавания: до 30 секунд\n"
        "• Формат: M4A (высокое качество)\n\n"
        "Отправь ссылку, название или голосовое, чтобы начать!"
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
    await status_msg.edit_text("🎵 Готовлю аудио...", reply_markup=None)

    success = await download_and_send_audio(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        url=url,
        status_msg=status_msg,
        youtube_service=youtube_service,
        db_service=db_service,
    )

    if success:
        await asyncio.sleep(1)
        try:
            await status_msg.delete()
        except Exception:
            pass


def format_duration(seconds: int) -> str:
    """Format seconds to MM:SS"""
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


@router.message(F.voice)
async def handle_voice(
    message: Message,
    youtube_service: YouTubeService,
    shazam_service: ShazamService,
    db_service: DatabaseService,
) -> None:
    """Recognize track from voice message via Shazam, then download from YouTube"""
    voice = message.voice
    if voice is None:
        return

    if (voice.duration or 0) > MAX_VOICE_DURATION:
        await message.answer(
            f"❌ Голосовое слишком длинное ({voice.duration} сек).\n"
            f"Максимум: {MAX_VOICE_DURATION} секунд."
        )
        return

    status_msg = await message.answer("🎧 Слушаю...")

    voice_path: Path | None = None
    try:
        # Download voice file from Telegram into a temporary .ogg
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            voice_path = Path(tmp.name)
        await message.bot.download(voice.file_id, destination=voice_path)

        # Reject empty/zero-byte downloads before burning a Shazam API call
        if voice_path.stat().st_size == 0:
            logger.warning(f"Empty voice file from user {message.from_user.id}")
            await status_msg.edit_text(
                "❌ Не удалось получить голосовое сообщение. Попробуй ещё раз."
            )
            return

        # Recognize via Shazam
        try:
            title, artist = await shazam_service.recognize_track(voice_path)
        except TrackNotRecognizedError:
            await status_msg.edit_text(
                "🤷 Не удалось распознать трек.\n"
                "Попробуй записать более чёткий фрагмент."
            )
            return
        except ShazamServiceError as e:
            logger.error(f"Shazam error for user {message.from_user.id}: {e}")
            await status_msg.edit_text(
                "❌ Что-то пошло не так. Попробуй позже."
            )
            return

        await status_msg.edit_text("🎵 Готовлю аудио...")

        query = f"{artist} {title}".strip() if artist else title

        # Search YouTube and pick the first result
        try:
            videos = youtube_service.search(query, max_results=1)
        except Exception as e:
            logger.error(f"YouTube search error for voice flow user {message.from_user.id}: {e}")
            await status_msg.edit_text("❌ Что-то пошло не так. Попробуй позже.")
            return

        video_id = videos[0].get("id") if videos else None
        if not video_id:
            await status_msg.edit_text(
                "🤷 Не нашёл подходящего трека.\nПопробуй другой фрагмент."
            )
            return

        url = f"https://www.youtube.com/watch?v={video_id}"

        success = await download_and_send_audio(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            url=url,
            status_msg=status_msg,
            youtube_service=youtube_service,
            db_service=db_service,
        )

        if success:
            await asyncio.sleep(1)
            try:
                await status_msg.delete()
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Unexpected voice handler error for user {message.from_user.id}: {e}")
        try:
            await status_msg.edit_text("❌ Произошла ошибка. Попробуй позже.")
        except Exception:
            pass
    finally:
        if voice_path:
            try:
                voice_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Could not delete voice file {voice_path}: {e}")


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

    status_msg = await message.answer("🎵 Готовлю аудио...")

    success = await download_and_send_audio(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        url=url,
        status_msg=status_msg,
        youtube_service=youtube_service,
        db_service=db_service,
    )

    if success:
        await asyncio.sleep(1)
        try:
            await status_msg.delete()
            await message.delete()
        except Exception as e:
            logger.warning(f"Could not delete messages: {e}")
